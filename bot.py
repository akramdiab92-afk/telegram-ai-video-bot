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

# معرف المدير
ADMIN_ID = 625548190

MAGIC_HOUR_BASE = "https://api.magichour.ai/v1"

DB_FILE = "bot_data.db"

app_web = Flask(__name__)

user_states = {}


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
    connection = sqlite3.connect(DB_FILE)
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

    connection.commit()
    connection.close()


def ensure_user(user):

    if not user:
        return

    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, balance)
        VALUES (?, ?, ?, 0)
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))

    cursor.execute("""
        UPDATE users
        SET username = ?, first_name = ?
        WHERE user_id = ?
    """, (
        user.username or "",
        user.first_name or "",
        user.id,
    ))

    connection.commit()
    connection.close()


def get_balance(user_id):

    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:
        return 0

    return row["balance"]


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

    connection.commit()
    connection.close()


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

    changed = cursor.rowcount

    connection.commit()
    connection.close()

    return changed > 0


# =========================================================
# Render Web Server
# =========================================================

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
# Magic Hour
# =========================================================

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
                    "extension": extension
                }
            ]
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return (
        data["items"][0]["upload_url"],
        data["items"][0]["file_path"]
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
    duration=5,
    resolution="480p"
):

    payload = {
        "assets": {
            "image_file_path": file_path
        },
        "end_seconds": duration,
        "name": "Telegram AI Video",
        "resolution": resolution,
    }

    # إضافة الوصف بالطريقة المستخدمة في النسخة الحالية
    payload["style"] = {
        "prompt": prompt
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
                "Authorization": f"Bearer {MAGIC_HOUR_API_KEY}"
            },
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        status = data.get("status")

        print("VIDEO STATUS:", status)

        if status == "complete":

            downloads = data.get("downloads", [])

            if downloads:
                return downloads[0]["url"], data

            return None, data

        if status in [
            "error",
            "failed",
            "canceled"
        ]:

            print("VIDEO ERROR:", data)

            return None, data

        time.sleep(10)

    return None, None


# =========================================================
# القوائم
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
        ]
    ]

    if user_id == ADMIN_ID:

        keyboard.append([
            InlineKeyboardButton(
                "👑 لوحة الإدارة",
                callback_data="admin"
            )
        ])

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


def settings_menu(state):

    duration = state.get("duration", 5)
    resolution = state.get("resolution", "480p")

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

    return InlineKeyboardMarkup(keyboard)


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
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# Start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    ensure_user(user)

    user_states.pop(user.id, None)

    balance = get_balance(user.id)

    await update.message.reply_text(
        "مرحباً 👋\n\n"
        "🎬 أهلاً بك في بوت تحويل الصور إلى فيديو "
        "بالذكاء الاصطناعي.\n\n"
        f"💰 رصيدك الحالي: {balance} فيديو\n\n"
        "📷 أرسل صورة للبدء.",
        reply_markup=main_menu(user.id)
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user_states.pop(user_id, None)

    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=main_menu(user_id)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    await update.message.reply_text(
        "ℹ️ طريقة الاستخدام:\n\n"
        "1️⃣ اشحن رصيدك.\n"
        "2️⃣ اضغط إنشاء فيديو.\n"
        "3️⃣ أرسل صورة.\n"
        "4️⃣ اكتب وصف الحركة.\n"
        "5️⃣ اضغط إنشاء الفيديو.\n\n"
        "مثال:\n"
        "اجعل الأم والابنة تقتربان من بعضهما "
        "ثم تتعانقان بشكل طبيعي ودافئ، "
        "مع حركة كاميرا سينمائية خفيفة "
        "والحفاظ على ملامح الوجه.",
        reply_markup=main_menu(user_id)
    )


# =========================================================
# شراء الرصيد
# =========================================================

async def show_buy(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "💰 اختر الباقة التي تريد شراءها:\n\n"
        "بعد اختيار الباقة سيظهر لك "
        "طريقة الدفع وإرسال إثبات التحويل.",
        reply_markup=packages_menu()
    )


async def create_payment(update, context, package_id):

    query = update.callback_query

    user_id = query.from_user.id

    package = PACKAGES.get(package_id)

    if not package:

        await query.answer(
            "الباقة غير موجودة.",
            show_alert=True
        )

        return

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

    await query.edit_message_text(
        f"🧾 طلب شراء رقم #{payment_id}\n\n"
        f"📦 {package['name']}\n"
        f"🎬 الرصيد: {package['videos']} فيديو\n"
        f"💰 السعر: {package['price']:,} ل.س\n\n"
        "💳 طريقة الدفع:\n"
        "قم بالتحويل إلى وسيلة الدفع التي تحددها أنت.\n\n"
        "📸 بعد التحويل أرسل صورة إثبات الدفع "
        "هنا في البوت.\n\n"
        "⚠️ سيتم إضافة الرصيد بعد تأكيد الدفع.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data="back_main"
                )
            ]
        ])
    )

    user_states[user_id] = {
        "waiting_payment_proof": True,
        "payment_id": payment_id,
    }


