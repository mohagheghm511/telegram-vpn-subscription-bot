from .database import CategorySetting, get_db, Setting, MandatoryChannel, Session, Order, Plan, Config, PendingConfig, Service
from datetime import datetime, timedelta
import random
from .config import ADMIN_IDS
from aiogram import types
import logging
from functools import wraps
from aiogram.fsm.context import FSMContext
import string

# ── اسامی رندوم برای سرویس ────────────────────────────────────
SERVICE_NAMES = [
    "آلفا", "بتا", "گاما", "دلتا", "اپسیلون", "زتا", "اتا", "تتا",
    "فونیکس", "اوریون", "آریا", "پارسا", "کوروش", "داریوش", "آرش",
    "ستاره", "ماه", "خورشید", "ابر", "طوفان", "آذرخش", "رعد",
    "زمرد", "یاقوت", "الماس", "عقیق", "فیروزه", "مروارید",
    "شاهین", "عقاب", "پرنده", "اژدها", "ببر", "شیر", "پلنگ",
]

def generate_service_name():
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return rand

def only_admin(handler):
    @wraps(handler)
    async def wrapper(event: types.Message | types.CallbackQuery, *args, **kwargs):

        admins = set(ADMIN_IDS) | set(get_all_admins())

        user = event.from_user

        if not user or user.id not in admins:

            if isinstance(event, types.CallbackQuery):
                await event.answer("دسترسی ندارید", show_alert=True)

            elif isinstance(event, types.Message):
                await event.reply("دسترسی ندارید")

            return

        return await handler(event, *args, **kwargs)

    return wrapper


