import os
import time
import threading
import requests

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes


BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً 👋\n"
        "أرسل لي صورة وسأحاول تحويلها إلى فيديو بالذكاء الاصطناعي 🎬"
    )


def magic_headers():
    return {
        "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}",
        "Content-Type": "application/json",
    }


def create_upload_url(extension):
    response = requests.post(
        f"{MAGIC_HOUR_BASE}/files/upload-urls",
        headers=magic_headers(),
        json={
            "items": [
                {
                    "type": "image",
                    "extension": extension
                }
            ]
        },
        timeout=60,
    )

    response.raise_for_status()
    data = response.json()

    return data["items"][0]["upload_url"], data["items"][0]["file_path"]


def upload_image(upload_url, image_bytes):
    response = requests.put(
        upload_url,
        data=image_bytes,
        timeout=120,
    )

    response.raise_for_status()


def create_video(file_path):
    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",
        headers=magic_headers(),
        json={
            "assets": {
                "image_file_path": file_path
            },
            "end_seconds": 5,
            "name": "Telegram Image To Video",
            "resolution": "480p"
        },
        timeout=120,
    )

    response.raise_for_status()
    return response.json()


def wait_for_video(video_id):
    for _ in range(60):
        response = requests.get(
            f"{MAGIC_HOUR_BASE}/video-projects/{video_id}",
            headers={
                "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}"
            },
            timeout=60,
        )

        response.raise_for_status()
        data = response.json()

        status = data.get("status")

        if status == "complete":
            downloads = data.get("downloads", [])

            if downloads:
                return downloads[0]["url"]

            return None

        if status in ["error", "canceled"]:
            return None

        time.sleep(10)

    return None


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text(
        "⏳ وصلت الصورة!\n"
        "جاري تجهيز الفيديو بالذكاء الاصطناعي، انتظر قليلًا... 🎬"
    )

    try:
        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        upload_url, file_path = create_upload_url("jpg")

        upload_image(upload_url, image_bytes)

        video_data = create_video(file_path)

        video_id = video_data["id"]

        video_url = wait_for_video(video_id)

        if not video_url:
            await message.edit_text(
                "❌ للأسف لم يتم إنشاء الفيديو هذه المرة."
            )
            return

        video_response = requests.get(
            video_url,
            timeout=180,
        )

        video_response.raise_for_status()

        await update.message.reply_video(
            video=video_response.content,
            caption="🎬 تم إنشاء الفيديو بنجاح!"
        )

        await message.delete()

    except Exception as error:
        print("ERROR:", error)

        await message.edit_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n"
            "تأكد من أن حساب Magic Hour يحتوي على رصيد كافٍ ثم حاول مرة أخرى."
        )


def run_bot():
    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(
        CommandHandler("start", start)
    )

    bot_app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )

    bot_app.run_polling(stop_signals=None)


if __name__ == "__main__":
    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