# =========================================================
# إثبات الدفع
# =========================================================

async def handle_payment_proof(update, context):

    user_id = update.effective_user.id

    state = user_states.get(user_id, {})

    if not state.get("waiting_payment_proof"):

        return False

    payment_id = state.get("payment_id")

    if not payment_id:

        return False

    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT * FROM payments WHERE id = ? AND user_id = ?",
        (
            payment_id,
            user_id,
        )
    )

    payment = cursor.fetchone()

    connection.close()

    if not payment:

        return False

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
                        callback_data=f"approve_{payment_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ رفض",
                        callback_data=f"reject_{payment_id}"
                    )
                ]
            ])
        )

        await update.message.reply_text(
            "✅ تم إرسال إثبات الدفع.\n\n"
            "⏳ سيتم مراجعة التحويل وإضافة الرصيد "
            "بعد التأكيد."
        )

        user_states.pop(user_id, None)

        return True

    except Exception as error:

        print("PAYMENT PROOF ERROR:", error)

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إرسال إثبات الدفع."
        )

        return True


# =========================================================
# تأكيد الدفع
# =========================================================

async def approve_payment(update, context, payment_id):

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
        "SELECT * FROM payments WHERE id = ?",
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

    cursor.execute("""
        UPDATE payments
        SET status = 'approved'
        WHERE id = ?
    """, (
        payment_id,
    ))

    connection.commit()
    connection.close()

    add_balance(
        payment["user_id"],
        payment["videos"]
    )

    new_balance = get_balance(
        payment["user_id"]
    )

    await query.answer(
        "تمت إضافة الرصيد.",
        show_alert=True
    )

    await query.edit_message_text(
        f"✅ تم تأكيد الطلب #{payment_id}\n\n"
        f"👤 المستخدم: {payment['user_id']}\n"
        f"🎬 تمت إضافة: {payment['videos']} فيديو\n"
        f"💰 الرصيد الجديد: {new_balance}"
    )

    try:

        await context.bot.send_message(
            chat_id=payment["user_id"],
            text=(
                "🎉 تم تأكيد الدفع!\n\n"
                f"📦 الباقة: {payment['package_name']}\n"
                f"🎬 تمت إضافة: {payment['videos']} فيديو\n\n"
                f"💰 رصيدك الحالي: {new_balance} فيديو"
            ),
            reply_markup=main_menu(
                payment["user_id"]
            )
        )

    except Exception as error:

        print("USER NOTIFICATION ERROR:", error)


async def reject_payment(update, context, payment_id):

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
        "SELECT * FROM payments WHERE id = ?",
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

    cursor.execute("""
        UPDATE payments
        SET status = 'rejected'
        WHERE id = ?
    """, (
        payment_id,
    ))

    connection.commit()
    connection.close()

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

        print("REJECT NOTIFICATION ERROR:", error)


# =========================================================
# الإدارة
# =========================================================