JOINED_CHANNEL_STATUSES = ('member', 'administrator', 'creator', 'restricted')
def add_to_free_test_queue(user_id):
    conn = get_db()
    conn.execute("INSERT INTO pending_free_configs (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_free_test_queue():
    """دریافت صف انتظار کانفیگ‌های رایگان با اطلاعات کاربر"""
    conn = get_db()
    rows = conn.execute(
        """SELECT pfc.*, u.full_name, u.username
           FROM pending_free_configs pfc
           JOIN users u ON pfc.user_id = u.telegram_id
           WHERE pfc.fulfilled_at IS NULL
           ORDER BY pfc.created_at ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

async def process_free_test_queue(bot):
    from .database import get_db, FreeTestConfig, Setting
    from datetime import datetime
    import logging

    conn = get_db()
    pending_users = conn.execute("SELECT id, user_id FROM pending_free_configs WHERE fulfilled_at IS NULL ORDER BY created_at ASC").fetchall()

    sent_count = 0
    for row in pending_users:
        pending_id = row['id']
        user_id = row['user_id']

        # Check if there's a free config available
        config = FreeTestConfig.get()
        if not config:
            break # No more configs available

        # Assign config
        FreeTestConfig.assign_to(user_id, config.id)

        # Mark as fulfilled
        conn.execute("UPDATE pending_free_configs SET fulfilled_at=? WHERE id=?", (datetime.now().isoformat(), pending_id))
        conn.commit()

        # Send to user
        try:
            text = Setting.get("msg_reach_referral").format(config=f"<code>{config.config_data}</code>")
            await bot.send_message(chat_id=int(user_id), text=text)
            sent_count += 1
        except Exception as e:
            logging.error(f"Failed to send free config to {user_id}: {e}")

    conn.close()
    return sent_count

async def get_missing_mandatory_channels(bot, user_id):
    channels = MandatoryChannel.get_all()
    if not channels:
        return []

    # admins = set(ADMIN_IDS) | set(get_all_admins())
    # if user_id in admins:
    #     return []

    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch['channel_id'], user_id)
            if member.status not in JOINED_CHANNEL_STATUSES:
                missing.append(ch)
        except Exception as e:
            logging.error(f"Mandatory join check failed for channel {ch['channel_id']}: {e}")
            missing.append(ch)
    return missing


async def edit_mandatory_join_message(message, missing_channels):
    from .keyboards import mandatory_join_inline

    if not missing_channels:
        return

    text = Setting.get("msg_mandatory_channels")
    markup = mandatory_join_inline(missing_channels, message.from_user.id)

    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise


async def send_mandatory_join_prompt(event, missing_channels):
    if not missing_channels:
        return

    if isinstance(event, types.CallbackQuery):
        await edit_mandatory_join_message(event.message, missing_channels)
    else:
        from .keyboards import mandatory_join_inline

        text = Setting.get("msg_mandatory_channels")
        markup = mandatory_join_inline(missing_channels, event.from_user.id)

        await event.answer(text, reply_markup=markup)


def require_mandatory_join(handler):
    @wraps(handler)
    async def wrapper(event: types.Message | types.CallbackQuery, *args, **kwargs):
        user = event.from_user
        if not user:
            return
        from .handlers_user import bot
        missing = await get_missing_mandatory_channels(bot, user.id)
        if not missing:
            return await handler(event, *args, **kwargs)
        if isinstance(event, types.CallbackQuery):
            await event.answer()

        # Save the deep link param so we can replay it after joining
        state: FSMContext = kwargs.get("state")
        if state and isinstance(event, types.Message):
            args_list = event.text.split()
            if len(args_list) > 1:
                await state.update_data(pending_start_param=args_list[1])

        await send_mandatory_join_prompt(event, missing)
    return wrapper



def update_invoice(invoice_id, **kwargs):
    """
    Updates an invoice dynamically based on provided arguments.
    Usage: update_invoice(123, status='paid', channel_message_id=456)
    """
    if not kwargs:
        return None

    conn = get_db()

    # 1. Build the SET clause dynamically: "column1 = ?, column2 = ?"
    columns = ", ".join([f"{key} = ?" for key in kwargs.keys()])

    # 2. Extract the values in the same order as the keys
    values = list(kwargs.values())

    # 3. Add the invoice_id to the values for the WHERE clause
    values.append(invoice_id)

    query = f"""
        UPDATE invoice
        SET {columns}
        WHERE id = ?
    """

    cursor = conn.execute(query, values)
    conn.commit()

    # rowcount returns the number of rows affected
    affected = cursor.rowcount
    conn.close()

    return affected > 0

def get_invoice_by_id(invoice_id: int):
    conn = get_db()

    cursor = conn.execute(
        """
        SELECT *
        FROM invoice
        WHERE id = ?
        """,
        (invoice_id,)
    )

    row = cursor.fetchone()

    conn.close()

    return row

def create_invoice(user_id, amount, channel_message_id=-1, method='card', status='pending'):
    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO invoice (
            user_id,
            amount,
            channel_message_id,
            method,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (user_id, amount, channel_message_id, method, status)
    )

    invoice_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return invoice_id

async def alert_admins(bot, *args, **kwargs) -> int:
    admins = ADMIN_IDS + get_all_admins()
    count = 0
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, *args, **kwargs)
            count += 1
        except:
            logging.error(f"faild to send alert to admin {admin_id}")

    return count


def reject_invoice(invoice_id: int):
    conn = get_db()

    conn.execute(
        """
        UPDATE invoice
        SET status = 'failed'
        WHERE id = ?
        """,
        (invoice_id,)
    )

    cursor = conn.execute(
        """
        SELECT *
        FROM invoice
        WHERE id = ?
        """,
        (invoice_id,)
    )

    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return row

def get_invoice_by_price(amount, status='pending'):
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT * FROM invoice
        WHERE amount = ?
          AND status = ?
          AND method = 'card'
        """,
        (amount,status)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def get_channel_id(ch):
    channel_id = Setting.get(ch)
    ch_id = channel_id.strip()
    if ch_id.startswith('-'): ch_id = int(ch_id)
    elif ch_id.isdigit(): ch_id = int(ch_id)
    elif not ch_id.startswith('@'): ch_id = f"@{ch_id}"
    return ch_id

def get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    if not user:
        return get_or_create_user(telegram_id, None, None, None)
    return user

def get_or_create_user(telegram_id, username=None, full_name=None, referred_by=None):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not user:
        conn.execute(
            "INSERT INTO users (telegram_id, username, full_name, referred_by) VALUES (?,?,?,?)",
            (telegram_id, username, full_name, referred_by)
        )
        conn.commit()
        if referred_by:
            bonus = int(get_setting('referral_bonus') or 30000)
            conn.execute(
                "UPDATE users SET balance = balance + ? WHERE telegram_id=?",
                (bonus, referred_by)
            )
            conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
                (referred_by, bonus, 'referral', f'پاداش دعوت کاربر {telegram_id}')
            )
            conn.commit()
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return user

def get_plan_categories():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT category FROM plans WHERE is_active=1 ORDER BY category"
    ).fetchall()
    conn.close()
    return [r['category'] for r in rows]


