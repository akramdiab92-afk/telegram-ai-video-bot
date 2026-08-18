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


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"


# ============================================================
# WEB SERVER FOR RENDER
# ============================================================

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "Telegram AI Video Bot is running! 🎬"


@app_web.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
    )


# ============================================================
# USER STATES
# ============================================================

user_states = {}


DEFAULT_SETTINGS = {
    "model": "default",
    "duration": 5,
    "resolution": "480p",
    "audio": False,
}


# ============================================================
# MODEL INFORMATION
# ============================================================

MODEL_NAMES = {
    "default": "⭐ تلقائي",
    "ltx-2.3": "⚡ LTX 2.3",
    "kling-2.6": "🎥 Kling 2.6",
    "kling-3.0": "🎬 Kling 3.0",
    "wan-2.2": "🌊 Wan 2.2",
    "seedance-1.5": "✨ Seedance 1.5",
    "seedance-2.0": "🚀 Seedance 2.0",
    "seedance-2.0-mini": "⚡ Seedance Mini",
    "seedance-2.5": "💎 Seedance 2.5",
    "minimax-h3": "🎙️ MiniMax H3",
    "veo3.1": "🌟 Veo 3.1",
    "veo3.1-lite": "🌟 Veo 3.1 Lite",
    "sora-2": "🧠 Sora 2",
}


MODEL_DURATIONS = {
    "default": [5],
    "ltx-2.3": [
        1, 2, 3, 4, 5, 6, 7, 8,
        9, 10, 15, 20, 25, 30
    ],
    "kling-2.6": [5, 10],
    "kling-3.0": [
        3, 4, 5, 6, 7, 8,
        9, 10, 11, 12, 13, 14, 15
    ],
    "wan-2.2": [
        3, 4, 5, 6, 7, 8,
        9, 10, 15
    ],
    "seedance-1.5": [
        4, 5, 6, 7, 8,
        9, 10, 11, 12
    ],
    "seedance-2.0": [
        4, 5, 6, 7, 8,
        9, 10, 11, 12,
        13, 14, 15
    ],
    "seedance-2.0-mini": [
        4, 5, 6, 7, 8,
        9, 10, 11, 12,
        13, 14, 15
    ],
    "seedance-2.5": list(range(4, 31)),
    "minimax-h3": [
        1, 2, 3, 4, 5,
        6, 7, 8, 9, 10,
        15, 20, 25, 30
    ],
    "veo3.1": [
        4, 6, 8, 16,
        24, 32, 40, 48, 56
    ],
    "veo3.1-lite": [
        4, 6, 8, 16,
        24, 32, 40, 48, 56
    ],
    "sora-2": [
        4, 8, 12, 24,
        36, 48, 60
    ],
}


MODEL_RESOLUTIONS = {
    "default": ["480p", "720p"],
    "ltx-2.3": ["480p", "720p", "1080p"],
    "kling-2.6": ["720p", "1080p"],
    "kling-3.0": ["720p", "1080p"],
    "wan-2.2": ["480p", "720p", "1080p"],
    "seedance-1.5": ["480p", "720p", "1080p"],
    "seedance-2.0": ["480p", "720p"],
    "seedance-2.0-mini": ["480p", "720p"],
    "seedance-2.5": ["480p", "720p"],
    "minimax-h3": ["480p", "720p", "1080p"],
    "veo3.1": ["720p", "1080p"],
    "veo3.1-lite": ["720p", "1080p"],
    "sora-2": ["720p"],
}


AUDIO_SUPPORTED = {
    "default": False,
    "ltx-2.3": True,
    "kling-2.6": False,
    "kling-3.0": True,
    "wan-2.2": False,
    "seedance-1.5": True,
    "seedance-2.0": True,
    "seedance-2.0-mini": True,
    "seedance-2.5": True,
    "minimax-h3": True,
    "veo3.1": True,
    "veo3.1-lite": True,
    "sora-2": True,
}


# ============================================================
# MAGIC HOUR API
# ============================================================

def magic_headers():
    return {
        "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}",
        "Content-Type": "application/json",
    }


