import logging
import os
import sys
import time
from typing import Dict, List
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
from telegram.error import TelegramError, NetworkError, TimedOut
from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError
from dotenv import load_dotenv
import pytz
from datetime import time

load_dotenv()

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
IS_WEBHOOK = bool(WEBHOOK_URL)

log_handlers = [logging.StreamHandler(sys.stdout)]
if not IS_WEBHOOK:
    log_handlers.append(logging.FileHandler("bot.log"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not GROQ_API_KEY:
    logger.error("GROQ_API_KEY topilmadi")
    raise ValueError("GROQ_API_KEY .env faylda topilmadi")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN topilmadi")
    raise ValueError("TELEGRAM_TOKEN .env faylda topilmadi")
if not ADMIN_CHAT_ID:
    logger.warning("ADMIN_CHAT_ID topilmadi, admin hisobotlari o'chirilgan")

masked_token = TELEGRAM_TOKEN[:8] + "..." + TELEGRAM_TOKEN[-4:] if TELEGRAM_TOKEN else "None"
logger.info(f"TELEGRAM_TOKEN yuklandi: {masked_token}")

client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

chat_histories: Dict[int, List[Dict[str, str]]] = {}
user_profiles: Dict[int, Dict[str, str]] = {}
stats = {"requests": 0, "errors": 0}
MAX_HISTORY_LENGTH = 10
MAX_RETRIES = 3
RETRY_DELAY = 2

SYSTEM_PROMPT = (
    "Siz NuMoN nomli aqlli va do'stona o'zbek tilidagi yordamchisiz. "
    "Faqat o'zbek tilida javob bering. Javoblaringiz aniq, qisqa va foydali bo'lsin. "
    "Kod yozganda izohsiz, toza kod bering. "
    "Matnda ### yoki *** belgilar ishlatmang. "
    "Foydalanuvchiga ismini aytib murojaat qiling."
)

reply_keyboard = [[KeyboardButton("Yangi suhbat")]]
markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)


def safe_markdown(text: str) -> str:
    """Telegram MarkdownV2 uchun maxsus belgilarni tozalash."""
    if not text:
        return ""
    chars_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in chars_to_escape:
        text = text.replace(ch, f"\\{ch}")
    return text


async def safe_send(chat_id: int, text: str, context, parse_mode=None, **kwargs):
    """Xatolarga chidamli xabar yuborish. Message obyekti yoki None qaytaradi."""
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            **kwargs
        )
    except TelegramError as e:
        logger.warning(f"Xabar yuborishda xato (chat={chat_id}): {e}")
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e2:
            logger.error(f"Xabar yuborish to'liq muvaffaqiyatsiz (chat={chat_id}): {e2}")
            return None


