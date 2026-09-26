import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
SMS_API_PATH = "/api/sms"
WEBHOOK_PATH = "/webhook"
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "your-domain.com")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = list(map(int, ADMIN_IDS_ENV.split(","))) if ADMIN_IDS_ENV else []