def create_upload_url(extension="jpg"):
    response = requests.post(
        f"{MAGIC_HOUR_BASE}/files/upload-urls",
        headers=magic_headers(),
        json={
            "items": [
                {
                    "type": "image",
                    "extension": extension,
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
        item["file_path"],
    )


def upload_image(upload_url, image_bytes):
    response = requests.put(
        upload_url,
        data=image_bytes,
        timeout=180,
    )

    response.raise_for_status()


def create_video(
    image_path,
    prompt,
    model,
    duration,
    resolution,
    audio=False,
    end_image_path=None,
):
    payload = {
        "assets": {
            "image_file_path": image_path,
        },
        "end_seconds": float(duration),
        "name": "Telegram AI Video",
        "model": model,
        "resolution": resolution,
        "audio": audio,
        "style": {
            "prompt": prompt,
        },
    }

    # صورة ثانية لنهاية الفيديو
    if end_image_path:
        payload["assets"]["end_image_file_path"] = end_image_path

    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",
        headers=magic_headers(),
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


def get_video_status(video_id):
    response = requests.get(
        f"{MAGIC_HOUR_BASE}/video-projects/{video_id}",
        headers={
            "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}",
        },
        timeout=60,
    )

    response.raise_for_status()

    return response.json()


def wait_for_video(video_id, max_wait=900):
    started = time.time()

    while time.time() - started < max_wait:

        data = get_video_status(video_id)

        status = data.get("status")

        print("VIDEO STATUS:", status)

        if status == "complete":

            downloads = data.get("downloads") or []

            if downloads:
                return downloads[0].get("url"), data

            return None, data

        if status in ["error", "canceled"]:

            print("VIDEO ERROR:", data)

            return None, data

        time.sleep(10)

    return None, None


# ============================================================
# STATE
# ============================================================

def get_state(user_id):
    if user_id not in user_states:

        user_states[user_id] = {
            **DEFAULT_SETTINGS,
            "images": [],
            "prompt": None,
            "generating": False,
        }

    return user_states[user_id]


def reset_process(user_id):
    state = get_state(user_id)

    state["images"] = []
    state["prompt"] = None
    state["generating"] = False


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "🎬 إنشاء فيديو",
                callback_data="new_video",
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ الإعدادات",
                callback_data="settings",
            ),
            InlineKeyboardButton(
                "📊 حالتي",
                callback_data="status",
            ),
        ],
        [
            InlineKeyboardButton(
                "ℹ️ المساعدة",
                callback_data="help",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SETTINGS MENU
# ============================================================

def settings_menu(state):

    model = state["model"]
    duration = state["duration"]
    resolution = state["resolution"]
    audio = state["audio"]

    model_name = MODEL_NAMES.get(
        model,
        model,
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
                callback_data="models",
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱️ المدة: {duration}ث",
                callback_data="durations",
            )
        ],
        [
            InlineKeyboardButton(
                f"📺 الدقة: {resolution}",
                callback_data="resolutions",
            )
        ],
        [
            InlineKeyboardButton(
                audio_text,
                callback_data="audio",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ القائمة الرئيسية",
                callback_data="back_main",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# MODEL MENU
# ============================================================

def model_menu():

    buttons = []

    models = [
        "default",
        "ltx-2.3",
        "kling-2.6",
        "kling-3.0",
        "wan-2.2",
        "seedance-1.5",
        "seedance-2.0",
        "seedance-2.0-mini",
        "seedance-2.5",
        "minimax-h3",
        "veo3.1-lite",
        "veo3.1",
        "sora-2",
    ]

    for model in models:

        buttons.append([
            InlineKeyboardButton(
                MODEL_NAMES[model],
                callback_data=f"model:{model}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="settings",
        )
    ])

    return InlineKeyboardMarkup(buttons)


# ============================================================
# DURATION MENU
# ============================================================

def duration_menu(model):

    durations = MODEL_DURATIONS.get(
        model,
        [5],
    )

    keyboard = []

    row = []

    for duration in durations:

        row.append(
            InlineKeyboardButton(
                f"{duration} ث",
                callback_data=f"duration:{duration}",
            )
        )

        if len(row) == 4:

            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="settings",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# RESOLUTION MENU
# ============================================================

def resolution_menu(model):

    resolutions = MODEL_RESOLUTIONS.get(
        model,
        ["480p"],
    )

    keyboard = []

    for resolution in resolutions:

        keyboard.append([
            InlineKeyboardButton(
                resolution,
                callback_data=f"resolution:{resolution}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="settings",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = get_state(user_id)

    reset_process(user_id)

    await update.message.reply_text(
        "مرحباً 👋\n\n"
        "🎬 أهلاً بك في بوت تحويل الصور إلى فيديو بالذكاء الاصطناعي.\n\n"
        "📷 أرسل صورة للبدء.\n\n"
        "يمكنك أيضًا استخدام القائمة لاختيار "
        "النموذج والمدة والدقة والصوت.",
        reply_markup=main_menu(),
    )


# ============================================================
# CANCEL COMMAND
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    reset_process(user_id)

    await update.message.reply_text(
        "❌ تم إلغاء العملية.\n\n"
        "📷 أرسل صورة جديدة للبدء.",
        reply_markup=main_menu(),
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "ℹ️ طريقة الاستخدام:\n\n"
        "1️⃣ اضغط إنشاء فيديو.\n"
        "2️⃣ أرسل صورة.\n"
        "3️⃣ يمكنك إرسال صورة ثانية إذا أردت انتقالًا "
        "بين صورتين.\n"
        "4️⃣ اكتب وصف الحركة.\n"
        "5️⃣ اختر الإعدادات التي تريدها.\n"
        "6️⃣ اضغط إنشاء الفيديو.\n\n"
        "مثال:\n"
        "اجعل الأم والابنة تقتربان من بعضهما "
        "ثم تتعانقان بشكل طبيعي ودافئ، "
        "مع حركة كاميرا سينمائية خفيفة، "
        "مع الحفاظ على ملامح الوجه كما هي.\n\n"
        "/cancel لإلغاء العملية.",
        reply_markup=main_menu(),
    )


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = get_state(user_id)

    data = query.data

    # --------------------------------------------------------
    # NEW VIDEO
    # --------------------------------------------------------

    if data == "new_video":

        reset_process(user_id)

        await query.edit_message_text(
            "📷 أرسل الصورة الأولى الآن.\n\n"
            "ويمكنك إرسال صورة ثانية بعدها "
            "إذا أردت انتقالًا بين صورتين.\n\n"
            "بعد الانتهاء اكتب وصف الحركة."
        )

        return

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    if data == "settings":

        await query.edit_message_text(
            "⚙️ إعدادات الفيديو:\n\n"
            "اختر الإعداد الذي تريد تغييره.",
            reply_markup=settings_menu(state),
        )

        return

    # --------------------------------------------------------
    # MODELS
    # --------------------------------------------------------

    if data == "models":

        await query.edit_message_text(
            "🤖 اختر نموذج الذكاء الاصطناعي:",
            reply_markup=model_menu(),
        )

        return

    # --------------------------------------------------------
    # MODEL SELECT
    # --------------------------------------------------------

    if data.startswith("model:"):

        model = data.split(":", 1)[1]

        if model not in MODEL_NAMES:

            await query.edit_message_text(
                "❌ النموذج غير معروف.",
                reply_markup=settings_menu(state),
            )

            return

        state["model"] = model

        valid_durations = MODEL_DURATIONS.get(
            model,
            [5],
        )

        if state["duration"] not in valid_durations:

            state["duration"] = valid_durations[0]

        valid_resolutions = MODEL_RESOLUTIONS.get(
            model,
            ["480p"],
        )

        if state["resolution"] not in valid_resolutions:

            state["resolution"] = valid_resolutions[0]

        if not AUDIO_SUPPORTED.get(
            model,
            False,
        ):

            state["audio"] = False

        await query.edit_message_text(
            f"✅ تم اختيار:\n"
            f"{MODEL_NAMES[model]}",
            reply_markup=settings_menu(state),
        )

        return

    # --------------------------------------------------------
    # DURATIONS
    # --------------------------------------------------------

    if data == "durations":

        await query.edit_message_text(
            "⏱️ اختر مدة الفيديو:",
            reply_markup=duration_menu(
                state["model"]
            ),
        )

        return

    if data.startswith("duration:"):

        duration = int(
            data.split(":", 1)[1]
        )

        valid = MODEL_DURATIONS.get(
            state["model"],
            [5],
        )

        if duration not in valid:

            await query.edit_message_text(
                "❌ هذه المدة غير متاحة لهذا النموذج.",
                reply_markup=settings_menu(state),
            )

            return

        state["duration"] = duration

        await query.edit_message_text(
            f"✅ تم اختيار مدة {duration} ثانية.",
            reply_markup=settings_menu(state),
        )

        return

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    if data == "resolutions":

        await query.edit_message_text(
            "📺 اختر الدقة:",
            reply_markup=resolution_menu(
                state["model"]
            ),
        )

        return

    if data.startswith("resolution:"):

        resolution = data.split(":", 1)[1]

        valid = MODEL_RESOLUTIONS.get(
            state["model"],
            ["480p"],
        )

        if resolution not in valid:

            await query.edit_message_text(
                "❌ هذه الدقة غير متاحة لهذا النموذج.",
                reply_markup=settings_menu(state),
            )

            return

        state["resolution"] = resolution

        await query.edit_message_text(
            f"✅ تم اختيار الدقة {resolution}.",
            reply_markup=settings_menu(state),
        )

        return

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    if data == "audio":

        model = state["model"]

        if not AUDIO_SUPPORTED.get(
            model,
            False,
        ):

            await query.edit_message_text(
                "🔇 الصوت غير مدعوم مع النموذج الحالي.\n\n"
                "اختر LTX 2.3 أو Kling 3.0 أو نموذجًا "
                "آخر يدعم الصوت.",
                reply_markup=settings_menu(state),
            )

            return

        state["audio"] = not state["audio"]

        text = (
            "🔊 تم تشغيل الصوت."
            if state["audio"]
            else
            "🔇 تم إيقاف الصوت."
        )

        await query.edit_message_text(
            text,
            reply_markup=settings_menu(state),
        )

        return

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if data == "status":

        model = MODEL_NAMES.get(
            state["model"],
            state["model"],
        )

        image_count = len(
            state.get("images", [])
        )

        await query.edit_message_text(
            "📊 حالتك الحالية:\n\n"
            f"🤖 النموذج: {model}\n"
            f"⏱️ المدة: {state['duration']} ثانية\n"
            f"📺 الدقة: {state['resolution']}\n"
            f"🔊 الصوت: "
            f"{'تشغيل' if state['audio'] else 'إيقاف'}\n"
            f"🖼️ الصور: {image_count}",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if data == "help":

        await query.edit_message_text(
            "ℹ️ أرسل صورة، ثم اكتب وصف الحركة.\n\n"
            "يمكنك إرسال صورة ثانية قبل كتابة الوصف.\n\n"
            "بعدها اختر الإعدادات واضغط إنشاء الفيديو.",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # BACK
    # --------------------------------------------------------

    if data == "back_main":

        await query.edit_message_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # CANCEL GENERATION
    # --------------------------------------------------------

    if data == "cancel_generation":

        reset_process(user_id)

        await query.edit_message_text(
            "❌ تم إلغاء العملية.",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # GENERATE
    # --------------------------------------------------------

    if data == "generate":

        await generate_video(
            update,
            context,
        )

        return


# ============================================================
# PHOTO HANDLER
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = get_state(user_id)

    if state.get("generating"):

        await update.message.reply_text(
            "⏳ يوجد فيديو قيد الإنشاء حاليًا.\n"
            "انتظر حتى ينتهي."
        )

        return

    try:

        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        image_bytes = bytes(image_bytes)

        images = state.setdefault(
            "images",
            [],
        )

        if len(images) >= 2:

            await update.message.reply_text(
                "ℹ️ يمكنك استخدام صورتين كحد أقصى.\n\n"
                "اكتب الآن وصف الحركة."
            )

            return

        images.append(image_bytes)

        if len(images) == 1:

            await update.message.reply_text(
                "✅ وصلت الصورة الأولى! 📷\n\n"
                "إذا أردت استخدام صورتين، "
                "أرسل الصورة الثانية الآن.\n\n"
                "وإذا كانت صورة واحدة كافية، "
                "اكتب وصف الحركة مباشرة."
            )

        else:

            await update.message.reply_text(
                "✅ وصلت الصورة الثانية! 📷📷\n\n"
                "الآن اكتب وصف الحركة والانتقال "
                "الذي تريده بين الصورتين."
            )

    except Exception as error:

        print("PHOTO ERROR:", error)

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة.\n"
            "حاول إرسالها مرة أخرى."
        )


# ============================================================
# TEXT HANDLER
# ============================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = get_state(user_id)

    images = state.get(
        "images",
        [],
    )

    if not images:

        await update.message.reply_text(
            "📷 أرسل صورة أولًا.",
            reply_markup=main_menu(),
        )

        return

    prompt = (
        update.message.text or ""
    ).strip()

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة التي تريدها."
        )

        return

    state["prompt"] = prompt

    model = MODEL_NAMES.get(
        state["model"],
        state["model"],
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "⚙️ تعديل الإعدادات",
                callback_data="settings",
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 إنشاء الفيديو",
                callback_data="generate",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_generation",
            )
        ],
    ]

    await update.message.reply_text(
        "📝 تم استلام وصف الحركة.\n\n"
        f"الوصف:\n{prompt}\n\n"
        "⚙️ الإعدادات الحالية:\n"
        f"🤖 {model}\n"
        f"⏱️ {state['duration']} ثانية\n"
        f"📺 {state['resolution']}\n"
        f"🔊 {'تشغيل' if state['audio'] else 'إيقاف'}\n"
        f"🖼️ عدد الصور: {len(images)}\n\n"
        "اضغط إنشاء الفيديو عندما تكون جاهزًا.",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# GENERATE VIDEO
# ============================================================

async def generate_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user_id = query.from_user.id

    state = get_state(user_id)

    images = state.get(
        "images",
        [],
    )

    prompt = state.get(
        "prompt"
    )

    if not images:

        await query.edit_message_text(
            "❌ لم يتم إرسال صورة.",
            reply_markup=main_menu(),
        )

        return

    if not prompt:

        await query.edit_message_text(
            "❌ لم يتم كتابة وصف الحركة.",
            reply_markup=main_menu(),
        )

        return

    if state.get("generating"):

        await query.answer(
            "يوجد فيديو قيد الإنشاء بالفعل.",
            show_alert=True,
        )

        return

    model = state["model"]

    duration = state["duration"]

    resolution = state["resolution"]

    audio = state["audio"]

    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    valid_durations = MODEL_DURATIONS.get(
        model,
        [5],
    )

    if duration not in valid_durations:

        duration = valid_durations[0]

        state["duration"] = duration

    valid_resolutions = MODEL_RESOLUTIONS.get(
        model,
        ["480p"],
    )

    if resolution not in valid_resolutions:

        resolution = valid_resolutions[0]

        state["resolution"] = resolution

    if not AUDIO_SUPPORTED.get(
        model,
        False,
    ):

        audio = False

        state["audio"] = False

    state["generating"] = True

    await query.answer()

    await query.edit_message_text(
        "⏳ جاري إنشاء الفيديو...\n\n"
        "📤 رفع الصورة إلى Magic Hour...\n"
        "🎬 تجهيز طلب الذكاء الاصطناعي..."
    )

    try:

        # ----------------------------------------------------
        # UPLOAD FIRST IMAGE
        # ----------------------------------------------------

        upload_url_1, file_path_1 = create_upload_url(
            "jpg"
        )

        upload_image(
            upload_url_1,
            images[0],
        )

        # ----------------------------------------------------
        # UPLOAD SECOND IMAGE
        # ----------------------------------------------------

        end_image_path = None

        if len(images) >= 2:

            await query.edit_message_text(
                "⏳ جاري رفع الصورة الثانية...\n\n"
                "بعدها سيبدأ إنشاء الفيديو."
            )

            upload_url_2, file_path_2 = create_upload_url(
                "jpg"
            )

            upload_image(
                upload_url_2,
                images[1],
            )

            end_image_path = file_path_2

        # ----------------------------------------------------
        # CREATE VIDEO
        # ----------------------------------------------------

        await query.edit_message_text(
            "🎬 تم إرسال الطلب إلى Magic Hour.\n\n"
            "⏳ جاري إنشاء الفيديو الآن...\n"
            "قد يستغرق الأمر عدة دقائق."
        )

        video_data = create_video(
            image_path=file_path_1,
            prompt=prompt,
            model=model,
            duration=duration,
            resolution=resolution,
            audio=audio,
            end_image_path=end_image_path,
        )

        video_id = video_data["id"]

        estimated_credits = video_data.get(
            "credits_charged"
        )

        print(
            "VIDEO ID:",
            video_id,
        )

        print(
            "ESTIMATED CREDITS:",
            estimated_credits,
        )

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        video_url, final_data = wait_for_video(
            video_id,
            max_wait=900,
        )

        if not video_url:

            state["generating"] = False

            error_message = ""

            if final_data:

                error_message = str(
                    final_data.get(
                        "error",
                        ""
                    )
                )

            await query.edit_message_text(
                "❌ لم يتم إنشاء الفيديو.\n\n"
                "قد يكون السبب:\n"
                "• عدم وجود Credits كافية\n"
                "• النموذج غير متاح لحسابك\n"
                "• إعداد غير مدعوم\n"
                "• خطأ مؤقت في Magic Hour\n\n"
                + (
                    f"تفاصيل: {error_message}"
                    if error_message
                    else ""
                ),
                reply_markup=main_menu(),
            )

            return

        # ----------------------------------------------------
        # DOWNLOAD VIDEO
        # ----------------------------------------------------

        await query.edit_message_text(
            "✅ اكتمل إنشاء الفيديو!\n\n"
            "📥 جاري تحميل الفيديو وإرساله إليك..."
        )

        video_response = requests.get(
            video_url,
            timeout=300,
        )

        video_response.raise_for_status()

        video_bytes = video_response.content

        # ----------------------------------------------------
        # CAPTION
        # ----------------------------------------------------

        caption = (
            "🎬 تم إنشاء الفيديو بنجاح! ✅\n\n"
            f"🤖 النموذج: "
            f"{MODEL_NAMES.get(model, model)}\n"
            f"⏱️ المدة: {duration} ثانية\n"
            f"📺 الدقة: {resolution}\n"
        )

        if audio:

            caption += "🔊 الصوت: تشغيل\n"

        else:

            caption += "🔇 الصوت: إيقاف\n"

        final_credits = None

        if final_data:

            final_credits = final_data.get(
                "credits_charged"
            )

        if final_credits is not None:

            caption += (
                f"💳 Credits المستخدمة: "
                f"{final_credits}"
            )

        elif estimated_credits is not None:

            caption += (
                f"💳 Credits المتوقعة: "
                f"{estimated_credits}"
            )

        # ----------------------------------------------------
        # SEND VIDEO
        # ----------------------------------------------------

        await context.bot.send_video(
            chat_id=user_id,
            video=video_bytes,
            caption=caption,
            supports_streaming=True,
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        state["generating"] = False

        reset_process(user_id)

        await query.edit_message_text(
            "✅ تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"
            "📷 يمكنك إرسال صورة جديدة للبدء من جديد.",
            reply_markup=main_menu(),
        )

    except requests.HTTPError as error:

        state["generating"] = False

        print(
            "HTTP ERROR:",
            error,
        )

        api_text = ""

        try:

            api_text = error.response.text

        except Exception:

            pass

        print(
            "API RESPONSE:",
            api_text,
        )

        status_code = None

        try:

            status_code = error.response.status_code

        except Exception:

            pass

        if status_code == 401:

            message = (
                "❌ مفتاح Magic Hour غير صحيح أو منتهي."
            )

        elif status_code == 402:

            message = (
                "💳 لا يوجد Credits كافية "
                "لهذا الطلب."
            )

        elif status_code == 422:

            message = (
                "❌ Magic Hour رفض إعدادات الطلب.\n\n"
                "جرّب النموذج الافتراضي والدقة 480p."
            )

        else:

            message = (
                "❌ حدث خطأ من Magic Hour.\n\n"
                "جرّب مرة أخرى بعد قليل."
            )

        await query.edit_message_text(
            message,
            reply_markup=main_menu(),
        )

    except Exception as error:

        state["generating"] = False

        print(
            "GENERATION ERROR:",
            repr(error),
        )

        await query.edit_message_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "جرّب مرة أخرى، وإذا استمر الخطأ "
            "أرسل لي آخر جزء من Logs في Render.",
            reply_markup=main_menu(),
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    print(
        "BOT ERROR:",
        repr(context.error),
    )


# ============================================================
# RUN BOT
# ============================================================

def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    bot_app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # Photos
    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    # Text
    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    # Buttons
    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    # Errors
    bot_app.add_error_handler(
        error_handler
    )

    print(
        "Telegram bot started successfully."
    )

    bot_app.run_polling(
        stop_signals=None,
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True,
    )

    bot_thread.start()

    run_web()
