import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN
from .database import init_db
from .handlers_user import dp, bot
from .handlers_admin import register_admin_handlers
from .handlers_partner import register_partner_handlers
from .handlers_admin_partners import register_admin_partner_handlers
from .config import WEBHOOK_PATH,WEBHOOK_HOST,WEBHOOK_PORT,WEBHOOK_URL, SMS_API_PATH
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from .webhook import sms_api_handler
from .tornoment import tornoment_handler
from .scheduler import start_scheduler
from .admin.notification import register_notification_handlers, seed_default_rules
from .models.db_init import init_db_async
from .users.free_test import register_free_test_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
async def on_startup(bot: Bot):
    await start_scheduler(bot)

    bot_info = await bot.get_me()
    logging.info(f"Bot info: {bot_info}")
    logging.info(f"Bot can accept payments: {bot_info.can_join_groups}")  # Check permissions

    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

def webhook():
    init_db()
    asyncio.run(init_db_async())
    app = web.Application()

    app.router.add_post(SMS_API_PATH, sms_api_handler)
    register_admin_handlers(dp)
    register_partner_handlers(dp)
    register_admin_partner_handlers(dp)
    register_admin_handlers(dp)
    seed_default_rules()
    register_free_test_handlers(dp)
    register_notification_handlers(dp)

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    # Set startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start web server
    logging.info(f"Starting server on {WEBHOOK_HOST}")
    logging.info(f"Telegram webhook: {WEBHOOK_PATH}")
    logging.info(f"SMS API: {SMS_API_PATH}")
    # asyncio.create_task(continous_ton_check())
    web.run_app(app, host="127.0.0.1", port=WEBHOOK_PORT)


async def main():
    await init_db_async()
    init_db()
    register_admin_handlers(dp)
    register_partner_handlers(dp)
    register_admin_partner_handlers(dp)
    register_admin_handlers(dp)
    seed_default_rules()
    register_notification_handlers(dp)
    register_free_test_handlers(dp)
    tornoment_handler(dp)
    await bot.delete_webhook()
    await start_scheduler(bot)

    logging.info("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    # webhook()
