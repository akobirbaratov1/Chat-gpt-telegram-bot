import logging
import os
import sys
from typing import Dict, List
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv
from functools import lru_cache
import pytz
from datetime import time

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not found in .env file!")
    raise ValueError("OPENAI_API_KEY not found in .env file!")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN not found in .env file!")
    raise ValueError("TELEGRAM_TOKEN not found in .env file!")
if not ADMIN_CHAT_ID:
    logger.error("ADMIN_CHAT_ID not found in .env file!")
    raise ValueError("ADMIN_CHAT_ID not found in .env file!")

masked_token = TELEGRAM_TOKEN[:8] + "..." + TELEGRAM_TOKEN[-4:] if TELEGRAM_TOKEN else "None"
logger.info(f"TELEGRAM_TOKEN loaded: {masked_token}")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.error(f"Error setting up OpenAI client: {str(e)}")
    raise

chat_histories: Dict[int, List[Dict[str, str]]] = {}
user_profiles: Dict[int, Dict[str, str]] = {}
stats = {"requests": 0, "errors": 0}
MAX_HISTORY_LENGTH = 10  

reply_keyboard = [[KeyboardButton("Start new chat")]]
markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Function to start the bot."""
    try:
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name or "User"
        chat_histories[chat_id] = [{"role": "system", "content": f"You are a friendly AI assistant. Please respond to the user {user_name} in English."}]
        user_profiles[chat_id] = {"name": user_name, "requests": 0}
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Hello, {user_name}! I am ready to help you. What shall we talk about? 😊",
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"New session started for chat {chat_id}. User: {user_name}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error in start function: {str(e)}")
        await context.bot.send_message(chat_id=chat_id, text="Sorry, an error occurred. Please try again! 😔", parse_mode='Markdown')

@lru_cache(maxsize=200)
def get_openai_response(chat_id: int, message: str) -> str:
    """Function to get a response from OpenAI."""
    try:
        chat_histories[chat_id].append({"role": "user", "content": message})
        if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
            system_message = chat_histories[chat_id][0]
            chat_histories[chat_id] = [system_message] + chat_histories[chat_id][-MAX_HISTORY_LENGTH+1:]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=chat_histories[chat_id],
            max_tokens=700,
            temperature=0.7
        )
        ai_response = response.choices[0].message.content
        chat_histories[chat_id].append({"role": "assistant", "content": ai_response})
        return ai_response
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error getting response from OpenAI: {str(e)}")
        if "rate limit" in str(e).lower():
            return "The request limit has been exceeded, please wait a bit and try again! 😅"
        return f"Sorry, an error occurred: {str(e)}. Please try again!"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Function to process text messages."""
    try:
        chat_id = update.effective_chat.id
        user_message = update.message.text
        stats["requests"] += 1

        if user_message == "Start new chat":
            await new_chat(update, context)
            return

        if chat_id not in chat_histories:
            user_name = update.effective_user.first_name or "User"
            chat_histories[chat_id] = [{"role": "system", "content": f"You are a friendly AI assistant. Please respond to the user {user_name} in English."}]
            user_profiles[chat_id] = {"name": user_name, "requests": 0}

        user_profiles[chat_id]["requests"] += 1

        loading_message = await context.bot.send_message(
            chat_id=chat_id,
            text="Preparing response... ⏳",
            parse_mode='Markdown'
        )

        ai_response = get_openai_response(chat_id, user_message)

        await context.bot.delete_message(chat_id=chat_id, message_id=loading_message.message_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text=ai_response,
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"Text request for chat {chat_id}: {user_message}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error processing text message: {str(e)}")
        await context.bot.send_message(chat_id=chat_id, text="An error occurred while processing the message. Please try again! 😔", parse_mode='Markdown')

async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Function to start a new chat."""
    try:
        chat_id = update.effective_chat.id
        user_name = user_profiles.get(chat_id, {}).get("name", "User")
        chat_histories[chat_id] = [{"role": "system", "content": f"You are a friendly AI assistant. Please respond to the user {user_name} in English."}]
        await context.bot.send_message(
            chat_id=chat_id,
            text="New chat started! I'm waiting for your new questions. 😊",
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"New chat started for chat {chat_id}.")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error starting new chat: {str(e)}")
        await context.bot.send_message(chat_id=chat_id, text="An error occurred while starting a new chat. Please try again! 😔", parse_mode='Markdown')

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Function to show statistics."""
    try:
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Statistics:\n- Requests: {stats['requests']}\n- Errors: {stats['errors']}",
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"Statistics requested for chat {chat_id}.")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error showing statistics: {str(e)}")
        await context.bot.send_message(chat_id=chat_id, text="An error occurred while showing statistics. Please try again! 😔", parse_mode='Markdown')

async def send_status_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send status report about the bot to the admin."""
    admin_chat_id = ADMIN_CHAT_ID
    status_message = (
        f"Bot Status:\n"
        f"- Running: {app.running}\n"
        f"- Requests: {stats['requests']}\n"
        f"- Errors: {stats['errors']}\n"
        f"- Log file size: {os.path.getsize('bot.log') / (1024 * 1024):.2f} MB"
    )
    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=status_message, parse_mode='Markdown')
        logger.info("Status report sent to admin.")
    except Exception as e:
        logger.error(f"Error sending message to admin: {str(e)}")

def clean_log_file():
    """If log file size exceeds 10 MB, clear the older parts."""
    log_file = "bot.log"
    max_size_mb = 10
    try:
        if os.path.exists(log_file):
            size_mb = os.path.getsize(log_file) / (1024 * 1024) 
            if size_mb > max_size_mb:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                new_lines = lines[len(lines) // 2:]
                with open(log_file, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                logger.info(f"Log file cleaned. New size: {os.path.getsize(log_file) / (1024 * 1024):.2f} MB")
    except Exception as e:
        logger.error(f"Error cleaning log file: {str(e)}")

async def check_log_size(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check log file size daily."""
    clean_log_file()

if __name__ == "__main__":
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        app.job_queue.scheduler.timezone = pytz.timezone("Asia/Tashkent")

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CommandHandler("stats", get_stats))

        app.job_queue.run_daily(send_status_report, time(hour=9, minute=0, tzinfo=pytz.timezone("Asia/Tashkent")))
        app.job_queue.run_daily(send_status_report, time(hour=21, minute=0, tzinfo=pytz.timezone("Asia/Tashkent")))
        app.job_queue.run_daily(check_log_size, time(hour=0, minute=0, tzinfo=pytz.timezone("Asia/Tashkent")))

        logger.info("Bot started...")
        app.run_polling()
    except Exception as e:
        logger.error(f"Error starting the bot: {str(e)}")
        sys.exit(1)