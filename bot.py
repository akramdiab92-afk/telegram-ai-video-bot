import os
import time
import threading
import sqlite3
import requests

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CopyTextButton,
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
# الإعدادات
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
MAGIC_HOUR_API_KEY = os.environ["MAGIC_HOUR_API_KEY"]

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

# Telegram ID الخاص بك
ADMIN_ID = 625548190

# حساب شام كاش
SHAM_CASH_NUMBER = "55c04a684471d4b5f504f0e6e2ca7384"

DB_FILE = "bot_data.db"

app_web = Flask(__name__)

# حالات المستخدمين المؤقتة
user_states = {}

# قفل إنشاء الفيديو لكل مستخدم
generation_locks = {}

# قفل عمليات الدفع الحساسة
payment_lock = threading.Lock()

# قفل عام لإنشاء/تعديل المستخدمين
database_lock = threading.Lock()


# =========================================================
# إعدادات التجربة المجانية
# =========================================================

FREE_TRIAL_DURATION = 3
FREE_TRIAL_RESOLUTION = "480p"


# =========================================================
# الباقات
# =========================================================

PACKAGES = {
    "pack_3": {
        "name": "🟢 باقة التجربة",
        "videos": 3,
        "price": 10000,
    },

    "pack_10": {
        "name": "🔵 الباقة الأساسية",
        "videos": 10,
        "price": 25000,
    },

    "pack_25": {
        "name": "🟣 الباقة المميزة",
        "videos": 25,
        "price": 55000,
    },

    "pack_50": {
        "name": "🔥 VIP",
        "videos": 50,
        "price": 100000,
    },
}


# =========================================================
# قاعدة البيانات
# =========================================================

def db():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_db():

    with database_lock:

        connection = db()

        cursor = connection.cursor()

        # المستخدمون
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # إضافة العمود إذا كانت قاعدة البيانات القديمة لا تحتوي عليه
        cursor.execute("""
            PRAGMA table_info(users)
        """)

        columns = [
            row["name"]
            for row in cursor.fetchall()
        ]

        if "trial_used" not in columns:

            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN trial_used INTEGER DEFAULT 0
            """)

        # المدفوعات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package_id TEXT,
                package_name TEXT,
                videos INTEGER,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # سجل عمليات إنشاء الفيديو
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_type TEXT,
                duration INTEGER,
                resolution TEXT,
                prompt TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.commit()

        connection.close()


def ensure_user(user):

    if not user:
        return

    with database_lock:

        connection = db()

        cursor = connection.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO users
            (
                user_id,
                username,
                first_name,
                balance,
                trial_used
            )
            VALUES (?, ?, ?, 0, 0)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
        ))

        cursor.execute("""
            UPDATE users
            SET
                username = ?,
                first_name = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "",
            user.id,
        ))

        connection.commit()

        connection.close()


def user_exists(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT 1
        FROM users
        WHERE user_id = ?
        LIMIT 1
    """, (
        user_id,
    ))

    row = cursor.fetchone()

    connection.close()

    return row is not None


def get_balance(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT balance
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cursor.fetchone()

    connection.close()

    if not row:
        return 0

    return int(row["balance"] or 0)


def add_balance(user_id, amount):

    if amount <= 0:
        return False

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    """, (
        amount,
        user_id,
    ))

    success = cursor.rowcount > 0

    connection.commit()

    connection.close()

    return success


def remove_balance(user_id, amount):

    if amount <= 0:
        return False

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET balance = balance - ?
        WHERE user_id = ?
        AND balance >= ?
    """, (
        amount,
        user_id,
        amount,
    ))

    success = cursor.rowcount > 0

    connection.commit()

    connection.close()

    return success


def has_free_trial(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT trial_used
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cursor.fetchone()

    connection.close()

    if not row:
        return False

    return int(row["trial_used"] or 0) == 0


def mark_trial_used(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET trial_used = 1
        WHERE user_id = ?
        AND trial_used = 0
    """, (
        user_id,
    ))

    changed = cursor.rowcount > 0

    connection.commit()

    connection.close()

    return changed


