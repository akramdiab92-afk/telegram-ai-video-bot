import os
import asyncio
import tempfile
import threading
from pathlib import Path

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

HF_SPACE = "IdlecloudX/wan-i2v-1"

# الحد الأدنى والأقصى الذي يسمح به الـSpace
MIN_DURATION = 0.5
MAX_DURATION = 20.1

DEFAULT_DURATION = 10.0

# عدد خطوات Wan 2.2
DEFAULT_STEPS = 6

# Safe Mode في الـSpace
DEFAULT_SAFE_MODE = True

# Flask / Render / Koyeb
app_web = Flask(__name__)

# حالة كل مستخدم
user_states = {}

# منع المستخدم من تشغيل أكثر من توليد بنفس الوقت
generation_locks = {}

# =========================================================
# الصفحة الرئيسية
# =========================================================

@app_web.route("/")
def home():
    return "Wan 2.2 Telegram Bot is running!"


@app_web.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))

    app_web.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
    )


# =========================================================
# Locks
# =========================================================

def get_generation_lock(user_id):
    if user_id not in generation_locks:
        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


# =========================================================
# Hugging Face
# =========================================================

def get_hf_client():
    print("Connecting to Hugging Face...")

    client = Client(
        HF_SPACE,
        verbose=True,
    )

    print("Connected to Hugging Face.")

    return client


def generate_video_sync(
    image_path,
    prompt,
    duration,
):
    """
    الاتصال بـ Wan 2.2.

    ملاحظة:
    نستخدم Gradio API الخاص بالـSpace بدل نظام الدفع
    أو أي API خارجي.
    """

    print("=" * 70)
    print("WAN 2.2 GENERATION")
    print("Space:", HF_SPACE)
    print("Image:", image_path)
    print("Prompt:", prompt)
    print("Duration:", duration)
    print("=" * 70)

    client = get_hf_client()

    # نستخدم endpoint /generate_video الموجود في الـSpace.
    #
    # إذا تغيرت أسماء مدخلات الـSpace مستقبلاً،
    # يمكن معرفة الأسماء الحالية من:
    #
    # client.view_api()
    #
    # الكود هنا يستخدم واجهة Wan 2.2 الحالية.

    result = client.predict(
        input_image=handle_file(image_path),
        prompt=prompt,
        duration_seconds=float(duration),
        steps=DEFAULT_STEPS,
        safe_mode=DEFAULT_SAFE_MODE,
        api_name="/generate_video",
    )

    print("RAW WAN RESULT:")
    print(result)

    video_path = extract_video_path(result)

    if not video_path:
        raise RuntimeError(
            "Wan 2.2 لم يرجع ملف فيديو صالح."
        )

    return video_path


# =========================================================
# استخراج الفيديو من نتيجة Gradio
# =========================================================

def extract_video_path(result):
    """
    يتعامل مع صيغ Gradio المختلفة.
    """

    if result is None:
        return None

    # أحياناً تكون النتيجة tuple
    if isinstance(result, tuple):
        for item in result:
            path = extract_video_path(item)

            if path:
                return path

        return None

    # أحياناً list
    if isinstance(result, list):
        for item in result:
            path = extract_video_path(item)

            if path:
                return path

        return None

    # dict / FileData
    if isinstance(result, dict):

        for key in (
            "video",
            "path",
            "filepath",
        ):
            value = result.get(key)

            if value:

                if isinstance(value, str):
                    if os.path.exists(value):
                        return value

        url = result.get("url")

        if url:
            return url

        return None

    # string
    if isinstance(result, str):

        if os.path.exists(result):
            return result

        return None

    return None


# =========================================================
# القائمة الرئيسية
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
                "⚙️ إعدادات الفيديو",
                callback_data="settings",
            )
        ],

        [
            InlineKeyboardButton(
                "ℹ️ المساعدة",
                callback_data="help",
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
                "5 ثواني",
                callback_data="duration_5",
            ),

            InlineKeyboardButton(
                "10 ثواني ⭐",
                callback_data="duration_10",
            ),
        ],

        [
            InlineKeyboardButton(
                "15 ثانية 🔥",
                callback_data="duration_15",
            ),

            InlineKeyboardButton(
                "20 ثانية 🚀",
                callback_data="duration_20",
            ),
        ],

        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    user_states.pop(
        user_id,
        None,
    )

    await update.message.reply_text(

        "🤖 أهلاً بك في بوت Wan 2.2\n\n"

        "🎬 حوّل صورك إلى فيديو بالذكاء الاصطناعي.\n\n"

        "⚡ Wan 2.2 I2V 14B Lightning\n"
        "🎞️ مدة تصل إلى 20.1 ثانية\n"
        "✍️ Prompt حر\n\n"

        "📷 أرسل صورة ثم اكتب وصف الحركة "
        "التي تريدها.\n\n"

        "🚀 البوت مفتوح حالياً بدون نظام "
        "دفع أو رصيد.",

        reply_markup=main_menu(),
    )


