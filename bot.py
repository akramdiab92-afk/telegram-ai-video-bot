import os
import threading
import sqlite3
import asyncio
import tempfile

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

from gradio_client import Client, handle_file


# =========================================================
# الإعدادات
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]

HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()

HF_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
HF_API_NAME = "/generate_video"

ADMIN_ID = 625548190

SHAM_CASH_NUMBER = "55c04a684471d4b5f504f0e6e2ca7384"

DB_FILE = "bot_data.db"

app_web = Flask(__name__)

user_states = {}

generation_locks = {}

payment_lock = threading.Lock()


# =========================================================
# إعدادات الفيديو
# =========================================================

ALLOWED_DURATIONS = [3, 4, 5]

DEFAULT_DURATION = 3

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            free_trial_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    cursor.execute("PRAGMA table_info(users)")

    columns = [
        row["name"]
        for row in cursor.fetchall()
    ]

    if "free_trial_used" not in columns:

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN free_trial_used INTEGER DEFAULT 0
        """)

    connection.commit()
    connection.close()


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
            free_trial_used
        )
        VALUES (?, ?, ?, 0, 0)
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))

    cursor.execute("""
        UPDATE users
        SET username = ?,
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
    """, (user_id,))

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
    """, (user_id,))

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


def has_free_trial(user_id):

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT free_trial_used
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()

    connection.close()

    if not row:
        return False

    return int(row["free_trial_used"] or 0) == 1


