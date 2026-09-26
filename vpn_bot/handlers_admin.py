import logging
from datetime import datetime

from aiogram import Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from vpn_bot.formatting import infinit_or_real
from vpn_bot.models.free_test import FreeTestPlan

from .config import ADMIN_IDS
from .database import AsyncSessionLocal, CategorySetting, MandatoryChannel, User, get_db
from .handlers_user import Form, bot
from .helpers import *
from .keyboards import *
from .pasarguard import PGPanel
from .utils import _generate_qr_image, get_panel
from sqlalchemy import delete, select

# ── Global ────────────────────────────────────
BOT_SHUTDOWN = False

def parse_resettable_int(text: str) -> int | None | bool:
    """Returns None for reset, int for positive numbers, False for invalid input."""
    text = text.strip().lower()
    if text == "/reset":
        return None
    try:
        val = int(text)
        return val if val >= 0 else False
    except ValueError:
        return False

def parse_resettable_string(text: str) -> str | None:
    """Returns None for reset, or the stripped string."""
    text = text.strip()
    if text.lower() == "/reset":
        return None
    return text


async def process_cat_setting_input(message: types.Message, state: FSMContext, field_name: str, unit_label: str):
    """Generic handler helper for CategorySetting input updates."""
    data = await state.get_data()
    category = data.get("edit_category")
    val = parse_resettable_int(message.text)

    if val is False:
        await message.answer("لطفاً یک عدد صحیح معتبر یا /reset وارد کنید:")
        return

    if CategorySetting.set(category, **{field_name: val}):
        display = f"{val:,} {unit_label}" if val is not None else "حذف شد / بدون محدودیت"
        await state.clear()
        await message.answer(
            f"✅ تنظیمات «{category}» با موفقیت به‌روزرسانی شد:\n{display}",
            reply_markup=ikb_with_color_edit(
                [[ikbe(text="⚙️ بازگشت به تنظیمات دسته", callback_data=f"edit_cat_settings_{category}")]],
                user_id=message.from_user.id,
            ),
        )
    else:
        await message.answer("❌ خطا در به‌روزرسانی")
        await state.clear()

async def process_cat_setting_str_input(message: types.Message, state: FSMContext, field_name: str, label: str):
    """Generic handler helper for string CategorySetting input updates (host, token, group_ids)."""
    data = await state.get_data()
    category = data.get("edit_category")
    val = parse_resettable_string(message.text)

    if CategorySetting.set(category, **{field_name: val}):
        display = val if val is not None else "حذف شد / غیرفعال"
        await state.clear()
        await message.answer(
            f"✅ مقدار {label} دسته‌بندی «{category}» با موفقیت به‌روزرسانی شد:\n<code>{display}</code>",
            parse_mode="HTML",
            reply_markup=ikb_with_color_edit(
                [[ikbe(text="⚙️ بازگشت به تنظیمات دسته", callback_data=f"edit_cat_settings_{category}")]],
                user_id=message.from_user.id,
            ),
        )
    else:
        await message.answer("❌ خطا در به‌روزرسانی")
        await state.clear()


def btn(text, cb):
    return ikbe(text=text, callback_data=cb)

async def safe_edit(callback, text, reply_markup=None):
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e):
            raise

async def admin_only(callback):
    admins = ADMIN_IDS + get_all_admins()
    if callback.from_user.id not in admins:
        await callback.answer("دسترسی ندارید", show_alert=True)
        return False
    return True

async def process_waiting_queue(plan_id, triggered_by_admin_id=None):
    plan = get_plan(plan_id)
    if not plan:
        return 0
    queue = get_pending_queue_for_plan(plan_id)
    if not queue:
        return 0

    sent_count = 0
    failed_count = 0
    for item in queue:
        if get_config_stock(plan_id) == 0:
            failed_count += 1
            continue
        ok, user_id, config_result, category = fulfill_pending_queue_item(item['id'], None, plan)
        if ok:
            try:
                config_data, _ = config_result
                msg_confirm = get_setting('msg_order_confirm') or '🎉 سفارش شما با موفقیت ثبت و تأیید شد!\n\n📋 اطلاعات سرویس خدمت شما:'
                footer = get_setting('msg_config_footer') or ''
                queue_header = get_setting('msg_config_from_queue') or '🎉 اطلاعات سرویس شما آماده شد!\nممنون از صبر و شکیبایی شما 🌺'
                text = f"{queue_header}\n\n{msg_confirm}\n\n<code>{config_data}</code>"
                markup = ikb_with_color_edit([[ikbe(text=f"دیدن اموزش", callback_data=f"guide_cat2_{category}")]], user_id=user_id)

                if footer:
                    text += f"\n\n{footer}"

                img = _generate_qr_image(config_data)
                await bot.send_photo(user_id, photo=img, caption=text, reply_markup=markup, parse_mode="HTML")

                sent_count += 1
            except Exception as e:
                logging.error(f"Queue send error to {user_id}: {e}")
        else:
            failed_count += 1

    remaining = get_pending_queue_count(plan_id)
    for admin_id in ADMIN_IDS:
        try:
            volume_display = f"{plan['volume_gb']} گیگ" if plan['volume_gb'] != -1 else "نامحدود"
            plan_display = f"{plan['name']} ({volume_display})"
            if sent_count > 0:
                msg = (f"✅ صف انتظار پلن «{plan_display}» پردازش شد.\n"
                       f"📤 ارسال شد: {sent_count} کانفیگ")
                if remaining > 0:
                    msg += f"\n⏳ هنوز {remaining} نفر در صف انتظار هستند."
                if failed_count > 0:
                    msg += f"\n⚠️ ناموفق: {failed_count} نفر (موجودی کافی نیست)"
            else:
                msg = (f"⚠️ صف انتظار پلن «{plan_display}» پردازش نشد.\n"
                       f"❌ موجودی کافی نیست!")
                if remaining > 0:
                    msg += f"\n⏳ {remaining} نفر در صف انتظار هستند."
            await bot.send_message(admin_id, msg)
        except:
            pass
    return sent_count


