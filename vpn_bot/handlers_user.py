import asyncio
from datetime import timedelta
import logging

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ContentType, InlineKeyboardButton, InlineKeyboardMarkup

from .config import ADMIN_IDS, BOT_TOKEN
from .database import FreeTestConfig, User, get_db, init_db
from .helpers import *
from .keyboards import *
from .utils import _generate_qr_image, get_panel, setup_emoji_converter

logging.basicConfig(level=logging.INFO)
# bot = Bot(token=BOT_TOKEN,session=AiohttpSession(proxy="socks5://127.0.0.1:10808"))
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
setup_emoji_converter(bot)

async def safe_edit(callback, text, reply_markup=None):
    msg = callback.message

    try:
        # media messages -> caption
        if (
            msg.photo
            or msg.video
            or msg.document
            or msg.animation
            or msg.audio
            or msg.voice
        ):
            await msg.edit_caption(
                caption=text,
                reply_markup=reply_markup
            )

        # text messages
        else:
            await msg.edit_text(
                text=text,
                reply_markup=reply_markup
            )

    except Exception as e:
        if "message is not modified" in str(e).lower():
            return

        raise

def btn(text, cb):
    return ikbe(text=text, callback_data=cb)

def _wallet_display(wallet_text, balance):
    """Replace {balance} placeholder if present; otherwise append balance on new line."""
    b = f"{balance:,}"
    if '{balance}' in wallet_text:
        return wallet_text.replace('{balance}', b)
    return f"{wallet_text}\n{b} تومان"

class Form(StatesGroup):
    waiting_receipt = State()
    waiting_support = State()
    waiting_config_data = State()
    waiting_plan_name = State()
    waiting_plan_volume = State()
    waiting_plan_duration = State()
    waiting_plan_price = State()
    waiting_plan_devices = State()
    waiting_broadcast = State()
    waiting_charge_id = State()
    waiting_charge_amount = State()
    waiting_setting_value = State()
    waiting_ticket_reply = State()
    waiting_test_config_name = State()
    waiting_test_config_data = State()
    waiting_test_config_desc = State()
    waiting_admin_id = State()
    waiting_admin_role = State()
    waiting_plan_category = State()
    waiting_charge_receipt = State()
    waiting_shutdown_msg = State()
    # states جدید
    waiting_edit_wallet = State()
    waiting_edit_service_config = State()
    waiting_guide_text = State()
    waiting_reply_config = State()
    waiting_for_custom_amount = State()
    # states ارسال پیام به کانال با دکمه پلن
    waiting_channel_username = State()
    waiting_channel_post_text = State()
    waiting_mandatory_channel_username = State()

    waiting_invite_channel_username = State()
    waiting_invite_post_text = State()
    waiting_invite_button_name = State()
    waiting_invite_start_param = State()


    waiting_cat_base_gig = State()
    waiting_cat_base_day = State()
    waiting_cat_min_gig = State()
    waiting_cat_min_day = State()
    waiting_button_text_value = State()

    waiting_cat_groups = State()
    waiting_cat_token = State()
    waiting_cat_host = State()


def _shutdown():
    try:
        from .handlers_admin import BOT_SHUTDOWN
        return BOT_SHUTDOWN
    except:
        return False