def get_active_plan_prices():
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT price
        FROM plans
        WHERE is_active = 1
        """
    )

    rows = cursor.fetchall()
    conn.close()

    return [row["price"] for row in rows]


def get_plans_by_category(category):
    conn = get_db()
    plans = conn.execute(
        "SELECT * FROM plans WHERE is_active=1 AND category=?", (category,)
    ).fetchall()
    result = []
    for p in plans:
        stock = conn.execute(
            "SELECT COUNT(*) as cnt FROM configs WHERE plan_id=? AND is_used=0", (p['id'],)
        ).fetchone()['cnt']
        result.append({**dict(p), 'stock': stock})
    conn.close()
    # مرتب‌سازی بر اساس حجم گیگ از کم به زیاد (نامحدود (-1) در آخر)
    result.sort(key=lambda x: (x['volume_gb'] == -1, x['volume_gb']))
    return result

def get_active_plans():
    conn = get_db()
    plans = conn.execute("SELECT * FROM plans WHERE is_active=1").fetchall()
    result = []
    for p in plans:
        stock = conn.execute(
            "SELECT COUNT(*) as cnt FROM configs WHERE plan_id=? AND is_used=0", (p['id'],)
        ).fetchone()['cnt']
        result.append({**dict(p), 'stock': stock})
    conn.close()
    return result

def get_plan(plan_id):
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not plan:
        return None
    result = dict(plan)
    category_settings = CategorySetting.get(result.get("category", ""))
    result["base_gig"] = category_settings["base_gig"]
    result["base_day"] = category_settings["base_day"]
    result["connect_to_panel"] = category_settings["connect_to_panel"]
    return result

def get_config_stock(plan_id):
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM configs WHERE plan_id=? AND is_used=0", (plan_id,)
    ).fetchone()['cnt']
    conn.close()
    return count

def assign_config(plan_id, user_id, order_id):
    conn = get_db()
    config = conn.execute(
        "SELECT * FROM configs WHERE plan_id=? AND is_used=0 LIMIT 1", (plan_id,)
    ).fetchone()
    if not config:
        conn.close()
        return None
    conn.execute(
        "UPDATE configs SET is_used=1, assigned_to=?, assigned_at=? WHERE id=?",
        (user_id, datetime.now().isoformat(), config['id'])
    )
    conn.commit()
    conn.close()
    return config

def check_low_stock(plan_id):
    conn = get_db()
    plan = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not plan:
        conn.close()
        return None
    stock = conn.execute(
        "SELECT COUNT(*) as cnt FROM configs WHERE plan_id=? AND is_used=0", (plan_id,)
    ).fetchone()['cnt']
    alert_threshold = plan['low_stock_alert']
    conn.close()
    if stock == 0:
        return 'empty'
    elif stock <= alert_threshold:
        return 'low'
    return None

def create_order(user_id, plan_id, amount, payment_method):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO orders (user_id, plan_id, amount, payment_method) VALUES (?,?,?,?)",
        (user_id, plan_id, amount, payment_method)
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_order(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return order

def confirm_order(order_id: int, sname: str = None, panel: bool = False) -> tuple:
    """
    Confirm an order and assign a config from stock.

    Returns:
        (True, (config_data, config_type, config_id, service_name)) - Success
        ("queued", (queue_pos, plan_id, user_id, order_id)) - Queued
        (False, error_message) - Error
    """
    session = Session()
    try:
        order = session.query(Order).filter_by(id=order_id).first()
        if not order or order.status != "pending":
            return False, "سفارش یافت نشد یا قبلاً پردازش شده"

        plan = session.query(Plan).filter_by(id=order.plan_id).first()
        if not plan:
            return False, "پلن یافت نشد"

        # Get available config from stock
        config = session.query(Config).filter_by(plan_id=order.plan_id, is_used=0).order_by(Config.id).first()

        if not config:
            # حالت پنل: سیگنال استفاده از X-UI
            if panel:
                return "panel", None  # ← اصلاح املایی

            # حالت عادی: افزودن به صف
            order.status = "queued"  # ← آپدیت status
            order.confirmed_at = datetime.now().isoformat()

            existing = session.query(PendingConfig).filter_by(order_id=order_id).first()

            if not existing:
                pending = PendingConfig(
                    order_id=order_id,
                    user_id=order.user_id,
                    plan_id=order.plan_id,
                    amount=order.amount,
                )
                session.add(pending)  # ← ایجاد entry

            session.commit()

            queue_pos = session.query(PendingConfig).filter_by(plan_id=order.plan_id, fulfilled_at=None).count()

            return "queued", (queue_pos, plan.id, order.user_id, order_id)

        # تایید سفارش
        final_service_name = config.service_name or sname or generate_service_name()

        # Mark config as used
        config.is_used = 1
        config.assigned_to = order.user_id
        config.assigned_at = datetime.now().isoformat()

        # Update order status
        order.status = "confirmed"
        order.config_id = config.id
        order.confirmed_at = datetime.now().isoformat()

        # Calculate expiry
        if plan.duration_days == -1:
            expires = "2099-12-31T00:00:00"
        else:
            expires = (datetime.now() + timedelta(days=plan.duration_days)).isoformat()

        # Create service record with the correct service_name
        service = Service.create(
            user_id=order.user_id,
            plan_id=plan.id,
            config_id=config.id,
            service_name=final_service_name,  # Use config's service_name
            expires_at=expires,
            volume_gb=plan.volume_gb,
            session=session,
        )

        session.commit()

        # Return config data along with service_name for reference
        return True, (config.config_data, plan.category, config.id, service.id, final_service_name)

    except Exception as e:
        session.rollback()
        logging.error(f"confirm_order error: {e}")
        return False, str(e)
    finally:
        session.close()

def reject_order(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()

def get_user_services(user_id):
    conn = get_db()
    services = conn.execute("""
        SELECT s.*, p.name as plan_name, p.volume_gb, c.config_data
        FROM services s
        JOIN plans p ON s.plan_id = p.id
        JOIN configs c ON s.config_id = c.id
        WHERE s.user_id=? AND s.is_active=1
        ORDER BY s.created_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(s) for s in services]

