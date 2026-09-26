"""
handlers_admin_partners.py — ربات مادر
پنل ادمین: مدیریت همکارها و انبار کانفیگ همکار
"""
from aiogram import Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup
import logging

from .config import ADMIN_IDS
from .database import get_db
from .helpers import (
    get_all_admins, get_all_partners, get_partner_by_id, update_partner,
    charge_partner_balance, deduct_partner_balance, get_partner_stats,
    get_partner_transactions, add_partner_config,
    get_available_partner_config_names, get_all_partner_config_stock_summary,
    get_partner_plans,
    get_all_partner_plans, create_global_partner_plan,
    delete_global_partner_plan, get_global_partner_plan,
)
from .handlers_user import bot
from .keyboards import ikb_with_color_edit,ikbe

def ikb(b): return InlineKeyboardMarkup(inline_keyboard=b)
def btn(t, c): return ikbe(text=t, callback_data=c)

async def safe_edit(cb, text, reply_markup=None):
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e): raise

class AdminPartnerForm(StatesGroup):
    waiting_partner_credit_limit = State()
    waiting_partner_charge_amount = State()
    waiting_partner_deduct_amount = State()
    waiting_partner_config_name = State()
    waiting_partner_config_cost = State()
    waiting_partner_config_data = State()
    waiting_partner_config_volume = State()
    # پلن‌های عمومی همکار
    plan_name     = State()
    plan_category = State()
    plan_volume   = State()
    plan_duration = State()
    plan_devices  = State()
    plan_cost     = State()