async def admin_panel(update, context):

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
        "SELECT COUNT(*) AS total FROM users"
    )

    users = cursor.fetchone()["total"]

    cursor.execute(
        "SELECT COUNT(*) AS total FROM payments WHERE status='pending'"
    )

    pending = cursor.fetchone()["total"]

    cursor.execute(
        "SELECT COUNT(*) AS total FROM payments WHERE status='approved'"
    )

    approved = cursor.fetchone()["total"]

    connection.close()

    await query.answer()

    await query.edit_message_text(
        "👑 لوحة الإدارة\n\n"
        f"👥 المستخدمون: {users}\n"
        f"⏳ طلبات الدفع المعلقة: {pending}\n"
        f"✅ المدفوعات المؤكدة: {approved}\n\n"
        "الأوامر الإدارية:\n\n"
        "/add USER_ID AMOUNT\n"
        "إضافة رصيد لمستخدم\n\n"
        "/remove USER_ID AMOUNT\n"
        "سحب رصيد من مستخدم\n\n"
        "/balance USER_ID\n"
        "عرض رصيد مستخدم\n\n"
        "/stats\n"
        "إحصائيات البوت",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ الرئيسية",
                    callback_data="back_main"
                )
            ]
        ])
    )


async def admin_add(update, context):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/add USER_ID AMOUNT"
        )

        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

        add_balance(
            user_id,
            amount
        )

        balance = get_balance(user_id)

        await update.message.reply_text(
            "✅ تمت إضافة الرصيد.\n\n"
            f"👤 المستخدم: {user_id}\n"
            f"➕ المبلغ: {amount}\n"
            f"💰 الرصيد الجديد: {balance}"
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 تمت إضافة رصيد إلى حسابك.\n\n"
                    f"➕ الرصيد المضاف: {amount} فيديو\n"
                    f"💰 رصيدك الحالي: {balance} فيديو"
                )
            )

        except Exception:
            pass

    except Exception:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )


async def admin_remove(update, context):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/remove USER_ID AMOUNT"
        )

        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

        success = remove_balance(
            user_id,
            amount
        )

        if not success:

            await update.message.reply_text(
                "❌ المستخدم لا يملك رصيدًا كافيًا."
            )

            return

        balance = get_balance(user_id)

        await update.message.reply_text(
            "✅ تم سحب الرصيد.\n\n"
            f"👤 المستخدم: {user_id}\n"
            f"➖ المبلغ: {amount}\n"
            f"💰 الرصيد الجديد: {balance}"
        )

    except Exception:

        await update.message.reply_text(
            "❌ تأكد من كتابة الأرقام بشكل صحيح."
        )


async def admin_balance(update, context):

    if update.effective_user.id != ADMIN_ID:

        return

    if len(context.args) != 1:

        await update.message.reply_text(
            "الاستخدام:\n"
            "/balance USER_ID"
        )

        return

    try:

        user_id = int(context.args[0])

        balance = get_balance(user_id)

        await update.message.reply_text(
            f"👤 المستخدم: {user_id}\n"
            f"💰 الرصيد: {balance} فيديو"
        )

    except Exception:

        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح."
        )


async def admin_stats(update, context):

    if update.effective_user.id != ADMIN_ID:

        return

    connection = db()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT COUNT(*) AS total FROM users"
    )
    users = cursor.fetchone()["total"]

    cursor.execute(
        "SELECT COALESCE(SUM(balance),0) AS total FROM users"
    )
    total_balance = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(videos),0) AS total
        FROM payments
        WHERE status='approved'
    """)

    sold = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(price),0) AS total
        FROM payments
        WHERE status='approved'
    """)

    revenue = cursor.fetchone()["total"]

    connection.close()

    await update.message.reply_text(
        "📊 إحصائيات البوت\n\n"
        f"👥 المستخدمون: {users}\n"
        f"💰 مجموع الأرصدة الحالية: {total_balance}\n"
        f"🎬 الفيديوهات المباعة: {sold}\n"
        f"💵 إجمالي المبيعات: {revenue:,} ل.س"
    )


# =========================================================
# إنشاء الفيديو
# =========================================================

