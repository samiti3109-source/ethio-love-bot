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

# 👑 የVIP ዋጋ እና የክፍያ መረጃ
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
    # Likes እና Matches ሰንጠረዦች (ለቻት እና ለላይክ የሚረዱ)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            liker_id INTEGER,
            liked_id INTEGER,
            liked_at TEXT,
            PRIMARY KEY (liker_id, liked_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            user_one INTEGER,
            user_two INTEGER,
            matched_at TEXT,
            PRIMARY KEY (user_one, user_two)
        )
    ''')
    conn.commit()
    conn.close()

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
    viewer = get_user(viewer_id)
    if not viewer:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    looking_for = viewer['looking_for']
    viewer_gender = viewer['gender']
    query = "SELECT * FROM users WHERE user_id != ?"
    params = [viewer_id]

    # ጾታን የማዛመድ ህግ (ወንድ ለሴት፣ ሴት ለወንድ፣ ወይም ሁለቱንም ለሚመርጡ)
    if looking_for not in ('ሁለቱንም', 'Both'):
        query += " AND (gender = ? OR gender = ?)"
        if looking_for in ('ወንድ', 'Male'):
            params.extend(['ወንድ', 'Male'])
        else:
            params.extend(['ሴት', 'Female'])
            
    # እኛንም የሚፈልግ መሆን አለበት (የጋራ መስፈርት)
    query += " AND (looking_for = ? OR looking_for = ? OR looking_for = 'ሁለቱንም' OR looking_for = 'Both')"
    if viewer_gender in ('ወንድ', 'Male'):
        params.extend(['ወንድ', 'Male'])
    else:
        params.extend(['ሴት', 'Female'])

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

# ላይክ እና ማች መመዝገቢያዎች
def record_like(liker_id, liked_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO likes (liker_id, liked_id, liked_at) VALUES (?, ?, ?)",
        (liker_id, liked_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    
    # የጋራ መፈላለግ (Match) መኖሩን ማረጋገጫ
    cursor.execute("SELECT * FROM likes WHERE liker_id = ? AND liked_id = ?", (liked_id, liker_id))
    match = cursor.fetchone()
    
    is_match = False
    if match:
        is_match = True
        cursor.execute(
            "INSERT OR IGNORE INTO matches (user_one, user_two, matched_at) VALUES (?, ?, ?)",
            (min(liker_id, liked_id), max(liker_id, liked_id), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        
    conn.close()
    return is_match
    # =========================================================
# 5. ቦት ኮማንዶች (BOT COMMANDS)
# =========================================================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    
    # ⚠️ ተጣብቀው እንዳይቀሩ የቆየውን State እናጸዳለን
    if user_id in user_states:
        user_states[user_id] = {}

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

@bot.message_handler(commands=['profile'])
def profile_cmd(message):
    user_id = message.from_user.id
    if not is_registered(user_id):
        bot.reply_to(message, "እባክዎ መጀመሪያ /start በመጫን ይመዝገቡ።")
        return

    user = get_user(user_id)
    lang = user['language']
    is_vip = check_vip_status(user_id)

    if lang == 'am':
        vip_line = f"👑 VIP አባል (እስከ {user['vip_expiry']})" if is_vip else "🔓 መደበኛ አባል"
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
        vip_line = f"👑 VIP Member (Until {user['vip_expiry']})" if is_vip else "🔓 Standard Member"
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

    caption = (
        f"👤 **{profile['fullname']}**, {profile['age']}\n"
        f"📍 {profile['city']}\n"
        f"⛪️ {profile['religion']}\n"
        f"⭐️ {profile['zodiac']}"
    )

    # 💚 Like እና ❌ Next ኢንላይን ቁልፎችን በትክክለኛው መጠን ይፈጥራል
    markup = types.InlineKeyboardMarkup()
    btn_like = types.InlineKeyboardButton("💚 Like", callback_data=f"like_{profile['user_id']}")
    btn_next = types.InlineKeyboardButton("❌ Next", callback_data="browse_next")
    markup.add(btn_like, btn_next)

    if profile['photo_id']:
        bot.send_photo(message.chat.id, profile['photo_id'], caption=caption, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

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

@bot.message_handler(commands=['makevip'])
def makevip_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "አጠቃቀም፦ /makevip <user_id> <days>")
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

# =========================================================
# 6. የ CALLBACK QUERY መቆጣጠሪያዎች (CALLBACK HANDLERS)
# =========================================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_queries(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id

    # 💚 Like ቁልፍ ሲጫን የሚሰራው
    if call.data.startswith("like_"):
        target_id = int(call.data.split("_")[1])
        lang = get_user_language(user_id)
        
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
            
        # ሬከርድ እናደርጋለን እንዲሁም ማች መፈጠሩን እንፈትሻለን
        is_match = record_like(user_id, target_id)
        
        if is_match:
            # የሁለቱንም የቻት ሁኔታ እንከፍታለን
            user_states[user_id] = {'step': 'chatting', 'chat_with': target_id}
            user_states[target_id] = {'step': 'chatting', 'chat_with': user_id}
            
            match_msg_viewer = "🎉 **እንኳን ደስ አሎት! Match ተፈጥሯል!** 🎉\n\nአሁን በቀጥታ መጻጻፍ ትችላላችሁ። መልእክትዎን እዚህ መጻፍ ይጀምሩ።\n\n⚠️ መጻጻፉን ለማቆም `/stop_chat` ይበሉ።"
            match_msg_target = "🎉 **እንኳን ደስ አሎት! አዲስ Match አለዎት!** 🎉\n\nአሁን በቀጥታ መጻጻፍ ትችላላችሁ። መልእክትዎን እዚህ መጻፍ ይጀምሩ።\n\n⚠️ መጻጻፉን ለማቆም `/stop_chat` ይበLock።"
            
            bot.send_message(user_id, match_msg_viewer, parse_mode="Markdown")
            try:
                bot.send_message(target_id, match_msg_target, parse_mode="Markdown")
            except Exception:
                pass
        else:
            like_confirm = "💚 ወደዱት! እሱ/እሷም መልሰው Like ሲያደርጉዎት እናሳውቆታለን።" if lang == 'am' else "💚 Liked! We will notify you when they like you back."
            bot.send_message(call.message.chat.id, like_confirm)
            # ወደ ቀጣዩ ፕሮፋይል ይመራዋል
            browse_cmd(call.message)
        return

    # የአድሚን ክፍያ ማረጋገጫዎች
    if call.data.startswith("vipapprove_"):
        target_user_id = int(call.data.split("_", 1)[1])
        expiry = (datetime.now() + timedelta(days=VIP_DURATION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_vip = 1, vip_expiry = ? WHERE user_id = ?", (expiry, target_user_id))
        conn.commit()
        conn.close()

        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n✅ Approved! User {target_user_id} is now VIP."
        )
        
        target_lang = get_user_language(target_user_id)
        notify = f"🎉 የክፍያ ደረሰኝዎ ጸድቋል! አሁን የ {VIP_DURATION_DAYS} ቀናት VIP አባል ሆነዋል።" if target_lang == 'am' \
            else f"🎉 Your payment receipt has been approved! You are now VIP for {VIP_DURATION_DAYS} days."
        try:
            bot.send_message(target_user_id, notify)
        except Exception:
            pass
        return

    elif call.data.startswith("vipreject_"):
        target_user_id = int(call.data.split("_", 1)[1])
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n❌ Rejected! Receipt disapproved."
        )
        
        target_lang = get_user_language(target_user_id)
        notify = "❌ የላኩት የክፍያ ፎቶ ተቀባይነት አላገኘም። እባክዎ ትክክለኛውን ደረሰኝ በድጋሚ ይላኩ።" if target_lang == 'am' \
            else "❌ Your payment receipt was rejected. Please send a valid screenshot again."
        try:
            bot.send_message(target_user_id, notify)
        except Exception:
            pass
        return

    if call.data == "browse_next":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        browse_cmd(call.message)
        return

    if call.data == "vip_paid":
        lang = get_user_language(user_id) if is_registered(user_id) else 'am'
        user_states[user_id] = {'step': 'awaiting_payment_proof', 'language': lang}
        payment_info = VIP_PAYMENT_INFO_AM if lang == 'am' else VIP_PAYMENT_INFO_EN
        bot.send_message(call.message.chat.id, payment_info, parse_mode="Markdown")
        return

    if user_id not in user_states:
        return

    state = user_states[user_id]

    # ቋንቋ ምርጫ
    if call.data.startswith("lang_"):
        selected_lang = call.data.split("_", 1)[1]
        state['language'] = selected_lang
        state['step'] = 'get_name'
        bot.delete_message(call.message.chat.id, call.message.message_id)
        prompt = "🇪🇹 ቋንቋ አማርኛ ተመርጧል።\n\n✍️ እባክዎ **ሙሉ ስምዎን** ያስገቡ፦" if selected_lang == 'am' \
            else "🇬🇧 English Language Selected.\n\n✍️ Please enter your **Full Name**:"
        bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")

    # ጾታ ምርጫ
    elif call.data.startswith("gender_"):
        gender = call.data.split("_", 1)[1]
        state['gender'] = gender
        state['step'] = 'get_looking_for'
        lang = state.get('language', 'am')

        markup = types.InlineKeyboardMarkup(row_width=2)
        if lang == 'am':
            btn_m = types.InlineKeyboardButton("👨 ወንድ", callback_data="look_ወንድ")
            btn_f = types.InlineKeyboardButton("👩 ሴት", callback_data="look_ሴት")
            btn_b = types.InlineKeyboardButton("🧑‍🤝‍🧑 ሁለቱንም", callback_data="look_ሁለቱንም")
            prompt = f"👤 ጾታ፦ **{gender}** ተመርጧል።\n\n🔍 ለመሆኑ **ማንን ማግኘት ይፈልጋሉ?**፦"
        else:
            btn_m = types.InlineKeyboardButton("👨 Male", callback_data="look_Male")
            btn_f = types.InlineKeyboardButton("👩 Female", callback_data="look_Female")
            btn_b = types.InlineKeyboardButton("🧑‍🤝‍🧑 Both", callback_data="look_Both")
            prompt = f"👤 Gender: **{gender}** selected.\n\n🔍 Who are you **interested in?**:"

        markup.add(btn_m, btn_f, btn_b)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="Markdown")

    # ፍላጎት ምርጫ
    elif call.data.startswith("look_"):
        looking_for = call.data.split("_", 1)[1]
        state['looking_for'] = looking_for
        state['step'] = 'get_age'
        lang = state.get('language', 'am')

        bot.delete_message(call.message.chat.id, call.message.message_id)
        prompt = f"🔍 ፍላጎት፦ **{looking_for}** ተመርጧል።\n\n🎂 እባክዎ **እድሜዎን** በቁጥር ያስገቡ (ለምሳሌ፦ 24)፦" if lang == 'am' \
            else f"🔍 Interested in: **{looking_for}** selected.\n\n🎂 Please enter your **Age** in numbers (e.g., 24):"
        bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")

    # ከተማ ምርጫ
    elif call.data.startswith("city_"):
        city_choice = call.data.split("_", 1)[1]
        lang = state.get('language', 'am')

        if city_choice == "other":
            state['step'] = 'get_custom_city'
            bot.delete_message(call.message.chat.id, call.message.message_id)
            prompt = "✍️ እባክዎ የሚኖሩበትን **የከተማ ስም** በጽሁፍ ያስገቡ፦" if lang == 'am' else "✍️ Please type the name of your **City**:"
            bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")
        else:
            state['city'] = city_choice
            state['step'] = 'get_religion'

            markup = types.InlineKeyboardMarkup(row_width=2)
            if lang == 'am':
                r1 = types.InlineKeyboardButton("⛪️ ኦርቶዶክስ", callback_data="rel_ኦርቶዶክስ")
                r2 = types.InlineKeyboardButton("🕌 ሙስሊም", callback_data="rel_ሙስሊም")
                r3 = types.InlineKeyboardButton("⛪️ ፕሮቴስታንት", callback_data="rel_ፕሮቴስታንት")
                r4 = types.InlineKeyboardButton("🌐 ሌላ", callback_data="rel_ሌላ")
                prompt = f"📍 ከተማ፦ **{city_choice}** ተመርጧል።\n\n👇 እባክዎ ሃይማኖትዎን ይምረጡ፦"
            else:
                r1 = types.InlineKeyboardButton("⛪️ Orthodox", callback_data="rel_Orthodox")
                r2 = types.InlineKeyboardButton("🕌 Muslim", callback_data="rel_Muslim")
                r3 = types.InlineKeyboardButton("⛪️ Protestant", callback_data="rel_Protestant")
                r4 = types.InlineKeyboardButton("🌐 Other", callback_data="rel_Other")
                prompt = f"📍 City: **{city_choice}** selected.\n\n👇 Please select your religion:"

            markup.add(r1, r2, r3, r4)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="Markdown")

    # ሃይማኖት ምርጫ
    elif call.data.startswith("rel_"):
        religion = call.data.split("_", 1)[1]
        state['religion'] = religion
        state['step'] = 'get_zodiac'
        lang = state.get('language', 'am')

        markup = types.InlineKeyboardMarkup(row_width=3)
        z1 = types.InlineKeyboardButton("♈️ Aries", callback_data="zod_አሪየስ")
        z2 = types.InlineKeyboardButton("♉️ Taurus", callback_data="zod_ታውረስ")
        z3 = types.InlineKeyboardButton("♊️ Gemini", callback_data="zod_ጄሚኒ")
        z4 = types.InlineKeyboardButton("♋️ Cancer", callback_data="zod_ካንሰር")
        z5 = types.InlineKeyboardButton("♌️ Leo", callback_data="zod_ሊዮ")
        z6 = types.InlineKeyboardButton("♍️ Virgo", callback_data="zod_ቪርጎ")
        z7 = types.InlineKeyboardButton("♎️ Libra", callback_data="zod_ሊብራ")
        z8 = types.InlineKeyboardButton("♏️ Scorpio", callback_data="zod_ስኮርፒዮ")
        z9 = types.InlineKeyboardButton("♐️ Sagittarius", callback_data="zod_ሳጁታሪየስ")
        z10 = types.InlineKeyboardButton("♑️ Capricorn", callback_data="zod_ካፕሪኮርን")
        z11 = types.InlineKeyboardButton("♒️ Aquarius", callback_data="zod_አኳሪየስ")
        z12 = types.InlineKeyboardButton("♓️ Pisces", callback_data="zod_ፓይሰስ")
        markup.add(z1, z2, z3, z4, z5, z6, z7, z8, z9, z10, z11, z12)

        bot.delete_message(call.message.chat.id, call.message.message_id)
        prompt = f"⛪️ ሃይማኖት፦ **{religion}** ተመርጧል።\n\n⭐️ እባክዎ የእርስዎን የኮከብ (Zodiac Sign) ምልክት ይምረጡ፦" if lang == 'am' \
            else f"⛪️ Religion: **{religion}** selected.\n\n⭐️ Please select your Zodiac Sign:"
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="Markdown")

    # ኮከብ ምርጫ
    elif call.data.startswith("zod_"):
        zodiac = call.data.split("_", 1)[1]
        state['zodiac'] = zodiac
        state['step'] = 'get_photo'
        lang = state.get('language', 'am')

        bot.delete_message(call.message.chat.id, call.message.message_id)
        prompt = f"⭐️ ኮከብ፦ **{zodiac}** ተመርጧል።\n\n📸 **የመጨረሻው ደረጃ!** እባክዎ ለሌሎች አባላት የሚታይ ምርጥ **ፎቶዎን** ይላኩ፦" if lang == 'am' \
            else f"⭐️ Zodiac: **{zodiac}** selected.\n\n📸 **Final step!** Please upload a nice **photo** for your profile:"
        bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")

# =========================================================
# 7. የፅሁፍ እና ፎቶ መልዕክቶች ፍሰት (REGISTRATION MESSAGE HANDLER)
# =========================================================

@bot.message_handler(content_types=['text', 'photo'])
def registration_flow(message):
    user_id = message.from_user.id
    
    # 💬 እርስ በርስ መጻጻፊያ (Chat System)
    if user_id in user_states and user_states[user_id].get('step') == 'chatting':
        target_chat_id = user_states[user_id].get('chat_with')
        
        # ቻት ማቆሚያ ትእዛዝ
        if message.text in ("/stop_chat", "/exit"):
            user_states.pop(user_id, None)
            user_states.pop(target_chat_id, None)
            
            bot.send_message(user_id, "📴 መጻጻፉ ተቋርጧል። ወደ ዋናው ማውጫ ለመመለስ /start ይበሉ።")
            try:
                bot.send_message(target_chat_id, "📴 ሌላኛው ወገን መጻጻፉን አቋርጧል። ወደ ዋናው ማውጫ ለመመለስ /start ይበሉ።")
            except Exception:
                pass
            return
            
        # መልእክት ማስተላለፊያ
        try:
            if message.content_type == 'text':
                bot.send_message(target_chat_id, f"💬 {message.text}")
            elif message.content_type == 'photo':
                bot.send_photo(target_chat_id, message.photo[-1].file_id, caption=message.caption or "")
        except Exception:
            bot.send_message(user_id, "⚠️ መልእክቱን ማድረስ አልተቻለም። ተጠቃሚው ቦቱን ዘግቶት ሊሆን ይችላል።")
        return

    if user_id not in user_states:
        return

    state = user_states[user_id]
    step = state.get('step')
    lang = state.get('language', 'am')

    # የክፍያ ደረሰኝ መቀበያ
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
            f"💳 **New VIP Payment Proof**\n\n"
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
        except Exception as e:
            print(f"Error sending proof to admin: {e}")

        user_states.pop(user_id, None)
        confirm = "✅ ደረሰኝዎ ለአድሚን ተልኳል። እባክዎ እስኪረጋገጥ ይጠብቁ።" if lang == 'am' \
            else "✅ Your receipt has been sent to the admin. Please wait for approval."
        bot.reply_to(message, confirm)
        return

    # ስም መቀበል
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

    # እድሜ መቀበል
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

    # ሌላ ከተማ በፅሁፍ መቀበል
    elif step == 'get_custom_city' and message.text:
        if message.text.startswith('/'):
            return
        state['city'] = message.text
        state['step'] = 'get_religion'

        markup = types.InlineKeyboardMarkup(row_width=2)
        if lang == 'am':
            r1 = types.InlineKeyboardButton("⛪️ ኦርቶዶክስ", callback_data="rel_ኦርቶዶክስ")
            r2 = types.InlineKeyboardButton("🕌 ሙስሊም", callback_data="rel_ሙስሊም")
            r3 = types.InlineKeyboardButton("⛪️ ፕሮቴስታንት", callback_data="rel_ፕሮቴስታንት")
            r4 = types.InlineKeyboardButton("🌐 ሌላ", callback_data="rel_ሌላ")
            text = f"✨ ከተማዎ **{message.text}** ተመዝግቧል!\n\n👇 እባክዎ ሃይማኖትዎን ይምረጡ፦"
        else:
            r1 = types.InlineKeyboardButton("⛪️ Orthodox", callback_data="rel_Orthodox")
            r2 = types.InlineKeyboardButton("🕌 Muslim", callback_data="rel_Muslim")
            r3 = types.InlineKeyboardButton("⛪️ Protestant", callback_data="rel_Protestant")
            r4 = types.InlineKeyboardButton("🌐 Other", callback_data="rel_Other")
            text = f"✨ Your city **{message.text}** has been registered!\n\n👇 Please select your religion:"

        markup.add(r1, r2, r3, r4)
        bot.send_message(message.chat.id, text, reply_markup=markup)

    # ፎቶ መቀበል እና ምዝገባ ማጠናቀቅ
    elif step == 'get_photo':
        if message.content_type == 'photo':
            photo_id = message.photo[-1].file_id
            state['photo_id'] = photo_id

            conn = get_db_connection()
            cursor = conn.cursor()

            now = datetime.now()
            free_vip_expiry = (now + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
            reg_date = now.strftime('%Y-%m-%d %H:%M:%S')
            username = message.from_user.username

            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, fullname, gender, looking_for, age, city, religion, zodiac, photo_id, language, is_vip, vip_expiry, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ''', (user_id, username, state['fullname'], state['gender'], state['looking_for'], state['age'], state['city'], state['religion'], state['zodiac'], photo_id, lang, free_vip_expiry, reg_date))

            conn.commit()
            conn.close()
            user_states.pop(user_id, None)

            if lang == 'am':
                congrats_text = (
                    "🎉 **እንኳን ደስ አለዎት! ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል።** 🎉\n\n"
                    "🎁 ለተመዘገቡበት **የ 5 ቀን ነጻ ቪአይፒ (VIP)** ተሰጥቶዎታል። ሁሉንም ጥቅሞች ያለገደብ መጠቀም ይችላሉ!\n\n"
                    "🔍 የሌሎችን መገለጫ ለማሰስ ➔ /browse ን ይጠቀሙ\n"
                    "👤 የራስዎን መገለጫ ለማየት ➔ /profile ን ይጠቀሙ"
                )
            else:
                congrats_text = (
                    "🎉 **Congratulations! Your registration is complete.** 🎉\n\n"
                    "🎁 You have received **5 Days of Free VIP** access. Enjoy all features without limits!\n\n"
                    "🔍 Browse other profiles ➔ /browse\n"
                    "👤 View your own profile ➔ /profile"
                )
            bot.send_message(message.chat.id, congrats_text, parse_mode="Markdown")
        else:
            err_photo = "⚠️ እባክዎ መገለጫዎ ላይ የሚቀመጥ እውነተኛ **ፎቶ** ብቻ ይላኩ!" if lang == 'am' else "⚠️ Please send a real **photo** for your profile!"
            bot.reply_tobot.reply_to(message, err_photo, parse_mode="Markdown")

