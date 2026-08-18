import os
import time
import threading
import sqlite3
import requests
import traceback

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

# قفل عام لعمليات الدفع الحساسة
payment_lock = threading.Lock()


# =========================================================
# التجربة المجانية
# =========================================================

FREE_TRIAL_DURATION = 3


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

    connection = db()

    cursor = connection.cursor()

    # -----------------------------------------------------
    # المستخدمون
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # إضافة عمود التجربة إذا كانت قاعدة البيانات قديمة
    # -----------------------------------------------------

    cursor.execute(
        "PRAGMA table_info(users)"
    )

    columns = [
        row["name"]
        for row in cursor.fetchall()
    ]

    if "trial_used" not in columns:

        print(
            "Adding trial_used column to users table...",
            flush=True
        )

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN trial_used INTEGER DEFAULT 0
        """)

    # -----------------------------------------------------
    # المدفوعات
    # -----------------------------------------------------

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

    connection.commit()

    connection.close()

    print(
        "Database initialized successfully.",
        flush=True
    )


# =========================================================
# المستخدم
# =========================================================

def ensure_user(user):

    if not user:
        return

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

    cursor.execute(
        """
        SELECT 1
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    connection.close()

    return row is not None


# =========================================================
# الرصيد
# =========================================================

def get_balance(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:
        return 0

    return int(row["balance"] or 0)


def add_balance(user_id, amount):

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


# =========================================================
# التجربة المجانية
# =========================================================

def has_free_trial(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT trial_used
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:
        return False

    return int(row["trial_used"] or 0) == 0


def mark_free_trial_used(user_id):

    connection = db()

    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE users
        SET trial_used = 1
        WHERE user_id = ?
        AND trial_used = 0
        """,
        (user_id,)
    )

    success = cursor.rowcount == 1

    connection.commit()

    connection.close()

    return success


# =========================================================
# أقفال إنشاء الفيديو
# =========================================================

def get_generation_lock(user_id):

    if user_id not in generation_locks:

        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


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


# =========================================================
# Magic Hour - رابط رفع الصورة
# =========================================================

def create_upload_url(extension="jpg"):

    print(
        "MAGIC HOUR: Requesting upload URL...",
        flush=True
    )

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

    print(
        "UPLOAD URL STATUS:",
        response.status_code,
        flush=True
    )

    print(
        "UPLOAD URL RESPONSE:",
        response.text,
        flush=True
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


# =========================================================
# رفع الصورة
# =========================================================

def upload_image(
    upload_url,
    image_bytes
):

    print(
        "MAGIC HOUR: Uploading image...",
        flush=True
    )

    response = requests.put(

        upload_url,

        data=image_bytes,

        timeout=120,
    )

    print(
        "IMAGE UPLOAD STATUS:",
        response.status_code,
        flush=True
    )

    print(
        "IMAGE UPLOAD RESPONSE:",
        response.text[:1000],
        flush=True
    )

    response.raise_for_status()


# =========================================================
# إنشاء الفيديو
# =========================================================

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

    print(
        "MAGIC HOUR: Creating video...",
        flush=True
    )

    print(
        "VIDEO PAYLOAD:",
        payload,
        flush=True
    )

    response = requests.post(

        f"{MAGIC_HOUR_BASE}/image-to-video",

        headers=magic_headers(),

        json=payload,

        timeout=120,
    )

    print(
        "VIDEO CREATE STATUS:",
        response.status_code,
        flush=True
    )

    print(
        "VIDEO CREATE RESPONSE:",
        response.text,
        flush=True
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


# =========================================================
# انتظار الفيديو
# =========================================================

def wait_for_video(video_id):

    # 90 × 10 ثواني
    # تقريباً 15 دقيقة

    for attempt in range(90):

        print(
            f"CHECK VIDEO [{attempt + 1}/90]",
            flush=True
        )

        response = requests.get(

            f"{MAGIC_HOUR_BASE}/video-projects/{video_id}",

            headers={
                "Authorization":
                    f"Bearer {MAGIC_HOUR_API_KEY}"
            },

            timeout=60,
        )

        print(
            "STATUS CHECK HTTP:",
            response.status_code,
            flush=True
        )

        response.raise_for_status()

        data = response.json()

        print(
            "VIDEO STATUS DATA:",
            data,
            flush=True
        )

        status = data.get(
            "status"
        )

        print(
            f"VIDEO STATUS [{attempt + 1}/90]:",
            status,
            flush=True
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
                "VIDEO FAILED:",
                data,
                flush=True
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

    keyboard = [

        [
            InlineKeyboardButton(
                "🎬 إنشاء فيديو",
                callback_data="new_video"
            )
        ],

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
    ]

    if trial_available:

        keyboard.insert(
            1,
            [
                InlineKeyboardButton(
                    "🎁 تجربة مجانية — 3 ثواني",
                    callback_data="new_video"
                )
            ]
        )

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
# الإعدادات
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

    ensure_user(user)

    user_states.pop(
        user.id,
        None
    )

    balance = get_balance(
        user.id
    )

    trial_available = has_free_trial(
        user.id
    )

    if trial_available:

        trial_text = (
            "🎁 لديك تجربة مجانية واحدة!\n"
            "⏱️ مدة التجربة: 3 ثوانٍ\n\n"
        )

    else:

        trial_text = ""

    await update.message.reply_text(

        "مرحباً 👋\n\n"

        "🎬 أهلاً بك في بوت تحويل الصور "
        "إلى فيديو بالذكاء الاصطناعي.\n\n"

        f"💰 رصيدك الحالي: "
        f"{balance} فيديو\n\n"

        f"{trial_text}"

        "📷 اضغط «إنشاء فيديو» للبدء.",

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

        "1️⃣ لديك تجربة مجانية واحدة لمدة 3 ثوانٍ.\n"
        "2️⃣ بعد انتهاء التجربة اشترِ رصيدًا.\n"
        "3️⃣ اضغط «إنشاء فيديو».\n"
        "4️⃣ أرسل صورة.\n"
        "5️⃣ اكتب وصف الحركة.\n"
        "6️⃣ اضغط إنشاء الفيديو.\n\n"

        "مثال:\n"

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

        "بعد اختيار الباقة ستظهر لك "
        "طريقة الدفع عبر شام كاش.",

        reply_markup=packages_menu()
    )


# =========================================================
# إنشاء طلب دفع
# =========================================================

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

        await update.message.forward(
            chat_id=ADMIN_ID
        )

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
            repr(error),
            flush=True
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
            repr(error),
            flush=True
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
            repr(error),
            flush=True
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

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        """
    )

    users = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'pending'
        """
    )

    pending = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status = 'approved'
        """
    )

    approved = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE trial_used = 1
        """
    )

    trials_used = cursor.fetchone()["total"]

    connection.close()

    await query.answer()

    await query.edit_message_text(

        "👑 لوحة الإدارة\n\n"

        f"👥 المستخدمون: "
        f"{users}\n"

        f"🎁 التجارب المستخدمة: "
        f"{trials_used}\n"

        f"⏳ طلبات الدفع المعلقة: "
        f"{pending}\n"

        f"✅ المدفوعات المؤكدة: "
        f"{approved}\n\n"

        "الأوامر:\n\n"

        "/add USER_ID AMOUNT\n"
        "إضافة رصيد\n\n"

        "/remove USER_ID AMOUNT\n"
        "سحب رصيد\n\n"

        "/balance USER_ID\n"
        "عرض رصيد\n\n"

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
# إضافة رصيد
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

            f"👤 المستخدم: "
            f"{user_id}\n"

            f"➕ المضاف: "
            f"{amount}\n"

            f"💰 الرصيد الجديد: "
            f"{balance}"
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
                )
            )

        except Exception as error:

            print(
                "ADD USER NOTIFICATION ERROR:",
                repr(error),
                flush=True
            )

    except ValueError:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )

    except Exception as error:

        print(
            "ADMIN ADD ERROR:",
            repr(error),
            flush=True
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

            f"👤 المستخدم: "
            f"{user_id}\n"

            f"➖ المسحوب: "
            f"{amount}\n"

            f"💰 الرصيد الجديد: "
            f"{balance}"
        )

    except ValueError:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )

    except Exception as error:

        print(
            "ADMIN REMOVE ERROR:",
            repr(error),
            flush=True
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

        await update.message.reply_text(

            f"👤 المستخدم: "
            f"{user_id}\n"

            f"💰 الرصيد: "
            f"{balance} فيديو"
        )

    except ValueError:

        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح."
        )

    except Exception as error:

        print(
            "ADMIN BALANCE ERROR:",
            repr(error),
            flush=True
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

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        """
    )

    users = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
        """
    )

    total_balance = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COALESCE(
            SUM(videos),
            0
        ) AS total
        FROM payments
        WHERE status = 'approved'
        """
    )

    sold = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COALESCE(
            SUM(price),
            0
        ) AS total
        FROM payments
        WHERE status = 'approved'
        """
    )

    revenue = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE trial_used = 1
        """
    )

    trials_used = cursor.fetchone()["total"]

    connection.close()

    await update.message.reply_text(

        "📊 إحصائيات البوت\n\n"

        f"👥 المستخدمون: "
        f"{users}\n\n"

        f"🎁 التجارب المستخدمة: "
        f"{trials_used}\n\n"

        f"💰 الأرصدة الحالية: "
        f"{total_balance}\n\n"

        f"🎬 الفيديوهات المباعة: "
        f"{sold}\n\n"

        f"💵 إجمالي المبيعات: "
        f"{revenue:,} ل.س"
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

    # إثبات دفع
    if await handle_payment_proof(
        update,
        context
    ):

        return

    state = user_states.get(
        user_id,
        {}
    )

    # -----------------------------------------------------
    # إذا كانت تجربة مجانية
    # -----------------------------------------------------

    is_trial = state.get(
        "free_trial",
        False
    )

    # -----------------------------------------------------
    # إذا لا توجد تجربة ولا رصيد
    # -----------------------------------------------------

    if not is_trial:

        balance = get_balance(
            user_id
        )

        if balance <= 0:

            await update.message.reply_text(

                "💳 لا يوجد لديك رصيد كافٍ.\n\n"

                "🎁 إذا لم تستخدم تجربتك المجانية "
                "يمكنك استخدامها الآن.\n\n"

                "أو اشترِ رصيدًا لإنشاء الفيديوهات.",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "🎁 التجربة المجانية",
                            callback_data="new_video"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "💰 شراء رصيد",
                            callback_data="buy"
                        )
                    ]

                ])
            )

            return

    # -----------------------------------------------------
    # التأكد من مرحلة الصورة
    # -----------------------------------------------------

    if not state.get(
        "waiting_for_photo"
    ):

        await update.message.reply_text(

            "📷 اضغط أولاً على "
            "«🎬 إنشاء فيديو» ثم أرسل الصورة.",

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
            5
        )

        resolution = state.get(
            "resolution",
            "480p"
        )

        # -------------------------------------------------
        # التجربة المجانية دائماً 3 ثواني
        # -------------------------------------------------

        if state.get(
            "free_trial",
            False
        ):

            duration = FREE_TRIAL_DURATION

        user_states[user_id] = {

            "image":
                bytes(image_bytes),

            "waiting_for_prompt":
                True,

            "waiting_for_photo":
                False,

            "duration":
                duration,

            "resolution":
                resolution,

            "free_trial":
                state.get(
                    "free_trial",
                    False
                ),
        }

        if state.get(
            "free_trial",
            False
        ):

            message = (

                "🎁 تم تفعيل التجربة المجانية!\n\n"

                "✅ وصلت الصورة.\n\n"

                "✍️ الآن اكتب وصف الحركة.\n\n"

                "⏱️ مدة التجربة: 3 ثوانٍ\n\n"

                "مثال:\n"

                "اجعل الشخص يبتسم ويحرك رأسه "
                "ببطء مع حركة كاميرا سينمائية "
                "خفيفة، مع الحفاظ على ملامح الوجه."
            )

        else:

            message = (

                "✅ وصلت الصورة!\n\n"

                "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"

                "مثال:\n\n"

                "اجعل الشخص يبتسم ويحرك رأسه "
                "ببطء مع حركة كاميرا سينمائية "
                "خفيفة، وحافظ على ملامح الوجه "
                "كما هي."
            )

        await update.message.reply_text(
            message
        )

    except Exception as error:

        print(
            "PHOTO ERROR:",
            repr(error),
            flush=True
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

    state["prompt"] = prompt

    state["waiting_for_prompt"] = False

    is_trial = state.get(
        "free_trial",
        False
    )

    if is_trial:

        duration_text = (
            "⏱️ المدة: 3 ثواني\n"
            "🎁 هذه تجربة مجانية"
        )

    else:

        duration_text = (

            f"⏱️ المدة: "
            f"{state.get('duration', 5)} ثواني\n"

            f"📺 الدقة: "
            f"{state.get('resolution', '480p')}"
        )

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

    await update.message.reply_text(

        "📝 تم استلام وصف الحركة:\n\n"

        f"{prompt}\n\n"

        f"{duration_text}\n\n"

        + (
            "🎁 لن يتم خصم أي رصيد من التجربة المجانية."
            if is_trial
            else
            f"💰 رصيدك الحالي: "
            f"{get_balance(user_id)} فيديو"
        )
        +

        "\n\nاضغط «إنشاء الفيديو» للبدء.",

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

    print(
        "\n" + "=" * 70,
        flush=True
    )

    print(
        "🎬 GENERATE VIDEO START",
        flush=True
    )

    print(
        "USER ID:",
        user_id,
        flush=True
    )

    print(
        "CALLBACK:",
        query.data,
        flush=True
    )

    print(
        "=" * 70,
        flush=True
    )

    await query.answer()

    lock = get_generation_lock(
        user_id
    )

    if not lock.acquire(
        blocking=False
    ):

        print(
            "❌ GENERATION LOCK ACTIVE",
            flush=True
        )

        await query.answer(
            "⏳ يوجد فيديو قيد الإنشاء بالفعل.",
            show_alert=True
        )

        return

    try:

        # =================================================
        # STEP 1
        # =================================================

        print(
            "STEP 1: Reading user state...",
            flush=True
        )

        state = user_states.get(
            user_id,
            {}
        )

        print(
            "STATE KEYS:",
            list(state.keys()),
            flush=True
        )

        is_trial = state.get(
            "free_trial",
            False
        )

        print(
            "FREE TRIAL:",
            is_trial,
            flush=True
        )

        balance = get_balance(
            user_id
        )

        print(
            "BALANCE:",
            balance,
            flush=True
        )

        # =================================================
        # التحقق من الرصيد أو التجربة
        # =================================================

        if not is_trial and balance <= 0:

            print(
                "❌ NO BALANCE AND NO TRIAL",
                flush=True
            )

            await query.edit_message_text(

                "💳 لا يوجد رصيد كافٍ.\n\n"

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

            return

        # =================================================
        # التحقق من الصورة والوصف
        # =================================================

        if "image" not in state:

            print(
                "❌ IMAGE MISSING",
                flush=True
            )

            await query.edit_message_text(
                "❌ الصورة غير موجودة. أرسل الصورة من جديد."
            )

            return

        if "prompt" not in state:

            print(
                "❌ PROMPT MISSING",
                flush=True
            )

            await query.edit_message_text(
                "❌ وصف الحركة غير موجود. اكتب الوصف من جديد."
            )

            return

        # =================================================
        # الإعدادات
        # =================================================

        if is_trial:

            duration = FREE_TRIAL_DURATION

        else:

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

        print(
            "STEP 2: Settings",
            flush=True
        )

        print(
            "DURATION:",
            duration,
            flush=True
        )

        print(
            "RESOLUTION:",
            resolution,
            flush=True
        )

        print(
            "PROMPT:",
            prompt,
            flush=True
        )

        print(
            "IMAGE SIZE:",
            len(image_bytes),
            "bytes",
            flush=True
        )

        # =================================================
        # رسالة البداية
        # =================================================

        if is_trial:

            start_message = (

                "🎁 جاري إنشاء تجربتك المجانية...\n\n"

                "📤 جاري رفع الصورة...\n"

                "⏱️ المدة: 3 ثواني\n\n"

                "💳 لن يتم خصم أي رصيد."
            )

        else:

            start_message = (

                "⏳ جاري إنشاء الفيديو...\n\n"

                "📤 جاري رفع الصورة...\n"

                f"⏱️ المدة: {duration} ثواني\n"

                f"📺 الدقة: {resolution}\n\n"

                "يرجى الانتظار..."
            )

        await query.edit_message_text(
            start_message
        )

        # =================================================
        # STEP 3
        # رابط رفع الصورة
        # =================================================

        print(
            "STEP 3: Requesting Magic Hour upload URL...",
            flush=True
        )

        upload_url, file_path = create_upload_url(
            "jpg"
        )

        print(
            "✅ UPLOAD URL RECEIVED",
            flush=True
        )

        print(
            "FILE PATH:",
            file_path,
            flush=True
        )

        # =================================================
        # STEP 4
        # رفع الصورة
        # =================================================

        print(
            "STEP 4: Uploading image...",
            flush=True
        )

        upload_image(
            upload_url,
            image_bytes
        )

        print(
            "✅ IMAGE UPLOADED SUCCESSFULLY",
            flush=True
        )

        await query.edit_message_text(

            "⏳ جاري إنشاء الفيديو...\n\n"

            "✅ تم رفع الصورة.\n"

            "🤖 جاري إرسال الطلب إلى Magic Hour...\n\n"

            + (
                "🎁 التجربة المجانية — 3 ثواني"
                if is_trial
                else
                f"⏱️ {duration} ثواني — {resolution}"
            )
        )

        # =================================================
        # STEP 5
        # إنشاء الفيديو
        # =================================================

        print(
            "STEP 5: Creating Magic Hour video...",
            flush=True
        )

        video_data = create_video(

            file_path=file_path,

            prompt=prompt,

            duration=duration,

            resolution=resolution
        )

        print(
            "✅ MAGIC HOUR VIDEO RESPONSE:",
            video_data,
            flush=True
        )

        video_id = video_data.get(
            "id"
        )

        if not video_id:

            print(
                "❌ NO VIDEO ID",
                flush=True
            )

            await query.edit_message_text(
                "❌ Magic Hour لم يرجع رقم الفيديو."
            )

            return

        print(
            "VIDEO ID:",
            video_id,
            flush=True
        )

        # =================================================
        # STEP 6
        # الانتظار
        # =================================================

        await query.edit_message_text(

            "⏳ الفيديو قيد المعالجة...\n\n"

            "🎬 Magic Hour يعمل على إنشاء الفيديو.\n\n"

            + (
                "🎁 تجربة مجانية — 3 ثواني"
                if is_trial
                else
                "💳 سيتم الخصم فقط بعد نجاح العملية."
            )
        )

        print(
            "STEP 6: Waiting for video...",
            flush=True
        )

        video_url, final_data = wait_for_video(
            video_id
        )

        print(
            "FINAL VIDEO URL:",
            video_url,
            flush=True
        )

        print(
            "FINAL DATA:",
            final_data,
            flush=True
        )

        if not video_url:

            await query.edit_message_text(

                "❌ لم يتم إنشاء الفيديو.\n\n"

                + (
                    "🎁 لم يتم استهلاك التجربة المجانية."
                    if is_trial
                    else
                    "💳 لم يتم خصم الرصيد."
                )
                +

                "\n\nيمكنك المحاولة مرة أخرى."
            )

            return

        # =================================================
        # STEP 7
        # تحميل الفيديو
        # =================================================

        await query.edit_message_text(

            "✅ تم إنشاء الفيديو!\n\n"

            "📥 جاري تحميله وإرساله إليك..."
        )

        print(
            "STEP 7: Downloading video...",
            flush=True
        )

        video_response = requests.get(

            video_url,

            timeout=180
        )

        print(
            "DOWNLOAD STATUS:",
            video_response.status_code,
            flush=True
        )

        video_response.raise_for_status()

        video_bytes = video_response.content

        print(
            "VIDEO SIZE:",
            len(video_bytes),
            "bytes",
            flush=True
        )

        if not video_bytes:

            raise RuntimeError(
                "Downloaded video is empty"
            )

        # =================================================
        # STEP 8
        # التعامل مع الرصيد / التجربة
        # =================================================

        if is_trial:

            print(
                "STEP 8: Marking free trial as used...",
                flush=True
            )

            trial_marked = mark_free_trial_used(
                user_id
            )

            if not trial_marked:

                print(
                    "⚠️ FREE TRIAL WAS ALREADY USED",
                    flush=True
                )

                # لا نسمح بتحويل محاولة مجانية ثانية
                # إلى تجربة مجانية بالخطأ.

                await query.edit_message_text(

                    "⚠️ حدث تعارض في حالة التجربة المجانية.\n\n"

                    "تواصل مع الإدارة."
                )

                return

            new_balance = get_balance(
                user_id
            )

            print(
                "FREE TRIAL SUCCESSFULLY CONSUMED",
                flush=True
            )

            print(
                "BALANCE REMAINS:",
                new_balance,
                flush=True
            )

        else:

            print(
                "STEP 8: Removing one paid credit...",
                flush=True
            )

            removed = remove_balance(
                user_id,
                1
            )

            if not removed:

                print(
                    "❌ BALANCE DEDUCTION FAILED",
                    flush=True
                )

                await query.edit_message_text(

                    "⚠️ تم إنشاء الفيديو، "
                    "لكن تعذر خصم الرصيد.\n\n"

                    "تم إيقاف العملية لحماية رصيدك.\n\n"

                    "تواصل مع الإدارة."
                )

                return

            new_balance = get_balance(
                user_id
            )

            print(
                "NEW BALANCE:",
                new_balance,
                flush=True
            )

        # =================================================
        # STEP 9
        # إرسال الفيديو إلى Telegram
        # =================================================

        print(
            "STEP 9: Sending video to Telegram...",
            flush=True
        )

        if is_trial:

            caption = (

                "🎉 تم إنشاء تجربتك المجانية بنجاح!\n\n"

                "🎁 التجربة: 3 ثواني\n"

                "💳 لم يتم خصم أي رصيد.\n\n"

                "⭐ يمكنك الآن شراء رصيد لإنشاء المزيد من الفيديوهات."
            )

        else:

            caption = (

                "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                "💳 تم خصم فيديو واحد.\n"

                f"💰 رصيدك المتبقي: "
                f"{new_balance} فيديو"
            )

        try:

            await context.bot.send_video(

                chat_id=user_id,

                video=video_bytes,

                caption=caption
            )

            print(
                "✅ VIDEO SENT TO TELEGRAM",
                flush=True
            )

        except Exception as send_error:

            print(
                "❌ VIDEO SEND ERROR:",
                repr(send_error),
                flush=True
            )

            # -------------------------------------------------
            # مهم:
            #
            # في التجربة المجانية تم تسجيلها قبل الإرسال.
            # في الدفع تم الخصم قبل الإرسال.
            #
            # لذلك لا نعيد الرصيد تلقائياً.
            # -------------------------------------------------

            try:

                await context.bot.send_message(

                    chat_id=ADMIN_ID,

                    text=(

                        "⚠️ تنبيه إداري\n\n"

                        "تم إنشاء فيديو بنجاح، "
                        "لكن فشل إرساله إلى المستخدم.\n\n"

                        f"👤 المستخدم: {user_id}\n"

                        f"🎁 تجربة مجانية: "
                        f"{'نعم' if is_trial else 'لا'}\n"

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
        # STEP 10
        # تنظيف الحالة
        # =================================================

        user_states.pop(
            user_id,
            None
        )

        print(
            "STEP 10: State cleaned.",
            flush=True
        )

        if is_trial:

            await query.edit_message_text(

                "🎉 تمت التجربة المجانية بنجاح!\n\n"

                "🎁 حصلت على فيديو مجاني لمدة 3 ثوانٍ.\n"

                "💳 لم يتم خصم أي رصيد.\n\n"

                "🔥 لإنشاء فيديوهات إضافية، "
                "يمكنك شراء إحدى الباقات.",

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

        print(
            "🎉 GENERATION COMPLETE",
            flush=True
        )

    except requests.HTTPError as error:

        print(
            "\n" + "❌" * 20,
            flush=True
        )

        print(
            "HTTP ERROR",
            flush=True
        )

        print(
            "ERROR TYPE:",
            type(error).__name__,
            flush=True
        )

        print(
            "ERROR:",
            repr(error),
            flush=True
        )

        if error.response is not None:

            print(
                "API STATUS:",
                error.response.status_code,
                flush=True
            )

            print(
                "API RESPONSE:",
                error.response.text,
                flush=True
            )

        print(
            "❌" * 20,
            flush=True
        )

        # لا نستهلك التجربة عند فشل API
        # ولا نخصم الرصيد.

        await query.edit_message_text(

            "❌ Magic Hour رفض الطلب أو حدث خطأ في الاتصال.\n\n"

            + (
                "🎁 لم يتم استهلاك التجربة المجانية."
                if is_trial
                else
                "💳 لم يتم خصم الرصيد."
            )
            +

            "\n\n"
            "يمكنك المحاولة مرة أخرى."
        )

    except Exception as error:

        print(
            "\n" + "❌" * 20,
            flush=True
        )

        print(
            "GENERAL GENERATION ERROR",
            flush=True
        )

        print(
            "ERROR TYPE:",
            type(error).__name__,
            flush=True
        )

        print(
            "ERROR:",
            repr(error),
            flush=True
        )

        traceback.print_exc()

        print(
            "❌" * 20,
            flush=True
        )

        await query.edit_message_text(

            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"

            + (
                "🎁 لم يتم استهلاك التجربة المجانية."
                if is_trial
                else
                "💳 لم يتم خصم الرصيد."
            )
            +

            "\n\n"
            "يمكنك المحاولة مرة أخرى."
        )

    finally:

        try:

            lock.release()

        except Exception:
            pass

        print(
            "🔓 GENERATION LOCK RELEASED",
            flush=True
        )


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
    # شراء
    # =====================================================

    if data == "buy":

        await show_buy(
            update,
            context
        )

        return

    # =====================================================
    # اختيار الباقة
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
    # إنشاء فيديو
    # =====================================================

    if data == "new_video":

        await query.answer()

        balance = get_balance(
            user_id
        )

        trial_available = has_free_trial(
            user_id
        )

        # -------------------------------------------------
        # تحديد هل المستخدم سيستخدم التجربة أم الرصيد
        # -------------------------------------------------

        if trial_available:

            is_trial = True

            duration = FREE_TRIAL_DURATION

            resolution = "480p"

            user_states[user_id] = {

                "waiting_for_photo":
                    True,

                "duration":
                    duration,

                "resolution":
                    resolution,

                "free_trial":
                    True,
            }

            await query.edit_message_text(

                "🎁 تجربتك المجانية جاهزة!\n\n"

                "📷 أرسل صورة الآن.\n\n"

                "⏱️ مدة الفيديو: 3 ثواني\n"

                "💳 لن يتم خصم أي رصيد.\n\n"

                "⭐ هذه التجربة متاحة مرة واحدة فقط."
            )

            return

        # -------------------------------------------------
        # لا توجد تجربة
        # -------------------------------------------------

        if balance <= 0:

            await query.edit_message_text(

                "💳 رصيدك صفر.\n\n"

                "اشترِ رصيدًا لإنشاء الفيديوهات.",

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

        # -------------------------------------------------
        # فيديو مدفوع
        # -------------------------------------------------

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

            "duration":
                duration,

            "resolution":
                resolution,

            "free_trial":
                False,
        }

        await query.edit_message_text(

            "📷 أرسل الصورة التي تريد "
            "تحويلها إلى فيديو.\n\n"

            f"💰 رصيدك: "
            f"{balance} فيديو\n\n"

            f"⏱️ المدة: "
            f"{duration} ثواني\n"

            f"📺 الدقة: "
            f"{resolution}"
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

        trial_available = has_free_trial(
            user_id
        )

        if trial_available:

            trial_status = (
                "🎁 التجربة المجانية: متاحة\n"
                "⏱️ 3 ثواني"
            )

        else:

            trial_status = (
                "🎁 التجربة المجانية: مستخدمة"
            )

        await query.edit_message_text(

            "💳 حسابك\n\n"

            f"🎬 الرصيد المدفوع: "
            f"{balance} فيديو\n\n"

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

        # لا نسمح بتغيير مدة التجربة
        if state.get(
            "free_trial",
            False
        ):

            await query.edit_message_text(

                "🎁 أنت حالياً في التجربة المجانية.\n\n"

                "⏱️ مدة التجربة ثابتة: 3 ثوانٍ.\n\n"

                "بعد التجربة يمكنك اختيار "
                "المدة والدقة للفيديوهات المدفوعة.",

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

        if state.get(
            "free_trial",
            False
        ):

            await query.answer(
                "التجربة المجانية مدتها 3 ثوانٍ فقط.",
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

        if state.get(
            "free_trial",
            False
        ):

            await query.answer(
                "يمكن تغيير الدقة بعد بدء الفيديو المدفوع.",
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

            "🎁 أولاً:\n"
            "لديك تجربة مجانية واحدة لمدة 3 ثوانٍ.\n\n"

            "🎬 بعد ذلك:\n"
            "اشترِ رصيدًا لإنشاء المزيد من الفيديوهات.\n\n"

            "1️⃣ اضغط إنشاء فيديو.\n"
            "2️⃣ أرسل صورة.\n"
            "3️⃣ اكتب وصف الحركة.\n"
            "4️⃣ اضغط إنشاء الفيديو.\n\n"

            "⚙️ يمكنك تغيير المدة والدقة "
            "للفيديوهات المدفوعة.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # =====================================================
    # إلغاء
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
        "\n" + "=" * 70,
        flush=True
    )

    print(
        "BOT ERROR:",
        repr(context.error),
        flush=True
    )

    traceback.print_exception(
        type(context.error),
        context.error,
        context.error.__traceback__
    )

    print(
        "=" * 70,
        flush=True
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
        "Telegram bot is starting...",
        flush=True
    )

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    print(
        "Initializing database...",
        flush=True
    )

    init_db()

    print(
        "Starting Telegram bot thread...",
        flush=True
    )

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )

    bot_thread.start()

    print(
        "Starting Flask web server...",
        flush=True
    )

    run_web()
