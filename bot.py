import os
import asyncio
import tempfile
import threading
import time
import traceback

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
    ContextTypes,
    filters,
)

from gradio_client import Client, handle_file


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]

HF_SPACE = "IdlecloudX/wan-i2v-1"

HF_API_NAME = "/generate_video"

MIN_DURATION = 0.5
MAX_DURATION = 20.1
DEFAULT_DURATION = 3.5

DEFAULT_STEPS = 6
DEFAULT_NEGATIVE_PROMPT = (
    "色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, "
    "风格, 作品, 画作, 画面, 静止, 整体发灰, "
    "最差质量, 低质量, JPEG压缩残留, 丑陋的, "
    "残缺的, 多余的手指, 画得不好的手部, "
    "画得不好的脸部, 畸形的, 毁容的, "
    "形态畸形的肢体, 手指融合, 静止不动的画面, "
    "杂乱的背景, 三条腿, 背景人很多, 倒着走"
)

DEFAULT_GUIDANCE = 1
DEFAULT_GUIDANCE_2 = 1

DEFAULT_SEED = 42

DEFAULT_QUALITY = 6
DEFAULT_SCHEDULER = "UniPCMultistep"
DEFAULT_FLOW_SHIFT = 3.0
DEFAULT_FRAME_MULTIPLIER = 16
DEFAULT_SAFE_MODE = True


# =========================================================
# Flask
# =========================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Wan 2.2 Telegram Bot is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))

    print("Starting Flask server...")

    web_app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
    )


# =========================================================
# USER STATE
# =========================================================

user_states = {}

generation_locks = {}


def get_lock(user_id):
    if user_id not in generation_locks:
        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


def get_duration(user_id):
    state = user_states.get(user_id, {})

    duration = state.get(
        "duration",
        DEFAULT_DURATION,
    )

    try:
        duration = float(duration)
    except Exception:
        duration = DEFAULT_DURATION

    duration = max(MIN_DURATION, duration)
    duration = min(MAX_DURATION, duration)

    return round(duration, 1)


# =========================================================
# HF CLIENT
# =========================================================

def get_hf_client():
    print("=" * 60)
    print("Connecting to Hugging Face...")
    print("Space:", HF_SPACE)
    print("=" * 60)

    client = Client(HF_SPACE)

    print("Hugging Face connected.")

    return client


# =========================================================
# EXTRACT VIDEO PATH
# =========================================================

def extract_video_path(result):
    print("=" * 70)
    print("RAW GRADIO RESULT:")
    print(repr(result))
    print("=" * 70)

    value = result

    # Tuple / list
    if isinstance(result, (tuple, list)):
        if len(result) > 0:
            value = result[0]

    # String path
    if isinstance(value, str):
        if os.path.exists(value):
            return value

        return value

    # Gradio FileData
    if isinstance(value, dict):

        path = value.get("path")

        if path:
            if os.path.exists(path):
                return path

            return path

        url = value.get("url")

        if url:
            return url

        # بعض إصدارات Gradio
        file_path = value.get("file_path")

        if file_path:
            return file_path

    # Object with path
    if hasattr(value, "path"):

        path = getattr(value, "path", None)

        if path:
            return path

    # Object with url
    if hasattr(value, "url"):

        url = getattr(value, "url", None)

        if url:
            return url

    raise RuntimeError(
        "Wan 2.2 لم يرجع ملف فيديو صالح."
    )


# =========================================================
# WAN GENERATION
# =========================================================

def generate_wan_video(
    image_path,
    prompt,
    duration,
):
    """
    استدعاء Space:
    IdlecloudX/wan-i2v-1

    الترتيب المهم:

    1 input_image
    2 last_image
    3 prompt
    4 steps
    5 negative_prompt
    6 duration_seconds
    7 guidance_scale
    8 guidance_scale_2
    9 seed
    10 randomize_seed
    11 quality
    12 scheduler
    13 flow_shift
    14 frame_multiplier
    15 safe_mode
    16 ...
    """

    print("=" * 70)
    print("WAN 2.2 GENERATION")
    print("Space:", HF_SPACE)
    print("Image:", image_path)
    print("Prompt:", prompt)
    print("Duration:", duration)
    print("=" * 70)

    client = get_hf_client()

    # -----------------------------------------------------
    # مهم جداً:
    #
    # last_image = None
    #
    # لأن الـSpace ينتظر صورة ثانية اختيارية
    # بعد الصورة الأولى.
    # -----------------------------------------------------

    result = client.predict(

        # 1
        handle_file(image_path),

        # 2
        None,

        # 3
        prompt,

        # 4
        DEFAULT_STEPS,

        # 5
        DEFAULT_NEGATIVE_PROMPT,

        # 6
        float(duration),

        # 7
        DEFAULT_GUIDANCE,

        # 8
        DEFAULT_GUIDANCE_2,

        # 9
        DEFAULT_SEED,

        # 10
        True,

        # 11
        DEFAULT_QUALITY,

        # 12
        DEFAULT_SCHEDULER,

        # 13
        DEFAULT_FLOW_SHIFT,

        # 14
        DEFAULT_FRAME_MULTIPLIER,

        # 15
        DEFAULT_SAFE_MODE,

        # 16
        True,

        api_name=HF_API_NAME,
    )

    return extract_video_path(result)


