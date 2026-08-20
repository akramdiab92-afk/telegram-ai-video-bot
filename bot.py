import os
import asyncio
import tempfile
import threading

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
# الإعدادات
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Space
HF_SPACE = "IdlecloudX/wan-i2v-1"

# API الخاص بالـSpace
HF_API_NAME = "/generate_video"

# المدة
MIN_DURATION = 0.5
MAX_DURATION = 20.1
DEFAULT_DURATION = 5.0

# إعدادات Wan
DEFAULT_STEPS = 6

DEFAULT_GUIDANCE = 1
DEFAULT_GUIDANCE_2 = 1

DEFAULT_NEGATIVE_PROMPT = (
    "色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, "
    "风格, 作品, 画作, 画面, 静止, 整体发灰, "
    "最差质量, 低质量, JPEG压缩残留, 丑陋的, "
    "残缺的, 多余的手指, 画得不好的手部, "
    "画得不好的脸部, 畸形的, 毁容的, "
    "形态畸形的肢体, 手指融合, 静止不动的画面, "
    "杂乱的背景, 三条腿, 背景人很多, 倒着走"
)


# =========================================================
# Flask
# =========================================================

web_app = Flask(__name__)

user_states = {}

generation_locks = {}


@web_app.route("/")
def home():
    return "Wan 2.2 Telegram Bot is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    web_app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# =========================================================
# أدوات عامة
# =========================================================

def get_lock(user_id):

    if user_id not in generation_locks:

        generation_locks[user_id] = (
            threading.Lock()
        )

    return generation_locks[user_id]


def get_duration(user_id):

    state = user_states.get(
        user_id,
        {}
    )

    duration = state.get(
        "duration",
        DEFAULT_DURATION
    )

    try:

        duration = float(
            duration
        )

    except Exception:

        duration = DEFAULT_DURATION

    if duration < MIN_DURATION:
        duration = MIN_DURATION

    if duration > MAX_DURATION:
        duration = MAX_DURATION

    return round(
        duration,
        1
    )


def cleanup_image(user_id):

    state = user_states.get(
        user_id,
        {}
    )

    image_path = state.get(
        "image_path"
    )

    if image_path:

        try:

            if os.path.exists(
                image_path
            ):

                os.remove(
                    image_path
                )

        except Exception as error:

            print(
                "IMAGE CLEANUP ERROR:",
                repr(error)
            )


# =========================================================
# Hugging Face
# =========================================================

def get_hf_client():

    print("=" * 60)
    print(
        "Connecting to Hugging Face..."
    )

    print(
        "Space:",
        HF_SPACE
    )

    print("=" * 60)

    client = Client(
        HF_SPACE
    )

    print(
        "Hugging Face connected."
    )

    return client


def extract_video_path(result):

    print("=" * 70)
    print(
        "RAW GRADIO RESULT:"
    )
    print(
        repr(result)
    )
    print("=" * 70)

    video_result = result

    # النتيجة غالباً tuple
    if isinstance(
        result,
        tuple
    ):

        if len(result) > 0:

            video_result = result[0]

    # أو list
    elif isinstance(
        result,
        list
    ):

        if len(result) > 0:

            video_result = result[0]

    # مسار مباشر
    if isinstance(
        video_result,
        str
    ):

        if os.path.exists(
            video_result
        ):

            return video_result

    # Gradio FileData
    if isinstance(
        video_result,
        dict
    ):

        path = video_result.get(
            "path"
        )

        if path and os.path.exists(
            path
        ):

            return path

        url = video_result.get(
            "url"
        )

        if url:

            return url

    raise RuntimeError(
        "Wan 2.2 لم يرجع ملف فيديو صالح."
    )


def generate_wan_video(
    image_path,
    prompt,
    duration
):

    print("=" * 70)

    print(
        "WAN 2.2 GENERATION"
    )

    print(
        "Space:",
        HF_SPACE
    )

    print(
        "Image:",
        image_path
    )

    print(
        "Prompt:",
        prompt
    )

    print(
        "Duration:",
        duration
    )

    print("=" * 70)

    client = get_hf_client()

    result = client.predict(

        handle_file(
            image_path
        ),

        prompt,

        DEFAULT_STEPS,

        DEFAULT_NEGATIVE_PROMPT,

        float(duration),

        DEFAULT_GUIDANCE,

        DEFAULT_GUIDANCE_2,

        42,

        True,

        api_name=HF_API_NAME
    )

    return extract_video_path(
        result
    )


