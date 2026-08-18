import os
import time
import threading
import requests

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)


# =========================================================
# ENVIRONMENT
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"


# =========================================================
# WEB SERVER FOR RENDER
# =========================================================

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(
        host="0.0.0.0",
        port=port
    )


# =========================================================
# USER STATES
# =========================================================

user_states = {}


DEFAULT_SETTINGS = {
    "model": "default",
    "duration": 5,
    "resolution": "480p",
    "audio": False,
}


# =========================================================
# MODEL CONFIGURATION
# Based on Magic Hour Image-to-Video API
# =========================================================

MODELS = {
    "default": {
        "name": "⭐ الافتراضي",
        "durations": [5],
        "resolutions": ["480p", "720p", "1080p"],
        "audio": True,
    },

    "ltx-2": {
        "name": "⚡ LTX-2",
        "durations": [
            1, 2, 3, 4, 5, 6, 7, 8, 9,
            10, 15, 20, 25, 30
        ],
        "resolutions": [
            "480p",
            "720p",
            "1080p"
        ],
        "audio": True,
    },

    "wan-2.2": {
        "name": "🌊 Wan 2.2",
        "durations": [
            3, 4, 5, 6, 7, 8, 9, 10, 15
        ],
        "resolutions": [
            "480p",
            "720p",
            "1080p"
        ],
        "audio": False,
    },

    "seedance": {
        "name": "🚀 Seedance",
        "durations": [
            2, 3, 4, 5, 6, 7,
            8, 9, 10, 11, 12
        ],
        "resolutions": [
            "480p",
            "720p",
            "1080p"
        ],
        "audio": False,
    },

    "seedance-2.0": {
        "name": "🔥 Seedance 2.0",
        "durations": [
            4, 5, 6, 7, 8, 9,
            10, 11, 12, 13, 14, 15
        ],
        "resolutions": [
            "480p",
            "720p"
        ],
        "audio": True,
    },

    "kling-2.5": {
        "name": "🎥 Kling 2.5",
        "durations": [
            5,
            10
        ],
        "resolutions": [
            "720p",
            "1080p"
        ],
        "audio": True,
    },

    "kling-3.0": {
        "name": "🎬 Kling 3.0",
        "durations": [
            3, 4, 5, 6, 7, 8,
            9, 10, 11, 12, 13,
            14, 15
        ],
        "resolutions": [
            "720p",
            "1080p"
        ],
        "audio": True,
    },

    "veo3.1": {
        "name": "💎 Veo 3.1",
        "durations": [
            4, 6, 8, 16, 24,
            32, 40, 48, 56
        ],
        "resolutions": [
            "720p",
            "1080p"
        ],
        "audio": True,
    },

    "veo3.1-lite": {
        "name": "💡 Veo 3.1 Lite",
        "durations": [
            8, 16, 24, 32,
            40, 48, 56
        ],
        "resolutions": [
            "720p",
            "1080p"
        ],
        "audio": True,
    },

    "sora-2": {
        "name": "🌟 Sora 2",
        "durations": [
            4, 8, 12, 24,
            36, 48, 60
        ],
        "resolutions": [
            "720p"
        ],
        "audio": True,
    },
}


# =========================================================
# MAGIC HOUR HEADERS
# =========================================================

def magic_headers():
    return {
        "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}",
        "Content-Type": "application/json",
    }


# =========================================================
# USER STATE
# =========================================================

def get_user_state(user_id):

    if user_id not in user_states:
        user_states[user_id] = {
            **DEFAULT_SETTINGS
        }

    return user_states[user_id]


# =========================================================
# UPLOAD IMAGE
# =========================================================

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

    item = data["items"][0]

    return (
        item["upload_url"],
        item["file_path"]
    )


def upload_image(
    upload_url,
    image_bytes
):

    response = requests.put(
        upload_url,
        data=image_bytes,
        timeout=120,
    )

    response.raise_for_status()


# =========================================================
# CREATE VIDEO
# =========================================================

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

        "style": {
            "prompt": prompt
        },

        "audio": audio,
    }

    print("CREATE VIDEO PAYLOAD:")
    print(payload)

    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",
        headers=magic_headers(),
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# WAIT FOR VIDEO
# =========================================================

