import os
import time
import threading
import requests

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)


BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

app_web = Flask(__name__)

# حفظ حالة كل مستخدم
user_states = {}


@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


def magic_headers():
    return {
        "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}",
        "Content-Type": "application/json",
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    await update.message.reply_text(
        "مرحباً 👋\n\n"
        "🎬 أنا بوت تحويل الصور إلى فيديو بالذكاء الاصطناعي.\n\n"
        "📷 أرسل لي صورة للبدء."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    await update.message.reply_text(
        "❌ تم إلغاء العملية.\n\n"
        "📷 أرسل صورة جديدة للبدء."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ طريقة الاستخدام:\n\n"
        "1️⃣ أرسل صورة.\n"
        "2️⃣ اكتب وصف الحركة التي تريدها.\n"
        "3️⃣ انتظر حتى يتم إنشاء الفيديو.\n\n"
        "مثال على وصف جيد:\n"
        "اجعل الشخص يبتسم ويحرك رأسه ببطء، "
        "مع تقريب سينمائي خفيف للكاميرا.\n\n"
        "لإلغاء العملية استخدم /cancel"
    )


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

    return (
        data["items"][0]["upload_url"],
        data["items"][0]["file_path"]
    )


def upload_image(upload_url, image_bytes):
    response = requests.put(
        upload_url,
        data=image_bytes,
        timeout=120,
    )

    response.raise_for_status()


def create_video(file_path, prompt):
    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",
        headers=magic_headers(),
        json={
            "assets": {
                "image_file_path": file_path
            },
            "model": "default",
            "end_seconds": 5,
            "name": "Telegram AI Video",
            "resolution": "480p",
            "audio": False,
            "style": {
                "prompt": prompt
            }
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

        print("VIDEO STATUS:", status)

        if status == "complete":

            downloads = data.get("downloads", [])

            if downloads:
                return downloads[0]["url"]

            return None

        if status in ["error", "failed", "canceled"]:
            print("VIDEO ERROR:", data)
            return None

        time.sleep(10)

    return None


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    # حفظ الصورة للمستخدم
    photo = update.message.photo[-1]

    telegram_file = await photo.get_file()

    image_bytes = await telegram_file.download_as_bytearray()

    user_states[user_id] = {
        "image": bytes(image_bytes)
    }

    await update.message.reply_text(
        "✅ وصلت الصورة!\n\n"
        "✍️ الآن اكتب لي كيف تريد أن تتحرك الصورة.\n\n"
        "مثال:\n"
        "«اجعل الشخص يبتسم ويحرك رأسه ببطء، "
        "مع حركة كاميرا سينمائية خفيفة.»\n\n"
        "أو اكتب /cancel للإلغاء."
    )


async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    if user_id not in user_states:
        await update.message.reply_text(
            "📷 أرسل صورة أولاً، وبعدها سأطلب منك وصف الحركة."
        )
        return

    prompt = update.message.text.strip()

    if not prompt:
        await update.message.reply_text(
            "✍️ اكتب وصفًا للحركة التي تريدها."
        )
        return

    state = user_states[user_id]

    image_bytes = state["image"]

    # حذف الحالة لمنع تنفيذ نفس الطلب مرتين
    user_states.pop(user_id, None)

    status_message = await update.message.reply_text(
        "⏳ جاري تجهيز الفيديو...\n\n"
        "🎬 سأحاول تحريك الصورة حسب وصفك.\n"
        "قد يستغرق الأمر بعض الوقت."
    )

    try:

        # 1 - الحصول على رابط رفع
        upload_url, file_path = create_upload_url("jpg")

        # 2 - رفع الصورة
        upload_image(upload_url, image_bytes)

        # 3 - إنشاء الفيديو
        video_data = create_video(
            file_path,
            prompt
        )

        video_id = video_data["id"]

        print("VIDEO ID:", video_id)

        # 4 - انتظار النتيجة
        video_url = wait_for_video(video_id)

        if not video_url:
            await status_message.edit_text(
                "❌ لم يتم إنشاء الفيديو هذه المرة.\n\n"
                "حاول بصورة أخرى أو بوصف حركة أبسط."
            )
            return

        # 5 - تحميل الفيديو
        video_response = requests.get(
            video_url,
            timeout=180,
        )

        video_response.raise_for_status()

        # 6 - إرسال الفيديو
        await update.message.reply_video(
            video=video_response.content,
            caption="🎬 تم إنشاء الفيديو بنجاح!"
        )

        await status_message.delete()

    except requests.HTTPError as error:

        print("HTTP ERROR:", error)

        try:
            error_text = error.response.text
            print("API RESPONSE:", error_text)
        except Exception:
            pass

        await status_message.edit_text(
            "❌ حدث خطأ من خدمة الفيديو.\n\n"
            "تأكد من توفر Credits في Magic Hour "
            "ثم حاول مرة أخرى."
        )

    except Exception as error:

        print("ERROR:", error)

        await status_message.edit_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "حاول مرة أخرى بصورة أخرى."
        )


def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    bot_app.add_handler(
        CommandHandler("start", start)
    )

    bot_app.add_handler(
        CommandHandler("cancel", cancel)
    )

    bot_app.add_handler(
        CommandHandler("help", help_command)
    )

    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    bot_app.run_polling(
        stop_signals=None
    )


if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