def reset_trial(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET trial_used = 0
        WHERE user_id = ?
    """, (
        user_id,
    ))

    changed = cursor.rowcount > 0

    connection.commit()

    connection.close()

    return changed


def get_generation_lock(user_id):

    if user_id not in generation_locks:

        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


def save_generation(
    user_id,
    video_type,
    duration,
    resolution,
    prompt,
    status
):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO generations
        (
            user_id,
            video_type,
            duration,
            resolution,
            prompt,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        video_type,
        duration,
        resolution,
        prompt,
        status,
    ))

    connection.commit()

    connection.close()


# =========================================================
# Render
# =========================================================

@app_web.route("/")
def home():

    return "Telegram AI Video Bot is running!"


@app_web.route("/health")
def health():

    return "OK"


def run_web():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app_web.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )


# =========================================================
# Magic Hour
# =========================================================

def magic_headers():

    return {
        "Authorization":
            f"Bearer {MAGIC_HOUR_API_KEY}",

        "Content-Type":
            "application/json",
    }


def create_upload_url(extension="jpg"):

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

    items = data.get(
        "items",
        []
    )

    if not items:

        raise RuntimeError(
            f"Magic Hour لم يعطِ رابط رفع الصورة: {data}"
        )

    upload_url = items[0].get(
        "upload_url"
    )

    file_path = items[0].get(
        "file_path"
    )

    if not upload_url or not file_path:

        raise RuntimeError(
            f"بيانات رفع الصورة غير مكتملة: {data}"
        )

    return (
        upload_url,
        file_path
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


def create_video(
    file_path,
    prompt,
    duration=5,
    resolution="480p"
):

    payload = {

        "assets": {
            "image_file_path":
                file_path
        },

        "end_seconds":
            duration,

        "name":
            "Telegram AI Video",

        "resolution":
            resolution,

        "style": {
            "prompt":
                prompt
        }
    }

    response = requests.post(
        f"{MAGIC_HOUR_BASE}/image-to-video",

        headers=magic_headers(),

        json=payload,

        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    video_id = data.get(
        "id"
    )

    if not video_id:

        raise RuntimeError(
            f"Magic Hour لم يرجع video ID: {data}"
        )

    return data


def wait_for_video(video_id):

    # 90 × 10 ثواني = حوالي 15 دقيقة

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

        status = data.get(
            "status"
        )

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

                video_url = downloads[0].get(
                    "url"
                )

                if video_url:

                    return (
                        video_url,
                        data
                    )

            return (
                None,
                data
            )

        if status in [
            "error",
            "failed",
            "canceled"
        ]:

            print(
                "VIDEO ERROR:",
                data
            )

            return (
                None,
                data
            )

        time.sleep(10)

    return (
        None,
        None
    )


# =========================================================
# القائمة الرئيسية
# =========================================================

def main_menu(user_id):

    balance = get_balance(
        user_id
    )

    trial_available = has_free_trial(
        user_id
    )

    keyboard = []

    # التجربة المجانية
    if trial_available:

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🎁 تجربة مجانية — 3 ثواني",
                    callback_data="free_trial"
                )
            ]
        )

    else:

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🎬 إنشاء فيديو",
                    callback_data="new_video"
                )
            ]
        )

    keyboard.extend([

        [
            InlineKeyboardButton(
                "💰 شراء رصيد",
                callback_data="buy"
            ),

            InlineKeyboardButton(
                "💳 رصيدي",
                callback_data="balance"
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
                "ℹ️ المساعدة",
                callback_data="help"
            )
        ],

    ])

    if user_id == ADMIN_ID:

        keyboard.append(
            [
                InlineKeyboardButton(
                    "👑 لوحة الإدارة",
                    callback_data="admin"
                )
            ]
        )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# قائمة الباقات
# =========================================================

def packages_menu():

    keyboard = []

    for package_id, package in PACKAGES.items():

        keyboard.append(
            [
                InlineKeyboardButton(

                    f"{package['name']} — "
                    f"{package['videos']} فيديو — "
                    f"{package['price']:,} ل.س",

                    callback_data=
                    f"package_{package_id}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# إعدادات الفيديو
# =========================================================

def settings_menu(state):

    duration = state.get(
        "duration",
        5
    )

    resolution = state.get(
        "resolution",
        "480p"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                f"⏱️ المدة: {duration} ث",
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
                "⬅️ رجوع",
                callback_data="back_main"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def duration_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "5 ثواني ⭐",
                callback_data="duration_5"
            )
        ],

        [
            InlineKeyboardButton(
                "10 ثواني",
                callback_data="duration_10"
            )
        ],

        [
            InlineKeyboardButton(
                "15 ثانية",
                callback_data="duration_15"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="settings"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


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

    user = update.effective_user

    ensure_user(
        user
    )

    user_states.pop(
        user.id,
        None
    )

    balance = get_balance(
        user.id
    )

    if has_free_trial(user.id):

        trial_text = (
            "🎁 لديك تجربة مجانية!\n"
            "يمكنك إنشاء أول فيديو لك "
            "مجانًا لمدة 3 ثوانٍ.\n\n"
        )

    else:

        trial_text = (
            "🎬 التجربة المجانية مستخدمة.\n"
            "يمكنك متابعة إنشاء الفيديوهات "
            "باستخدام رصيدك.\n\n"
        )

    await update.message.reply_text(

        "مرحباً 👋\n\n"

        "🎬 أهلاً بك في بوت تحويل الصور "
        "إلى فيديو بالذكاء الاصطناعي.\n\n"

        f"{trial_text}"

        f"💰 رصيدك الحالي: "
        f"{balance} فيديو\n\n"

        "📷 اختر من القائمة للبدء.",

        reply_markup=main_menu(
            user.id
        )
    )


# =========================================================
# /cancel
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

        "❌ تم إلغاء العملية.",

        reply_markup=main_menu(
            user_id
        )
    )


# =========================================================
# /help
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "🎁 أول مرة:\n"
        "تحصل على فيديو مجاني لمدة 3 ثوانٍ.\n\n"

        "🎬 بعد التجربة:\n"
        "اشترِ رصيدًا ثم أرسل صورة واكتب "
        "وصف الحركة.\n\n"

        "⚙️ يمكنك اختيار:\n"
        "• مدة 5 أو 10 أو 15 ثانية\n"
        "• دقة 480p أو 720p أو 1080p\n\n"

        "📝 مثال للوصف:\n"
        "اجعل الشخص يبتسم ويحرك رأسه "
        "بشكل طبيعي مع حركة كاميرا "
        "سينمائية خفيفة، مع الحفاظ "
        "على ملامح الوجه.",

        reply_markup=main_menu(
            user_id
        )
    )


# =========================================================
# شراء الرصيد
# =========================================================

async def show_buy(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        "💰 اختر الباقة التي تريد شراءها:\n\n"

        "🎬 كل فيديو يتم خصم فيديو واحد "
        "من رصيدك بعد نجاح الإنشاء.\n\n"

        "بعد اختيار الباقة ستظهر لك "
        "طريقة الدفع عبر شام كاش.",

        reply_markup=packages_menu()
    )


async def create_payment(
    update,
    context,
    package_id
):

    query = update.callback_query

    user_id = query.from_user.id

    package = PACKAGES.get(
        package_id
    )

    if not package:

        await query.answer(
            "الباقة غير موجودة.",
            show_alert=True
        )

        return

    ensure_user(
        query.from_user
    )

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO payments
        (
            user_id,
            package_id,
            package_name,
            videos,
            price,
            status
        )
        VALUES (?, ?, ?, ?, ?, 'pending')
        """,
        (
            user_id,
            package_id,
            package["name"],
            package["videos"],
            package["price"],
        )
    )

    payment_id = cursor.lastrowid

    connection.commit()

    connection.close()

    await query.answer()

    keyboard = [

        [
            InlineKeyboardButton(
                "📋 نسخ حساب شام كاش",

                copy_text=CopyTextButton(
                    text=SHAM_CASH_NUMBER
                )
            )
        ],

        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="back_main"
            )
        ]
    ]

    await query.edit_message_text(

        f"🧾 طلب شراء رقم #{payment_id}\n\n"

        f"📦 {package['name']}\n"

        f"🎬 الرصيد: "
        f"{package['videos']} فيديو\n"

        f"💰 السعر: "
        f"{package['price']:,} ل.س\n\n"

        "💳 طريقة الدفع:\n"
        "📱 شام كاش\n\n"

        "🔢 حساب شام كاش:\n\n"

        f"`{SHAM_CASH_NUMBER}`\n\n"

        "اضغط الزر بالأسفل لنسخ الحساب مباشرة.\n\n"

        "📸 بعد التحويل أرسل صورة إثبات الدفع "
        "هنا في البوت.\n\n"

        "⚠️ سيتم إضافة الرصيد بعد تأكيد الدفع.",

        parse_mode="Markdown",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )

    user_states[user_id] = {

        "waiting_payment_proof":
            True,

        "payment_id":
            payment_id,

    }


# =========================================================
# إثبات الدفع
# =========================================================

