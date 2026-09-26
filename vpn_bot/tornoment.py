from datetime import datetime, timezone, timedelta
import jdatetime
from aiogram import Router, F, types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, user
from .database import Tornoment, User, Setting
from .handlers_user import DynamicTextFilter, bot
from .keyboards import ikb_with_color_edit, ikbe
import time
from datetime import datetime, timezone
from .helpers import require_mandatory_join
from .handlers_user import _check_shutdown_msg, _check_shutdown_cb
from aiogram.types import  ContentType, CopyTextButton


def truncate_user_id(user_id: int) -> str:
    s = str(user_id)
    return f"{s[:2]}***{s[-4:]}"

async def show_top(message: types.Message, n, edit=False):
    t = Tornoment.get_active_and_running()
    if edit:
        f = message.edit_text
    else:
        f = message.answer

    if not t:
        await f(Setting.get("msg_no_tornoment"))
        return

    my_invites = User.get_referral_count(message.from_user.id)
    top_invited = get_cached_top_inviters(t.created_at,t.ends_at, n=15)[:n]
    medals = ["🥇", "🥈", "🥉"]
    lines = []

    for i, (user, count) in enumerate(top_invited):
        icon = medals[i] if i < len(medals) else "😴"
        lines.append(
            f"{icon} | <code>{truncate_user_id(user.telegram_id)}</code>\n"
            f"👥 تعداد دعوت: {count}"
        )

    ranking_text = "\n".join(lines)
    showed = min(len(top_invited), n)
    d = t.description.format(count=showed, list=ranking_text)
    me = await bot.get_me()
    invite_link = f"https://t.me/{me.username}?start=reft_{message.from_user.id}"
    await f(
        f"🏆 <b>{t.name}</b>\n\n{d}",
        reply_markup=get_top_inviters_keyboard(my_invites, link=t.link, invite_link=invite_link),
        parse_mode="HTML"
    )

# FSM states for adding and editing tournaments
class TournamentForm(StatesGroup):
    name = State()
    description = State()
    link = State()  # Added state for guide post link
    ends_at = State()

class EditTournamentForm(StatesGroup):
    waiting_for_value = State()


def get_top_inviters_keyboard(count, user_id=-1, link='', invite_link=''):
    buttons = [
        [ikbe(text=f"تعداد دعوتی شما: {count} نفر", callback_data="noop"), ikbe(text=f"کپی لینک دعوت", copy_text=CopyTextButton(text=invite_link),)],
        [
            ikbe(text=f"شرایط مسابقه", url=link),
            ikbe(text=f"مابقی نفرات برتر", callback_data="t_show_all"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def get_tournaments_keyboard(user_id=-1):
    buttons = []
    tournaments = Tornoment.get_all()

    # Get current UTC time to compare with ends_at
    current_time_utc = datetime.now(timezone.utc)

    for t in tournaments:
        # Ensure t.ends_at has timezone info; if naive, assume UTC
        ends_at = t.ends_at
        if ends_at and ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)

        # Determine status emoji based on expiration and status code
        if ends_at and current_time_utc > ends_at:
            status_emoji = "منقضی شده - "  # Expired
        elif t.status == "1":
            status_emoji = "فعال - "  # Active and not expired
        else:
            status_emoji = "غیرفعال - "  # Inactive

        buttons.append([ikbe(
            text=f"{status_emoji} {t.name or f'مسابقه {t.id}'}",
            callback_data=f"t_view:{t.id}"
        )])

    buttons.append([ikbe(text="➕ افزودن مسابقه جدید", callback_data="t_add")])
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="admin_back")])
    return ikb_with_color_edit(buttons, user_id=user_id)

def convert_utc_to_tehran(dt_utc: datetime) -> datetime:
    """
    Convert a UTC datetime object to Iran timezone (UTC+3:30)
    """
    if dt_utc is None:
        return None

    # If the input is naive, assume it is UTC
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    # Define Tehran timezone
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    return dt_utc.astimezone(tehran_tz)