async def handle_photo(update, context):

    user_id = update.effective_user.id

    ensure_user(
        update.effective_user
    )

    # إذا كان المستخدم يرسل إثبات دفع
    if await handle_payment_proof(
        update,
        context
    ):

        return

    balance = get_balance(user_id)

    if balance <= 0:

        await update.message.reply_text(
            "💳 لا يوجد لديك رصيد كافٍ.\n\n"
            "اشترِ رصيدًا أولاً حتى تتمكن من إنشاء الفيديو.",
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

    photo = update.message.photo[-1]

    try:

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        user_states[user_id] = {
            "image": bytes(image_bytes),
            "waiting_for_prompt": True,
            "duration": 5,
            "resolution": "480p",
        }

        await update.message.reply_text(
            "✅ وصلت الصورة!\n\n"
            "✍️ الآن اكتب وصف الحركة التي تريدها.\n\n"
            "مثال:\n"
            "اجعل الأم والابنة تقتربان من بعضهما "
            "ثم تتعانقان بشكل طبيعي ودافئ، "
            "مع حركة كاميرا سينمائية خفيفة، "
            "وحافظ على ملامح الوجه كما هي."
        )

    except Exception as error:

        print("PHOTO ERROR:", error)

        await update.message.reply_text(
            "❌ حدث خطأ أثناء استقبال الصورة."
        )


async def handle_text(update, context):

    user_id = update.effective_user.id

    ensure_user(
        update.effective_user
    )

    state = user_states.get(
        user_id,
        {}
    )

    if state.get("waiting_payment_proof"):

        await update.message.reply_text(
            "📸 أرسل صورة إثبات الدفع."
        )

        return

    if "image" not in state:

        await update.message.reply_text(
            "📷 أرسل صورة أولاً.",
            reply_markup=main_menu(user_id)
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
        "📝 تم استلام الوصف:\n\n"
        f"{prompt}\n\n"
        f"💰 رصيدك الحالي: {get_balance(user_id)} فيديو\n\n"
        "إذا كان كل شيء مناسبًا اضغط إنشاء الفيديو.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# توليد الفيديو
# =========================================================

async def generate_video(update, context):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = user_states.get(
        user_id,
        {}
    )

    balance = get_balance(user_id)

    if balance <= 0:

        await query.edit_message_text(
            "💳 لا يوجد Credits/رصيد كافٍ.\n\n"
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

    if "image" not in state or "prompt" not in state:

        await query.edit_message_text(
            "❌ أرسل صورة واكتب وصف الحركة أولاً."
        )

        return

    await query.edit_message_text(
        "⏳ جاري إنشاء الفيديو...\n\n"
        "🎬 يرجى الانتظار حتى انتهاء المعالجة."
    )

    try:

        image_bytes = state["image"]
        prompt = state["prompt"]

        duration = state.get(
            "duration",
            5
        )

        resolution = state.get(
            "resolution",
            "480p"
        )

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
            duration=duration,
            resolution=resolution
        )

        video_id = video_data["id"]

        print("VIDEO ID:", video_id)

        # الانتظار
        video_url, final_data = wait_for_video(
            video_id
        )

        if not video_url:

            await query.edit_message_text(
                "❌ لم يتم إنشاء الفيديو.\n\n"
                "لم يتم خصم الرصيد لأن العملية لم تنجح."
            )

            return

        # تحميل الفيديو
        video_response = requests.get(
            video_url,
            timeout=180
        )

        video_response.raise_for_status()

        # الخصم بعد النجاح فقط
        removed = remove_balance(
            user_id,
            1
        )

        if not removed:

            await query.edit_message_text(
                "⚠️ تم إنشاء الفيديو لكن تعذر خصم الرصيد."
            )

            return

        new_balance = get_balance(
            user_id
        )

        await context.bot.send_video(
            chat_id=user_id,
            video=video_response.content,
            caption=(
                "🎬 تم إنشاء الفيديو بنجاح!\n\n"
                "💳 تم خصم فيديو واحد.\n"
                f"💰 رصيدك المتبقي: {new_balance} فيديو"
            )
        )

        user_states.pop(
            user_id,
            None
        )

        await query.edit_message_text(
            "✅ تم إرسال الفيديو بنجاح! 🎬\n\n"
            f"💰 رصيدك المتبقي: {new_balance} فيديو",
            reply_markup=main_menu(user_id)
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

        await query.edit_message_text(
            "❌ Magic Hour رفض الطلب.\n\n"
            "جرّب استخدام:\n"
            "480p + 5 ثواني + الإعدادات الافتراضية."
        )

    except Exception as error:

        print("GENERATION ERROR:", error)

        await query.edit_message_text(
            "❌ حدث خطأ أثناء إنشاء الفيديو.\n\n"
            "لم يتم خصم الرصيد."
        )


# =========================================================
# الأزرار
# =========================================================

async def button_handler(update, context):

    query = update.callback_query

    user_id = query.from_user.id

    ensure_user(
        query.from_user
    )

    data = query.data

    # شراء
    if data == "buy":

        await show_buy(
            update,
            context
        )

        return

    # اختيار باقة
    if data.startswith("package_"):

        package_id = data.replace(
            "package_",
            ""
        )

        await create_payment(
            update,
            context,
            package_id
        )

        return

    # تأكيد الدفع
    if data.startswith("approve_"):

        payment_id = int(
            data.replace(
                "approve_",
                ""
            )
        )

        await approve_payment(
            update,
            context,
            payment_id
        )

        return

    # رفض الدفع
    if data.startswith("reject_"):

        payment_id = int(
            data.replace(
                "reject_",
                ""
            )
        )

        await reject_payment(
            update,
            context,
            payment_id
        )

        return

    # الإدارة
    if data == "admin":

        await admin_panel(
            update,
            context
        )

        return

    # إنشاء
    if data == "new_video":

        await query.answer()

        balance = get_balance(user_id)

        if balance <= 0:

            await query.edit_message_text(
                "💳 رصيدك صفر.\n\n"
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

        user_states[user_id] = {
            "waiting_for_photo": True,
            "duration": 5,
            "resolution": "480p",
        }

        await query.edit_message_text(
            "📷 أرسل الصورة التي تريد تحويلها إلى فيديو.\n\n"
            f"💰 رصيدك: {balance} فيديو"
        )

        return

    # الرصيد
    if data == "balance":

        await query.answer()

        balance = get_balance(user_id)

        await query.edit_message_text(
            "💳 رصيدك الحالي:\n\n"
            f"🎬 {balance} فيديو",
            reply_markup=main_menu(user_id)
        )

        return

    # الإعدادات
    if data == "settings":

        await query.answer()

        state = user_states.setdefault(
            user_id,
            {
                "duration": 5,
                "resolution": "480p",
            }
        )

        await query.edit_message_text(
            "⚙️ إعدادات الفيديو:",
            reply_markup=settings_menu(state)
        )

        return

    # المدة
    if data == "durations":

        await query.answer()

        await query.edit_message_text(
            "⏱️ اختر مدة الفيديو:",
            reply_markup=duration_menu()
        )

        return

    if data.startswith("duration_"):

        duration = int(
            data.replace(
                "duration_",
                ""
            )
        )

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["duration"] = duration

        await query.answer(
            f"تم اختيار {duration} ثانية."
        )

        await query.edit_message_text(
            f"✅ المدة: {duration} ثانية",
            reply_markup=settings_menu(state)
        )

        return

    # الدقة
    if data == "resolutions":

        await query.answer()

        await query.edit_message_text(
            "📺 اختر الدقة:",
            reply_markup=resolution_menu()
        )

        return

    if data.startswith("resolution_"):

        resolution = data.replace(
            "resolution_",
            ""
        ) + "p"

        state = user_states.setdefault(
            user_id,
            {}
        )

        state["resolution"] = resolution

        await query.answer(
            f"تم اختيار {resolution}"
        )

        await query.edit_message_text(
            f"✅ الدقة: {resolution}",
            reply_markup=settings_menu(state)
        )

        return

    # المساعدة
    if data == "help":

        await query.answer()

        await query.edit_message_text(
            "ℹ️ أرسل صورة ثم اكتب وصف الحركة.\n\n"
            "مثال:\n"
            "اجعل الشخص يبتسم ويتحرك بشكل طبيعي "
            "مع حركة كاميرا سينمائية خفيفة "
            "مع الحفاظ على ملامح الوجه.",
            reply_markup=main_menu(user_id)
        )

        return

    # إلغاء
    if data == "cancel_generation":

        await query.answer()

        user_states.pop(
            user_id,
            None
        )

        await query.edit_message_text(
            "❌ تم إلغاء العملية.",
            reply_markup=main_menu(user_id)
        )

        return

    # رجوع
    if data == "back_main":

        await query.answer()

        await query.edit_message_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_menu(user_id)
        )

        return

    # إنشاء الفيديو
    if data == "generate":

        await generate_video(
            update,
            context
        )

        return


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

    # أوامر الإدارة
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

    bot_app.run_polling(
        stop_signals=None
    )


# =========================================================
# البداية
# =========================================================

if __name__ == "__main__":

    init_db()

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    run_web()