async def handle_payment_proof(
    update,
    context
):

    user_id = update.effective_user.id

    state = user_states.get(
        user_id,
        {}
    )

    if not state.get(
        "waiting_payment_proof"
    ):

        return False

    payment_id = state.get(
        "payment_id"
    )

    if not payment_id:

        return False

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM payments
        WHERE id = ?
        AND user_id = ?
        """,
        (
            payment_id,
            user_id
        )
    )

    payment = cursor.fetchone()

    connection.close()

    if not payment:

        await update.message.reply_text(
            "❌ لم يتم العثور على طلب الدفع."
        )

        user_states.pop(
            user_id,
            None
        )

        return True

    if payment["status"] != "pending":

        await update.message.reply_text(
            "⚠️ هذا الطلب تمت معالجته مسبقاً."
        )

        user_states.pop(
            user_id,
            None
        )

        return True

    try:

        # إرسال صورة الإثبات للإدارة
        await update.message.forward(
            chat_id=ADMIN_ID
        )

        # إرسال بيانات الطلب
        await context.bot.send_message(

            chat_id=ADMIN_ID,

            text=(

                "💰 طلب دفع جديد\n\n"

                f"🧾 رقم الطلب: "
                f"#{payment_id}\n"

                f"👤 المستخدم: "
                f"{user_id}\n"

                f"📦 الباقة: "
                f"{payment['package_name']}\n"

                f"🎬 الفيديوهات: "
                f"{payment['videos']}\n"

                f"💰 السعر: "
                f"{payment['price']:,} ل.س\n\n"

                "اختر الإجراء:"
            ),

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "✅ تأكيد الدفع",
                        callback_data=
                        f"approve_{payment_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "❌ رفض",
                        callback_data=
                        f"reject_{payment_id}"
                    )
                ]

            ])
        )

        await update.message.reply_text(

            "✅ تم إرسال إثبات الدفع للإدارة.\n\n"

            "⏳ سيتم مراجعة التحويل "
            "وإضافة الرصيد بعد التأكيد."
        )

        user_states.pop(
            user_id,
            None
        )

        return True

    except Exception as error:

        print(
            "PAYMENT PROOF ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إرسال إثبات الدفع."
        )

        return True


# =========================================================
# تأكيد الدفع
# =========================================================

async def approve_payment(
    update,
    context,
    payment_id
):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "غير مسموح.",
            show_alert=True
        )

        return

    with payment_lock:

        connection = db()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT *
            FROM payments
            WHERE id = ?
            """,
            (payment_id,)
        )

        payment = cursor.fetchone()

        if not payment:

            connection.close()

            await query.answer(
                "الطلب غير موجود.",
                show_alert=True
            )

            return

        if payment["status"] != "pending":

            connection.close()

            await query.answer(
                "تم التعامل مع هذا الطلب مسبقاً.",
                show_alert=True
            )

            return

        cursor.execute(
            """
            UPDATE payments
            SET status = 'approved'
            WHERE id = ?
            AND status = 'pending'
            """,
            (payment_id,)
        )

        if cursor.rowcount != 1:

            connection.close()

            await query.answer(
                "تم التعامل مع الطلب مسبقاً.",
                show_alert=True
            )

            return

        cursor.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                payment["videos"],
                payment["user_id"]
            )
        )

        connection.commit()

        connection.close()

    new_balance = get_balance(
        payment["user_id"]
    )

    await query.answer(
        "تمت إضافة الرصيد.",
        show_alert=True
    )

    await query.edit_message_text(

        f"✅ تم تأكيد الطلب #{payment_id}\n\n"

        f"👤 المستخدم: "
        f"{payment['user_id']}\n\n"

        f"📦 الباقة: "
        f"{payment['package_name']}\n\n"

        f"🎬 تمت إضافة: "
        f"{payment['videos']} فيديو\n\n"

        f"💰 الرصيد الجديد: "
        f"{new_balance} فيديو"
    )

    try:

        await context.bot.send_message(

            chat_id=payment["user_id"],

            text=(

                "🎉 تم تأكيد الدفع!\n\n"

                f"📦 الباقة: "
                f"{payment['package_name']}\n"

                f"🎬 تمت إضافة: "
                f"{payment['videos']} فيديو\n\n"

                f"💰 رصيدك الحالي: "
                f"{new_balance} فيديو"
            ),

            reply_markup=main_menu(
                payment["user_id"]
            )
        )

    except Exception as error:

        print(
            "USER NOTIFICATION ERROR:",
            repr(error)
        )


# =========================================================
# رفض الدفع
# =========================================================

async def reject_payment(
    update,
    context,
    payment_id
):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "غير مسموح.",
            show_alert=True
        )

        return

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM payments
        WHERE id = ?
        """,
        (payment_id,)
    )

    payment = cursor.fetchone()

    if not payment:

        connection.close()

        await query.answer(
            "الطلب غير موجود.",
            show_alert=True
        )

        return

    if payment["status"] != "pending":

        connection.close()

        await query.answer(
            "تم التعامل مع هذا الطلب مسبقاً.",
            show_alert=True
        )

        return

    cursor.execute(
        """
        UPDATE payments
        SET status = 'rejected'
        WHERE id = ?
        AND status = 'pending'
        """,
        (payment_id,)
    )

    changed = cursor.rowcount > 0

    connection.commit()

    connection.close()

    if not changed:

        await query.answer(
            "تم التعامل مع الطلب مسبقاً.",
            show_alert=True
        )

        return

    await query.answer(
        "تم رفض الطلب.",
        show_alert=True
    )

    await query.edit_message_text(

        f"❌ تم رفض طلب الدفع #{payment_id}."
    )

    try:

        await context.bot.send_message(

            chat_id=payment["user_id"],

            text=(

                "❌ تم رفض إثبات الدفع الخاص بك.\n\n"

                "إذا كنت تعتقد أن هناك خطأ، "
                "تواصل مع الإدارة."
            ),

            reply_markup=main_menu(
                payment["user_id"]
            )
        )

    except Exception as error:

        print(
            "REJECT NOTIFICATION ERROR:",
            repr(error)
        )


# =========================================================
# لوحة الإدارة
# =========================================================

async def admin_panel(
    update,
    context
):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "غير مسموح.",
            show_alert=True
        )

        return

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM users
    """)

    users = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'pending'
    """)

    pending = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'approved'
    """)

    approved = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'rejected'
    """)

    rejected = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
    """)

    total_balance = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM users
        WHERE trial_used = 1
    """)

    trials_used = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM generations
        WHERE status = 'success'
    """)

    successful_videos = cursor.fetchone()["total"]

    connection.close()

    await query.answer()

    await query.edit_message_text(

        "👑 لوحة الإدارة\n\n"

        f"👥 المستخدمون: {users}\n"

        f"🎁 استخدموا التجربة: {trials_used}\n"

        f"🎬 الفيديوهات الناجحة: "
        f"{successful_videos}\n\n"

        f"⏳ طلبات الدفع المعلقة: {pending}\n"

        f"✅ المدفوعات المؤكدة: {approved}\n"

        f"❌ المدفوعات المرفوضة: {rejected}\n\n"

        f"💰 الأرصدة الحالية: "
        f"{total_balance} فيديو\n\n"

        "الأوامر:\n\n"

        "/add USER_ID AMOUNT\n"
        "إضافة رصيد\n\n"

        "/remove USER_ID AMOUNT\n"
        "سحب رصيد\n\n"

        "/balance USER_ID\n"
        "عرض رصيد\n\n"

        "/reset_trial USER_ID\n"
        "إعادة التجربة المجانية\n\n"

        "/stats\n"
        "الإحصائيات",

        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "⬅️ الرئيسية",
                    callback_data="back_main"
                )
            ]

        ])
    )