def register_admin_handlers(dp: Dispatcher):


    @dp.callback_query(F.data == "admin_free_tests")
    @only_admin
    async def admin_free_tests_config(callback: types.CallbackQuery):


        free_plan = await FreeTestPlan.get_active()
        free_test_plan_id = await FreeTestPlan.get_plan_id()

        # Get ALL plans including price=0 so admin can see them
        plans = get_active_plans()
        if free_plan:
            v = infinit_or_real(free_plan["volume_gb"], "گیگ")
            d = infinit_or_real(free_plan["duration_days"], "روز")
            max_dev = infinit_or_real(free_plan["max_devices"], "دستگاه")
            text = (
                f"🎁 تنظیمات تست رایگان\n\n"
                f"✅ پلن فعال: {free_plan['name']}\n"
                f"📊 حجم: {v}\n"
                f"🕓 مدت: {d}\n"
                f"👥 دستگاه: {max_dev}\n"
                f"💰 قیمت: 0 تومان (رایگان)\n"
                f"⚠️ فقط یک پلن می‌تواند به عنوان تست رایگان فعال باشد."
            )

        else:
            text = (
                "🎁 تنظیمات تست رایگان\n\n"
                "❌ هیچ پلنی به عنوان تست رایگان تنظیم نشده است.\n\n"
                "از لیست زیر یک پلن را انتخاب کنید:\n"
                "⚠️ با انتخاب، قیمت پلن 0 شده و از دید کاربران مخفی می‌شود."
            )

        buttons = []
        for p in plans:
            # Check if this specific plan is the active free test plan
            is_selected = p["id"] == free_test_plan_id

            if is_selected:
                # Mark it clearly for the admin
                btn_text = f"✅ [تست رایگان] {p['name']} (رایگان - موجودی: {p['stock']})"
                btn_style = "success"
            else:
                btn_text = f"{p['name']} ({p['price']:,} تومان - موجودی: {p['stock']})"
                btn_style = None

            buttons.append([ikbe(text=btn_text, callback_data=f"set_free_test_plan_{p['id']}", style=btn_style)])

        if free_plan:
            buttons.append([ikbe(text="❌ حذف تست رایگان", callback_data="remove_free_test_plan", style="danger")])

        buttons.append([ikbe(text="🔙 بازگشت", callback_data="admin_back")])

        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("set_free_test_plan_"))
    @only_admin
    async def set_free_test_plan(callback: types.CallbackQuery):


        plan_id = int(callback.data.split("_")[-1])

        # Get plan info for confirmation
        success, info = await FreeTestPlan.set_plan(plan_id)
        if not success:
            await callback.answer("❌ پلن یافت نشد", show_alert=True)
            return

        # Show confirmation dialog
        text = f"⚠️ تایید تنظیم تست رایگان\n\n{info}\n\n❗ آیا مطمئن هستید؟"

        buttons = [
            [
                ikbe(text="✅ بله، تنظیم شود", callback_data=f"confirm_free_test_plan_{plan_id}", style="success"),
                ikbe(text="❌ انصراف", callback_data="admin_free_tests", style="danger"),
            ]
        ]

        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("confirm_free_test_plan_"))
    @only_admin
    async def confirm_free_test_plan(callback: types.CallbackQuery):


        plan_id = int(callback.data.split("_")[-1])

        if await FreeTestPlan.confirm_set_plan(plan_id):
            await callback.answer("✅ پلن تست رایگان تنظیم شد!", show_alert=False)
            # Refresh the view
            await admin_free_tests_config(callback)
        else:
            await callback.answer("❌ خطا در تنظیم پلن", show_alert=True)

    @dp.callback_query(F.data == "remove_free_test_plan")
    @only_admin
    async def remove_free_test_plan(callback: types.CallbackQuery):


        success, previous_plan_id = await FreeTestPlan.remove_plan()

        if success:
            await callback.answer("✅ تست رایگان غیرفعال شد!", show_alert=False)
            # Note: We don't restore the original price - admin should do that manually if needed
            await admin_free_tests_config(callback)
        else:
            await callback.answer("❌ خطا", show_alert=True)


    @dp.callback_query(F.data.startswith("toggle_color_edit"))
    async def toggle_color_edit_mode(callback: types.CallbackQuery, state: FSMContext):
        if not await admin_only(callback):
            return

        buttons = callback.message.reply_markup.inline_keyboard
        await callback.answer("🎨 حالت ویرایش رنگ فعال شد.\nروی هر دکمه بزنید تا رنگش تغییر کند.")
        await state.update_data(edit_mode=True)

        await safe_edit(callback, callback.message.text,
                       reply_markup=ikb_with_color_edit(buttons, edit_mode=True, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("exit_color_edit"))
    async def exit_color_edit_mode(callback: types.CallbackQuery, state: FSMContext):
        if not await admin_only(callback):
            return

        buttons = callback.message.reply_markup.inline_keyboard

        await callback.answer("🎨 حالت ویرایش رنگ غیرفعال شد.")
        await state.update_data(edit_mode=False)

        await safe_edit(callback, callback.message.text,
                       reply_markup=ikb_with_color_edit(buttons,  edit_mode=False, user_id=callback.from_user.id))

    async def check_shutdown(callback):
        global BOT_SHUTDOWN
        admins = ADMIN_IDS + get_all_admins()
        if callback.from_user.id in admins:
            return True
        if BOT_SHUTDOWN and callback.data not in ["check_bot_status", "turn_on_bot"]:
            try:
                with open('/tmp/bot_shutdown.txt', 'r', encoding='utf-8') as f:
                    shutdown_msg = f.read()
                await callback.answer(f"⚠️ {shutdown_msg}", show_alert=True)
            except:
                await callback.answer("⚠️ ربات در حال حاضر خاموش است", show_alert=True)
            return False
        return True

    # ── پنل اصلی ────────────────────────────────────
    @dp.callback_query(F.data.startswith("color_edit_"))
    async def change_button_color(callback: types.CallbackQuery):
        if not await admin_only(callback):
            return
        # data, keypad_name = callback.data.split("|")
        buttons = callback.message.reply_markup.inline_keyboard

        button_key = callback.data.replace("color_edit_", "")
        current = get_button_color(button_key)
        new_color = cycle_color(current)
        set_button_color(button_key, new_color)

        await callback.answer(f"رنگ تغییر کرد", show_alert=False)
        await safe_edit(callback, callback.message.text,
                        reply_markup=ikb_with_color_edit(buttons, edit_mode=True, user_id=callback.from_user.id))


    @dp.callback_query(F.data == "admin_stats")
    async def admin_stats(callback, state=None):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        stats = get_bot_stats()
        total, pays = User.get_referred_users_counts()

        text = (f"📊 آمار ربات\n\n"
                f"👤 کل کاربران: {stats['total_users']}\n"
                f"👤 کاربران دعوت شده: {total}\n"
                f"👤 کاربران دعوت شده و دارای خرید: {pays}\n"
                f"✅ سفارش موفق: {stats['total_orders']}\n"
                f"✅ سفارش موفق امروز: {stats['today_total_orders']}\n"
                f"💰 درآمد کل: {stats['total_revenue']:,} تومان\n"
                f"💰 درآمد امروز: {stats['today_revenue']:,} تومان\n"
                f"🔗 سرویس فعال: {stats['active_services']}")
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_back")
    async def admin_back_cb(callback):
        if not await check_shutdown(callback): return
        await safe_edit(callback, "پنل مدیریت:", reply_markup=admin_main_inline(callback.from_user.id))

    # ── مدیریت پلن‌ها ────────────────────────────────────

    @dp.callback_query(F.data == "admin_plans")
    async def admin_plans(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plans = get_active_plans()
        await safe_edit(callback, "مدیریت پلن‌ها:", reply_markup=admin_plans_inline(plans, callback.from_user.id))

    @dp.callback_query(F.data == "admin_add_plan")
    async def admin_add_plan_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_plan_name)
        await callback.message.edit_text("نام پلن جدید را وارد کنید:\n(مثال: ۳۰ گیگ یک ماهه)")

    @dp.message(Form.waiting_plan_name)
    async def plan_name(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        data = await state.get_data()
        if data.get('edit_plan_id'):
            plan_id = data['edit_plan_id']
            field = data.get('edit_plan_field', 'name')
            if field == 'label':
                conn = get_db()
                if message.text.strip() == '/reset':
                    conn.execute("UPDATE plans SET custom_label=NULL WHERE id=?", (plan_id,))
                    result_msg = "✅ متن دکمه به حالت پیش‌فرض برگشت!"
                else:
                    conn.execute("UPDATE plans SET custom_label=? WHERE id=?", (message.text.strip(), plan_id))
                    result_msg = "✅ متن دکمه ذخیره شد!"
                conn.commit()
                conn.close()
                await state.clear()
                await message.answer(result_msg, reply_markup=admin_main_inline(message.from_user.id))
            elif field == 'description':
                conn = get_db()
                if message.text.strip() == '/reset':
                    conn.execute("UPDATE plans SET custom_description=NULL WHERE id=?", (plan_id,))
                    result_msg = "✅ متن صفحه پلن به حالت پیش‌فرض برگشت!"
                else:
                    conn.execute("UPDATE plans SET custom_description=? WHERE id=?", (message.text.strip(), plan_id))
                    result_msg = "✅ متن صفحه پلن ذخیره شد!"
                conn.commit()
                conn.close()
                await state.clear()
                await message.answer(result_msg, reply_markup=admin_main_inline(message.from_user.id))
            elif update_plan(plan_id, name=message.text):
                await state.clear()
                await message.answer("✅ نام پلن به‌روزرسانی شد!")
            else:
                await message.answer("❌ خطا در به‌روزرسانی")
                await state.clear()
        else:
            await state.update_data(plan_name=message.text)
            await state.set_state(Form.waiting_plan_category)
            existing = get_plan_categories()
            cats_text = "\n".join([f"• {c}" for c in existing]) if existing else "هنوز دسته‌ای ندارید"
            await message.answer(
                f"نوع/دسته‌بندی سرویس را وارد کنید:\n(مثال: v2ray یا cisco)\n\nدسته‌های موجود:\n{cats_text}"
            )

    @dp.message(Form.waiting_plan_category)
    async def plan_category(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        data = await state.get_data()
        if data.get('edit_plan_id'):
            plan_id = data['edit_plan_id']
            if update_plan(plan_id, category=message.text.strip()):
                await state.clear()
                await message.answer("✅ دسته‌بندی پلن به‌روزرسانی شد!")
            else:
                await message.answer("❌ خطا در به‌روزرسانی")
                await state.clear()
        else:
            await state.update_data(plan_category=message.text.strip())
            await state.set_state(Form.waiting_plan_volume)
            await message.answer("حجم به گیگ (مثال: 30) یا 'نامحدود':")

    @dp.message(Form.waiting_plan_volume)
    async def plan_volume(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        text = message.text.strip().lower()
        data = await state.get_data()
        vol = -1 if text in ("نامحدود", "-1") else None
        if vol is None:
            try:
                vol = float(message.text)
                if vol <= 0:
                    await message.answer("عدد مثبت یا 'نامحدود' وارد کنید:")
                    return
            except:
                await message.answer("عدد یا 'نامحدود' وارد کنید:")
                return
        if data.get('edit_plan_id'):
            update_plan(data['edit_plan_id'], volume_gb=vol)
            await state.clear()
            await message.answer(f"✅ حجم پلن به‌روزرسانی شد! ({'نامحدود' if vol == -1 else str(vol) + ' GB'})")
        else:
            await state.update_data(plan_volume=vol)
            await state.set_state(Form.waiting_plan_duration)
            await message.answer("مدت به روز (مثال: 30) یا 'نامحدود':")

    @dp.message(Form.waiting_plan_duration)
    async def plan_duration(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        text = message.text.strip().lower()
        data = await state.get_data()
        dur = -1 if text in ("نامحدود", "-1") else None
        if dur is None:
            try:
                dur = int(message.text)
                if dur <= 0:
                    await message.answer("عدد مثبت یا 'نامحدود' وارد کنید:")
                    return
            except:
                await message.answer("عدد یا 'نامحدود' وارد کنید:")
                return
        if data.get('edit_plan_id'):
            update_plan(data['edit_plan_id'], duration_days=dur)
            await state.clear()
            await message.answer(f"✅ مدت زمان پلن به‌روزرسانی شد!")
        else:
            await state.update_data(plan_duration=dur)
            await state.set_state(Form.waiting_plan_price)
            await message.answer("قیمت به تومان (مثال: 50000):")

    @dp.message(Form.waiting_plan_price)
    async def plan_price(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        try:
            price = int(message.text)
        except:
            await message.answer("عدد وارد کنید:")
            return
        data = await state.get_data()
        if data.get('edit_plan_id'):
            update_plan(data['edit_plan_id'], price=price)
            await state.clear()
            await message.answer("✅ قیمت پلن به‌روزرسانی شد!")
        else:
            await state.update_data(plan_price=price)
            await state.set_state(Form.waiting_plan_devices)
            await message.answer("تعداد دستگاه (مثال: 1):")

    @dp.message(Form.waiting_plan_devices)
    async def plan_devices(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        try:
            devices = int(message.text)
        except:
            await message.answer("عدد وارد کنید:")
            return
        data = await state.get_data()
        if data.get('edit_plan_id'):
            update_plan(data['edit_plan_id'], max_devices=devices)
            await state.clear()
            await message.answer("✅ تعداد کاربر پلن به‌روزرسانی شد!")
        else:
            category = data.get('plan_category', 'عمومی')
            conn = get_db()
            conn.execute(
                "INSERT INTO plans (name, category, volume_gb, duration_days, max_devices, price) VALUES (?,?,?,?,?,?)",
                (data['plan_name'], category, data['plan_volume'], data['plan_duration'], devices, data['plan_price'])
            )
            conn.commit()
            conn.close()
            await state.clear()
            await message.answer(f"✅ پلن «{data['plan_name']}» در دسته «{category}» اضافه شد!", reply_markup=admin_main_inline(message.from_user.id))

    # ── جزئیات پلن و ویرایش ────────────────────────────────────

    @dp.callback_query(F.data.startswith("admin_plan_"))
    async def admin_plan_detail(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[2])
        plan = get_plan(plan_id)
        if not plan:
            await callback.answer("پلن یافت نشد", show_alert=True)
            return
        volume_display = "نامحدود 📊" if plan['volume_gb'] == -1 else f"{plan['volume_gb']} GB"
        duration_display = "نامحدود ⏱" if plan['duration_days'] == -1 else f"{plan['duration_days']} روز"
        text = (
            f"📦 جزئیات پلن\n\n"
            f"نام: {plan['name']}\n"
            f"دسته‌بندی: {plan.get('category', 'بدون دسته')}\n"
            f"حجم: {volume_display}\n"
            f"مدت زمان: {duration_display}\n"
            f"تعداد کاربر: {plan['max_devices']}\n"
            f"قیمت: {plan['price']:,} تومان\n"
            f"موجودی: {get_config_stock(plan_id)}"
        )
        buttons = [
            [ikbe(text=f"✏️ نام: {plan['name']}", callback_data=f"edit_plan_name_{plan_id}")],
            [ikbe(text="🏷 متن دکمه (custom)", callback_data=f"edit_plan_label_{plan_id}")],
            [ikbe(text=f"📁 دسته: {plan.get('category', '—')}", callback_data=f"edit_plan_cat_{plan_id}")],
            [ikbe(text=f"📊 حجم: {volume_display}", callback_data=f"edit_plan_vol_{plan_id}")],
            [ikbe(text=f"⏱ مدت: {duration_display}", callback_data=f"edit_plan_dur_{plan_id}")],
            [ikbe(text=f"👥 کاربر: {plan['max_devices']}", callback_data=f"edit_plan_dev_{plan_id}")],
            [ikbe(text=f"💰 قیمت: {plan['price']:,}", callback_data=f"edit_plan_pri_{plan_id}")],
            [ikbe(text=f"📋 کانفیگ‌ها ({get_config_stock(plan_id)} عدد)", callback_data=f"plancfg_{plan_id}")],
            [ikbe(text=f"⚙️ تنظیمات دسته‌بندی: {plan.get('category', '—')}", callback_data=f"edit_cat_settings_{plan.get('category', '')}")],
            [ikbe(text="🗑️ حذف پلن", callback_data=f"delete_plan_{plan_id}")],
            [ikbe(text="🔙 بازگشت", callback_data="admin_plans")],
        ]
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("edit_cat_settings_"))
    @only_admin
    async def edit_category_settings(callback: types.CallbackQuery, cat=None):
        category = cat or callback.data.replace("edit_cat_settings_", "")
        settings = CategorySetting.get(category)
        # New API/Host settings display
        host = settings.get('host') or "تنظیم نشده"
        token = settings.get('token') or "تنظیم نشده"
        group_ids = settings.get('group_ids') or "تنظیم نشده"

        p_text = "🔌 اتصال به پنل: روشن 🟢" if settings['connect_to_panel'] == 1 else "🔌 اتصال به پنل: خاموش 🔴"

        text = (
            f"⚙️ تنظیمات دسته‌بندی: <b>{category}</b>\n\n"
            f"هاست: <code>{host}</code>\n"
            f"🔑 توکن: <code>{token}</code>\n"
            f"👥 گروه‌ها: <code>{group_ids}</code>\n"
            f"⚠️ این تنظیمات برای <b>تمام پلن‌ها</b> در این دسته‌بندی اعمال می‌شود."
        )
        buttons = [
            [ikbe(text=f"هاست: {host}", callback_data=f"edit_cat_host_{category}")],
            [ikbe(text=f"توکن: {token}", callback_data=f"edit_cat_token_{category}")],
            [ikbe(text=f"گروه‌ها: {group_ids}", callback_data=f"edit_cat_groups_{category}")],
            [ikbe(text=p_text, callback_data=f"toggle_cat_panel_{category}")],
            [ikbe(text="🔙 بازگشت", callback_data="admin_plans")],
        ]
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    # ── Host / Token / Group IDs Callbacks ────────────────────

    @dp.callback_query(F.data.startswith("edit_cat_host_"))
    @only_admin
    async def edit_cat_host(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_host_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_host)
        await callback.message.edit_text(f"آدرس هاست جدید برای دسته‌بندی «{category}» را وارد کنید:\n(برای حذف /reset بفرستید)\n\nمثال: https://panel.example.com")

    @dp.message(Form.waiting_cat_host)
    @only_admin
    async def save_cat_host(message: types.Message, state: FSMContext):
        await process_cat_setting_str_input(message, state, "host", "هاست")

    @dp.callback_query(F.data.startswith("edit_cat_token_"))
    @only_admin
    async def edit_cat_token(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_token_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_token)
        await callback.message.edit_text(f"توکن API جدید برای دسته‌بندی «{category}» را وارد کنید:\n(برای حذف /reset بفرستید)")

    @dp.message(Form.waiting_cat_token)
    @only_admin
    async def save_cat_token(message: types.Message, state: FSMContext):
        await process_cat_setting_str_input(message, state, "token", "Token")

    @dp.callback_query(F.data.startswith("edit_cat_groups_"))
    @only_admin
    async def edit_cat_groups(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_groups_", "")

        # Fetch current saved IDs and convert to a list[cite: 1]
        settings = CategorySetting.get(category)
        current_ids_str = settings.get("group_ids") or ""
        selected_groups = [g.strip() for g in current_ids_str.split(",") if g.strip()]

        # Store in state to track toggles before saving
        await state.update_data(selected_groups=selected_groups)

        panel = await get_panel(category)
        groups = await panel.get_groups()

        buttons = []
        for g_id, g_name in groups:
            g_id_str = str(g_id)
            is_selected = g_id_str in selected_groups
            btn_text = f"✅ {g_name}" if is_selected else f"❌ {g_name}"

            # Using shortened prefix 'ctg_tog_' to prevent callback_data length limits
            buttons.append([ikbe(text=btn_text, callback_data=f"ctg_tog_{category}_{g_id_str}")])

        buttons.append([ikbe(text="💾 ذخیره تغییرات", callback_data=f"ctg_save_{category}")])
        buttons.append([ikbe(text="🔙 بازگشت", callback_data=f"edit_cat_settings_{category}")])

        await safe_edit(
            callback,
            f"گروه‌های فعال برای دسته‌بندی «{category}» را انتخاب کنید:",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("ctg_tog_"))
    @only_admin
    async def toggle_cat_group(callback: types.CallbackQuery, state: FSMContext):
        # Extract category and group ID safely
        parts = callback.data.split("_")
        g_id_str = parts[-1]

        # Reconstruct category name in case it contains underscores
        category = "_".join(parts[2:-1])

        data = await state.get_data()
        selected_groups = data.get("selected_groups", [])

        # Toggle logic
        if g_id_str in selected_groups:
            selected_groups.remove(g_id_str)
        else:
            selected_groups.append(g_id_str)

        await state.update_data(selected_groups=selected_groups)

        # Regenerate keyboard with new state
        panel = await get_panel(category)
        groups = await panel.get_groups()

        buttons = []
        for g_id, g_name in groups:
            is_sel = str(g_id) in selected_groups
            btn_text = f"✅ {g_name}" if is_sel else f"❌ {g_name}"
            buttons.append([ikbe(text=btn_text, callback_data=f"ctg_tog_{category}_{g_id}")])

        buttons.append([ikbe(text="💾 ذخیره تغییرات", callback_data=f"ctg_save_{category}")])
        buttons.append([ikbe(text="🔙 بازگشت", callback_data=f"edit_cat_settings_{category}")])

        await callback.message.edit_reply_markup(reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))
        await callback.answer()

    @dp.callback_query(F.data.startswith("ctg_save_"))
    @only_admin
    async def save_cat_groups(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("ctg_save_", "")
        data = await state.get_data()
        selected_groups = data.get("selected_groups", [])

        # Join IDs with commas, set to None if list is empty
        val = ",".join(selected_groups) if selected_groups else None

        # Update database[cite: 1]
        if CategorySetting.set(category, group_ids=val):
            await callback.answer("✅ شناسه‌های گروه ذخیره شدند!", show_alert=True)
        else:
            await callback.answer("❌ خطا در ذخیره‌سازی!", show_alert=True)

        await state.clear()

        # Route back to the main category settings view
        await edit_category_settings(callback, cat=category)

    @dp.callback_query(F.data.startswith("edit_cat_min_gig_"))
    @only_admin
    async def edit_cat_min_gig(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_min_gig_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_min_gig)
        await callback.message.edit_text(f"حداقل حجم (گیگابایت) برای تمدید دسته‌بندی «{category}» را وارد کنید:\n\n• برای بدون محدودیت /reset را بفرستید\n\nمثال: 5")

    @dp.message(Form.waiting_cat_min_gig)
    @only_admin
    async def save_cat_min_gig(message: types.Message, state: FSMContext):
        await process_cat_setting_input(message, state, "min_gig", "گیگابایت")

    @dp.callback_query(F.data.startswith("edit_cat_min_day_"))
    @only_admin
    async def edit_cat_min_day(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_min_day_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_min_day)
        await callback.message.edit_text(f"حداقل زمان (روز) برای تمدید دسته‌بندی «{category}» را وارد کنید:\n\n• برای بدون محدودیت /reset را بفرستید\n\nمثال: 7")

    @dp.message(Form.waiting_cat_min_day)
    @only_admin
    async def save_cat_min_day(message: types.Message, state: FSMContext):
        await process_cat_setting_input(message, state, "min_day", "روز")

    @dp.callback_query(F.data.startswith("edit_cat_bgig_"))
    @only_admin
    async def edit_cat_bgig(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_bgig_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_base_gig)
        await callback.message.edit_text(f"مقدار جدید برای قیمت پایه تمدید حجم دسته‌بندی «{category}» را وارد کنید:\n(برای حذف /reset بفرستید)")

    @dp.message(Form.waiting_cat_base_gig)
    @only_admin
    async def save_cat_bgig(message: types.Message, state: FSMContext):
        await process_cat_setting_input(message, state, "base_gig", "تومان")

    @dp.callback_query(F.data.startswith("edit_cat_bday_"))
    @only_admin
    async def edit_cat_bday(callback: types.CallbackQuery, state: FSMContext):
        category = callback.data.replace("edit_cat_bday_", "")
        await state.update_data(edit_category=category)
        await state.set_state(Form.waiting_cat_base_day)
        await callback.message.edit_text(f"مقدار جدید برای قیمت پایه تمدید روز دسته‌بندی «{category}» را وارد کنید:\n(برای حذف /reset بفرستید)")

    @dp.message(Form.waiting_cat_base_day)
    @only_admin
    async def save_cat_bday(message: types.Message, state: FSMContext):
        await process_cat_setting_input(message, state, "base_day", "تومان")

    @dp.callback_query(F.data.startswith("toggle_cat_panel_"))
    @only_admin
    async def toggle_cat_panel(callback: types.CallbackQuery):
        category = callback.data.replace("toggle_cat_panel_", "")
        settings = CategorySetting.get(category)

        new_status = 0 if settings['connect_to_panel'] == 1 else 1
        update_kwargs = {"connect_to_panel": new_status}

        if new_status == 1:
            async with AsyncSessionLocal() as session:
                plan = (await session.execute(select(Plan).where(Plan.category == category, Plan.is_active == 1, Plan.price > 0).limit(1))).scalar_one_or_none()
                if plan:
                    if settings['base_gig'] is None and plan.volume_gb > 0:
                        update_kwargs["base_gig"] = int(plan.price / plan.volume_gb)
                    if settings['base_day'] is None and plan.duration_days > 0:
                        update_kwargs["base_day"] = int(plan.price / plan.duration_days)

        if CategorySetting.set(category, **update_kwargs):
            status_text = "روشن " if new_status == 1 else "خاموش "
            await callback.answer(f" وضعیت اتصال پنل دسته‌بندی «{category}» به {status_text} تغییر یافت.")
            await edit_category_settings(callback, cat=category)
        else:
            await callback.answer("❌ خطا در به‌روزرسانی", show_alert=True)



    @dp.callback_query(F.data.startswith("plancfg_"))
    async def plan_configs_list(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[1])
        plan = get_plan(plan_id)
        if not plan:
            await callback.answer("پلن یافت نشد", show_alert=True)
            return
        conn = get_db()
        configs = conn.execute(
            "SELECT id, config_data FROM configs WHERE plan_id=? AND is_used=0 ORDER BY id ASC",
            (plan_id,)
        ).fetchall()
        conn.close()
        await callback.answer()
        if not configs:
            await callback.message.answer(
                f"📭 هیچ کانفیگ موجودی برای پلن «{plan['name']}» وجود ندارد.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [ikbe(text="🔙 بازگشت به پلن", callback_data=f"admin_plan_{plan_id}")]
                ])
            )
            return
        await callback.message.answer(
            f"📋 کانفیگ‌های موجود پلن «{plan['name']}» ({len(configs)} عدد):\n"
            f"برای حذف هر کانفیگ روی دکمه زیر آن بزنید."
        )
        for cfg in configs:
            await callback.message.answer(
                f"<code>{cfg['config_data']}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [ikbe(
                        text="🗑 حذف این کانفیگ",
                        callback_data=f"del_config_{cfg['id']}_{plan_id}"
                    )]
                ])
            )
        await callback.message.answer(
            "─────────────────",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ikbe(text="🗑🗑 حذف همه کانفیگ‌ها", callback_data=f"del_all_configs_{plan_id}")],
                [ikbe(text="🔙 بازگشت به پلن", callback_data=f"admin_plan_{plan_id}")]
            ])
        )


    @dp.callback_query(F.data.startswith("del_all_configs_"))
    async def del_all_configs_confirm(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        plan = get_plan(plan_id)
        if not plan:
            await callback.answer("پلن یافت نشد", show_alert=True)
            return
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM configs WHERE plan_id=? AND is_used=0", (plan_id,)
        ).fetchone()['cnt']
        conn.close()
        await callback.answer()
        await callback.message.answer(
            f"⚠️ آیا مطمئن هستید؟\n\n"
            f"تعداد {count} کانفیگ موجود پلن «{plan['name']}» حذف خواهد شد.\n"
            f"این عمل غیرقابل بازگشت است.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ikbe(text="✅ بله، همه را حذف کن", callback_data=f"confirm_del_all_{plan_id}")],
                [ikbe(text="❌ انصراف", callback_data=f"admin_plan_{plan_id}")]
            ])
        )

    @dp.callback_query(F.data.startswith("confirm_del_all_"))
    async def del_all_configs_execute(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        plan = get_plan(plan_id)
        conn = get_db()
        deleted = conn.execute(
            "DELETE FROM configs WHERE plan_id=? AND is_used=0", (plan_id,)
        ).rowcount
        conn.commit()
        conn.close()
        plan_name = plan['name'] if plan else str(plan_id)
        await callback.answer(f"✅ {deleted} کانفیگ حذف شد.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            f"✅ {deleted} کانفیگ از پلن «{plan_name}» حذف شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ikbe(text="🔙 بازگشت به پلن", callback_data=f"admin_plan_{plan_id}")]
            ])
        )

    @dp.callback_query(F.data.startswith("del_config_"))
    async def delete_config_handler(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        parts = callback.data.split("_")
        config_id = int(parts[2])
        plan_id = int(parts[3])
        conn = get_db()
        row = conn.execute(
            "SELECT id, is_used FROM configs WHERE id=?", (config_id,)
        ).fetchone()
        if not row:
            conn.close()
            await callback.answer("❌ کانفیگ پیدا نشد یا قبلاً حذف شده.", show_alert=True)
            return
        if row['is_used']:
            conn.close()
            await callback.answer("⚠️ این کانفیگ قبلاً به کاربری اختصاص داده شده و قابل حذف نیست.", show_alert=True)
            return
        conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
        conn.commit()
        conn.close()
        await callback.answer("✅ کانفیگ حذف شد.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("edit_plan_name_"))
    async def edit_plan_name(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_name)
        await callback.message.edit_text("نام جدید پلن را وارد کنید:")


    @dp.callback_query(F.data.startswith("edit_plan_label_"))
    async def edit_plan_label(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        conn = get_db()
        row = conn.execute("SELECT custom_label FROM plans WHERE id=?", (plan_id,)).fetchone()
        conn.close()
        current = row['custom_label'] if row and row['custom_label'] else "پیش‌فرض"
        txt = "متن دکمه فعلی: " + current + "\n\nمتن جدید را وارد کنید:\n(برای پیش‌فرض: /reset)"
        await state.update_data(edit_plan_id=plan_id, edit_plan_field='label')
        await state.set_state(Form.waiting_plan_name)
        await callback.message.edit_text(txt)


    @dp.callback_query(F.data.startswith("edit_plan_cat_"))
    async def edit_plan_cat(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_category)
        await callback.message.edit_text("دسته‌بندی جدید را وارد کنید:")

    @dp.callback_query(F.data.startswith("edit_plan_vol_"))
    async def edit_plan_vol(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_volume)
        await callback.message.edit_text("حجم جدید (GB) یا 'نامحدود':")

    @dp.callback_query(F.data.startswith("edit_plan_dur_"))
    async def edit_plan_dur(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_duration)
        await callback.message.edit_text("مدت زمان جدید (روز) یا 'نامحدود':")

    @dp.callback_query(F.data.startswith("edit_plan_dev_"))
    async def edit_plan_dev(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_devices)
        await callback.message.edit_text("تعداد کاربر جدید:")

    @dp.callback_query(F.data.startswith("edit_plan_pri_"))
    async def edit_plan_pri(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(edit_plan_id=plan_id)
        await state.set_state(Form.waiting_plan_price)
        await callback.message.edit_text("قیمت جدید (تومان):")

    @dp.callback_query(F.data.startswith("delete_plan_"))
    async def delete_plan_confirm(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[-1])
        plan = get_plan(plan_id)
        if not plan:
            await callback.answer("پلن یافت نشد", show_alert=True)
            return
        await callback.message.edit_text(
            f"⚠️ آیا مطمئن هستید که می‌خواهید پلن «{plan['name']}» را حذف کنید؟",
            reply_markup=ikb_with_color_edit([[
                btn("✅ تأیید حذف", f"confirm_delete_plan_{plan_id}"),
                btn("❌ انصراف", f"admin_plan_{plan_id}"),
            ]], user_id=callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("confirm_delete_plan_"))
    async def confirm_delete_plan(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[-1])
        plan = get_plan(plan_id)
        if delete_plan(plan_id):
            await callback.answer("✅ پلن حذف شد")
            await callback.message.edit_text(f"✅ پلن «{plan['name']}» حذف شد.", reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_plans")]], user_id=callback.from_user.id))
        else:
            await callback.answer("❌ خطا در حذف پلن", show_alert=True)

    # ── افزودن کانفیگ (بدون پسورد، هر پیام = یک کانفیگ) ────────────────────────────────────

    @dp.callback_query(F.data == "admin_add_config")
    async def admin_add_config_select(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plans = get_active_plans()
        if not plans:
            await callback.answer("ابتدا یک پلن اضافه کنید", show_alert=True)
            return

        plans = sorted(plans, key=lambda x: (x["category"], x["volume_gb"]))
        buttons = [[btn(f"{p['name']} (موجودی: {p['stock']})", f"admin_add_config_{p['id']}")] for p in plans]
        buttons.append([btn("🔙 بازگشت", "admin_back")])
        await callback.message.edit_text(
            "برای کدام پلن کانفیگ اضافه می‌کنید؟",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("admin_add_config_"))
    async def admin_add_config_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        await state.update_data(config_plan_id=plan_id, config_count=0)
        # Ask admin for mode: multi-line OR each line
        kb = ikb_with_color_edit([
            [ikbe(text="هر پیام یک کانفیگ", callback_data="admin_config_mode_multiline")],
            [ikbe(text="هر خط یک کانفیگ", callback_data="admin_config_mode_perline")],
            [ikbe(text="🔙 بازگشت", callback_data=f"admin_add_config")]
        ], user_id = callback.from_user.id)

        plan = get_plan(plan_id)
        await callback.message.edit_text(
            f"📥 افزودن کانفیگ برای پلن «{plan['name']}»\n\n"
            f"لطفا نوع ثبت کانفیگ را انتخاب کنید:\n"
            f"📝 «هر پیام یک کانفیگ» (حتی چند خط در یک پیام، همگی یک کانفیگ ذخیره می‌شود)\n"
            f"🔹 «هر خط یک کانفیگ» (چند خط در یک پیام = چند کانفیگ)\n",
            reply_markup=kb
        )

    @dp.callback_query(F.data.in_(["admin_config_mode_multiline", "admin_config_mode_perline"]))
    async def admin_add_config_mode_select(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        data = await state.get_data()
        plan_id = data.get("config_plan_id")
        if not plan_id:
            await callback.answer("لطفا ابتدا پلن را انتخاب کنید.", show_alert=True)
            return

        mode = "perline" if callback.data == "admin_config_mode_perline" else "multiline"
        await state.update_data(config_mode=mode)
        await state.set_state(Form.waiting_config_data)
        plan = get_plan(plan_id)
        if mode == "multiline":
            msg = (
                f"📥 افزودن کانفیگ برای پلن «{plan['name']}»\n\n"
                f"هر پیام = یک کانفیگ\n"
                f"(هر متنی که ارسال کنید — چه یک خط، چه چند خط — به عنوان یک کانفیگ ذخیره می‌شود)\n\n"
                f"وقتی تمام شد بنویسید: /done"
            )
        else:
            msg = (
                f"📥 افزودن کانفیگ برای پلن «{plan['name']}»\n\n"
                f"هر خط = یک کانفیگ\n"
                f"(اگر چند خط را در یک پیام بفرستید، هر خط به طور جداگانه ذخیره می‌شود)\n\n"
                f"وقتی تمام شد بنویسید: /done"
            )
        await callback.message.edit_text(msg)

    @dp.message(Form.waiting_config_data)
    async def save_configs(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return

        if message.text and message.text.strip() == "/done":
            data = await state.get_data()
            count = data.get('config_count', 0)
            plan_id = data.get('config_plan_id')
            plan = get_plan(plan_id)
            stock = get_config_stock(plan_id)
            await state.clear()
            await message.answer(
                f"✅ {count} کانفیگ اضافه شد!\n"
                f"📦 پلن: {plan['name']}\n"
                f"📊 موجودی فعلی: {stock}",
                reply_markup=admin_main_inline(message.from_user.id)
            )
            await process_waiting_queue(plan_id, message.from_user.id)
            return

        data = await state.get_data()
        plan_id = data.get('config_plan_id')
        config_mode = data.get('config_mode', 'multiline')  # default for backward compatibility

        conn = get_db()
        saved_count = 0

        _type = "text"
        config_items = []

        if message.text:
            if config_mode == "multiline":
                config_value = message.html_text.strip()
                if not config_value:
                    await message.answer("متن کانفیگ نمی‌تواند خالی باشد.")
                    return
                config_items.append(config_value)
            else:  # perline
                lines = [line.strip() for line in message.html_text.split('\n') if line.strip()]
                if not lines:
                    await message.answer("هیچ خط معتبری یافت نشد.")
                    return
                config_items.extend(lines)
        else:
            return

        for config_value in config_items:
            conn.execute(
                "INSERT INTO configs (plan_id, config_data) VALUES (?,?)",
                (plan_id, config_value)
            )
            saved_count += 1

        conn.commit()
        conn.close()
        prev = data.get('config_count', 0)
        await state.update_data(config_count=prev + saved_count)
        await message.answer(f"✅ {saved_count} کانفیگ ذخیره شد (جمعا: {prev+saved_count})\nبیشتر بفرست یا /done بزن.")


# ── ارسال پست دعوت به کانال با لینک ثابت ────────────────────────────────────

    @dp.callback_query(F.data == "admin_invite_send")
    async def admin_invite_send(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_invite_channel_username)
        await safe_edit(
            callback,
            "لطفا یوزرنیم کانال مقصد را وارد کنید (مثال: @mychannel یا عدد آی‌دی کانال):",
            reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id)
        )

    @dp.message(Form.waiting_invite_channel_username)
    async def receive_invite_channel_username(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        channel_username = message.text.strip()
        await state.update_data(invite_channel_username=channel_username)
        await state.set_state(Form.waiting_invite_post_text)
        await message.answer(
            "لطفا متن یا مدیا (عکس، ویدیو، گیف یا سند) پست ارسالی را ارسال کنید.\n\n"
            "اگر متن می‌فرستید فقط متن را بفرستید.\n"
            "در غیر اینصورت عکس/ویدیو/گیف/سند را همراه با کپشن وارد کنید (در یک پیام)."
        )

    @dp.message(Form.waiting_invite_post_text, F.content_type.in_({"text", "photo", "video", "animation", "document"}))
    async def receive_invite_post_text_or_media(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return

        caption = message.html_text if (message.caption is not None) else None
        main_text = message.html_text if (message.content_type == "text") else None
        await state.update_data(invite_post_text=main_text or caption)

        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
            await state.update_data(invite_post_media_type="photo", invite_post_media_id=file_id)
        elif message.content_type == "video":
            await state.update_data(invite_post_media_type="video", invite_post_media_id=message.video.file_id)
        elif message.content_type == "animation":
            await state.update_data(invite_post_media_type="animation", invite_post_media_id=message.animation.file_id)
        elif message.content_type == "document":
            await state.update_data(invite_post_media_type="document", invite_post_media_id=message.document.file_id)
        else:
            await state.update_data(invite_post_media_type=None, invite_post_media_id=None)

        await state.set_state(Form.waiting_invite_button_name)
        await message.answer("لطفا نام دکمه شیشه‌ای (متن روی دکمه) را وارد کنید:")

    @dp.message(Form.waiting_invite_button_name)
    async def receive_invite_button_name(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return

        button_name = message.text.strip()
        await state.update_data(invite_button_name=button_name)

        await state.set_state(Form.waiting_invite_start_param)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="نمایش تست رایگان", callback_data="invite_param_show_free_test")],
            [InlineKeyboardButton(text="نمایش سرویس ها", callback_data="invite_param_show_categories")],
            [InlineKeyboardButton(text="نمایش مسابقه", callback_data="invite_param_show_tornoment")]
        ])

        text = "دکمه زیر پیام چه کاری انجام بده؟"

        await message.answer(
            text,
            reply_markup=keyboard
        )

    @dp.callback_query(Form.waiting_invite_start_param, F.data.in_({"invite_param_show_free_test", "invite_param_show_categories", "invite_param_show_tornoment"}))
    async def process_invite_start_param(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return

        start_param = callback.data.replace("invite_param_", "")

        data = await state.get_data()

        channel_username = data.get("invite_channel_username")
        post_text = data.get("invite_post_text", "")
        media_type = data.get("invite_post_media_type")
        media_id = data.get("invite_post_media_id")
        button_name = data.get("invite_button_name")

        await state.clear()

        await callback.message.delete()

        if not channel_username:
            await callback.message.answer(
                "❌ آیدی کانال پیدا نشد.\nلطفاً دوباره تلاش کنید.",
                reply_markup=admin_main_inline(callback.from_user.id)
            )
            return

        if isinstance(channel_username, str) and channel_username.lstrip("-").isdigit():
            channel_username = int(channel_username)

        me = await bot.get_me()
        # قرار دادن پارامتر انتخابی در انتهای لینک
        link = f"https://t.me/{me.username}?start={start_param}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [ikbe(text=button_name, url=link, style="primary")]
        ])

        try:
            if media_type == "photo" and media_id:
                await bot.send_photo(chat_id=channel_username, photo=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "video" and media_id:
                await bot.send_video(chat_id=channel_username, video=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "animation" and media_id:
                await bot.send_animation(chat_id=channel_username, animation=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "document" and media_id:
                await bot.send_document(chat_id=channel_username, document=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            else:
                await bot.send_message(chat_id=channel_username, text=post_text, reply_markup=keyboard, parse_mode='HTML', disable_web_page_preview=False)

            await callback.message.answer(
                "✅ پست دعوت با موفقیت به کانال ارسال شد.",
                reply_markup=admin_main_inline(callback.from_user.id)
            )
        except Exception as e:
            await callback.message.answer(
                f"❌ خطا در ارسال پست دعوت به کانال:\n{e}",
                reply_markup=admin_main_inline(callback.from_user.id)
            )
        finally:
            await callback.answer()

    # ── ارسال پیام به کانال با دکمه پلن ────────────────────────────────────

    @dp.callback_query(F.data == "admin_channel_send")
    async def admin_channel_send(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_channel_username)
        await safe_edit(
            callback,
            "لطفا یوزرنیم کانال را وارد کنید (مثال: @mychannel یا عدد آی‌دی کانال):",
            reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id)
        )

    @dp.message(Form.waiting_channel_username)
    async def receive_channel_username(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        channel_username = message.text.strip()
        await state.update_data(channel_username=channel_username)
        await state.set_state(Form.waiting_channel_post_text)
        await message.answer(
            "لطفا متن یا مدیا (عکس، ویدیو، گیف یا سند) پست ارسالی به کانال را ارسال کنید.\n\n"
            "اگر متن می‌فرستید فقط متن را بفرستید.\n"
            "در غیر اینصورت عکس/ویدیو/گیف/سند را همراه با کپشن وارد کنید (در یک پیام)."
        )

    @dp.message(Form.waiting_channel_post_text, F.content_type.in_({"text", "photo", "video", "animation", "document"}))
    async def receive_channel_post_text_or_media(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return

        caption = message.html_text if (message.caption is not None) else None
        main_text = message.html_text if (message.content_type == "text") else None
        await state.update_data(channel_post_text=main_text or caption)

        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
            await state.update_data(channel_post_media_type="photo", channel_post_media_id=file_id)
        elif message.content_type == "video":
            await state.update_data(channel_post_media_type="video", channel_post_media_id=message.video.file_id)
        elif message.content_type == "animation":
            await state.update_data(channel_post_media_type="animation", channel_post_media_id=message.animation.file_id)
        elif message.content_type == "document":
            await state.update_data(channel_post_media_type="document", channel_post_media_id=message.document.file_id)
        else:
            await state.update_data(channel_post_media_type=None, channel_post_media_id=None)

        plans = get_active_plans()
        if not plans:
            await state.clear()
            await message.answer("❌ هیچ پلنی فعال نیست.", reply_markup=admin_main_inline(message.from_user.id))
            return

        kb = []
        for i, plan in enumerate(plans, 1):
            kb.append([ikbe(text=plan['name'], callback_data=f"select_channel_btn_plan_{plan['id']}")])
        kb.append([ikbe(text="⚡️ ارسال", callback_data="finish_channel_btn_select", style='primary')])

        await state.update_data(selected_plans=[])
        await message.answer(
            "پلن‌هایی که می‌خواهید به عنوان دکمه زیر پست قرار گیرند انتخاب کنید (چندتا می‌توانید انتخاب کنید):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )

    @dp.callback_query(F.data.startswith("select_channel_btn_plan_"))
    async def select_plan_for_channel_button(callback: types.CallbackQuery, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if callback.from_user.id not in admins:
            return
        plan_id = int(callback.data.replace("select_channel_btn_plan_", ""))
        data = await state.get_data()
        selected_plans = data.get("selected_plans", [])

        if plan_id in selected_plans:
            selected_plans.remove(plan_id)
        else:
            selected_plans.append(plan_id)

        await state.update_data(selected_plans=selected_plans)

        plans = get_active_plans()
        selected_text = "دکمه‌های انتخاب‌شده:\n"
        for pid in selected_plans:
            plan = next((p for p in plans if p['id'] == pid), None)
            if plan:
                selected_text += f"▫️ {plan['name']}\n"

        kb = []
        for i, plan in enumerate(plans, 1):
            if plan['id'] in selected_plans:
                kb.append([ikbe(text=plan['name'], callback_data=f"select_channel_btn_plan_{plan['id']}", style="success")])
            else:
                kb.append([ikbe(text=plan['name'], callback_data=f"select_channel_btn_plan_{plan['id']}")])
        kb.append([ikbe(text="⚡️ ارسال", callback_data="finish_channel_btn_select", style='primary')])

        await callback.message.edit_text(
            "پلن‌هایی که می‌خواهید به عنوان دکمه انتخاب کنید کلیک و سپس روی ارسال بزنید.\n\n" + selected_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )

    @dp.callback_query(F.data == "finish_channel_btn_select")
    async def finish_channel_plan_buttons(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        data = await state.get_data()
        selected_plans = data.get("selected_plans", [])
        plans = get_active_plans()
        plans_sorted = sorted(plans, key=lambda x: x.get("id", 0))

        me = await bot.get_me()
        buttons = []
        for plan_id in selected_plans:
            plan = next((p for p in plans_sorted if p['id'] == plan_id), None)
            if plan:
                url = plan.get("custom_link") or f"https://t.me/{me.username}?start=plan_{plan['id']}"
                buttons.append([ikbe(text=plan['name'], url=url, style='primary')])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        post_text = data.get("channel_post_text", "")
        channel_username = data.get("channel_username")
        media_type = data.get("channel_post_media_type")
        media_id = data.get("channel_post_media_id")
        await state.clear()

        if not channel_username:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text="❌ آیدی کانال پیدا نشد.\nلطفاً دوباره از منو ارسال پست به کانال شروع کنید.",
                reply_markup=admin_main_inline(callback.from_user.id)
            )
            return

        if isinstance(channel_username, str) and channel_username.lstrip("-").isdigit():
            channel_username = int(channel_username)

        try:
            if media_type == "photo" and media_id:
                await bot.send_photo(chat_id=channel_username, photo=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "video" and media_id:
                await bot.send_video(chat_id=channel_username, video=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "animation" and media_id:
                await bot.send_animation(chat_id=channel_username, animation=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            elif media_type == "document" and media_id:
                await bot.send_document(chat_id=channel_username, document=media_id, caption=post_text, reply_markup=keyboard, parse_mode='HTML')
            else:
                await bot.send_message(chat_id=channel_username, text=post_text, reply_markup=keyboard, parse_mode='HTML', disable_web_page_preview=False)
            await callback.message.delete()
            await bot.send_message(
                chat_id=callback.from_user.id,
                text="✅ پست با موفقیت به کانال ارسال شد.",
                reply_markup=admin_main_inline(callback.from_user.id)
            )
        except Exception as e:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=f"❌ خطا در ارسال پست به کانال:\n{e}",
                reply_markup=admin_main_inline(callback.from_user.id)
            )


    # ── FORCE JOIN ────────────────────────────────────

    def _mandatory_channels_text(channels):
        if not channels:
            return "📢 عضویت اجباری\n\nهنوز کانالی اضافه نشده است.\nروی هر کانال بزنید تا حذف شود."
        return "📢 عضویت اجباری\n\nکانال‌های فعلی (برای حذف روی نام کانال بزنید):"

    @dp.callback_query(F.data == "admin_mandatory_channels")
    async def admin_mandatory_channels(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.clear()
        channels = MandatoryChannel.get_all()
        await safe_edit(
            callback,
            _mandatory_channels_text(channels),
            reply_markup=admin_mandatory_channels_inline(channels, callback.from_user.id),
        )

    @dp.callback_query(F.data.startswith("admin_mandatory_remove_"))
    async def admin_mandatory_remove(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        channel_row_id = int(callback.data.replace("admin_mandatory_remove_", ""))
        ch = MandatoryChannel.get_by_id(channel_row_id)
        if ch:
            MandatoryChannel.remove(channel_row_id)
            await callback.answer(f"✅ «{ch['title']}» حذف شد")
        else:
            await callback.answer("کانال یافت نشد", show_alert=True)
        channels = MandatoryChannel.get_all()
        await safe_edit(
            callback,
            _mandatory_channels_text(channels),
            reply_markup=admin_mandatory_channels_inline(channels, callback.from_user.id),
        )

    @dp.callback_query(F.data == "admin_mandatory_add")
    async def admin_mandatory_add(callback: types.CallbackQuery, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_mandatory_channel_username)
        await safe_edit(
            callback,
            "➕ افزودن کانال عضویت اجباری\n\n"
            "یوزرنیم کانال را وارد کنید (مثال: @mychannel یا آیدی عددی کانال):",
            reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_mandatory_channels")]], user_id=callback.from_user.id),
        )

    @dp.message(Form.waiting_mandatory_channel_username)
    async def receive_mandatory_channel_username(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        raw = (message.text or "").strip()
        if not raw:
            await message.answer("یوزرنیم کانال را وارد کنید:")
            return

        chat_ref = raw
        if raw.lstrip("-").isdigit():
            chat_ref = int(raw)

        try:
            chat = await bot.get_chat(chat_ref)
        except Exception as e:
            logging.error(f"Mandatory channel get_chat error: {e}")
            await message.answer(
                "❌ کانال یافت نشد. مطمئن شوید یوزرنیم درست است و ربات به کانال دسترسی دارد."
            )
            return

        if chat.type not in ("channel", "supergroup"):
            await message.answer("❌ این چت یک کانال نیست.")
            return

        try:
            bot_info = await bot.get_me()
            member = await bot.get_chat_member(chat.id, bot_info.id)
        except Exception as e:
            logging.error(f"Mandatory channel get_chat_member error: {e}")
            await message.answer(
                "❌ ربات عضو این کانال نیست. ابتدا ربات را به کانال اضافه کنید."
            )
            return

        if member.status not in ("administrator", "creator"):
            await message.answer("❌ ربات در این کانال ادمین نیست. ابتدا ربات را ادمین کانال کنید.")
            return

        username = chat.username
        title = chat.title or (f"@{username}" if username else str(chat.id))
        ok, err = MandatoryChannel.add(chat.id, username, title)
        await state.clear()

        if not ok:
            if err == "duplicate":
                await message.answer(f"⚠️ کانال «{title}» قبلاً اضافه شده است.")
            else:
                await message.answer(f"❌ خطا در ذخیره کانال: {err}")
        else:
            uname_display = f" (@{username})" if username else ""
            await message.answer(f"✅ کانال «{title}»{uname_display} اضافه شد.")

        channels = MandatoryChannel.get_all()
        await message.answer(
            _mandatory_channels_text(channels),
            reply_markup=admin_mandatory_channels_inline(channels, message.from_user.id),
        )

    # ── مدیریت کاربران ────────────────────────────────────

    @dp.callback_query(F.data == "admin_users")
    async def admin_users(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_charge_id)
        await callback.message.edit_text(
            "👤 مدیریت کاربران\n\n"
            "آیدی عددی تلگرام کاربر را وارد کنید:\n"
            "(مثال: 123456789)"
        )

    @dp.message(Form.waiting_charge_id)
    async def get_user_for_admin(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        try:
            uid = int(message.text.strip())
        except:
            await message.answer("آیدی باید عدد باشد. دوباره وارد کنید:")
            return
        user = get_user(uid)
        if not user:
            await message.answer("⚠️ کاربر یافت نشد.\nشاید هنوز ربات را استارت نزده باشد.")
            await state.clear()
            return
        await state.clear()
        status = "🚫 مسدود" if user['is_banned'] else "✅ فعال"
        svc_count = get_user_service_count(uid)
        ref_count = get_user_referral_count(uid)
        p_count = len(User.get_referral_with_pay_true(uid))

        text = (
            f"👤 اطلاعات کاربر\n\n"
            f"نام: {user['full_name']}\n"
            f"یوزرنیم: @{user['username']}\n"
            f"🆔 آیدی: <code>{uid}</code>\n"
            f"💰 موجودی: {user['balance']:,} تومان\n"
            f"📦 تعداد سرویس: {svc_count}\n"
            f"👥 زیرمجموعه: {ref_count} نفر\n"
            f"👥 زیرمجموعه های فعال: {p_count} نفر\n"
            f"وضعیت: {status}"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=admin_user_inline(uid))

    @dp.callback_query(F.data.startswith("admin_edit_wallet_"))
    async def admin_edit_wallet_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        uid = int(callback.data.split("_")[3])
        user = get_user(uid)
        await state.update_data(target_user_id=uid)
        await state.set_state(Form.waiting_edit_wallet)
        await callback.message.edit_text(
            f"💰 ویرایش کیف پول کاربر {uid}\n"
            f"موجودی فعلی: {user['balance']:,} تومان\n\n"
            f"مبلغ جدید را وارد کنید (عدد):\n"
            f"• عدد مثبت = شارژ (مثال: 50000)\n"
            f"• عدد منفی = کسر (مثال: -50000)\n"
            f"• برای تنظیم مستقیم: set:200000"
        )

    @dp.message(Form.waiting_edit_wallet)
    async def do_edit_wallet(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        data = await state.get_data()
        uid = data.get('target_user_id')
        text = message.text.strip()
        try:
            if text.startswith("set:"):
                amount = int(text.replace("set:", ""))
                set_wallet(uid, amount, "تنظیم موجودی توسط ادمین")
                await state.clear()
                await message.answer(f"✅ موجودی کاربر {uid} به {amount:,} تومان تنظیم شد.", reply_markup=admin_main_inline(message.from_user.id))
            else:
                amount = int(text)
                charge_wallet(uid, amount, "ویرایش توسط ادمین")
                await state.clear()
                sign = "+" if amount >= 0 else ""
                await message.answer(f"✅ {sign}{amount:,} تومان به کاربر {uid} اعمال شد.", reply_markup=admin_main_inline(message.from_user.id))
                try:
                    if amount > 0:
                        charge_msg = get_setting('msg_wallet_charge_confirm') or '💰 {amount} تومان به کیف پول شما اضافه شد.'
                        charge_msg = charge_msg.replace('{amount}', f"{amount:,}")
                        await bot.send_message(uid, charge_msg)
                except:
                    pass
        except:
            await message.answer("فرمت نادرست. مثال: 50000 یا -50000 یا set:100000")

    @dp.callback_query(F.data.startswith("admin_charge_"))
    async def admin_charge_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        uid = int(callback.data.split("_")[2])
        await state.update_data(target_user_id=uid)
        await state.set_state(Form.waiting_charge_amount)
        await callback.message.edit_text(f"مبلغ شارژ برای کاربر {uid} را به تومان وارد کنید:")

    @dp.message(Form.waiting_charge_amount)
    async def do_charge(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS:
            return
        try:
            amount = int(message.text.strip())
        except:
            await message.answer("مبلغ نامعتبر. عدد وارد کنید:")
            return
        data = await state.get_data()
        uid = data.get('target_user_id')
        charge_wallet(uid, amount, "شارژ توسط ادمین")
        await state.clear()
        await message.answer(f"✅ {amount:,} تومان به کاربر {uid} اضافه شد.", reply_markup=admin_main_inline(message.from_user.id))
        try:
            charge_msg = get_setting('msg_wallet_charge_confirm') or '💰 {amount} تومان به کیف پول شما اضافه شد.'
            charge_msg = charge_msg.replace('{amount}', f"{amount:,}")
            await bot.send_message(uid, charge_msg)
        except:
            pass

    @dp.callback_query(F.data.startswith("admin_ban_"))
    async def admin_ban(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        uid = int(callback.data.split("_")[2])
        conn = get_db()
        user = conn.execute("SELECT is_banned FROM users WHERE telegram_id=?", (uid,)).fetchone()
        new_status = 0 if user['is_banned'] else 1
        conn.execute("UPDATE users SET is_banned=? WHERE telegram_id=?", (new_status, uid))
        conn.commit()
        conn.close()
        label = "🚫 مسدود شد" if new_status else "✅ رفع مسدودیت شد"
        await callback.answer(label)
        try:
            await callback.message.edit_text(callback.message.text + f"\n\n{label}", parse_mode="HTML")
        except:
            pass

    @dp.callback_query(F.data.startswith("admin_user_services_"))
    async def admin_user_services(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        uid = int(callback.data.split("_")[3])
        services = get_user_services(uid)
        if not services:
            await callback.answer("این کاربر سرویسی ندارد.", show_alert=True)
            return
        text = f"📦 سرویس‌های کاربر {uid}:\n\n"
        for s in services:
            sname = s.get('service_name') or s['plan_name']
            text += f"• {sname} — تا {s['expires_at'][:10]}\n"
            text += f"  <code>{s['config_data'][:50]}...</code>\n\n"
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", f"admin_users")]], user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("admin_edit_service_"))
    async def admin_edit_service(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        uid = int(callback.data.split("_")[3])
        services = get_user_services(uid)
        if not services:
            await callback.answer("این کاربر سرویسی ندارد.", show_alert=True)
            return
        buttons = []
        for s in services:
            sname = s.get('service_name') or s['plan_name']
            buttons.append([btn(f"✏️ {sname}", f"edit_svc_config_{s['id']}")])
        buttons.append([btn("🔙 بازگشت", f"admin_users")])
        await callback.message.edit_text(f"کدام سرویس را ویرایش می‌کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("edit_svc_config_"))
    async def edit_svc_config_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        svc_id = int(callback.data.split("_")[3])
        conn = get_db()
        s = conn.execute("SELECT * FROM services s JOIN configs c ON s.config_id=c.id WHERE s.id=?", (svc_id,)).fetchone()
        conn.close()
        if not s:
            await callback.answer("سرویس یافت نشد", show_alert=True)
            return
        await state.update_data(edit_svc_id=svc_id, edit_config_id=s['config_id'])
        await state.set_state(Form.waiting_edit_service_config)
        await callback.message.edit_text(
            f"کانفیگ فعلی:\n<code>{s['config_data']}</code>\n\nکانفیگ جدید را وارد کنید:",
            parse_mode="HTML"
        )

    @dp.message(Form.waiting_edit_service_config)
    async def save_svc_config(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        data = await state.get_data()
        config_id = data.get('edit_config_id')
        conn = get_db()
        conn.execute("UPDATE configs SET config_data=? WHERE id=?", (message.html_text.strip(), config_id))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ کانفیگ سرویس به‌روزرسانی شد.", reply_markup=admin_main_inline(message.from_user.id))

    # ── صف انتظار ────────────────────────────────────

    @dp.callback_query(F.data == "admin_waiting_queue")
    async def admin_waiting_queue_view(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return

        all_queue = get_all_pending_queue()
        plans_with_queue = get_all_pending_plans()

        if not all_queue:
            await callback.answer("صف انتظار خالی است.", show_alert=True)
            return

        text = f"⏳ صف انتظار — {len(all_queue)} نفر\n\n"
        for i, item in enumerate(all_queue[:20], 1):
            name = item.get('full_name') or '—'
            username = item.get('username') or '—'
            plan_name = item.get('plan_name') or '—'
            created = item.get('created_at', '')[:16] if item.get('created_at') else '—'
            text += (
                f"{i}. 👤 {name} (@{username})\n"
                f"   🆔 <code>{item['user_id']}</code>\n"
                f"   📦 {plan_name} | 💰 {item['amount']:,} تومان\n"
                f"   📅 {created}\n\n"
            )
        if len(all_queue) > 20:
            text += f"... و {len(all_queue)-20} مورد دیگر\n"

        buttons = []
        for p in plans_with_queue:
            buttons.append([btn(f"📤 پردازش صف «{p['name']}» ({p['waiting_count']} نفر)", f"process_queue_{p['plan_id']}")])
        buttons.append([btn("🗑 حذف از صف", "admin_queue_delete_menu")])
        buttons.append([btn("🔙 بازگشت", "admin_back")])
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_queue_delete_menu")
    async def admin_queue_delete_menu(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        all_queue = get_all_pending_queue()
        if not all_queue:
            await callback.answer("صف انتظار خالی است.", show_alert=True)
            return
        buttons = []
        for item in all_queue[:15]:
            name = item.get('full_name') or str(item['user_id'])
            plan_name = item.get('plan_name') or '—'
            buttons.append([btn(f"🗑 {name} — {plan_name}", f"delete_queue_{item['id']}")])
        buttons.append([btn("🔙 بازگشت", "admin_waiting_queue")])
        await safe_edit(callback, "کدام مورد را از صف حذف کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("delete_queue_"))
    async def delete_queue_item_cb(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        queue_id = int(callback.data.split("_")[2])

        # اطلاعات آیتم قبل از حذف — برای ارسال پیام به کاربر
        conn = get_db()
        item = conn.execute("SELECT * FROM pending_configs WHERE id=?", (queue_id,)).fetchone()
        conn.close()

        delete_queue_item(queue_id)

        # ارسال پیام لغو به کاربر
        if item:
            cancel_msg = get_setting('msg_order_cancelled') or '❌ سفارش شما لغو شد.\nدرصورت نیاز با پشتیبانی تماس بگیرید.'
            try:
                await bot.send_message(item['user_id'], cancel_msg)
            except Exception as e:
                logging.warning(f"Could not send cancel msg to {item['user_id']}: {e}")

        await callback.answer("✅ سفارش لغو و به کاربر اطلاع داده شد")

        # نمایش مجدد صف
        all_queue = get_all_pending_queue()
        if not all_queue:
            await safe_edit(callback, "✅ صف انتظار خالی شد.", reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id))
            return
        buttons = []
        for q in all_queue[:15]:
            name = q.get('full_name') or str(q['user_id'])
            plan_name = q.get('plan_name') or '—'
            buttons.append([btn(f"🗑 {name} — {plan_name}", f"delete_queue_{q['id']}")])
        buttons.append([btn("🔙 بازگشت", "admin_waiting_queue")])
        await safe_edit(callback, f"صف انتظار — {len(all_queue)} نفر\nکدام مورد را حذف کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("process_queue_"))
    async def manual_process_queue(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[2])
        stock = get_config_stock(plan_id)
        if stock == 0:
            await callback.answer("موجودی صفر است! ابتدا کانفیگ اضافه کنید.", show_alert=True)
            return
        await callback.answer("در حال پردازش...")
        sent = await process_waiting_queue(plan_id, callback.from_user.id)
        remaining = get_pending_queue_count(plan_id)
        plan = get_plan(plan_id)
        text = f"✅ پردازش صف پلن «{plan['name']}» انجام شد.\n📤 ارسال شد: {sent} کانفیگ"
        if remaining > 0:
            text += f"\n⏳ باقی‌مانده در صف: {remaining} نفر"
        else:
            text += "\n✅ صف خالی شد."
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id))

    # ── آموزش اتصال (ادمین) ────────────────────────────────────

    @dp.callback_query(F.data == "admin_guides")
    async def admin_guides(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        categories = get_all_guide_categories()
        text = "📖 مدیریت آموزش اتصال\n\n"
        if categories:
            text += "دسته‌های موجود:\n" + "\n".join([f"• {c}" for c in categories])
        else:
            text += "هنوز آموزشی اضافه نشده."
        buttons = [[btn("➕ افزودن/ویرایش آموزش", "admin_guide_add")]]
        if categories:
            buttons.append([btn("🗑 حذف آموزش", "admin_guide_delete")])
        buttons.append([btn("🔙 بازگشت", "admin_back")])
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_guide_add")
    async def admin_guide_add(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_cats = get_plan_categories()
        guide_cats = get_all_guide_categories()
        all_cats = list(set(plan_cats + guide_cats))
        if all_cats:
            buttons = [[btn(f"✏️ {cat}", f"admin_guide_edit_{cat}")] for cat in all_cats]
            buttons.append([btn("➕ دسته جدید", "admin_guide_new_cat")])
            buttons.append([btn("🔙 بازگشت", "admin_guides")])
            await callback.message.edit_text("کدام دسته را ویرایش می‌کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))
        else:
            await state.update_data(guide_category=None)
            await state.set_state(Form.waiting_guide_text)
            await callback.message.edit_text("ابتدا نام دسته را وارد کنید (مثال: v2ray):")

    @dp.callback_query(F.data == "admin_guide_new_cat")
    async def admin_guide_new_cat(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.update_data(guide_category=None)
        await state.set_state(Form.waiting_guide_text)
        await callback.message.edit_text("نام دسته جدید را وارد کنید (مثال: cisco):")

    @dp.callback_query(F.data.startswith("admin_guide_edit_"))
    async def admin_guide_edit(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        category = callback.data.replace("admin_guide_edit_", "", 1)
        current = get_connection_guide(category)
        await state.update_data(guide_category=category)
        await state.set_state(Form.waiting_guide_text)
        await callback.message.edit_text(
            f"آموزش فعلی برای «{category}»:\n\n{current or '—'}\n\n"
            f"متن جدید آموزش را وارد کنید:"
        )

    @dp.message(Form.waiting_guide_text)
    async def save_guide_text(message: types.Message, state: FSMContext):
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        data = await state.get_data()
        category = data.get('guide_category')
        text = message.html_text.strip()

        if category is None:
            # متن اول = نام دسته
            await state.update_data(guide_category=text)
            await message.answer(f"نام دسته: «{text}»\n\nحالا متن آموزش اتصال را وارد کنید:")
            return

        set_connection_guide(category, text)
        await state.clear()
        await message.answer(
            f"✅ آموزش اتصال برای دسته «{category}» ذخیره شد.",
            reply_markup=admin_main_inline(message.from_user.id)
        )

    @dp.callback_query(F.data == "admin_guide_delete")
    async def admin_guide_delete(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        categories = get_all_guide_categories()
        if not categories:
            await callback.answer("آموزشی برای حذف وجود ندارد.", show_alert=True)
            return
        buttons = [[btn(f"🗑 {cat}", f"confirm_delete_guide_{cat}")] for cat in categories]
        buttons.append([btn("🔙 بازگشت", "admin_guides")])
        await callback.message.edit_text("کدام آموزش را حذف کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("confirm_delete_guide_"))
    async def confirm_delete_guide(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        category = callback.data.replace("confirm_delete_guide_", "", 1)
        delete_connection_guide(category)
        await callback.answer(f"✅ آموزش «{category}» حذف شد")
        await safe_edit(callback, "پنل مدیریت:", reply_markup=admin_main_inline(callback.from_user.id))

    # ── تنظیمات ────────────────────────────────────

    @dp.callback_query(F.data == "admin_settings")
    async def admin_settings_cb(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await callback.message.edit_text("تنظیمات ربات:", reply_markup=admin_settings_inline(callback.from_user.id))

    @dp.callback_query(F.data.startswith("setting_"))
    async def edit_setting(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        key = callback.data.replace("setting_", "")
        current = get_setting(key) or "تنظیم نشده"
        await state.update_data(setting_key=key)
        await state.set_state(Form.waiting_setting_value)
        await callback.message.edit_text(f"مقدار فعلی:\n{current}\n\nمقدار جدید را وارد کنید:")

    @dp.message(Form.waiting_setting_value)
    async def save_setting(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS + get_all_admins():
            return
        data = await state.get_data()
        key = data.get('setting_key')
        came_from = data.get('came_from', '')
        import re as _re
        raw_val = message.html_text.strip()
        # فقط برای بررسی reset، تگ‌های tg-emoji رو حذف می‌کنیم
        plain_val = _re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', raw_val)
        # بررسی reset
        if plain_val.strip().lower() == 'reset':
            set_setting(key, None)
        else:
            # مقدار اصلی با تگ‌های پریمیوم ذخیره می‌شه
            set_setting(key, raw_val)
        await state.clear()
        if came_from == "edit_texts":
            # نمایش مجدد لیست ویرایش متن‌ها
            await message.answer(
                f"✅ متن با موفقیت ذخیره شد.\n\nکلید: <code>{key}</code>\n\nمقدار جدید:\n{message.html_text.strip()}",
                parse_mode="HTML",
                reply_markup=ikb_with_color_edit([
                    [btn("✏️ بازگشت به ویرایش متن‌ها", "admin_edit_texts")],
                    [btn("🏠 پنل اصلی", "admin_back")],
                ], user_id=message.from_user.id)
            )
        else:
            await message.answer("✅ تنظیم ذخیره شد.", reply_markup=admin_main_inline(message.from_user.id))


    @dp.callback_query(F.data == "admin_edit_buttons")
    async def admin_edit_buttons(callback, state: FSMContext):
        """ویرایش متن دکمه‌های منوی ربات"""
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        button_list = [
            ("🛒 دکمه خرید سرویس",           "editbtn_btn_buy"),
            ("🎁 دکمه تست رایگان",            "editbtn_btn_free_test"),
            ("🖥️ دکمه حساب کاربری",          "editbtn_btn_account"),
            ("💰 دکمه کیف پول",               "editbtn_btn_wallet"),
            ("⚙️ دکمه نحوه اتصال",            "editbtn_btn_connection"),
            ("👩‍💻 دکمه پشتیبانی",               "editbtn_btn_support"),
            ("🏆 دکمه مسابقات",                "editbtn_btn_tornoment"),
            ("💡 دکمه همکاری و کسب درآمد",   "editbtn_btn_earn"),
            ("🛠 دکمه پنل مدیریت",            "editbtn_btn_admin"),
        ]
        buttons = []
        for label, cb in button_list:
            key = cb.replace("editbtn_", "")
            current = get_setting(key) or "پیش‌فرض"
            buttons.append([btn(f"{label}: {current[:20]}", cb)])
        buttons.append([btn("🔙 بازگشت", "admin_edit_texts")])
        await callback.message.edit_text(
            "🎛 ویرایش دکمه‌های منو\n\n"
            "روی هر دکمه بزنید تا متن آن را ویرایش کنید.\n"
            "برای برگشت به پیش‌فرض کلمه reset را بنویسید.",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("editbtn_"))
    async def editbtn_handler(callback, state: FSMContext):
        """handler ویرایش دکمه‌های منو"""
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        setting_key = callback.data.replace("editbtn_", "", 1)
        current = get_setting(setting_key) or "تنظیم نشده"
        await state.update_data(setting_key=setting_key, came_from="edit_buttons")
        await state.set_state(Form.waiting_setting_value)
        await callback.message.edit_text(
            f"✏️ ویرایش دکمه:\n<code>{setting_key}</code>\n\n"
            f"━━━ مقدار فعلی ━━━\n{current}\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"متن جدید را وارد کنید:\n(برای برگشت به پیش‌فرض کلمه reset را بنویسید)",
            parse_mode="HTML"
        )

    @dp.callback_query(F.data == "admin_edit_texts")
    async def admin_edit_texts(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        texts_list = [
            # ── پیام‌های اصلی ──
            ("👋 متن خوش‌آمدگویی", "edittxt_welcome_text"),
            ("📋 متن معرفی بخش خرید", "edittxt_msg_buy_intro"),
            ("📦 هدر انتخاب دسته سرویس", "edittxt_msg_category_header"),
            ("📝 توضیحات اضافه زیر پلن", "edittxt_msg_plan_desc"),
            # ── خرید و پرداخت ──
            ("✅ متن بعد از ارسال رسید", "edittxt_msg_after_receipt"),
            ("🎉 هدر پیام تأیید سفارش", "edittxt_msg_order_confirm"),
            ("📎 پاورقی پیام کانفیگ", "edittxt_msg_config_footer"),
            # ── صف انتظار ──
            ("⏳ متن صف انتظار (کاربر)", "edittxt_msg_queue_notice"),
            ("📦 متن ارسال کانفیگ از صف", "edittxt_msg_config_from_queue"),
            # ── تست رایگان ──
            ("🎁 متن معرفی تست رایگان", "edittxt_msg_free_test_intro"),
            ("🎁 متن صفحه دعوت شده ها", "edittxt_msg_my_referral_view"),
            ("🎁 متن نبود تست رایگان", "edittxt_msg_no_free_test"),
            ("🎁 متن ارسال کانفیگ رایگان", "edittxt_msg_reach_referral"),
            ("🎁 متن پاداش معرفی", "edittxt_msg_bonus"),
            ("❌ متن نبود مسابقه", "edittxt_msg_no_tornoment"),

            # ── کیف پول ──
            ("💰 متن صفحه کیف پول", "edittxt_msg_wallet_intro"),
            ("✅ متن تأیید شارژ کیف پول", "edittxt_msg_wallet_charge_confirm"),
            # ── پشتیبانی ──
            ("👩‍💻 متن معرفی بخش پشتیبانی", "edittxt_msg_support_intro"),
            ("✉️ متن تأیید ارسال تیکت", "edittxt_msg_support_sent"),
            # ── آموزش اتصال ──
            ("🔌 متن معرفی آموزش اتصال", "edittxt_msg_connection_intro"),
            ("❌ متن لغو سفارش از صف", "edittxt_msg_order_cancelled"),
            # ── پرداخت ──
            ("💳 متن پرداخت کارت به کارت", "edittxt_msg_payment_card"),
            ("🪙 متن پرداخت ارز دیجیتال", "edittxt_msg_payment_crypto"),
            ("💳 متن شارژ کیف پول با کارت", "edittxt_msg_wallet_payment_card"),
            ("❌ متن رد کارت به کارت اتوماتیک", "edittxt_msg_wallet_charge_auto_fail"),
            ("📸 متن درخواست ارسال رسید", "edittxt_msg_wallet_payment_card_send_image"),
            ("❌ متن موجودی ناکافی", "edittxt_msg_insufficient_balance"),
            ("✅ متن تست رایگان فعال شد", "edittxt_msg_free_test_success"),
            ("❌ متن تست رایگان غیرفعال", "edittxt_msg_free_test_unavailable"),
 # ("📝 متن صفحه نمایش سرویس", "edittxt_msg_service_message_page_free"),
            ("📢 متن عضویت اجباری", "edittxt_msg_mandatory_channels"),
            ("📝 متن شارژ کیف پول", "edittxt_msg_wallet_charge_choose_amount"),

        ]
        buttons = [[btn(label, cb)] for label, cb in texts_list]
        # اضافه کردن دکمه متن صفحه پلن‌ها
        buttons.append([btn("📝 متن صفحه هر پلن", "admin_edit_plan_desc")])
        buttons.append([btn("🎛 ویرایش دکمه ها", "admin_edit_buttons")])
        buttons.append([btn("🔙 بازگشت", "admin_settings")])
        await callback.message.edit_text(
            "✏️ ویرایش متن‌های ربات:\n\n(روی هر گزینه بزنید تا متن آن را ویرایش کنید)",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("edit_plan_desc_"))
    async def edit_plan_desc_select(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[3])
        conn = get_db()
        row = conn.execute("SELECT custom_description, name FROM plans WHERE id=?", (plan_id,)).fetchone()
        conn.close()
        current = row['custom_description'] if row and row['custom_description'] else "پیش‌فرض"
        await state.update_data(edit_plan_id=plan_id, edit_plan_field='description')
        await state.set_state(Form.waiting_plan_name)
        txt = "📝 متن فعلی:\n" + current[:150] + "\n\nمتن جدید را وارد کنید:\n(برای برگشت به پیش‌فرض: /reset)"
        await callback.message.edit_text(txt)

    @dp.callback_query(F.data == "admin_edit_plan_desc")
    async def admin_edit_plan_desc(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        plans = get_active_plans()
        if not plans:
            await callback.answer("هیچ پلنی موجود نیست.", show_alert=True)
            return
        buttons = []
        for p in plans:
            label = p.get('custom_label') or p['name']
            has_desc = "✅" if p.get('custom_description') else "➕"
            buttons.append([btn(f"{has_desc} {label}", f"edit_plan_desc_{p['id']}")])
        buttons.append([btn("🔙 بازگشت", "admin_edit_texts")])
        await callback.message.edit_text(
            "📝 متن صفحه هر پلن\n\nکدام پلن را ویرایش می‌کنید؟\n✅ = متن سفارشی دارد | ➕ = پیش‌فرض",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("edittxt_"))
    async def edittxt_handler(callback, state: FSMContext):
        """handler ویرایش همه متن‌های ربات با پیشوند edittxt_"""
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        # استخراج کلید: edittxt_msg_buy_intro → msg_buy_intro
        setting_key = callback.data.replace("edittxt_", "", 1)
        current = get_setting(setting_key) or "تنظیم نشده"
        await state.update_data(setting_key=setting_key, came_from="edit_texts")
        await state.set_state(Form.waiting_setting_value)
        # راهنمای متغیرها برای متن‌های پرداخت
        var_hints = {
            'msg_payment_card': '📌 متغیرها: {card} {owner} {amount}',
            'msg_payment_crypto': '📌 متغیرها: {network} {address} {amount}',
            'msg_wallet_payment_card': '📌 متغیرها: {card} {owner} {amount}',
            'msg_free_test_success': '📌 متغیرها: {config}',
            # 'msg_service_message_page_free': '📌 متغیرها: {service_name} {category} {db_valume} {expire} {days} {config} {used_traffic} {status} {remaining_gb}',
            'msg_insufficient_balance': '📌 متغیرها: {balance} {price} {diff}',
            'msg_wallet_payment_crypto': '📌 متغیرها: {network} {address} {amount}',
            'msg_wallet_charge_confirm': '📌 متغیرها: {amount}',
            'msg_queue_notice': '📌 متغیرها: {pos}',
            'msg_free_test_intro': '📌 متغیرها: {link} {count}',
            'msg_my_referral_view': '📌 متغیرها: {total} {pays} {not_pay}',
            'msg_bonus': '📌 متغیرها: {amount}',
            'msg_reach_referral': '📌 متغیرها: {config}',
        }
        hint = var_hints.get(setting_key, '')
        await callback.message.edit_text(
            f"📝 ویرایش متن:\n<code>{setting_key}</code>\n\n"
            f"━━━ مقدار فعلی ━━━\n{current}\n\n"
            f"{hint + chr(10) if hint else ''}"
            f"━━━━━━━━━━━━━━━━━\n"
            f"متن جدید را وارد کنید:",
            parse_mode="HTML"
        )

    # ── پیام همگانی ────────────────────────────────────

    @dp.callback_query(F.data == "admin_broadcast")
    async def broadcast_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_broadcast)
        await callback.message.edit_text(
            "📢 متن پیام همگانی را بنویسید:\n\n"
            "💡 فرمت‌بندی تلگرام پشتیبانی میشه — bold، italic، quote و... همه حفظ میشن.",
            parse_mode="HTML"
        )

    @dp.message(Form.waiting_broadcast)
    async def do_broadcast(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS:
            return
        await state.clear()
        conn = get_db()
        users = conn.execute("SELECT telegram_id FROM users WHERE is_banned=0").fetchall()
        conn.close()
        sent, failed = 0, 0
        for u in users:
            try:
                await bot.send_message(u['telegram_id'], message.html_text, parse_mode="HTML")
                sent += 1
            except:
                failed += 1
        await message.answer(f"📢 ارسال شد: {sent}\n❌ ناموفق: {failed}", reply_markup=admin_main_inline(message.from_user.id))

    # ── تست رایگان ────────────────────────────────────

    @dp.callback_query(F.data == "admin_free_tests")
    async def admin_free_tests(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        conn = get_db()
        test_configs = conn.execute("SELECT * FROM free_test_configs WHERE is_used=0").fetchall()
        conn.close()
        text = "🎁 کانفیگ‌های تست رایگان موجود:\n\n"
        if test_configs:
            text += f"📊 کل موجود: {len(test_configs)}\n\n"
            for i, tc in enumerate(test_configs[:5], 1):
                text += f"{i}. <code>{tc['config_data'][:40]}...</code>\n"
            if len(test_configs) > 5:
                text += f"... و {len(test_configs) - 5} مورد دیگر"
        else:
            text = "❌ هیچ تست رایگانی موجود نیست."
        buttons = [[btn("➕ افزودن تست‌های جدید", "admin_add_free_test")]]
        if test_configs:
            buttons.append([btn("🗑 حذف تست", "admin_delete_free_test")])

        buttons.append([btn("⏳ صف انتظار کانفیگ رایگان", "admin_free_test_queue")])
        buttons.append([btn("🔙 بازگشت", "admin_back")])
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_add_free_test")
    async def admin_add_free_test_start(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_test_config_data)
        await state.update_data(test_count=0)
        await callback.message.edit_text(
            "هر پیام = یک کانفیگ تست\n(هر متنی که ارسال کنید به عنوان یک کانفیگ ذخیره می‌شود)\n\nوقتی تمام شد /done بنویسید:"
        )

    @dp.message(Form.waiting_test_config_data)
    async def test_config_data(message: types.Message, state: FSMContext):
        if not is_bot_admin(message.from_user.id, ADMIN_IDS):
            return
        if message.text.strip() == "/done":
            data = await state.get_data()
            count = data.get('test_count', 0)
            await state.clear()

            from .handlers_user import bot
            from .helpers import process_free_test_queue
            sent = await process_free_test_queue(bot)
            print("HERE")
            msg = f"✅ {count} کانفیگ تست اضافه شد!"
            if sent > 0:
                msg += f"\n📤 تعداد {sent} کانفیگ تست به صورت خودکار برای کاربران در صف انتظار ارسال شد."

            await message.answer(msg, reply_markup=admin_main_inline(message.from_user.id))
            return
        config_text = message.html_text.strip()
        if not config_text:
            await message.answer("متن نمی‌تواند خالی باشد.")
            return
        conn = get_db()
        conn.execute("INSERT INTO free_test_configs (config_data) VALUES (?)", (config_text,))
        conn.commit()
        conn.close()
        data = await state.get_data()
        prev = data.get('test_count', 0)
        await state.update_data(test_count=prev + 1)
        await message.answer(f"✅ کانفیگ #{prev+1} ذخیره شد.\nبیشتر بفرست یا /done بزن.")

    @dp.callback_query(F.data == "admin_delete_free_test")
    async def admin_delete_free_test(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        conn = get_db()
        configs = conn.execute("SELECT id FROM free_test_configs WHERE is_used=0 ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        if not configs:
            await callback.answer("موردی برای حذف نیست.", show_alert=True)
            return
        buttons = [[btn(f"🗑 تست #{c['id']}", f"confirm_delete_free_test_{c['id']}")] for c in configs]
        buttons.append([btn("🔙 بازگشت", "admin_free_tests")])
        await callback.message.edit_text("کدام تست را حذف می‌کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_free_test_queue")
    async def admin_free_test_queue_view(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return

        queue = get_free_test_queue()

        if not queue:
            await callback.answer("صف انتظار تست رایگان خالی است.", show_alert=True)
            return

        text = f"⏳ صف انتظار تست رایگان — {len(queue)} نفر\n\n"
        for i, item in enumerate(queue[:20], 1):
            name = item.get('full_name') or '—'
            username = item.get('username') or '—'
            created = item.get('created_at', '')[:16] if item.get('created_at') else '—'
            text += (
                f"{i}. 👤 {name} (@{username})\n"
                f"   🆔 <code>{item['user_id']}</code>\n"
                f"   📅 {created}\n\n"
            )

        if len(queue) > 20:
            text += f"... و {len(queue)-20} مورد دیگر\n"

        buttons = [[btn("🔙 بازگشت", "admin_free_tests")]]
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("confirm_delete_free_test_"))
    async def confirm_delete_free_test(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        test_id = int(callback.data.split("_")[-1])
        conn = get_db()
        conn.execute("DELETE FROM free_test_configs WHERE id=?", (test_id,))
        conn.commit()
        conn.close()
        await callback.answer("✅ حذف شد")
        await safe_edit(callback, "پنل مدیریت:", reply_markup=admin_main_inline(callback.from_user.id))

    # ── مدیریت ادمین‌ها ────────────────────────────────────

    @dp.callback_query(F.data == "admin_manage_admins")
    async def admin_manage_admins(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        conn = get_db()
        all_admins_rows = conn.execute(
            "SELECT telegram_id, role FROM admin_users WHERE is_active=1"
        ).fetchall()
        conn.close()
        role_icons = {"channel": "📢", "bot": "🤖", "both": "👑"}
        role_names = {"channel": "ادمین کانال", "bot": "ادمین ربات", "both": "ادمین کانال+ربات"}
        text = "👥 ادمین‌های ربات:\n\n⭐ ادمین‌های اصلی:\n"
        for admin_id in ADMIN_IDS:
            text += f"  👑 <code>{admin_id}</code>\n"
        if all_admins_rows:
            text += "\n✅ ادمین‌های اضافه شده:\n"
            for row in all_admins_rows:
                icon = role_icons.get(row["role"], "📢")
                name = role_names.get(row["role"], row["role"])
                text += f"  {icon} <code>{row['telegram_id']}</code> — {name}\n"
        buttons = [
            [btn("➕ افزودن ادمین جدید", "admin_add_new_admin")],
            [btn("🗑 حذف ادمین", "admin_remove_admin")],
            [btn("🔙 بازگشت", "admin_back")],
        ]
        await safe_edit(callback, text, reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data == "admin_add_new_admin")
    async def admin_add_new_admin(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_admin_id)
        await callback.message.edit_text("آیدی عددی ادمین جدید را وارد کنید:\n(مثال: 123456789)")

    @dp.message(Form.waiting_admin_id)
    async def add_new_admin_handler(message: types.Message, state: FSMContext):
        if not is_bot_admin(message.from_user.id, ADMIN_IDS):
            return
        try:
            admin_id = int(message.text.strip())
        except:
            await message.answer("آیدی باید عدد باشد. دوباره وارد کنید:")
            return
        if admin_id in ADMIN_IDS:
            await state.clear()
            await message.answer("❌ این کاربر سوپرادمین است و قابل ویرایش نیست.")
            return
        current_role = get_admin_role(admin_id)
        role_names = {"channel": "ادمین کانال 📢", "bot": "ادمین ربات 🤖", "both": "ادمین کانال+ربات 👑"}
        extra = ""
        if current_role:
            extra = f"\n\n⚠️ این کاربر الان «{role_names.get(current_role, current_role)}» است."
        await state.update_data(new_admin_id=admin_id)
        await state.set_state(Form.waiting_admin_role)
        await message.answer(
            f"نقش ادمین <code>{admin_id}</code> را انتخاب کنید:{extra}",
            parse_mode="HTML",
            reply_markup=ikb_with_color_edit([
                [btn("📢 ادمین کانال (تیکت + رسید)", "set_admin_role_channel")],
                [btn("🤖 ادمین ربات (پنل مدیریت)", "set_admin_role_bot")],
                [btn("👑 ادمین کامل (همه دسترسی‌ها)", "set_admin_role_both")],
                [btn("❌ انصراف", "admin_back")],
            ], user_id=message.from_user.id)
        )

    @dp.callback_query(F.data.startswith("set_admin_role_"))
    async def set_admin_role(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        role = callback.data.replace("set_admin_role_", "")
        data = await state.get_data()
        admin_id = data.get("new_admin_id")
        if not admin_id:
            await state.clear()
            await callback.message.edit_text("❌ خطا. دوباره تلاش کنید.", reply_markup=admin_main_inline(callback.from_user.id))
            return
        role_labels = {"channel": "ادمین کانال 📢", "bot": "ادمین ربات 🤖", "both": "ادمین کانال و ربات 👑"}
        was_existing = get_admin_role(admin_id) is not None
        if add_admin_user(admin_id, callback.from_user.id, role):
            await state.clear()
            action = "آپدیت شد" if was_existing else "اضافه شد"
            await callback.message.edit_text(
                f"✅ کاربر <code>{admin_id}</code> با نقش «{role_labels[role]}» {action}!",
                parse_mode="HTML", reply_markup=admin_main_inline(callback.from_user.id)
            )
            try:
                await bot.send_message(admin_id, f"🎉 دسترسی شما آپدیت شد.\nنقش: {role_labels[role]}")
            except:
                pass
        else:
            await state.clear()
            await callback.message.edit_text("❌ خطا در اضافه کردن ادمین.", reply_markup=admin_main_inline())

    @dp.callback_query(F.data == "admin_remove_admin")
    async def admin_remove_admin(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        all_admins = get_all_admins()
        all_admins.pop(-1)
        if not all_admins:
            await callback.answer("هیچ ادمین اضافه شده‌ای موجود نیست.", show_alert=True)
            return
        buttons = [[btn(f"🗑 {admin_id}", f"confirm_remove_admin_{admin_id}")] for admin_id in all_admins]
        buttons.append([btn("🔙 بازگشت", "admin_back")])
        await callback.message.edit_text("کدام ادمین را حذف کنید؟", reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id))

    @dp.callback_query(F.data.startswith("confirm_remove_admin_"))
    async def confirm_remove_admin(callback):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        admin_id = int(callback.data.split("_")[3])
        remove_admin_user(admin_id)
        await callback.answer("✅ حذف شد")
        await safe_edit(callback, f"✅ ادمین {admin_id} حذف شد.", reply_markup=ikb_with_color_edit([[btn("🔙 بازگشت", "admin_back")]], user_id=callback.from_user.id))

    # ── خاموشی ربات ────────────────────────────────────

    @dp.callback_query(F.data == "shutdown_bot")
    async def shutdown_confirm(callback, state: FSMContext):
        if not await check_shutdown(callback): return
        if not await admin_only(callback): return
        await state.set_state(Form.waiting_shutdown_msg)
        await callback.message.edit_text(
            "⚠️ خاموشی ربات\n\nمتن پیامی را که برای کاربران نمایش داده شود وارد کنید:\n\n(مثال: ربات برای به‌روزرسانی موقتاً خاموش است)"
        )

    @dp.message(Form.waiting_shutdown_msg)
    async def set_shutdown_msg(message: types.Message, state: FSMContext):
        global BOT_SHUTDOWN
        admins = ADMIN_IDS + get_all_admins()
        if message.from_user.id not in admins:
            return
        shutdown_msg = message.text
        await state.clear()
        BOT_SHUTDOWN = True
        try:
            with open('/tmp/bot_shutdown.txt', 'w', encoding='utf-8') as f:
                f.write(shutdown_msg)
        except:
            pass
        all_users = get_all_users()
        admins_list = ADMIN_IDS + get_all_admins()
        for user_id in all_users:
            if user_id in admins_list:
                continue
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ {shutdown_msg}\n\nپس از اتمام به‌روزرسانی دوباره فعال خواهیم شد.",
                    reply_markup=ikb_with_color_edit([[btn("🔄 بررسی وضعیت", "check_bot_status")]], user_id=message.from_user.id)
                )
            except:
                pass
        await message.answer(
            f"✅ ربات خاموش شد.\n\nپیام برای کاربران:\n{shutdown_msg}",
            reply_markup=ikb_with_color_edit([[btn("🔄 روشن کردن", "turn_on_bot")]], user_id=message.from_user.id)
        )

    @dp.callback_query(F.data == "check_bot_status")
    async def check_bot_status(callback):
        global BOT_SHUTDOWN
        if BOT_SHUTDOWN:
            try:
                with open('/tmp/bot_shutdown.txt', 'r', encoding='utf-8') as f:
                    msg = f.read()
                await callback.answer(f"⚠️ {msg}", show_alert=True)
            except:
                await callback.answer("⚠️ ربات در حال حاضر خاموش است", show_alert=True)
        else:
            await callback.answer("✅ ربات فعال است", show_alert=True)

    @dp.callback_query(F.data == "turn_on_bot")
    async def turn_on_bot(callback):
        global BOT_SHUTDOWN
        admins = ADMIN_IDS + get_all_admins()
        if callback.from_user.id not in admins:
            await callback.answer("❌ دسترسی غیرمجاز", show_alert=True)
            return
        BOT_SHUTDOWN = False
        try:
            import os
            os.remove('/tmp/bot_shutdown.txt')
        except:
            pass
        all_users = get_all_users()
        admins_list = ADMIN_IDS + get_all_admins()
        for user_id in all_users:
            if user_id in admins_list:
                continue
            try:
                await bot.send_message(user_id, "✅ ربات دوباره فعال شد!")
            except:
                pass
        await callback.message.edit_text(
            "✅ ربات روشن شد و در دسترس کاربران است.",
            reply_markup=admin_main_inline(callback.from_user.id)
        )