TOP_INVITERS_CACHE = {
    "data": None,
    "expires": 0,
}
TOP_INVITERS_CACHE2 = {
    "data": None,
    "expires": 0,
}
def get_cached_top_inviters(start_date, ends_data, n=10):
    if (
        TOP_INVITERS_CACHE["data"] is None
        or time.time() > TOP_INVITERS_CACHE["expires"]
    ):
        TOP_INVITERS_CACHE["data"] = User.get_top_inviters(
            start_date,
            ends_data,
            n=n
        )
        print(f"Cache miss: fetching top inviters for start_date={start_date},ends_date={ends_data} n={n}")
        TOP_INVITERS_CACHE["expires"] = time.time() + 5  # 5 sec

    return TOP_INVITERS_CACHE["data"]

def get_cached_top_inviters_admin(start_date, ends_data, n=10):
    if (
        TOP_INVITERS_CACHE2["data"] is None
        or time.time() > TOP_INVITERS_CACHE2["expires"]
    ):
        TOP_INVITERS_CACHE2["data"] = User.get_top_inviters(
            start_date,
            ends_data,
            n=n
        )
        print(f"Cache miss: fetching top inviters for start_date={start_date},ends_date={ends_data} n={n}")
        TOP_INVITERS_CACHE2["expires"] = time.time() + 5  # 5 sec

    return TOP_INVITERS_CACHE2["data"]


def convert_tehran_dt_to_persian_str(dt_tehran: datetime) -> str:
    """
    Convert a Gregorian datetime object (Tehran time) to a readable Persian string
    """
    if dt_tehran is None:
        return "ثبت نشده"

    # jdatetime works directly with naive or aware Gregorian datetime objects
    j_dt = jdatetime.datetime.fromgregorian(datetime=dt_tehran)
    return j_dt.strftime("%Y-%m-%d %H:%M")


def parse_datetime(text: str) -> datetime:
    """
    Convert the user's Persian datetime string (UTC+3:30) into a UTC Gregorian datetime object
    """
    text = text.strip().replace('/', '-')  # Standardize separators

    # Common Persian formats the user might input
    formats = [
        "%Y-%m-%d %H:%M",     # 1405-03-30 18:30
        "%Y-%m-%d %H:%M:%S",  # 1405-03-30 18:30:00
        "%Y-%m-%d",           # 1405-03-30 (Default time 00:00)
    ]

    j_dt = None
    for fmt in formats:
        try:
            j_dt = jdatetime.datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if j_dt is None:
        raise ValueError("Invalid Persian datetime format.")

    # 1. Convert Jalali object to Gregorian datetime (naive, Iran time)
    gregorian_dt = j_dt.togregorian()

    # 2. Subtract 3.5 hours to convert to UTC
    utc_dt = gregorian_dt - timedelta(hours=3, minutes=30)
    return utc_dt


# Generate keyboard for tournament details
def get_tournament_detail_keyboard(t_id, user_id=-1):
    buttons = []
    buttons.append([
        ikbe(text="✏️ ویرایش نام", callback_data=f"t_edit:name:{t_id}"),
        ikbe(text="✏️ ویرایش توضیحات", callback_data=f"t_edit:description:{t_id}")
    ])
    buttons.append([
        ikbe(text="🔗 ویرایش لینک", callback_data=f"t_edit:link:{t_id}"),  # Added link edit button
        ikbe(text="⏰ ویرایش زمان پایان", callback_data=f"t_edit:ends_at:{t_id}")
    ])
    buttons.append([
        ikbe(text="🔄 تغییر وضعیت", callback_data=f"t_edit:toggle_status:{t_id}"),
        ikbe(text="❌ حذف این مسابقه", callback_data=f"t_delete:{t_id}")
    ])
    buttons.append([ikbe(text="مدیریت شرکت کننده گان", callback_data=f"t_edit2:view_ranks:{t_id}")])

    buttons.append([ikbe(text="🔙 بازگشت به لیست", callback_data="admin_tornoment")])
    return ikb_with_color_edit(buttons, user_id=user_id)


