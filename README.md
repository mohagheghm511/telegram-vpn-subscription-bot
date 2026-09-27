<div align="center">

# 🔐 Telegram Subscription Sales Bot: Automatic Payment & Delivery

**A production Telegram bot that sells service subscriptions from start to finish.** Payments are confirmed automatically and the service is created and delivered on the spot, with no admin involvement.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-SQLAlchemy-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/source-open-success)

</div>

---

## ✨ Features

### 🛒 For customers
- **Buy a subscription** from categorized plans (traffic volume, duration, device type).
- **Wallet:** top up by card-to-card transfer or cryptocurrency, then pay for plans from the balance.
- **Automatic delivery:** as soon as payment is confirmed, the bot creates the account on the **Pasarguard** panel and sends the config, a subscription link and a QR code.
- **My services:** usage, expiry, config details and renewal.
- **Free trial** account, with a queue when trial stock runs out.
- **Referral link** with rewards, plus **referral tournaments** with leaderboards.
- **Connection tutorials** and **mandatory channel membership**.

### ⚡ Automatic payment confirmation
A webhook receives the **bank's deposit SMS** (forwarded from a phone). The bot parses the amount (Blu, Melli, Tejarat and other formats), matches it to the pending invoice, confirms it, and charges the wallet or activates the plan, all within seconds.

### 🤝 Reseller / partner system
- Users can apply to become a **partner (reseller)** for a configurable fee.
- Partners get their own panel, statistics, custom server name, partner-only plans and prices, trial creation and a separate config wallet.

### 🛠️ Admin panel (inside Telegram)
- Plan management (add, edit, delete, pricing), manual config stock with low-stock alerts.
- User management, **multi-level admins** (bot admin, channel admin, both).
- Broadcast messages, channel posts with buttons, a notification center with templates.
- Statistics, the trial queue, tournaments, mandatory-join settings, and a **maintenance switch**.
- **Live UI customization:** edit button colors and texts directly from the bot.
- **Scheduled jobs:** expiry reminders and automatic notifications.

## 🧰 Tech Stack
Python · aiogram 3 · SQLAlchemy + SQLite · aiohttp (webhooks) · Pasarguard API SDK · qrcode · jdatetime

## 🚀 Getting Started
```bash
git clone https://github.com/mohagheghm511/telegram-vpn-subscription-bot.git
cd telegram-vpn-subscription-bot
pip install -r requirements.txt
cp .env.example .env        # fill in your values
python -m vpn_bot
```

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Bot token from @BotFather |
| `ADMIN_IDS` | Comma-separated numeric Telegram IDs of the super-admins |
| `WEBHOOK_HOST` / `WEBHOOK_PORT` | Public domain and port for the payment-SMS webhook |

The database is created **empty on first run**. Plans, panel credentials and texts are all configured from the admin panel inside the bot.

## 📁 Project Structure
```
vpn_bot/
├── main.py / __main__.py     # entry point
├── handlers_user.py          # customer flows
├── handlers_admin.py         # admin panel
├── handlers_partner.py       # reseller flows
├── handlers_admin_partners.py
├── webhook.py                # bank-SMS payment confirmation
├── pasarguard.py             # panel API client
├── scheduler.py              # reminders & background jobs
├── tornoment.py              # referral tournaments
├── admin/notification.py     # notification center
├── models/ · database.py     # data layer
└── keyboards.py · formatting.py · helpers.py · utils.py
```

---
<div align="center">Built by <a href="https://github.com/mohagheghm511">@mohagheghm511</a> · Need a custom bot? Get in touch.</div>
