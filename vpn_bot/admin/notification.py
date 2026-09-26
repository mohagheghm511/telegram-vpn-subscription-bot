# notification.py
"""
Self-contained notification system.

Features:
  - Per-type configurable timing (hours)
  - Per-type configurable message with {variable} placeholders
  - Per-type selectable buttons (toggle on/off from admin panel)
  - Duplicate prevention via notification_log table
  - Admin panel for full management
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from vpn_bot.database import (
    NotificationLog,
    NotificationRule,
    Plan,
    Service,
    Session,
)


def _fetch_expiring_services(window_start: str, window_end: str):
    """Synchronous helper: fetch services expiring within the given window."""
    with Session() as session:
        return (
            session.query(Service, Plan)
            .join(Plan, Service.plan_id == Plan.id)
            .filter(
                Service.is_active == 1,
                Service.expires_at >= window_start,
                Service.expires_at <= window_end,
            )
            .all()
        )

# Import bot from handlers_user (same pattern as handlers_admin)
from vpn_bot.handlers_user import bot
from vpn_bot.keyboards import ikb_with_color_edit, ikbe
from vpn_bot.utils import only_admin

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
#  BUTTON PRESETS  (per notification type)
# ═══════════════════════════════════════════════════
# Each entry: {"key": unique_id, "text": button label, "callback_data": callback}
# callback_data may contain {var} placeholders filled at send-time.
BUTTON_PRESETS: dict[str, list[dict]] = {
    # "inactive_user": [
    #     {"key": "buy_service", "text": "⚡ خرید سرویس", "callback_data": "back_plans"},
    #     {"key": "charge_wallet", "text": "💰 شارژ کیف پول", "callback_data": "back_wallet"},
    # ],
    "service_expiry": [
        {"key": "renew_service", "text": "🔄 جزییات سرویس", "callback_data": "srv_{service_id}"},
        {"key": "buy_service", "text": "⚡ خرید سرویس جدید", "callback_data": "back_plans"},
        {"key": "charge_wallet", "text": "💰 شارژ کیف پول", "callback_data": "back_wallet"},
    ],
    "service_volume_90": [
        {"key": "service_detail", "text": "جزئیات سرویس", "callback_data": "srv_{service_id}"},
        {"key": "buy_service", "text": "⚡ خرید سرویس جدید", "callback_data": "back_plans"},
        {"key": "charge_wallet", "text": "💰 شارژ کیف پول", "callback_data": "back_wallet"},
    ],
    "service_time_expired": [
        {"key": "service_detail", "text": "جزئیات سرویس", "callback_data": "srv_{service_id}"},
        {"key": "buy_service", "text": "⚡ خرید سرویس جدید", "callback_data": "back_plans"},
        {"key": "charge_wallet", "text": "💰 شارژ کیف پول", "callback_data": "back_wallet"},
    ],
}


# ═══════════════════════════════════════════════════
#  DEFAULT RULES  (seeded on first run)
# ═══════════════════════════════════════════════════
DEFAULT_RULES = [
    # {
    #     "type_key": "inactive_user",
    #     "is_enabled": 0,
    #     "hours": 24,
    #     "message": "",
    #     "buttons_json": json.dumps(["buy_service", "charge_wallet"]),
    #     "variables": "full_name",
    #     "info": "یادآوری کاربر غیرفعال (بدون خرید)",
    # },
    {
        "type_key": "service_expiry",
        "is_enabled": 0,
        "hours": 48,
        "message": "",
        "buttons_json": json.dumps(["renew_service", "buy_service", "charge_wallet"]),
        "variables": "service_name,expires_at,remaining_time",
        "info": "هشدار انقضای سرویس",
    },
    {
        "type_key": "service_volume_90",
        "is_enabled": 0,
        "hours": 1,
        "message": "⚠️ هشدار مصرف حجم\n\n📦 سرویس: {service_name}\n📥 مصرف شده: {used_mb} MB\n📤 باقیمانده: {remaining_mb} MB\n📊 کل حجم: {total_mb} MB\n\n۹۰٪ حجم سرویس شما مصرف شده است.",
        "buttons_json": json.dumps(["service_detail", "buy_service", "charge_wallet"]),
        "variables": "service_name,used_mb,remaining_mb,total_mb,service_id,category",
        "info": "مصرف ۹۰٪ حجم سرویس",
    },
    {
        "type_key": "service_time_expired",
        "is_enabled": 0,
        "hours": 1,
        "message": "⌛ زمان سرویس شما به پایان رسید.\n\n📦 سرویس: {service_name}\n📅 زمان انقضا: {expire_at}\n\nبرای ادامه استفاده، سرویس جدید خریداری کنید.",
        "buttons_json": json.dumps(["service_detail", "buy_service", "charge_wallet"]),
        "variables": "service_name,expire_at,service_id,category",
        "info": "پایان زمان سرویس",
    },
]


# ═══════════════════════════════════════════════════
#  FSM STATES
# ═══════════════════════════════════════════════════
class NotifForm(StatesGroup):
    waiting_notif_hours = State()
    waiting_notif_text = State()


# ═══════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════
def btn(text: str, callback_data: str):
    return ikbe(text=text, callback_data=callback_data)


async def _safe_edit(callback: types.CallbackQuery, text: str, reply_markup=None):
    """Edit message text/caption, ignoring 'not modified' errors."""
    try:
        if callback.message.photo or callback.message.video or callback.message.document:
            await callback.message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await callback.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise


def build_keyboard(type_key: str, user_id: int, **format_kwargs) -> list:
    """
    Build inline keyboard rows from a notification rule's enabled buttons.
    format_kwargs are used to fill {var} placeholders in callback_data.
    """
    rule = NotificationRule.get_by_key(type_key)
    if not rule:
        return []

    try:
        enabled_keys = json.loads(rule.buttons_json)
    except (json.JSONDecodeError, TypeError):
        enabled_keys = []

    presets = BUTTON_PRESETS.get(type_key, [])
    rows = []

    for preset in presets:
        if preset["key"] not in enabled_keys:
            continue
        callback_data = preset["callback_data"]
        # Fill placeholders like {service_id} in callback_data
        try:
            callback_data = callback_data.format(**format_kwargs)
        except (KeyError, ValueError):
            pass
        rows.append([ikbe(text=preset["text"], callback_data=callback_data)])

    return rows


def seed_default_rules():
    """Create default notification rules if they don't exist yet."""
    for defaults in DEFAULT_RULES:
        existing = NotificationRule.get_by_key(defaults["type_key"])
        if not existing:
            session = Session()
            rule = NotificationRule(**defaults)
            session.add(rule)
            session.commit()
            session.close()
            log.info(f"Seeded notification rule: {defaults['type_key']}")


