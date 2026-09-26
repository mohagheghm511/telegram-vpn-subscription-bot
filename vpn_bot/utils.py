import io
import logging
import re

import qrcode
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .database import CategorySetting, Setting
from .pasarguard import PGPanel
from .config import ADMIN_IDS
from .helpers import get_all_admins
from functools import wraps


CUSTOM_EMOJIS = {
  "✈️": "5927118708873892465",
  "🍏": "5775870512127283512",
  "⭐️": "5886685105065300941",
  "🎁": "5805298713211447980",
  "🔣": "5764638872000533034",
  "🖥": "5942734685976138521",
  "⚙️": "5924722061288150929",
  "⚙": "6032742198179532882",
  "🎛": "5771449289972650710",
  "📰": "5893057118545646106",
  "📝": "5778299625370817409",
  "📋": "5778299625370817409", # add
  "🗂": "5766994197705921104",
  "↔️": "5778593237925105705",
  "⬅️": "6039519841256214245",
  "🔙": "5258236805890710909", # additional line
  "🤝": "6033125983572201397", # new
  "🔁": "6030657343744644592",
  "⏫": "5938437708635443119",
  "✏️": "5771847914477326786",
  "✏": "6039614175917903752",
  "❌": "5774077015388852135",
  "⌨": "6039404727542747508",
  "📎": "5776138384942567185",
  "🔧": "5962952497197748583",
  "🔨": "5836866396419530588",
  "🚪": "6035130900075777681",
  "🔎": "6032850693348399258",
  "🏷": "5890727932011223292",
  "↩️": "5778432163766604235",
  "➡️": "6037622221625626773",
  "📺": "6044356915029348425",
  "🔗": "5766902139376898645",
  "➕": "5882207227997066107",
  "ℹ": "6028435952299413210",
  "❓": "6030848053177486888",
  "❗️": "6030563507299160824",
  "‼️": "6030563507299160824",
  "▶️": "5850346984501680054",
  "✅": "6030839471832829491",
  "⬆️": "5776288820467077551",
  "🔓": "6037496202990194718",
  "🔒": "5778570255555105942",
  "🖼": "5776253421346625666",
  "🤖": "5983580310292402968",
  "📁": "5805382340519664323",
  "📄": "6050643982646513651",
  "🗑": "6039522349517115015",
  "🎶": "5938473438468378529",
  "👁": "5935757052042285202",
  "⬇️": "5963087934696459905",
  "☁": "6028115612163641653",
  "📤": "6043874504302661409",
  "🛡": "6030445631921721471",
  "📂": "6039348811363520645",
  "📥": "5776182936638329359",
  "📢": "6039381989985882045",
  "📣": "6039422865189638057",
  "🔊": "6039454987250044861",
  "🔇": "6039505337151655702",
  "🔈": "6039853100653612987",
  "🔔": "6039677157318332604",
  "🔕": "6039569594157371705",
  "📷": "5766975922620076409",
  "🎞": "5937999673510858217",
  "❤️": "5938368005611195877",
  "📖": "6039584437564347225",
  "5️⃣": "6035231690073314447",
  "2️⃣": "5940420518942347102",
  "⏰": "5850317551090800862",
  "🕓": "5775896410780079073",
  "👣": "5843679481566335204",
  "✅️": "5843596438373667352",
  "⏲️": "5769230088960741619",
  "⏰️": "5983150113483134607",
  "🥇": "6037428784888549034",
  "1️⃣": "5940515192906456099",
  "🎥": "5884351885556585857",
  "🎤": "5933678317935791830",
  "🎙": "6044117517847236354",
  "📞": "6037418554276452311",
  "☎️": "6039398100408209720",
  "💬": "5936035091045159318",
  "💡": "5767288287001580715",
  "💭": "5904248647972820334",
  "💤": "5983401171501454028",
  "🔞": "6050842281286570825",
  "📍": "5983099415689171511",
  "👤": "5884366771913233289",
  "🆔": "5884366771913233289",# new
  "🗣": "5766919430915232878",
  "👥": "5938196735200333756",
  "🎯": "6032949275732742941",
  "🎭": "6032882536235932111",
  "🙂": "6039587087559168309",
  "🙁": "5778197572652897847",
  "😀": "5935824500208702046",
  "😝": "6043847274210005137",
  "🤔": "6043960760130868895",
  "😐": "6041748912102968702",
  "😨": "6043973168291384891",
  "☹️": "6042029429301973188",
  "😡": "6044118213631938928",
  "🐻": "6044004057696177711",
  "🎉": "6041731551845159060",
  "👋": "5985478698722136468",
  "👍": "6041720006973067267",
  "👎": "6041716699848249286",
  "👆": "5884106131822875141",
  "✋️": "5891184096192763888",
  "🚫": "5938071395169734715",
  "👏": "5994417835630137549",
  "🍔": "6041874690220233085",
  "🎂": "5922681543800655962",
  "🛁": "6041963669057703997",
  "🏳️": "6041923781696426657",
  "🪧": "6042098561095570207",
  "⛱️": "6041933986538721961",
  "🗺": "5904650558127478452",
  "🏠": "6042137469204303531",
  "🏡": "5938537205847822613",
  "💼": "5938492039971737551",
  "🎓": "5938195768832692153",
  "👓": "5882223295469722324",
  "🔫": "5767356727305441799",
  "🎮": "5938413566624272793",
  "⚽️": "6042069608721027027",
  "⚪️": "5884094183223857554",
  "⬜️": "5884089033558070257",
  "☁️": "5884330496619450755",
  "📸": "5879995903955179148",
  "⚡": "5884428842780594914",
  "⚡️": "5922272602784534896",
  "🔄": "5769248574499983619",
  "#️⃣": "5850693253355017860",
  "☀️": "5769527287812723055",
  "🌝": "5938342819922973434",
  "🪟": "6034834092065821141",
  "📌": "6041777576714702813",
  "⭕️": "5776428312414917091",
  "✨": "5940660740758184142",
  "📦": "5884479287171485878",
  "🌙": "5769143090103193926",
  "♾": "6048407885233263063",
  "🛜": "6048723247501938454",
  "💊": "6050677620830376838",
  "💧": "6050944866580435869",
  "🖍": "5771798621137670637",
  "🖌": "6050877727651664314",
  "🧽": "5811966564039135541",
  "🫥": "5812150667812280629",
  "🪄": "6021792097454002931",
  "👩‍🎨": "5769635757211784031",
  "🔃": "5767310088255576068",
  "🔡": "5767262289564536912",
  "🅰": "5769403725898584391",
  "✂️": "5771880672192893347",
  "📈": "5935913431801532272",
  "📊": "5936143551854285132",
  "🌐": "5776233299424843260",
  "🏧": "5879814368572478751",
  "💰": "5904359114531675993",
  "🪙": "5890848474563352982",
  "💵": "5890848474563352982", #add
  "💳": "5445353829304387411", #add
  "💎": "5836907383292436018",
  "🤑": "5902206159095339799",
  "🏪": "5920332557466997677",
  "📟": "5776118099812028333",
  "🌀": "6050588788021793070",
  "🔳": "5771652845652677093",
  "📅": "5891100675042974129",
  # "⏲": "5891211339170326418", #
  "⏳": "5891211339170326418", # new
  "⏱": "5891211339170326418", # new 2
  "⏲": "5891211339170326418",
  "👛": "5769126056262898415",
  # "⏲": "6030537810509828330",
  "🕶": "5962882510705660145",
  "🧠": "5864019342873598613",
  "🧭": "6030687898141987254",
  "🆕": "5895669571058142797",
  "🪐": "5891156376473836675",
  "1⃣": "5794375786743995258",
  "2⃣": "5793900634512039101",
  "3⃣": "5793981487271386646",
  "4⃣": "5794377032284510899",
  "5⃣": "5794421072879164075",
  "6⃣": "5794125282776456691",
  "7⃣": "5793921538117868592",
  "8⃣": "5794030230855227946",
  "9⃣": "5793886611443817052",
  "👑": "5805553606635559688",
  "🌟": "5895708410447401643",
  "🧩": "5837069325034331827",
  "TON_LOGO": "5382164415019768638",# ton logo
  "🏆": "5857399969341774943",
  "🥇": "5440539497383087970",
  "🥈": "5447203607294265305",
  "🥉": "5453902265922376865",
  "😴": "5911290659171471320"

}