# =========================================================
# /cancel
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    state = user_states.pop(
        user_id,
        None,
    )

    if state:

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
        reply_markup=main_menu(),
    )


# =========================================================
# /help
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "1️⃣ اضغط «🎬 إنشاء فيديو».\n"
        "2️⃣ أرسل الصورة.\n"
        "3️⃣ اكتب وصف الحركة بحرية.\n"
        "4️⃣ اختر مدة الفيديو.\n"
        "5️⃣ اضغط إنشاء.\n\n"

        "🤖 الموديل:\n"
        "Wan 2.2 I2V 14B Lightning\n\n"

        "⏱️ المدة:\n"
        "من 0.5 إلى 20.1 ثانية.\n\n"

        "✍️ يمكنك كتابة Prompt طويل ومفصل "
        "حتى الحد الذي يسمح به الـSpace.\n\n"

        "⚠️ التوليد يعتمد على توفر GPU في "
        "Hugging Face.",

        reply_markup=main_menu(),
    )


# =========================================================
# زر إنشاء فيديو
# =========================================================

async def start_generation(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    old_state = user_states.get(
        user_id,
        {},
    )

    duration = old_state.get(
        "duration",
        DEFAULT_DURATION,
    )

    user_states[user_id] = {

        "waiting_for_photo": True,

        "duration": duration,
    }

    await query.edit_message_text(

        "📷 أرسل الصورة الآن.\n\n"

        f"⏱️ المدة الحالية: {duration:g} ثانية\n\n"

        "بعد إرسال الصورة سأطلب منك "
        "وصف الحركة.",

        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "⚙️ تغيير المدة",
                    callback_data="settings",
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


# =========================================================
# استقبال الصورة
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
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 اضغط «🎬 إنشاء فيديو» "
            "أولاً ثم أرسل الصورة.",

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

        duration = state.get(
            "duration",
            DEFAULT_DURATION,
        )

        user_states[user_id] = {

            "image_path":
                temp_image_path,

            "waiting_for_prompt":
                True,

            "duration":
                duration,
        }

        await update.message.reply_text(

            "✅ وصلت الصورة.\n\n"

            f"⏱️ المدة: {duration:g} ثانية\n\n"

            "✍️ الآن اكتب وصف الحركة "
            "التي تريدها.\n\n"

            "مثال:\n"
            "اجعل الشخص يتحرك بشكل طبيعي "
            "مع حركة كاميرا سينمائية بطيئة.",

        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error),
        )

        if temp_image_path:

            try:
                os.remove(
                    temp_image_path
                )
            except Exception:
                pass

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة.",
        )