def tornoment_handler(dp: Dispatcher):
    # 1. Main tournament management menu
    @dp.callback_query(F.data == "admin_tornoment")
    async def admin_tornoment_menu(callback: types.CallbackQuery, state: FSMContext):
        await state.clear() # Clear previous states if any
        await callback.message.edit_text(
            text="🏆 <b>به بخش مدیریت مسابقه‌ها خوش آمدید</b>\n\nلطفاً یک مسابقه را برای مشاهده و ویرایش انتخاب کنید یا یک مسابقه جدید بسازید:",
            reply_markup=get_tournaments_keyboard(callback.from_user.id),
            parse_mode="HTML"
        )

    # 2. View details of a specific tournament
    @dp.callback_query(F.data.startswith("t_view:"))
    async def view_tournament_detail(callback: types.CallbackQuery, ranking_text = "", t_id_=None):
        print(callback.data)
        t_id = t_id_ or int(callback.data.split(":")[-1])
        tournament = Tornoment.get_by_id(t_id)

        if not tournament:
            await callback.answer("❌ این مسابقه یافت نشد.", show_alert=True)
            return

        # Check expiration logic inside detail view to align with the main menu
        current_time_utc = datetime.now(timezone.utc)
        ends_at = tournament.ends_at
        if ends_at and ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)

        if ends_at and current_time_utc > ends_at:
            status_text = "🔴 منقضی شده"
        elif tournament.status == "1":
            status_text = "🟢 فعال"
        else:
            status_text = "🔴 غیرفعال"

        # Convert UTC database timestamps to Iran time before formatting
        tehran_created = convert_utc_to_tehran(tournament.created_at)
        tehran_ends = convert_utc_to_tehran(tournament.ends_at)

        # Convert Tehran datetime directly to Persian string
        created_str = convert_tehran_dt_to_persian_str(tehran_created)
        ends_str = convert_tehran_dt_to_persian_str(tehran_ends)
        inviters = User.get_top_inviters(tournament.created_at, tournament.ends_at, n=-1)
        inviter_count = len(inviters)
        all_inviteds = sum([c for (u,c) in inviters])

        text = (
            f"📋 <b>جزئیات مسابقه: {tournament.name}</b>\n\n"
            f"🔹 <b>توضیحات:</b>\n{tournament.description or 'ثبت نشده'}\n\n"
            f"🔗 <b>لینک پست راهنما:</b>\n{tournament.link or 'ثبت نشده'}\n\n"
            f"🔸 <b>وضعیت:</b> {status_text}\n"
            f"👤 <b>افراد شرکت کننده:</b> <code>{inviter_count}</code>\n"
            f"👥 <b>افراد دعوت شده:</b> <code>{all_inviteds}</code>\n"
            f"📅 <b>تاریخ ساخت:</b> <code>{created_str}</code>\n"
            f"⏰ <b>تاریخ پایان:</b> <code>{ends_str}</code>"
        )

        text += f"\n{ranking_text}"
        await callback.message.edit_text(
            text=text,
            reply_markup=get_tournament_detail_keyboard(t_id, user_id=callback.from_user.id),
            parse_mode="HTML"
        )
    # ----------------------------------------------------
    # Section A: Step-by-step process to add a new tournament (FSM)
    # ----------------------------------------------------

    @dp.callback_query(F.data == "t_add")
    async def add_tournament_start(callback: types.CallbackQuery, state: FSMContext):
        # Validation: Check if there is already an active and running tournament
        active_tournament = Tornoment.get_active_and_running()

        if active_tournament:
            # Format end date to display in the error message
            ends_str = active_tournament.ends_at.strftime("%Y-%m-%d %H:%M")

            # Show alert error and prevent proceeding
            await callback.answer(
                f"⚠️ خطای محدودیت ساخت!\n\n"
                f"مسابقه «{active_tournament.name}» در حال حاضر فعال است و تا تاریخ {ends_str} ادامه دارد.\n"
                f"تا زمانی که این مسابقه به پایان نرسد یا غیرفعال نشود، نمی‌توانید مسابقه جدیدی بسازید.",
                show_alert=True
            )
            return

        # If no active tournament exists, start the creation flow
        await callback.message.edit_text(
            text="✨ <b>قدم اول:</b>\nلطفاً <b>نام مسابقه</b> جدید را ارسال کنید:",
            parse_mode="HTML"
        )
        await state.set_state(TournamentForm.name)

    @dp.message(TournamentForm.name)
    async def add_tournament_name(message: types.Message, state: FSMContext):
        await state.update_data(name=message.text)
        await message.answer("📝 <b>قدم دوم:</b>\nحالا <b>توضیحات</b> مربوط به این مسابقه را بنویسید (مثلاً قوانین، جوایز و...):\n📌 متغیرها: <code>{count}</code> <code>{list}</code>", parse_mode="HTML")
        await state.set_state(TournamentForm.description)

    @dp.message(TournamentForm.description)
    async def add_tournament_description(message: types.Message, state: FSMContext):
        await state.update_data(description=message.text)
        await message.answer("🔗 <b>قدم سوم:</b>\nلطفاً <b>لینک پست راهنما</b> را ارسال کنید:", parse_mode="HTML")
        await state.set_state(TournamentForm.link)

    @dp.message(TournamentForm.link)
    async def add_tournament_link(message: types.Message, state: FSMContext):
        link_value = message.text.strip()
        if not link_value.startswith("https://"):
            await message.answer("لینک معتبر نیست")
            return
        await state.update_data(link=link_value)

        friendly_prompt = (
            "⏳ <b>قدم آخر: زمان پایان مسابقه</b>\n"
            "لطفاً تاریخ و ساعت پایان را به صورت میلادی وارد کنید.\n\n"
            "💡 <b>فرمت‌های مورد قبول:</b>\n"
            "• <code>1405-04-20 18:30</code> (تاریخ و ساعت)\n"
            "• <code>1405/04/20</code> (فقط تاریخ)\n\n"
            "لطفاً زمان مورد نظرتون رو بفرستید:"
        )
        await message.answer(friendly_prompt, parse_mode="HTML")
        await state.set_state(TournamentForm.ends_at)

    @dp.message(TournamentForm.ends_at)
    async def add_tournament_final(message: types.Message, state: FSMContext):
        try:
            # Attempt to parse input text into a datetime object
            ends_at_datetime = parse_datetime(message.text)
        except ValueError:
            # Friendly prompt in case of incorrect input format
            await message.answer(
                "ورودی شما خوانا نبود. 🧐\n"
                "لطفاً مطمئن بشید که تاریخ رو مثل نمونه زیر وارد می‌کنید:\n"
                "👉 <code>2026-06-25 20:00</code>",
                parse_mode="HTML"
            )
            return

        user_data = await state.get_data()

        # Save the datetime object into the database along with the new link field
        Tornoment.create(
            name=user_data['name'],
            description=user_data['description'],
            link=user_data['link'],
            ends_at=ends_at_datetime
        )

        await state.clear()
        await message.answer(
            "🎉 <b>مسابقه جدید با موفقیت و با تاریخ مشخص شده ثبت شد!</b>",
            reply_markup=get_tournaments_keyboard(message.from_user.id),
            parse_mode="HTML"
        )

    # ----------------------------------------------------
    # Section B: Edit, toggle status, and delete operations
    # ----------------------------------------------------

    @dp.callback_query(F.data.startswith("t_delete:"))
    async def delete_tournament(callback: types.CallbackQuery):
        t_id = int(callback.data.split(":")[1])
        Tornoment.delete_by_id(t_id)
        await callback.answer("🗑 مسابقه با موفقیت حذف شد.", show_alert=True)

        # Return to main menu by modifying the current message text
        await callback.message.edit_text(
            text="🏆 <b>لیست مسابقه‌ها به‌روزرسانی شد:</b>",
            reply_markup=get_tournaments_keyboard(callback.from_user.id),
            parse_mode="HTML"
        )

    # Toggle tournament status directly (with concurrency validation logic)
    @dp.callback_query(F.data.startswith("t_edit:toggle_status:"))
    async def toggle_tournament_status(callback: types.CallbackQuery):
        t_id = int(callback.data.split(":")[2])
        tournament = Tornoment.get_by_id(t_id)

        if not tournament:
            await callback.answer("❌ این مسابقه یافت نشد.", show_alert=True)
            return

        # If the tournament is currently inactive and the admin wants to activate it:
        if tournament.status == "0":
            # Validation: Look for another running active tournament
            active_tournament = Tornoment.get_active_and_running()

            if active_tournament:
                ends_str = active_tournament.ends_at.strftime("%Y-%m-%d %H:%M") if active_tournament.ends_at else "نامشخص"

                await callback.answer(
                    f"⚠️ خطای محدودیت فعال‌سازی!\n\n"
                    f"مسابقه «{active_tournament.name}» در حال حاضر فعال است و تا تاریخ {ends_str} ادامه دارد.\n\n"
                    f"شما نمی‌توانید همزمان دو مسابقه فعال داشته باشید. لطفاً ابتدا مسابقه قبلی را غیرفعال کنید.",
                    show_alert=True
                )
                return

            # If no other active tournament is running, activate this one
            Tornoment.update_field(t_id, "status", "1")
            await callback.answer("🟢 مسابقه با موفقیت فعال شد.")

        # If the tournament is currently active and the admin wants to deactivate it:
        else:
            Tornoment.update_field(t_id, "status", "0")
            await callback.answer("🔴 مسابقه غیرفعال شد.")

        # Refresh the tournament detail view to reflect changes natively
        await view_tournament_detail(callback)

    # Initiate editing process for textual fields (name, description, link, end time)
    @dp.callback_query(F.data.startswith("t_edit:"))
    async def edit_tournament_field_start(callback: types.CallbackQuery, state: FSMContext):
        parts = callback.data.split(":")
        field_name = parts[1]
        t_id = int(parts[2])

        field_titles = {
            "name": "نام جدید",
            "description": "توضیحات جدید",
            "link": "لینک جدید پست راهنما",
            "ends_at": "زمان پایان جدید (مثلاً: <code>1405-04-20 18:30</code>)"
        }

        await state.update_data(edit_t_id=t_id, edit_field=field_name)
        await state.set_state(EditTournamentForm.waiting_for_value)

        # Build a cancel button if the user decides to drop the modification
        cancel_kb = InlineKeyboardBuilder()
        cancel_kb.row(InlineKeyboardButton(text="🔙 انصراف", callback_data=f"t_view:{t_id}"))

        # Use edit_text to replace the keyboard layout fluidly
        await callback.message.edit_text(
            text=f"✏️ لطفاً <b>{field_titles.get(field_name)}</b> را در قالب یک پیام ارسال کنید:",
            reply_markup=cancel_kb.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()

    # Capture the updated value from the user and commit to database
    @dp.message(EditTournamentForm.waiting_for_value)
    async def process_tournament_field_edit(message: types.Message, state: FSMContext):
        data = await state.get_data()
        t_id = data['edit_t_id']
        field_name = data['edit_field']
        new_value = message.text

        # If the field being updated is a timestamp, validate and parse it
        if field_name == "ends_at":
            try:
                new_value = parse_datetime(new_value)
            except ValueError:
                await message.answer(
                    "❌ فرمت تاریخ نامعتبر است.\n"
                    "لطفاً تاریخ را مجدداً با فرمت صحیح وارد کنید (نمونه: <code>2026-06-25 20:00</code>):",
                    parse_mode="HTML"
                )
                return

        # Handle clearing link field if user inputs a dash or clears it
        if field_name == "link" and new_value.strip() == "-":
            new_value = ""

        # Update changes inside the database
        Tornoment.update_field(t_id, field_name, new_value)
        await state.clear()

        # Since the user sent a text message, we must send a new response message here
        await message.answer(
            "✅ تغییرات با موفقیت در دیتابیس اعمال شد.\n\n🏆 <b>لیست مسابقه‌ها:</b>",
            reply_markup=get_tournaments_keyboard(message.from_user.id),
            parse_mode="HTML"
        )

    ############################ USER SECTION
    @dp.message(DynamicTextFilter("btn_tornoment", 'مسابقه 🏆'))
    @require_mandatory_join
    async def show_top_inviters(message: types.Message):
        if await _check_shutdown_msg(message): return
        await show_top(message, n=3)

    @dp.callback_query(F.data == "t_show_all")
    async def show_all_top_inviters(callback: types.CallbackQuery):
        if await _check_shutdown_cb(callback): return
        await show_top(callback.message, n=10, edit=True)


    # ── Show all inviters (page 0 entry) ──────────────────────────────────
    @dp.callback_query(F.data.startswith("t_edit2:view_ranks:"))
    async def show_all_inviters(callback: types.CallbackQuery):
        t_id = int(callback.data.split(":")[2])
        await _render_all_inviters_page(callback, page=0, t_id=t_id)

    # ── Paginate all-inviters list ─────────────────────────────────────────
    @dp.callback_query(F.data.startswith("t_all_page:"))
    async def paginate_all_inviters(callback: types.CallbackQuery):
        t_id = int(callback.data.split(":")[1])
        page = int(callback.data.split(":")[2])

        await _render_all_inviters_page(callback, page=page, t_id=t_id)

    # ── Back to top-3 view ─────────────────────────────────────────────────
    @dp.callback_query(F.data.startswith("t_back_to_top"))
    async def back_to_top(callback: types.CallbackQuery):
        # t_id
        t_id = int(callback.data.split(":")[1])
        await view_tournament_detail(callback, t_id_=t_id)
        # op(callback.message, n=3, edit=True)
        pass

    # ── Drill into a specific user (inv_page=0) ────────────────────────────
    @dp.callback_query(F.data.startswith("t_user_detail:"))
    async def show_user_detail(callback: types.CallbackQuery):
        _, target_uid, back_page = callback.data.split(":")
        target_uid = int(target_uid)
        back_page = int(back_page)
        await _render_user_detail_page(callback, target_uid, back_page, inv_page=0)

    # ── Paginate invited-users list inside a user's detail view ───────────
    @dp.callback_query(F.data.startswith("t_user_inv_page:"))
    async def paginate_user_invited(callback: types.CallbackQuery):
        _, target_uid, back_page, inv_page = callback.data.split(":")
        await _render_user_detail_page(
            callback,
            int(target_uid),
            int(back_page),
            int(inv_page),
        )



"""
Paste this block into your tornoment_handler() function (inside the dp registration section),
and add the two helper functions outside it.

Dependencies already in your file: get_cached_top_inviters, truncate_user_id,
ikbe, InlineKeyboardMarkup, User, Setting, Tornoment, bot
"""

from aiogram import Router, F, types, Dispatcher
from aiogram.types import InlineKeyboardMarkup
from .keyboards import ikbe
from .database import Tornoment, User, Setting

PAGE_SIZE = 10  # users per page


# ─────────────────────────────────────────────
#  Helper: build the "all inviters" keyboard
# ─────────────────────────────────────────────
def get_all_inviters_keyboard(inviters, page: int, t_id: int) -> InlineKeyboardMarkup:
    """
    inviters: list of (User, count) tuples (full list, already sorted desc)
    page: 0-based page index
    """
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = inviters[start:end]
    total_pages = max(1, -(-len(inviters) // PAGE_SIZE))  # ceil division

    buttons = []

    medals = ["🥇", "🥈", "🥉"]
    for i, (user, count) in enumerate(page_items):
        rank = start + i
        icon = medals[rank] if rank < len(medals) else f"#{rank + 1}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {user.telegram_id} — {count} دعوت",
                callback_data=f"t_user_detail:{user.telegram_id}:{page}"
            )
        ])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(ikbe(text="⬅️ قبلی", callback_data=f"t_all_page:{t_id}:{page - 1}"))
    nav.append(ikbe(text=f"صفحه {page + 1} / {total_pages}", callback_data="noop"))
    if end < len(inviters):
        nav.append(ikbe(text="➡️ بعدی", callback_data=f"t_all_page:{t_id}:{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([ikbe(text="🔙 بازگشت", callback_data=f"t_back_to_top:{t_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─────────────────────────────────────────────
#  Helper: build the "user detail" keyboard
# ─────────────────────────────────────────────
def get_user_detail_keyboard(
    invited_users,          # list of User objects invited by this user
    target_uid: int,
    back_page: int,
    inv_page: int = 0,
    t_id: int = -1
) -> InlineKeyboardMarkup:
    start = inv_page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = invited_users[start:end]
    total_pages = max(1, -(-len(invited_users) // PAGE_SIZE))

    buttons = []

    for u in page_items:
        if u.username:
            profile_url = f"https://t.me/{u.username}"
        else:
            profile_url = f"https://t.me/"

            profile_url = f"tg://user?id={u.telegram_id}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{u.telegram_id} — {'✅ خرید' if u.pays_referral else '❌ بدون خرید'}",
                url=profile_url
            )
        ])

    # Pagination row for invited users
    nav = []
    if inv_page > 0:
        nav.append(ikbe(
            text="⬅️ قبلی",
            callback_data=f"t_user_inv_page:{target_uid}:{back_page}:{inv_page - 1}"
        ))
    nav.append(ikbe(text=f"صفحه {inv_page + 1} / {total_pages}", callback_data="noop"))
    if end < len(invited_users):
        nav.append(ikbe(
            text="➡️ بعدی",
            callback_data=f"t_user_inv_page:{target_uid}:{back_page}:{inv_page + 1}"
        ))
    if nav:
        buttons.append(nav)

    buttons.append([ikbe(text="🔙 بازگشت به لیست", callback_data=f"t_all_page:{t_id}:{back_page}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



# ─────────────────────────────────────────────
#  Internal renderers (shared by entry + pagination)
# ─────────────────────────────────────────────
async def _render_all_inviters_page(callback: types.CallbackQuery, page: int, t_id: int):
    # t = Tornoment.get_active_and_running()
    t = Tornoment.get_by_id(t_id)
    if not t:
        await callback.answer(Setting.get("msg_no_tornoment"), show_alert=True)
        return

    all_inviters = get_cached_top_inviters_admin(t.created_at, t.ends_at, n=-1)
    if not all_inviters:
        await callback.answer("هنوز کسی دعوت نکرده است.", show_alert=True)
        return

    total = len(all_inviters)
    total_pages = max(1, -(-total // PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))

    await callback.message.edit_text(
        text=(
            f"👥 <b>لیست کامل دعوت‌کنندگان</b>\n"
            f"مجموع: <code>{total}</code> نفر\n\n"
            f"روی هر نفر کلیک کنید تا جزئیاتش را ببینید 👇"
        ),
        reply_markup=get_all_inviters_keyboard(all_inviters, page, t_id),
        parse_mode="HTML",
    )


async def _render_user_detail_page(
    callback: types.CallbackQuery,
    target_uid: int,
    back_page: int,
    inv_page: int,
):
    t = Tornoment.get_active_and_running()
    if not t:
        await callback.answer(Setting.get("msg_no_tornoment"), show_alert=True)
        return

    # Count how many this user invited in the tournament window
    all_inviters = get_cached_top_inviters_admin(t.created_at, t.ends_at, n=-1)
    invite_count = next(
        (c for (u, c) in all_inviters if u.telegram_id == target_uid), 0
    )

    # Referral bonus per invite
    referral_bonus = int(Setting.get("referral_bonus") or "0")

    # List of all users this person invited (ever registered via their link)
    invited_users = User.get_referral(target_uid)  # returns list[User]

    # Profit = count of invited users who made a purchase × bonus
    paying_count = sum(1 for u in invited_users if u.pays_referral)
    bonus_count = sum(1 for u in invited_users if u.pays_bonus)
    # paying_count = len(invited_users)
    total_profit = bonus_count * referral_bonus

    user_obj = User.get_by_telegram_id(target_uid)
    display_name = (
        f"@{user_obj.username}" if user_obj and user_obj.username
        else target_uid
    )

    text = (
        f"👤 <b>جزئیات کاربر: {display_name}</b>\n\n"
        f"🆔 شناسه: <code>{target_uid}</code>\n"
        f"👥 دعوت‌شدگان در مسابقه: <code>{invite_count}</code> نفر\n"
        f"✅ دعوت‌شدگانی که خرید کردند: <code>{paying_count}</code> نفر\n"
        f"💰 سود کسب‌شده از دعوت: <code>{total_profit:,}</code> تومان\n\n"
        f"📋 لیست دعوت‌شدگان:"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_user_detail_keyboard(
            invited_users, target_uid, back_page, inv_page, t.id
        ),
        parse_mode="HTML",
    )