async def send_notification(
    user_id: int,
    type_key: str,
    target_id: int = 0,
    **template_vars,
):
    """
    Send a notification to a user if not already sent.
    Returns True if sent, False if skipped or failed.
    """
    if await asyncio.to_thread(NotificationLog.has_sent, user_id, type_key, target_id):
        return False

    rule = await asyncio.to_thread(NotificationRule.get_by_key, type_key)
    if not rule or not rule.message:
        return False

    try:
        text = rule.message.format(**template_vars)
    except (KeyError, ValueError) as e:
        log.warning(f"Failed to format notification template for {type_key}: {e}")
        return False

    kb_rows = build_keyboard(type_key, user_id, **template_vars)
    kb = ikb_with_color_edit(kb_rows, user_id=user_id) if kb_rows else None

    try:
        if kb:
            await bot.send_message(user_id, text=text, reply_markup=kb)
        else:
            await bot.send_message(user_id, text=text)
        await asyncio.to_thread(NotificationLog.mark_sent, user_id, type_key, target_id)
        return True
    except TelegramForbiddenError:
        await asyncio.to_thread(NotificationLog.mark_sent, user_id, type_key, target_id)
        log.error(f"Notification to {user_id} blocked by user")
        return False
    except Exception as e:
        if "Bad Request: chat not found" in str(e):
            log.error(f"Notification to {user_id} blocked by user")
            await asyncio.to_thread(NotificationLog.mark_sent, user_id, type_key, target_id)
            return False

        log.error(f"Failed to send notification to {user_id} (marked as sent): {e}")
        await asyncio.to_thread(NotificationLog.mark_sent, user_id, type_key, target_id)
        return False