# =========================================================
# MAIN MENU
# =========================================================

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
                "⏱️ اختيار مدة الفيديو",
                callback_data="duration_menu",
            )
        ],

        [
            InlineKeyboardButton(
                "ℹ️ معلومات",
                callback_data="info",
            )
        ],

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# DURATION MENU
# =========================================================

def duration_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "0.5 ثانية",
                callback_data="duration_0.5",
            ),
            InlineKeyboardButton(
                "1 ثانية",
                callback_data="duration_1",
            ),
        ],

        [
            InlineKeyboardButton(
                "3 ثواني",
                callback_data="duration_3",
            ),
            InlineKeyboardButton(
                "5 ثواني ⭐",
                callback_data="duration_5",
            ),
        ],

        [
            InlineKeyboardButton(
                "8 ثواني",
                callback_data="duration_8",
            ),
            InlineKeyboardButton(
                "10 ثواني",
                callback_data="duration_10",
            ),
        ],

        [
            InlineKeyboardButton(
                "15 ثانية",
                callback_data="duration_15",
            ),
            InlineKeyboardButton(
                "20.1 ثانية 🔥",
                callback_data="duration_20.1",
            ),
        ],

        [
            InlineKeyboardButton(
                "✏️ مدة مخصصة",
                callback_data="custom_duration",
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ الرئيسية",
                callback_data="back_main",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# GENERATION BUTTONS
# =========================================================

def generation_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🎬 إنشاء الفيديو",
                callback_data="generate",
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 إعادة المحاولة",
                callback_data="retry",
            )
        ],

        [
            InlineKeyboardButton(
                "⏱️ تغيير المدة",
                callback_data="duration_menu",
            )
        ],

        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_generation",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    old_state = user_states.get(
        user_id,
        {},
    )

    duration = old_state.get(
        "duration",
        DEFAULT_DURATION,
    )

    user_states[user_id] = {
        "duration": duration,
    }

    await update.message.reply_text(

        "🎬 أهلاً بك في بوت Wan 2.2\n\n"

        "🤖 المحرك:\n"
        "Wan 2.2 I2V 14B Lightning\n\n"

        "📷 أرسل صورة\n"
        "✍️ اكتب وصف الحركة\n"
        "⏱️ اختر المدة\n"
        "🎬 ثم أنشئ الفيديو.\n\n"

        f"⏱️ المدة الحالية: {duration} ثانية\n"
        f"🔥 الحد الأقصى: {MAX_DURATION} ثانية\n\n"

        "💰 لا يوجد دفع داخل البوت.\n"
        "ℹ️ التوليد يعتمد على توفر الـSpace وZeroGPU.",

        reply_markup=main_menu(),
    )


# =========================================================
# /CANCEL
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = user_states.pop(
        user_id,
        {},
    )

    image_path = state.get(
        "image_path",
    )

    if image_path:

        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass

    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=main_menu(),
    )


# =========================================================
# /HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "1️⃣ اضغط 🎬 إنشاء فيديو\n"
        "2️⃣ أرسل صورة\n"
        "3️⃣ اكتب وصف الحركة\n"
        "4️⃣ اضغط 🎬 إنشاء الفيديو\n\n"

        "⏱️ المدة من "
        f"{MIN_DURATION} إلى {MAX_DURATION} ثانية.\n\n"

        "وإذا فشل التوليد، يمكنك الضغط على "
        "🔄 إعادة المحاولة بدون إعادة إرسال "
        "الصورة أو كتابة الوصف.",

        reply_markup=main_menu(),
    )