def charge_wallet(user_id, amount, description="شارژ کیف پول"):
    conn = get_db()
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (amount, user_id))
    conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
        (user_id, amount, 'charge', description)
    )
    conn.commit()
    conn.close()

def set_wallet(user_id, amount, description="ویرایش موجودی توسط ادمین"):
    """تنظیم مستقیم موجودی کیف پول"""
    conn = get_db()
    conn.execute("UPDATE users SET balance = ? WHERE telegram_id=?", (amount, user_id))
    conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
        (user_id, amount, 'admin_set', description)
    )
    conn.commit()
    conn.close()

def deduct_wallet(user_id, amount, description="خرید سرویس"):
    conn = get_db()
    user = conn.execute("SELECT balance FROM users WHERE telegram_id=?", (user_id,)).fetchone()
    if not user or user['balance'] < amount:
        conn.close()
        return False
    conn.execute("UPDATE users SET balance = balance - ? WHERE telegram_id=?", (amount, user_id))
    conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, type, description) VALUES (?,?,?,?)",
        (user_id, -amount, 'deduct', description)
    )
    conn.commit()
    conn.close()
    return True

def has_used_free_test(user_id):
    conn = get_db()
    row = conn.execute("SELECT id FROM free_test_configs WHERE assigned_to=?", (user_id,)).fetchone()
    conn.close()
    return row is not None

def get_free_test_config():
    conn = get_db()
    config = conn.execute(
        "SELECT * FROM free_test_configs WHERE is_used=0 LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(config) if config else None

def assign_free_test_to_user(user_id, config_id):
    conn = get_db()
    conn.execute(
        "UPDATE free_test_configs SET is_used=1, assigned_to=?, assigned_at=? WHERE id=?",
        (user_id, datetime.now().isoformat(), config_id)
    )
    conn.commit()
    conn.close()

def get_all_free_test_configs():
    conn = get_db()
    configs = conn.execute(
        "SELECT COUNT(*) as total, SUM(is_used) as used FROM free_test_configs"
    ).fetchone()
    conn.close()
    return dict(configs) if configs else {'total': 0, 'used': 0}

def add_free_test_config(config_data, description=""):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO free_test_configs (config_data, description) VALUES (?,?)",
        (config_data, description)
    )
    config_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return config_id

def get_free_test_stock():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM free_test_configs WHERE is_used=0").fetchone()
    conn.close()
    return row['cnt'] if row else 0

# ── ادمین‌های دینامیک ────────────────────────────────────

def add_admin_user(telegram_id, added_by, role='channel'):
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM admin_users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE admin_users SET role=?, is_active=1, added_by=? WHERE telegram_id=?",
                (role, added_by, telegram_id)
            )
        else:
            conn.execute(
                "INSERT INTO admin_users (telegram_id, added_by, role) VALUES (?,?,?)",
                (telegram_id, added_by, role)
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False

def get_admin_role(telegram_id):
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM admin_users WHERE telegram_id=? AND is_active=1",
        (telegram_id,)
    ).fetchone()
    conn.close()
    return row['role'] if row else None

