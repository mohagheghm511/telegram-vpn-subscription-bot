
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher, F, types
from aiogram.fsm.context import FSMContext

from vpn_bot.config import ADMIN_IDS
from vpn_bot.database import (
    Config,
    FreeTestPlan,
    FreeTestUsage,
    Order,
    Service,
    Session,
    Setting,
    User,
    get_db,
)
from vpn_bot.handlers_user import (
    DynamicTextFilter,
    _create_panel_client_with_retry,
    bot,
    _check_shutdown_msg,
)
from vpn_bot.helpers import (
    alert_admins,
    create_order,
    generate_service_name,
    get_all_admins,
    get_plan,
    is_bot_admin,
)
from vpn_bot.keyboards import (
    free_test_cta_inline,
    ikb_with_color_edit,
    service_detail_inline,
)
from vpn_bot.utils import (
    get_panel,
    _generate_qr_image,
)


def register_free_test_handlers(dp: Dispatcher):
    ############### FREE TEST ###############
    @dp.message(DynamicTextFilter("btn_free_test"))
    async def free_test(message: types.Message, state: FSMContext):
        if await _check_shutdown_msg(message): return

        user_id = message.from_user.id
        is_admin = is_bot_admin(user_id, ADMIN_IDS + get_all_admins())

        # Check if user has an active free test service - show it to them
        active_service = await FreeTestUsage.get_active_free_test_service(user_id)
        if active_service and not is_admin:
            service_id = active_service["id"]
            conn = get_db()
            s = conn.execute("""SELECT s.*, p.name as plan_name, p.category, c.config_data, c.password
                FROM services s JOIN plans p ON s.plan_id=p.id JOIN configs c ON s.config_id=c.id
                WHERE s.id=?""", (service_id,)).fetchone()
            conn.close()
            if not s:
                await message.answer("سرویس یافت نشد", show_alert=True)
                return
            s = dict(s)
            sname = s.get('service_name') or s['plan_name']
            volume_display = "نامحدود" if s['volume_gb'] == -1 else f"{s['volume_gb']} گیگ"
            expires = s['expires_at'][:10] if s.get('expires_at') else '—'
            text = (
                f"📦 سرویس: {sname}\n"
                f"📁 نوع: {s.get('category', '—')}\n"
                f"📊 حجم: {volume_display}\n"
                f"📅 انقضا: {expires}\n\n"
                f"🔗 اطلاعات اتصال:\n<code>{s['config_data']}</code>"
            )
            if s.get('password'):
                text += f"\n🔑 پسورد: <code>{s['password']}</code>"

            img = _generate_qr_image(s['config_data'])
            await bot.send_photo(chat_id=message.from_user.id, photo=img, caption=text, parse_mode="HTML", reply_markup=service_detail_inline(service_id, message.from_user.id, True))

            # text = Setting.get("msg_service_message_page_free") or "تنظیم نشده"
            return

        # Get free test plan
        free_plan = await FreeTestPlan.get_active()
        if not free_plan:
            text = Setting.get("msg_free_test_unavailable")
            kb = ikb_with_color_edit([], user_id=user_id)
            await message.reply(text=text, reply_markup=kb)
            return

        # Send a processing message that we'll edit with the result
        processing_msg = await message.answer("⏳ در حال ایجاد تست رایگان...")

        # Directly process the free test (no confirmation needed)
        await _process_free_test(user_id, is_admin, processing_msg.chat.id, processing_msg.message_id)


    async def _process_free_test(user_id: int, is_admin: bool, chat_id: int, message_id: int):
        """Process free test creation - shared logic for direct and callback triggers"""
        user = User.get_by_telegram_id(user_id)

        # Get free test plan
        free_plan = await FreeTestPlan.get_active()
        if not free_plan:
            try:
                await bot.edit_message_text(
                    "❌ تست رایگان در حال حاضر موجود نیست.", chat_id=chat_id, message_id=message_id
                )
            except Exception:
                pass
            return

        plan_id = free_plan["plan_id"]
        plan = get_plan(plan_id) or {}

        try:
            panel = await get_panel(plan["category"])
            is_alive = await panel.is_alive()
        except Exception:
            is_alive = False

        is_alive = is_alive and plan.get("connect_to_panel") == 1
        sname = generate_service_name()
        sname = f"FREE{sname}"
        try:
            if is_alive:
                # Create via X-UI
                xui_result = await _create_panel_client_with_retry(sname, user_id, free_plan, c="", panel=panel)

                if isinstance(xui_result, Exception) or xui_result is None:
                    try:
                        await bot.edit_message_text(
                            "❌ خطا در ایجاد سرویس. لطفاً بعداً تلاش کنید.", chat_id=chat_id, message_id=message_id
                        )
                    except Exception:
                        pass
                    return


                sub_url = xui_result.subscription_url
                now_str = datetime.now().isoformat()

                # 1. Create Config entry
                config = Config.create(
                    plan_id=plan_id,
                    config_data=sub_url,
                    # type="text",
                    is_used=1,
                    assigned_to=user_id,
                    assigned_at=now_str,
                )

                # Create order for tracking
                order = Order.create(
                    user_id=user_id,
                    plan_id=plan_id,
                    amount=0,
                    payment_method="free_test",
                    status="confirmed",
                    config_id=config.id,
                    confirmed_at=now_str,
                )

                if free_plan["duration_days"] == -1:
                    expires = "2099-12-31T00:00:00"
                else:
                    expires = (datetime.now() + timedelta(days=free_plan["duration_days"])).isoformat()

                # Create service
                session = Session()
                service = Service.create(user_id, plan_id, config.id, sname, expires, free_plan["volume_gb"], session)
                session.commit()
                session.close()

                # Record free test usage
                await FreeTestUsage.record_usage(user_id, service.id)

                # Send success message
                footer = Setting.get("msg_config_footer")
                text = (Setting.get("msg_free_test_success")).format(config=sub_url)
                if footer:
                    text += f"\n\n{footer}"

                kb = free_test_cta_inline(
                    service_id=service.id,
                    category=free_plan.get("category") or "",
                    user_id=user_id,
                )

                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)

                # Alert admin
                admin_text = (
                    f"🎁 تست رایگان جدید\n\n"
                    f"👤 {user.full_name} (@{user.username})\n"
                    f"👤 {user_id}\n"
                    f"📦 پلن: {free_plan['name']}\n"
                    f"🔧 سرویس: {sname}\n"
                    f"✅ ایجاد شد"
                )

            else:
                # Use config stock (old method as fallback)
                result = await Config.process_free_test(
                    user_id=user_id,
                    plan_id=plan_id,
                    category=free_plan["category"],
                    volume_gb=free_plan["volume_gb"],
                    duration_days=free_plan["duration_days"],
                    service_name_generator=generate_service_name,
                )

                if not result:
                    await bot.edit_message_text(
                        "❌ در حال حاضر تست رایگان موجود نیست. لطفاً بعداً تلاش کنید.",
                        chat_id=chat_id,
                        message_id=message_id,
                    )
                    return

                config, service_id = result

                # Record free test usage
                await FreeTestUsage.record_usage(user_id, service_id)


                # Send success message
                footer = Setting.get("msg_config_footer")
                text = (Setting.get("msg_free_test_success")).format(config=config.config_data)
                if footer:
                    text += f"\n\n{footer}"

                kb = free_test_cta_inline(
                    service_id=service_id,
                    category=free_plan.get("category") or "",
                    user_id=user_id,
                )

                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)

                # Alert admin
                admin_text = (
                    f"🎁 تست رایگان جدید\n\n"
                    f"👤 {user.full_name} (@{user.username})\n"
                    f"👤 {user_id}\n"
                    f"📦 پلن: {free_plan['name']}\n"
                    f"✅ ایجاد شد (Stock)"
                )
                await alert_admins(bot, text=admin_text)

        except Exception as e:
            logging.error(f"Free test error: {e}")
            try:
                await bot.edit_message_text(
                    "❌ خطایی رخ داد. لطفاً بعداً تلاش کنید.", chat_id=chat_id, message_id=message_id
                )
            except Exception:
                pass