# =========================================================
# PHOTO
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = user_states.get(
        user_id,
        {},
    )

    if not state.get(
        "waiting_for_photo",
    ):

        await update.message.reply_text(
            "📷 اضغط أولاً على 🎬 إنشاء فيديو.",
            reply_markup=main_menu(),
        )

        return

    temp_image_path = None

    try:

        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False,
        ) as temp_file:

            temp_image_path = temp_file.name

        await telegram_file.download_to_drive(
            custom_path=temp_image_path,
        )

        duration = get_duration(
            user_id,
        )

        user_states[user_id] = {

            "image_path":
                temp_image_path,

            "duration":
                duration,

            "waiting_for_photo":
                False,

            "waiting_for_prompt":
                True,

            "prompt":
                None,
        }

        await update.message.reply_text(

            "✅ وصلت الصورة!\n\n"

            f"⏱️ المدة: {duration} ثانية\n\n"

            "✍️ الآن اكتب وصف الحركة التي تريدها.",

        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error),
        )

        if temp_image_path:

            try:
                os.remove(temp_image_path)
            except Exception:
                pass

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة.",
        )


# =========================================================
# TEXT
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = user_states.get(
        user_id,
        {},
    )

    # -----------------------------------------------------
    # CUSTOM DURATION
    # -----------------------------------------------------

    if state.get(
        "waiting_for_custom_duration",
    ):

        try:

            duration = float(
                update.message.text.strip(),
            )

        except ValueError:

            await update.message.reply_text(
                "❌ اكتب مدة صحيحة، مثال: 12 أو 18.5",
            )

            return

        if (
            duration < MIN_DURATION
            or duration > MAX_DURATION
        ):

            await update.message.reply_text(

                f"❌ المدة يجب أن تكون بين "
                f"{MIN_DURATION} و "
                f"{MAX_DURATION} ثانية.",
            )

            return

        state["duration"] = round(
            duration,
            1,
        )

        state.pop(
            "waiting_for_custom_duration",
            None,
        )

        await update.message.reply_text(

            f"✅ تم اختيار مدة "
            f"{state['duration']} ثانية.",

            reply_markup=main_menu(),
        )

        return

    # -----------------------------------------------------
    # PROMPT
    # -----------------------------------------------------

    if state.get(
        "waiting_for_prompt",
    ):

        prompt = update.message.text.strip()

        if not prompt:

            await update.message.reply_text(
                "✍️ اكتب وصف الحركة.",
            )

            return

        state["prompt"] = prompt

        state["waiting_for_prompt"] = False

        duration = get_duration(
            user_id,
        )

        await update.message.reply_text(

            "📝 تم استلام الوصف:\n\n"

            f"{prompt}\n\n"

            f"⏱️ المدة: {duration} ثانية\n\n"

            "اضغط 🎬 إنشاء الفيديو.",

            reply_markup=generation_menu(),
        )

        return

    await update.message.reply_text(
        "استخدم القائمة للبدء 👇",
        reply_markup=main_menu(),
    )


# =========================================================
# ACTUAL GENERATION
# =========================================================