def is_bot_admin(telegram_id, superadmin_ids):
    if telegram_id in superadmin_ids:
        return True
    role = get_admin_role(telegram_id)
    return role in ('bot', 'both')


def is_channel_admin(telegram_id, superadmin_ids):
    if telegram_id in superadmin_ids:
        return True
    role = get_admin_role(telegram_id)
    return role in ('channel', 'both')

def remove_admin_user(telegram_id):
    conn = get_db()
    conn.execute("UPDATE admin_users SET is_active=0 WHERE telegram_id=?", (telegram_id,))
    conn.commit()
    conn.close()

def get_all_admins():
    conn = get_db()
    admins = conn.execute(
        "SELECT telegram_id FROM admin_users WHERE is_active=1"
    ).fetchall()
    conn.close()
    return [admin['telegram_id'] for admin in admins]

def is_admin(telegram_id):
    conn = get_db()
    admin = conn.execute(
        "SELECT id FROM admin_users WHERE telegram_id=? AND is_active=1",
        (telegram_id,)
    ).fetchone()
    conn.close()
    return admin is not None

# ── تیکت‌ها ────────────────────────────────────
def add_support_reply(ticket_id, reply_message, admin_id):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO support_replies (ticket_id, reply_message, reply_by_admin) VALUES (?,?,?)",
        (ticket_id, reply_message, admin_id)
    )
    reply_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return reply_id

def get_ticket_replies(ticket_id):
    conn = get_db()
    replies = conn.execute(
        "SELECT * FROM support_replies WHERE ticket_id=? ORDER BY created_at ASC",
        (ticket_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in replies]

def mark_reply_as_sent(reply_id, user_id):
    conn = get_db()
    conn.execute("UPDATE support_replies SET sent_to_user=? WHERE id=?", (user_id, reply_id))
    conn.commit()
    conn.close()

def get_support_ticket(ticket_id):
    conn = get_db()
    ticket = conn.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
    conn.close()
    return dict(ticket) if ticket else None

def close_support_ticket(ticket_id):
    conn = get_db()
    conn.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()

# ── صف انتظار ────────────────────────────────────

def add_to_pending_queue(order_id, user_id, plan_id, amount):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO pending_configs (order_id, user_id, plan_id, amount) VALUES (?,?,?,?)",
        (order_id, user_id, plan_id, amount)
    )
    conn.commit()
    conn.close()