# =========================================================
# القوائم
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
                "⏱️ اختيار مدة الفيديو",
                callback_data="duration_menu"
            )
        ],

        [
            InlineKeyboardButton(
                "ℹ️ معلومات",
                callback_data="info"
            )
        ],

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def duration_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "0.5 ثانية",
                callback_data="duration_0.5"
            ),

            InlineKeyboardButton(
                "1 ثانية",
                callback_data="duration_1"
            ),
        ],

        [
            InlineKeyboardButton(
                "3 ثواني",
                callback_data="duration_3"
            ),

            InlineKeyboardButton(
                "5 ثواني ⭐",
                callback_data="duration_5"
            ),
        ],

        [
            InlineKeyboardButton(
                "8 ثواني",
                callback_data="duration_8"
            ),

            InlineKeyboardButton(
                "10 ثواني",
                callback_data="duration_10"
            ),
        ],

        [
            InlineKeyboardButton(
                "15 ثانية",
                callback_data="duration_15"
            ),

            InlineKeyboardButton(
                "20.1 ثانية 🔥",
                callback_data="duration_20.1"
            ),
        ],

        [
            InlineKeyboardButton(
                "✏️ مدة مخصصة",
                callback_data="custom_duration"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ الرئيسية",
                callback_data="back_main"
            )
        ]

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    # لا نمسح الحالة إذا كان المستخدم لديه عملية محفوظة
    if user_id not in user_states:

        user_states[user_id] = {
            "duration":
                DEFAULT_DURATION
        }

    await update.message.reply_text(

        "🎬 أهلاً بك في بوت Wan 2.2\n\n"

        "🤖 المحرك:\n"
        "Wan 2.2 I2V 14B Lightning\n\n"

        "📷 أرسل صورة\n"
        "✍️ اكتب وصف الحركة\n"
        "⏱️ اختر المدة\n"
        "🎬 وسيتم إنشاء الفيديو.\n\n"

        f"⏱️ المدة الحالية: "
        f"{get_duration(user_id)} ثانية\n"

        f"🔥 الحد الأقصى: "
        f"{MAX_DURATION} ثانية\n\n"

        "💰 لا يوجد دفع أو رصيد داخل البوت.",

        reply_markup=main_menu()
    )


# =========================================================
# /cancel
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    cleanup_image(
        user_id
    )

    user_states.pop(
        user_id,
        None
    )

    await update.message.reply_text(

        "❌ تم إلغاء العملية.",

        reply_markup=main_menu()
    )


# =========================================================
# /help
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "1️⃣ اضغط «🎬 إنشاء فيديو»\n"
        "2️⃣ أرسل الصورة\n"
        "3️⃣ اكتب وصف الحركة\n"
        "4️⃣ اضغط إنشاء الفيديو\n\n"

        f"⏱️ المدة من {MIN_DURATION} "
        f"إلى {MAX_DURATION} ثانية.\n\n"

        "مثال:\n"
        "اجعل الشخص يتحرك بشكل طبيعي، "
        "يبتسم ويحرك رأسه ببطء، "
        "مع حركة كاميرا سينمائية ناعمة "
        "مع الحفاظ على ملامح الوجه.",

        reply_markup=main_menu()
    )


# =========================================================
# استقبال الصورة
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = user_states.get(
        user_id,
        {}
    )

    if not state.get(
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 اضغط أولاً على "
            "«🎬 إنشاء فيديو».",

            reply_markup=main_menu()
        )

        return

    temp_image_path = None

    try:

        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        ) as temp_file:

            temp_image_path = (
                temp_file.name
            )

        await telegram_file.download_to_drive(
            custom_path=temp_image_path
        )

        duration = get_duration(
            user_id
        )

        user_states[user_id] = {

            "image_path":
                temp_image_path,

            "duration":
                duration,

            "waiting_for_photo":
                False,

            "waiting_for_prompt":
                True
        }

        await update.message.reply_text(

            "✅ وصلت الصورة!\n\n"

            f"⏱️ المدة: "
            f"{duration} ثانية\n\n"

            "✍️ الآن اكتب وصف الحركة.",

        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error)
        )

        if temp_image_path:

            try:

                os.remove(
                    temp_image_path
                )

            except Exception:
                pass

        await update.message.reply_text(

            "❌ حدث خطأ أثناء استقبال الصورة.\n"
            "حاول مرة أخرى."
        )


