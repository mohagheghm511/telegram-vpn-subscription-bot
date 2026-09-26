import random
import inspect
import re
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .config import ADMIN_IDS
from .utils import CUSTOM_EMOJIS

def kbe(*args, **kwargs):
    text = kwargs.get("text", "")
    # Check for Telegram emoji tags with emoji-id
    if "icon_custom_emoji_id" not in kwargs:
        emoji_tag_pattern = r'<tg-emoji emoji-id="(\d+)">([^<]+)</tg-emoji>'
        match = re.search(emoji_tag_pattern, text)

        if match:
            emoji_id = match.group(1)
            kwargs["icon_custom_emoji_id"] = emoji_id
            # Remove the entire tag from text
            kwargs["text"] = re.sub(emoji_tag_pattern, "", text).strip()
        else:
            # longest match first for multi-char emojis
            for emoji in sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True):
                if emoji in text:
                    kwargs["icon_custom_emoji_id"] = CUSTOM_EMOJIS[emoji]
                    kwargs["text"] = text.replace(emoji, "", 1).strip()
                    break
    return KeyboardButton(*args, **kwargs)


def ikbe(*args, **kwargs):

    text = kwargs.get("text", "")
   # Check for Telegram emoji tags with emoji-id
    if "icon_custom_emoji_id" not in kwargs:
        emoji_tag_pattern = r'<tg-emoji emoji-id="(\d+)">([^<]+)</tg-emoji>'
        match = re.search(emoji_tag_pattern, text)

        if match:
            emoji_id = match.group(1)
            kwargs["icon_custom_emoji_id"] = emoji_id
            # Remove the entire tag from text
            kwargs["text"] = re.sub(emoji_tag_pattern, "", text).strip()
        else:
            # longest match first for multi-char emojis
            for emoji in sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True):
                if emoji in text:
                    kwargs["icon_custom_emoji_id"] = CUSTOM_EMOJIS[emoji]
                    kwargs["text"] = text.replace(emoji, "", 1).strip()
                    break
    return InlineKeyboardButton(*args, **kwargs)

SERVICE_NAMES = [
    "آلفا", "بتا", "گاما", "دلتا", "اپسیلون", "زتا", "اتا", "تتا",
    "فونیکس", "اوریون", "آریا", "پارسا", "کوروش", "داریوش", "آرش",
    "ستاره", "ماه", "خورشید", "ابر", "طوفان", "آذرخش", "رعد",
    "زمرد", "یاقوت", "الماس", "عقیق", "فیروزه", "مروارید",
    "شاهین", "عقاب", "پرنده", "اژدها", "ببر", "شیر", "پلنگ",
]

def ikb_with_color_edit(buttons, edit_mode=False, user_id=-1, strip_numbers=False):
    from .helpers import is_bot_admin
    is_admin = is_bot_admin(user_id, ADMIN_IDS)
    from .helpers import get_button_color
    buttons = buttons.copy()
    new_buttons = []
    n = len(buttons)
    for i in range(n):
        l = []
        j = len(buttons[i])
        for j in range(j):
            color = get_button_color(buttons[i][j].callback_data.replace("color_edit_", ""))
            buttons[i][j].style = color if color else buttons[i][j].style
            if buttons[i][j].callback_data.startswith(("exit_color_edit", "toggle_color_edit")):
                continue
            elif edit_mode and is_admin and not buttons[i][j].callback_data.startswith("color_edit_"):
                buttons[i][j].callback_data = "color_edit_" + buttons[i][j].callback_data
            if not edit_mode:
                buttons[i][j].callback_data = buttons[i][j].callback_data.replace("color_edit_", "")
            l.append(buttons[i][j])
        new_buttons.append(l)
    if is_admin:
        if edit_mode:
            new_buttons.append([ikbe(text="✅ خروج از ویرایش رنگ", callback_data="exit_color_edit")])
        else:
            new_buttons.append([ikbe(text="🎨 ویرایش رنگ ها", callback_data="toggle_color_edit")])
    return InlineKeyboardMarkup(inline_keyboard=new_buttons)

def _btn(key, default):
    try:
        from .helpers import get_setting
        val = get_setting(key)
        return val if val else default
    except Exception:
        return default