# =========================================================
# استقبال الـPrompt
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

    if state.get(
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 أرسل الصورة أولاً.",
        )

        return

    if not state.get(
        "waiting_for_prompt"
    ):

        await update.message.reply_text(

            "🎬 اضغط «إنشاء فيديو» "
            "للبدء.",

            reply_markup=main_menu(),
        )

        return

    prompt = (
        update.message.text
        or ""
    ).strip()

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة.",
        )

        return

    # لا نضيف أي كلمات إلى Prompt المستخدم.
    state["prompt"] = prompt

    state["waiting_for_prompt"] = False

    duration = state.get(
        "duration",
        DEFAULT_DURATION,
    )

    await update.message.reply_text(

        "📝 تم استلام الوصف:\n\n"

        f"{prompt}\n\n"

        f"⏱️ المدة: {duration:g} ثانية\n\n"

        "إذا كان كل شيء صحيحاً اضغط "
        "«🎬 إنشاء الفيديو».",

        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🎬 إنشاء الفيديو",
                    callback_data="generate",
                )
            ],

            [
                InlineKeyboardButton(
                    "⏱️ تغيير المدة",
                    callback_data="settings",
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


# =========================================================
# إنشاء الفيديو
# =========================================================

async def generate_video(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    lock = get_generation_lock(
        user_id
    )

    if not lock.acquire(
        blocking=False
    ):

        await query.answer(
            "⏳ لديك عملية توليد قيد التنفيذ.",
            show_alert=True,
        )

        return

    image_path = None

    try:

        state = user_states.get(
            user_id,
            {},
        )

        image_path = state.get(
            "image_path"
        )

        prompt = state.get(
            "prompt"
        )

        duration = float(
            state.get(
                "duration",
                DEFAULT_DURATION,
            )
        )

        # حماية من القيم غير الصحيحة
        duration = max(
            MIN_DURATION,
            min(
                MAX_DURATION,
                duration,
            ),
        )

        if not image_path or not os.path.exists(
            image_path
        ):

            await query.edit_message_text(

                "❌ الصورة غير موجودة.\n\n"
                "ابدأ عملية جديدة.",

                reply_markup=main_menu(),
            )

            return

        if not prompt:

            await query.edit_message_text(

                "❌ لم يتم العثور على وصف الحركة.",

                reply_markup=main_menu(),
            )

            return

        await query.edit_message_text(

            "⏳ جاري إنشاء الفيديو...\n\n"

            "🤖 Wan 2.2 I2V 14B Lightning\n"

            f"⏱️ المدة: {duration:g} ثانية\n\n"

            "⚡ قد يستغرق التوليد بعض الوقت.\n\n"

            "إذا كان الـGPU مشغولاً في Hugging Face "
            "قد تحتاج إلى المحاولة مرة أخرى.",

        )

        # تشغيل التوليد خارج event loop
        try:

            video_path = await asyncio.to_thread(

                generate_video_sync,

                image_path,

                prompt,

                duration,
            )

        except Exception as error:

            print("=" * 70)
            print("WAN GENERATION ERROR")
            print("TYPE:", type(error).__name__)
            print("ERROR:", repr(error))
            print("=" * 70)

            error_text = str(error)

            if "503" in error_text:

                message = (

                    "⚠️ Wan 2.2 مشغول حالياً.\n\n"

                    "يوجد توليد آخر يستخدم GPU.\n"

                    "انتظر قليلاً ثم حاول مرة أخرى."
                )

            elif "422" in error_text:

                message = (

                    "❌ إعدادات الطلب غير مقبولة من Space.\n\n"

                    "راجع Logs في الاستضافة لمعرفة التفاصيل."
                )

            elif "api_name" in error_text.lower():

                message = (

                    "❌ تغيّرت واجهة API الخاصة بالـSpace.\n\n"

                    "راجع Logs، وسنحدّث اسم الـendpoint."
                )

            else:

                message = (

                    "❌ فشل إنشاء الفيديو.\n\n"

                    "قد يكون السبب ضغطاً على ZeroGPU "
                    "أو خطأ مؤقتاً في الـSpace.\n\n"

                    "حاول مرة أخرى."
                )

            await query.edit_message_text(
                message,
                reply_markup=main_menu(),
            )

            return

        if not video_path:

            await query.edit_message_text(

                "❌ لم يرجع Wan 2.2 فيديو.",

                reply_markup=main_menu(),
            )

            return

        # =================================================
        # إرسال الفيديو
        # =================================================

        await query.edit_message_text(
            "✅ تم إنشاء الفيديو!\n\n"
            "📤 جاري إرساله إليك..."
        )

        try:

            # إذا كانت النتيجة رابطاً
            if isinstance(
                video_path,
                str
            ) and video_path.startswith(
                ("http://", "https://")
            ):

                await context.bot.send_video(

                    chat_id=user_id,

                    video=video_path,

                    caption=(

                        "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                        "🤖 Wan 2.2 I2V 14B Lightning\n"

                        f"⏱️ المدة: {duration:g} ثانية"
                    ),

                    supports_streaming=True,
                )

            else:

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

                            f"⏱️ المدة: {duration:g} ثانية"
                        ),

                        supports_streaming=True,
                    )

        except Exception as error:

            print(
                "VIDEO SEND ERROR:",
                repr(error),
            )

            await query.edit_message_text(

                "⚠️ تم إنشاء الفيديو، "
                "لكن تعذر إرساله إلى Telegram.\n\n"

                "حاول مرة أخرى.",
            )

            return

        await query.edit_message_text(

            "🎉 تم إنشاء الفيديو وإرساله بنجاح!\n\n"

            "🤖 Wan 2.2 I2V 14B Lightning\n"

            f"⏱️ المدة: {duration:g} ثانية",

            reply_markup=main_menu(),
        )

        # تنظيف حالة المستخدم
        user_states.pop(
            user_id,
            None,
        )

    finally:

        # حذف الصورة المؤقتة
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
                    repr(error),
                )

        try:
            lock.release()
        except Exception:
            pass


