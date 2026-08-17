import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً 👋\nأرسل لي صورة وسنجهزها لتحويلها إلى فيديو بالذكاء الاصطناعي 🎬"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "وصلت الصورة ✅\nميزة تحويل الصورة إلى فيديو سنضيفها قريباً 🎬"
    )

def run_bot():
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    bot_app.run_polling(stop_signals=None)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