def main_keyboard(is_admin=False):
    buy     = _btn('btn_buy',        'خرید سرویس 🛒')
    free    = _btn('btn_free_test',  'تست رایگان 🎁')
    account = _btn('btn_account',    'حساب کاربری 🖥️')
    wallet  = _btn('btn_wallet',     'کیف پول 💰')
    conn_   = _btn('btn_connection', 'نحوه اتصال ⚙️')
    support = _btn('btn_support',    'پشتیبانی 👩‍💻')
    earn    = _btn('btn_earn',       'همکاری و کسب درآمد 💡')
    admin_  = _btn('btn_admin',      'پنل مدیریت 🛠')
    tornoment = _btn('btn_tornoment', 'مسابقه 🏆')

    rows = [
        [kbe(text=account), kbe(text=buy, style='primary')],
        # [kbe(text=tornoment)],
        [kbe(text=support), kbe(text=wallet)],
        [kbe(text=free)],
        [kbe(text=earn), kbe(text=conn_)],
    ]
    if is_admin:
        rows.append([kbe(text=admin_)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# def panel_inline(user_id=-1):
#     buttons = [
#         [
#             ikbe(text="پنل اصلی", callback_data="edit_panel_main_panel"),
#             # ikbe(text="پنل تست", callback_data="edit_panel_test_panel"),
#         ]
#         ,
#         [ikbe(text="کمترین مقدار موجودی", callback_data="edittxt_minimum_config_auto_charge")],
#         [ikbe(text="🔙 بازگشت", callback_data="admin_back")],
#     ]
#     return ikb_with_color_edit(buttons, user_id=user_id)

def back_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[kbe(text="🔙 بازگشت")]],
        resize_keyboard=True
    )

def categories_inline(categories, user_id=-1):
    buttons = []

    for i in range(0, len(categories), 1):
        row = [
            ikbe(
                text=f"📦 {cat}",
                callback_data=f"category_{cat}"
            )
            for cat in categories[i:i + 1]
        ]
        buttons.append(row)

    buttons.append([
        ikbe(text="🔙 بازگشت", callback_data="back_main")
    ])

    return ikb_with_color_edit(buttons, user_id=user_id)

def plans_inline(plans, category=None, user_id=-1):
    buttons = []
    for p in plans:
        # skip free plans
        if p["price"] <= 0:
            continue

        if p.get('custom_label'):
            label = p['custom_label']
        else:
            volume_display = "نامحدود 📊" if p['volume_gb'] == -1 else f"{p['volume_gb']} گیگ"
            duration_display = "نامحدود ⏱" if p['duration_days'] == -1 else f"{p['duration_days']} روز"
            label = f"{volume_display} | {duration_display} | {p['price']:,} تومان"
        buttons.append([ikbe(text=label, callback_data=f"plan_{p['id']}")])
    back_cb = f"back_category_{category}" if category else "back_main"
    buttons.append([ikbe(text="🔙 بازگشت", callback_data=back_cb)])
    return ikb_with_color_edit(buttons, user_id=user_id)