async def _check_shutdown_msg(message: types.Message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    admins = ADMIN_IDS + get_all_admins()
    # چک بن
    if user_id not in admins:
        conn = get_db()
        row = conn.execute("SELECT is_banned FROM users WHERE telegram_id=?", (user_id,)).fetchone()
        conn.close()
        if row and row['is_banned']:
            await message.answer("⛔ حساب شما توسط مدیریت مسدود شده است.\nبرای اطلاعات بیشتر با پشتیبانی تماس بگیرید.")
            return True
    # چک shutdown
    if _shutdown():
        if user_id not in admins:
            try:
                with open('/tmp/bot_shutdown.txt', 'r', encoding='utf-8') as f:
                    msg = f.read()
            except:
                msg = "ربات در حال حاضر در دسترس نیست"
            await message.answer(f"⚠️ {msg}", reply_markup=ikb_with_color_edit([[btn("🔄 بررسی وضعیت", "check_bot_status")]], user_id=message.from_user.id))
            return True
    return False

async def _check_shutdown_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    admins = ADMIN_IDS + get_all_admins()
    # چک بن
    if user_id not in admins:
        conn = get_db()
        row = conn.execute("SELECT is_banned FROM users WHERE telegram_id=?", (user_id,)).fetchone()
        conn.close()
        if row and row['is_banned']:
            await callback.answer("⛔ حساب شما مسدود شده است.", show_alert=True)
            return True
    # چک shutdown
    if _shutdown():
        if user_id not in admins:
            try:
                with open('/tmp/bot_shutdown.txt', 'r', encoding='utf-8') as f:
                    msg = f.read()
                await callback.answer(f"⚠️ {msg}", show_alert=True)
            except:
                await callback.answer("⚠️ ربات در حال حاضر خاموش است", show_alert=True)
            return True
    return False

# ── /start ────────────────────────────────────

@dp.callback_query(F.data == "check_mandatory_join")
async def check_mandatory_join_cb(callback: types.CallbackQuery, state: FSMContext):
    missing = await get_missing_mandatory_channels(bot, callback.from_user.id)
    if missing:
        await callback.answer("هنوز در کانال ما عضو نشدید ❗️", show_alert=True)
        await edit_mandatory_join_message(callback.message, missing)
        return

    await callback.message.edit_text("✅ عضویت تأیید شد!")

    data = await state.get_data()
    pending_param = data.pop("pending_start_param", None)
    await state.set_data(data)

    # Build a lightweight proxy so cmd_start gets a real from_user
    class _MsgProxy:
        def __init__(self, msg, user):
            self._msg = msg
            self.from_user = user
            self.text = f"/start {pending_param}" if pending_param else "/start"
            self.chat = msg.chat

        def __getattr__(self, name):
            return getattr(self._msg, name)

    proxy = _MsgProxy(callback.message, callback.from_user)
    await cmd_start(proxy, state, start_param=pending_param)


@dp.message(CommandStart())
@require_mandatory_join
async def cmd_start(message: types.Message, state: FSMContext, start_param: str = None):
    if await _check_shutdown_msg(message): return

    # Use injected param (from post-join replay) or parse from message text
    args = message.text.split() if not start_param else ["/start", start_param]
    print(args)
    referred_by = None
    pays_bonus = 0
    if len(args) > 1:
        if args[1].startswith("ref_"):
            try:
                referred_by = int(args[1].replace("ref_", ""))
                pays_bonus = 1
                if referred_by == message.from_user.id:
                    referred_by = None
                    pays_bonus = 0
            except:
                pass
        if args[1].startswith("reft_"):
            try:
                referred_by = int(args[1].replace("reft_", ""))
                if referred_by == message.from_user.id:
                    referred_by = None
            except:
                pass

    user, exists = User.get_or_create(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
        referred_by,
        pays_bonus=pays_bonus
    )

    if not exists and referred_by and pays_bonus:
        amount = int(Setting.get("referral_bonus") or "0")
        charge_wallet(referred_by, amount, "هدیه دعوت")
        text = Setting.get("msg_bonus").format(amount=amount)
        await bot.send_message(referred_by, text)

    if user.is_banned:
        await message.answer("⛔ حساب شما توسط مدیریت مسدود شده است.\nبرای اطلاعات بیشتر با پشتیبانی تماس بگیرید.")
        return

    # deep link پلن — مستقیم بره صفحه پلن و روش پرداخت
    if len(args) > 1 and args[1].startswith("plan_"):
        try:
            plan_id = int(args[1].replace("plan_", ""))
            plan = get_plan(plan_id)
            if plan and plan.get('is_active'):
                volume_display = "نامحدود 📊" if plan['volume_gb'] == -1 else f"{plan['volume_gb']} گیگ"
                duration_display = "نامحدود ⏱" if plan['duration_days'] == -1 else f"{plan['duration_days']} روز"
                if plan.get('custom_description'):
                    text = plan['custom_description']
                else:
                    extra = get_setting('msg_plan_desc') or ''
                    text = (
                        f"📦 {plan['name']}\n\n"
                        f"📊 حجم: {volume_display}\n"
                        f"⏱ مدت: {duration_display}\n"
                        f"👥 تعداد کاربر: {plan['max_devices']}\n"
                        f"💰 قیمت: {plan['price']:,} تومان\n"
                        f"📁 دسته: {plan.get('category', '—')}"
                    )
                    if extra:
                        text += f"\n\n{extra}"
                is_admin = is_bot_admin(message.from_user.id, ADMIN_IDS)
                await message.answer(get_setting('welcome_text') or 'سلام! به ربات فروش VPN خوش اومدی 👋', reply_markup=main_keyboard(is_admin), parse_mode="HTML")
                await message.answer(text, reply_markup=payment_method_inline(plan_id, message.from_user.id), parse_mode="HTML")
                return
        except:
            pass

    welcome = get_setting('welcome_text') or 'سلام! به ربات فروش VPN خوش اومدی 👋'
    is_admin = is_bot_admin(message.from_user.id, ADMIN_IDS)
    await message.answer(welcome, reply_markup=main_keyboard(is_admin), parse_mode="HTML")

    if len(args) > 1 and args[1].startswith("show_free_test"):
        await free_test(message, state)
        return

    if len(args) > 1 and args[1].startswith("show_categories"):
        await buy_service(message)
        return

    if len(args) > 1 and args[1].startswith("show_tornoment"):
        from .tornoment import show_top
        await show_top(message, n=3)
        return

# ── خرید سرویس ────────────────────────────────────
from aiogram import types
from aiogram.filters import BaseFilter

from .keyboards import _btn


class DynamicTextFilter(BaseFilter):
    def __init__(self, db_key: str, db_default: str=''):
        self.db_key = db_key
        self.db_default = db_default

    async def __call__(self, message: types.Message):
        inline_keypad = kbe(text=Setting.get(self.db_key, self.db_default))
        return (message.text or "").strip() == inline_keypad.text.strip()

@dp.message(DynamicTextFilter("btn_buy", 'خرید سرویس 🛒'))
@require_mandatory_join
async def buy_service(message: types.Message):
    if await _check_shutdown_msg(message): return
    categories = get_plan_categories()
    if not categories:
        await message.answer("در حال حاضر سرویسی موجود نیست.")
        return
    if len(categories) == 1:
        plans = get_plans_by_category(categories[0])
        await message.answer(get_setting("msg_buy_intro") or "پلن مورد نظر را انتخاب کنید:", reply_markup=plans_inline(plans, categories[0], message.from_user.id))
    else:
        await message.answer(get_setting("msg_buy_intro") or "نوع سرویس را انتخاب کنید:", reply_markup=categories_inline(categories, user_id=message.from_user.id))

@dp.callback_query(F.data.startswith("category_"))
async def select_category(callback: types.CallbackQuery):
    if await _check_shutdown_cb(callback): return
    category = callback.data.replace("category_", "", 1)
    plans = get_plans_by_category(category)
    if not plans:
        await callback.answer("پلنی در این دسته موجود نیست.", show_alert=True)
        return
    await callback.message.edit_text(
        (get_setting("msg_category_header") or "📦 سرویس‌های {category}\n\nپلن مورد نظر را انتخاب کنید:").replace("{category}", category),
        reply_markup=plans_inline(plans, category, callback.from_user.id)
    )

@dp.callback_query(F.data.startswith("back_category_"))
async def back_to_category(callback: types.CallbackQuery):
    categories = get_plan_categories()
    await callback.message.edit_text(
        get_setting("msg_buy_intro") or "نوع سرویس را انتخاب کنید:",
        reply_markup=categories_inline(categories, user_id=callback.from_user.id)
    )

@dp.callback_query(F.data.startswith("plan_"))
async def show_plan(callback: types.CallbackQuery):
    if await _check_shutdown_cb(callback): return
    plan_id = int(callback.data.split("_")[1])
    plan = get_plan(plan_id)
    if not plan:
        await callback.answer("پلن یافت نشد", show_alert=True)
        return

    volume_display = "نامحدود 📊" if plan['volume_gb'] == -1 else f"{plan['volume_gb']} گیگ"
    duration_display = "نامحدود ⏱" if plan['duration_days'] == -1 else f"{plan['duration_days']} روز"
    # اگه custom_description داشت از اون استفاده کن، وگرنه پیش‌فرض
    if plan.get('custom_description'):
        text = plan['custom_description']
    else:
        extra = get_setting('msg_plan_desc') or ''
        text = (
            f"📦 {plan['name']}\n\n"
            f"📊 حجم: {volume_display}\n"
            f"⏱ مدت: {duration_display}\n"
            f"👥 تعداد کاربر: {plan['max_devices']}\n"
            f"💰 قیمت: {plan['price']:,} تومان\n"
            f"📁 دسته: {plan.get('category', '—')}"
        )
        if extra:
            text += f"\n\n{extra}"

    await callback.message.edit_text(
        text,
        reply_markup=payment_method_inline(plan_id, callback.from_user.id),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "back_plans")
async def back_to_plans(callback: types.CallbackQuery):
    categories = get_plan_categories()
    if len(categories) == 1:
        plans = get_plans_by_category(categories[0])
        await callback.message.edit_text(
            get_setting("msg_buy_intro") or "پلن مورد نظر را انتخاب کنید:",
            reply_markup=plans_inline(plans, categories[0], callback.from_user.id)
        )
    else:
        await callback.message.edit_text(
            get_setting("msg_buy_intro") or "نوع سرویس را انتخاب کنید:",
            reply_markup=categories_inline(categories, user_id=callback.from_user.id)
        )


async def _create_panel_client_with_retry(sname, recipient_id, plan, c="", panel=None):
    """Create VPN Panel client, retrying on email conflicts. Returns client, Exception, or None."""
    total_gb = plan["volume_gb"] if plan["volume_gb"] and plan["volume_gb"] > 0 else None
    expiry_days = plan["duration_days"] if plan["duration_days"] and plan["duration_days"] > 0 else None
    max_connections = plan["max_devices"] if plan["max_devices"] and plan["max_devices"] > 0 else None

    max_retries = 5
    for attempt in range(max_retries):
        suffix = f"_{attempt}" if attempt > 0 else ""
        email = sname + suffix

        try:
            logging.info(f"Creating VPN Panel client: {email} (attempt {attempt + 1}/{max_retries})")
            client = await panel.create_client(
                username=email,
                total_gb=total_gb,
                expiry_time=expiry_days,
                limit_ip=max_connections,
                note=f"# {c} - {recipient_id}",
            )
            if client:
                logging.info(f"VPN Panel client created: {email}")
                return client
            logging.warning(f"VPN Panel create_client returned falsy for {email}, retrying")
        except Exception as e:
            err = str(e).lower()
            if any(kw in err for kw in ("email already exists", "client with this email already exists", "duplicate")):
                logging.warning(f"Email conflict for {email}, retrying")
                continue
            logging.error(f"VPN Panel client creation failed: {e}")
            return e  # Critical error

    return None  # Retries exhausted



@dp.callback_query(F.data.startswith("paymethod_wallet_"))
async def pay_with_wallet(callback: types.CallbackQuery, state: FSMContext):
    if await _check_shutdown_cb(callback): return
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    plan_id = int(callback.data.split("_")[2])
    plan = get_plan(plan_id)
    user = User.get_by_telegram_id(callback.from_user.id)

    if not plan:
        await callback.answer("پلن یافت نشد", show_alert=True)
        return
    if user.balance < plan['price']:
        text = Setting.get('msg_insufficient_balance')

        diff = plan['price'] - user.balance
        await state.update_data(diff=diff)

        text = text.format(balance=f"{user.balance:,}", price=f"{plan['price']:,}", diff=diff)

        # Delete previous sticker, send new sticker+message
        # await delete_prev_sticker_and_msg(state, callback.message.chat.id)
        sent = await callback.message.answer(
            text,
            reply_markup=wallet_inline(callback.from_user.id)
        )
        return

    ok = deduct_wallet(callback.from_user.id, plan['price'], f"خرید پلن {plan['name']}")
    if not ok:
        await callback.answer("خطا در پردازش. دوباره تلاش کنید.", show_alert=True)
        return

    order_id = create_order(callback.from_user.id, plan_id, plan['price'], 'wallet')

    sname = generate_service_name()
    sname = f"{plan['volume_gb']}GB{sname}"
    try:
        panel = await get_panel(plan['category'])
        is_alive = await panel.is_alive()
    except Exception:
        is_alive = False

    is_alive = is_alive and plan["connect_to_panel"] == 1
    status, result = confirm_order(order_id, sname=sname, panel=is_alive)

    # threash_hold_referrer = int(Setting.get("threash_hold_referrer"))
    if user.referred_by:
        # Only increment buy_count on first purchase
        if not user.pays_referral:
            User.increase_buy_count(user.referred_by)
            User.set_pays_referral_true(user.telegram_id)

        # referral = User.get_by_telegram_id(user.referred_by)
        # if not referral:
        #     logging.error("couldn't find referral user")
        #     return

        # c = User.get_referral_count(user.referred_by)
        # if referral.buy_count % threash_hold_referrer == 0 and not user.pays_referral:  # When threshold is reached
        #     User.set_pays_referral_true(user.telegram_id)
        #     # Assign a free config for every threshold invite achieved
        #     config = FreeTestConfig.get()
        #     if config:
        #         FreeTestConfig.assign_to(referral.telegram_id, config.id)
        #         text = Setting.get("msg_reach_referral").format(config=config.config_data)
        #         await bot.send_message(chat_id=int(referral.telegram_id), text=text)
        #     else:
        #         add_to_free_test_queue(referral.telegram_id)
        #         queue_msg = Setting.get('msg_no_free_test')
        #         await bot.send_message(int(referral.telegram_id), queue_msg)
        #         text = (
        #             f"❗️ کاربر در صف کانفیگ رایگان قرار گرفت.\n\n"
        #             f"👤 {referral.full_name} (@{referral.username})\n"
        #             f"👤 ایدی عدد: {referral.telegram_id}\n"
        #             f"💰 تعداد دعوت: {c:,} نفر\n"
        #             f"💰 تعداد دعوت موفق: {referral.buy_count:,} نفر\n\n"
        #             f"💡 کانفیگ به محض اضافه شدن توسط شما در پنل، خودکار برای کاربر ارسال می‌شود."
        #         )
        #         await alert_admins(bot, text=text)

    markup = ikb_with_color_edit([[ikbe(text="دیدن اموزش", callback_data=f"guide_cat2_{plan['category']}")]], user_id=user.telegram_id)
    if status is True:
        config_data, category, config_id, service_id, used_service_name = result


        msg_confirm = Setting.get('msg_order_confirm')
        footer = Setting.get('msg_config_footer')
        text = f"{msg_confirm}\n\n<code>{config_data}</code>"
        if footer:
            text += f"\n\n{footer}"

        img = _generate_qr_image(config_data)
        await callback.message.delete()
        await bot.send_photo(callback.from_user.id, photo=img, reply_markup=markup,caption=text, parse_mode="HTML")

        text = (
            f"🛒 سفارش جدید (کیف پول)\n\n"
            f"👤 {callback.from_user.full_name} (@{callback.from_user.username})\n"
            f"👤 {callback.from_user.id}\n"
            f"📦 پلن: {plan['name']}\n"
            f"💰 مبلغ: {plan['price']:,} تومان\n"
            f"✅ پرداخت از کیف پول — تأیید خودکار"
        )

        channel_id = get_channel_id('receipt_order_channel_id')
        if channel_id:
            try:
                sent_msg = await bot.send_message(channel_id, text=text)
            except Exception as e:
                logging.error(f"Receipt channel error (alert admin): {e}")
                await alert_admins(bot, text=text)
        else:
            await alert_admins(bot, text=text)

        await notify_stock(plan_id, callback.from_user.id)

    elif status == "panel":
        # ⚠️ LONG PROCESS STARTS HERE
        panel_result = await _create_panel_client_with_retry(sname, callback.from_user.id, plan, c=plan["name"], panel=panel)

        if isinstance(panel_result, Exception) or panel_result is None:
            # ── ADD TO QUEUE INSTEAD OF REFUNDING ──
            error_msg = str(panel_result) if isinstance(panel_result, Exception) else "تلاش‌ها تمام شد"

            # Add to pending queue
            add_to_pending_queue(order_id, callback.from_user.id, plan_id, plan["price"])

            # ✅ اصلاح شد: آپدیت کردن استاتوس سفارش در دیتابیس از pending به queued
            with Session() as session:
                order_obj = session.query(Order).filter_by(id=order_id).first()
                if order_obj:
                    order_obj.status = "queued"
                    session.commit()

            queue_pos = get_queue_position(plan_id, order_id) or 1

            # Show queue message to user
            queue_msg = Setting.get("msg_queue_notice").replace("{pos}", str(queue_pos))
            try:
                await bot.edit_message_text(
                    queue_msg,
                    chat_id=chat_id,
                    message_id=message_id,
                )
            except Exception:
                pass

            # Alert admins
            admin_text = (
                f"⚠️ خطا در ایجاد سرویس پنل - انتقال به صف\n\n"
                f"👤 خریدار: {callback.from_user.full_name} (@{callback.from_user.username})\n"
                f"🎯 دریافت کننده: {callback.from_user.id}\n"
                f"📦 پلن: {plan['name']}\n"
                f"💰 مبلغ: {plan['price']:,} تومان\n"
                f"⏲ جایگاه در صف: {queue_pos}\n"
                f"❌ خطا: {error_msg[:100]}"
            )
            await alert_admins(bot, text=admin_text)

            await state.clear()
            return

        sub_url = panel_result.subscription_url
        config = Config.create(plan["id"], sub_url, "text")
        session = Session()
        order = session.query(Order).filter_by(id=order_id).first()
        if plan["duration_days"] == -1:
            expires = "2099-12-31T00:00:00"
        else:
            expires = (datetime.now() + timedelta(days=plan["duration_days"])).isoformat()

        session.query(Config).filter_by(id=config.id).update(
            {Config.is_used: 1, Config.assigned_to: order.user_id, Config.assigned_at: datetime.now().isoformat()}
        )

        session.query(Order).filter_by(id=order_id).update(
            {Order.status: "confirmed", Order.config_id: config.id, Order.confirmed_at: datetime.now().isoformat()}
        )

        s = Service.create(order.user_id, order.plan_id, config.id, sname, expires, plan["volume_gb"], session)
        session.commit()

        msg_confirm = Setting.get('msg_order_confirm')
        footer = Setting.get('msg_config_footer')
        text = f"{msg_confirm}\n\n<code>{sub_url}</code>"
        if footer:
            text += f"\n\n{footer}"

        img = _generate_qr_image(sub_url)
        await callback.message.delete()
        await bot.send_photo(callback.from_user.id, photo=img, reply_markup=markup, caption=text, parse_mode="HTML")

        text = (
            f"🛒 سفارش جدید \n\n"
            f"👤 {callback.from_user.full_name} (@{callback.from_user.username})\n"
            f"👤 {callback.from_user.id}\n"
            f"📦 پلن: {plan['name']}\n"
            f"💰 مبلغ: {plan['price']:,} تومان\n"
            f"✅ پرداخت و ساخت خودکار"
        )

        channel_id = get_channel_id('receipt_order_channel_id')
        if channel_id:
            try:
                sent_msg = await bot.send_message(channel_id, text=text)
            except Exception as e:
                logging.error(f"Receipt channel error (alert admin): {e}")
                await alert_admins(bot, text=text)
        else:
            await alert_admins(bot, text=text)


        await state.clear()
        return

    elif status == 'queued':
        queue_pos, *_ = result
        queue_msg = Setting.get('msg_queue_notice')
        queue_msg = queue_msg.replace('{pos}', str(queue_pos))
        await callback.message.edit_text(queue_msg)
        text = (
            f"❗️ سفارش کیف پول در صف انتظار!\n\n"
            f"👤 {callback.from_user.full_name} (@{callback.from_user.username})\n"
            f"👤 {callback.from_user.id}\n"
            f"📦 پلن: {plan['name']}\n"
            f"💰 مبلغ: {plan['price']:,} تومان\n"
            f"⏲ جایگاه در صف: {queue_pos}"
        )
        await alert_admins(bot, text=text)
    else:
        User.charge_wallet(callback.from_user.id, plan["price"], f"بازگشت وجه به دلیل خطای سیستمی - سفارش {order_id}")
        await callback.answer(f"خطا: {result}", show_alert=True)

# @dp.callback_query(F.data.startswith("paymethod_card_") | F.data.startswith("paymethod_crypto_"))
# async def pay_with_receipt(callback: types.CallbackQuery, state: FSMContext):
#     if await _check_shutdown_cb(callback): return
#     parts = callback.data.split("_")
#     method = parts[1]  # card یا crypto
#     plan_id = int(parts[2])
#     plan = get_plan(plan_id)
#     if not plan:
#         await callback.answer("پلن یافت نشد", show_alert=True)
#         return

#     await state.update_data(plan_id=plan_id, pay_method=method)
#     await state.set_state(Form.waiting_receipt)

#     if method == "card":
#         card = get_setting('card_number') or 'تنظیم نشده'
#         owner = get_setting('card_owner') or 'تنظیم نشده'
#         card_tmpl = get_setting('msg_payment_card') or (
#             "——— پرداخت کارت به کارت 💳 ———\n\n"
#             "لطفاً مبلغ زیر را به حساب واریز کنید:\n\n"
#             "💳 شماره کارت:\n<code>{card}</code>\n"
#             "👤 به نام: {owner}\n\n"
#             "💵 مبلغ واریزی: {amount} تومان\n\n"
#             "⚠️ لطفاً از حساب دیگران واریز نکنید\n\n"
#             "📸 پس از واریز، تصویر رسید را ارسال کنید:"
#         )
#         text = card_tmpl.replace('{card}', card).replace('{owner}', owner).replace('{amount}', f"{plan['price']:,}")
#     else:
#         address = get_setting('crypto_address') or 'تنظیم نشده'
#         network = get_setting('crypto_network') or 'TRX'
#         crypto_tmpl = get_setting('msg_payment_crypto') or (
#             "——— پرداخت ارز دیجیتال 🪙 ———\n\n"
#             "🌐 شبکه: {network}\n"
#             "📋 آدرس:\n<code>{address}</code>\n\n"
#             "💵 مبلغ معادل: {amount} تومان\n\n"
#             "📸 پس از انتقال، تصویر تراکنش را ارسال کنید:"
#         )
#         text = crypto_tmpl.replace('{network}', network).replace('{address}', address).replace('{amount}', f"{plan['price']:,}")

#     await callback.message.edit_text(text, parse_mode="HTML",
#                                      reply_markup=ikb_with_color_edit([[btn("❌ لغو", "cancel_order")]], user_id=callback.from_user.id))

# @dp.message(Form.waiting_receipt, F.photo | F.document)
# async def receive_receipt(message: types.Message, state: FSMContext):
#     if await _check_shutdown_msg(message): return
#     # قبول کردن هم photo هم document (عکس از گالری)
#     if message.document and not message.document.mime_type.startswith('image/'):
#         await message.answer("❌ لطفاً تصویر رسید را ارسال کنید.")
#         return
#     data = await state.get_data()
#     plan_id = data.get('plan_id')
#     method = data.get('pay_method', 'card')
#     plan = get_plan(plan_id)
#     if not plan:
#         await message.answer("خطا: پلن یافت نشد.")
#         await state.clear()
#         return

#     order_id = create_order(message.from_user.id, plan_id, plan['price'], method)
#     file_id = message.photo[-1].file_id if message.photo else message.document.file_id

#     # ذخیره file_id در order
#     conn = get_db()
#     conn.execute("UPDATE orders SET receipt_file_id=? WHERE id=?", (file_id, order_id))
#     conn.commit()
#     conn.close()

#     channel_id = get_setting('receipt_channel_id')
#     caption = (
#         f"🛒 سفارش جدید #{order_id}\n\n"
#         f"👤 {message.from_user.full_name} (@{message.from_user.username})\n"
#         f"🆔 <code>{message.from_user.id}</code>\n"
#         f"📦 پلن: {plan['name']}\n"
#         f"💰 مبلغ: {plan['price']:,} تومان\n"
#         f"💳 روش: {'کارت به کارت' if method == 'card' else 'ارز دیجیتال'}"
#     )

#     sent_msg = None
#     if channel_id:
#         try:
#             ch_id = channel_id.strip()
#             if ch_id.startswith('-'): ch_id = int(ch_id)
#             elif ch_id.isdigit(): ch_id = int(ch_id)
#             elif not ch_id.startswith('@'): ch_id = f"@{ch_id}"
#             sent_msg = await bot.send_photo(
#                 ch_id, file_id, caption=caption, parse_mode="HTML",
#                 reply_markup=ikb_with_color_edit([[
#                     btn("✅ تأیید", f"confirm_order_{order_id}"),
#                     btn("❌ رد", f"reject_order_{order_id}"),
#                 ]], user_id=message.from_user.id)
#             )
#         except Exception as e:
#             logging.error(f"Receipt channel error: {e}")

#     if sent_msg:
#         conn = get_db()
#         conn.execute("UPDATE orders SET channel_message_id=? WHERE id=?", (sent_msg.message_id, order_id))
#         conn.commit()
#         conn.close()

#     after_msg = get_setting('msg_after_receipt') or '✅ رسید شما دریافت شد.\nپس از بررسی توسط تیم ما، سرویس شما فعال خواهد شد.'
#     await message.answer(after_msg, parse_mode="HTML")
#     await state.clear()

# # ── تأیید/رد سفارش ────────────────────────────────────

# @dp.callback_query(F.data.startswith("confirm_order_"))
# async def confirm_order_cb(callback: types.CallbackQuery, state: FSMContext):
#     if not is_channel_admin(callback.from_user.id, ADMIN_IDS):
#         await callback.answer("دسترسی ندارید", show_alert=True)
#         return
#     order_id = int(callback.data.split("_")[2])
#     order = get_order(order_id)
#     if not order:
#         await callback.answer("سفارش یافت نشد", show_alert=True)
#         return

#     # ذخیره order_id برای ریپلای بعدی
#     await state.update_data(confirm_order_id=order_id, confirm_user_id=order['user_id'],
#                              confirm_plan_id=order['plan_id'])

#     # فوری caption آپدیت کن — دکمه‌های تأیید/رد حذف
#     orig_cap = callback.message.caption or callback.message.text or ""
#     confirmed_cap = orig_cap + "\n\n✅ تأیید شد"
#     try:
#         if callback.message.caption is not None:
#             await callback.message.edit_caption(caption=confirmed_cap, reply_markup=None)
#         else:
#             await callback.message.edit_text(confirmed_cap, reply_markup=None)
#     except Exception as e:
#         logging.warning(f"caption update error: {e}")

#     status, result = confirm_order(order_id)

#     if status == True:
#         config_data, _ = result
#         # کانفیگ اتوماتیک رفت — دکمه رو هم حذف کن
#         try:
#             if callback.message.caption is not None:
#                 await callback.message.edit_caption(
#                     caption=confirmed_cap + " — کانفیگ ارسال شد", reply_markup=None)
#             else:
#                 await callback.message.edit_text(
#                     confirmed_cap + " — کانفیگ ارسال شد", reply_markup=None)
#         except:
#             pass
#         msg_confirm = get_setting('msg_order_confirm') or '🎉 سفارش شما با موفقیت ثبت و تأیید شد!\n\n📋 اطلاعات سرویس خدمت شما:'
#         footer = get_setting('msg_config_footer') or ''
#         text = f"{msg_confirm}\n\n<code>{config_data}</code>"
#         if footer:
#             text += f"\n\n{footer}"
#         await bot.send_message(order['user_id'], text, parse_mode="HTML")
#         await notify_stock(order['plan_id'], None)
#         await callback.answer("✅ تأیید شد — کانفیگ ارسال شد")

#     elif status == 'queued':
#         # موجودی نداشت — دکمه ارسال کانفیگ میمونه (قبلاً ست شد)
#         plan = get_plan(order['plan_id'])
#         for admin_id in ADMIN_IDS:
#             try:
#                 await bot.send_message(
#                     admin_id,
#                     f"⚠️ سفارش #{order_id} تأیید شد ولی پلن «{plan['name']}» موجودی ندارد!\n"
#                     f"لطفاً کانفیگ رو با ریپلای روی فیش ارسال کنید."
#                 )
#             except:
#                 pass
#         await callback.answer("✅ تأیید شد")
#     else:
#         await callback.answer(f"خطا: {result}", show_alert=True)



# @dp.message(Form.waiting_reply_config)
# async def send_manual_config(message: types.Message, state: FSMContext):
#     """ارسال کانفیگ دستی از طریق ریپلای/پیام ادمین"""
#     if not is_channel_admin(message.from_user.id, ADMIN_IDS):
#         return
#     data = await state.get_data()
#     order_id = data.get('reply_order_id')
#     user_id = data.get('reply_user_id')
#     if not user_id:
#         await state.clear()
#         return

#     config_text = message.html_text.strip()
#     msg_confirm = get_setting('msg_order_confirm') or '🎉 سفارش شما با موفقیت ثبت و تأیید شد!\n\n📋 اطلاعات سرویس خدمت شما:'
#     footer = get_setting('msg_config_footer') or ''
#     text = f"{msg_confirm}\n\n<code>{config_text}</code>"
#     if footer:
#         text += f"\n\n{footer}"

#     try:
#         await bot.send_message(user_id, text, parse_mode="HTML")
#     except Exception as e:
#         await message.answer(f"❌ خطا در ارسال به کاربر: {e}")
#         await state.clear()
#         return

#     # اگر order در صف بود، از صف حذف کنیم
#     if order_id:
#         conn = get_db()
#         conn.execute(
#             "UPDATE pending_configs SET fulfilled_at=? WHERE order_id=? AND fulfilled_at IS NULL",
#             (datetime.now().isoformat(), order_id)
#         )
#         conn.execute(
#             "UPDATE orders SET status='confirmed', confirmed_at=? WHERE id=?",
#             (datetime.now().isoformat(), order_id)
#         )
#         conn.commit()
#         conn.close()

#     # آپدیت caption کانال از اطلاعات ذخیره‌شده هنگام کلیک دکمه
#     reply_ch_id = data.get('reply_ch_id')
#     reply_msg_id = data.get('reply_msg_id')
#     reply_orig_cap = data.get('reply_orig_cap', '')
#     if reply_ch_id and reply_msg_id:
#         try:
#             import re as _re
#             clean = _re.sub(r'\n\n(⏳|✅|❌)[^\n]*$', '', reply_orig_cap, flags=_re.DOTALL).strip()
#             final_cap = clean + "\n\n✅ تأیید شد — کانفیگ ارسال شد"
#             try:
#                 await bot.edit_message_caption(
#                     chat_id=reply_ch_id, message_id=reply_msg_id,
#                     caption=final_cap, reply_markup=None)
#             except:
#                 await bot.edit_message_text(
#                     chat_id=reply_ch_id, message_id=reply_msg_id,
#                     text=final_cap, reply_markup=None)
#         except Exception as e:
#             logging.warning(f"Channel caption update failed: {e}")

#     await state.clear()
#     await message.answer(f"✅ کانفیگ با موفقیت به کاربر {user_id} ارسال شد.")

# @dp.callback_query(F.data.startswith("reject_order_"))
# async def reject_order_cb(callback: types.CallbackQuery):
#     if not is_channel_admin(callback.from_user.id, ADMIN_IDS):
#         await callback.answer("دسترسی ندارید", show_alert=True)
#         return
#     order_id = int(callback.data.split("_")[2])
#     order = get_order(order_id)
#     reject_order(order_id)
#     try:
#         if callback.message.caption:
#             await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ رد شد", reply_markup=None)
#         else:
#             await callback.message.edit_text(callback.message.text + "\n\n❌ رد شد", reply_markup=None)
#     except:
#         pass
#     await bot.send_message(order['user_id'], "❌ متأسفانه رسید واریزی شما تأیید نشد.\nدرصورت بروز مشکل با پشتیبانی تماس بگیرید.")
#     await callback.answer("❌ رد شد")

# ── ریپلای ادمین روی فیش برای ارسال کانفیگ ────────────────────────────────────

@dp.message(F.reply_to_message)
async def handle_admin_reply(message: types.Message, state: FSMContext):
    # فقط پیام‌های متنی
    if not message.text:
        return

    # شناسایی فرستنده — در چنل from_user ممکنه None باشه
    sender_id = None
    if message.from_user:
        sender_id = message.from_user.id
    elif message.sender_chat:
        sender_id = message.sender_chat.id

    logging.info(f"[REPLY] sender_id={sender_id} admins={ADMIN_IDS + get_all_admins()}")

    if sender_id is None:
        return

    # چنل receipt هم مجاز است
    all_admin_ids = ADMIN_IDS + get_all_admins()
    receipt_ch_id = None
    try:
        s = (get_channel_id("receipt_photo_channel_id") or "").strip() # NOT SURE
        if s:
            receipt_ch_id = int(s.lstrip("@").replace("-100", "-100") if not s.lstrip("-").isdigit() else s)
    except:
        pass

    is_ok = (sender_id in all_admin_ids) or (receipt_ch_id and abs(sender_id) == abs(receipt_ch_id))
    if not is_ok:
        logging.info(f"[REPLY] sender {sender_id} not admin, skip")
        return

    if await _check_shutdown_msg(message): return

    current_state = await state.get_state()
    logging.info(f"[REPLY] current_state={current_state}")

    # اگه هر state دیگه‌ای فعاله (مثل waiting_setting_value) — دست نزن
    if current_state is not None:
        return

    orig = message.reply_to_message
    # متن پیام اصلی — هم text هم caption (عکس فیش)
    orig_text = orig.caption or orig.text or ""
    orig_type = "caption" if orig.caption else "text" if orig.text else "empty"
    logging.info(f"[REPLY] orig_type={orig_type} | text={repr(orig_text[:100])}")

    # ریپلای روی تیکت
    if "🎫 تیکت #" in orig_text:
        try:
            lines = orig_text.split("\n")
            ticket_id = int(lines[0].replace("🎫 تیکت #", "").strip())
            conn = get_db()
            ticket = conn.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
            conn.close()
            if not ticket:
                return
            user_id = ticket['user_id']
            reply_id = add_support_reply(ticket_id, message.html_text, message.from_user.id)
            await bot.send_message(user_id, f"📬 پاسخ پشتیبانی:\n\n{message.html_text}")
            mark_reply_as_sent(reply_id, user_id)
            close_support_ticket(ticket_id)
            await message.reply("✅ پاسخ ارسال شد.")
        except Exception as e:
            logging.error(f"Ticket reply error: {e}")
        return

    # حالت ۱: ریپلای روی پیام هشدار ادمین "❗️ سفارش #X تأیید شد ولی..."
    # استخراج order_id از متن هشدار
    warning_match = re.search(r'سفارش #(\d+) تأیید شد', orig_text)
    if warning_match:
        order_id = int(warning_match.group(1))
        order = get_order(order_id)
        if order:
            user_id = order['user_id']
            config_text = message.html_text.strip()
            msg_confirm = Setting.get('msg_order_confirm')
            footer = Setting.get('msg_config_footer')
            send_text = f"{msg_confirm}\n\n<code>{config_text}</code>"
            if footer:
                send_text += f"\n\n{footer}"
            try:
                await bot.send_message(user_id, send_text)
                # حذف از صف انتظار
                conn = get_db()
                conn.execute("UPDATE pending_configs SET fulfilled_at=? WHERE order_id=? AND fulfilled_at IS NULL",
                    (datetime.now().isoformat(), order_id))
                conn.execute("UPDATE orders SET status='confirmed', confirmed_at=? WHERE id=?",
                    (datetime.now().isoformat(), order_id))
                conn.commit()
                conn.close()
                await message.reply(f"✅ کانفیگ ارسال شد به کاربر {user_id}")
            except Exception as e:
                await message.reply(f"❌ خطا در ارسال: {e}")
        else:
            await message.reply("❌ سفارش پیدا نشد")
        return

    # حالت ۱-ب: ریپلای روی پیام "📤 کانفیگ سرویس برای ارسال به کاربر XXXXX"
    manual_user_match = re.search(r'کانفیگ سرویس برای ارسال به کاربر (\d+)', orig_text)
    if manual_user_match:
        user_id = int(manual_user_match.group(1))
        config_text = message.html_text.strip()
        msg_confirm = Setting.get('msg_order_confirm')
        footer = Setting.get('msg_config_footer')
        text = f"{msg_confirm}\n\n<code>{config_text}</code>"
        if footer:
            text += f"\n\n{footer}"
        try:
            await bot.send_message(user_id, text)
            await message.reply(f"✅ کانفیگ با موفقیت به کاربر {user_id} ارسال شد.")
        except Exception as e:
            await message.reply(f"❌ خطا در ارسال به کاربر {user_id}: {e}")
        return

    # حالت ۲: ریپلای روی فیش سفارش (متن یا عکس با caption)
    if "سفارش جدید" not in orig_text and "🛒" not in orig_text:
        return

    # استخراج order_id
    try:
        match = re.search(r'سفارش جدید #(\d+)', orig_text)
        if not match:
            await message.reply("❌ شناسه سفارش پیدا نشد.")
            return
        order_id = int(match.group(1))
        order = get_order(order_id)
        if not order:
            await message.reply("❌ سفارش در دیتابیس پیدا نشد.")
            return
        user_id = order['user_id']
    except Exception as e:
        logging.error(f"Reply order parse error: {e}")
        return

    config_text = message.html_text.strip()
    msg_confirm = Setting.get('msg_order_confirm')
    footer = Setting.get('msg_config_footer')
    text = f"{msg_confirm}\n\n<code>{config_text}</code>"
    if footer:
        text += f"\n\n{footer}"

    try:
        await bot.send_message(user_id, text)
    except Exception as e:
        await message.reply(f"❌ خطا در ارسال به کاربر {user_id}: {e}")
        return

    # حذف از صف انتظار
    conn = get_db()
    conn.execute(
        "UPDATE pending_configs SET fulfilled_at=? WHERE order_id=? AND fulfilled_at IS NULL",
        (datetime.now().isoformat(), order_id)
    )
    conn.execute(
        "UPDATE orders SET status='confirmed', confirmed_at=? WHERE id=? AND status != 'confirmed'",
        (datetime.now().isoformat(), order_id)
    )
    conn.commit()
    conn.close()

    try:
        # caption اصلی بدون متن‌های اضافه (صف انتظار و ...) فقط اطلاعات سفارش
        import re as _re
        # حذف متن‌های اضافه‌ای که قبلاً اضافه شدن
        clean_text = _re.sub(r'\n\n(⏲|✅|❌).*$', '', orig_text, flags=_re.DOTALL).strip()
        final_caption = clean_text + "\n\n✅ تأیید شد — کانفیگ ارسال شد"
        if orig.caption is not None:
            await orig.edit_caption(caption=final_caption, reply_markup=None)
        elif orig.text is not None:
            await orig.edit_text(final_caption, reply_markup=None)
    except Exception as e:
        logging.warning(f"Could not edit original message: {e}")

    await message.reply(f"✅ کانفیگ با موفقیت به کاربر {user_id} ارسال شد.")

# ── تست رایگان ────────────────────────────────────
# @dp.message(DynamicTextFilter('btn_free_test',  'تست رایگان 🎁'))
# @require_mandatory_join
# async def free_test(message: types.Message, state: FSMContext):
#     if await _check_shutdown_msg(message): return
#     me = await bot.get_me()
#     link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
#     count = User.get_referral_count(message.from_user.id)
#     text = Setting.get("msg_free_test_intro").format(link=f"<code>{link}</code>", count=count)

#     kb = InlineKeyboardMarkup(
#         inline_keyboard=[
#             [ikbe(
#                 text="کپی لینک",
#                 copy_text=CopyTextButton(text=link),
#                 style='primary'
#             )],
#             [ikbe(
#                 text="کاربران دعوت شده",
#                 callback_data="my_referral",
#                 style='success'
#             )],
#         ],
#         )
#     await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "my_referral")
async def my_referral(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    refered_users = User.get_referral(user_id)
    # find total and pays counts for this user NOT all users
    total, pays = User.get_referred_user_count(user_id)
    # you invited total user and pays user bougt a VPN service
    buttons = []
    list = ""
    for u in refered_users:
        display_name = f"{u.full_name} - {u.telegram_id}"
        status = "خرید کرده" if getattr(u, "pays_referral", 0) == 1 else "خرید نکرده"
        list += f"\n{status} {display_name}"

    text = Setting.get("msg_my_referral_view").format(total=total, pays=pays, not_pay=total - pays, list=list)
    # Optional back button to return to previous menu
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="back_main")])

    markup = ikb_with_color_edit(buttons, user_id=callback.from_user.id)

    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)