def wait_for_video(video_id):

    for attempt in range(90):

        response = requests.get(
            f"{MAGIC_HOUR_BASE}/video-projects/{video_id}",
            headers={
                "Authorization":
                    f"Bearer {MAGIC_HOUR_API_KEY}"
            },
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        status = data.get("status")

        print(
            f"VIDEO STATUS [{attempt + 1}/90]:",
            status
        )

        if status == "complete":

            downloads = data.get(
                "downloads",
                []
            )

            if downloads:

                return (
                    downloads[0]["url"],
                    data
                )

            return None, data

        if status in [
            "error",
            "failed",
            "canceled"
        ]:

            print(
                "VIDEO ERROR:",
                data
            )

            return None, data

        time.sleep(10)

    return None, None


# =========================================================
# MAIN MENU
# =========================================================

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
                "🎯 أوصاف جاهزة",
                callback_data="presets"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 حالتي",
                callback_data="status"
            ),

            InlineKeyboardButton(
                "ℹ️ المساعدة",
                callback_data="help"
            )
        ],

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# SETTINGS MENU
# =========================================================

def settings_menu(state):

    model = state.get(
        "model",
        "default"
    )

    model_name = MODELS.get(
        model,
        {}
    ).get(
        "name",
        model
    )

    duration = state.get(
        "duration",
        5
    )

    resolution = state.get(
        "resolution",
        "480p"
    )

    audio = state.get(
        "audio",
        False
    )

    audio_text = (
        "🔊 الصوت: تشغيل"
        if audio
        else
        "🔇 الصوت: إيقاف"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                f"🤖 {model_name}",
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
                "⬅️ القائمة الرئيسية",
                callback_data="back_main"
            )
        ]

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# MODEL MENU
# =========================================================

