import os
import time
import sqlite3
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
# إعدادات
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

# معرف الأدمن الذي أرسلته
ADMIN_ID = 625548190

# موجود مسبقًا في Render
SHAM_CASH_NUMBER = os.environ.get(
    "SHAM_CASH_NUMBER",
    ""
)

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

DB_FILE = "bot_data.db"

DEFAULT_MODEL = "default"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "480p"
DEFAULT_AUDIO = False


# =========================================================
# الباقات
# عدّل الأسعار لاحقًا من هنا فقط
# =========================================================

PACKAGES = {
    "pack_5": {
        "name": "🟢 الباقة الصغيرة",
        "videos": 5,
        "price": 25000,
    },
    "pack_15": {
        "name": "🔵 الباقة المتوسطة",
        "videos": 15,
        "price": 60000,
    },
    "pack_50": {
        "name": "🟣 الباقة الكبيرة",
        "videos": 50,
        "price": 180000,
    },
}


# =========================================================
# Flask / Render
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
# قاعدة البيانات
# =========================================================

db_lock = threading.Lock()


def db_connect():
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0,
                created_at INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package_id TEXT,
                amount INTEGER,
                transaction_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                prompt TEXT,
                model TEXT,
                duration INTEGER,
                resolution TEXT,
                audio INTEGER,
                status TEXT,
                created_at INTEGER
            )
        """)

        connection.commit()
        connection.close()


def ensure_user(user):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO users
            (user_id, username, first_name, balance, created_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                int(time.time()),
            )
        )

        connection.commit()
        connection.close()


def get_balance(user_id):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (user_id,)
        )

        row = cursor.fetchone()
        connection.close()

        if not row:
            return 0

        return int(row["balance"])


def add_balance(user_id, amount):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id=?
            """,
            (amount, user_id)
        )

        connection.commit()
        connection.close()


def remove_balance(user_id, amount):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id=?
            AND balance >= ?
            """,
            (amount, user_id, amount)
        )

        changed = cursor.rowcount

        connection.commit()
        connection.close()

        return changed == 1


def create_payment(
    user_id,
    package_id,
    amount,
    transaction_id
):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO payments
            (
                user_id,
                package_id,
                amount,
                transaction_id,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                user_id,
                package_id,
                amount,
                transaction_id,
                int(time.time()),
            )
        )

        payment_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return payment_id


def get_payment(payment_id):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT *
            FROM payments
            WHERE id=?
            """,
            (payment_id,)
        )

        row = cursor.fetchone()
        connection.close()

        return row


def approve_payment(payment_id):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT *
            FROM payments
            WHERE id=?
            """,
            (payment_id,)
        )

        payment = cursor.fetchone()

        if not payment:
            connection.close()
            return None, "not_found"

        if payment["status"] != "pending":
            connection.close()
            return payment, "already_processed"

        package = PACKAGES.get(
            payment["package_id"]
        )

        if not package:
            connection.close()
            return payment, "package_not_found"

        cursor.execute(
            """
            UPDATE payments
            SET status='approved'
            WHERE id=?
            AND status='pending'
            """,
            (payment_id,)
        )

        cursor.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id=?
            """,
            (
                package["videos"],
                payment["user_id"],
            )
        )

        connection.commit()
        connection.close()

        return payment, "approved"


def reject_payment(payment_id):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT *
            FROM payments
            WHERE id=?
            """,
            (payment_id,)
        )

        payment = cursor.fetchone()

        if not payment:
            connection.close()
            return None, "not_found"

        if payment["status"] != "pending":
            connection.close()
            return payment, "already_processed"

        cursor.execute(
            """
            UPDATE payments
            SET status='rejected'
            WHERE id=?
            """,
            (payment_id,)
        )

        connection.commit()
        connection.close()

        return payment, "rejected"


def create_video_job(
    user_id,
    prompt,
    model,
    duration,
    resolution,
    audio
):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO video_jobs
            (
                user_id,
                prompt,
                model,
                duration,
                resolution,
                audio,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'processing', ?)
            """,
            (
                user_id,
                prompt,
                model,
                duration,
                resolution,
                int(audio),
                int(time.time()),
            )
        )

        job_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return job_id