def payment_method_inline(order_id, user_id=-1, back="back_plans"):
    buttons = [
        [ikbe(text="🔙 بازگشت", callback_data=back), ikbe(text="💰 تایید و پرداخت", callback_data=f"paymethod_wallet_{order_id}"), ]
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def my_account_inline(services, user_id, page=0, per_page=10):
    buttons = []
    buttons.append([ikbe(text="➕ افزایش موجودی", callback_data="goto_wallet")])
    total = len(services)
    start = page * per_page
    end = min(start + per_page, total)
    page_services = services[start:end]
    if page_services:
        buttons.append([ikbe(text="━━━ سرویس‌های شما ━━━", callback_data="noop")])
        for s in page_services:
            sname = s.get('service_name') or s['plan_name']
            expire = s['expires_at'][:10] if s.get('expires_at') else '—'
            buttons.append([ikbe(
                text=f"📦 {sname} | تا {expire}",
                callback_data=f"srv_{s['id']}"
            )])
    nav = []
    if page > 0:
        nav.append(ikbe(text="◀️ قبلی", callback_data=f"account_page_{page-1}"))
    if end < total:
        nav.append(ikbe(text="بعدی ▶️", callback_data=f"account_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="back_main")])
    return ikb_with_color_edit(buttons, user_id=user_id)

def service_detail_inline(service_id, user_id=-1, is_free=False):
    buttons = []
    if is_free:
        buttons.append([ikbe(text="خرید اشتراک", callback_data="back_plans")],)

    buttons.append([ikbe(text="🔙 بازگشت", callback_data="back_to_account"), ikbe(text="📋 دریافت کانفیگ", callback_data=f"getconfig_{service_id}")])

    return ikb_with_color_edit(buttons, user_id=user_id)

def wallet_inline(user_id=-1):
    buttons = [
        [ikbe(text="💳 شارژ با کارت", callback_data="wallet_card"),
         ikbe(text="🪙 شارژ با ارز", callback_data="wallet_crypto")],
        [ikbe(text="🔙 بازگشت", callback_data="back_main")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def earn_inline(user_id=-1, is_active_partner=False):
    buttons = [
        [ikbe(text="🔗 لینک رفرال من", callback_data="my_referral")],
        [ikbe(text="🤝 همکاری حرفه‌ای 🔒", callback_data="partner_info")],
    ]
    if is_active_partner:
        buttons.append([ikbe(text="💰 شارژ حساب کانفیگ", callback_data="partner_charge_config")])
        buttons.append([ikbe(text="📊 پنل همکاری", callback_data="partner_panel_menu")])
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def partner_unlock_inline(user_id=-1):
    buttons = [
        [ikbe(text="💳 پرداخت و فعال‌سازی", callback_data="partner_unlock")],
        [ikbe(text="🔙 بازگشت", callback_data="back_earn")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def partner_panel_inline(user_id=-1):
    buttons = [
        [ikbe(text="➕ ساخت تست", callback_data="partner_create_test"),
         ikbe(text="⚙️ ساخت کانفیگ", callback_data="partner_create_config")],
        [ikbe(text="✏️ نام سرور", callback_data="partner_server_name"),
         ikbe(text="📊 آمار من", callback_data="partner_stats")],
        [ikbe(text="🔙 بازگشت", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def connection_guide_categories_inline(categories, user_id=-1):
    buttons = [[ikbe(text=f"📡 {cat}", callback_data=f"guide_cat_{cat}")] for cat in categories]
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="back_main")])
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_main_inline(user_id=-1):
    buttons = [
        [ikbe(text="📦 مدیریت پلن‌ها", callback_data="admin_plans"),
         ikbe(text="⚙️ افزودن کانفیگ", callback_data="admin_add_config")],
        [ikbe(text="👤 مدیریت کاربران", callback_data="admin_users"),
         ikbe(text="📢 پیام همگانی", callback_data="admin_broadcast")],
        [ikbe(text="🎁 تست رایگان", callback_data="admin_free_tests"),
         ikbe(text="👥 مدیریت ادمین", callback_data="admin_manage_admins")],
        [ikbe(text="⚙️ تنظیمات", callback_data="admin_settings"),
         ikbe(text="📊 آمار", callback_data="admin_stats")],
        [ikbe(text="⏳ صف انتظار", callback_data="admin_waiting_queue"),
         ikbe(text="📖 آموزش اتصال", callback_data="admin_guides")],
        [ikbe(text="🪧 ارسال پیام به کانال", callback_data="admin_channel_send"),
         ikbe(text="🪧 ارسال پیام تک دکمه", callback_data="admin_invite_send")],
        [
            ikbe(text="🤝 مدیریت همکارها", callback_data="admin_partners"),
        ],
        [ikbe(text="🏆 مسابقات", callback_data="admin_tornoment")],
        [ikbe(text="🔔 اعلان‌ها", callback_data="admin_notifications")],
        [ikbe(text="📢 عضویت اجباری", callback_data="admin_mandatory_channels")],
        [ikbe(text="🔴 خاموشی ربات", callback_data="shutdown_bot")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def free_test_cta_inline(service_id, category, user_id=-1, sticker_key=None):
    buttons = [
        [ikbe(text="جزئیات سرویس", callback_data=f"srv_free_{service_id}", style="danger"),
         ikbe(text="آموزش اتصال", callback_data=f"guide_free_cat_{category}_{service_id}", style="success")],
        [ikbe(text="خرید اشتراک", callback_data="back_plans")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id, strip_numbers=True)


def admin_plans_inline(plans, user_id=-1):
    buttons = []
    for p in plans:
        status = "✅" if p['is_active'] else "❌"
        buttons.append([ikbe(
            text=f"{status} {p['name']} | موجودی: {p['stock']}",
            callback_data=f"admin_plan_{p['id']}"
        )])
    buttons.append([
        ikbe(text="➕ افزودن پلن جدید", callback_data="admin_add_plan"),
        ikbe(text="🔙 بازگشت", callback_data="admin_back"),
    ])
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_plan_detail_inline(plan_id, user_id=-1):
    buttons = [
        [ikbe(text="✏️ ویرایش", callback_data=f"edit_plan_name_{plan_id}"),
         ikbe(text="🗑️ حذف", callback_data=f"delete_plan_confirm_{plan_id}")],
        [ikbe(text="🔙 بازگشت", callback_data="admin_plans")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_settings_inline(user_id=-1):
    settings_list = [
        ("💳 شماره کارت", "edittxt_card_number"),
        ("👤 نام صاحب کارت", "edittxt_card_owner"),
        ("🪙 آدرس کیف ارز دیجیتال", "edittxt_crypto_address"),
        ("🌐 شبکه ارز دیجیتال", "edittxt_crypto_network"),
        ("🌐 دعوت لازم برای کانفیگ رایگان", "edittxt_threash_hold_referrer"),
        ("⏲ زمان لغو خودکار کارت به کارت", "edittxt_automatic_timeout"),
        ("📢 آیدی چنل پشتیبانی", "edittxt_support_channel_id"),
        ("📋 آیدی چنل فیش‌ها", "edittxt_receipt_channel_id"),
        ("📋 آیدی چنل فیش‌های اتوماتیک", "edittxt_receipt_auto_channel_id"),
        ("🎁 پاداش رفرال (تومان)", "edittxt_referral_bonus"),
        ("🤝 هزینه فعال‌سازی همکاری", "edittxt_partner_fee"),
        ("✏️ ویرایش متن‌های ربات", "admin_edit_texts"),
    ]
    buttons = [[ikbe(text=label, callback_data=cb)] for label, cb in settings_list]
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="admin_back")])
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_user_inline(user_id):
    buttons = [
        [ikbe(text="💰 ویرایش موجودی", callback_data=f"admin_edit_wallet_{user_id}"),
         ikbe(text="🚫 بن/رفع‌بن", callback_data=f"admin_ban_{user_id}")],
        [ikbe(text="📋 سرویس‌های کاربر", callback_data=f"admin_user_services_{user_id}"),
         ikbe(text="✏️ ویرایش سرویس", callback_data=f"admin_edit_service_{user_id}")],
        [ikbe(text="🔙 بازگشت", callback_data="admin_users")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_queue_item_inline(queue_id, plan_id, user_id=-1):
    buttons = [
        [ikbe(text="🗑 حذف از صف", callback_data=f"delete_queue_{queue_id}"),
         ikbe(text="🔙 بازگشت", callback_data="admin_waiting_queue")],
    ]
    return ikb_with_color_edit(buttons, user_id=user_id)

def admin_mandatory_channels_inline(channels, user_id=-1):
    buttons = []
    for ch in channels:
        buttons.append([ikbe(
            text=f"❌ {ch.get('title')} - {ch.get('username')}",
            callback_data=f"admin_mandatory_remove_{ch['id']}",
        )])
    buttons.append([ikbe(text="➕ افزودن کانال", callback_data="admin_mandatory_add")])
    buttons.append([ikbe(text="🔙 بازگشت", callback_data="admin_back")])
    return ikb_with_color_edit(buttons, user_id=user_id)

def mandatory_join_inline(missing_channels, user_id=-1):
    buttons = []
    for ch in missing_channels:
        title = ch.get('title') or ch.get('username') or str(ch['channel_id'])
        if ch.get('username'):
            buttons.append([ikbe(text=f"📢 {title}", url=f"https://t.me/{ch['username']}", style='primary')])
        else:
            buttons.append([ikbe(text=f"📢 {title}", callback_data="noop", style='danger')])
    buttons.append([ikbe(text="✅ بررسی عضویت", callback_data="check_mandatory_join", style='success')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