# =========================================================
# استقبال النص
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = user_states.get(
        user_id,
        {}
    )

    # -----------------------------------------------------
    # مدة مخصصة
    # -----------------------------------------------------

    if state.get(
        "waiting_for_custom_duration"
    ):

        try:

            duration = float(
                update.message.text.strip()
            )

        except ValueError:

            await update.message.reply_text(
                "❌ اكتب مدة صحيحة، مثل:\n12\n18.5"
            )

            return

        if (
            duration < MIN_DURATION
            or
            duration > MAX_DURATION
        ):

            await update.message.reply_text(

                f"❌ المدة يجب أن تكون بين "
                f"{MIN_DURATION} و "
                f"{MAX_DURATION} ثانية."
            )

            return

        state["duration"] = round(
            duration,
            1
        )

        state.pop(
            "waiting_for_custom_duration",
            None
        )

        await update.message.reply_text(

            f"✅ تم اختيار مدة "
            f"{state['duration']} ثانية.",

            reply_markup=main_menu()
        )

        return

    # -----------------------------------------------------
    # وصف الحركة
    # -----------------------------------------------------

    if state.get(
        "waiting_for_prompt"
    ):

        prompt = (
            update.message.text.strip()
        )

        if not prompt:

            await update.message.reply_text(
                "✍️ اكتب وصف الحركة."
            )

            return

        state["prompt"] = prompt

        state["waiting_for_prompt"] = False

        duration = get_duration(
            user_id
        )

        await update.message.reply_text(

            "📝 تم استلام الوصف:\n\n"

            f"{prompt}\n\n"

            f"⏱️ المدة: "
            f"{duration} ثانية\n\n"

            "إذا كان كل شيء صحيحاً اضغط "
            "«🎬 إنشاء الفيديو».",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🎬 إنشاء الفيديو",
                        callback_data="generate"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⏱️ تغيير المدة",
                        callback_data="duration_menu"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation"
                    )
                ]

            ])
        )

        return

    await update.message.reply_text(

        "استخدم القائمة للبدء 👇",

        reply_markup=main_menu()
    )


# =========================================================
# إنشاء الفيديو
# =========================================================

async def generate_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    lock = get_lock(
        user_id
    )

    if not lock.acquire(
        blocking=False
    ):

        await query.answer(

            "⏳ يوجد فيديو قيد الإنشاء بالفعل.",

            show_alert=True
        )

        return

    try:

        state = user_states.get(
            user_id,
            {}
        )

        image_path = state.get(
            "image_path"
        )

        prompt = state.get(
            "prompt"
        )

        duration = get_duration(
            user_id
        )

        # -------------------------------------------------
        # التأكد من وجود الصورة
        # -------------------------------------------------

        if (
            not image_path
            or
            not os.path.exists(
                image_path
            )
        ):

            await query.edit_message_text(

                "❌ الصورة غير موجودة.\n\n"
                "ابدأ عملية جديدة.",

                reply_markup=main_menu()
            )

            return

        # -------------------------------------------------
        # التأكد من وجود الوصف
        # -------------------------------------------------

        if not prompt:

            await query.edit_message_text(

                "❌ لم يتم العثور على وصف الحركة.",

                reply_markup=main_menu()
            )

            return

        # -------------------------------------------------
        # رسالة التوليد
        # -------------------------------------------------

        await query.edit_message_text(

            "⏳ جاري إنشاء الفيديو...\n\n"

            "🤖 Wan 2.2 I2V 14B Lightning\n"
            "⚡ Lightning\n\n"

            f"⏱️ المدة: "
            f"{duration} ثانية\n\n"

            "قد يستغرق التوليد بعض الوقت "
            "بسبب ضغط ZeroGPU."
        )

        # -------------------------------------------------
        # التوليد
        # -------------------------------------------------

        try:

            video_path = await asyncio.to_thread(

                generate_wan_video,

                image_path,

                prompt,

                duration
            )

        except Exception as error:

            print("=" * 70)
            print("WAN ERROR")
            print(
                type(error).__name__
            )
            print(
                repr(error)
            )
            print("=" * 70)

            # مهم جداً:
            # لا نحذف الصورة ولا الحالة هنا
            # حتى تعمل إعادة المحاولة

            await query.edit_message_text(

                "❌ فشل إنشاء الفيديو.\n\n"

                "غالباً بسبب ضغط ZeroGPU "
                "أو خطأ مؤقت في الـSpace.\n\n"

                "يمكنك الضغط على "
                "«🔄 إعادة المحاولة» "
                "بدون إرسال الصورة أو كتابة الوصف من جديد.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "🔄 إعادة المحاولة",
                            callback_data="retry_generation"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "⏱️ تغيير المدة",
                            callback_data="duration_menu"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="cancel_generation"
                        )
                    ]

                ])
            )

            return

        # -------------------------------------------------
        # التأكد من وجود الفيديو
        # -------------------------------------------------

        if not video_path:

            await query.edit_message_text(

                "❌ لم يرجع الـSpace ملف فيديو.\n\n"
                "يمكنك المحاولة مرة أخرى.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "🔄 إعادة المحاولة",
                            callback_data="retry_generation"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="cancel_generation"
                        )
                    ]

                ])
            )

            return

        # -------------------------------------------------
        # إرسال الفيديو
        # -------------------------------------------------

        await query.edit_message_text(

            "✅ تم إنشاء الفيديو!\n\n"
            "📤 جاري إرساله إليك..."
        )

        try:

            # إذا كان مسار ملف محلي
            if (
                isinstance(
                    video_path,
                    str
                )
                and
                os.path.exists(
                    video_path
                )
            ):

                with open(
                    video_path,
                    "rb"
                ) as video_file:

                    await context.bot.send_video(

                        chat_id=user_id,

                        video=video_file,

                        caption=(

                            "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                            "🤖 Wan 2.2 I2V 14B Lightning\n"

                            f"⏱️ المدة: "
                            f"{duration} ثانية"
                        ),

                        supports_streaming=True
                    )

            else:

                # إذا رجع رابط فيديو
                await context.bot.send_video(

                    chat_id=user_id,

                    video=video_path,

                    caption=(

                        "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                        "🤖 Wan 2.2 I2V 14B Lightning\n"

                        f"⏱️ المدة: "
                        f"{duration} ثانية"
                    ),

                    supports_streaming=True
                )

        except Exception as error:

            print(
                "SEND VIDEO ERROR:",
                repr(error)
            )

            # لا نمسح الحالة هنا أيضاً
            # حتى يستطيع المستخدم إعادة المحاولة

            await query.edit_message_text(

                "⚠️ تم إنشاء الفيديو، "
                "لكن حدث خطأ أثناء إرساله إلى Telegram.\n\n"

                "يمكنك محاولة إرساله مرة أخرى.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "🔄 إعادة المحاولة",
                            callback_data="retry_generation"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="cancel_generation"
                        )
                    ]

                ])
            )

            return

        # -------------------------------------------------
        # النجاح الكامل
        # -------------------------------------------------

        await query.edit_message_text(

            "🎉 تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"

            f"⏱️ المدة: "
            f"{duration} ثانية\n\n"

            "يمكنك إنشاء فيديو جديد من القائمة.",

            reply_markup=main_menu()
        )

        # فقط بعد النجاح نحذف الصورة والحالة
        cleanup_image(
            user_id
        )

        user_states.pop(
            user_id,
            None
        )

    finally:

        try:
            lock.release()
        except Exception:
            pass