def model_menu():

    keyboard = []

    for model_id, info in MODELS.items():

        keyboard.append(
            [
                InlineKeyboardButton(
                    info["name"],
                    callback_data=f"model:{model_id}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# DURATION MENU
# =========================================================

def duration_menu(model):

    model_info = MODELS.get(
        model,
        MODELS["default"]
    )

    durations = model_info[
        "durations"
    ]

    keyboard = []

    row = []

    for duration in durations:

        row.append(
            InlineKeyboardButton(
                f"{duration}ث",
                callback_data=f"duration:{duration}"
            )
        )

        if len(row) == 4:

            keyboard.append(row)

            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# RESOLUTION MENU
# =========================================================

def resolution_menu(model):

    model_info = MODELS.get(
        model,
        MODELS["default"]
    )

    resolutions = model_info[
        "resolutions"
    ]

    keyboard = []

    for resolution in resolutions:

        keyboard.append(
            [
                InlineKeyboardButton(
                    resolution,
                    callback_data=
                    f"resolution:{resolution}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# PRESET PROMPTS
# =========================================================

PRESETS = {

    "portrait": (
        "اجعل الشخص يبتسم بشكل طبيعي، "
        "ويرمش ويحرك رأسه ببطء، "
        "مع حركة تنفس طبيعية وحركة كاميرا "
        "سينمائية خفيفة، مع الحفاظ على ملامح "
        "الوجه والهوية كما هي."
    ),

    "hug": (
        "اجعل الشخصين يقتربان من بعضهما "
        "بشكل طبيعي ثم يتعانقان بعاطفة وهدوء، "
        "مع حركة جسد واقعية وحركة كاميرا "
        "سينمائية ناعمة، مع الحفاظ على "
        "ملامح الوجه كما هي."
    ),

    "family": (
        "اجعل أفراد العائلة يبتسمون ويتفاعلون "
        "مع بعضهم بشكل طبيعي ودافئ، "
        "مع حركة بسيطة وواقعية للوجه والجسم "
        "وحركة كاميرا سينمائية ناعمة."
    ),

    "camera": (
        "حركة كاميرا سينمائية بطيئة إلى الأمام "
        "مع عمق واقعي وإضاءة طبيعية، "
        "واجعل الشخص يتحرك بشكل طبيعي "
        "مع الحفاظ على تفاصيل الصورة."
    ),

    "nature": (
        "أضف حركة طبيعية وهادئة للمشهد، "
        "مثل حركة الهواء والسحب والإضاءة، "
        "مع تأثير سينمائي واقعي وحركة كاميرا "
        "ناعمة."
    ),

}


def presets_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🙂 صورة شخصية",
                callback_data="preset:portrait"
            )
        ],

        [
            InlineKeyboardButton(
                "🤗 عناق",
                callback_data="preset:hug"
            )
        ],

        [
            InlineKeyboardButton(
                "👨‍👩‍👧 عائلة",
                callback_data="preset:family"
            )
        ],

        [
            InlineKeyboardButton(
                "🎥 حركة كاميرا",
                callback_data="preset:camera"
            )
        ],

        [
            InlineKeyboardButton(
                "🌿 طبيعة",
                callback_data="preset:nature"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )
        ]

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_states.pop(
        user_id,
        None
    )

    get_user_state(user_id)

    await update.message.reply_text(

        "مرحباً 👋\n\n"

        "🎬 أهلاً بك في بوت تحويل الصور "
        "إلى فيديو بالذكاء الاصطناعي.\n\n"

        "📷 أرسل صورة للبدء.\n\n"

        "بعد الصورة سأطلب منك وصف الحركة.",

        reply_markup=main_menu()
    )


# =========================================================
# /CANCEL
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_states.pop(
        user_id,
        None
    )

    await update.message.reply_text(

        "❌ تم إلغاء العملية.\n\n"
        "📷 أرسل صورة جديدة للبدء.",

        reply_markup=main_menu()
    )


# =========================================================
# /HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "1️⃣ أرسل صورة.\n"
        "2️⃣ اكتب وصف الحركة.\n"
        "3️⃣ اختر النموذج والدقة والمدة.\n"
        "4️⃣ اضغط إنشاء الفيديو.\n"
        "5️⃣ انتظر حتى يكتمل الفيديو.\n\n"

        "💡 مثال:\n"
        "اجعل الأم وابنتها تقتربان من بعضهما "
        "ثم تتعانقان بشكل طبيعي ودافئ، "
        "مع حركة كاميرا سينمائية خفيفة، "
        "والحفاظ على ملامح الوجه كما هي.",

        reply_markup=main_menu()
    )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = get_user_state(
        user_id
    )

    try:

        photo = update.message.photo[-1]

        telegram_file = (
            await photo.get_file()
        )

        image_bytes = (
            await telegram_file
            .download_as_bytearray()
        )

        state["image"] = bytes(
            image_bytes
        )

        await update.message.reply_text(

            "✅ وصلت الصورة!\n\n"

            "✍️ الآن اكتب وصف الحركة "
            "التي تريدها.\n\n"

            "أو يمكنك استخدام "
            "🎯 الأوصاف الجاهزة من القائمة.\n\n"

            "مثال:\n"
            "اجعل الشخص يبتسم ويحرك رأسه "
            "ببطء مع تقريب سينمائي للكاميرا.\n\n"

            "استخدم /cancel للإلغاء."

        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            error
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


# =========================================================
# TEXT / PROMPT
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = get_user_state(
        user_id
    )

    if "image" not in state:

        await update.message.reply_text(

            "📷 أرسل صورة أولاً.",

            reply_markup=main_menu()
        )

        return

    prompt = (
        update.message.text
        .strip()
    )

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة."
        )

        return

    state["prompt"] = prompt

    keyboard = [

        [
            InlineKeyboardButton(
                "⚙️ الإعدادات",
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

        "📝 تم استلام الوصف:\n\n"

        f"{prompt}\n\n"

        "راجع الإعدادات أو اضغط إنشاء الفيديو.",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = get_user_state(
        user_id
    )

    data = query.data


    # -----------------------------------------------------
    # NEW VIDEO
    # -----------------------------------------------------

    if data == "new_video":

        state.clear()

        state.update(
            DEFAULT_SETTINGS
        )

        await query.edit_message_text(
            "📷 أرسل الصورة التي تريد تحويلها إلى فيديو."
        )

        return


    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    if data == "settings":

        await query.edit_message_text(

            "⚙️ إعدادات الفيديو:\n\n"
            "اختر الإعداد الذي تريد تغييره.",

            reply_markup=settings_menu(
                state
            )
        )

        return


    # -----------------------------------------------------
    # MODELS
    # -----------------------------------------------------

    if data == "models":

        await query.edit_message_text(

            "🤖 اختر نموذج الذكاء الاصطناعي:\n\n"
            "بعض النماذج تحتاج Credits أو خطة مدفوعة.",

            reply_markup=model_menu()
        )

        return


    # -----------------------------------------------------
    # DURATIONS
    # -----------------------------------------------------

    if data == "durations":

        await query.edit_message_text(

            "⏱️ اختر مدة الفيديو:",

            reply_markup=duration_menu(
                state.get(
                    "model",
                    "default"
                )
            )
        )

        return


    # -----------------------------------------------------
    # RESOLUTIONS
    # -----------------------------------------------------

    if data == "resolutions":

        await query.edit_message_text(

            "📺 اختر الدقة:",

            reply_markup=resolution_menu(
                state.get(
                    "model",
                    "default"
                )
            )
        )

        return


    # -----------------------------------------------------
    # AUDIO
    # -----------------------------------------------------

    if data == "audio":

        model = state.get(
            "model",
            "default"
        )

        model_info = MODELS.get(
            model,
            MODELS["default"]
        )

        if not model_info["audio"]:

            await query.answer(
                "❌ الصوت غير مدعوم لهذا النموذج.",
                show_alert=True
            )

            return

        state["audio"] = not state.get(
            "audio",
            False
        )

        await query.edit_message_text(

            "⚙️ تم تغيير إعداد الصوت.",

            reply_markup=settings_menu(
                state
            )
        )

        return


    # -----------------------------------------------------
    # PRESETS
    # -----------------------------------------------------

    if data == "presets":

        await query.edit_message_text(

            "🎯 اختر وصفًا جاهزًا:",

            reply_markup=presets_menu()
        )

        return


    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if data == "status":

        model = state.get(
            "model",
            "default"
        )

        model_name = MODELS.get(
            model,
            {}
        ).get(
            "name",
            model
        )

        await query.edit_message_text(

            "📊 حالتك الحالية:\n\n"

            f"🤖 النموذج: {model_name}\n"
            f"⏱️ المدة: "
            f"{state.get('duration', 5)} ثانية\n"
            f"📺 الدقة: "
            f"{state.get('resolution', '480p')}\n"
            f"🔊 الصوت: "
            f"{'تشغيل' if state.get('audio', False) else 'إيقاف'}\n"
            f"📷 الصورة: "
            f"{'موجودة ✅' if 'image' in state else 'غير موجودة ❌'}\n"
            f"✍️ الوصف: "
            f"{'موجود ✅' if 'prompt' in state else 'غير موجود ❌'}",

            reply_markup=main_menu()
        )

        return


    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if data == "help":

        await query.edit_message_text(

            "ℹ️ أرسل صورة ثم اكتب وصف الحركة.\n\n"
            "بعد ذلك تستطيع اختيار:\n"
            "🤖 النموذج\n"
            "⏱️ المدة\n"
            "📺 الدقة\n"
            "🔊 الصوت\n\n"
            "ثم اضغط إنشاء الفيديو.",

            reply_markup=main_menu()
        )

        return


    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

    if data == "back_main":

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu()
        )

        return


    # -----------------------------------------------------
    # MODEL SELECTION
    # -----------------------------------------------------

    if data.startswith(
        "model:"
    ):

        model = data.split(
            ":",
            1
        )[1]

        if model not in MODELS:

            await query.answer(
                "❌ نموذج غير معروف.",
                show_alert=True
            )

            return

        state["model"] = model

        info = MODELS[
            model
        ]

        # ضبط مدة صالحة
        if state.get(
            "duration"
        ) not in info[
            "durations"
        ]:

            state["duration"] = (
                info["durations"][0]
            )

        # ضبط دقة صالحة
        if state.get(
            "resolution"
        ) not in info[
            "resolutions"
        ]:

            state["resolution"] = (
                info["resolutions"][0]
            )

        # إيقاف الصوت إذا النموذج لا يدعمه
        if not info["audio"]:

            state["audio"] = False

        await query.edit_message_text(

            f"✅ تم اختيار:\n\n"
            f"{info['name']}\n\n"
            "تم ضبط المدة والدقة تلقائيًا "
            "بما يتوافق مع النموذج.",

            reply_markup=settings_menu(
                state
            )
        )

        return


    # -----------------------------------------------------
    # DURATION
    # -----------------------------------------------------

    if data.startswith(
        "duration:"
    ):

        duration = int(
            data.split(
                ":",
                1
            )[1]
        )

        model = state.get(
            "model",
            "default"
        )

        if duration not in MODELS[
            model
        ]["durations"]:

            await query.answer(
                "❌ هذه المدة غير متاحة لهذا النموذج.",
                show_alert=True
            )

            return

        state["duration"] = duration

        await query.edit_message_text(

            f"✅ تم اختيار مدة "
            f"{duration} ثانية.",

            reply_markup=settings_menu(
                state
            )
        )

        return


    # -----------------------------------------------------
    # RESOLUTION
    # -----------------------------------------------------

    if data.startswith(
        "resolution:"
    ):

        resolution = data.split(
            ":",
            1
        )[1]

        model = state.get(
            "model",
            "default"
        )

        if resolution not in MODELS[
            model
        ]["resolutions"]:

            await query.answer(
                "❌ هذه الدقة غير متاحة لهذا النموذج.",
                show_alert=True
            )

            return

        state["resolution"] = resolution

        await query.edit_message_text(

            f"✅ تم اختيار الدقة "
            f"{resolution}.",

            reply_markup=settings_menu(
                state
            )
        )

        return


    # -----------------------------------------------------
    # PRESET
    # -----------------------------------------------------

    if data.startswith(
        "preset:"
    ):

        preset = data.split(
            ":",
            1
        )[1]

        if preset not in PRESETS:

            return

        state["prompt"] = PRESETS[
            preset
        ]

        await query.edit_message_text(

            "🎯 تم اختيار الوصف الجاهز:\n\n"
            f"{state['prompt']}\n\n"
            "اضغط إنشاء الفيديو للمتابعة.",

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🎬 إنشاء الفيديو",
                            callback_data="generate"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ الإعدادات",
                            callback_data="settings"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ رجوع",
                            callback_data="back_main"
                        )
                    ]
                ]
            )
        )

        return


    # -----------------------------------------------------
    # CANCEL GENERATION
    # -----------------------------------------------------

    if data == "cancel_generation":

        user_states.pop(
            user_id,
            None
        )

        await query.edit_message_text(

            "❌ تم إلغاء العملية.",

            reply_markup=main_menu()
        )

        return


    # -----------------------------------------------------
    # GENERATE
    # -----------------------------------------------------

    if data == "generate":

        await generate_video(
            update,
            context
        )

        return


# =========================================================
# GENERATE VIDEO
# =========================================================

async def generate_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user_id = query.from_user.id

    state = get_user_state(
        user_id
    )

    if "image" not in state:

        await query.edit_message_text(
            "❌ أرسل صورة أولاً."
        )

        return

    if "prompt" not in state:

        await query.edit_message_text(
            "❌ اكتب وصف الحركة أولاً."
        )

        return

    await query.answer()

    await query.edit_message_text(

        "⏳ جاري تجهيز الفيديو...\n\n"
        "📤 رفع الصورة...\n"
        "🤖 إرسال الطلب إلى Magic Hour...\n\n"
        "قد يستغرق الفيديو بعض الوقت."
    )

    try:

        model = state.get(
            "model",
            "default"
        )

        duration = state.get(
            "duration",
            5
        )

        resolution = state.get(
            "resolution",
            "480p"
        )

        audio = state.get(
            "audio",
            False
        )

        prompt = state[
            "prompt"
        ]

        # -------------------------------------------------
        # Validate model
        # -------------------------------------------------

        if model not in MODELS:

            raise ValueError(
                "Invalid model"
            )

        model_info = MODELS[
            model
        ]

        # -------------------------------------------------
        # Validate duration
        # -------------------------------------------------

        if duration not in model_info[
            "durations"
        ]:

            duration = model_info[
                "durations"
            ][0]

        # -------------------------------------------------
        # Validate resolution
        # -------------------------------------------------

        if resolution not in model_info[
            "resolutions"
        ]:

            resolution = model_info[
                "resolutions"
            ][0]

        # -------------------------------------------------
        # Validate audio
        # -------------------------------------------------

        if not model_info[
            "audio"
        ]:

            audio = False

        # -------------------------------------------------
        # Upload
        # -------------------------------------------------

        upload_url, file_path = (
            create_upload_url(
                "jpg"
            )
        )

        upload_image(
            upload_url,
            state["image"]
        )

        # -------------------------------------------------
        # Create
        # -------------------------------------------------

        video_data = create_video(

            file_path=file_path,

            prompt=prompt,

            model=model,

            duration=duration,

            resolution=resolution,

            audio=audio
        )

        video_id = video_data[
            "id"
        ]

        credits = video_data.get(
            "credits_charged"
        )

        print(
            "VIDEO ID:",
            video_id
        )

        print(
            "CREDITS:",
            credits
        )

        # -------------------------------------------------
        # Wait
        # -------------------------------------------------

        video_url, final_data = (
            wait_for_video(
                video_id
            )
        )

        if not video_url:

            await query.edit_message_text(

                "❌ لم يتم إنشاء الفيديو.\n\n"

                "الأسباب المحتملة:\n"
                "• لا يوجد Credits كافية\n"
                "• النموذج غير متاح لحسابك\n"
                "• إعداد غير متاح\n"
                "• فشل مؤقت من Magic Hour\n\n"

                "جرّب النموذج الافتراضي و480p."
            )

            return

        # -------------------------------------------------
        # Download
        # -------------------------------------------------

        video_response = requests.get(
            video_url,
            timeout=180
        )

        video_response.raise_for_status()

        # -------------------------------------------------
        # Caption
        # -------------------------------------------------

        caption = (
            "🎬 تم إنشاء الفيديو بنجاح! ✅\n\n"
            f"🤖 النموذج: "
            f"{model_info['name']}\n"
            f"⏱️ المدة: {duration} ثانية\n"
            f"📺 الدقة: {resolution}\n"
            f"🔊 الصوت: "
            f"{'تشغيل' if audio else 'إيقاف'}"
        )

        if credits is not None:

            caption += (
                f"\n💳 Credits: {credits}"
            )

        # -------------------------------------------------
        # Send video
        # -------------------------------------------------

        await context.bot.send_video(

            chat_id=user_id,

            video=video_response.content,

            caption=caption
        )

        await query.edit_message_text(

            "✅ تم إنشاء الفيديو بنجاح وإرساله لك! 🎬\n\n"

            "📷 أرسل صورة جديدة لإنشاء فيديو آخر.",

            reply_markup=main_menu()
        )

        # Clear current job
        user_states.pop(
            user_id,
            None
        )

    # =====================================================
    # HTTP ERROR
    # =====================================================

    except requests.HTTPError as error:

        print(
            "HTTP ERROR:",
            error
        )

        try:

            print(
                "API RESPONSE:",
                error.response.text
            )

        except Exception:

            pass

        await query.edit_message_text(

            "❌ Magic Hour رفض الطلب.\n\n"

            "جرّب التالي:\n"
            "1️⃣ النموذج الافتراضي\n"
            "2️⃣ دقة 480p\n"
            "3️⃣ مدة 5 ثوانٍ\n"
            "4️⃣ إيقاف الصوت\n\n"

            "إذا بقي الخطأ، نراجع سجل Render."
        )

    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as error:

        print(
            "GENERATION ERROR:",
            error
        )

        await query.edit_message_text(

            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "جرّب مرة أخرى باستخدام "
            "الإعدادات الافتراضية."
        )


# =========================================================
# RUN BOT
# =========================================================

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
            filters.TEXT &
            ~filters.COMMAND,
            handle_text
        )
    )

    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    print(
        "🤖 Telegram bot starting..."
    )

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
