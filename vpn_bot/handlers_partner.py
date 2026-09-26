"""
handlers_partner.py — ربات مادر
بخش همکاری: ثبت همکار، شارژ حساب، تایید ادمین
"""
from aiogram import Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging

from .config import ADMIN_IDS
from .database import get_db
from .helpers import (
    get_setting, get_partner, get_partner_by_id, get_all_admins,
    charge_partner_balance, create_partner_charge_request,
    get_partner_charge_request, confirm_partner_charge,
    reject_partner_charge, get_partner_stats, get_partner_transactions
)
from .keyboards import ikbe
from .handlers_user import bot

def ikb(buttons): return InlineKeyboardMarkup(inline_keyboard=buttons)
def btn(text, cb): return ikbe(text=text, callback_data=cb)

def _channel(channel_id):
    """تبدیل آیدی کانال به فرمت صحیح"""
    if not channel_id:
        return None
    channel_id = str(channel_id).strip()
    if channel_id.startswith("@"):
        return channel_id
    try:
        return int(channel_id)
    except:
        return channel_id

class PartnerForm(StatesGroup):
    waiting_partner_token = State()
    waiting_partner_numeric_id = State()
    waiting_partner_receipt = State()
    waiting_partner_charge_amount = State()
    waiting_partner_charge_receipt = State()

