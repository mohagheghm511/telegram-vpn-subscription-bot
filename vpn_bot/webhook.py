from .keyboards import ikb_with_color_edit, ikbe
from .helpers import get_invoice_by_price, get_channel_id, reject_invoice, charge_wallet, alert_admins
import asyncio
from aiohttp import web
from .database import Setting, Invoice
import logging
import json
import re
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_bot():
    from .handlers_user import bot
    return bot

PATTERNS = [
    r'([0-9,]+)\s*ریال\s*به حساب شما نشست',  # Blu
    r'انتقال:\s*([\d,]+)\+',                 # Melli
    r'واریز:\s*([\d,]+)\s*ریال',             # Tejarat
]

def extract_deposit_amount(text: str) -> str | None:
    for pattern in PATTERNS:
        m = re.search(pattern, text)
        if m:
            return m.group(1).replace(',', '')
    return None


async def confirm_charge_automatic(amount: int, bot):
    invoice = get_invoice_by_price(amount)
    text = "\n\n✅ تایید اتوماتیک"
    if not invoice:
        text = "\nخطای نا شناخته رخ داده ❌"
        text += f"\nفاکتور با مبلغ {amount} یافت نشد."
        logging.error(f"sms: can't confirm invoice with amount {amount}")
        return

    invoice = Invoice.confirm(invoice[0])
    if not invoice:
        logging.error(f"sms: failed to confirm invoice with amount {amount}")
        return

    logging.info(f"sms: charge user {invoice.user_id} with {amount} TOMAN")
    charge_wallet(invoice.user_id, invoice.amount, "شارژ کیف پول توسط ربات خودکار")

    channel_id = get_channel_id('receipt_auto_channel_id')

    if invoice.channel_message_id and invoice.channel_message_id > 0:
        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=invoice.channel_message_id,
            text=invoice.text + text,
        )
    else:
        await bot.send_message(
            chat_id=channel_id,
            text=invoice.text + text,
        )

    charge_msg = Setting.get('msg_wallet_charge_confirm')
    charge_msg = charge_msg.replace('{amount}', f"{amount:,}")
    if invoice.chat_message_id and invoice.chat_message_id > 0:
        await bot.delete_message(chat_id=invoice.user_id, message_id=invoice.chat_message_id)

    await bot.send_message(chat_id=invoice.user_id, text=charge_msg, reply_markup=None)

async def reject_charge_automatic(invoice_id: int, bot):
    invoice = reject_invoice(invoice_id)
    t = Setting.get("automatic_timeout")

    text = f"\n\nرد اتوماتیک بعد از {t} دقیقه ❌"
    if not invoice:
        text = "\nخطای نا شناخته رخ داده ❌"

    user_id = invoice[1]
    amount = invoice[2]
    msg_id = invoice[5]
    invoice_text = invoice[6]
    channel_id = get_channel_id('receipt_auto_channel_id')
    if msg_id > 0:
        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=msg_id,
            text=invoice_text + text,
        )
    else:
        await bot.send_message(
            chat_id=channel_id,
            text=invoice_text + text,
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[ikbe(text="✅️ بله پرداخت کردم", callback_data=f"fallback_automatic_{amount}", style="success")]])
    text = Setting.get('msg_wallet_charge_auto_fail')
    text = text.format(amount=f"{amount:,}")
    await bot.send_message(user_id,text=text, reply_markup=kb)


async def check_sms(amount:int, bot):
    t = int(Setting.get("automatic_timeout", "15"))
    sec = int(t*60)
    await asyncio.sleep(sec)
    invoice = get_invoice_by_price(amount)
    if invoice:
        await reject_charge_automatic(invoice[0], bot)


# SMS API endpoint handler
async def sms_api_handler(request):
    """
    Handle SMS via API POST request
    Expected JSON format:

    ```json

    {
        'from': '+1234567890',
        'text': 'Hello',
        'sentStamp': 1780403717000,
        'receivedStamp': 1780403730213,
        'sim': 'sim2'
    }

    ```
    """
    try:
        data = await request.json()
        logging.info(f"sms: {data}")
        bot = get_bot()
        await alert_admins(bot, f"#sms:\n {data}")
        message = data.get('message', '')

        if not message:
            return web.json_response(
                {"status": "error", "message": "Message field is required"},
                status=400
            )
        rial = extract_deposit_amount(message)
        if not rial:
            return web.json_response(
                {"status": "error", "message": "Invalid format"},
                status=400
            )
        rial = rial.replace(",", "")
        toman = (int(rial)//10)
        logging.info(f"sms: amount -> {toman}")

        await confirm_charge_automatic(toman, bot)

        return web.json_response({
            "status": "success",
            "message": "SMS received and stored",
        })

    except json.JSONDecodeError:
        return web.json_response(
            {"status": "error", "message": "Invalid JSON"},
            status=400
        )
    except Exception as e:
        logging.error(f"Error processing SMS API request: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)},
            status=500
        )