# =========================================================
# إضافة رصيد يدوي
# =========================================================

async def admin_add(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/add USER_ID AMOUNT"
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

            await update.message.reply_text(
                "❌ يجب أن يكون مقدار الرصيد أكبر من صفر."
            )

            return

        if not user_exists(user_id):

            await update.message.reply_text(
                "❌ هذا المستخدم غير موجود في قاعدة البيانات."
            )

            return

        success = add_balance(
            user_id,
            amount
        )

        if not success:

            await update.message.reply_text(
                "❌ تعذر إضافة الرصيد."
            )

            return

        balance = get_balance(
            user_id
        )

        await update.message.reply_text(

            "✅ تمت إضافة الرصيد.\n\n"

            f"👤 المستخدم: {user_id}\n"

            f"➕ المضاف: {amount}\n"

            f"💰 الرصيد الجديد: {balance}"
        )

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "🎉 تمت إضافة رصيد إلى حسابك.\n\n"

                    f"➕ الرصيد المضاف: "
                    f"{amount} فيديو\n"

                    f"💰 رصيدك الحالي: "
                    f"{balance} فيديو"
                ),

                reply_markup=main_menu(
                    user_id
                )
            )

        except Exception as error:

            print(
                "ADD USER NOTIFICATION ERROR:",
                repr(error)
            )

    except ValueError:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )

    except Exception as error:

        print(
            "ADMIN ADD ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إضافة الرصيد."
        )


# =========================================================
# سحب رصيد
# =========================================================

async def admin_remove(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/remove USER_ID AMOUNT"
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

            await update.message.reply_text(
                "❌ يجب أن يكون مقدار السحب أكبر من صفر."
            )

            return

        if not user_exists(user_id):

            await update.message.reply_text(
                "❌ هذا المستخدم غير موجود في قاعدة البيانات."
            )

            return

        success = remove_balance(
            user_id,
            amount
        )

        if not success:

            await update.message.reply_text(
                "❌ الرصيد غير كافٍ أو المستخدم غير موجود."
            )

            return

        balance = get_balance(
            user_id
        )

        await update.message.reply_text(

            "✅ تم سحب الرصيد.\n\n"

            f"👤 المستخدم: {user_id}\n"

            f"➖ المسحوب: {amount}\n"

            f"💰 الرصيد الجديد: {balance}"
        )

    except ValueError:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )

    except Exception as error:

        print(
            "ADMIN REMOVE ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء سحب الرصيد."
        )


# =========================================================
# عرض رصيد مستخدم
# =========================================================

async def admin_balance(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 1:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/balance USER_ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

        if not user_exists(user_id):

            await update.message.reply_text(
                "❌ المستخدم غير موجود."
            )

            return

        balance = get_balance(
            user_id
        )

        trial = (
            "متاحة"
            if has_free_trial(user_id)
            else "مستخدمة"
        )

        await update.message.reply_text(

            f"👤 المستخدم: {user_id}\n\n"

            f"💰 الرصيد: {balance} فيديو\n"

            f"🎁 التجربة المجانية: {trial}"
        )

    except ValueError:

        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح."
        )

    except Exception as error:

        print(
            "ADMIN BALANCE ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ."
        )


# =========================================================
# إعادة التجربة المجانية للمستخدم
# =========================================================

async def admin_reset_trial(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 1:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/reset_trial USER_ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

        if not user_exists(user_id):

            await update.message.reply_text(
                "❌ المستخدم غير موجود."
            )

            return

        success = reset_trial(
            user_id
        )

        if not success:

            await update.message.reply_text(
                "⚠️ لم يتم تغيير الحالة."
            )

            return

        await update.message.reply_text(

            "✅ تمت إعادة التجربة المجانية.\n\n"

            f"👤 المستخدم: {user_id}\n"

            "🎁 أصبح بإمكانه استخدام "
            "التجربة المجانية مرة أخرى."
        )

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(
                    "🎁 تمت إعادة تفعيل التجربة المجانية "
                    "لحسابك من الإدارة.\n\n"
                    "يمكنك الآن إنشاء فيديو مجاني "
                    "لمدة 3 ثوانٍ."
                ),

                reply_markup=main_menu(
                    user_id
                )
            )

        except Exception as error:

            print(
                "RESET TRIAL NOTIFICATION ERROR:",
                repr(error)
            )

    except ValueError:

        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح."
        )

    except Exception as error:

        print(
            "RESET TRIAL ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ."
        )


# =========================================================
# الإحصائيات
# =========================================================

async def admin_stats(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:

        return

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM users
    """)

    users = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
    """)

    total_balance = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM users
        WHERE trial_used = 1
    """)

    trials_used = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM generations
        WHERE status = 'success'
    """)

    successful = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM generations
        WHERE status = 'failed'
    """)

    failed = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(
            SUM(videos),
            0
        ) AS total
        FROM payments
        WHERE status = 'approved'
    """)

    sold = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(
            SUM(price),
            0
        ) AS total
        FROM payments
        WHERE status = 'approved'
    """)

    revenue = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'pending'
    """)

    pending = cursor.fetchone()["total"]

    connection.close()

    await update.message.reply_text(

        "📊 إحصائيات البوت\n\n"

        f"👥 المستخدمون: {users}\n\n"

        f"🎁 التجارب المستخدمة: "
        f"{trials_used}\n\n"

        f"🎬 الفيديوهات الناجحة: "
        f"{successful}\n\n"

        f"❌ الفيديوهات الفاشلة: "
        f"{failed}\n\n"

        f"💰 الأرصدة الحالية: "
        f"{total_balance}\n\n"

        f"🎬 الفيديوهات المباعة: "
        f"{sold}\n\n"

        f"💵 إجمالي المبيعات: "
        f"{revenue:,} ل.س\n\n"

        f"⏳ المدفوعات المعلقة: "
        f"{pending}"
    )


# =========================================================
# بدء الفيديو المجاني
# =========================================================