def register_partner_handlers(dp: Dispatcher):

    def all_admins():
        return ADMIN_IDS + get_all_admins()

    # ── ثبت درخواست همکاری ────────────────────────────────────

    @dp.callback_query(F.data == "partner_unlock")
    async def partner_unlock_start(callback, state: FSMContext):
        partner = get_partner(callback.from_user.id)
        if partner and partner['is_active']:
            await callback.answer("شما قبلاً همکار فعال هستید!", show_alert=True)
            return
        fee = int(get_setting('partner_fee') or 10000000)
        await callback.message.edit_text(
            f"🤝 <b>فعال‌سازی همکاری</b>\n\n"
            f"💰 هزینه: <b>{fee:,} تومان</b>\n\n"
            f"توکن ربات تلگرام خود را ارسال کنید:",
            parse_mode="HTML",
            reply_markup=ikb([[btn("❌ انصراف", "back_earn")]])
        )
        await state.set_state(PartnerForm.waiting_partner_token)

    @dp.message(PartnerForm.waiting_partner_token)
    async def get_partner_token(message: types.Message, state: FSMContext):
        token = (message.text or "").strip()
        if not token:
            await message.answer("❌ لطفاً توکن را به صورت متن ارسال کنید:")
            return
        if ":" not in token or len(token) < 30:
            await message.answer("❌ توکن نامعتبر. از @BotFather توکن بگیرید:")
            return
        await state.update_data(partner_token=token)
        await state.set_state(PartnerForm.waiting_partner_numeric_id)
        await message.answer("✅ توکن دریافت شد.\n\nآیدی عددی تلگرام خود را ارسال کنید:")

    @dp.message(PartnerForm.waiting_partner_numeric_id)
    async def get_partner_numeric_id(message: types.Message, state: FSMContext):
        try:
            numeric_id = int((message.text or "").strip())
        except:
            await message.answer("❌ آیدی باید عدد باشد:")
            return

        existing = get_partner(message.from_user.id)
        if existing:
            await state.clear()
            await message.answer("❌ شما قبلاً درخواست همکاری دارید.")
            return

        await state.update_data(partner_numeric_id=numeric_id)

        fee = int(get_setting('partner_fee') or 10000000)
        card = get_setting('card_number') or '—'
        owner = get_setting('card_owner') or '—'
        await message.answer(
            f"✅ آیدی دریافت شد.\n\n"
            f"💳 لطفاً هزینه فعال‌سازی را واریز کنید:\n"
            f"💰 مبلغ: <b>{fee:,} تومان</b>\n"
            f"💳 شماره کارت: <code>{card}</code>\n"
            f"👤 به نام: {owner}\n\n"
            f"📸 پس از واریز، تصویر رسید را ارسال کنید:",
            parse_mode="HTML"
        )
        await state.set_state(PartnerForm.waiting_partner_receipt)

    @dp.message(PartnerForm.waiting_partner_receipt)
    async def get_partner_receipt(message: types.Message, state: FSMContext):
        file_id = None
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document:
            file_id = message.document.file_id

        if not file_id:
            await message.answer("❌ لطفاً تصویر رسید را ارسال کنید:")
            return

        data = await state.get_data()
        token = data.get('partner_token')
        numeric_id = data.get('partner_numeric_id')
        await state.clear()

        # ثبت همکار در دیتابیس
        conn = get_db()
        conn.execute(
            "INSERT OR IGNORE INTO partners (telegram_id, bot_token, is_active, balance, credit_limit) VALUES (?,?,0,0,0)",
            (message.from_user.id, token)
        )
        conn.commit(); conn.close()

        fee = int(get_setting('partner_fee') or 10000000)
        caption = (
            f"🤝 <b>درخواست همکاری جدید</b>\n\n"
            f"👤 نام: {message.from_user.full_name}\n"
            f"🆔 آیدی: <code>{message.from_user.id}</code>\n"
            f"📊 آیدی عددی: <code>{numeric_id}</code>\n"
            f"🤖 توکن: <code>{token}</code>\n"
            f"💰 مبلغ واریزی: <b>{fee:,} تومان</b>"
        )
        confirm_kb = ikb([[
            btn("✅ تایید", f"approve_partner_{message.from_user.id}"),
            btn("❌ رد", f"reject_partner_{message.from_user.id}"),
        ]])

        # فقط به کانال فیش‌ها ارسال میشه
        receipt_channel = get_setting('receipt_channel_id') or get_setting('support_channel_id')
        ch = _channel(receipt_channel)
        sent = False
        if ch:
            try:
                await bot.send_photo(ch, file_id, caption=caption, parse_mode="HTML", reply_markup=confirm_kb)
                sent = True
            except Exception as e:
                logging.error(f"ارسال به کانال: {e}")

        if not sent:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_photo(admin_id, file_id, caption=caption, parse_mode="HTML", reply_markup=confirm_kb)
                except: pass

        await message.answer(
            "✅ درخواست همکاری شما ثبت شد.\n"
            "پس از بررسی توسط ادمین، نتیجه اعلام خواهد شد."
        )

    # ── تایید/رد همکار ────────────────────────────────────

    @dp.callback_query(F.data.startswith("approve_partner_"))
    async def approve_partner(callback):
        if callback.from_user.id not in all_admins():
            await callback.answer("دسترسی ندارید", show_alert=True); return
        partner_tid = int(callback.data.split("_")[2])
        conn = get_db()
        conn.execute("UPDATE partners SET is_active=1 WHERE telegram_id=?", (partner_tid,))
        conn.commit(); conn.close()
        try:
            await bot.send_message(
                partner_tid,
                "🎉 <b>درخواست همکاری شما تایید شد!</b>\n\n"
                "برای شارژ حساب کانفیگ، از بخش «همکاری» اقدام کنید.",
                parse_mode="HTML"
            )
        except: pass
        await callback.answer("✅ همکار فعال شد")
        try:
            new_cap = (callback.message.caption or callback.message.text or '') + "\n\n✅ <b>تایید شد</b>"
            if callback.message.photo:
                await callback.message.edit_caption(new_cap, parse_mode="HTML")
            else:
                await callback.message.edit_text(new_cap, parse_mode="HTML")
        except: pass

    @dp.callback_query(F.data.startswith("reject_partner_"))
    async def reject_partner_cb(callback):
        if callback.from_user.id not in all_admins():
            await callback.answer("دسترسی ندارید", show_alert=True); return
        partner_tid = int(callback.data.split("_")[2])
        conn = get_db()
        conn.execute("DELETE FROM partners WHERE telegram_id=? AND is_active=0", (partner_tid,))
        conn.commit(); conn.close()
        try:
            await bot.send_message(partner_tid, "❌ درخواست همکاری شما رد شد.")
        except: pass
        await callback.answer("❌ رد شد")
        try:
            new_cap = (callback.message.caption or callback.message.text or '') + "\n\n❌ <b>رد شد</b>"
            if callback.message.photo:
                await callback.message.edit_caption(new_cap, parse_mode="HTML")
            else:
                await callback.message.edit_text(new_cap, parse_mode="HTML")
        except: pass

    # ── شارژ حساب کانفیگ ────────────────────────────────────

    @dp.callback_query(F.data == "partner_charge_config")
    async def partner_charge_config_start(callback, state: FSMContext):
        partner = get_partner(callback.from_user.id)
        if not partner or not partner['is_active']:
            await callback.answer("حساب همکاری فعال نیست", show_alert=True); return
        stats = get_partner_stats(partner['id'])
        await callback.message.edit_text(
            f"💰 <b>شارژ حساب کانفیگ</b>\n\n"
            f"موجودی فعلی: <b>{stats['balance']:,} تومان</b>\n\n"
            f"مبلغ شارژ را وارد کنید (تومان):",
            parse_mode="HTML",
            reply_markup=ikb([[btn("❌ انصراف", "partner_panel_menu")]])
        )
        await state.set_state(PartnerForm.waiting_partner_charge_amount)

    @dp.message(PartnerForm.waiting_partner_charge_amount)
    async def partner_charge_amount(message: types.Message, state: FSMContext):
        partner = get_partner(message.from_user.id)
        if not partner: await state.clear(); return
        try:
            amount = int((message.text or "").strip().replace(",", ""))
            if amount < 100000: raise ValueError
        except:
            await message.answer("❌ حداقل ۱۰۰,۰۰۰ تومان:"); return
        await state.update_data(charge_amount=amount)
        card = get_setting('card_number') or '—'
        owner = get_setting('card_owner') or '—'
        await message.answer(
            f"💳 مبلغ: <b>{amount:,} تومان</b>\n"
            f"💳 کارت: <code>{card}</code>\n"
            f"👤 به نام: {owner}\n\n"
            f"📸 تصویر رسید را ارسال کنید:",
            parse_mode="HTML"
        )
        await state.set_state(PartnerForm.waiting_partner_charge_receipt)

    @dp.message(PartnerForm.waiting_partner_charge_receipt)
    async def partner_charge_receipt(message: types.Message, state: FSMContext):
        partner = get_partner(message.from_user.id)
        if not partner: await state.clear(); return
        data = await state.get_data()
        amount = data.get('charge_amount')
        await state.clear()

        file_id = None
        if message.photo: file_id = message.photo[-1].file_id
        elif message.document: file_id = message.document.file_id

        if not file_id:
            await message.answer("❌ لطفاً تصویر رسید ارسال کنید.")
            return

        req_id = create_partner_charge_request(partner['id'], amount, 'card')
        conn = get_db()
        conn.execute("UPDATE partner_charge_requests SET receipt_file_id=? WHERE id=?", (file_id, req_id))
        conn.commit(); conn.close()

        caption = (
            f"💰 <b>درخواست شارژ کانفیگ همکار</b>\n\n"
            f"👤 {message.from_user.full_name}\n"
            f"🆔 <code>{message.from_user.id}</code>\n"
            f"💵 مبلغ: <b>{amount:,} تومان</b>\n"
            f"🔖 درخواست: #{req_id}"
        )
        confirm_kb = ikb([[
            btn("✅ تایید شارژ", f"confirm_partner_charge_{req_id}"),
            btn("❌ رد", f"reject_partner_charge_{req_id}"),
        ]])

        # فقط به کانال فیش‌ها ارسال میشه
        receipt_channel = get_setting('receipt_channel_id') or get_setting('support_channel_id')
        ch = _channel(receipt_channel)
        sent = False
        if ch:
            try:
                await bot.send_photo(ch, file_id, caption=caption, parse_mode="HTML", reply_markup=confirm_kb)
                sent = True
            except Exception as e:
                logging.error(f"ارسال شارژ کانال: {e}")

        if not sent:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_photo(admin_id, file_id, caption=caption, parse_mode="HTML", reply_markup=confirm_kb)
                except: pass

        await message.answer("✅ درخواست شارژ ثبت شد. پس از تایید ادمین، موجودی شما افزوده می‌شود.")

    # ── تایید/رد شارژ ────────────────────────────────────

    @dp.callback_query(F.data.startswith("confirm_partner_charge_"))
    async def confirm_partner_charge_cb(callback):
        if callback.from_user.id not in all_admins():
            await callback.answer("دسترسی ندارید", show_alert=True); return
        req_id = int(callback.data.split("_")[3])
        req = confirm_partner_charge(req_id)
        if not req:
            await callback.answer("درخواست یافت نشد یا قبلاً پردازش شده", show_alert=True); return
        partner = get_partner_by_id(req['partner_id'])
        if partner:
            try:
                await bot.send_message(
                    partner['telegram_id'],
                    f"✅ حساب کانفیگ شما شارژ شد!\n💰 مبلغ: <b>{req['amount']:,} تومان</b>",
                    parse_mode="HTML"
                )
            except: pass
        await callback.answer("✅ شارژ تایید شد")
        try:
            txt = (callback.message.caption or callback.message.text or '') + "\n\n✅ <b>شارژ تایید شد</b>"
            if callback.message.photo:
                await callback.message.edit_caption(txt, parse_mode="HTML")
            else:
                await callback.message.edit_text(txt, parse_mode="HTML")
        except: pass

    @dp.callback_query(F.data.startswith("reject_partner_charge_"))
    async def reject_partner_charge_cb(callback):
        if callback.from_user.id not in all_admins():
            await callback.answer("دسترسی ندارید", show_alert=True); return
        req_id = int(callback.data.split("_")[3])
        req = get_partner_charge_request(req_id)
        if not req: return
        reject_partner_charge(req_id)
        partner = get_partner_by_id(req['partner_id'])
        if partner:
            try:
                await bot.send_message(partner['telegram_id'], f"❌ درخواست شارژ #{req_id} رد شد.")
            except: pass
        await callback.answer("❌ رد شد")
        try:
            txt = (callback.message.caption or callback.message.text or '') + "\n\n❌ <b>رد شد</b>"
            if callback.message.photo:
                await callback.message.edit_caption(txt, parse_mode="HTML")
            else:
                await callback.message.edit_text(txt, parse_mode="HTML")
        except: pass

    # ── پنل همکار ────────────────────────────────────

    @dp.callback_query(F.data == "partner_panel_menu")
    async def partner_panel_menu(callback):
        partner = get_partner(callback.from_user.id)
        if not partner or not partner['is_active']:
            await callback.answer("حساب همکاری فعال نیست", show_alert=True); return
        stats = get_partner_stats(partner['id'])
        await callback.message.edit_text(
            f"🤝 <b>پنل همکاری</b>\n\n"
            f"💰 موجودی کانفیگ: <b>{stats['balance']:,} تومان</b>\n"
            f"📦 کل سفارشات: {stats['total_orders']}\n"
            f"💸 کل هزینه: {stats['total_spent']:,} تومان",
            parse_mode="HTML",
            reply_markup=ikb([
                [btn("💰 شارژ حساب کانفیگ", "partner_charge_config")],
                [btn("📊 تاریخچه تراکنش‌ها", "partner_transactions")],
                [btn("🔙 بازگشت", "back_earn")],
            ])
        )

    @dp.callback_query(F.data == "partner_transactions")
    async def partner_transactions_view(callback):
        partner = get_partner(callback.from_user.id)
        if not partner: return
        txs = get_partner_transactions(partner['id'], limit=15)
        if not txs:
            await callback.answer("تراکنشی وجود ندارد", show_alert=True); return
        text = "📊 <b>آخرین تراکنش‌ها:</b>\n\n"
        for tx in txs:
            sign = "+" if tx['amount'] > 0 else ""
            text += f"{'🟢' if tx['amount'] > 0 else '🔴'} {sign}{tx['amount']:,} — {tx['description'] or ''}\n"
            text += f"   📅 {tx['created_at'][:16]}\n\n"
        await callback.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=ikb([[btn("🔙 بازگشت", "partner_panel_menu")]])
        )
