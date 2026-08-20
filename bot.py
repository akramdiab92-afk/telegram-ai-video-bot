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

# Space الجديد الذي أرسلته
HF_SPACE = "IdlecloudX/wan-i2v-1"

# API الخاص بالـGradio
HF_API_NAME = "/generate_video"

# الحد الأدنى والأقصى لمدة الفيديو
MIN_DURATION = 0.5
MAX_DURATION = 20.1

# الإعداد الافتراضي
DEFAULT_DURATION = 5.0

# خطوات التوليد
DEFAULT_STEPS = 6

# Guidance
DEFAULT_GUIDANCE = 1
DEFAULT_GUIDANCE_2 = 1

# Negative Prompt
DEFAULT_NEGATIVE_PROMPT = (
    "色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, "
    "风格, 作品, 画作, 画面, 静止, 整体发灰, "
    "最差质量, 低质量, JPEG压缩残留, 丑陋的, "
    "残缺的, 多余的手指, 画得不好的手部, "
    "画得不好的脸部, 畸形的, 毁容的, "
    "形态畸形的肢体, 手指融合, 静止不动的画面, "
    "杂乱的背景, 三条腿, 背景人很多, 倒着走"
)

# Flask حتى يبقى Render شغال
web_app = Flask(__name__)

# حالات المستخدمين
user_states = {}

# منع تشغيل أكثر من توليد لنفس المستخدم
generation_locks = {}


# =========================================================
# Flask
# =========================================================

@web_app.route("/")
def home():
    return "Wan 2.2 Telegram Bot is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))

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
        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


def get_duration(user_id):
    state = user_states.get(user_id, {})

    duration = state.get(
        "duration",
        DEFAULT_DURATION
    )

    try:
        duration = float(duration)
    except Exception:
        duration = DEFAULT_DURATION

    if duration < MIN_DURATION:
        duration = MIN_DURATION

    if duration > MAX_DURATION:
        duration = MAX_DURATION

    return round(duration, 1)


# =========================================================
# الاتصال بـ Hugging Face
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
# توليد الفيديو
# =========================================================

def generate_wan_video(
    image_path,
    prompt,
    duration
):

    print("=" * 70)
    print("WAN 2.2 GENERATION")
    print("Space:", HF_SPACE)
    print("Image:", image_path)
    print("Prompt:", prompt)
    print("Duration:", duration)
    print("=" * 70)

    client = get_hf_client()

    # ترتيب المدخلات مطابق لواجهة الـSpace الحالية:
    #
    # input_image
    # prompt
    # steps
    # negative_prompt
    # duration_seconds
    # guidance_scale
    # guidance_scale_2
    # seed
    # randomize_seed

    result = client.predict(
        handle_file(image_path),

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

    print("=" * 70)
    print("RAW GRADIO RESULT:")
    print(repr(result))
    print("=" * 70)

    video_result = result

    # الـSpace يرجع غالباً:
    # (video_path, seed)

    if isinstance(result, tuple):
        if len(result) > 0:
            video_result = result[0]

    elif isinstance(result, list):
        if len(result) > 0:
            video_result = result[0]

    # إذا كان مسار ملف
    if isinstance(video_result, str):

        if os.path.exists(video_result):
            return video_result

    # إذا رجع Gradio FileData
    if isinstance(video_result, dict):

        path = video_result.get("path")

        if path and os.path.exists(path):
            return path

        url = video_result.get("url")

        if url:
            return url

    raise RuntimeError(
        "Wan 2.2 لم يرجع ملف فيديو صالح."
    )


# =========================================================
# القائمة الرئيسية
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

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# قائمة المدة
# =========================================================

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

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    user_states[user_id] = {
        "duration": DEFAULT_DURATION
    }

    await update.message.reply_text(

        "🎬 أهلاً بك في بوت Wan 2.2\n\n"

        "🤖 المحرك:\n"
        "Wan 2.2 I2V 14B Lightning\n\n"

        "📷 أرسل صورة\n"
        "✍️ اكتب وصف الحركة\n"
        "⏱️ اختر المدة التي تريدها\n"
        "🎬 والبوت ينشئ لك الفيديو.\n\n"

        f"⏱️ المدة الحالية: {DEFAULT_DURATION} ثانية\n"
        f"🔥 الحد الأقصى: {MAX_DURATION} ثانية\n\n"

        "💰 لا يوجد دفع أو رصيد حالياً.\n"
        "🎁 البوت مفتوح للاستخدام.",

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

    state = user_states.pop(
        user_id,
        {}
    )

    image_path = state.get(
        "image_path"
    )

    if image_path:

        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass

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

        "⏱️ يمكنك اختيار مدة من "
        "0.5 إلى 20.1 ثانية.\n\n"

        "مثال للوصف:\n"
        "اجعل الشخص يتحرك بشكل طبيعي، "
        "يبتسم ويحرك رأسه ببطء، "
        "مع حركة كاميرا سينمائية ناعمة "
        "مع الحفاظ على ملامح الوجه.",

        reply_markup=main_menu()
    )


# =========================================================
# الصور
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

            "📷 اضغط أولاً على «🎬 إنشاء فيديو».",

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

            temp_image_path = temp_file.name

        await telegram_file.download_to_drive(
            custom_path=temp_image_path
        )

        duration = get_duration(user_id)

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

            f"⏱️ المدة: {duration} ثانية\n\n"

            "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"

            "مثال:\n"
            "اجعل الشخص يبتسم ويتحرك بشكل طبيعي "
            "مع حركة كاميرا سينمائية ناعمة.",

        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error)
        )

        if temp_image_path:

            try:
                os.remove(temp_image_path)
            except Exception:
                pass

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