async def start_free_trial(
    update,
    context
):

    query = update.callback_query

    user_id = query.from_user.id

    await query.answer()

    ensure_user(
        query.from_user
    )

    if not has_free_trial(user_id):

        await query.edit_message_text(

            "⚠️ لقد استخدمت التجربة المجانية مسبقًا.\n\n"

            "يمكنك الآن شراء رصيد وإنشاء "
            "فيديوهات إضافية.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # التجربة إجبارياً 3 ثواني و480p
    user_states[user_id] = {

        "waiting_for_photo":
            True,

        "trial":
            True,

        "duration":
            FREE_TRIAL_DURATION,

        "resolution":
            FREE_TRIAL_RESOLUTION,
    }

    await query.edit_message_text(

        "🎁 التجربة المجانية\n\n"

        "هذه أول محاولة لك وهي مجانية بالكامل. ❤️\n\n"

        "⏱️ المدة: 3 ثواني فقط\n"

        "📺 الدقة: 480p\n"

        "💰 السعر: مجانًا\n\n"

        "📷 أرسل الصورة الآن.\n\n"

        "⚠️ بعد استخدام التجربة، "
        "ستحتاج إلى شراء رصيد لإنشاء فيديوهات أخرى."
    )


# =========================================================
# بدء فيديو مدفوع
# =========================================================

async def start_paid_video(
    update,
    context
):

    query = update.callback_query

    user_id = query.from_user.id

    await query.answer()

    balance = get_balance(
        user_id
    )

    if balance <= 0:

        await query.edit_message_text(

            "💳 رصيدك صفر.\n\n"

            "اشترِ رصيدًا أولاً حتى تتمكن "
            "من إنشاء فيديو.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "💰 شراء رصيد",
                        callback_data="buy"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⬅️ الرئيسية",
                        callback_data="back_main"
                    )
                ]

            ])
        )

        return

    old_state = user_states.get(
        user_id,
        {}
    )

    duration = old_state.get(
        "duration",
        5
    )

    resolution = old_state.get(
        "resolution",
        "480p"
    )

    user_states[user_id] = {

        "waiting_for_photo":
            True,

        "trial":
            False,

        "duration":
            duration,

        "resolution":
            resolution,
    }

    await query.edit_message_text(

        "🎬 إنشاء فيديو جديد\n\n"

        f"💰 رصيدك: {balance} فيديو\n\n"

        f"⏱️ المدة: {duration} ثواني\n"

        f"📺 الدقة: {resolution}\n\n"

        "📷 أرسل الصورة التي تريد "
        "تحويلها إلى فيديو."
    )


# =========================================================
# استقبال الصور
# =========================================================