# ── حساب کاربری ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_account',    'حساب کاربری 🖥️'))
@require_mandatory_join
async def my_account(message: types.Message):
    if await _check_shutdown_msg(message): return
    await show_account_page(message.from_user.id, message=message)

async def show_account_page(user_id, message=None, callback=None, page=0):
    user = get_user(user_id)
    services = get_user_services(user_id)
    svc_count = len(services)
    ref_count = get_user_referral_count(user_id)
    p_count = len(User.get_referral_with_pay_true(user_id))

    text = (
        f"——— حساب کاربری 🖥️ ———\n\n"
        f"🆔 آیدی عددی: <code>{user_id}</code>\n"
        f"📦 تعداد سرویس‌ها: {svc_count}\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"👥 زیرمجموعه‌ها: {ref_count} نفر\n"
        f"👥 زیرمجموعه‌های فعال: {p_count} نفر\n"
    )
    kb = my_account_inline(services, user_id, page=page)

    if message:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    elif callback:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("account_page_"))
async def account_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    await show_account_page(callback.from_user.id, callback=callback, page=page)
    await callback.answer()

@dp.callback_query(F.data == "goto_wallet")
async def goto_wallet(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    wallet_text = get_setting('msg_wallet_intro') or '——— کیف پول 💰 ———\nموجودی کیف پول شما :'
    await callback.message.edit_text(
        f"{_wallet_display(wallet_text, user['balance'])}\n\nبرای شارژ کیف پول روش پرداخت انتخاب کنید:",
        reply_markup=wallet_inline(callback.from_user.id)
    )

@dp.callback_query(F.data.startswith("srv_"))
@dp.callback_query(F.data.startswith("srv_free"))
async def service_detail(callback: types.CallbackQuery):
    service_id = int(callback.data.split("_")[-1])
    conn = get_db()
    s = conn.execute("""SELECT s.*, p.name as plan_name, p.category, c.config_data, c.password
        FROM services s JOIN plans p ON s.plan_id=p.id JOIN configs c ON s.config_id=c.id
        WHERE s.id=?""", (service_id,)).fetchone()
    conn.close()
    if not s:
        await callback.answer("سرویس یافت نشد", show_alert=True)
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
    await bot.send_photo(chat_id=callback.from_user.id, photo=img, caption=text, parse_mode="HTML", reply_markup=service_detail_inline(service_id, callback.from_user.id))
    await callback.message.delete()


@dp.callback_query(F.data.startswith("renew_"))
async def renew_service(callback: types.CallbackQuery):
    await callback.answer(
        "⚠️ در حال حاضر تمدید امکان‌پذیر نیست.\nدرصورت نیاز، لطفاً سرویس جدید خریداری کنید.",
        show_alert=True
    )

@dp.callback_query(F.data.startswith("getconfig_"))
async def get_config_cb(callback: types.CallbackQuery):
    service_id = int(callback.data.split("_")[1])
    conn = get_db()
    s = conn.execute("SELECT c.config_data, c.password FROM services s JOIN configs c ON s.config_id=c.id WHERE s.id=? AND s.user_id=?",
                     (service_id, callback.from_user.id)).fetchone()
    conn.close()
    if not s:
        await callback.answer("دسترسی ندارید", show_alert=True)
        return
    await callback.answer()
    s = dict(s)
    text = f"🔗 اطلاعات اتصال:\n<code>{s['config_data']}</code>"
    if s.get('password'):
        text += f"\n🔑 پسورد: <code>{s['password']}</code>"
    await bot.send_message(callback.from_user.id, text, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_account")
async def back_to_account(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_account_page(callback.from_user.id, callback=callback)
    await callback.answer()

# ── کیف پول ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_wallet',     'کیف پول 💰'))
@require_mandatory_join
async def wallet(message: types.Message):
    if await _check_shutdown_msg(message): return
    user = get_user(message.from_user.id)
    wallet_text = get_setting('msg_wallet_intro') or '——— کیف پول 💰 ———\nموجودی کیف پول شما :'
    await message.answer(
        f"{_wallet_display(wallet_text, user['balance'])}\n\nبرای شارژ کیف پول روش پرداخت انتخاب کنید:",
        reply_markup=wallet_inline(message.from_user.id)
    )

CHARGE_AMOUNTS = [200000, 500000, 1000000, 5000000, 10000000]

def charge_amounts_inline(method, user_id, diff=None):
    ps = get_active_plan_prices()
    ps.sort()
    buttons = []
    if diff:
        buttons.append([ikbe(text=f"{diff:,} تومان", callback_data=f"charge_amount_{method}_{diff}")])

    for i in range(0, len(ps), 3):
        row = []
        for p in ps[i:i+3]:
            row.append(ikbe(text=f"{p:,} تومان", callback_data=f"charge_amount_{method}_{p}"))
        buttons.append(row)

    buttons.append([btn("✏️ مبلغ دلخواه", f"charge_custom_{method}")])
    buttons.append([btn("🔙 بازگشت", "back_wallet")])
    return ikb_with_color_edit(buttons, user_id=user_id)

@dp.callback_query(F.data.startswith("charge_custom_"))
async def process_custom_amount_start(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    method = parts[-1]
    await state.set_state(Form.waiting_for_custom_amount)
    await state.update_data(charge_method=method)
    await callback.message.edit_text(
        get_setting("msg_wallet_charge_custom_amount") or "مبلغ دلخواه را به تومان وارد کنید:",
        reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", f"wallet_{method}")]], user_id=callback.from_user.id)
    )
    await callback.answer()

@dp.message(Form.waiting_for_custom_amount)
async def process_custom_amount_input(message: types.Message, state: FSMContext):
    if not (message.text or "x").isdigit():
        return await message.answer("❌ لطفاً فقط عدد وارد کنید:")

    amount = int(message.text)
    if amount < 1000:
        return await message.answer("❌ مبلغ وارد شده باید بیشتر از 1,000 تومان باشد.")

    data = await state.get_data()
    method = data.get('charge_method', 'card')
    await state.update_data(charge_amount=amount)
    if method == "card":
        # We pass the message here to show the invoice
        await process_payment_logic_card(message.from_user, amount, message, state=state)
    else:
        address = get_setting('crypto_address') or 'تنظیم نشده'
        network = get_setting('crypto_network') or 'TRX'
        wallet_crypto_tmpl = get_setting('msg_wallet_payment_crypto') or (
            "——— شارژ کیف پول — ارز دیجیتال 🪙 ———\n\n"
            "🌐 شبکه: {network}\n"
            "📋 آدرس:\n<code>{address}</code>\n\n"
            "💵 مبلغ معادل: {amount} تومان\n\n"
            "📸 تصویر تراکنش را ارسال کنید:"
        )
        text = wallet_crypto_tmpl.replace('{network}', network).replace('{address}', address).replace('{amount}', f"{amount:,}")

        await state.set_state(Form.waiting_charge_receipt)
        await message.answer(text, parse_mode="HTML",
                            reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", f"wallet_{method}")]], user_id=message.from_user.id))

@dp.callback_query(F.data == "back_wallet")
async def back_wallet(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    wallet_text = get_setting('msg_wallet_intro') or '——— کیف پول 💰 ———\nموجودی کیف پول شما :'
    await callback.message.edit_text(
        f"{_wallet_display(wallet_text, user['balance'])}\n\nبرای شارژ کیف پول روش پرداخت انتخاب کنید:",
        reply_markup=wallet_inline(callback.from_user.id)
    )

@dp.callback_query(F.data == "wallet_card")
async def wallet_card(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    diff = data.get("diff", 0)
    await callback.message.edit_text(
        Setting.get("msg_wallet_charge_choose_amount"),
        reply_markup=charge_amounts_inline('card', user_id=callback.from_user.id, diff=diff)
    )

@dp.callback_query(F.data == "wallet_crypto")
async def wallet_crypto(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    diff = data.get("diff", 0)
    await callback.message.edit_text(
        Setting.get("msg_wallet_charge_choose_amount"),
        reply_markup=charge_amounts_inline('crypto', user_id=callback.from_user.id, diff=diff)
    )

from aiogram.types import ContentType, CopyTextButton

from .database import Invoice, Session, Setting
from .helpers import create_invoice, get_invoice_by_id
from .webhook import check_sms


async def process_payment_logic_card(user: types.User, amount: int, message: types.Message, state: FSMContext, method: str = "card"):
    # 1. Ensure unique amount (your i + 1 logic)
    i = 1
    while Invoice.is_locked(amount + i):
        i += 1

    amount += i

    # 2. Create Invoice
    invoice_id = create_invoice(user.id, amount)

    # 3. Get Settings
    timeout = Setting.get("automatic_timeout")
    card = Setting.get('card_number')
    owner = Setting.get('card_owner')
    wallet_card_tmpl = Setting.get('msg_wallet_payment_card')
    from aiogram.types import InlineKeyboardButton
    caption = (
        f"💰 درخواست شارژ کیف پول اتوماتیک\n\n"
        f"👤 {user.full_name} (@{user.username})\n"
        f"👤 <code>{user.id}</code>\n"
        f"💳 روش: کارت\n"
        f"💵 مبلغ: {amount:,} تومان"
    )
    update_invoice(invoice_id, text=caption)

    kb_user = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="کپی شماره کارت",
                copy_text=CopyTextButton(text=card),
                style='primary', pass_this=True
            )],
            [InlineKeyboardButton(
                text="کپی مبلغ (ریال)",
                copy_text=CopyTextButton(text=str(amount * 10)),
                style='primary')
            ],
            [ikbe(text="🔙 بازگشت", callback_data=f"wallet_cancel_card_{invoice_id}",style='danger'), ikbe(text="پرداخت کردم ✅️", callback_data=f"user_confirm_send_card_to_card_{invoice_id}_{amount}", style='success')]
        ],
        # user_id=user.id,
        # default_color='primary'
    )

    text = wallet_card_tmpl.format(
        card=f"<code>{card}</code>",
        owner=owner,
        amount=f"<code>{amount:,}</code>",
        timeout=str(timeout)
    )

    # If it's a callback, we edit. If it's a new message (custom input), we send new.
    try:
        msg = await message.edit_text(text, reply_markup=kb_user)
    except:
        msg = await message.answer(text, reply_markup=kb_user)

    update_invoice(invoice_id, chat_message_id=msg.message_id)

@dp.callback_query(F.data.startswith("fallback_automatic_"))
async def fallback_automatic_card_charge(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    method = "card"
    amount = int(parts[-1])
    await state.update_data(charge_method=method, charge_amount=amount)
    await state.set_state(Form.waiting_charge_receipt)
    text = Setting.get('msg_wallet_payment_card_send_image')
    await callback.message.edit_text(text)


@dp.callback_query(F.data.startswith("wallet_cancel"))
async def wallet_cancel_by_invoice_id(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    method = parts[-2]
    invoice_id = int(parts[-1])

    if method == "card":

        obj = Invoice

        invoice = obj.reject(invoice_id)
        if invoice:
            channel_id = get_channel_id('receipt_auto_channel_id')
            if invoice.channel_message_id and invoice.channel_message_id > 0:
                try:
                    await bot.delete_message(channel_id, invoice.channel_message_id)
                except Exception as e:
                    logging.error(f"Error deleting message: {e}")

    await callback.answer("فاکتور منقضی شد.", show_alert=True)
    await state.clear()
    data = await state.get_data()
    diff = data.get("diff", 0)
    await callback.message.edit_text(
        Setting.get("msg_wallet_charge_choose_amount"),
        reply_markup=charge_amounts_inline(method, user_id=callback.from_user.id, diff=diff)
    )

@dp.callback_query(F.data.startswith("charge_amount_card_"))
async def select_charge_amount_card(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = int(parts[3])

    await process_payment_logic_card(callback.from_user, amount, callback.message, state=state)

@dp.callback_query(F.data.startswith("user_confirm_send_card_to_card_"))
async def user_confirm_send_card_to_card(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = int(parts[-1])
    invoice_id = int(parts[-2])
    ivc = get_invoice_by_id(invoice_id)
    if ivc and ivc[5] and ivc[5] > 0:
        await callback.answer("درخواست شما درحال بررسی است.", show_alert=True)
        return

    # Admin Notification
    channel_id = get_channel_id('receipt_auto_channel_id')
    caption = (
        f"💰 درخواست شارژ کیف پول اتوماتیک\n\n"
        f"👤 {callback.from_user.full_name} (@{callback.from_user.username})\n"
        f"👤 <code>{callback.from_user.id}</code>\n"
        f"💳 روش: کارت\n"
        f"💵 مبلغ: {amount:,} تومان"
    )
    if channel_id:

        try:
            msg = await bot.send_message(channel_id, caption, reply_markup=None)
            update_invoice(invoice_id, channel_message_id=msg.message_id, chat_message_id=callback.message.message_id)
        except Exception as e:
            await alert_admins(bot, text=f"error send to channel {e}")
            logging.error(f"Charge channel error (admin alert): {e}")

    await state.update_data(current_invoice_id=invoice_id)

    asyncio.create_task(check_sms(amount, bot))
    await callback.message.answer("درحال بررسی درخواست شما هستم..")


@dp.callback_query(F.data.startswith("charge_amount_crypto_"))
async def select_charge_amount_crypto(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    method = "crypto"
    amount = int(parts[3])
    await state.update_data(charge_method=method, charge_amount=amount)

    address = Setting.get('crypto_address')
    network = Setting.get('crypto_network')
    wallet_crypto_tmpl = Setting.get('msg_wallet_payment_crypto')
    text = wallet_crypto_tmpl.replace('{network}', network).replace('{address}', address).replace('{amount}', f"{amount:,}")

    await state.set_state(Form.waiting_charge_receipt)
    await callback.message.edit_text(text,
                                     reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", f"wallet_{method}")]], user_id=callback.from_user.id))

@dp.message(Form.waiting_charge_receipt, F.photo | F.document)
async def receive_charge_receipt(message: types.Message, state: FSMContext):
    if await _check_shutdown_msg(message): return
    if message.document and not message.document.mime_type.startswith('image/'):
        await message.answer("❌ لطفاً تصویر رسید را ارسال کنید.")
        return
    data = await state.get_data()
    amount = data.get('charge_amount', 0)
    method = data.get('charge_method', 'card')

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    channel_id = get_channel_id('receipt_channel_id')
    if channel_id:
        caption = (
            f"💰 درخواست شارژ کیف پول\n\n"
            f"👤 {message.from_user.full_name} (@{message.from_user.username})\n"
            f"👤 <code>{message.from_user.id}</code>\n"
            f"💳 روش: {'کارت' if method == 'card' else 'ارز دیجیتال'}\n"
            f"💵 مبلغ: {amount:,} تومان"
        )
        try:

            invoice_id = create_invoice(message.from_user.id, amount, method=method)
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"رد", callback_data=f"reject_charge_{invoice_id}", style='danger'),
                InlineKeyboardButton(text=f"تأیید", callback_data=f"confirm_charge_{invoice_id}", style='success'),
            ]])
            msg = await bot.send_photo(channel_id, file_id, caption=caption,
                                 reply_markup=kb)
            message_id = msg.message_id
            update_invoice(invoice_id, channel_message_id=message_id, text=caption)

        except Exception as e:
            logging.error(f"Charge channel error: {e}")

    await message.answer("✅ درخواست شارژ ارسال شد.\n\nمنتظر تأیید ادمین باشید.")
    await state.clear()


# NOTE: the previous duplicate `receive_charge_receipt` handler (which generated
# legacy callback_data like `confirm_charge_<user_id>_<amount>`) was removed.
# Old receipts already sitting in the channel with that legacy format are still
# supported below via a fallback lookup, so no manual cleanup is needed.


def _resolve_invoice_id_from_cb(cb_data: str, prefix: str):
    """
    Resolve an invoice from a charge-related callback_data.
    Supports both formats:
      - new:    {prefix}<invoice_id>
      - legacy (confirm): {prefix}<user_id>_<amount>
      - legacy (reject):  {prefix}<user_id>
    Returns invoice_id or None.
    """
    payload = cb_data[len(prefix):] if cb_data.startswith(prefix) else cb_data
    parts = [p for p in payload.split("_") if p != ""]
    if not parts:
        return None

    # 1) try as plain invoice_id (new format)
    try:
        candidate = int(parts[-1])
    except (ValueError, TypeError):
        return None

    s = Session()
    try:
        # is there an invoice with this id?
        obj = s.query(Invoice).filter(Invoice.id == candidate).first()
        if obj is not None:
            return obj.id

        # 2) legacy fallback: {user_id}_{amount}  ->  parts = [user_id, amount]
        if len(parts) >= 2:
            try:
                legacy_user = int(parts[-2])
                legacy_amount = int(parts[-1])
                obj = (
                    s.query(Invoice)
                    .filter(
                        Invoice.user_id == legacy_user,
                        Invoice.amount == legacy_amount,
                        Invoice.status == 'pending',
                    )
                    .order_by(Invoice.created_at.desc())
                    .first()
                )
                if obj is not None:
                    return obj.id
            except (ValueError, TypeError):
                pass

        # 3) legacy reject_charge_{user_id}  -> use latest pending invoice for that user
        try:
            legacy_user = int(parts[-1])
            obj = (
                s.query(Invoice)
                .filter(
                    Invoice.user_id == legacy_user,
                    Invoice.status == 'pending',
                )
                .order_by(Invoice.created_at.desc())
                .first()
            )
            if obj is not None:
                return obj.id
        except (ValueError, TypeError):
            pass

        return None
    finally:
        s.close()


@dp.callback_query(F.data.startswith("confirm_charge_"))
@only_admin
async def confirm_charge(callback: types.CallbackQuery):
    # ack first so the button never stays stuck in loading state
    try:
        await callback.answer()
    except Exception:
        pass

    base_caption = (callback.message.caption or callback.message.text or "")

    try:
        invoice_id = _resolve_invoice_id_from_cb(callback.data, "confirm_charge_")

        if invoice_id is None:
            try:
                await safe_edit(callback, base_caption + "\n\n❌ خطا: سفارش یافت نشد", reply_markup=None)
            except Exception:
                pass
            return

        invoice = Invoice.confirm(invoice_id)

        if invoice is False:
            try:
                await safe_edit(callback, base_caption + "\n\n⚠️ قبلاً تأیید شده", reply_markup=None)
            except Exception:
                pass
            return

        if invoice is None:
            try:
                await safe_edit(callback, base_caption + "\n\n❌ خطا: سفارش یافت نشد", reply_markup=None)
            except Exception:
                pass
            return

        # successfully confirmed
        logging.info(f"u{invoice.user_id} wallet charged with {invoice.amount}T (admin {callback.from_user.id})")
        charge_wallet(invoice.user_id, invoice.amount, "شارژ کیف پول توسط ادمین")

        try:
            await safe_edit(callback, base_caption + "\n\n✅ تأیید شد", reply_markup=None)
        except Exception as e:
            logging.error(f"confirm_charge safe_edit failed: {e}")

        # notify user
        try:
            charge_msg = Setting.get('msg_wallet_charge_confirm') or ""
            charge_msg = charge_msg.replace('{amount}', f"{invoice.amount:,}")
            if charge_msg:
                await bot.send_message(invoice.user_id, charge_msg)
        except Exception as e:
            logging.error(f"Failed to notify user {invoice.user_id}: {e}")

    except Exception as e:
        logging.exception(f"Error confirming invoice (cb={callback.data}): {e}")
        try:
            await callback.answer("❌ خطا در تأیید سفارش", show_alert=True)
        except Exception:
            pass


@dp.callback_query(F.data.startswith("reject_charge_"))
@only_admin
async def reject_charge(callback: types.CallbackQuery):
    # ack first so the button never stays stuck in loading state
    try:
        await callback.answer()
    except Exception:
        pass

    base_caption = (callback.message.caption or callback.message.text or "")

    try:
        invoice_id = _resolve_invoice_id_from_cb(callback.data, "reject_charge_")

        if invoice_id is None:
            try:
                await safe_edit(callback, base_caption + "\n\n❌ خطا: سفارش یافت نشد", reply_markup=None)
            except Exception:
                pass
            return

        invoice = reject_invoice(invoice_id)

        if not invoice:
            # already success/failed or vanished
            try:
                await safe_edit(callback, base_caption + "\n\n⚠️ این سفارش قابل رد نیست (قبلاً پردازش شده)", reply_markup=None)
            except Exception:
                pass
            return

        user_id = invoice[1]

        try:
            await safe_edit(callback, base_caption + "\n\n❌ رد شد", reply_markup=None)
        except Exception:
            pass

        try:
            await bot.send_message(
                user_id,
                "❌ توسط ادمین درخواست شارژ کیف پول رد شد.\nدرصورت بروز مشکل با پشتیبانی تماس بگیرید."
            )
        except Exception:
            pass

    except Exception as e:
        logging.exception(f"Error rejecting invoice (cb={callback.data}): {e}")
        try:
            await callback.answer("❌ خطا در رد سفارش", show_alert=True)
        except Exception:
            pass

# ── نحوه اتصال ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_connection', 'نحوه اتصال ⚙️'))
@require_mandatory_join
async def connection_guide(message: types.Message):
    if await _check_shutdown_msg(message): return
    categories = get_all_guide_categories()
    if not categories:
        # fallback: دسته‌بندی از پلن‌ها
        categories = list(set(get_plan_categories()))
    if not categories:
        await message.answer("آموزش اتصال هنوز تنظیم نشده است. با پشتیبانی تماس بگیرید.")
        return
    await message.answer(
        get_setting("msg_connection_intro") or "🔌 آموزش اتصال برای کدام نوع سرویس؟",
        reply_markup=connection_guide_categories_inline(categories, message.from_user.id)
    )


@dp.callback_query(F.data.startswith("guide_cat_"))
@dp.callback_query(F.data.startswith("guide_free_cat_"))
async def show_guide(callback: types.CallbackQuery):
    category = callback.data.split("_")[-1]
    guide = get_connection_guide(category)
    if not guide:
        await callback.answer("آموزش این دسته هنوز تنظیم نشده.", show_alert=True)
        return
    await callback.message.edit_text(
        f"📖 آموزش اتصال — {category}\n\n{guide}",
        reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "back_guide")]], user_id=callback.from_user.id)
    )

@dp.callback_query(F.data.startswith("guide_cat2_"))
async def show_guide2(callback: types.CallbackQuery):
    category = callback.data.replace("guide_cat2_", "", 1)
    guide = get_connection_guide(category)
    if not guide:
        await callback.answer("آموزش این دسته هنوز تنظیم نشده.", show_alert=True)
        return
    await callback.message.answer(
        f"📖 آموزش اتصال — {category}\n\n{guide}",
        reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "back_guide")]], user_id=callback.from_user.id)
    )

