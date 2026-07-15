import os
import random
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
from flask import Flask
from threading import Thread

# 1. ለRender ዌብ ሰርቨር ማዘጋጃ
app = Flask('')

@app.route('/')
def home():
    return "የኢትዮ ላቭ ቴሌግራም ቦት በሰላም እየሰራ ነው!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. የቦት ቶከን ማረጋገጫ
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("እባክዎ 'TELEGRAM_BOT_TOKEN' የሚለውን Environment Variable በRender ላይ ያስገቡ!")

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = 'ethio_love_bot.db'

# የአድሚን ቴሌግራም ID
ADMIN_ID = 1883279841

# ጊዜያዊ ምዝገባ መረጃዎችን መያዣ
user_states = {}

# 👑 የVIP ዋጋ እና የክፍያ መረጃ (እባክዎ ይህንን ያዘምኑ)
VIP_PRICE_ETB = 100
VIP_DURATION_DAYS = 30
VIP_PAYMENT_INFO_AM = (
    "💳 **የክፍያ መረጃ**\n"
    "Telebirr: 0900000000 (ስም)\n"
    "ባንክ፦ CBC 1000000000000 (ስም)\n\n"
    "⚠️ ከላይ ያለውን አካውንት በመጠቀም ይክፈሉ እና የክፍያ ደረሰኝ (screenshot) ከታች ይላኩ።"
)
VIP_PAYMENT_INFO_EN = (
    "💳 **Payment Info**\n"
    "Telebirr: 0900000000 (Name)\n"
    "Bank: CBC 1000000000000 (Name)\n\n"
    "⚠️ Pay using the account above, then send a screenshot of your receipt below."
)