# =========================================================
# الإعدادات
# =========================================================

async def show_settings(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = user_states.setdefault(
        user_id,
        {},
    )

    duration = state.get(
        "duration",
        DEFAULT_DURATION,
    )

    await query.edit_message_text(

        "⚙️ إعدادات الفيديو\n\n"

        "🤖 Wan 2.2 I2V 14B Lightning\n\n"

        f"⏱️ المدة الحالية: {duration:g} ثانية\n\n"

        "اختر المدة:",

        reply_markup=duration_menu(),
    )


# =========================================================
# تغيير المدة
# =========================================================

async def set_duration(
    update,
    context,
    duration,
):

    query = update.callback_query

    await query.answer(
        f"تم اختيار {duration:g} ثانية."
    )

    user_id = query.from_user.id

    state = user_states.setdefault(
        user_id,
        {},
    )

    state["duration"] = duration

    # إذا كان بانتظار صورة
    if state.get(
        "waiting_for_photo"
    ):

        await query.edit_message_text(

            "📷 أرسل الصورة الآن.\n\n"

            f"⏱️ المدة: {duration:g} ثانية",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="cancel_generation",
                    )
                ],

            ]),
        )

        return

    # إذا كانت هناك صورة وPrompt
    if state.get(
        "image_path"
    ):

        await query.edit_message_text(

            "⚙️ تم تغيير المدة.\n\n"

            f"⏱️ المدة الجديدة: {duration:g} ثانية\n\n"

            "اضغط «🎬 إنشاء الفيديو».",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🎬 إنشاء الفيديو",
                        callback_data="generate",
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⚙️ تغيير المدة",
                        callback_data="settings",
                    )
                ],

            ]),
        )

        return

    await query.edit_message_text(

        f"✅ تم اختيار {duration:g} ثانية.",

        reply_markup=main_menu(),
    )


# =========================================================
# زر الإلغاء
# =========================================================

async def cancel_generation(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = user_states.pop(
        user_id,
        None,
    )

    if state:

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

        reply_markup=main_menu(),
    )


# =========================================================
# Button Handler
# =========================================================

async def button_handler(
    update,
    context,
):

    query = update.callback_query

    data = query.data or ""

    # إنشاء
    if data == "new_video":

        await start_generation(
            update,
            context,
        )

        return

    # إعدادات
    if data == "settings":

        await show_settings(
            update,
            context,
        )

        return

    # مدد
    if data == "duration_5":

        await set_duration(
            update,
            context,
            5.0,
        )

        return

    if data == "duration_10":

        await set_duration(
            update,
            context,
            10.0,
        )

        return

    if data == "duration_15":

        await set_duration(
            update,
            context,
            15.0,
        )

        return

    if data == "duration_20":

        await set_duration(
            update,
            context,
            20.0,
        )

        return

    # إنشاء
    if data == "generate":

        await generate_video(
            update,
            context,
        )

        return

    # إلغاء
    if data == "cancel_generation":

        await cancel_generation(
            update,
            context,
        )

        return

    # مساعدة
    if data == "help":

        await query.answer()

        await query.edit_message_text(

            "ℹ️ Wan 2.2 I2V 14B Lightning\n\n"

            "📷 أرسل صورة.\n"
            "✍️ اكتب وصف الحركة.\n"
            "⏱️ اختر المدة.\n"
            "🎬 أنشئ الفيديو.\n\n"

            "المدة المتاحة في الـSpace "
            "تصل إلى 20.1 ثانية.\n\n"

            "البوت حالياً لا يحتوي على "
            "نظام دفع أو رصيد أو تجربة مجانية.",

            reply_markup=main_menu(),
        )

        return

    # الرئيسية
    if data == "back_main":

        await query.answer()

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu(),
        )

        return

    await query.answer(
        "الخيار غير معروف.",
        show_alert=True,
    )


# =========================================================
# Error Handler
# =========================================================

async def error_handler(
    update,
    context,
):

    print(
        "BOT ERROR:",
        repr(context.error),
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

    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    bot_app.add_error_handler(
        error_handler
    )

    print(
        "=============================================="
    )

    print(
        "Telegram Wan 2.2 Bot is starting..."
    )

    print(
        "Space:",
        HF_SPACE,
    )

    print(
        "=============================================="
    )

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    print(
        "Starting web server..."
    )

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True,
    )

    bot_thread.start()

    print(
        "Starting Flask..."
    )

    run_web()