async def do_generation(
    query,
    context,
    user_id,
):

    state = user_states.get(
        user_id,
        {},
    )

    image_path = state.get(
        "image_path",
    )

    prompt = state.get(
        "prompt",
    )

    duration = get_duration(
        user_id,
    )

    if not image_path or not os.path.exists(
        image_path,
    ):

        await query.edit_message_text(
            "❌ الصورة غير موجودة.\n\n"
            "ابدأ عملية جديدة.",
            reply_markup=main_menu(),
        )

        return

    if not prompt:

        await query.edit_message_text(
            "❌ لم يتم العثور على الوصف.",
            reply_markup=main_menu(),
        )

        return

    await query.edit_message_text(

        "⏳ جاري إنشاء الفيديو...\n\n"

        "🤖 Wan 2.2 I2V 14B Lightning\n"
        "⚡ Lightning\n\n"

        f"⏱️ المدة: {duration} ثانية\n\n"

        "قد يتأخر التوليد إذا كان ZeroGPU مشغولاً.",

    )

    try:

        video_path = await asyncio.to_thread(

            generate_wan_video,

            image_path,

            prompt,

            duration,
        )

    except Exception as error:

        print("=" * 70)
        print("WAN ERROR")
        print(type(error).__name__)
        print(repr(error))
        print("=" * 70)
        traceback.print_exc()

        # لا نحذف الحالة هنا
        # حتى يستطيع المستخدم إعادة المحاولة
        await query.edit_message_text(

            "❌ فشل إنشاء الفيديو.\n\n"

            f"المدة: {duration} ثانية\n\n"

            "يمكنك الضغط على 🔄 إعادة المحاولة "
            "بنفس الصورة والوصف بدون إعادة إدخالهم.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔄 إعادة المحاولة",
                        callback_data="retry",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⏱️ تغيير المدة",
                        callback_data="duration_menu",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation",
                    )
                ],

            ]),
        )

        return

    if not video_path:

        await query.edit_message_text(

            "❌ لم يرجع الـSpace ملف فيديو.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔄 إعادة المحاولة",
                        callback_data="retry",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation",
                    )
                ],

            ]),
        )

        return

    await query.edit_message_text(
        "✅ تم إنشاء الفيديو!\n\n"
        "📤 جاري إرساله إلى Telegram...",
    )

    try:

        if isinstance(video_path, str):

            if video_path.startswith("http://") or \
               video_path.startswith("https://"):

                await context.bot.send_video(

                    chat_id=user_id,

                    video=video_path,

                    caption=(

                        "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                        "🤖 Wan 2.2 I2V 14B Lightning\n"

                        f"⏱️ المدة: {duration} ثانية"
                    ),

                    supports_streaming=True,
                )

            else:

                with open(
                    video_path,
                    "rb",
                ) as video_file:

                    await context.bot.send_video(

                        chat_id=user_id,

                        video=video_file,

                        caption=(

                            "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                            "🤖 Wan 2.2 I2V 14B Lightning\n"

                            f"⏱️ المدة: {duration} ثانية"
                        ),

                        supports_streaming=True,
                    )

        else:

            raise RuntimeError(
                "نوع ملف الفيديو غير معروف."
            )

    except Exception as error:

        print(
            "SEND VIDEO ERROR:",
            repr(error),
        )

        await query.edit_message_text(

            "⚠️ تم إنشاء الفيديو، "
            "لكن حدث خطأ أثناء إرساله إلى Telegram.\n\n"

            "يمكنك تجربة إنشاءه مرة أخرى.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔄 إعادة المحاولة",
                        callback_data="retry",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⬅️ الرئيسية",
                        callback_data="back_main",
                    )
                ],

            ]),
        )

        return

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    await query.edit_message_text(

        "🎉 تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"

        f"⏱️ المدة: {duration} ثانية\n\n"

        "يمكنك إنشاء فيديو آخر.",

        reply_markup=main_menu(),
    )

    # نحذف الملف بعد النجاح فقط
    old_image = state.get(
        "image_path",
    )

    if old_image:

        try:

            if os.path.exists(
                old_image,
            ):
                os.remove(old_image)

        except Exception:
            pass

    user_states.pop(
        user_id,
        None,
    )


# =========================================================
# GENERATE / RETRY
# =========================================================