@dp.callback_query(F.data == "back_guide")
async def back_guide(callback: types.CallbackQuery):
    categories = get_all_guide_categories()
    if not categories:
        categories = list(set(get_plan_categories()))
    await callback.message.edit_text(
        get_setting("msg_connection_intro") or "🔌 آموزش اتصال برای کدام نوع سرویس؟",
        reply_markup=connection_guide_categories_inline(categories, callback.from_user.id)
    )

# ── پشتیبانی ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_support',    'پشتیبانی 👩‍💻'))
@require_mandatory_join
async def support(message: types.Message, state: FSMContext):
    if await _check_shutdown_msg(message): return
    support_text = get_setting('msg_support_intro') or (
        "اگر مشکلی در اتصال، پرداخت یا هر موضوع دیگری دارید، ادمین‌های ما آنلاین هستند 👩‍💻\n\n"
        "پیام خود را اینجا بنویسید تا سریع‌تر پاسخ دریافت کنید 🌺"
    )
    await message.answer(support_text, reply_markup=back_keyboard(), parse_mode="HTML")
    await state.set_state(Form.waiting_support)

@dp.message(Form.waiting_support)
async def send_support(message: types.Message, state: FSMContext):
    if await _check_shutdown_msg(message): return
    if message.text == "🔙 بازگشت":
        await state.clear()
        await message.answer("منوی اصلی:", reply_markup=main_keyboard(is_bot_admin(message.from_user.id, ADMIN_IDS)))
        return

    conn = get_db()
    cursor = conn.execute("INSERT INTO support_tickets (user_id, message) VALUES (?,?)",
                          (message.from_user.id, message.text))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = (
        f"🎫 تیکت #{ticket_id}\n"
        f"👤 {message.from_user.full_name} (@{message.from_user.username})\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"💬 {message.text}\n\n"
        f"📌 برای پاسخ، روی این پیام ریپلای کنید."
    )
    ticket_kb = ikb_with_color_edit([[btn(f"✅ بستن تیکت #{ticket_id}", f"close_and_send_{ticket_id}_{message.from_user.id}")]], user_id=message.from_user.id)

    conn = get_db()
    channel_admins = conn.execute(
        "SELECT telegram_id FROM admin_users WHERE is_active=1 AND role IN ('channel','both')"
    ).fetchall()
    conn.close()

    sent_count = 0
    for row in channel_admins:
        try:
            await bot.send_message(row['telegram_id'], text, parse_mode="HTML", reply_markup=ticket_kb)
            sent_count += 1
        except:
            pass

    # ارسال به سوپرادمین‌ها نیز
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=ticket_kb)
            sent_count += 1
        except:
            pass

    if sent_count == 0:
        await message.answer("❌ خطا در ارسال. لطفاً بعداً تلاش کنید.")
    else:
        await message.answer(get_setting("msg_support_sent") or "✅ پیام شما به پشتیبانی ارسال شد.")
    await state.clear()

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_channel_admin(callback.from_user.id, ADMIN_IDS):
        await callback.answer("دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    ticket_id = int(parts[2])
    user_id = int(parts[3])
    await state.update_data(ticket_id=ticket_id, user_id=user_id)
    await state.set_state(Form.waiting_ticket_reply)
    await callback.message.edit_text("پاسخ خود را بنویسید:")

@dp.message(Form.waiting_ticket_reply)
async def send_ticket_reply(message: types.Message, state: FSMContext):
    if not is_channel_admin(message.from_user.id, ADMIN_IDS):
        return
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    user_id = data.get('user_id')
    reply_id = add_support_reply(ticket_id, message.html_text, message.from_user.id)
    try:
        await bot.send_message(user_id, f"📬 پاسخ پشتیبانی:\n\n{message.html_text}", parse_mode="HTML")
        mark_reply_as_sent(reply_id, user_id)
    except:
        pass
    close_support_ticket(ticket_id)
    await state.clear()
    await message.answer("✅ پاسخ ارسال شد و تیکت بسته شد.")

@dp.callback_query(F.data.startswith("close_and_send_"))
async def close_and_send(callback: types.CallbackQuery):
    if not is_channel_admin(callback.from_user.id, ADMIN_IDS):
        await callback.answer("دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    ticket_id = int(parts[3])
    user_id = int(parts[4])
    close_support_ticket(ticket_id)
    try:
        await callback.message.edit_text(callback.message.text + "\n\n✅ بسته شد", reply_markup=None)
    except:
        pass
    try:
        await bot.send_message(user_id, f"✅ تیکت #{ticket_id} بسته شد.")
    except:
        pass
    await callback.answer("بسته شد")

# ── همکاری ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_earn',       'همکاری و کسب درآمد 💡'))
@require_mandatory_join
async def earn(message: types.Message):
    if await _check_shutdown_msg(message): return
    from .helpers import get_partner
    partner = get_partner(message.from_user.id)
    is_active = partner and partner['is_active']
    await message.answer("همکاری و کسب درآمد:", reply_markup=earn_inline(message.from_user.id, is_active_partner=is_active))

@dp.callback_query(F.data == "partner_info")
async def partner_info(callback: types.CallbackQuery):
    from .helpers import get_partner
    partner = get_partner(callback.from_user.id)
    if partner and partner['is_active']:
        from .handlers_partner import register_partner_handlers
        from .helpers import get_partner_stats
        stats = get_partner_stats(partner['id'])
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        await callback.message.edit_text(
            f"🤝 <b>پنل همکاری</b>\n\n"
            f"💰 موجودی کانفیگ: <b>{stats['balance']:,} تومان</b>\n"
            f"📦 کل سفارشات: {stats['total_orders']}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ikbe(text="💰 شارژ حساب کانفیگ", callback_data="partner_charge_config")],
                [ikbe(text="📊 تاریخچه تراکنش‌ها", callback_data="partner_transactions")],
                [ikbe(text="🔙 بازگشت", callback_data="back_earn")],
            ])
        )
        return
    fee = get_setting('partner_fee') or '10000000'
    text = (f"🤝 همکاری حرفه‌ای\n\nبا پرداخت {int(fee):,} تومان:\n\n"
            f"✅ ربات اختصاصی برای شما\n✅ مدیریت پلن‌های خودتان\n✅ شارژ حساب و دریافت کانفیگ")
    await callback.message.edit_text(text, reply_markup=partner_unlock_inline(callback.from_user.id))