# =========================================================
# النص
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

    if state.get(
        "waiting_for_custom_duration"
    ):

        try:

            duration = float(
                update.message.text.strip()
            )

        except ValueError:

            await update.message.reply_text(
                "❌ اكتب مدة صحيحة، مثل: 12 أو 18.5"
            )

            return

        if duration < MIN_DURATION or duration > MAX_DURATION:

            await update.message.reply_text(

                f"❌ المدة يجب أن تكون بين "
                f"{MIN_DURATION} و {MAX_DURATION} ثانية."
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

    if state.get(
        "waiting_for_prompt"
    ):

        prompt = update.message.text.strip()

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

        user_states[user_id] = state

        await update.message.reply_text(

            "📝 تم استلام الوصف:\n\n"

            f"{prompt}\n\n"

            f"⏱️ المدة: {duration} ثانية\n\n"

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

    lock = get_lock(user_id)

    if not lock.acquire(blocking=False):

        await query.answer(
            "⏳ يوجد فيديو قيد الإنشاء بالفعل.",
            show_alert=True
        )

        return

    image_path = None

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

        if not image_path or not os.path.exists(
            image_path
        ):

            await query.edit_message_text(
                "❌ الصورة غير موجودة.\n\n"
                "ابدأ من جديد.",
                reply_markup=main_menu()
            )

            return

        if not prompt:

            await query.edit_message_text(
                "❌ لم يتم العثور على وصف الحركة.",
                reply_markup=main_menu()
            )

            return

        await query.edit_message_text(

            "⏳ جاري إنشاء الفيديو...\n\n"

            "🤖 Wan 2.2 I2V 14B Lightning\n"
            "⚡ FP8 / Lightning\n\n"

            f"⏱️ المدة: {duration} ثانية\n\n"

            "قد يستغرق التوليد بعض الوقت بسبب "
            "ضغط ZeroGPU.",

        )

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
            print(type(error).__name__)
            print(repr(error))
            print("=" * 70)

            await query.edit_message_text(

                "❌ فشل إنشاء الفيديو.\n\n"

                "قد يكون السبب ضغطاً على ZeroGPU "
                "أو خطأ مؤقتاً في الـSpace.\n\n"

                "حاول مرة أخرى بعد قليل.",

                reply_markup=main_menu()
            )

            return

        if not video_path:

            await query.edit_message_text(

                "❌ لم يرجع الـSpace ملف فيديو.",

                reply_markup=main_menu()
            )

            return

        await query.edit_message_text(
            "✅ تم إنشاء الفيديو!\n\n"
            "📤 جاري إرساله إليك..."
        )

        try:

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

                        f"⏱️ المدة: {duration} ثانية"
                    ),

                    supports_streaming=True
                )

        except Exception as error:

            print(
                "SEND VIDEO ERROR:",
                repr(error)
            )

            await query.edit_message_text(

                "⚠️ تم إنشاء الفيديو، "
                "لكن حدث خطأ أثناء إرساله إلى Telegram.",

                reply_markup=main_menu()
            )

            return

        await query.edit_message_text(

            "🎉 تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"

            f"⏱️ المدة: {duration} ثانية\n\n"

            "يمكنك إنشاء فيديو آخر من القائمة.",

            reply_markup=main_menu()
        )

        user_states.pop(
            user_id,
            None
        )

    finally:

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
                    "IMAGE DELETE ERROR:",
                    repr(error)
                )

        try:
            lock.release()
        except Exception:
            pass


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
    # إنشاء فيديو
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

        user_states[user_id] = {

            "duration":
                duration,

            "waiting_for_photo":
                True,

            "waiting_for_prompt":
                False
        }

        await query.edit_message_text(

            "📷 أرسل الصورة التي تريد تحويلها إلى فيديو.\n\n"

            f"⏱️ المدة الحالية: {duration} ثانية\n\n"

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

            f"الحد الأقصى: {MAX_DURATION} ثانية",

            reply_markup=duration_menu()
        )

        return

    # -----------------------------------------------------
    # مدة محددة
    # -----------------------------------------------------

    if data.startswith(
        "duration_"
    ):

        value = data.replace(
            "duration_",
            "",
            1
        )

        try:

            duration = float(value)

        except ValueError:

            await query.answer(
                "المدة غير صحيحة.",
                show_alert=True
            )

            return

        if duration < MIN_DURATION or duration > MAX_DURATION:

            await query.answer(
                "المدة غير متاحة.",
                show_alert=True
            )

            return

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["duration"] = round(
            duration,
            1
        )

        state.pop(
            "waiting_for_custom_duration",
            None
        )

        await query.answer(
            f"تم اختيار {duration} ثانية."
        )

        await query.edit_message_text(

            f"✅ تم اختيار {duration} ثانية.\n\n"

            "يمكنك الآن إنشاء فيديو جديد.",

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

            "✏️ اكتب المدة التي تريدها بالثواني.\n\n"

            f"مثال: 12 أو 18.5\n\n"

            f"المسموح: {MIN_DURATION} - "
            f"{MAX_DURATION} ثانية"
        )

        return

    # -----------------------------------------------------
    # معلومات
    # -----------------------------------------------------

    if data == "info":

        await query.answer()

        await query.edit_message_text(

            "🤖 Wan 2.2 I2V 14B Lightning\n\n"

            "🎬 تحويل الصورة إلى فيديو\n"
            "⚡ Lightning LoRA\n"
            "🚀 FP8\n\n"

            f"⏱️ مدة الفيديو: "
            f"{MIN_DURATION} - {MAX_DURATION} ثانية\n\n"

            "✍️ المستخدم حر في كتابة وصف الحركة.\n\n"

            "💰 لا يوجد نظام دفع أو رصيد حالياً.",

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

    # -----------------------------------------------------
    # إلغاء
    # -----------------------------------------------------

    if data == "cancel_generation":

        await query.answer()

        state = user_states.pop(
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

            except Exception:
                pass

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

        duration = state.get(
            "duration",
            DEFAULT_DURATION
        )

        user_states[user_id] = {
            "duration": duration
        }

        await query.edit_message_text(

            "🏠 القائمة الرئيسية\n\n"

            "🤖 Wan 2.2 I2V 14B Lightning\n"

            f"⏱️ المدة الحالية: {duration} ثانية",

            reply_markup=main_menu()
        )

        return

    # -----------------------------------------------------
    # توليد
    # -----------------------------------------------------

    if data == "generate":

        await generate_video(
            update,
            context
        )

        return

    await query.answer(
        "الخيار غير معروف.",
        show_alert=True
    )


# =========================================================
# معالجة الأخطاء
# =========================================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# تشغيل Telegram
# =========================================================

def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # أوامر
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

    # الصور
    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # النصوص
    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # الأزرار
    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # الأخطاء
    bot_app.add_error_handler(
        error_handler
    )

    print("=" * 60)
    print("Telegram bot starting...")
    print("Wan Space:", HF_SPACE)
    print("=" * 60)

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    print("Starting Flask server...")

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )

    bot_thread.start()

    print("Starting web server...")

    run_web()