def finish_video_job(job_id, status):
    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE video_jobs
            SET status=?
            WHERE id=?
            """,
            (status, job_id)
        )

        connection.commit()
        connection.close()


# =========================================================
# Magic Hour
# =========================================================

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
                    "extension": extension,
                }
            ]
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return (
        data["items"][0]["upload_url"],
        data["items"][0]["file_path"],
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
    audio,
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
                "Authorization":
                    f"Bearer {MAGIC_HOUR_API_KEY}"
            },
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        status = data.get("status")

        print("VIDEO STATUS:", status)

        if status == "complete":

            downloads = data.get(
                "downloads",
                []
            )

            if downloads:
                return downloads[0]["url"], data

            return None, data

        if status in [
            "error",
            "failed",
            "canceled",
        ]:
            print("VIDEO ERROR:", data)
            return None, data

        time.sleep(10)

    return None, None


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
                "💰 رصيدي",
                callback_data="balance"
            ),
            InlineKeyboardButton(
                "💳 شراء رصيد",
                callback_data="buy"
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
    ]

    return InlineKeyboardMarkup(keyboard)


def settings_menu(state):
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

    audio_text = (
        "🔊 الصوت: تشغيل"
        if audio
        else
        "🔇 الصوت: إيقاف"
    )

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
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def model_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ الافتراضي",
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
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def duration_menu(model):
    if model == "kling-2.6":
        durations = [5, 10]

    elif model == "kling-3.0":
        durations = [5, 8, 10, 15]

    elif model == "wan-2.2":
        durations = [5, 8, 10, 15]

    else:
        durations = [5, 10, 15]

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
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def packages_menu():
    keyboard = []

    for package_id, package in PACKAGES.items():

        keyboard.append([
            InlineKeyboardButton(
                f"{package['name']} — "
                f"{package['videos']} فيديو — "
                f"{package['price']:,} ل.س",
                callback_data=f"package_{package_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back_main"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# أوامر المستخدم
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    ensure_user(update.effective_user)

    await update.message.reply_text(
        "مرحباً 👋\n\n"
        "🎬 أهلاً بك في بوت تحويل الصور إلى فيديو "
        "بالذكاء الاصطناعي.\n\n"
        "💰 يمكنك شراء رصيد ثم إنشاء الفيديوهات.\n\n"
        f"رصيدك الحالي: "
        f"{get_balance(update.effective_user.id)} فيديو",
        reply_markup=main_menu()
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=main_menu()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ℹ️ طريقة الاستخدام:\n\n"
        "1️⃣ اشترِ رصيدًا.\n"
        "2️⃣ اضغط إنشاء فيديو.\n"
        "3️⃣ أرسل الصورة.\n"
        "4️⃣ اكتب وصف الحركة.\n"
        "5️⃣ اضغط إنشاء الفيديو.\n\n"
        "🎬 يتم خصم فيديو واحد فقط عند نجاح الإنشاء.\n\n"
        "إذا فشل إنشاء الفيديو، لا يتم خصم الرصيد.",
        reply_markup=main_menu()
    )


# =========================================================
# الصور
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    if get_balance(user_id) <= 0:

        await update.message.reply_text(
            "💰 لا يوجد لديك رصيد كافٍ.\n\n"
            "اضغط 💳 شراء رصيد للحصول على باقة.",
            reply_markup=main_menu()
        )

        return

    try:

        photo = update.message.photo[-1]

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        context.user_data["image"] = bytes(
            image_bytes
        )

        await update.message.reply_text(
            "✅ وصلت الصورة!\n\n"
            "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"
            "مثال:\n"
            "اجعل الشخص يبتسم ويحرك رأسه ببطء، "
            "مع حركة كاميرا سينمائية خفيفة، "
            "وحافظ على ملامح الوجه كما هي."
        )

    except Exception as error:

        print("PHOTO ERROR:", error)

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


# =========================================================
# النص / وصف الحركة
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    ensure_user(update.effective_user)

    if "image" not in context.user_data:

        await update.message.reply_text(
            "📷 أرسل صورة أولاً.",
            reply_markup=main_menu()
        )

        return

    prompt = update.message.text.strip()

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة."
        )

        return

    context.user_data["prompt"] = prompt

    keyboard = [
        [
            InlineKeyboardButton(
                "⚙️ الإعدادات",
                callback_data="settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 إنشاء الفيديو",
                callback_data="generate"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_generation"
            )
        ],
    ]

    await update.message.reply_text(
        "📝 تم استلام الوصف:\n\n"
        f"{prompt}\n\n"
        f"💰 رصيدك: "
        f"{get_balance(update.effective_user.id)} فيديو",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
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

    ensure_user(query.from_user)

    if get_balance(user_id) <= 0:

        await query.edit_message_text(
            "💰 لا يوجد رصيد كافٍ.\n\n"
            "اشترِ رصيدًا أولاً.",
            reply_markup=main_menu()
        )

        return

    image_bytes = context.user_data.get(
        "image"
    )

    prompt = context.user_data.get(
        "prompt"
    )

    if not image_bytes or not prompt:

        await query.edit_message_text(
            "❌ يجب إرسال صورة وكتابة وصف الحركة أولاً.",
            reply_markup=main_menu()
        )

        return

    state = context.user_data

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

    await query.edit_message_text(
        "⏳ جاري إنشاء الفيديو...\n\n"
        "🎬 انتظر قليلًا."
    )

    job_id = create_video_job(
        user_id,
        prompt,
        model,
        duration,
        resolution,
        audio
    )

    try:

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
            audio=audio,
        )

        video_id = video_data["id"]

        print("VIDEO ID:", video_id)

        # الانتظار
        video_url, final_data = wait_for_video(
            video_id
        )

        if not video_url:

            finish_video_job(
                job_id,
                "failed"
            )

            await query.edit_message_text(
                "❌ لم يتم إنشاء الفيديو.\n\n"
                "لم يتم خصم أي رصيد من حسابك.",
                reply_markup=main_menu()
            )

            return

        # تحميل الفيديو
        video_response = requests.get(
            video_url,
            timeout=180
        )

        video_response.raise_for_status()

        # الخصم فقط بعد نجاح الفيديو
        removed = remove_balance(
            user_id,
            1
        )

        if not removed:

            finish_video_job(
                job_id,
                "balance_error"
            )

            await query.edit_message_text(
                "⚠️ تم إنشاء الفيديو، لكن حدثت "
                "مشكلة في خصم الرصيد.\n"
                "تواصل مع الإدارة."
            )

            return

        finish_video_job(
            job_id,
            "complete"
        )

        await context.bot.send_video(
            chat_id=user_id,
            video=video_response.content,
            caption=(
                "🎬 تم إنشاء الفيديو بنجاح!\n\n"
                f"💰 رصيدك المتبقي: "
                f"{get_balance(user_id)} فيديو"
            )
        )

        await query.edit_message_text(
            "✅ تم إنشاء الفيديو بنجاح! 🎬\n\n"
            "يمكنك إرسال صورة جديدة.",
            reply_markup=main_menu()
        )

        context.user_data.pop(
            "image",
            None
        )

        context.user_data.pop(
            "prompt",
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

        finish_video_job(
            job_id,
            "api_error"
        )

        await query.edit_message_text(
            "❌ Magic Hour رفض الطلب.\n\n"
            "لم يتم خصم رصيدك.",
            reply_markup=main_menu()
        )

    except Exception as error:

        print(
            "GENERATION ERROR:",
            error
        )

        finish_video_job(
            job_id,
            "error"
        )

        await query.edit_message_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "لم يتم خصم رصيدك.",
            reply_markup=main_menu()
        )


# =========================================================
# الدفع
# =========================================================

async def buy_menu_handler(
    query
):

    await query.edit_message_text(
        "💳 شراء رصيد\n\n"
        "اختر الباقة المناسبة لك:",
        reply_markup=packages_menu()
    )


async def package_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    package_id
):

    query = update.callback_query

    package = PACKAGES.get(
        package_id
    )

    if not package:

        await query.edit_message_text(
            "❌ الباقة غير موجودة.",
            reply_markup=main_menu()
        )

        return

    context.user_data[
        "selected_package"
    ] = package_id

    await query.edit_message_text(
        "💳 طلب شراء رصيد\n\n"
        f"{package['name']}\n"
        f"🎬 عدد الفيديوهات: {package['videos']}\n"
        f"💰 السعر: {package['price']:,} ل.س\n\n"
        "📱 حوّل المبلغ إلى حساب شام كاش:\n\n"
        f"{SHAM_CASH_NUMBER}\n\n"
        "بعد التحويل اضغط الزر بالأسفل "
        "وأرسل رقم العملية.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ أرسلت المبلغ",
                    callback_data="payment_sent"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data="buy"
                )
            ],
        ])
    )


async def payment_sent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    context.user_data[
        "waiting_transaction_id"
    ] = True

    await query.edit_message_text(
        "🧾 أرسل الآن رقم العملية/رقم الحوالة "
        "الذي ظهر لك بعد تحويل المبلغ."
    )


async def handle_transaction_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "waiting_transaction_id"
    ):
        return False

    transaction_id = update.message.text.strip()

    package_id = context.user_data.get(
        "selected_package"
    )

    package = PACKAGES.get(
        package_id
    )

    if not package:

        await update.message.reply_text(
            "❌ انتهت عملية الشراء. "
            "ابدأ من جديد.",
            reply_markup=main_menu()
        )

        context.user_data.pop(
            "waiting_transaction_id",
            None
        )

        return True

    payment_id = create_payment(
        update.effective_user.id,
        package_id,
        package["price"],
        transaction_id
    )

    context.user_data.pop(
        "waiting_transaction_id",
        None
    )

    await update.message.reply_text(
        "✅ تم إرسال طلب الدفع للإدارة.\n\n"
        "⏳ سيتم إضافة الرصيد بعد التحقق من الحوالة.",
        reply_markup=main_menu()
    )

    # إشعار الأدمن
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ قبول",
                callback_data=f"approve_{payment_id}"
            ),
            InlineKeyboardButton(
                "❌ رفض",
                callback_data=f"reject_{payment_id}"
            ),
        ]
    ])

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "💳 طلب دفع جديد\n\n"
                f"🆔 الطلب: #{payment_id}\n"
                f"👤 المستخدم: "
                f"{update.effective_user.id}\n"
                f"👤 الاسم: "
                f"{update.effective_user.first_name}\n"
                f"📦 الباقة: "
                f"{package['name']}\n"
                f"🎬 الفيديوهات: "
                f"{package['videos']}\n"
                f"💰 المبلغ: "
                f"{package['price']:,} ل.س\n"
                f"🧾 رقم العملية: "
                f"{transaction_id}"
            ),
            reply_markup=keyboard
        )

    except Exception as error:
        print(
            "ADMIN NOTIFICATION ERROR:",
            error
        )

    return True


# =========================================================
# معالجة الأزرار
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    ensure_user(query.from_user)

    data = query.data

    # -------------------------
    # إنشاء فيديو
    # -------------------------

    if data == "new_video":

        if get_balance(user_id) <= 0:

            await query.edit_message_text(
                "💰 رصيدك صفر.\n\n"
                "اشترِ رصيدًا أولًا.",
                reply_markup=main_menu()
            )

            return

        context.user_data[
            "waiting_for_photo"
        ] = True

        await query.edit_message_text(
            "📷 أرسل الصورة التي تريد "
            "تحويلها إلى فيديو."
        )

        return

    # -------------------------
    # الرصيد
    # -------------------------

    if data == "balance":

        balance = get_balance(
            user_id
        )

        await query.edit_message_text(
            "💰 رصيدك الحالي:\n\n"
            f"🎬 {balance} فيديو",
            reply_markup=main_menu()
        )

        return

    # -------------------------
    # شراء
    # -------------------------

    if data == "buy":

        await buy_menu_handler(
            query
        )

        return

    if data.startswith("package_"):

        package_id = data.replace(
            "package_",
            ""
        )

        await package_selected(
            update,
            context,
            package_id
        )

        return

    if data == "payment_sent":

        await payment_sent(
            update,
            context
        )

        return

    # -------------------------
    # Admin
    # -------------------------

    if data.startswith("approve_"):

        if user_id != ADMIN_ID:

            await query.answer(
                "غير مصرح لك.",
                show_alert=True
            )

            return

        payment_id = int(
            data.replace(
                "approve_",
                ""
            )
        )

        payment, result = approve_payment(
            payment_id
        )

        if result != "approved":

            await query.edit_message_text(
                "⚠️ تم التعامل مع هذا الطلب "
                "مسبقًا أو أنه غير موجود."
            )

            return

        package = PACKAGES.get(
            payment["package_id"]
        )

        await query.edit_message_text(
            "✅ تم قبول طلب الدفع.\n\n"
            f"الطلب: #{payment_id}\n"
            f"المستخدم: {payment['user_id']}\n"
            f"الرصيد المضاف: "
            f"{package['videos']} فيديو"
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "🎉 تم تأكيد الدفع!\n\n"
                    f"تمت إضافة "
                    f"{package['videos']} فيديو "
                    "إلى رصيدك.\n\n"
                    f"💰 رصيدك الحالي: "
                    f"{get_balance(payment['user_id'])} فيديو"
                ),
                reply_markup=main_menu()
            )

        except Exception as error:

            print(
                "USER NOTIFICATION ERROR:",
                error
            )

        return

    if data.startswith("reject_"):

        if user_id != ADMIN_ID:

            await query.answer(
                "غير مصرح لك.",
                show_alert=True
            )

            return

        payment_id = int(
            data.replace(
                "reject_",
                ""
            )
        )

        payment, result = reject_payment(
            payment_id
        )

        if result != "rejected":

            await query.edit_message_text(
                "⚠️ تم التعامل مع هذا الطلب "
                "مسبقًا أو أنه غير موجود."
            )

            return

        await query.edit_message_text(
            "❌ تم رفض طلب الدفع.\n\n"
            f"الطلب: #{payment_id}"
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "❌ تم رفض طلب الدفع.\n\n"
                    "إذا كنت متأكدًا من صحة التحويل، "
                    "تواصل مع الإدارة."
                ),
                reply_markup=main_menu()
            )

        except Exception as error:

            print(
                "USER NOTIFICATION ERROR:",
                error
            )

        return

    # -------------------------
    # الإعدادات
    # -------------------------

    if data == "settings":

        await query.edit_message_text(
            "⚙️ إعدادات الفيديو:\n\n"
            "اختر الإعداد الذي تريد تغييره.",
            reply_markup=settings_menu(
                context.user_data
            )
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
                context.user_data.get(
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

        context.user_data[
            "audio"
        ] = not context.user_data.get(
            "audio",
            DEFAULT_AUDIO
        )

        await query.edit_message_text(
            "⚙️ تم تغيير الصوت.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "model_default":

        context.user_data[
            "model"
        ] = "default"

        context.user_data[
            "audio"
        ] = False

        await query.edit_message_text(
            "✅ تم اختيار النموذج الافتراضي.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "model_ltx":

        context.user_data[
            "model"
        ] = "ltx-2.3"

        await query.edit_message_text(
            "⚡ تم اختيار LTX 2.3.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "model_kling26":

        context.user_data[
            "model"
        ] = "kling-2.6"

        context.user_data[
            "audio"
        ] = False

        await query.edit_message_text(
            "🎥 تم اختيار Kling 2.6.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "model_kling30":

        context.user_data[
            "model"
        ] = "kling-3.0"

        await query.edit_message_text(
            "🎬 تم اختيار Kling 3.0.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "model_wan":

        context.user_data[
            "model"
        ] = "wan-2.2"

        await query.edit_message_text(
            "🌊 تم اختيار Wan 2.2.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data.startswith("duration_"):

        duration = int(
            data.replace(
                "duration_",
                ""
            )
        )

        context.user_data[
            "duration"
        ] = duration

        await query.edit_message_text(
            f"✅ المدة: {duration} ثواني.",
            reply_markup=settings_menu(
                context.user_data
            )
        )

        return

    if data == "resolution_480":

        context.user_data[
            "resolution"
        ] = "480p"

    elif data == "resolution_720":

        context.user_data[
            "resolution"
        ] = "720p"

    elif data == "resolution_1080":

        context.user_data[
            "resolution"
        ] = "1080p"

    elif data == "generate":

        await generate_video(
            update,
            context
        )

        return

    elif data == "cancel_generation":

        context.user_data.clear()

        await query.edit_message_text(
            "❌ تم إلغاء العملية.",
            reply_markup=main_menu()
        )

        return

    elif data == "help":

        await query.edit_message_text(
            "ℹ️ أرسل صورة ثم اكتب وصف الحركة.\n\n"
            "🎬 كل فيديو ناجح يخصم فيديو واحد من رصيدك.\n"
            "❌ الفيديو الفاشل لا يخصم الرصيد.",
            reply_markup=main_menu()
        )

        return

    elif data == "back_main":

        await query.edit_message_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_menu()
        )

        return

    else:
        return

    await query.edit_message_text(
        f"✅ تم اختيار الدقة "
        f"{context.user_data['resolution']}.",
        reply_markup=settings_menu(
            context.user_data
        )
    )


# =========================================================
# إحصائيات الأدمن
# =========================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ غير مصرح لك."
        )

        return

    with db_lock:
        connection = db_connect()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT COUNT(*) AS count FROM users"
        )

        users = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM video_jobs
            WHERE status='complete'
            """
        )

        videos = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM payments
            WHERE status='approved'
            """
        )

        payments = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM payments
            WHERE status='approved'
            """
        )

        revenue = cursor.fetchone()["total"]

        connection.close()

    await update.message.reply_text(
        "👑 لوحة الإدارة\n\n"
        f"👥 المستخدمون: {users}\n"
        f"🎬 الفيديوهات الناجحة: {videos}\n"
        f"💳 الدفعات المقبولة: {payments}\n"
        f"💰 إجمالي المبيعات: {revenue:,} ل.س"
    )