@bot.message_handler(commands=['reset_db'])
def reset_database(message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS daily_views")
        cursor.execute("DROP TABLE IF EXISTS seen_profiles")
        cursor.execute("DROP TABLE IF EXISTS likes")
        cursor.execute("DROP TABLE IF EXISTS matches")
        conn.commit()
        conn.close()

        init_db()
        bot.reply_to(message, "🔄 ሄሎ ሳሚ! ዳታቤዙ (Database) በስኬት ተጠርጎ አዲስ ሰንጠረዦች ተፈጥረዋል!")
    except Exception as e:
        conn.close()
        bot.reply_to(message, f"❌ ስህተት አጋጥሟል: {str(e)}")

# ቦቱን የማስነሻ ዋና ክፍል
if __name__ == '__main__':
    print("የኢትዮ ላቭ ቦት በተሳካ ሁኔታ ስራ ጀምሯል...")
    
    # 1. ዌብሁክን ያጸዳል
    try:
        bot.remove_webhook()
        import time
        time.sleep(2)
    except Exception as e:
        print(f"Error removing webhook: {e}")

    # 2. የ Flask ሰርቨሩን በጀርባ ያስነሳል
    keep_alive()

    # 3. ቦቱን በደህንነት ያስነሳል
    try:
        bot.infinity_polling(skip_pending=True, timeout=60, non_stop=True)
    except Exception as e:
        print(f"Polling error occurred: {e}")
        