# ═══════════════════════════════════════════════════
#  BACKGROUND TASKS
# ═══════════════════════════════════════════════════

# async def inactive_user_notifier_task(bot: Bot):
#     """
#     Checks every 10 minutes for users who registered >= X hours ago
#     but never bought anything (buy_count == 0).
#     Sends a reminder once per user.
#     """
#     while True:
#         try:
#             rule = NotificationRule.get_enabled("inactive_user")
#             if not rule or not rule.message or rule.hours <= 0:
#                 await asyncio.sleep(10 * 60)
#                 continue

#             cutoff = (datetime.now() - timedelta(hours=rule.hours)).isoformat()

#             with Session() as session:
#                 users = (
#                     session.query(User)
#                     .filter(
#                         User.buy_count == 0,
#                         User.is_banned == 0,
#                         User.joined_at <= cutoff,
#                     )
#                     .all()
#                 )

#                 for user in users:
#                     await send_notification(
#                         user_id=user.telegram_id,
#                         type_key="inactive_user",
#                         full_name=user.full_name or "",
#                     )

#         except Exception as e:
#             log.error(f"inactive_user_notifier_task error: {e}")

#         await asyncio.sleep(10 * 60)


async def service_expiry_notifier_task(bot: Bot):
    """
    Checks every 30 minutes for active services expiring within X hours.
    Sends a warning once per service.
    """
    while True:
        try:
            rule = await asyncio.to_thread(NotificationRule.get_enabled, "service_expiry")
            if not rule or not rule.message or rule.hours <= 0:
                await asyncio.sleep(30 * 60)
                continue

            now = datetime.now()
            window_start = now.isoformat()
            window_end = (now + timedelta(hours=rule.hours)).isoformat()

            services = await asyncio.to_thread(_fetch_expiring_services, window_start, window_end)
            for svc, plan in services:
                    # do not send to free test
                    if plan.price <= 0:
                        continue
                    # Calculate remaining time for template

                    try:
                        expires_at = svc.expires_at
                        if expires_at and expires_at.endswith("Z"):
                            expires_at = expires_at[:-1]
                        expiry_dt = datetime.fromisoformat(expires_at) if expires_at else now
                        remaining = expiry_dt - now
                        days_left = remaining.days
                        hours_left = remaining.seconds // 3600
                        if days_left > 0:
                            time_str = f"{days_left} روز و {hours_left} ساعت"
                        else:
                            time_str = f"{hours_left} ساعت"
                    except:
                        time_str = svc.expires_at[:16] if svc.expires_at else "—"

                    # TODO: send notification for services that has been renewed
                    await send_notification(
                        user_id=svc.user_id,
                        type_key="service_expiry",
                        target_id=svc.id,
                        service_id=svc.id,
                        service_name=svc.service_name or "—",
                        expires_at=svc.expires_at[:16] if svc.expires_at else "—",
                        remaining_time=time_str,
                    )

        except Exception as e:
            log.error(f"service_expiry_notifier_task error: {e}")

        await asyncio.sleep(30 * 60)


# ═══════════════════════════════════════════════════
#  ADMIN PANEL  (register via register_notification_handlers)
# ═══════════════════════════════════════════════════