def register_admin_partner_handlers(dp: Dispatcher):

    def all_admins():
        return ADMIN_IDS + get_all_admins()

    async def admin_only(callback):
        if callback.from_user.id not in all_admins():
            await callback.answer("دسترسی ندارید", show_alert=True)
            return False
        return True

    # ── منوی مدیریت همکارها ────────────────────────────────────

    @dp.callback_query(F.data == "admin_partners")
    async def admin_partners_menu(callback):
        if not await admin_only(callback): return
        partners = get_all_partners()
        active = [p for p in partners if p['is_active']]
        inactive = [p for p in partners if not p['is_active']]
        text = (f"🤝 <b>مدیریت همکارها</b>\n\n"
                f"✅ فعال: {len(active)}\n"
                f"⏳ در انتظار تایید: {len(inactive)}")
        await safe_edit(callback, text, reply_markup=ikb([
            [btn("📋 لیست همکارها", "admin_partners_list")],
            [btn("📦 انبار کانفیگ همکارها", "admin_partner_configs")],
            [btn("🔙 بازگشت", "admin_back")],
        ]))

    @dp.callback_query(F.data == "admin_partners_list")
    async def admin_partners_list(callback):
        if not await admin_only(callback): return
        partners = get_all_partners()
        if not partners:
            await callback.answer("هیچ همکاری ثبت نشده", show_alert=True); return
        buttons = []
        for p in partners:
            status = "✅" if p['is_active'] else "⏳"
            buttons.append([btn(
                f"{status} آیدی: {p['telegram_id']} | موجودی: {p['balance']:,}",
                f"admin_partner_detail_{p['id']}"
            )])
        buttons.append([btn("🔙 بازگشت", "admin_partners")])
        await safe_edit(callback, "📋 لیست همکارها:", reply_markup=ikb(buttons))

    @dp.callback_query(F.data.startswith("admin_partner_detail_"))
    async def admin_partner_detail(callback):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        partner = get_partner_by_id(partner_id)
        if not partner:
            await callback.answer("همکار یافت نشد", show_alert=True); return
        stats = get_partner_stats(partner_id)
        plans = get_partner_plans(partner_id)
        status = "✅ فعال" if partner['is_active'] else "⏳ در انتظار"
        text = (
            f"🤝 <b>جزئیات همکار</b>\n\n"
            f"🆔 آیدی: <code>{partner['telegram_id']}</code>\n"
            f"📊 وضعیت: {status}\n"
            f"💰 موجودی: <b>{stats['balance']:,} تومان</b>\n"
            f"🔝 سقف اعتبار: {stats['credit_limit']:,} تومان\n"
            f"📦 تعداد پلن: {len(plans)}\n"
            f"✅ کل سفارشات: {stats['total_orders']}\n"
            f"💸 کل هزینه: {stats['total_spent']:,} تومان"
        )
        await safe_edit(callback, text, reply_markup=ikb([
            [btn("💰 شارژ موجودی", f"admin_partner_charge_{partner_id}"),
             btn("➖ کسر موجودی", f"admin_partner_deduct_{partner_id}")],
            [btn("🔝 تنظیم سقف", f"admin_partner_limit_{partner_id}")],
            [btn("📊 تاریخچه", f"admin_partner_history_{partner_id}")],
            [btn("✅ فعال/غیرفعال", f"admin_partner_toggle_{partner_id}")],
            [btn("🔙 بازگشت", "admin_partners_list")],
        ]))

    @dp.callback_query(F.data.startswith("admin_partner_toggle_"))
    async def admin_partner_toggle(callback):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        partner = get_partner_by_id(partner_id)
        if not partner: return
        new_status = 0 if partner['is_active'] else 1
        update_partner(partner_id, is_active=new_status)
        label = "✅ فعال شد" if new_status else "❌ غیرفعال شد"
        await callback.answer(label)

    @dp.callback_query(F.data.startswith("admin_partner_charge_"))
    async def admin_partner_charge_start(callback, state: FSMContext):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        await state.update_data(target_partner_id=partner_id)
        await state.set_state(AdminPartnerForm.waiting_partner_charge_amount)
        await callback.message.edit_text("💰 مبلغ شارژ را وارد کنید (تومان):")

    @dp.message(AdminPartnerForm.waiting_partner_charge_amount)
    async def admin_partner_charge_do(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            amount = int(message.text.strip().replace(",", ""))
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        data = await state.get_data()
        partner_id = data['target_partner_id']
        await state.clear()
        charge_partner_balance(partner_id, amount, "شارژ توسط ادمین")
        partner = get_partner_by_id(partner_id)
        await message.answer(f"✅ {amount:,} تومان به حساب همکار اضافه شد.")
        if partner:
            try:
                await bot.send_message(partner['telegram_id'], f"✅ حساب کانفیگ شما {amount:,} تومان شارژ شد.")
            except: pass

    @dp.callback_query(F.data.startswith("admin_partner_deduct_"))
    async def admin_partner_deduct_start(callback, state: FSMContext):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        await state.update_data(target_partner_id=partner_id)
        await state.set_state(AdminPartnerForm.waiting_partner_deduct_amount)
        await callback.message.edit_text("➖ مبلغ کسر را وارد کنید (تومان):")

    @dp.message(AdminPartnerForm.waiting_partner_deduct_amount)
    async def admin_partner_deduct_do(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            amount = int(message.text.strip().replace(",", ""))
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        data = await state.get_data()
        partner_id = data['target_partner_id']
        await state.clear()
        ok = deduct_partner_balance(partner_id, amount, "کسر توسط ادمین")
        if ok:
            await message.answer(f"✅ {amount:,} تومان کسر شد.")
        else:
            await message.answer("❌ موجودی کافی نیست.")

    @dp.callback_query(F.data.startswith("admin_partner_limit_"))
    async def admin_partner_limit_start(callback, state: FSMContext):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        await state.update_data(target_partner_id=partner_id)
        await state.set_state(AdminPartnerForm.waiting_partner_credit_limit)
        partner = get_partner_by_id(partner_id)
        await callback.message.edit_text(
            f"🔝 سقف فعلی: {partner['credit_limit']:,} تومان\n\nسقف جدید را وارد کنید:")

    @dp.message(AdminPartnerForm.waiting_partner_credit_limit)
    async def admin_partner_limit_do(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            limit = int(message.text.strip().replace(",", ""))
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        data = await state.get_data()
        partner_id = data['target_partner_id']
        await state.clear()
        update_partner(partner_id, credit_limit=limit)
        await message.answer(f"✅ سقف اعتبار به {limit:,} تومان تنظیم شد.")

    @dp.callback_query(F.data.startswith("admin_partner_history_"))
    async def admin_partner_history(callback):
        if not await admin_only(callback): return
        partner_id = int(callback.data.split("_")[3])
        txs = get_partner_transactions(partner_id, limit=15)
        if not txs:
            await callback.answer("تراکنشی وجود ندارد", show_alert=True); return
        text = "📊 <b>تاریخچه همکار:</b>\n\n"
        for tx in txs:
            sign = "+" if tx['amount'] > 0 else ""
            text += f"{'🟢' if tx['amount'] > 0 else '🔴'} {sign}{tx['amount']:,} — {tx['description'] or ''}\n"
            text += f"   📅 {tx['created_at'][:16]}\n\n"
        await safe_edit(callback, text, reply_markup=ikb([[btn("🔙 بازگشت", f"admin_partner_detail_{partner_id}")]]))

    # ── انبار کانفیگ همکارها ────────────────────────────────────

    @dp.callback_query(F.data == "admin_partner_configs")
    async def admin_partner_configs(callback):
        if not await admin_only(callback): return
        summary = get_all_partner_config_stock_summary()
        text = "📦 <b>انبار کانفیگ همکارها</b>\n\n"
        if summary:
            for item in summary:
                cost_txt = f" | 💰 {item['cost']:,} ت" if item.get('cost') else ""
                text += f"• <b>{item['name']}</b>{cost_txt}: موجود {item['available']} / کل {item['total']}\n"
        else:
            text += "انبار خالی است.\n"
        buttons = []
        for item in summary:
            buttons.append([btn(
                f"📦 {item['name']} — موجود: {item['available']}",
                f"admin_pconfig_detail_{item['name']}"
            )])
        buttons.append([btn("➕ پلن جدید + افزودن کانفیگ", "admin_add_partner_config")])
        buttons.append([btn("🔙 بازگشت", "admin_partners")])
        await safe_edit(callback, text, reply_markup=ikb(buttons))

    @dp.callback_query(F.data.startswith("admin_pconfig_detail_"))
    async def admin_pconfig_detail(callback):
        if not await admin_only(callback): return
        name = callback.data[21:]
        summary = get_all_partner_config_stock_summary()
        item = next((i for i in summary if i['name'] == name), None)
        if not item:
            await callback.answer("پلن یافت نشد.", show_alert=True); return
        cost_txt = f"{item['cost']:,} تومان" if item.get('cost') else "رایگان"
        text = (
            f"📦 <b>{item['name']}</b>\n\n"
            f"💾 حجم: {item['volume_gb']} گیگ\n"
            f"📊 موجود: {item['available']} / کل: {item['total']}\n"
            f"💰 هزینه برای همکار: {cost_txt}"
        )
        await safe_edit(callback, text, reply_markup=ikb([
            [btn("➕ افزودن کانفیگ", f"admin_addconfig_to_{name}")],
            [btn("🗑 حذف این پلن", f"admin_del_pconfig_{name}")],
            [btn("🔙 بازگشت", "admin_partner_configs")],
        ]))

    @dp.callback_query(F.data.startswith("admin_addconfig_to_"))
    async def admin_addconfig_to_plan(callback, state: FSMContext):
        if not await admin_only(callback): return
        name = callback.data[19:]
        await state.update_data(partner_config_name=name, partner_config_count=0, adding_to_existing=True)
        await state.set_state(AdminPartnerForm.waiting_partner_config_volume)
        # حجم رو از summary بگیر
        summary = get_all_partner_config_stock_summary()
        item = next((i for i in summary if i['name'] == name), None)
        if item:
            await state.update_data(partner_config_volume=item['volume_gb'], partner_config_count=0)
            await state.set_state(AdminPartnerForm.waiting_partner_config_cost)
            await callback.message.edit_text(
                f"📦 افزودن کانفیگ به پلن <b>{name}</b>\n\n"
                f"💰 قیمت هر کانفیگ برای همکار را وارد کنید (تومان):\n"
                f"برای رایگان عدد 0 وارد کنید:",
                parse_mode="HTML"
            )
        else:
            await state.set_state(AdminPartnerForm.waiting_partner_config_volume)
            await callback.message.edit_text(f"💾 حجم کانفیگ‌های پلن <b>{name}</b> را وارد کنید (گیگ):", parse_mode="HTML")

    @dp.callback_query(F.data.startswith("admin_del_pconfig_"))
    async def admin_del_pconfig(callback):
        if not await admin_only(callback): return
        name = callback.data[18:]
        from .database import get_db as _get_db
        conn = _get_db()
        deleted = conn.execute(
            "DELETE FROM configs_partners WHERE name=? AND is_used=0", (name,)
        ).rowcount
        conn.commit()
        conn.close()
        await callback.answer(f"✅ {deleted} کانفیگ از پلن «{name}» حذف شد.")
        # برگشت به لیست
        summary = get_all_partner_config_stock_summary()
        text = "📦 <b>انبار کانفیگ همکارها</b>\n\n"
        if summary:
            for item in summary:
                cost_txt = f" | 💰 {item['cost']:,} ت" if item.get('cost') else ""
                text += f"• <b>{item['name']}</b>{cost_txt}: موجود {item['available']} / کل {item['total']}\n"
        else:
            text += "انبار خالی است.\n"
        buttons = []
        for item in summary:
            buttons.append([btn(f"📦 {item['name']} — موجود: {item['available']}", f"admin_pconfig_detail_{item['name']}")])
        buttons.append([btn("➕ پلن جدید + افزودن کانفیگ", "admin_add_partner_config")])
        buttons.append([btn("🔙 بازگشت", "admin_partners")])
        await safe_edit(callback, text, reply_markup=ikb(buttons))

    @dp.callback_query(F.data == "admin_add_partner_config")
    async def admin_add_partner_config_start(callback, state: FSMContext):
        if not await admin_only(callback): return
        await state.update_data(adding_to_existing=False, partner_config_count=0)
        await state.set_state(AdminPartnerForm.waiting_partner_config_name)
        await callback.message.edit_text(
            "➕ <b>پلن جدید</b>\n\nاسم پلن را وارد کنید (مثال: v2ray-1g):",
            parse_mode="HTML"
        )

    @dp.message(AdminPartnerForm.waiting_partner_config_name)
    async def admin_partner_config_name(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        name = message.text.strip()
        await state.update_data(partner_config_name=name)
        await state.set_state(AdminPartnerForm.waiting_partner_config_volume)
        await message.answer(f"اسم: <b>{name}</b>\n\nحجم (گیگ) را وارد کنید:", parse_mode="HTML")

    @dp.message(AdminPartnerForm.waiting_partner_config_volume)
    async def admin_partner_config_volume(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            volume = int(message.text.strip())
            if volume <= 0: raise ValueError
        except:
            await message.answer("❌ عدد مثبت وارد کنید:"); return
        await state.update_data(partner_config_volume=volume, partner_config_count=0)
        await state.set_state(AdminPartnerForm.waiting_partner_config_cost)
        await message.answer(
            f"💰 قیمت هر کانفیگ برای همکار را وارد کنید (تومان):\n"
            f"این مبلغ به ازای هر فروش از موجودی همکار کسر می‌شود.\n"
            f"برای رایگان عدد 0 وارد کنید:"
        )

    @dp.message(AdminPartnerForm.waiting_partner_config_cost)
    async def admin_partner_config_cost(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            cost = int(message.text.strip().replace(",", ""))
            if cost < 0: raise ValueError
        except:
            await message.answer("❌ عدد معتبر وارد کنید:"); return
        await state.update_data(partner_config_cost=cost)
        await state.set_state(AdminPartnerForm.waiting_partner_config_data)
        data = await state.get_data()
        await message.answer(
            f"📦 افزودن کانفیگ — <b>{data['partner_config_name']}</b> ({data['partner_config_volume']} گیگ)\n"
            f"💰 هزینه برای همکار: <b>{cost:,} تومان</b>\n\n"
            f"می‌توانید در هر پیام چند کانفیگ بفرستید:\n"
            f"کانفیگ‌ها را با یک <b>خط خالی</b> از هم جدا کنید.\n\n"
            f"مثال:\n"
            f"<code>vless://config1...\n\nvless://config2...\n\nvless://config3...</code>\n\n"
            f"وقتی تمام شد /done بزن:",
            parse_mode="HTML"
        )
    @dp.message(AdminPartnerForm.waiting_partner_config_data)
    async def admin_partner_config_data(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return

        if message.text and message.text.strip() == "/done":
            data = await state.get_data()
            count = data.get('partner_config_count', 0)
            await state.clear()
            await message.answer(f"✅ {count} کانفیگ به انبار همکار اضافه شد!")
            return

        raw = message.html_text.strip() if message.text else ""
        if not raw:
            await message.answer("متن نمی‌تواند خالی باشد."); return

        # تقسیم بر اساس خط خالی — هر بلوک یک کانفیگ
        blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]

        if not blocks:
            await message.answer("❌ هیچ کانفیگی پیدا نشد."); return

        data = await state.get_data()
        name   = data['partner_config_name']
        volume = data['partner_config_volume']
        cost   = data.get('partner_config_cost', 0)
        prev   = data.get('partner_config_count', 0)

        for config_text in blocks:
            add_partner_config(name, config_text, volume, cost)

        new_count = prev + len(blocks)
        await state.update_data(partner_config_count=new_count)
        await message.answer(
            f"✅ {len(blocks)} کانفیگ ذخیره شد. (مجموع تا الان: {new_count})\n"
            f"بیشتر بفرست یا /done بزن."
        )
    # ── مدیریت پلن‌های عمومی همکار ────────────────────────────────────────

    @dp.callback_query(F.data == "admin_partner_plans")
    async def admin_partner_plans_menu(callback):
        if not await admin_only(callback): return
        def fmt_volume(v): return "نامحدود" if v == -1 else f"{v} گیگ"
        def fmt_duration(d): return "نامحدود" if d == -1 else f"{d} روز"
        plans = get_all_partner_plans(active_only=False)
        text = "🗂 <b>پلن‌های همکار</b>\n\n"
        if plans:
            for p in plans:
                status = "✅" if p['is_active'] else "❌"
                text += (f"{status} <b>{p['name']}</b> | {p['category']}\n"
                         f"   💾 {p['volume_gb']} گیگ | ⏱ {p['duration_days']} روز"
                         f" | 💰 هزینه: {p['cost']:,} ت\n\n")
        else:
            text += "هیچ پلنی ساخته نشده.\n"
        buttons = [[btn("➕ پلن جدید", "admin_add_partner_plan")]]
        for p in plans:
            buttons.append([btn(
                f"🗑 حذف — {p['name']} ({p['cost']:,} ت)",
                f"admin_del_partner_plan_{p['id']}"
            )])
        buttons.append([btn("🔙 بازگشت", "admin_partners")])
        await safe_edit(callback, text, reply_markup=ikb(buttons))

    @dp.callback_query(F.data == "admin_add_partner_plan")
    async def admin_add_partner_plan_start(callback, state: FSMContext):
        if not await admin_only(callback): return
        await state.set_state(AdminPartnerForm.plan_name)
        await callback.message.edit_text("📦 نام پلن را وارد کنید (مثال: v2ray 1 گیگ):")

    @dp.message(AdminPartnerForm.plan_name)
    async def admin_partner_plan_name(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        await state.update_data(plan_name=message.text.strip())
        await state.set_state(AdminPartnerForm.plan_category)
        await message.answer("📁 دسته‌بندی را وارد کنید (مثال: v2ray، cisco):")

    @dp.message(AdminPartnerForm.plan_category)
    async def admin_partner_plan_category(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        await state.update_data(plan_category=message.text.strip())
        await state.set_state(AdminPartnerForm.plan_volume)
        await message.answer("💾 حجم را وارد کنید (گیگابایت، برای نامحدود -1):")

    @dp.message(AdminPartnerForm.plan_volume)
    async def admin_partner_plan_volume(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            vol = int(message.text.strip())
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        await state.update_data(plan_volume=vol)
        await state.set_state(AdminPartnerForm.plan_duration)
        await message.answer("⏱ مدت را وارد کنید (روز، برای نامحدود -1):")

    @dp.message(AdminPartnerForm.plan_duration)
    async def admin_partner_plan_duration(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            dur = int(message.text.strip())
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        await state.update_data(plan_duration=dur)
        await state.set_state(AdminPartnerForm.plan_devices)
        await message.answer("💻 تعداد دستگاه را وارد کنید:")

    @dp.message(AdminPartnerForm.plan_devices)
    async def admin_partner_plan_devices(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            devs = int(message.text.strip())
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        await state.update_data(plan_devices=devs)
        await state.set_state(AdminPartnerForm.plan_cost)
        await message.answer("💰 قیمت هر کانفیگ برای همکار را وارد کنید (تومان):\n"
                             "این مبلغ به ازای هر فروش از موجودی همکار کسر می‌شود.")

    @dp.message(AdminPartnerForm.plan_cost)
    async def admin_partner_plan_cost(message: types.Message, state: FSMContext):
        if message.from_user.id not in all_admins(): return
        try:
            cost = int(message.text.strip().replace(",", ""))
        except:
            await message.answer("❌ عدد وارد کنید:"); return
        data = await state.get_data()
        plan_id = create_global_partner_plan(
            data['plan_name'], data['plan_category'],
            data['plan_volume'], data['plan_duration'],
            data['plan_devices'], cost,
        )
        await state.clear()
        await message.answer(
            f"✅ پلن «{data['plan_name']}» با هزینه {cost:,} تومان ساخته شد.\n"
            f"شناسه: #{plan_id}"
        )

    @dp.callback_query(F.data.startswith("admin_del_partner_plan_"))
    async def admin_del_partner_plan(callback, state: FSMContext):
        if not await admin_only(callback): return
        plan_id = int(callback.data.split("_")[4])
        plan = get_global_partner_plan(plan_id)
        if not plan:
            await callback.answer("پلن یافت نشد.", show_alert=True); return
        delete_global_partner_plan(plan_id)
        await callback.answer(f"✅ پلن «{plan['name']}» حذف شد.")
        # برگشت به لیست
        plans = get_all_partner_plans(active_only=False)
        text = "🗂 <b>پلن‌های همکار</b>\n\n"
        if plans:
            for p in plans:
                status = "✅" if p['is_active'] else "❌"
                text += (f"{status} <b>{p['name']}</b> | {p['category']}\n"
                         f"   💾 {p['volume_gb']} گیگ | ⏱ {p['duration_days']} روز"
                         f" | 💰 هزینه: {p['cost']:,} ت\n\n")
        else:
            text += "هیچ پلنی ساخته نشده.\n"
        buttons = [[btn("➕ پلن جدید", "admin_add_partner_plan")]]
        for p in plans:
            buttons.append([btn(
                f"🗑 حذف — {p['name']} ({p['cost']:,} ت)",
                f"admin_del_partner_plan_{p['id']}"
            )])
        buttons.append([btn("🔙 بازگشت", "admin_partners")])
        await safe_edit(callback, text, reply_markup=ikb(buttons))
