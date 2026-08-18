import os
import time
import threading
import requests

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)


BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

app_web = Flask(__name__)

# حالة المستخدمين
user_states = {}

# الإعدادات الافتراضية
DEFAULT_MODEL = "default"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "480p"
DEFAULT_AUDIO = False


# =========================
# Render Web Server
# =========================

@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)


# =========================
# Magic Hour
# =========================

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


def create_video(
    file_path,
    prompt,
    model,
    duration,
    resolution,
    audio
):
    payload = {
        "assets": {
            "image_file_path": file_path
        },
        "end_seconds": duration,
        "name": "Telegram AI Video",
        "model": model,
        "resolution": resolution,
        "audio": audio,
        "style": {
            "prompt": prompt
        }
    }

    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",
        headers=magic_headers(),
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


def wait_for_video(video_id):
    for _ in range(90):

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
                return downloads[0]["url"], data

            return None, data

        if status in [
            "error",
            "failed",
            "canceled"
        ]:
            print("VIDEO ERROR:", data)
            return None, data

        time.sleep(10)

    return None, None


# =========================
# Menus
# =========================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🎬 إنشاء فيديو",
                callback_data="new_video"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ الإعدادات",
                callback_data="settings"
            ),
            InlineKeyboardButton(
                "ℹ️ المساعدة",
                callback_data="help"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 حالتي",
                callback_data="status"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def settings_menu(state):
    model = state.get("model", DEFAULT_MODEL)
    duration = state.get("duration", DEFAULT_DURATION)
    resolution = state.get(
        "resolution",
        DEFAULT_RESOLUTION
    )
    audio = state.get("audio", DEFAULT_AUDIO)

    audio_text = "🔊 الصوت: تشغيل" if audio else "🔇 الصوت: إيقاف"

    keyboard = [
        [
            InlineKeyboardButton(
                f"🤖 النموذج: {model}",
                callback_data="models"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱️ المدة: {duration}ث",
                callback_data="durations"
            )
        ],
        [
            InlineKeyboardButton(
                f"📺 الدقة: {resolution}",
                callback_data="resolutions"
            )
        ],
        [
            InlineKeyboardButton(
                audio_text,
                callback_data="audio"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def model_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ الافتراضي (مناسب للمجاني)",
                callback_data="model_default"
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ LTX 2.3",
                callback_data="model_ltx"
            )
        ],
        [
            InlineKeyboardButton(
                "🎥 Kling 2.6",
                callback_data="model_kling26"
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 Kling 3.0",
                callback_data="model_kling30"
            )
        ],
        [
            InlineKeyboardButton(
                "🌊 Wan 2.2",
                callback_data="model_wan"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def duration_menu(model):
    if model in [
        "kling-2.6"
    ]:
        durations = [5, 10]

    elif model in [
        "kling-3.0"
    ]:
        durations = [3, 5, 8, 10, 15]

    elif model in [
        "wan-2.2"
    ]:
        durations = [3, 5, 8, 10, 15]

    else:
        durations = [3, 5, 10, 15, 30]

    keyboard = []

    row = []

    for duration in durations:
        row.append(
            InlineKeyboardButton(
                f"{duration} ث",
                callback_data=f"duration_{duration}"
            )
        )

        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="settings"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def resolution_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "480p ⭐",
                callback_data="resolution_480"
            )
        ],
        [
            InlineKeyboardButton(
                "720p",
                callback_data="resolution_720"
            )
        ],
        [
            InlineKeyboardButton(
                "1080p",
                callback_data="resolution_1080"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# Commands
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    await update.message.reply_text(
        "مرحباً 👋\n\n"
        "🎬 أهلاً بك في بوت تحويل الصور إلى فيديو بالذكاء الاصطناعي.\n\n"
        "📷 أرسل صورة للبدء.\n\n"
        "بعد إرسال الصورة سأطلب منك وصف الحركة.",
        reply_markup=main_menu()
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    await update.message.reply_text(
        "❌ تم إلغاء العملية.\n\n"
        "📷 أرسل صورة جديدة للبدء.",
        reply_markup=main_menu()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ℹ️ طريقة الاستخدام:\n\n"
        "1️⃣ أرسل صورة.\n"
        "2️⃣ اكتب وصف الحركة.\n"
        "3️⃣ اختر الإعدادات إذا أردت.\n"
        "4️⃣ انتظر إنشاء الفيديو.\n\n"
        "مثال:\n"
        "اجعل الأم وابنتها تقتربان من بعضهما "
        "ثم تتعانقان بشكل طبيعي ودافئ، "
        "مع حركة كاميرا سينمائية خفيفة "
        "والحفاظ على ملامح الوجه.",
        reply_markup=main_menu()
    )


# =========================
# Buttons
# =========================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = user_states.setdefault(
        user_id,
        {
            "model": DEFAULT_MODEL,
            "duration": DEFAULT_DURATION,
            "resolution": DEFAULT_RESOLUTION,
            "audio": DEFAULT_AUDIO,
        }
    )

    data = query.data

    if data == "new_video":

        await query.edit_message_text(
            "📷 أرسل الصورة التي تريد تحويلها إلى فيديو."
        )

        state["waiting_for_photo"] = True
        return

    if data == "settings":

        await query.edit_message_text(
            "⚙️ إعدادات الفيديو:\n\n"
            "اختر الإعداد الذي تريد تغييره.",
            reply_markup=settings_menu(state)
        )

        return

    if data == "models":

        await query.edit_message_text(
            "🤖 اختر النموذج:",
            reply_markup=model_menu()
        )

        return

    if data == "durations":

        await query.edit_message_text(
            "⏱️ اختر مدة الفيديو:",
            reply_markup=duration_menu(
                state.get(
                    "model",
                    DEFAULT_MODEL
                )
            )
        )

        return

    if data == "resolutions":

        await query.edit_message_text(
            "📺 اختر الدقة:",
            reply_markup=resolution_menu()
        )

        return

    if data == "audio":

        state["audio"] = not state.get(
            "audio",
            DEFAULT_AUDIO
        )

        await query.edit_message_text(
            "⚙️ تم تغيير إعداد الصوت.\n\n"
            + (
                "🔊 الصوت: تشغيل"
                if state["audio"]
                else
                "🔇 الصوت: إيقاف"
            ),
            reply_markup=settings_menu(state)
        )

        return

    if data == "help":

        await query.edit_message_text(
            "ℹ️ أرسل صورة ثم اكتب وصف الحركة.\n\n"
            "يمكنك بعد ذلك اختيار النموذج "
            "والمدة والدقة والصوت من الإعدادات.",
            reply_markup=main_menu()
        )

        return

    if data == "status":

        await query.edit_message_text(
            "📊 إعداداتك الحالية:\n\n"
            f"🤖 النموذج: {state.get('model', DEFAULT_MODEL)}\n"
            f"⏱️ المدة: {state.get('duration', DEFAULT_DURATION)} ثانية\n"
            f"📺 الدقة: {state.get('resolution', DEFAULT_RESOLUTION)}\n"
            f"🔊 الصوت: {'تشغيل' if state.get('audio', False) else 'إيقاف'}",
            reply_markup=main_menu()
        )

        return

    if data == "back_main":

        await query.edit_message_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_menu()
        )

        return

    # Models

    if data == "model_default":

        state["model"] = "default"
        state["audio"] = False

        await query.edit_message_text(
            "✅ تم اختيار النموذج الافتراضي.\n\n"
            "هذا الخيار مناسب كبداية للحساب المجاني.",
            reply_markup=settings_menu(state)
        )

        return

    if data == "model_ltx":

        state["model"] = "ltx-2.3"

        await query.edit_message_text(
            "⚡ تم اختيار LTX 2.3.",
            reply_markup=settings_menu(state)
        )

        return

    if data == "model_kling26":

        state["model"] = "kling-2.6"
        state["audio"] = False

        await query.edit_message_text(
            "🎥 تم اختيار Kling 2.6.\n\n"
            "قد يتطلب هذا الخيار خطة أو Credits.",
            reply_markup=settings_menu(state)
        )

        return

    if data == "model_kling30":

        state["model"] = "kling-3.0"

        await query.edit_message_text(
            "🎬 تم اختيار Kling 3.0.\n\n"
            "قد يتطلب هذا الخيار خطة أو Credits.",
            reply_markup=settings_menu(state)
        )

        return

    if data == "model_wan":

        state["model"] = "wan-2.2"

        await query.edit_message_text(
            "🌊 تم اختيار Wan 2.2.\n\n"
            "قد يتطلب هذا الخيار خطة أو Credits.",
            reply_markup=settings_menu(state)
        )

        return

    # Durations

    if data.startswith("duration_"):

        duration = int(
            data.replace(
                "duration_",
                ""
            )
        )

        state["duration"] = duration

        await query.edit_message_text(
            f"✅ تم اختيار مدة {duration} ثانية.",
            reply_markup=settings_menu(state)
        )

        return

    # Resolutions

    if data == "resolution_480":

        state["resolution"] = "480p"

    elif data == "resolution_720":

        state["resolution"] = "720p"

    elif data == "resolution_1080":

        state["resolution"] = "1080p"

    else:
        return

    await query.edit_message_text(
        f"✅ تم اختيار الدقة {state['resolution']}.",
        reply_markup=settings_menu(state)
    )


# =========================
# Photo
# =========================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = user_states.setdefault(
        user_id,
        {
            "model": DEFAULT_MODEL,
            "duration": DEFAULT_DURATION,
            "resolution": DEFAULT_RESOLUTION,
            "audio": DEFAULT_AUDIO,
        }
    )

    try:

        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        state["image"] = bytes(image_bytes)
        state["waiting_for_prompt"] = True

        await update.message.reply_text(
            "✅ وصلت الصورة!\n\n"
            "✍️ الآن اكتب لي وصف الحركة التي تريدها.\n\n"
            "مثال:\n"
            "اجعل الشخص يبتسم ويحرك رأسه ببطء، "
            "مع حركة كاميرا سينمائية خفيفة، "
            "وحافظ على ملامح الوجه كما هي.\n\n"
            "يمكنك استخدام /cancel للإلغاء."
        )

    except Exception as error:

        print("PHOTO ERROR:", error)

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


# =========================
# Text / Prompt
# =========================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if user_id not in user_states:

        await update.message.reply_text(
            "📷 أرسل صورة أولاً.",
            reply_markup=main_menu()
        )

        return

    state = user_states[user_id]

    if "image" not in state:

        await update.message.reply_text(
            "📷 أرسل صورة أولاً."
        )

        return

    prompt = update.message.text.strip()

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة."
        )

        return

    state["prompt"] = prompt

    keyboard = [
        [
            InlineKeyboardButton(
                "⚙️ الإعدادات الحالية",
                callback_data="settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 إنشاء الفيديو الآن",
                callback_data="generate"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_generation"
            )
        ]
    ]

    await update.message.reply_text(
        "📝 تم استلام وصف الحركة:\n\n"
        f"{prompt}\n\n"
        "يمكنك تعديل الإعدادات أو بدء إنشاء الفيديو.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# Generate Button
# =========================

async def generate_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    if user_id not in user_states:

        await query.edit_message_text(
            "❌ لا توجد عملية حالية.\n\n"
            "📷 أرسل صورة للبدء."
        )

        return

    state = user_states[user_id]

    if "image" not in state or "prompt" not in state:

        await query.edit_message_text(
            "❌ يجب إرسال صورة وكتابة وصف الحركة أولاً."
        )

        return

    await query.edit_message_text(
        "⏳ جاري إنشاء الفيديو...\n\n"
        "🎬 تم إرسال طلبك إلى Magic Hour.\n"
        "قد يستغرق إنشاء الفيديو بعض الوقت."
    )

    try:

        image_bytes = state["image"]

        prompt = state["prompt"]

        model = state.get(
            "model",
            DEFAULT_MODEL
        )

        duration = state.get(
            "duration",
            DEFAULT_DURATION
        )

        resolution = state.get(
            "resolution",
            DEFAULT_RESOLUTION
        )

        audio = state.get(
            "audio",
            DEFAULT_AUDIO
        )

        # رفع الصورة
        upload_url, file_path = create_upload_url(
            "jpg"
        )

        upload_image(
            upload_url,
            image_bytes
        )

        # إنشاء الفيديو
        video_data = create_video(
            file_path=file_path,
            prompt=prompt,
            model=model,
            duration=duration,
            resolution=resolution,
            audio=audio
        )

        video_id = video_data["id"]

        credits = video_data.get(
            "credits_charged"
        )

        print("VIDEO ID:", video_id)
        print("CREDITS:", credits)

        # الانتظار
        video_url, final_data = wait_for_video(
            video_id
        )

        if not video_url:

            await query.edit_message_text(
                "❌ لم يتم إنشاء الفيديو.\n\n"
                "قد يكون السبب عدم توفر Credits "
                "أو أن الإعداد المختار غير متاح "
                "في حساب Magic Hour."
            )

            user_states.pop(
                user_id,
                None
            )

            return

        # تحميل الفيديو
        video_response = requests.get(
            video_url,
            timeout=180
        )

        video_response.raise_for_status()

        # إرسال الفيديو
        caption = "🎬 تم إنشاء الفيديو بنجاح!"

        if credits is not None:

            caption += (
                f"\n💳 Credits المستخدمة: {credits}"
            )

        await context.bot.send_video(
            chat_id=user_id,
            video=video_response.content,
            caption=caption
        )

        await query.edit_message_text(
            "✅ تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"
            "يمكنك إرسال صورة جديدة للبدء من جديد.",
            reply_markup=main_menu()
        )

        user_states.pop(
            user_id,
            None
        )

    except requests.HTTPError as error:

        print("HTTP ERROR:", error)

        try:
            print(
                "API RESPONSE:",
                error.response.text
            )
        except Exception:
            pass

        await query.edit_message_text(
            "❌ Magic Hour رفض الطلب.\n\n"
            "إذا اخترت نموذجًا أو دقة "
            "غير متاحة لحسابك، ارجع للإعدادات "
            "واختر الافتراضي 480p."
        )

    except Exception as error:

        print("GENERATION ERROR:", error)

        await query.edit_message_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "حاول مرة أخرى أو استخدم "
            "الإعدادات الافتراضية."
        )


# =========================
# Extra Button Handler
# =========================

async def extra_buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if query.data == "generate":

        await generate_video(
            update,
            context
        )

        return

    if query.data == "cancel_generation":

        user_id = query.from_user.id

        user_states.pop(
            user_id,
            None
        )

        await query.answer()

        await query.edit_message_text(
            "❌ تم إلغاء العملية.",
            reply_markup=main_menu()
        )

        return


# =========================
# Bot
# =========================

def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    bot_app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
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

    bot_app.add_handler(
        CallbackQueryHandler(
            extra_buttons,
            pattern="^(generate|cancel_generation)$"
        )
    )

    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    bot_app.run_polling(
        stop_signals=None
    )


# =========================
# Start
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