def _hours_label(type_key: str) -> str:
    """Human-readable timing description."""
    if type_key == "inactive_user":
        return "بعد از ثبت‌نام"
    elif type_key == "service_expiry":
        return "قبل از انقضا"
    elif type_key == "service_volume_90":
        return "(تنظیم ساعتی ندارد)"
    elif type_key == "service_time_expired":
        return "در زمان اتمام"
    return ""


def register_notification_handlers(dp: Dispatcher):
    """Register all admin callback/message handlers for notification management."""

    # ── List all notification rules ──────────────────

    @dp.callback_query(F.data == "admin_notifications")
    @only_admin
    async def notif_list(callback: types.CallbackQuery):
        rules = NotificationRule.get_all()
        if not rules:
            await _safe_edit(
                callback,
                "🔔 مدیریت اعلان‌ها\n\n❌ هیچ قانون اعلانی وجود ندارد.\nربات را ری‌استارت کنید تا قوانین پیش‌فرض ایجاد شوند.",
                reply_markup=ikb_with_color_edit(
                    [[btn("🔙 بازگشت", "admin_back")]],
                    user_id=callback.from_user.id,
                ),
            )
            return

        text = "🔔 مدیریت اعلان‌ها\n\n"
        for i, r in enumerate(rules, 1):
            icon = "🟢" if r.is_enabled else "🔴"
            text += f"{i}. {icon} {r.info}\n"
            text += f"   ⏱ {r.hours} ساعت {_hours_label(r.type_key)}\n\n"

        buttons = []
        for r in rules:
            buttons.append([btn(f"⚙️ {r.info}", f"notif_detail_{r.type_key}")])
        buttons.append([btn("🔙 بازگشت", "admin_back")])

        await _safe_edit(
            callback, text,
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id),
        )

    # ── Detail / edit page for one rule ──────────────

    @dp.callback_query(F.data.startswith("notif_detail_"))
    @only_admin
    async def notif_detail(callback: types.CallbackQuery, type_key_override: str = None):
        type_key = type_key_override or callback.data.replace("notif_detail_", "")
        rule = NotificationRule.get_by_key(type_key)
        if not rule:
            await callback.answer("❌ قانون یافت نشد", show_alert=True)
            return

        status = "✅ فعال" if rule.is_enabled else "❌ غیرفعال"
        msg_preview = rule.message if rule.message else "تنظیم نشده"

        # Show enabled buttons
        btn_hint = ""
        try:
            enabled_keys = json.loads(rule.buttons_json)
            presets = BUTTON_PRESETS.get(type_key, [])
            enabled_names = []
            for p in presets:
                if p["key"] in enabled_keys:
                    enabled_names.append(p["text"])
            if enabled_names:
                btn_hint = "\n📌 دکمه‌ها: " + " | ".join(enabled_names)
        except Exception:
            pass

        text = (
            f"🔔 {rule.info}\n\n"
            f"وضعیت: {status}\n"
            f"⏱ زمان: {rule.hours} ساعت {_hours_label(type_key)}\n"
            f"{btn_hint}\n\n"
            f"💬 متن پیام:\n{msg_preview}"
        )

        buttons = [
            [btn("✏️ تغییر متن", f"notif_set_text_{type_key}")],
            [btn("⏱ تغییر زمان", f"notif_set_hours_{type_key}")],
            [btn("🔘 مدیریت دکمه‌ها", f"notif_buttons_{type_key}")],
            [btn("🧪 تست ارسال", f"notif_test_{type_key}")],
            [
                btn(
                    "🔴 غیرفعال کردن" if rule.is_enabled else "🟢 فعال کردن",
                    f"notif_toggle_{type_key}",
                )
            ],
            [btn("🔙 بازگشت", "admin_notifications")],
        ]
        await _safe_edit(
            callback, text,
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id),
        )

    # ── Test notification ───────────────────────────

    @dp.callback_query(F.data.startswith("notif_test_"))
    @only_admin
    async def notif_test(callback: types.CallbackQuery):
        type_key = callback.data.replace("notif_test_", "")
        rule = NotificationRule.get_by_key(type_key)
        if not rule:
            await callback.answer("❌ قانون یافت نشد", show_alert=True)
            return

        if not rule.message:
            await callback.answer("❌ ابتدا متن اعلان را تنظیم کنید", show_alert=True)
            return

        admin_id = callback.from_user.id

        # Build mock variables for preview
        mock_vars = {}
        if type_key == "inactive_user":
            mock_vars["full_name"] = callback.from_user.full_name or "کاربر تست"
        elif type_key == "service_expiry":
            mock_vars["service_name"] = "سرویس تست"
            mock_vars["expires_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            mock_vars["remaining_time"] = "2 روز و 5 ساعت"
            mock_vars["service_id"] = "0"
        elif type_key == "service_volume_90":
            mock_vars["service_name"] = "سرویس تست"
            mock_vars["used_mb"] = "4500.0"
            mock_vars["remaining_mb"] = "500.0"
            mock_vars["total_mb"] = "5000.0"
            mock_vars["service_id"] = "0"
            mock_vars["category"] = "v2ray"
        elif type_key == "service_time_expired":
            mock_vars["service_name"] = "سرویس تست"
            mock_vars["expire_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            mock_vars["service_id"] = "0"
            mock_vars["category"] = "v2ray"

        # Try formatting the message
        try:
            text = rule.message.format(**mock_vars)
        except (KeyError, ValueError) as e:
            await callback.answer(f"❌ خطا در متغیرها: {e}", show_alert=True)
            return

        # Build keyboard with mock data
        kb_rows = build_keyboard(type_key, admin_id, **mock_vars)
        kb = ikb_with_color_edit(kb_rows, user_id=admin_id) if kb_rows else None

        try:
            await callback.message.answer(text, reply_markup=kb)
            await callback.answer("✅ پیام تست ارسال شد", show_alert=False)
        except Exception as e:
            await callback.answer(f"❌ خطا در ارسال: {e}", show_alert=True)

    # ── Toggle enabled/disabled ──────────────────────

    @dp.callback_query(F.data.startswith("notif_toggle_"))
    @only_admin
    async def notif_toggle(callback: types.CallbackQuery):
        type_key = callback.data.replace("notif_toggle_", "")
        new_state = NotificationRule.toggle(type_key)
        icon = "فعال" if new_state else "غیرفعال"
        await callback.answer(f"✅ {icon} شد", show_alert=False)
        # Refresh detail page with explicit type_key
        await notif_detail(callback, type_key_override=type_key)

    # ── Set hours ────────────────────────────────────

    @dp.callback_query(F.data.startswith("notif_set_hours_"))
    @only_admin
    async def notif_set_hours(callback: types.CallbackQuery, state: FSMContext):
        type_key = callback.data.replace("notif_set_hours_", "")
        await state.update_data(notif_type_key=type_key)
        await state.set_state(NotifForm.waiting_notif_hours)

        rule = NotificationRule.get_by_key(type_key)
        current = rule.hours if rule else 24
        await callback.message.edit_text(
            f"⏱ تنظیم زمان اعلان\n\n"
            f"مقدار فعلی: {current} ساعت\n\n"
            f"مقدار جدید را وارد کنید (فقط عدد):",
        )

    @dp.message(NotifForm.waiting_notif_hours)
    @only_admin
    async def notif_save_hours(message: types.Message, state: FSMContext):
        try:
            hours = int(message.text.strip())
            if hours < 1:
                raise ValueError
        except (ValueError, TypeError):
            await message.answer("❌ لطفاً یک عدد صحیح بزرگتر از صفر وارد کنید:")
            return

        data = await state.get_data()
        type_key = data.get("notif_type_key")
        if not type_key:
            await state.clear()
            return

        NotificationRule.set_hours(type_key, hours)
        await state.clear()
        await message.answer(f"✅ زمان به {hours} ساعت تغییر کرد.", parse_mode="HTML")

    # ── Set message text ─────────────────────────────

    @dp.callback_query(F.data.startswith("notif_set_text_"))
    @only_admin
    async def notif_set_text(callback: types.CallbackQuery, state: FSMContext):
        type_key = callback.data.replace("notif_set_text_", "")
        await state.update_data(notif_type_key=type_key)
        await state.set_state(NotifForm.waiting_notif_text)

        rule = NotificationRule.get_by_key(type_key)

        # Build variable hint
        var_hint = ""
        if rule and rule.variables:
            vars_formatted = " ".join(f"<code>{{{v.strip()}}}</code>" for v in rule.variables.split(","))
            var_hint = f"\n\n📌 متغیرهای قابل استفاده:\n{vars_formatted}"

        current = rule.message if rule and rule.message else "(خالی)"
        await callback.message.answer(current)
        await callback.message.answer(
            f"{var_hint}\n\n"
            f"متن جدید را ارسال کنید:",
        )

    @dp.message(NotifForm.waiting_notif_text)
    @only_admin
    async def notif_save_text(message: types.Message, state: FSMContext):
        data = await state.get_data()
        type_key = data.get("notif_type_key")
        if not type_key:
            await state.clear()
            return

        NotificationRule.set_message(type_key, message.html_text)
        await state.clear()
        await message.answer("✅ متن اعلان ذخیره شد.", parse_mode="HTML")

    # ── Button management ────────────────────────────

    @dp.callback_query(F.data.startswith("notif_buttons_"))
    @only_admin
    async def notif_buttons(callback: types.CallbackQuery, type_key_override: str = None):
        type_key = type_key_override or callback.data.replace("notif_buttons_", "")
        rule = NotificationRule.get_by_key(type_key)
        if not rule:
            await callback.answer("❌ قانون یافت نشد", show_alert=True)
            return

        try:
            enabled_keys = set(json.loads(rule.buttons_json))
        except (json.JSONDecodeError, TypeError):
            enabled_keys = set()

        presets = BUTTON_PRESETS.get(type_key, [])
        buttons = []

        for p in presets:
            is_on = p["key"] in enabled_keys
            icon = "🟢" if is_on else "🔴"
            buttons.append([btn(f"{p['text']} {icon}", f"notif_btn_toggle_{type_key}:{p['key']}")])

        buttons.append([btn("🔙 بازگشت", f"notif_detail_{type_key}")])

        await _safe_edit(
            callback,
            f"🔘 مدیریت دکمه‌ها — {rule.info}\n\n"
            f"روی هر دکمه بزنید تا فعال/غیرفعال شود:",
            reply_markup=ikb_with_color_edit(buttons, user_id=callback.from_user.id),
        )

    @dp.callback_query(F.data.startswith("notif_btn_toggle_"))
    @only_admin
    async def notif_btn_toggle(callback: types.CallbackQuery):
        # Parse: notif_btn_toggle_{type_key}:{btn_key}
        # Using ':' as separator to avoid ambiguity with underscores in keys
        data = callback.data or ""
        after_prefix = data[len("notif_btn_toggle_"):]
        colon_idx = after_prefix.find(":")
        if colon_idx == -1:
            await callback.answer("❌ خطا", show_alert=True)
            return

        type_key = after_prefix[:colon_idx]
        btn_key = after_prefix[colon_idx + 1:]

        rule = NotificationRule.get_by_key(type_key)
        if not rule:
            await callback.answer("❌ قانون یافت نشد", show_alert=True)
            return

        try:
            enabled_keys = set(json.loads(rule.buttons_json))
        except (json.JSONDecodeError, TypeError):
            enabled_keys = set()

        if btn_key in enabled_keys:
            enabled_keys.discard(btn_key)
        else:
            enabled_keys.add(btn_key)

        NotificationRule.set_buttons(type_key, json.dumps(sorted(enabled_keys)))
        await callback.answer("✅ تغییر کرد", show_alert=False)

        # Refresh the buttons page with explicit type_key
        await notif_buttons(callback, type_key_override=type_key)