async def handle_photo(
    update,
    context
):

    user_id = update.effective_user.id

    ensure_user(
        update.effective_user
    )

    # إذا كان المستخدم ينتظر إثبات دفع
    if await handle_payment_proof(
        update,
        context
    ):

        return

    state = user_states.get(
        user_id,
        {}
    )

    # تجربة مجانية
    if state.get("trial"):

        if not has_free_trial(user_id):

            await update.message.reply_text(

                "⚠️ التجربة المجانية مستخدمة مسبقًا.",

                reply_markup=main_menu(
                    user_id
                )
            )

            user_states.pop(
                user_id,
                None
            )

            return

    # فيديو مدفوع
    else:

        balance = get_balance(
            user_id
        )

        if balance <= 0:

            await update.message.reply_text(

                "💳 لا يوجد لديك رصيد كافٍ.\n\n"

                "اشترِ رصيدًا أولاً.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "💰 شراء رصيد",
                            callback_data="buy"
                        )
                    ]

                ])
            )

            return

    if not state.get(
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 اضغط أولاً على "
            "«إنشاء فيديو» ثم أرسل الصورة.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    photo = update.message.photo[-1]

    try:

        telegram_file = await photo.get_file()

        image_bytes = (
            await telegram_file.download_as_bytearray()
        )

        duration = state.get(
            "duration",
            FREE_TRIAL_DURATION
            if state.get("trial")
            else 5
        )

        resolution = state.get(
            "resolution",
            FREE_TRIAL_RESOLUTION
            if state.get("trial")
            else "480p"
        )

        user_states[user_id] = {

            "image":
                bytes(image_bytes),

            "waiting_for_prompt":
                True,

            "waiting_for_photo":
                False,

            "trial":
                state.get(
                    "trial",
                    False
                ),

            "duration":
                duration,

            "resolution":
                resolution,
        }

        if state.get("trial"):

            await update.message.reply_text(

                "✅ وصلت الصورة!\n\n"

                "🎁 أنت تستخدم التجربة المجانية.\n"

                "⏱️ 3 ثواني\n"

                "📺 480p\n\n"

                "✍️ الآن اكتب وصف الحركة التي تريدها."
            )

        else:

            await update.message.reply_text(

                "✅ وصلت الصورة!\n\n"

                "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"

                "مثال:\n\n"

                "اجعل الشخص يبتسم ويحرك رأسه "
                "ببطء مع حركة كاميرا سينمائية "
                "خفيفة، وحافظ على ملامح الوجه "
                "كما هي."
            )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


# =========================================================
# استقبال النص
# =========================================================

async def handle_text(
    update,
    context
):

    user_id = update.effective_user.id

    ensure_user(
        update.effective_user
    )

    state = user_states.get(
        user_id,
        {}
    )

    if state.get(
        "waiting_payment_proof"
    ):

        await update.message.reply_text(

            "📸 أرسل صورة إثبات الدفع "
            "وليس رسالة نصية."
        )

        return

    if state.get(
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 أنا بانتظار الصورة.\n\n"
            "أرسل صورة للمتابعة."
        )

        return

    if "image" not in state:

        await update.message.reply_text(

            "📷 أرسل صورة أولاً.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    prompt = update.message.text.strip()

    if not prompt:

        await update.message.reply_text(
            "✍️ اكتب وصف الحركة."
        )

        return

    # إذا كانت تجربة مجانية
    if state.get("trial"):

        duration = FREE_TRIAL_DURATION
        resolution = FREE_TRIAL_RESOLUTION

    else:

        duration = state.get(
            "duration",
            5
        )

        resolution = state.get(
            "resolution",
            "480p"
        )

    state["prompt"] = prompt

    state["waiting_for_prompt"] = False

    keyboard = [

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
                "❌ إلغاء",
                callback_data="cancel_generation"
            )
        ]

    ]

    if state.get("trial"):

        await update.message.reply_text(

            "🎁 تجربة مجانية\n\n"

            "📝 وصف الحركة:\n\n"

            f"{prompt}\n\n"

            "⏱️ المدة: 3 ثواني\n"

            "📺 الدقة: 480p\n"

            "💰 السعر: مجانًا\n\n"

            "اضغط «🎬 إنشاء الفيديو» للبدء.",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    else:

        await update.message.reply_text(

            "📝 تم استلام وصف الحركة:\n\n"

            f"{prompt}\n\n"

            f"⏱️ المدة: {duration} ثواني\n"

            f"📺 الدقة: {resolution}\n\n"

            f"💰 رصيدك الحالي: "
            f"{get_balance(user_id)} فيديو\n\n"

            "اضغط «🎬 إنشاء الفيديو» للبدء.",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )


# =========================================================
# إنشاء الفيديو
# =========================================================

async def generate_video(
    update,
    context
):

    query = update.callback_query

    user_id = query.from_user.id

    await query.answer()

    lock = get_generation_lock(
        user_id
    )

    # منع الضغط مرتين
    if not lock.acquire(
        blocking=False
    ):

        await query.answer(
            "⏳ يوجد فيديو قيد الإنشاء بالفعل.",
            show_alert=True
        )

        return

    trial_reserved = False

    try:

        state = user_states.get(
            user_id,
            {}
        )

        if (
            "image" not in state
            or
            "prompt" not in state
        ):

            await query.edit_message_text(

                "❌ أرسل صورة واكتب وصف الحركة أولاً.",

                reply_markup=main_menu(
                    user_id
                )
            )

            return

        is_trial = bool(
            state.get(
                "trial",
                False
            )
        )

        # =====================================================
        # التحقق من التجربة المجانية
        # =====================================================

        if is_trial:

            if not has_free_trial(user_id):

                await query.edit_message_text(

                    "⚠️ التجربة المجانية مستخدمة مسبقًا.\n\n"

                    "اشترِ رصيدًا للمتابعة.",

                    reply_markup=InlineKeyboardMarkup([

                        [
                            InlineKeyboardButton(
                                "💰 شراء رصيد",
                                callback_data="buy"
                            )
                        ]

                    ])
                )

                user_states.pop(
                    user_id,
                    None
                )

                return

            # تسجيل التجربة قبل البدء لمنع التكرار
            trial_reserved = mark_trial_used(
                user_id
            )

            if not trial_reserved:

                await query.edit_message_text(

                    "⚠️ لا يمكن استخدام التجربة المجانية مرة أخرى.",

                    reply_markup=main_menu(
                        user_id
                    )
                )

                user_states.pop(
                    user_id,
                    None
                )

                return

            duration = FREE_TRIAL_DURATION
            resolution = FREE_TRIAL_RESOLUTION

        else:

            # =================================================
            # الفيديو المدفوع
            # =================================================

            balance = get_balance(
                user_id
            )

            if balance <= 0:

                await query.edit_message_text(

                    "💳 لا يوجد رصيد كافٍ.\n\n"

                    "اشترِ رصيدًا أولاً.",

                    reply_markup=InlineKeyboardMarkup([

                        [
                            InlineKeyboardButton(
                                "💰 شراء رصيد",
                                callback_data="buy"
                            )
                        ]

                    ])
                )

                return

            duration = state.get(
                "duration",
                5
            )

            resolution = state.get(
                "resolution",
                "480p"
            )

        prompt = state["prompt"]

        image_bytes = state["image"]

        video_type = (
            "free_trial"
            if is_trial
            else "paid"
        )

        # =====================================================
        # حفظ العملية
        # =====================================================

        save_generation(

            user_id=user_id,

            video_type=video_type,

            duration=duration,

            resolution=resolution,

            prompt=prompt,

            status="started"
        )

        # =====================================================
        # رسالة البداية
        # =====================================================

        if is_trial:

            await query.edit_message_text(

                "🎁 جاري إنشاء تجربتك المجانية...\n\n"

                "📤 جاري رفع الصورة...\n"

                "⏱️ المدة: 3 ثواني\n"

                "📺 الدقة: 480p\n\n"

                "💰 لن يتم خصم أي رصيد."
            )

        else:

            await query.edit_message_text(

                "⏳ جاري إنشاء الفيديو...\n\n"

                "📤 جاري رفع الصورة...\n"

                f"⏱️ المدة: {duration} ثواني\n"

                f"📺 الدقة: {resolution}\n\n"

                "قد يستغرق الأمر بعض الوقت."
            )

        try:

            # =================================================
            # رفع الصورة
            # =================================================

            upload_url, file_path = (
                create_upload_url("jpg")
            )

            upload_image(
                upload_url,
                image_bytes
            )

            print(
                "IMAGE UPLOADED:",
                file_path
            )

            # =================================================
            # إنشاء المشروع
            # =================================================

            await query.edit_message_text(

                "⏳ جاري إنشاء الفيديو...\n\n"

                "🎬 تم رفع الصورة.\n"

                "🤖 جاري إرسال الطلب إلى Magic Hour...\n\n"

                "قد يستغرق الإنشاء عدة دقائق."
            )

            video_data = create_video(

                file_path=file_path,

                prompt=prompt,

                duration=duration,

                resolution=resolution
            )

            video_id = video_data["id"]

            print(
                "VIDEO ID:",
                video_id
            )

            # =================================================
            # الانتظار
            # =================================================

            await query.edit_message_text(

                "⏳ الفيديو قيد المعالجة...\n\n"

                "🎬 Magic Hour يعمل على إنشاء الفيديو.\n\n"

                "يرجى الانتظار..."
            )

            video_url, final_data = (
                wait_for_video(video_id)
            )

            if not video_url:

                print(
                    "FINAL VIDEO DATA:",
                    final_data
                )

                # في حال التجربة، نعيد السماح بها
                # لأن الفيديو لم ينجح
                if is_trial and trial_reserved:

                    reset_trial(
                        user_id
                    )

                    trial_reserved = False

                save_generation(

                    user_id=user_id,

                    video_type=video_type,

                    duration=duration,

                    resolution=resolution,

                    prompt=prompt,

                    status="failed"
                )

                await query.edit_message_text(

                    "❌ لم يتم إنشاء الفيديو.\n\n"

                    "لم يتم خصم أي رصيد.\n\n"

                    "يمكنك المحاولة مرة أخرى.",

                    reply_markup=main_menu(
                        user_id
                    )
                )

                return

            # =================================================
            # تحميل الفيديو
            # =================================================

            await query.edit_message_text(

                "✅ تم إنشاء الفيديو!\n\n"

                "📥 جاري تحميله وإرساله إليك..."
            )

            video_response = requests.get(
                video_url,
                timeout=180
            )

            video_response.raise_for_status()

            video_bytes = video_response.content

            if not video_bytes:

                raise RuntimeError(
                    "الفيديو الذي تم تحميله فارغ."
                )

            print(
                "VIDEO SIZE:",
                len(video_bytes)
            )

            # =================================================
            # خصم الرصيد للفيديو المدفوع فقط
            # =================================================

            if not is_trial:

                removed = remove_balance(
                    user_id,
                    1
                )

                if not removed:

                    print(
                        "BALANCE DEDUCTION FAILED:",
                        user_id
                    )

                    await query.edit_message_text(

                        "⚠️ تم إنشاء الفيديو، "
                        "لكن تعذر خصم الرصيد.\n\n"

                        "تم إيقاف العملية لحماية رصيدك.\n\n"

                        "تواصل مع الإدارة."
                    )

                    return

            # =================================================
            # الرصيد الحالي
            # =================================================

            new_balance = get_balance(
                user_id
            )

            # =================================================
            # إرسال الفيديو
            # =================================================

            try:

                if is_trial:

                    caption = (

                        "🎁 تمت التجربة المجانية بنجاح! 🎬\n\n"

                        "⏱️ المدة: 3 ثواني\n"

                        "📺 الدقة: 480p\n"

                        "💰 لم يتم خصم أي رصيد.\n\n"

                        "🔥 أعجبك الفيديو؟\n"
                        "اشترِ رصيدًا لإنشاء فيديوهات "
                        "أطول وبجودات أعلى."
                    )

                else:

                    caption = (

                        "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                        "💳 تم خصم فيديو واحد.\n"

                        f"💰 رصيدك المتبقي: "
                        f"{new_balance} فيديو"
                    )

                await context.bot.send_video(

                    chat_id=user_id,

                    video=video_bytes,

                    caption=caption
                )

            except Exception as send_error:

                print(
                    "VIDEO SEND ERROR:",
                    repr(send_error)
                )

                try:

                    await context.bot.send_message(

                        chat_id=ADMIN_ID,

                        text=(

                            "⚠️ تنبيه:\n\n"

                            "تم إنشاء فيديو، "
                            "لكن تعذر إرساله للمستخدم.\n\n"

                            f"👤 المستخدم: {user_id}\n"

                            f"🎁 تجربة مجانية: "
                            f"{is_trial}\n"

                            f"💰 الرصيد الحالي: "
                            f"{new_balance}"
                        )
                    )

                except Exception:
                    pass

                await query.edit_message_text(

                    "⚠️ تم إنشاء الفيديو، "
                    "لكن حدث خطأ أثناء إرساله.\n\n"

                    "تم إبلاغ الإدارة."
                )

                return

            # =================================================
            # نجاح كامل
            # =================================================

            save_generation(

                user_id=user_id,

                video_type=video_type,

                duration=duration,

                resolution=resolution,

                prompt=prompt,

                status="success"
            )

            # =================================================
            # تنظيف الحالة
            # =================================================

            user_states.pop(
                user_id,
                None
            )

            if is_trial:

                await query.edit_message_text(

                    "🎉 تمت التجربة المجانية بنجاح!\n\n"

                    "🎁 كانت هذه محاولتك المجانية الوحيدة.\n\n"

                    "🔥 لإنشاء فيديوهات جديدة، "
                    "اشترِ رصيدًا من القائمة.",

                    reply_markup=main_menu(
                        user_id
                    )
                )

            else:

                await query.edit_message_text(

                    "✅ تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"

                    f"💰 رصيدك المتبقي: "
                    f"{new_balance} فيديو",

                    reply_markup=main_menu(
                        user_id
                    )
                )

        except requests.HTTPError as error:

            print(
                "HTTP ERROR:",
                repr(error)
            )

            try:

                if error.response is not None:

                    print(
                        "API STATUS:",
                        error.response.status_code
                    )

                    print(
                        "API RESPONSE:",
                        error.response.text
                    )

            except Exception:
                pass

            # إعادة التجربة في حال فشل الطلب
            if is_trial and trial_reserved:

                reset_trial(
                    user_id
                )

                trial_reserved = False

            save_generation(

                user_id=user_id,

                video_type=video_type,

                duration=duration,

                resolution=resolution,

                prompt=prompt,

                status="failed"
            )

            await query.edit_message_text(

                "❌ Magic Hour رفض الطلب أو حدث خطأ في الاتصال.\n\n"

                "إذا كنت تستخدم الفيديو المدفوع، "
                "لم يتم خصم الرصيد.\n\n"

                "إذا كانت هذه تجربتك المجانية، "
                "تم الحفاظ على التجربة ويمكنك المحاولة مرة أخرى.",

                reply_markup=main_menu(
                    user_id
                )
            )

        except Exception as error:

            print(
                "GENERATION ERROR:",
                repr(error)
            )

            # إعادة التجربة إذا فشلت العملية
            if is_trial and trial_reserved:

                reset_trial(
                    user_id
                )

                trial_reserved = False

            save_generation(

                user_id=user_id,

                video_type=video_type,

                duration=duration,

                resolution=resolution,

                prompt=prompt,

                status="failed"
            )

            await query.edit_message_text(

                "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"

                "لم يتم خصم أي رصيد.\n\n"

                "إذا كانت هذه التجربة المجانية، "
                "يمكنك المحاولة مرة أخرى.",

                reply_markup=main_menu(
                    user_id
                )
            )

    finally:

        try:

            lock.release()

        except Exception:

            pass


# =========================================================
# الأزرار
# =========================================================

async def button_handler(
    update,
    context
):

    query = update.callback_query

    user_id = query.from_user.id

    ensure_user(
        query.from_user
    )

    data = query.data or ""

    # =====================================================
    # التجربة المجانية
    # =====================================================

    if data == "free_trial":

        await start_free_trial(
            update,
            context
        )

        return

    # =====================================================
    # شراء
    # =====================================================

    if data == "buy":

        await show_buy(
            update,
            context
        )

        return

    # =====================================================
    # اختيار باقة
    # =====================================================

    if data.startswith(
        "package_"
    ):

        package_id = data.replace(
            "package_",
            "",
            1
        )

        await create_payment(
            update,
            context,
            package_id
        )

        return

    # =====================================================
    # تأكيد الدفع
    # =====================================================

    if data.startswith(
        "approve_"
    ):

        try:

            payment_id = int(
                data.replace(
                    "approve_",
                    "",
                    1
                )
            )

        except ValueError:

            await query.answer(
                "رقم الطلب غير صحيح.",
                show_alert=True
            )

            return

        await approve_payment(
            update,
            context,
            payment_id
        )

        return

    # =====================================================
    # رفض الدفع
    # =====================================================

    if data.startswith(
        "reject_"
    ):

        try:

            payment_id = int(
                data.replace(
                    "reject_",
                    "",
                    1
                )
            )

        except ValueError:

            await query.answer(
                "رقم الطلب غير صحيح.",
                show_alert=True
            )

            return

        await reject_payment(
            update,
            context,
            payment_id
        )

        return

    # =====================================================
    # لوحة الإدارة
    # =====================================================

    if data == "admin":

        await admin_panel(
            update,
            context
        )

        return

    # =====================================================
    # إنشاء فيديو مدفوع
    # =====================================================

    if data == "new_video":

        await start_paid_video(
            update,
            context
        )

        return

    # =====================================================
    # الرصيد
    # =====================================================

    if data == "balance":

        await query.answer()

        balance = get_balance(
            user_id
        )

        if has_free_trial(user_id):

            trial_status = (
                "🎁 التجربة المجانية: متاحة"
            )

        else:

            trial_status = (
                "🎁 التجربة المجانية: مستخدمة"
            )

        await query.edit_message_text(

            "💳 رصيد حسابك\n\n"

            f"🎬 الرصيد: {balance} فيديو\n\n"

            f"{trial_status}",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # =====================================================
    # الإعدادات
    # =====================================================

    if data == "settings":

        await query.answer()

        # لا نسمح بتغيير إعدادات التجربة
        state = user_states.get(
            user_id,
            {}
        )

        if state.get("trial"):

            await query.edit_message_text(

                "🎁 التجربة المجانية ثابتة:\n\n"

                "⏱️ 3 ثواني\n"

                "📺 480p\n\n"

                "هذه الإعدادات لا يمكن تغييرها "
                "في التجربة المجانية.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "⬅️ رجوع",
                            callback_data="back_main"
                        )
                    ]

                ])
            )

            return

        state = user_states.setdefault(

            user_id,

            {
                "duration": 5,
                "resolution": "480p"
            }
        )

        if "duration" not in state:

            state["duration"] = 5

        if "resolution" not in state:

            state["resolution"] = "480p"

        await query.edit_message_text(

            "⚙️ إعدادات الفيديو:\n\n"

            "اختر الإعداد الذي تريد تغييره.",

            reply_markup=settings_menu(
                state
            )
        )

        return

    # =====================================================
    # المدة
    # =====================================================

    if data == "durations":

        await query.answer()

        state = user_states.get(
            user_id,
            {}
        )

        if state.get("trial"):

            await query.edit_message_text(

                "🎁 التجربة المجانية مدتها ثابتة "
                "3 ثواني.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "⬅️ رجوع",
                            callback_data="settings"
                        )
                    ]

                ])
            )

            return

        await query.edit_message_text(

            "⏱️ اختر مدة الفيديو:",

            reply_markup=duration_menu()
        )

        return

    if data.startswith(
        "duration_"
    ):

        try:

            duration = int(
                data.replace(
                    "duration_",
                    "",
                    1
                )
            )

        except ValueError:

            await query.answer(
                "المدة غير صحيحة.",
                show_alert=True
            )

            return

        if duration not in [
            5,
            10,
            15
        ]:

            await query.answer(
                "هذه المدة غير متاحة.",
                show_alert=True
            )

            return

        state = user_states.setdefault(
            user_id,
            {}
        )

        if state.get("trial"):

            await query.answer(
                "التجربة المجانية ثابتة على 3 ثواني.",
                show_alert=True
            )

            return

        state["duration"] = duration

        if "resolution" not in state:

            state["resolution"] = "480p"

        await query.answer(
            "تم تغيير المدة."
        )

        await query.edit_message_text(

            f"✅ تم اختيار "
            f"{duration} ثانية.",

            reply_markup=settings_menu(
                state
            )
        )

        return

    # =====================================================
    # الدقة
    # =====================================================

    if data == "resolutions":

        await query.answer()

        state = user_states.get(
            user_id,
            {}
        )

        if state.get("trial"):

            await query.edit_message_text(

                "🎁 التجربة المجانية تستخدم دقة "
                "480p فقط.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "⬅️ رجوع",
                            callback_data="settings"
                        )
                    ]

                ])
            )

            return

        await query.edit_message_text(

            "📺 اختر الدقة:",

            reply_markup=resolution_menu()
        )

        return

    if data.startswith(
        "resolution_"
    ):

        value = data.replace(
            "resolution_",
            "",
            1
        )

        allowed = {
            "480": "480p",
            "720": "720p",
            "1080": "1080p",
        }

        resolution = allowed.get(
            value
        )

        if not resolution:

            await query.answer(
                "الدقة غير صحيحة.",
                show_alert=True
            )

            return

        state = user_states.setdefault(
            user_id,
            {}
        )

        if state.get("trial"):

            await query.answer(
                "التجربة المجانية ثابتة على 480p.",
                show_alert=True
            )

            return

        state["resolution"] = resolution

        if "duration" not in state:

            state["duration"] = 5

        await query.answer(
            "تم تغيير الدقة."
        )

        await query.edit_message_text(

            f"✅ تم اختيار الدقة "
            f"{resolution}.",

            reply_markup=settings_menu(
                state
            )
        )

        return

    # =====================================================
    # المساعدة
    # =====================================================

    if data == "help":

        await query.answer()

        await query.edit_message_text(

            "ℹ️ طريقة الاستخدام:\n\n"

            "🎁 أول فيديو:\n"
            "مجاني — 3 ثواني — 480p.\n\n"

            "💰 بعد التجربة:\n"
            "اشترِ رصيدًا لإنشاء فيديوهات جديدة.\n\n"

            "⚙️ الفيديوهات المدفوعة:\n"
            "5 / 10 / 15 ثانية\n"
            "480p / 720p / 1080p\n\n"

            "📷 أرسل صورة.\n"
            "✍️ اكتب وصف الحركة.\n"
            "🎬 اضغط إنشاء الفيديو.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # =====================================================
    # إلغاء إنشاء الفيديو
    # =====================================================

    if data == "cancel_generation":

        await query.answer()

        user_states.pop(
            user_id,
            None
        )

        await query.edit_message_text(

            "❌ تم إلغاء العملية.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # =====================================================
    # الرئيسية
    # =====================================================

    if data == "back_main":

        await query.answer()

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # =====================================================
    # إنشاء الفيديو
    # =====================================================

    if data == "generate":

        await generate_video(
            update,
            context
        )

        return

    # =====================================================
    # غير معروف
    # =====================================================

    await query.answer(
        "الخيار غير معروف.",
        show_alert=True
    )


# =========================================================
# أخطاء البوت
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
# تشغيل البوت
# =========================================================

def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # الأوامر
    # =====================================================

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

    # =====================================================
    # أوامر الإدارة
    # =====================================================

    bot_app.add_handler(
        CommandHandler(
            "add",
            admin_add
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "remove",
            admin_remove
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "balance",
            admin_balance
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "reset_trial",
            admin_reset_trial
        )
    )

    bot_app.add_handler(
        CommandHandler(
            "stats",
            admin_stats
        )
    )

    # =====================================================
    # الصور
    # =====================================================

    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # =====================================================
    # النصوص
    # =====================================================

    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # =====================================================
    # الأزرار
    # =====================================================

    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # =====================================================
    # الأخطاء
    # =====================================================

    bot_app.add_error_handler(
        error_handler
    )

    print(
        "Telegram bot is starting..."
    )

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    print(
        "Initializing database..."
    )

    init_db()

    print(
        "Starting Telegram bot thread..."
    )

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )

    bot_thread.start()

    print(
        "Starting Flask web server..."
    )

    run_web()