def only_admin(handler):
    @wraps(handler)
    async def wrapper(event: Message | CallbackQuery, *args, **kwargs):

        admins = set(ADMIN_IDS) | set(get_all_admins())

        user = event.from_user

        if not user or user.id not in admins:
            if isinstance(event, CallbackQuery):
                await event.answer("دسترسی ندارید", show_alert=True)

            elif isinstance(event, Message):
                await event.reply("دسترسی ندارید")

            return

        return await handler(event, *args, **kwargs)

    return wrapper


async def get_panel(category):
    settings = CategorySetting.get(category)

    host = settings.get("host") or ""
    token = settings.get("token") or ""
    group_ids = (settings.get("group_ids") or "").split(",")

    username, password = token.split(":")

    return await PGPanel.create(base_url=host, username=username, password=password, groups=group_ids)


async def get_pg(t = "main"):
    host = Setting.get(f"{t}_panel_host", "")
    token = Setting.get(f"{t}_panel_token", "")
    username, password = token.split(":")
    groups = Setting.get(f"{t}_panel_groups", "")
    groups = groups.split(",")
    return await PGPanel.create(base_url=host, username=username, password=password, groups=groups)

def _generate_qr_image(data: str, box_size: int = 10, border: int = 2):
    """Generate QR code image bytes with error handling"""
    if not data:
        return None

    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return BufferedInputFile(buf.getvalue(), filename="qrcode.png")
    except Exception as e:
        logging.error(f"QR generation failed: {e}")
        return None