async def add_balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ غير مصرح لك."
        )

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/addbalance USER_ID AMOUNT"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

        if amount <= 0:
            raise ValueError

        add_balance(
            user_id,
            amount
        )

        await update.message.reply_text(
            "✅ تمت إضافة الرصيد.\n\n"
            f"👤 المستخدم: {user_id}\n"
            f"🎬 الرصيد المضاف: {amount}"
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎁 تمت إضافة رصيد إلى حسابك.\n\n"
                    f"🎬 الرصيد المضاف: {amount}\n"
                    f"💰 رصيدك الحالي: "
                    f"{get_balance(user_id)} فيديو"
                )
            )

        except Exception as error:

            print(
                "BALANCE USER MESSAGE ERROR:",
                error
            )

    except Exception:

        await update.message.reply_text(
            "❌ البيانات غير صحيحة."
        )


# =========================================================
# تشغيل البوت
# =========================================================

def run_bot():

    init_db()

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
        CommandHandler(
            "admin",
            admin_command
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "addbalance",
            add_balance_command
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
            handle_transaction_or_prompt
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


# =========================================================
# النصوص
# =========================================================

async def handle_transaction_or_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # إذا كان المستخدم ينتظر رقم عملية الدفع
    if context.user_data.get(
        "waiting_transaction_id"
    ):

        await handle_transaction_id(
            update,
            context
        )

        return

    # وإلا اعتبر الرسالة وصف فيديو
    await handle_text(
        update,
        context
    )


# =========================================================
# Start
# =========================================================

if __name__ == "__main__":

    init_db()

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