@dp.callback_query(F.data == "back_earn")
async def back_earn(callback: types.CallbackQuery):
    from .helpers import get_partner
    partner = get_partner(callback.from_user.id)
    is_active = partner and partner['is_active']
    await callback.message.edit_text("همکاری و کسب درآمد:", reply_markup=earn_inline(callback.from_user.id, is_active_partner=is_active))

# ── مدیریت ────────────────────────────────────

@dp.message(DynamicTextFilter('btn_admin',      'پنل مدیریت 🛠'))
async def admin_panel_msg(message: types.Message):
    if not is_bot_admin(message.from_user.id, ADMIN_IDS):
        return
    from .keyboards import admin_main_inline
    await message.answer("پنل مدیریت:", reply_markup=admin_main_inline(message.from_user.id))

# ── بازگشت و misc ────────────────────────────────────

@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.delete()

@dp.callback_query(F.data == "cancel_order")
async def cancel_order_cb(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ سفارش لغو شد.")

@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

@dp.message(F.text == "🔙 بازگشت")
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("منوی اصلی:", reply_markup=main_keyboard(is_bot_admin(message.from_user.id, ADMIN_IDS)))

async def notify_stock(plan_id, buyer_id):
    if not plan_id:
        return
    status = check_low_stock(plan_id)
    plan = get_plan(plan_id)
    if not plan:
        return
    stock = get_config_stock(plan_id)
    for admin_id in ADMIN_IDS:
        try:
            if status == 'empty':
                await bot.send_message(admin_id, f"🔴 پلن «{plan['name']}» تمام شد!")
            elif status == 'low':
                await bot.send_message(admin_id, f"🟡 پلن «{plan['name']}» در حال اتمام! موجودی: {stock}")
        except:
            pass

# ── fallback رسانه ────────────────────────────────────

@dp.message(F.content_type.in_({ContentType.VOICE, ContentType.AUDIO, ContentType.VIDEO}))
async def handle_media(message: types.Message):
    if await _check_shutdown_msg(message): return
    await message.answer("❌ این نوع فایل در اینجا قابل استفاده نیست.")