# =========================================================
# زر إعادة المحاولة
# =========================================================

async def retry_generation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer(
        "🔄 إعادة محاولة التوليد..."
    )

    user_id = query.from_user.id

    state = user_states.get(
        user_id,
        {}
    )

    # التأكد أن البيانات ما زالت موجودة
    image_path = state.get(
        "image_path"
    )

    prompt = state.get(
        "prompt"
    )

    if (
        not image_path
        or
        not os.path.exists(
            image_path
        )
    ):

        await query.edit_message_text(

            "❌ لم تعد الصورة موجودة.\n\n"
            "ابدأ عملية جديدة.",

            reply_markup=main_menu()
        )

        return

    if not prompt:

        await query.edit_message_text(

            "❌ لم يعد وصف الحركة موجوداً.\n\n"
            "ابدأ عملية جديدة.",

            reply_markup=main_menu()
        )

        return

    # استدعاء نفس وظيفة التوليد
    await generate_video(
        update,
        context
    )


# =========================================================
# الأزرار
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user_id = query.from_user.id

    data = query.data or ""

    # -----------------------------------------------------
    # فيديو جديد
    # -----------------------------------------------------

    if data == "new_video":

        await query.answer()

        old_state = user_states.get(
            user_id,
            {}
        )

        duration = old_state.get(
            "duration",
            DEFAULT_DURATION
        )

        # تنظيف أي صورة قديمة
        if old_state.get(
            "image_path"
        ):

            cleanup_image(
                user_id
            )

        user_states[user_id] = {

            "duration":
                duration,

            "waiting_for_photo":
                True,

            "waiting_for_prompt":
                False
        }

        await query.edit_message_text(

            "📷 أرسل الصورة التي تريد "
            "تحويلها إلى فيديو.\n\n"

            f"⏱️ المدة الحالية: "
            f"{duration} ثانية\n\n"

            "بعد إرسال الصورة سأطلب منك وصف الحركة.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⏱️ تغيير المدة",
                        callback_data="duration_menu"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation"
                    )
                ]

            ])
        )

        return

    # -----------------------------------------------------
    # قائمة المدة
    # -----------------------------------------------------

    if data == "duration_menu":

        await query.answer()

        await query.edit_message_text(

            "⏱️ اختر مدة الفيديو:\n\n"

            f"🔥 الحد الأقصى: "
            f"{MAX_DURATION} ثانية",

            reply_markup=duration_menu()
        )

        return

    # -----------------------------------------------------
    # مدة محددة
    # -----------------------------------------------------

    if data.startswith(
        "duration_"
    ):

        await query.answer()

        value = data.replace(
            "duration_",
            "",
            1
        )

        try:

            duration = float(
                value
            )

        except Exception:

            await query.answer(
                "❌ مدة غير صحيحة.",
                show_alert=True
            )

            return

        duration = max(
            MIN_DURATION,
            min(
                MAX_DURATION,
                duration
            )
        )

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["duration"] = round(
            duration,
            1
        )

        # إذا المستخدم كان في عملية
        # ومعه صورة ووصف
        if (
            state.get("image_path")
            and
            state.get("prompt")
        ):

            await query.edit_message_text(

                f"✅ تم تغيير المدة إلى "
                f"{duration} ثانية.\n\n"

                "الصورة والوصف محفوظان.\n"
                "يمكنك المتابعة مباشرة.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "🎬 إنشاء الفيديو",
                            callback_data="generate"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "⏱️ تغيير المدة",
                            callback_data="duration_menu"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="cancel_generation"
                        )
                    ]

                ])
            )

        else:

            await query.edit_message_text(

                f"✅ تم اختيار "
                f"{duration} ثانية.",

                reply_markup=main_menu()
            )

        return

    # -----------------------------------------------------
    # مدة مخصصة
    # -----------------------------------------------------

    if data == "custom_duration":

        await query.answer()

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["waiting_for_custom_duration"] = True

        await query.edit_message_text(

            f"✏️ أرسل المدة التي تريدها.\n\n"

            f"الحد الأدنى: "
            f"{MIN_DURATION} ثانية\n"

            f"الحد الأقصى: "
            f"{MAX_DURATION} ثانية\n\n"

            "مثال:\n"
            "12\n"
            "18.5\n"
            "20.1",

        )

        return

    # -----------------------------------------------------
    # إنشاء الفيديو
    # -----------------------------------------------------

    if data == "generate":

        await generate_video(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # إعادة المحاولة
    # -----------------------------------------------------

    if data == "retry_generation":

        await retry_generation(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # إلغاء
    # -----------------------------------------------------

    if data == "cancel_generation":

        await query.answer()

        cleanup_image(
            user_id
        )

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
    # الرئيسية
    # -----------------------------------------------------

    if data == "back_main":

        await query.answer()

        state = user_states.get(
            user_id,
            {}
        )

        # إذا لا توجد عملية جارية
        if not state.get(
            "image_path"
        ):

            user_states[user_id] = {
                "duration":
                    state.get(
                        "duration",
                        DEFAULT_DURATION
                    )
            }

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu()
        )

        return

    # -----------------------------------------------------
    # معلومات
    # -----------------------------------------------------

    if data == "info":

        await query.answer()

        await query.edit_message_text(

            "🤖 Wan 2.2 I2V 14B Lightning\n\n"

            "🎬 تحويل صورة إلى فيديو\n"
            "⚡ Lightning / FP8\n"
            "🖼️ Image to Video\n\n"

            f"⏱️ المدة: "
            f"{MIN_DURATION} - "
            f"{MAX_DURATION} ثانية\n\n"

            "☁️ التوليد يتم عبر Hugging Face "
            "Space.\n\n"

            "⚠️ سرعة التوليد تعتمد على توفر "
            "ZeroGPU وضغط الـSpace.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⬅️ الرئيسية",
                        callback_data="back_main"
                    )
                ]

            ])
        )

        return


# =========================================================
# الأخطاء العامة
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("=" * 70)
    print("TELEGRAM ERROR")
    print(
        repr(context.error)
    )
    print("=" * 70)


# =========================================================
# تشغيل البوت
# =========================================================

def main():

    print("=" * 70)
    print("STARTING WAN 2.2 TELEGRAM BOT")
    print("=" * 70)

    # تشغيل Flask في Thread
    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    # إنشاء Telegram Application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # الأوامر
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    # الصور
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # الأزرار
    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # النصوص
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_text
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "Bot is running..."
    )

    # تشغيل Telegram
    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# نقطة البداية
# =========================================================

if __name__ == "__main__":

    main()