def t(text):
    # Pattern to match existing tg-emoji tags
    emoji_tag_pattern = r'<tg-emoji emoji-id="[^"]+">.</tg-emoji>'

    # Split text into segments: emoji tags and plain text
    parts = re.split(f'({emoji_tag_pattern})', text)

    result = []
    for part in parts:
        # If it's already a tag, keep it as-is
        if re.match(emoji_tag_pattern, part):
            result.append(part)
        else:
            # Process plain text
            result.append("".join(
                f'<tg-emoji emoji-id="{CUSTOM_EMOJIS[ch]}">{ch}</tg-emoji>'
                if ch in CUSTOM_EMOJIS else ch
                for ch in part
            ))

    return "".join(result)



def setup_emoji_converter(bot: Bot):
  """
  Patches all bot methods to automatically convert emojis.
  Call this once after creating your bot instance.
  """

  # 1. Patch bot.send_message
  original_send_message = bot.send_message

  async def send_message_with_emoji(
      chat_id: int | str,
      text: str,
      parse_mode: str | None = None,
      **kwargs
  ) -> Message:
      converted_text = t(text)
      # Force HTML parse mode for custom emojis to work
      parse_mode = parse_mode or ParseMode.HTML
      return await original_send_message(chat_id, converted_text, parse_mode=parse_mode, **kwargs)

  bot.send_message = send_message_with_emoji


  # 2. Patch Message.answer
  original_message_answer = Message.answer

  async def message_answer_with_emoji(
      self,
      text: str,
      parse_mode: str | None = None,
      **kwargs
  ) -> Message:
      converted_text = t(text)
      parse_mode = parse_mode or ParseMode.HTML
      return await original_message_answer(self, converted_text, parse_mode=parse_mode, **kwargs)

  Message.answer = message_answer_with_emoji


  # 3. Patch Message.reply
  original_message_reply = Message.reply

  async def message_reply_with_emoji(
      self,
      text: str,
      parse_mode: str | None = None,
      **kwargs
  ) -> Message:
      converted_text = t(text)
      parse_mode = parse_mode or ParseMode.HTML
      return await original_message_reply(self, converted_text, parse_mode=parse_mode, **kwargs)

  Message.reply = message_reply_with_emoji


  # 4. Patch CallbackQuery.answer (for popup messages)
  original_callback_answer = CallbackQuery.answer

  async def callback_answer_with_emoji(
      self,
      text: str | None = None,
      **kwargs
  ) -> bool:
      if text:
          text = t(text)
      return await original_callback_answer(self, text, **kwargs)

  CallbackQuery.answer = callback_answer_with_emoji


  # 5. Patch CallbackQuery.message.answer
  original_callback_message_answer = CallbackQuery.message.answer if hasattr(CallbackQuery, 'message') else None


  # 6. Patch bot.edit_message_text
  original_edit_message_text = bot.edit_message_text

  async def edit_message_text_with_emoji(
      text: str,
      chat_id: int | str | None = None,
      message_id: int | None = None,
      inline_message_id: str | None = None,
      parse_mode: str | None = None,
      **kwargs
  ) -> Message | bool:
      converted_text = t(text)
      parse_mode = parse_mode or ParseMode.HTML
      return await original_edit_message_text(
          converted_text,
          chat_id=chat_id,
          message_id=message_id,
          inline_message_id=inline_message_id,
          parse_mode=parse_mode,
          **kwargs
      )

  bot.edit_message_text = edit_message_text_with_emoji


  # 7. Patch Message.edit_text
  original_message_edit_text = Message.edit_text

  async def message_edit_text_with_emoji(
      self,
      text: str,
      parse_mode: str | None = None,
      **kwargs
  ) -> Message | bool:
      converted_text = t(text)
      parse_mode = parse_mode or ParseMode.HTML
      return await original_message_edit_text(self, converted_text, parse_mode=parse_mode, **kwargs)

  Message.edit_text = message_edit_text_with_emoji