# 3. የዳታቤዝ (Database) ግንኙነት መቆጣጠሪያዎች
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            fullname TEXT,
            gender TEXT,
            looking_for TEXT,
            age INTEGER,
            city TEXT,
            religion TEXT,
            zodiac TEXT,
            photo_id TEXT,
            language TEXT DEFAULT 'am',
            is_vip INTEGER DEFAULT 0,
            vip_expiry TEXT,
            registered_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_views (
            user_id INTEGER,
            view_date TEXT,
            view_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, view_date)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_profiles (
            viewer_id INTEGER,
            viewed_id INTEGER,
            seen_at TEXT,
            PRIMARY KEY (viewer_id, viewed_id)
        )
    ''')
    conn.commit()
    conn.close()

# ቦቱ ሲነሳ ዳታቤዙን ያዘጋጃል
init_db()

# 4. አጋዥ ተግባራት (Helper Functions)
def is_registered(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user is not None

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_user_language(user_id):
    user = get_user(user_id)
    return user['language'] if user else 'am'

def check_vip_status(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return False

    is_vip = user['is_vip']
    vip_expiry_str = user['vip_expiry']

    if is_vip == 1 and vip_expiry_str:
        try:
            expiry_date = datetime.strptime(vip_expiry_str, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date:
                conn.close()
                return True
            else:
                cursor.execute("UPDATE users SET is_vip = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
        except ValueError:
            pass

    conn.close()
    return False

def increment_and_check_profile_view(user_id):
    if check_vip_status(user_id):
        return True

    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT view_count FROM daily_views WHERE user_id = ? AND view_date = ?", (user_id, today))
    row = cursor.fetchone()

    if row:
        current_views = row['view_count']
        if current_views >= 30:
            conn.close()
            return False
        else:
            cursor.execute("UPDATE daily_views SET view_count = view_count + 1 WHERE user_id = ? AND view_date = ?", (user_id, today))
    else:
        cursor.execute("INSERT INTO daily_views (user_id, view_date, view_count) VALUES (?, ?, 1)", (user_id, today))

    conn.commit()
    conn.close()
    return True

def get_next_profile(viewer_id):
    """Pick a profile the viewer hasn't seen yet, respecting looking_for/gender."""
    viewer = get_user(viewer_id)
    if not viewer:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    looking_for = viewer['looking_for']
    query = "SELECT * FROM users WHERE user_id != ?"
    params = [viewer_id]

    if looking_for not in ('ሁለቱንም', 'Both'):
        query += " AND gender = ?"
        params.append(looking_for)

    query += """
        AND user_id NOT IN (
            SELECT viewed_id FROM seen_profiles WHERE viewer_id = ?
        )
    """
    params.append(viewer_id)

    cursor.execute(query, params)
    candidates = cursor.fetchall()
    conn.close()

    if not candidates:
        return None
    return random.choice(candidates)

def mark_profile_seen(viewer_id, viewed_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO seen_profiles (viewer_id, viewed_id, seen_at) VALUES (?, ?, ?)",
        (viewer_id, viewed_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

# =========================================================
# 5. ደረጃ በደረጃ የምዝገባ ሂደት (BILINGUAL REGISTRATION)
# =========================================================

# 1️⃣ /start ➔ ቋንቋ ማስመረጫ
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id

    if is_registered(user_id):
        lang = get_user_language(user_id)

        if lang == 'am':
            welcome_text = (
                "👋 **እንኳን ወደ Ethio Love Bot በድጋሚ በደህና መጡ!**\n\n"
                "🔍 የሌሎችን መገለጫ ለመፈለግ ➔ /browse ን ይጠቀሙ\n"
                "👤 የራስዎን መገለጫ ለማየት ➔ /profile ን ይጠቀሙ\n"
                "⚙️ መረጃ ለማስተካከል ➔ /edit ን ይጠቀሙ\n"
                "👑 ቪአይፒ ለመሆን ➔ /vip ን ይጠቀሙ"
            )
        else:
            welcome_text = (
                "👋 **Welcome back to Ethio Love Bot!**\n\n"
                "🔍 Browse other profiles ➔ /browse\n"
                "👤 View your profile ➔ /profile\n"
                "⚙️ Edit your profile ➔ /edit\n"
                "👑 Become a VIP ➔ /vip"
            )
        bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")
        return

    # ቋንቋ እንዲመርጥ አዝራር ማሳየት
    user_states[user_id] = {'step': 'get_lang'}
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_am = types.InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")
    btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    markup.add(btn_am, btn_en)

    bot.send_message(
        message.chat.id,
        "💖 **Welcome to Ethio Love Bot! / እንኳን ወደ ኢትዮ ላቭ በሰላም መጡ!** 💖\n\n"
        "Please select your language / እባክዎ ቋንቋ ይምረጡ፦",
        reply_markup=markup
    )

# 2️⃣ /profile ➔ የራስን መገለጫ ማሳየት
@bot.message_handler(commands=['profile'])
def profile_cmd(message):
    user_id = message.from_user.id
    if not is_registered(user_id):
        bot.reply_to(message, "እባክዎ መጀመሪያ /start በመጫን ይመዝገቡ።" )
        return

    user = get_user(user_id)
    lang = user['language']
    is_vip = check_vip_status(user_id)

    if lang == 'am':
        vip_line = "👑 VIP አባል" if is_vip else "🔓 መደበኛ አባል"
        caption = (
            f"👤 **{user['fullname']}**\n"
            f"🎂 እድሜ፦ {user['age']}\n"
            f"📍 ከተማ፦ {user['city']}\n"
            f"⛪️ ሃይማኖት፦ {user['religion']}\n"
            f"⭐️ ኮከብ፦ {user['zodiac']}\n"
            f"⚧️ ጾታ፦ {user['gender']}\n"
            f"🔍 ፍላጎት፦ {user['looking_for']}\n\n"
            f"{vip_line}\n\n"
            f"⚙️ መረጃ ለማስተካከል ➔ /edit"
        )
    else:
        vip_line = "👑 VIP Member" if is_vip else "🔓 Standard Member"
        caption = (
            f"👤 **{user['fullname']}**\n"
            f"🎂 Age: {user['age']}\n"
            f"📍 City: {user['city']}\n"
            f"⛪️ Religion: {user['religion']}\n"
            f"⭐️ Zodiac: {user['zodiac']}\n"
            f"⚧️ Gender: {user['gender']}\n"
            f"🔍 Looking for: {user['looking_for']}\n\n"
            f"{vip_line}\n\n"
            f"⚙️ Edit your info ➔ /edit"
        )

    if user['photo_id']:
        bot.send_photo(message.chat.id, user['photo_id'], caption=caption, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, caption, parse_mode="Markdown")

# 3️⃣ /browse ➔ ሌሎችን መገለጫዎች ማየት
@bot.message_handler(commands=['browse'])
def browse_cmd(message):
    user_id = message.from_user.id
    if not is_registered(user_id):
        bot.reply_to(message, "እባክዎ መጀመሪያ /start በመጫን ይመዝገቡ።")
        return

    lang = get_user_language(user_id)

    if not increment_and_check_profile_view(user_id):
        limit_text = (
            "🚫 የዛሬውን የ30 መገለጫ እይታ ገደብ ጨርሰዋል።\n"
            "👑 ያለገደብ ለማየት VIP ይሁኑ ➔ /vip"
        ) if lang == 'am' else (
            "🚫 You've reached today's limit of 30 profile views.\n"
            "👑 Become VIP for unlimited views ➔ /vip"
        )
        bot.reply_to(message, limit_text, parse_mode="Markdown")
        return

    profile = get_next_profile(user_id)
    if not profile:
        none_text = (
            "😔 ለጊዜው የሚታዩ አዲስ መገለጫዎች የሉም። ቆይተው እንደገና ይሞክሩ።"
        ) if lang == 'am' else (
            "😔 No new profiles to show right now. Please check back later."
        )
        bot.reply_to(message, none_text)
        return

    mark_profile_seen(user_id, profile['user_id'])

    if lang == 'am':
        caption = (
            f"👤 **{profile['fullname']}**, {profile['age']}\n"
            f"📍 {profile['city']}\n"
            f"⛪️ {profile['religion']}\n"
            f"⭐️ {profile['zodiac']}"
        )
    else:
        caption = (
            f"👤 **{profile['fullname']}**, {profile['age']}\n"
            f"📍 {profile['city']}\n"
            f"⛪️ {profile['religion']}\n"
            f"⭐️ {profile['zodiac']}"
        )

    markup = types.InlineKeyboardMarkup()
    next_label = "➡️ ቀጣይ" if lang == 'am' else "➡️ Next"
    markup.add(types.InlineKeyboardButton(next_label, callback_data="browse_next"))

    if profile['photo_id']:
        bot.send_photo(message.chat.id, profile['photo_id'], caption=caption, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

# 4️⃣ /edit ➔ መገለጫ ማስተካከያ (ቀላል ስሪት: ከዜሮ ማስመዝገብ)
@bot.message_handler(commands=['edit'])
def edit_cmd(message):
    user_id = message.from_user.id
    if not is_registered(user_id):
        bot.reply_to(message, "እባክዎ መጀመሪያ /start በመጫን ይመዝገቡ።")
        return

    lang = get_user_language(user_id)
    user_states[user_id] = {'step': 'get_name', 'language': lang, '_editing': True}

    prompt = "✍️ መገለጫዎን በድጋሚ እንዲያዘጋጁ፣ እባክዎ **ሙሉ ስምዎን** ያስገቡ፦" if lang == 'am' \
        else "✍️ Let's update your profile. Please enter your **Full Name**:"
    bot.send_message(message.chat.id, prompt, parse_mode="Markdown")

# 5️⃣ /vip ➔ የ VIP መረጃ (ክፍያ ገና አልተካተተም - ማስተካከል ያስፈልጋል)
@bot.message_handler(commands=['vip'])
def vip_cmd(message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) if is_registered(user_id) else 'am'
    is_vip = check_vip_status(user_id)

    markup = None
    if lang == 'am':
        if is_vip:
            user = get_user(user_id)
            text = f"👑 እርስዎ ቀድሞውኑ VIP አባል ነዎት! የቪአይፒ ጊዜዎ እስከ {user['vip_expiry']} ድረስ ይቆያል።"
        else:
            text = (
                "👑 **VIP ቢሆኑ የሚያገኙት ጥቅም፦**\n"
                "• ያለገደብ የመገለጫ እይታ\n"
                "• ቅድሚያ በፍለጋ ውጤቶች\n\n"
                f"💰 ዋጋ፦ {VIP_PRICE_ETB} ብር / {VIP_DURATION_DAYS} ቀናት\n\n"
                "ከፍለው ከጨረሱ በኋላ ከታች ያለውን ቁልፍ ይጫኑ፦"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💳 ተከፍያለሁ", callback_data="vip_paid"))
    else:
        if is_vip:
            user = get_user(user_id)
            text = f"👑 You are already a VIP member! Your VIP is valid until {user['vip_expiry']}."
        else:
            text = (
                "👑 **VIP Benefits:**\n"
                "• Unlimited profile views\n"
                "• Priority in browse results\n\n"
                f"💰 Price: {VIP_PRICE_ETB} ETB / {VIP_DURATION_DAYS} days\n\n"
                "Once you've paid, tap the button below:"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💳 I've Paid", callback_data="vip_paid"))

    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")


# 6️⃣ /makevip ➔ አድሚን በእጅ VIP ለመስጠት (ADMIN ONLY)
@bot.message_handler(commands=['makevip'])
def makevip_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "አጠቃቀም፦ /makevip <user_id> <days>\nUsage: /makevip <user_id> <days>")
        return

    try:
        target_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        bot.reply_to(message, "⚠️ user_id እና days ቁጥር መሆን አለባቸው።")
        return

    if not is_registered(target_id):
        bot.reply_to(message, f"⚠️ User {target_id} አልተመዘገበም።")
        return

    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1, vip_expiry = ? WHERE user_id = ?", (expiry, target_id))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"✅ User {target_id} ➔ VIP until {expiry}")

    target_lang = get_user_language(target_id)
    notify = f"🎉 እንኳን ደስ አለዎት! VIP ሆነዋል፣ እስከ {expiry} ድረስ ይቆያል።" if target_lang == 'am' \
        else f"🎉 Congratulations! You are now VIP until {expiry}."
    try:
        bot.send_message(target_id, notify)
    except Exception:
        pass

# ጽሁፍ እና ፎቶ የሚቀበል የሜሴጅ ሃንድለር
@bot.message_handler(content_types=['text', 'photo'])
def registration_flow(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return

    state = user_states[user_id]
    step = state.get('step')
    lang = state.get('language', 'am')

    # 💳 የክፍያ ደረሰኝ (screenshot) መቀበል
    if step == 'awaiting_payment_proof':
        if message.content_type != 'photo':
            err = "⚠️ እባክዎ የክፍያ ደረሰኝ **ስክሪንሾት** ብቻ ይላኩ።" if lang == 'am' else "⚠️ Please send a **screenshot** of your payment receipt."
            bot.reply_to(message, err, parse_mode="Markdown")
            return

        photo_id = message.photo[-1].file_id
        user = get_user(user_id)
        fullname = user['fullname'] if user else message.from_user.first_name
        username = message.from_user.username or "N/A"

        admin_caption = (
            f"💳 **New VIP Payment Proof**\n"
            f"User: {fullname} (@{username})\n"
            f"User ID: `{user_id}`\n"
            f"Amount expected: {VIP_PRICE_ETB} ETB / {VIP_DURATION_DAYS} days"
        )
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"vipapprove_{user_id}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"vipreject_{user_id}")
        )
        try:
            bot.send_photo(ADMIN_ID, photo_id, caption=admin_caption, reply_markup=admin_markup, parse_mode="Markdown")
        except Exception:
            pass

        user_states.pop(user_id, None)
        confirm = "✅ ደረሰኝዎ ለአድሚን ተልኳል። እባክዎ እስኪረጋገጥ ይጠብቁ።" if lang == 'am' \
            else "✅ Your receipt has been sent to the admin. Please wait for approval."
        bot.reply_to(message, confirm)
        return

    # ሀ) ስም መቀበል
    if step == 'get_name' and message.text:
        if message.text.startswith('/'):
            return
        state['fullname'] = message.text
        state['step'] = 'get_gender'

        markup = types.InlineKeyboardMarkup(row_width=2)
        if lang == 'am':
            btn_male = types.InlineKeyboardButton("👨 ወንድ ነኝ", callback_data="gender_ወንድ")
            btn_female = types.InlineKeyboardButton("👩 ሴት ነኝ", callback_data="gender_ሴት")
            text = f"✨ ደስ የሚል ስም ነው **{message.text}**!\n\n👇 እባክዎ የእርስዎን ጾታ ይምረጡ፦"
        else:
            btn_male = types.InlineKeyboardButton("👨 Male", callback_data="gender_Male")
            btn_female = types.InlineKeyboardButton("👩 Female", callback_data="gender_Female")
            text = f"✨ Nice name **{message.text}**!\n\n👇 Please select your gender:"

        markup.add(btn_male, btn_female)
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

    # ሐ) እድሜ መቀበል
    elif step == 'get_age' and message.text:
        if message.text.startswith('/'):
            return
        try:
            age = int(message.text)
            if age < 18 or age > 100:
                err_text = "⚠️ እባክዎ ትክክለኛ እድሜ ያስገቡ (ከ 18 ዓመት በላይ መሆን አለበት)፦" if lang == 'am' else "⚠️ Please enter a valid age (must be 18 or older):"
                bot.reply_to(message, err_text)
                return
            state['age'] = age
            state['step'] = 'get_city'

            markup = types.InlineKeyboardMarkup(row_width=2)
            if lang == 'am':
                c1 = types.InlineKeyboardButton("📍 አዲስ አበባ", callback_data="city_አዲስ አበባ")
                c2 = types.InlineKeyboardButton("📍 አዳማ", callback_data="city_አዳማ")
                c3 = types.InlineKeyboardButton("📍 ሐዋሳ", callback_data="city_ሐዋሳ")
                c4 = types.InlineKeyboardButton("📍 ባህር ዳር", callback_data="city_ባህር ዳር")
                c5 = types.InlineKeyboardButton("📍 ድሬዳዋ", callback_data="city_ድሬዳዋ")
                c6 = types.InlineKeyboardButton("📍 መቐለ", callback_data="city_መቐለ")
                c_other = types.InlineKeyboardButton("🌐 ሌላ ከተማ", callback_data="city_other")
                city_prompt = "📍 በመቀጠል አሁን የሚኖሩበትን **ከተማ** ይምረጡ፦"
            else:
                c1 = types.InlineKeyboardButton("📍 Addis Ababa", callback_data="city_Addis Ababa")
                c2 = types.InlineKeyboardButton("📍 Adama", callback_data="city_Adama")
                c3 = types.InlineKeyboardButton("📍 Hawassa", callback_data="city_Hawassa")
                c4 = types.InlineKeyboardButton("📍 Bahir Dar", callback_data="city_Bahir Dar")
                c5 = types.InlineKeyboardButton("📍 Dire Dawa", callback_data="city_Dire Dawa")
                c6 = types.InlineKeyboardButton("📍 Mekelle", callback_data="city_Mekelle")
                c_other = types.InlineKeyboardButton("🌐 Other City", callback_data="city_other")
                city_prompt = "📍 Next, select the **city** you live in:"

            markup.add(c1, c2, c3, c4, c5, c6)
            markup.add(c_other)

            bot.send_message(message.chat.id, city_prompt, reply_markup=markup, parse_mode="Markdown")
        except ValueError:
            err_num = "⚠️ እባክዎ እድሜዎን በቁጥር ብቻ ያስገቡ (ለምሳሌ፦ 25)፦" if lang == 'am' else "⚠️ Please enter your age in numbers only (e.g., 25):"
            bot.reply_to(message, err_num)

    # መ) ሌላ ከተማ በጽሁፍ ሲያስገባ መቀበል
    elif step == 'get_custom_city' and message.text:
        if message.text.startswith('/'):
            return
        state['city'] = message.text
        state['step'] = 'get_religion'

        markup = types.InlineKeyboard