def mark_free_trial_used(user_id):

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET free_trial_used = 1
        WHERE user_id = ?
        AND free_trial_used = 0
    """, (user_id,))

    changed = cursor.rowcount > 0

    connection.commit()
    connection.close()

    return changed


def get_generation_lock(user_id):

    if user_id not in generation_locks:

        generation_locks[user_id] = threading.Lock()

    return generation_locks[user_id]


# =========================================================
# Flask / Render
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
# Hugging Face
# =========================================================

def get_hf_client():

    print("Connecting to Hugging Face Space...")

    if HF_TOKEN:

        client = Client(
            HF_SPACE,
            token=HF_TOKEN
        )

    else:

        client = Client(
            HF_SPACE
        )

    print("Hugging Face client connected.")

    return client


def normalize_video_result(result):

    if result is None:
        return None

    video_output = result

    if isinstance(result, tuple):

        if len(result) == 0:
            return None

        video_output = result[0]

    elif isinstance(result, list):

        if len(result) == 0:
            return None

        video_output = result[0]

    if isinstance(video_output, str):

        if os.path.exists(video_output):
            return video_output

        return None

    if isinstance(video_output, dict):

        path = video_output.get("path")

        if path and os.path.exists(path):
            return path

        url = video_output.get("url")

        if url:
            return url

    return None


def generate_wan_video(
    image_path,
    prompt,
    duration
):

    if duration not in ALLOWED_DURATIONS:

        duration = DEFAULT_DURATION

    print("=" * 60)

    print("WAN 2.2 GENERATION STARTED")

    print("Image:", image_path)

    print("Duration:", duration)

    print("Prompt:", prompt)

    print("=" * 60)

    client = get_hf_client()

    result = client.predict(

        input_image=handle_file(
            image_path
        ),

        prompt=prompt,

        steps=DEFAULT_STEPS,

        negative_prompt=DEFAULT_NEGATIVE_PROMPT,

        duration_seconds=float(
            duration
        ),

        guidance_scale=DEFAULT_GUIDANCE,

        guidance_scale_2=DEFAULT_GUIDANCE_2,

        seed=42,

        randomize_seed=True,

        api_name=HF_API_NAME
    )

    print(
        "WAN RESULT:",
        result
    )

    video_path = normalize_video_result(
        result
    )

    if not video_path:

        raise RuntimeError(
            "Wan 2.2 لم يرجع ملف فيديو صالح."
        )

    if not os.path.exists(video_path):

        raise RuntimeError(
            f"ملف الفيديو غير موجود: {video_path}"
        )

    file_size = os.path.getsize(
        video_path
    )

    print(
        "VIDEO GENERATED:",
        video_path
    )

    print(
        "VIDEO SIZE:",
        file_size
    )

    if file_size <= 0:

        raise RuntimeError(
            "الفيديو الناتج فارغ."
        )

    return video_path


# =========================================================
# القائمة الرئيسية
# =========================================================

def main_menu(user_id):

    balance = get_balance(user_id)

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

    if user_id == ADMIN_ID:

        keyboard.append([
            InlineKeyboardButton(
                "👑 لوحة الإدارة",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# الباقات
# =========================================================

def packages_menu():

    keyboard = []

    for package_id, package in PACKAGES.items():

        keyboard.append([
            InlineKeyboardButton(

                f"{package['name']} — "
                f"{package['videos']} فيديو — "
                f"{package['price']:,} ل.س",

                callback_data=
                f"package_{package_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back_main"
        )
    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# الإعدادات
# =========================================================

def settings_menu(state):

    duration = state.get(
        "duration",
        DEFAULT_DURATION
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
                "🤖 Wan 2.2 14B ⚡",
                callback_data="wan_info"
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
                "3 ثواني ⭐",
                callback_data="duration_3"
            )
        ],

        [
            InlineKeyboardButton(
                "4 ثواني",
                callback_data="duration_4"
            )
        ],

        [
            InlineKeyboardButton(
                "5 ثواني 🔥",
                callback_data="duration_5"
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
# START
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

    trial_used = has_free_trial(
        user.id
    )

    if not trial_used:

        trial_text = (
            "🎁 لديك تجربة مجانية متاحة!\n"
            "فيديو واحد لمدة 3 ثوانٍ."
        )

    else:

        trial_text = (
            "🎁 تم استخدام تجربتك المجانية."
        )

    await update.message.reply_text(

        "مرحباً 👋\n\n"

        "🎬 أهلاً بك في بوت تحويل الصور "
        "إلى فيديو بالذكاء الاصطناعي.\n\n"

        "🤖 المحرك: Wan 2.2 14B\n"
        "⚡ Lightning LoRA\n\n"

        f"💰 رصيدك: {balance} فيديو\n\n"

        f"{trial_text}\n\n"

        "📷 اضغط «إنشاء فيديو» للبدء.",

        reply_markup=main_menu(
            user.id
        )
    )


# =========================================================
# CANCEL
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    state = user_states.pop(
        user_id,
        None
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

    await update.message.reply_text(

        "❌ تم إلغاء العملية.",

        reply_markup=main_menu(
            user_id
        )
    )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    await update.message.reply_text(

        "ℹ️ طريقة الاستخدام:\n\n"

        "1️⃣ لديك تجربة مجانية لأول فيديو.\n"
        "2️⃣ اضغط «إنشاء فيديو».\n"
        "3️⃣ أرسل صورة.\n"
        "4️⃣ اكتب وصف الحركة.\n"
        "5️⃣ اضغط «إنشاء الفيديو».\n\n"

        "🎁 التجربة المجانية: 3 ثوانٍ.\n"
        "💳 بعد ذلك تحتاج إلى رصيد.\n\n"

        "⚙️ يمكنك اختيار 3 أو 4 أو 5 ثوانٍ.\n\n"

        "مثال للوصف:\n"
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

    cursor.execute("""
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
    """, (
        user_id,
        package_id,
        package["name"],
        package["videos"],
        package["price"],
    ))

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

        "📸 بعد التحويل أرسل صورة إثبات الدفع "
        "هنا في البوت.\n\n"

        "⚠️ سيتم إضافة الرصيد بعد تأكيد الدفع.",

        parse_mode="Markdown",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )

    user_states[user_id] = {

        "waiting_payment_proof": True,

        "payment_id": payment_id,
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

    cursor.execute("""
        SELECT *
        FROM payments
        WHERE id = ?
        AND user_id = ?
    """, (
        payment_id,
        user_id
    ))

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

                f"🧾 رقم الطلب: #{payment_id}\n"

                f"👤 المستخدم: {user_id}\n"

                f"📦 الباقة: {payment['package_name']}\n"

                f"🎬 الفيديوهات: {payment['videos']}\n"

                f"💰 السعر: {payment['price']:,} ل.س\n\n"

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

        cursor.execute("""
            SELECT *
            FROM payments
            WHERE id = ?
        """, (payment_id,))

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

        cursor.execute("""
            UPDATE payments
            SET status = 'approved'
            WHERE id = ?
            AND status = 'pending'
        """, (payment_id,))

        if cursor.rowcount != 1:

            connection.close()

            await query.answer(
                "تم التعامل مع الطلب مسبقاً.",
                show_alert=True
            )

            return

        cursor.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
        """, (
            payment["videos"],
            payment["user_id"]
        ))

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

        f"👤 المستخدم: {payment['user_id']}\n\n"

        f"📦 الباقة: {payment['package_name']}\n\n"

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

    cursor.execute("""
        SELECT *
        FROM payments
        WHERE id = ?
    """, (payment_id,))

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

    cursor.execute("""
        UPDATE payments
        SET status = 'rejected'
        WHERE id = ?
        AND status = 'pending'
    """, (payment_id,))

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
        FROM users
        WHERE free_trial_used = 1
    """)

    trials = cursor.fetchone()["total"]

    connection.close()

    await query.answer()

    await query.edit_message_text(

        "👑 لوحة الإدارة\n\n"

        f"👥 المستخدمون: {users}\n"

        f"🎁 التجارب المستخدمة: {trials}\n"

        f"⏳ طلبات الدفع المعلقة: {pending}\n"

        f"✅ المدفوعات المؤكدة: {approved}\n\n"

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
            "الاستخدام:\n/add USER_ID AMOUNT"
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
                "❌ هذا المستخدم غير موجود."
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
            "الاستخدام:\n/remove USER_ID AMOUNT"
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
                "❌ المستخدم غير موجود."
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
# رصيد مستخدم
# =========================================================

async def admin_balance(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 1:

        await update.message.reply_text(
            "الاستخدام:\n/balance USER_ID"
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

            f"👤 المستخدم: {user_id}\n"

            f"💰 الرصيد: {balance} فيديو"
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
        FROM users
        WHERE free_trial_used = 1
    """)

    trials = cursor.fetchone()["total"]

    connection.close()

    await update.message.reply_text(

        "📊 إحصائيات البوت\n\n"

        f"👥 المستخدمون: {users}\n\n"

        f"🎁 التجارب المجانية المستخدمة: {trials}\n\n"

        f"💰 الأرصدة الحالية: {total_balance}\n\n"

        f"🎬 الفيديوهات المباعة: {sold}\n\n"

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

    # فحص إثبات الدفع أولاً
    if await handle_payment_proof(
        update,
        context
    ):

        return

    state = user_states.get(
        user_id,
        {}
    )

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

    trial_available = not has_free_trial(
        user_id
    )

    balance = get_balance(
        user_id
    )

    if not trial_available and balance <= 0:

        await update.message.reply_text(

            "💳 لا يوجد لديك رصيد كافٍ.\n\n"

            "لقد استخدمت تجربتك المجانية.\n"

            "اشترِ رصيداً لإنشاء فيديو جديد.",

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

    photo = update.message.photo[-1]

    temp_image_path = None

    try:

        telegram_file = await photo.get_file()

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        ) as temp_file:

            temp_image_path = temp_file.name

        await telegram_file.download_to_drive(
            custom_path=temp_image_path
        )

        duration = state.get(
            "duration",
            DEFAULT_DURATION
        )

        if trial_available:

            duration = 3

        user_states[user_id] = {

            "image_path":
                temp_image_path,

            "waiting_for_prompt":
                True,

            "waiting_for_photo":
                False,

            "duration":
                duration,

            "is_free_trial":
                trial_available,
        }

        if trial_available:

            await update.message.reply_text(

                "🎁 هذه تجربتك المجانية!\n\n"

                "⏱️ المدة: 3 ثوانٍ\n\n"

                "✍️ الآن اكتب وصف الحركة التي تريدها."
            )

        else:

            await update.message.reply_text(

                "✅ وصلت الصورة!\n\n"

                f"⏱️ المدة: {duration} ثوانٍ\n\n"

                "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"

                "مثال:\n"

                "اجعل الشخص يبتسم ويحرك رأسه "
                "ببطء مع حركة كاميرا سينمائية "
                "خفيفة، وحافظ على ملامح الوجه."
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

    if "image_path" not in state:

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

    duration = state.get(
        "duration",
        DEFAULT_DURATION
    )

    if state.get(
        "is_free_trial"
    ):

        duration = 3

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

    if state.get(
        "is_free_trial"
    ):

        balance_text = (
            "🎁 تجربة مجانية — 3 ثوانٍ"
        )

    else:

        balance_text = (
            f"💰 رصيدك: "
            f"{get_balance(user_id)} فيديو"
        )

    await update.message.reply_text(

        "📝 تم استلام وصف الحركة:\n\n"

        f"{prompt}\n\n"

        f"⏱️ المدة: {duration} ثواني\n\n"

        f"{balance_text}\n\n"

        "اضغط «إنشاء الفيديو» للبدء.",

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

    await query.answer()

    user_id = query.from_user.id

    lock = get_generation_lock(
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

    image_path = None

    is_trial = False

    trial_marked = False

    charged = False

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

        is_trial = bool(
            state.get(
                "is_free_trial",
                False
            )
        )

        duration = state.get(
            "duration",
            DEFAULT_DURATION
        )

        if is_trial:

            duration = 3

        if duration not in ALLOWED_DURATIONS:

            duration = DEFAULT_DURATION

        # -------------------------------------------------
        # التحقق من الصورة
        # -------------------------------------------------

        if not image_path or not os.path.exists(
            image_path
        ):

            await query.edit_message_text(

                "❌ لم أجد الصورة.\n\n"

                "أرسل صورة جديدة وحاول مرة أخرى.",

                reply_markup=main_menu(
                    user_id
                )
            )

            return

        # -------------------------------------------------
        # التحقق من الوصف
        # -------------------------------------------------

        if not prompt:

            await query.edit_message_text(

                "❌ لم يتم العثور على وصف الحركة.",

                reply_markup=main_menu(
                    user_id
                )
            )

            return

        # -------------------------------------------------
        # التحقق من الرصيد
        # -------------------------------------------------

        if is_trial:

            if has_free_trial(
                user_id
            ):

                await query.edit_message_text(

                    "⚠️ تم استخدام التجربة المجانية مسبقاً.",

                    reply_markup=main_menu(
                        user_id
                    )
                )

                return

        else:

            balance = get_balance(
                user_id
            )

            if balance <= 0:

                await query.edit_message_text(

                    "💳 لا يوجد رصيد كافٍ.\n\n"

                    "اشترِ رصيداً أولاً.",

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
        # رسالة البداية
        # -------------------------------------------------

        if is_trial:

            await query.edit_message_text(

                "🎁 جاري تشغيل تجربتك المجانية...\n\n"

                "🤖 Wan 2.2 14B\n"
                "⚡ Lightning LoRA\n\n"

                "⏱️ المدة: 3 ثوانٍ\n\n"

                "قد يستغرق التوليد بعض الوقت."
            )

        else:

            await query.edit_message_text(

                "⏳ جاري إنشاء الفيديو...\n\n"

                "🤖 Wan 2.2 14B\n"
                "⚡ Lightning LoRA\n\n"

                f"⏱️ المدة: {duration} ثوانٍ\n\n"

                "قد يستغرق التوليد بعض الوقت."
            )

        # -------------------------------------------------
        # توليد الفيديو
        # -------------------------------------------------

        try:

            video_path = await asyncio.to_thread(

                generate_wan_video,

                image_path,

                prompt,

                duration
            )

        except Exception as error:

            print("=" * 60)

            print("❌ WAN GENERATION ERROR")

            print(
                "ERROR TYPE:",
                type(error).__name__
            )

            print(
                "ERROR:",
                repr(error)
            )

            print("=" * 60)

            await query.edit_message_text(

                "❌ تعذر إنشاء الفيديو.\n\n"

                "حدث خطأ أثناء الاتصال بـ Wan 2.2 "
                "أو أثناء التوليد.\n\n"

                "💳 لم يتم خصم أي رصيد.\n\n"

                "يمكنك المحاولة مرة أخرى."
            )

            return

        # -------------------------------------------------
        # التحقق من الفيديو
        # -------------------------------------------------

        if not video_path:

            await query.edit_message_text(

                "❌ لم يتم الحصول على فيديو من Wan 2.2.\n\n"

                "💳 لم يتم خصم الرصيد."
            )

            return

        if not os.path.exists(video_path):

            await query.edit_message_text(

                "❌ ملف الفيديو غير موجود.\n\n"

                "💳 لم يتم خصم الرصيد."
            )

            return

        # -------------------------------------------------
        # التجربة المجانية
        # -------------------------------------------------

        if is_trial:

            trial_marked = mark_free_trial_used(
                user_id
            )

            if not trial_marked:

                print(
                    "WARNING: Could not mark free trial."
                )

                await query.edit_message_text(

                    "⚠️ تم إنشاء الفيديو، "
                    "لكن حدث خطأ في تسجيل التجربة المجانية.\n\n"

                    "تم إيقاف الإرسال لحماية النظام.\n"

                    "تواصل مع الإدارة."
                )

                return

        # -------------------------------------------------
        # خصم الرصيد
        # -------------------------------------------------

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

                    "تم إيقاف إرسال الفيديو لحماية النظام.\n\n"

                    "تواصل مع الإدارة."
                )

                return

            charged = True

        # -------------------------------------------------
        # إرسال الفيديو
        # -------------------------------------------------

        await query.edit_message_text(

            "✅ تم إنشاء الفيديو!\n\n"

            "📤 جاري إرساله إليك..."
        )

        try:

            with open(
                video_path,
                "rb"
            ) as video_file:

                if is_trial:

                    caption = (

                        "🎁 انتهت تجربتك المجانية!\n\n"

                        "🎬 تم إنشاء الفيديو بنجاح.\n"

                        "⏱️ المدة: 3 ثوانٍ\n\n"

                        "💡 يمكنك الآن شراء رصيد "
                        "لإنشاء المزيد من الفيديوهات."
                    )

                else:

                    new_balance = get_balance(
                        user_id
                    )

                    caption = (

                        "🎬 تم إنشاء الفيديو بنجاح!\n\n"

                        "💳 تم خصم فيديو واحد.\n"

                        f"💰 رصيدك المتبقي: "
                        f"{new_balance} فيديو"
                    )

                await context.bot.send_video(

                    chat_id=user_id,

                    video=video_file,

                    caption=caption,

                    supports_streaming=True
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

                        "⚠️ تنبيه مهم\n\n"

                        "تم إنشاء فيديو بنجاح، "
                        "لكن تعذر إرساله للمستخدم.\n\n"

                        f"👤 المستخدم: {user_id}\n"

                        f"🎁 تجربة مجانية: "
                        f"{'نعم' if is_trial else 'لا'}\n"

                        f"💳 تم الخصم: "
                        f"{'نعم' if charged else 'لا'}\n\n"

                        "يرجى مراجعة الحالة."
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

        # -------------------------------------------------
        # النجاح الكامل
        # -------------------------------------------------

        if is_trial:

            await query.edit_message_text(

                "🎉 تم إنشاء تجربتك المجانية "
                "وإرسالها بنجاح! 🎬\n\n"

                "🎁 انتهت تجربتك المجانية.\n\n"

                "يمكنك الآن شراء رصيد وإنشاء "
                "المزيد من الفيديوهات بواسطة "
                "Wan 2.2 14B ⚡",

                reply_markup=InlineKeyboardMarkup([

                    [
                        InlineKeyboardButton(
                            "💰 شراء رصيد",
                            callback_data="buy"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "🏠 القائمة الرئيسية",
                            callback_data="back_main"
                        )
                    ]

                ])
            )

        else:

            new_balance = get_balance(
                user_id
            )

            await query.edit_message_text(

                "✅ تم إنشاء الفيديو وإرساله بنجاح! 🎬\n\n"

                f"💰 رصيدك المتبقي: "
                f"{new_balance} فيديو",

                reply_markup=main_menu(
                    user_id
                )
            )

        # -------------------------------------------------
        # تنظيف الحالة
        # -------------------------------------------------

        user_states.pop(
            user_id,
            None
        )

    finally:

        # -------------------------------------------------
        # حذف الصورة المؤقتة
        # -------------------------------------------------

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
                    "TEMP IMAGE DELETE ERROR:",
                    repr(error)
                )

        # -------------------------------------------------
        # تحرير القفل
        # -------------------------------------------------

        try:

            lock.release()

            print(
                "🔓 GENERATION LOCK RELEASED"
            )

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

    # -----------------------------------------------------
    # شراء
    # -----------------------------------------------------

    if data == "buy":

        await show_buy(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # الباقة
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # تأكيد الدفع
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # رفض الدفع
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # الإدارة
    # -----------------------------------------------------

    if data == "admin":

        await admin_panel(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # إنشاء فيديو
    # -----------------------------------------------------

    if data == "new_video":

        await query.answer()

        trial_available = not has_free_trial(
            user_id
        )

        balance = get_balance(
            user_id
        )

        if not trial_available and balance <= 0:

            await query.edit_message_text(

                "💳 رصيدك صفر.\n\n"

                "🎁 لقد استخدمت تجربتك المجانية.\n\n"

                "اشترِ رصيداً لإنشاء فيديو جديد.",

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
            DEFAULT_DURATION
        )

        if duration not in ALLOWED_DURATIONS:

            duration = DEFAULT_DURATION

        user_states[user_id] = {

            "waiting_for_photo":
                True,

            "duration":
                duration,

            "is_free_trial":
                trial_available,
        }

        if trial_available:

            await query.edit_message_text(

                "🎁 لديك تجربة مجانية!\n\n"

                "📷 أرسل الصورة التي تريد "
                "تحويلها إلى فيديو.\n\n"

                "⏱️ التجربة المجانية = 3 ثوانٍ\n\n"

                "⚡ Wan 2.2 14B"
            )

        else:

            await query.edit_message_text(

                "📷 أرسل الصورة التي تريد "
                "تحويلها إلى فيديو.\n\n"

                f"💰 رصيدك: {balance} فيديو\n\n"

                f"⏱️ المدة: {duration} ثوانٍ\n\n"

                "⚡ Wan 2.2 14B"
            )

        return

    # -----------------------------------------------------
    # الرصيد
    # -----------------------------------------------------

    if data == "balance":

        await query.answer()

        balance = get_balance(
            user_id
        )

        trial_used = has_free_trial(
            user_id
        )

        trial_text = (

            "❌ مستخدمة"

            if trial_used

            else

            "🎁 متاحة — 3 ثوانٍ"
        )

        await query.edit_message_text(

            "💳 معلومات رصيدك:\n\n"

            f"🎬 الرصيد المدفوع: "
            f"{balance} فيديو\n\n"

            f"🎁 التجربة المجانية: "
            f"{trial_text}",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # -----------------------------------------------------
    # الإعدادات
    # -----------------------------------------------------

    if data == "settings":

        await query.answer()

        state = user_states.setdefault(

            user_id,

            {
                "duration":
                    DEFAULT_DURATION
            }
        )

        if "duration" not in state:

            state["duration"] = DEFAULT_DURATION

        await query.edit_message_text(

            "⚙️ إعدادات الفيديو:\n\n"

            "🤖 المحرك: Wan 2.2 14B\n"
            "⚡ Lightning LoRA\n\n"

            "اختر الإعداد الذي تريد تغييره.",

            reply_markup=settings_menu(
                state
            )
        )

        return

    # -----------------------------------------------------
    # المدد
    # -----------------------------------------------------

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

        if duration not in ALLOWED_DURATIONS:

            await query.answer(
                "هذه المدة غير متاحة.",
                show_alert=True
            )

            return

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["duration"] = duration

        await query.answer(
            "تم تغيير المدة."
        )

        await query.edit_message_text(

            f"✅ تم اختيار {duration} ثانية.",

            reply_markup=settings_menu(
                state
            )
        )

        return

    # -----------------------------------------------------
    # معلومات Wan
    # -----------------------------------------------------

    if data == "wan_info":

        await query.answer()

        await query.edit_message_text(

            "🤖 محرك الفيديو\n\n"

            "Wan 2.2 14B\n"
            "⚡ Lightning LoRA\n"
            "🚀 توليد سريع باستخدام FP8\n\n"

            "📷 صورة + وصف الحركة\n"
            "⬇️\n"
            "🎬 فيديو AI\n\n"

            "المدد المدعومة في البوت:\n"
            "3 / 4 / 5 ثوانٍ",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "⬅️ الإعدادات",
                        callback_data="settings"
                    )
                ]

            ])
        )

        return

    # -----------------------------------------------------
    # المساعدة
    # -----------------------------------------------------

    if data == "help":

        await query.answer()

        await query.edit_message_text(

            "ℹ️ طريقة الاستخدام:\n\n"

            "1️⃣ لديك تجربة مجانية 3 ثوانٍ.\n"
            "2️⃣ اضغط «🎬 إنشاء فيديو».\n"
            "3️⃣ أرسل صورة.\n"
            "4️⃣ اكتب وصف الحركة.\n"
            "5️⃣ اضغط «🎬 إنشاء الفيديو».\n\n"

            "⚙️ المدد المدعومة: 3 / 4 / 5 ثوانٍ.\n\n"

            "🎁 أول فيديو مجاني.\n"
            "💳 بعد ذلك تحتاج إلى رصيد.",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # -----------------------------------------------------
    # إلغاء التوليد
    # -----------------------------------------------------

    if data == "cancel_generation":

        await query.answer()

        state = user_states.pop(
            user_id,
            None
        )

        image_path = None

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

            reply_markup=main_menu(
                user_id
            )
        )

        return

    # -----------------------------------------------------
    # الرئيسية
    # -----------------------------------------------------

    if data == "back_main":

        await query.answer()

        await query.edit_message_text(

            "🏠 القائمة الرئيسية",

            reply_markup=main_menu(
                user_id
            )
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
# تشغيل البوت
# =========================================================

def run_bot():

    bot_app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # الأوامر
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # الإدارة
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # الصور
    # -----------------------------------------------------

    bot_app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # -----------------------------------------------------
    # النصوص
    # -----------------------------------------------------

    bot_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # -----------------------------------------------------
    # الأزرار
    # -----------------------------------------------------

    bot_app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # -----------------------------------------------------
    # الأخطاء
    # -----------------------------------------------------

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