async def generate_or_retry(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    lock = get_lock(user_id)

    if not lock.acquire(
        blocking=False,
    ):

        await query.answer(
            "⏳ يوجد فيديو قيد الإنشاء بالفعل.",
            show_alert=True,
        )

        return

    try:

        await do_generation(
            query,
            context,
            user_id,
        )

    finally:

        try:
            lock.release()
        except Exception:
            pass


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    data = query.data or ""

    user_id = query.from_user.id

    # -----------------------------------------------------
    # NEW VIDEO
    # -----------------------------------------------------

    if data == "new_video":

        await query.answer()

        old_state = user_states.get(
            user_id,
            {},
        )

        duration = old_state.get(
            "duration",
            DEFAULT_DURATION,
        )

        user_states[user_id] = {

            "duration":
                duration,

            "waiting_for_photo":
                True,

            "waiting_for_prompt":
                False,
        }

        await query.edit_message_text(

            "📷 أرسل الصورة التي تريد تحويلها إلى فيديو.\n\n"

            f"⏱️ المدة الحالية: {duration} ثانية\n\n"

            "بعد إرسال الصورة سأطلب منك وصف الحركة.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⏱️ تغيير المدة",
                        callback_data="duration_menu",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation",
                    )
                ],

            ]),
        )

        return

    # -----------------------------------------------------
    # DURATION MENU
    # -----------------------------------------------------

    if data == "duration_menu":

        await query.answer()

        await query.edit_message_text(

            "⏱️ اختر مدة الفيديو:\n\n"

            f"الحد الأقصى: {MAX_DURATION} ثانية",

            reply_markup=duration_menu(),
        )

        return

    # -----------------------------------------------------
    # CUSTOM DURATION
    # -----------------------------------------------------

    if data == "custom_duration":

        await query.answer()

        state = user_states.setdefault(
            user_id,
            {},
        )

        state["waiting_for_custom_duration"] = True

        await query.edit_message_text(

            "✏️ أرسل المدة التي تريدها بالثواني.\n\n"

            f"مثال: 12\n"
            f"أو: 18.5\n\n"

            f"المسموح: {MIN_DURATION} - "
            f"{MAX_DURATION} ثانية.",

        )

        return

    # -----------------------------------------------------
    # DURATION VALUES
    # -----------------------------------------------------

    if data.startswith(
        "duration_",
    ):

        value = data.replace(
            "duration_",
            "",
        )

        try:

            duration = float(
                value,
            )

        except Exception:

            await query.answer(
                "❌ مدة غير صحيحة.",
                show_alert=True,
            )

            return

        state = user_states.setdefault(
            user_id,
            {},
        )

        state["duration"] = duration

        state.pop(
            "waiting_for_custom_duration",
            None,
        )

        await query.answer(
            f"تم اختيار {duration} ثانية.",
        )

        await query.edit_message_text(

            f"✅ المدة الآن: {duration} ثانية\n\n"

            "يمكنك متابعة إنشاء الفيديو.",

            reply_markup=main_menu(),
        )

        return

    # -----------------------------------------------------
    # GENERATE
    # -----------------------------------------------------

    if data == "generate":

        await generate_or_retry(
            update,
            context,
        )

        return

    # -----------------------------------------------------
    # RETRY
    # -----------------------------------------------------

    if data == "retry":

        await generate_or_retry(
            update,
            context,
        )

        return

    # -----------------------------------------------------
    # CANCEL
    # -----------------------------------------------------

    if data == "cancel_generation":

        await query.answer()

        state = user_states.pop(
            user_id,
            {},
        )

        image_path = state.get(
            "image_path",
        )

        if image_path:

            try:

                if os.path.exists(
                    image_path,
                ):
                    os.remove(
                        image_path,
                    )

            except Exception:
                pass

        await query.edit_message_text(

            "❌ تم إلغاء العملية.",

            reply_markup=main_menu(),
        )

        return

    # -----------------------------------------------------
    # BACK MAIN
    # -----------------------------------------------------

    if data == "back_main":

        await query.answer()

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu(),
        )

        return

    # -----------------------------------------------------
    # INFO
    # -----------------------------------------------------

    if data == "info":

        await query.answer()

        await query.edit_message_text(

            "🤖 Wan 2.2 I2V 14B Lightning\n\n"

            "📷 تحويل صورة إلى فيديو\n"
            "✍️ وصف حركة مخصص\n"
            f"⏱️ مدة من {MIN_DURATION} إلى "
            f"{MAX_DURATION} ثانية\n"
            "🔄 إعادة المحاولة بنفس الطلب\n\n"

            "المعالجة تتم عبر Hugging Face "
            "ZeroGPU حسب توفر الخدمة.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⬅️ الرئيسية",
                        callback_data="back_main",
                    )
                ]

            ]),
        )

        return

    await query.answer()


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    print("=" * 70)
    print("TELEGRAM ERROR")
    print(type(context.error).__name__)
    print(repr(context.error))
    print("=" * 70)

    # Conflict يعني نسخة أخرى من البوت تستخدم نفس TOKEN
    if context.error:

        error_text = str(
            context.error,
        )

        if "Conflict" in error_text:

            print(
                "WARNING: Another Telegram bot instance "
                "is already running with the same BOT_TOKEN."
            )


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("STARTING WAN 2.2 TELEGRAM BOT")
    print("=" * 60)

    # Flask في Thread مستقل
    web_thread = threading.Thread(
        target=run_web,
        daemon=True,
    )

    web_thread.start()

    print("Starting Telegram bot...")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # Buttons
    application.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    # Photos
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_text,
        )
    )

    application.add_error_handler(
        error_handler,
    )

    print("=" * 60)
    print("Bot is running...")
    print("=" * 60)

    # Polling
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