async def safe_delete(chat_id: int, message_id: int, context) -> bool:
    """Xatolarga chidamli xabar o'chirish."""
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramError:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name or "Foydalanuvchi"
        chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT.format(name=user_name)}]
        user_profiles[chat_id] = {"name": user_name, "requests": 0}
        await safe_send(
            chat_id, 
            f"Salom, {user_name}! Men NuMoN — sun'iy intellekt yordamchingizman. Sizga qanday yordam bera olaman? 😊",
            context,
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"Yangi sessiya boshlandi: chat={chat_id}, foydalanuvchi={user_name}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"start funksiyasida xato: {e}")


def get_ai_response(chat_id: int, message: str) -> str:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if chat_id not in chat_histories:
                chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

            chat_histories[chat_id].append({"role": "user", "content": message})

            if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
                system_message = chat_histories[chat_id][0]
                chat_histories[chat_id] = [system_message] + chat_histories[chat_id][-MAX_HISTORY_LENGTH + 1:]

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=chat_histories[chat_id],
                max_tokens=700,
                temperature=0.7,
                timeout=30
            )

            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Groq bo'sh javob qaytardi")

            ai_response = response.choices[0].message.content.strip()
            chat_histories[chat_id].append({"role": "assistant", "content": ai_response})
            return ai_response

        except (APIConnectionError, APITimeoutError, NetworkError) as e:
            logger.warning(f"Groq ulanish xatosi (urinish {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            stats["errors"] += 1
            return "Server bilan bog'lanishda muammo yuz berdi. Iltimos, birozdan keyin qayta urinib ko'ring."

        except RateLimitError as e:
            stats["errors"] += 1
            logger.error(f"Groq limit xatosi: {e}")
            return "So'rovlar limiti oshib ketdi. Iltimos, biroz kuting va qayta urinib ko'ring."

        except APIError as e:
            logger.error(f"Groq API xatosi: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            stats["errors"] += 1
            return "Sun'iy intellekt xizmatida vaqtinchalik muammo. Qayta urinib ko'ring."

        except Exception as e:
            logger.error(f"Groq kutilmagan xato: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            stats["errors"] += 1
            return "Kechirasiz, xatolik yuz berdi. Iltimos, qayta urinib ko'ring."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_message = None

    try:
        user_message = update.message.text.strip() if update.message.text else ""
        stats["requests"] += 1

        if user_message == "Yangi suhbat":
            await new_chat(update, context)
            return

        if chat_id not in chat_histories:
            user_name = update.effective_user.first_name or "Foydalanuvchi"
            chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT.format(name=user_name)}]
            user_profiles[chat_id] = {"name": user_name, "requests": 0}

        if chat_id in user_profiles:
            user_profiles[chat_id]["requests"] += 1

        loading = await safe_send(chat_id, "Javob tayyorlanmoqda... ⏳", context, parse_mode='Markdown')
        loading_id = loading.message_id if loading else None

        try:
            ai_response = get_ai_response(chat_id, user_message)
        finally:
            if loading_id:
                await safe_delete(chat_id, loading_id, context)

        await safe_send(chat_id, ai_response, context, parse_mode='Markdown', reply_markup=markup)
        logger.info(f"Matnli so'rov: chat={chat_id}, xabar={user_message[:50]}")

    except TelegramError as e:
        stats["errors"] += 1
        logger.error(f"Telegram xatosi (chat={chat_id}): {e}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Xabarni qayta ishlashda xato (chat={chat_id}): {e}")
        try:
            await safe_send(chat_id, "Kechirasiz, xatolik yuz berdi. Iltimos, qayta urinib ko'ring.", context)
        except Exception:
            pass


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = update.effective_chat.id
        user_name = user_profiles.get(chat_id, {}).get("name", "Foydalanuvchi")
        chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT.format(name=user_name)}]
        await safe_send(
            chat_id,
            "Yangi suhbat boshlandi! Yangi savollaringizni kutyapman. 😊",
            context,
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"Yangi suhbat: chat={chat_id}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Yangi suhbatda xato: {e}")


async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = update.effective_chat.id
        await safe_send(
            chat_id,
            f"Statistika:\n- So'rovlar: {stats['requests']}\n- Xatolar: {stats['errors']}",
            context,
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"Statistika so'raldi: chat={chat_id}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Statistikada xato: {e}")


async def send_status_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_CHAT_ID:
        return
        mode = "Webhook" if IS_WEBHOOK else "Polling (Lokal)"
    report = (
        f"Bot holati:\n"
        f"- Rejim: {mode}\n"
        f"- So'rovlar: {stats['requests']}\n"
        f"- Xatolar: {stats['errors']}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=report)
        logger.info("Admin hisoboti yuborildi")
    except Exception as e:
        logger.error(f"Admin hisobotida xato: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global xato ushlagich."""
    logger.error(f"Global xato: {context.error}", exc_info=True)
    try:
        if update and hasattr(update, 'effective_chat'):
            await safe_send(
                update.effective_chat.id,
                "Kechirasiz, kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
                context
            )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        app.job_queue.scheduler.timezone = pytz.timezone("Asia/Tashkent")

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CommandHandler("stats", get_stats))
        app.add_error_handler(error_handler)

        app.job_queue.run_daily(send_status_report, time(hour=9, minute=0, tzinfo=pytz.timezone("Asia/Tashkent")))
        app.job_queue.run_daily(send_status_report, time(hour=21, minute=0, tzinfo=pytz.timezone("Asia/Tashkent")))

        if IS_WEBHOOK:
            port = int(os.getenv("PORT", "8000"))
            full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook"
            logger.info(f"Webhook rejimi ishga tushmoqda -> {full_webhook_url}")
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path="webhook",
                webhook_url=full_webhook_url,
                max_connections=40
            )
        else:
            logger.info("Bot ishga tushdi (polling rejimi)...")
            app.run_polling()
    except Exception as e:
        logger.error(f"Bot ishga tushishda xato: {e}")
        sys.exit(1)