def get_pending_queue_for_plan(plan_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT pc.*, u.full_name, u.username
           FROM pending_configs pc
           JOIN users u ON pc.user_id = u.telegram_id
           WHERE pc.plan_id=? AND pc.fulfilled_at IS NULL
           ORDER BY pc.created_at ASC""",
        (plan_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_pending_queue():
    """دریافت تمام صف انتظار با اطلاعات کامل"""
    conn = get_db()
    rows = conn.execute(
        """SELECT pc.*, u.full_name, u.username, p.name as plan_name
           FROM pending_configs pc
           JOIN users u ON pc.user_id = u.telegram_id
           JOIN plans p ON pc.plan_id = p.id
           WHERE pc.fulfilled_at IS NULL
           ORDER BY pc.created_at ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_queue_item(queue_id):
    """حذف یک آیتم از صف انتظار"""
    conn = get_db()
    conn.execute("DELETE FROM pending_configs WHERE id=?", (queue_id,))
    conn.commit()
    conn.close()

def get_pending_queue_count(plan_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM pending_configs WHERE plan_id=? AND fulfilled_at IS NULL",
        (plan_id,)
    ).fetchone()
    conn.close()
    return row['c'] if row else 0

def get_queue_position(plan_id, order_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT order_id FROM pending_configs WHERE plan_id=? AND fulfilled_at IS NULL ORDER BY created_at ASC",
        (plan_id,)
    ).fetchall()
    conn.close()
    for i, r in enumerate(rows, 1):
        if r['order_id'] == order_id:
            return i
    return None

def fulfill_pending_queue_item(pending_id, config_data, plan):
    conn = get_db()
    pending = conn.execute("SELECT * FROM pending_configs WHERE id=?", (pending_id,)).fetchone()
    if not pending:
        conn.close()
        return False, None, None, None

    config = conn.execute(
        "SELECT * FROM configs WHERE plan_id=? AND is_used=0 LIMIT 1",
        (pending['plan_id'],)
    ).fetchone()
    if not config:
        conn.close()
        return False, None, None, None

    from datetime import timedelta
    if plan['duration_days'] == -1:
        expires = "2099-12-31T00:00:00"
    else:
        expires = (datetime.now() + timedelta(days=plan['duration_days'])).isoformat()

    sname = config['service_name'] or generate_service_name()

    conn.execute(
        "UPDATE configs SET is_used=1, assigned_to=?, assigned_at=? WHERE id=?",
        (pending['user_id'], datetime.now().isoformat(), config['id'])
    )
    conn.execute(
        "INSERT INTO services (user_id, plan_id, config_id, service_name, expires_at, volume_gb) VALUES (?,?,?,?,?,?)",
        (pending['user_id'], pending['plan_id'], config['id'], sname, expires, plan['volume_gb'])
    )
    conn.execute(
        "UPDATE orders SET config_id=? WHERE id=?",
        (config['id'], pending['order_id'])
    )
    conn.execute(
        "UPDATE pending_configs SET fulfilled_at=? WHERE id=?",
        (datetime.now().isoformat(), pending_id)
    )
    conn.commit()
    conn.close()
    return True, pending['user_id'], (config['config_data'], None), plan["category"]

def get_all_pending_plans():
    conn = get_db()
    rows = conn.execute(
        """SELECT pc.plan_id, p.name, COUNT(*) as waiting_count
           FROM pending_configs pc
           JOIN plans p ON pc.plan_id = p.id
           WHERE pc.fulfilled_at IS NULL
           GROUP BY pc.plan_id"""
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        try:
            result.append({'plan_id': r['plan_id'], 'name': r['name'], 'waiting_count': r['waiting_count']})
        except:
            result.append({'plan_id': r[0], 'name': r[1], 'waiting_count': r[2]})
    return result

def get_bot_stats():
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
    total_orders = conn.execute("SELECT COUNT(*) as c FROM orders WHERE status='confirmed'").fetchone()['c']
    total_revenue = conn.execute("SELECT SUM(amount) as s FROM orders WHERE status='confirmed'").fetchone()['s'] or 0
    today_revenue = conn.execute("""
        SELECT SUM(amount) as s
        FROM orders
        WHERE status = 'confirmed'
          AND created_at >= datetime('now', '+3 hours', '+30 minutes', 'start of day', '-3 hours', '-30 minutes')
    """).fetchone()['s'] or 0
    today_total_orders = conn.execute("""
        SELECT COUNT(*) as c
        FROM orders
        WHERE status = 'confirmed'
          AND created_at >= datetime('now', '+3 hours', '+30 minutes', '-1 day', 'start of day', '-3 hours', '-30 minutes')
    """).fetchone()['c']
    active_services = conn.execute("SELECT COUNT(*) as c FROM services WHERE is_active=1").fetchone()['c']
    conn.close()
    return {
        'total_users': total_users,
        'total_orders': total_orders,
        'today_revenue': today_revenue,
        'today_total_orders': today_total_orders,
        'total_revenue': total_revenue,
        'active_services': active_services
    }

# ── ویرایش پلن ────────────────────────────────────

def update_plan(plan_id, name=None, volume_gb=None, duration_days=None, max_devices=None, price=None, category=None):
    conn = get_db()
    updates = []
    values = []
    if name is not None:
        updates.append("name=?"); values.append(name)
    if volume_gb is not None:
        updates.append("volume_gb=?"); values.append(volume_gb)
    if duration_days is not None:
        updates.append("duration_days=?"); values.append(duration_days)
    if max_devices is not None:
        updates.append("max_devices=?"); values.append(max_devices)
    if price is not None:
        updates.append("price=?"); values.append(price)
    if category is not None:
        updates.append("category=?"); values.append(category)
    if not updates:
        conn.close()
        return False
    values.append(plan_id)
    conn.execute(f"UPDATE plans SET {','.join(updates)} WHERE id=?", values)
    conn.commit()
    conn.close()
    return True

def delete_plan(plan_id):
    conn = get_db()
    conn.execute("UPDATE plans SET is_active=0 WHERE id=?", (plan_id,))
    conn.commit()
    conn.close()
    return True

def get_all_users():
    try:
        conn = get_db()
        users = conn.execute("SELECT telegram_id FROM users").fetchall()
        conn.close()
        return [u['telegram_id'] for u in users]
    except Exception as e:
        return []

# ── آموزش اتصال ────────────────────────────────────

def get_connection_guide(category):
    """دریافت متن آموزش اتصال برای یک دسته‌بندی"""
    conn = get_db()
    row = conn.execute(
        "SELECT guide_text FROM connection_guides WHERE category=?", (category,)
    ).fetchone()
    conn.close()
    return row['guide_text'] if row else None

def set_connection_guide(category, guide_text):
    """ذخیره یا به‌روزرسانی آموزش اتصال"""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO connection_guides (category, guide_text, updated_at) VALUES (?,?,?)",
        (category, guide_text, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_all_guide_categories():
    """دریافت تمام دسته‌بندی‌هایی که آموزش دارند"""
    conn = get_db()
    rows = conn.execute("SELECT category FROM connection_guides ORDER BY category").fetchall()
    conn.close()
    return [r['category'] for r in rows]

def delete_connection_guide(category):
    conn = get_db()
    conn.execute("DELETE FROM connection_guides WHERE category=?", (category,))
    conn.commit()
    conn.close()

# ── سرویس ────────────────────────────────────

def get_user_service_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM services WHERE user_id=? AND is_active=1", (user_id,)
    ).fetchone()
    conn.close()
    return row['c'] if row else 0

def get_user_referral_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM users WHERE referred_by=?", (user_id,)
    ).fetchone()
    conn.close()
    return row['c'] if row else 0


# ── مدیریت رنگ دکمه‌ها ────────────────────────────────────

COLOR_EMOJIS = {
    'normal': '',
    'danger': 'danger',
    'primary': 'primary',
    'success': 'success'
}

def get_button_color(button_key: str) -> str|None:
    """دریافت رنگ فعلی یک دکمه"""
    conn = get_db()
    row = conn.execute("SELECT color FROM button_colors WHERE button_key=?", (button_key,)).fetchone()
    conn.close()
    color =  row['color'] if row else None
    if not color or color=='normal':
        return None
    return COLOR_EMOJIS[color]

def set_button_color(button_key: str, color: str):
    """ذخیره رنگ دکمه"""
    if color not in COLOR_EMOJIS:
        color = 'normal'
    conn = get_db()
    print("set color to :", color)
    conn.execute("INSERT OR REPLACE INTO button_colors (button_key, color) VALUES (?,?)",
                (button_key, color))
    conn.commit()
    conn.close()

def cycle_color(current_color: str|None) -> str:
    """چرخش رنگ: normal → red → blue → green → normal"""
    if not current_color:
        current_color = 'normal'
    order = ['normal', 'danger', 'primary', 'success']
    idx = order.index(current_color)
    return order[(idx + 1) % len(order)]


# ══════════════════════════════════════════════════
# ── توابع سیستم همکار ──────────────────────────
# ══════════════════════════════════════════════════

def get_partner(telegram_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM partners WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_partner_by_id(partner_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_partners():
    conn = get_db()
    rows = conn.execute("SELECT * FROM partners ORDER BY registered_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_partner(partner_id, **kwargs):
    conn = get_db()
    updates, values = [], []
    allowed = ['balance','credit_limit','is_active','welcome_text','channel_link','bot_token','bot_username']
    for k, v in kwargs.items():
        if k in allowed:
            updates.append(f"{k}=?"); values.append(v)
    if not updates:
        conn.close(); return False
    values.append(partner_id)
    conn.execute(f"UPDATE partners SET {','.join(updates)} WHERE id=?", values)
    conn.commit(); conn.close()
    return True

def charge_partner_balance(partner_id, amount, description="شارژ حساب"):
    conn = get_db()
    conn.execute("UPDATE partners SET balance = balance + ? WHERE id=?", (amount, partner_id))
    conn.execute("INSERT INTO partner_transactions (partner_id, amount, type, description) VALUES (?,?,?,?)",
                 (partner_id, amount, 'charge', description))
    conn.commit(); conn.close()

def deduct_partner_balance(partner_id, amount, description="خرید کانفیگ"):
    conn = get_db()
    row = conn.execute("SELECT balance FROM partners WHERE id=?", (partner_id,)).fetchone()
    if not row or row['balance'] < amount:
        conn.close(); return False
    conn.execute("UPDATE partners SET balance = balance - ? WHERE id=?", (amount, partner_id))
    conn.execute("INSERT INTO partner_transactions (partner_id, amount, type, description) VALUES (?,?,?,?)",
                 (partner_id, -amount, 'deduct', description))
    conn.commit(); conn.close()
    return True

def get_partner_transactions(partner_id, limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM partner_transactions WHERE partner_id=? ORDER BY created_at DESC LIMIT ?",
        (partner_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_partner_config(name, config_data, volume_gb, cost=0):
    import logging
    logging.info(f"ADD PARTNER CONFIG: name={name} volume={volume_gb} cost={cost} data={config_data[:20]}")
    conn = get_db()
    conn.execute("INSERT INTO configs_partners (name, config_data, volume_gb, cost) VALUES (?,?,?,?)",
                 (name, config_data, volume_gb, cost))
    conn.commit(); conn.close()

def get_available_partner_config_names():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT name, volume_gb, COUNT(*) as cnt FROM configs_partners WHERE is_used=0 GROUP BY name ORDER BY volume_gb"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_partner_config_stock_summary():
    conn = get_db()
    rows = conn.execute(
        """SELECT name, volume_gb,
           COUNT(*) as total,
           SUM(CASE WHEN is_used=0 THEN 1 ELSE 0 END) as available,
           MAX(COALESCE(cost,0)) as cost
           FROM configs_partners GROUP BY name ORDER BY volume_gb"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_partner_plans(partner_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM partner_plans WHERE partner_id=? AND is_active=1 ORDER BY volume_gb",
        (partner_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_partner_plan(plan_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM partner_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_partner_plan(plan_id):
    conn = get_db()
    conn.execute("DELETE FROM partner_plans WHERE id=?", (plan_id,))
    conn.commit(); conn.close()

def get_partner_stats(partner_id):
    conn = get_db()
    total_orders = conn.execute(
        "SELECT COUNT(*) as c FROM partner_orders WHERE partner_id=? AND status='confirmed'", (partner_id,)
    ).fetchone()['c']
    total_spent = conn.execute(
        "SELECT COALESCE(SUM(cost),0) as s FROM partner_orders WHERE partner_id=? AND status='confirmed'", (partner_id,)
    ).fetchone()['s']
    partner = conn.execute("SELECT balance, credit_limit FROM partners WHERE id=?", (partner_id,)).fetchone()
    conn.close()
    return {
        'total_orders': total_orders,
        'total_spent': total_spent,
        'balance': partner['balance'] if partner else 0,
        'credit_limit': partner['credit_limit'] if partner else 0,
    }

def create_partner_charge_request(partner_id, amount, payment_method='card'):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO partner_charge_requests (partner_id, amount, payment_method) VALUES (?,?,?)",
        (partner_id, amount, payment_method)
    )
    req_id = cursor.lastrowid
    conn.commit(); conn.close()
    return req_id

def get_partner_charge_request(req_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM partner_charge_requests WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def confirm_partner_charge(req_id):
    conn = get_db()
    req = conn.execute("SELECT * FROM partner_charge_requests WHERE id=?", (req_id,)).fetchone()
    if not req or req['status'] != 'pending':
        conn.close(); return False
    conn.execute("UPDATE partner_charge_requests SET status='confirmed' WHERE id=?", (req_id,))
    conn.execute("UPDATE partners SET balance = balance + ? WHERE id=?", (req['amount'], req['partner_id']))
    conn.execute("INSERT INTO partner_transactions (partner_id, amount, type, description) VALUES (?,?,?,?)",
                 (req['partner_id'], req['amount'], 'charge', f'شارژ تایید شده #{req_id}'))
    conn.commit(); conn.close()
    return dict(req)

def reject_partner_charge(req_id):
    conn = get_db()
    conn.execute("UPDATE partner_charge_requests SET status='rejected' WHERE id=?", (req_id,))
    conn.commit(); conn.close()

# ── پلن‌های عمومی همکار (ساخته‌شده توسط ادمین مادر) ──────────────────────

def get_all_partner_plans(active_only=True):
    """همه پلن‌های عمومی که ادمین مادر ساخته (partner_id=NULL)"""
    conn = get_db()
    q = "SELECT * FROM partner_plans WHERE partner_id IS NULL"
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY category, cost"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_global_partner_plan(name, category, volume_gb, duration_days, max_devices, cost):
    """ساخت پلن عمومی توسط ادمین مادر"""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO partner_plans (partner_id, name, category, volume_gb, duration_days, max_devices, price, cost)
           VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (name, category, volume_gb, duration_days, max_devices, cost, cost),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def delete_global_partner_plan(plan_id):
    """حذف پلن عمومی"""
    conn = get_db()
    conn.execute("DELETE FROM partner_plans WHERE id=? AND partner_id IS NULL", (plan_id,))
    conn.commit()
    conn.close()

def get_global_partner_plan(plan_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM partner_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
