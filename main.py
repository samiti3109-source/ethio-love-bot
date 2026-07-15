import os
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

# የአድሚን (የሳሚ) ቴሌግራም ID
ADMIN_ID = 1883279841

# ጊዜያዊ ምዝገባ መረጃዎችን መያዣ (In-memory user state)
user_states = {}

# 3. የዳታቤዝ (Database) ግንኙነት መቆጣጠሪያዎች
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # የተጠቃሚዎች ሰንጠረዥ - ሁሉንም አዳዲስ መረጃዎች ያካተተ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            fullname TEXT,
            gender TEXT,
            age INTEGER,
            city TEXT,
            religion TEXT,
            zodiac TEXT,
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

# =========================================================
# 5. ደረጃ በደረጃ የምዝገባ ሂደት (STEP-BY-STEP REGISTRATION)
# =========================================================

# 1️⃣ /start ➔ የምዝገባ መጀመሪያ
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    
    # ተጠቃሚው ቀድሞ የተመዘገበ ከሆነ ቀጥታ ወደ ዋናው ማውጫ ይወስደዋል
    if is_registered(user_id):
        welcome_text = (
            "👋 እንኳን ወደ **Ethio Love Bot** በድጋሚ መጡ!\n\n"
            "🔍 የሌሎችን መገለጫ ለመፈለግ ➔ /browse ን ይጠቀሙ\n"
            "👤 የራስዎን መገለጫ ለማየት ➔ /profile ን ይጠቀሙ\n"
            "⚙️ መረጃ ለማስተካከል ➔ /edit ን ይጠቀሙ\n"
            "👑 ቪአይፒ ለመሆን ➔ /vip ን ይጠቀሙ"
        )
        bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")
        return

    # አዲስ ከሆነ ምዝገባውን ይጀምራል
    user_states[user_id] = {'step': 'get_name'}
    bot.send_message(
        message.chat.id, 
        "👋 እንኳን ወደ **Ethio Love Bot** በሰላም መጡ! ለመመዝገብ ጥቂት ጥያቄዎችን ይመልሱ።\n\n✍️ በመጀመሪያ **ሙሉ ስምዎን** ያስገቡ፦",
        parse_mode="Markdown"
    )

# ሁሉንም ጽሁፎችን እና ደረጃዎችን የሚቀበል የሜሴጅ ሃንድለር
@bot.message_handler(func=lambda msg: msg.from_user.id in user_states and not msg.text.startswith('/'))
def registration_flow(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    step = state['step']
    
    # ሀ) ስም መቀበል
    if step == 'get_name':
        state['fullname'] = message.text
        state['step'] = 'get_gender'
        
        # የጾታ መምረጫ በተን
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_male = types.InlineKeyboardButton("ወንድ 👨", callback_data="gender_ወንድ")
        btn_female = types.InlineKeyboardButton("ሴት 👩", callback_data="gender_ሴት")
        markup.add(btn_male, btn_female)
        
        bot.send_message(message.chat.id, f"ደስ ይላል {message.text}! እባክዎ ጾታዎን ይምረጡ፦", reply_markup=markup)

    # ሐ) እድሜ መቀበል
    elif step == 'get_age':
        try:
            age = int(message.text)
            if age < 18 or age > 100:
                bot.reply_to(message, "እባክዎ ትክክለኛ እድሜ ያስገቡ (ከ 18 ዓመት በላይ መሆን አለብዎት)፦")
                return
            state['age'] = age
            state['step'] = 'get_city'
            bot.send_message(message.chat.id, "✍️ አሁን የሚኖሩበትን **ከተማ** ያስገቡ (ለምሳሌ፦ አዲስ አበባ)፦", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "እባክዎ እድሜዎን በቁጥር ብቻ ያስገቡ (ለምሳሌ፦ 25)፦")

    # መ) ከተማ መቀበል
    elif step == 'get_city':
        state['city'] = message.text
        state['step'] = 'get_religion'
        
        # የሀይማኖት መምረጫ በተን
        markup = types.InlineKeyboardMarkup(row_width=2)
        r1 = types.InlineKeyboardButton("ኦርቶዶክስ ⛪️", callback_data="rel_ኦርቶዶክስ")
        r2 = types.InlineKeyboardButton("ሙስሊም 🕌", callback_data="rel_ሙስሊም")
        r3 = types.InlineKeyboardButton("ፕሮቴስታንት ⛪️", callback_data="rel_ፕሮቴስታንት")
        r4 = types.InlineKeyboardButton("ሌላ", callback_data="rel_ሌላ")
        markup.add(r1, r2, r3, r4)
        
        bot.send_message(message.chat.id, "📍 ከተማዎ ተመዝግቧል። እባክዎ ሃይማኖትዎን ይምረጡ፦", reply_markup=markup)

# 6. የInline Buttons ምርጫዎችን የሚቀበል የኮልባክ ሃንድለር
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_queries(call):
    user_id = call.from_user.id
    
    # የምዝገባ ሂደት ውስጥ ከሌለ ምንም አያደርግም
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "የምዝገባ ጊዜው አልፏል ወይም እንደገና ጀምረዋል።")
        return
        
    state = user_states[user_id]
    
    # ለጾታ ምርጫ
    if call.data.startswith("gender_"):
        gender = call.data.split("_")[1]
        state['gender'] = gender
        state['step'] = 'get_age'
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"ጾታ፦ {gender} ተመርጧል።\n\n✍️ እባክዎ **እድሜዎን** በቁጥር ያስገቡ፦", parse_mode="Markdown")
        
    # ለሃይማኖት ምርጫ
    elif call.data.startswith("rel_"):
        religion = call.data.split("_")[1]
        state['religion'] = religion
        state['step'] = 'get_zodiac'
        
        # የዞዲያክ መምረጫ በተን
        markup = types.InlineKeyboardMarkup(row_width=3)
        z1 = types.InlineKeyboardButton("አሪየስ (Aries) ♈️", callback_data="zod_አሪየስ")
        z2 = types.InlineKeyboardButton("ታውረስ (Taurus) ♉️", callback_data="zod_ታውረስ")
        z3 = types.InlineKeyboardButton("ጄሚኒ (Gemini) ♊️", callback_data="zod_ጄሚኒ")
        z4 = types.InlineKeyboardButton("ካንሰር (Cancer) ♋️", callback_data="zod_ካንሰር")
        z5 = types.InlineKeyboardButton("ሊዮ (Leo) ♌️", callback_data="zod_ሊዮ")
        z6 = types.InlineKeyboardButton("ቪርጎ (Virgo) ♍️", callback_data="zod_ቪርጎ")
        z7 = types.InlineKeyboardButton("ሊብራ (Libra) ♎️", callback_data="zod_ሊብራ")
        z8 = types.InlineKeyboardButton("ስኮርፒዮ (Scorpio) ♏️", callback_data="zod_ስኮርፒዮ")
        z9 = types.InlineKeyboardButton("ሳጁታሪየስ (Sagittarius) ♐️", callback_data="zod_ሳጁታሪየስ")
        z10 = types.InlineKeyboardButton("ካፕሪኮርን (Capricorn) ♑️", callback_data="zod_ካፕሪኮርን")
        z11 = types.InlineKeyboardButton("አኳሪየስ (Aquarius) ♒️", callback_data="zod_አኳሪየስ")
        z12 = types.InlineKeyboardButton("ፓይሰስ (Pisces) ♓️", callback_data="zod_ፓይሰስ")
        
        markup.add(z1, z2, z3, z4, z5, z6, z7, z8, z9, z10, z11, z12)
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"ሃይማኖት፦ {religion} ተመርጧል።\n\n⭐️ እባክዎ የእርስዎን የኮከብ (Zodiac Sign) ምልክት ይምረጡ፦", reply_markup=markup)

    # ለዞዲያክ ምርጫ (የመጨረሻው ደረጃ እና ዳታቤዝ ላይ ማስቀመጥ)
    elif call.data.startswith("zod_"):
        zodiac = call.data.split("_")[1]
        state['zodiac'] = zodiac
        
        # ዳታቤዝ ላይ ማስገባት
        conn = get_db_connection()
        cursor = conn.cursor()
        
        now = datetime.now()
        # አዲስ ለተመዘገበው ሰው የ 5 ቀን ነጻ ቪአይፒ መፍጠር
        free_vip_expiry = (now + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        reg_date = now.strftime('%Y-%m-%d %H:%M:%S')
        
        username = call.from_user.username
        
        cursor.execute('''
            INSERT INTO users (user_id, username, fullname, gender, age, city, religion, zodiac, is_vip, vip_expiry, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (user_id, username, state['fullname'], state['gender'], state['age'], state['city'], state['religion'], state['zodiac'], free_vip_expiry, reg_date))
        
        conn.commit()
        conn.close()
        
        # ከጊዜያዊ ሜሞሪ ማጥፋት
        user_states.pop(user_id, None)
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        congrats_text = (
            "🎉 **እንኳን ደስ አለዎት! ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል።**\n\n"
            "🎁 ለተመዘገቡበት **የ 5 ቀን ነጻ ቪአይፒ (VIP)** ተሰጥቶዎታል። ሁሉንም ጥቅሞች ያለገደብ መጠቀም ይችላሉ!\n\n"
            "🔍 የሌሎችን መገለጫ ለማሰስ ➔ /browse ን ይጠቀሙ\n"
            "👤 የራስዎን መገለጫ ለማየት ➔ /profile ን ይጠቀሙ"
        )
        bot.send_message(call.message.chat.id, congrats_text, parse_mode="Markdown")

# ==========================================
# 7. የቴሌግራም ሜኑ ሌሎች ትዕዛዞች
# ==========================================

# 2️⃣ /browse ➔ ፕሮፋይሎችን ማሰስ
@bot.message_handler(commands=['browse'])
def view_profiles(message):
    user_id = message.from_user.id
    if not is_registered(user_id):
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ለመመዝገብ /start ን ይጫኑ።")
        return

    can_view = increment_and_check_profile_view(user_id)
    
    if not can_view:
        block_text = (
            "🚫 **የዛሬው የ30 ፕሮፋይል እይታ ገደብዎ አልቋል!**\n\n"
            "መገለጫዎችን ማሰስ ለመቀጠል በወር **199 ብር** ብቻ በመክፈል የቪአይፒ (VIP) አባል ይሁኑ!\n\n"
            "👉 ለመክፈል /vip ን ይጫኑ።"
        )
        bot.send_message(message.chat.id, block_text, parse_mode="Markdown")
        return
    
    profile_sample = (
        "🔍 **የአባላት መገለጫዎች (Browse)** 🔍\n\n"
        "👤 **ስም፦** አስቴር\n"
        "🚺 **ጾታ፦** ሴት\n"
        "🔞 **እድሜ፦** 24\n"
        "⛪️ **ሃይማኖት፦** ኦርቶዶክስ\n"
        "♍️ **የኮከብ ምልክት፦** ቪርጎ\n"
        "📍 **ከተማ፦** አዲስ አበባ\n\n"
        "⏭ ሌላ ፕሮፋይል ለማየት መልሰው /browse ን ይጫኑ።"
    )
    bot.send_message(message.chat.id, profile_sample, parse_mode="Markdown")

# 3️⃣ /likes ➔ እኔን ላይክ ያደረጉኝ
@bot.message_handler(commands=['likes'])
def show_likes(message):
    if not is_registered(message.from_user.id):
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ለመመዝገብ /start ን ይጫኑ።")
        return
    likes_text = (
        "❤️ **እርስዎን ላይክ ያደረጉ ሰዎች** ❤️\n\n"
        "እስካሁን ምንም አዲስ ላይክ የሎትም።"
    )
    bot.send_message(message.chat.id, likes_text, parse_mode="Markdown")

# 4️⃣ /matches ➔ ማች የሆኑ ፕሮፋይሎች
@bot.message_handler(commands=['matches'])
def show_matches(message):
    if not is_registered(message.from_user.id):
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ለመመዝገብ /start ን ይጫኑ።")
        return
    matches_text = (
        "🎉 **የእርስዎ ምርጫዎች (My Matches)** 🎉\n\n"
        "እስካሁን አዲስ ተዛማጅ (Match) የለም።"
    )
    bot.send_message(message.chat.id, matches_text, parse_mode="Markdown")

# 5️⃣ /profile ➔ የእኔ ፕሮፋይል (የተመዘገቡትን መረጃዎች ጨምሮ ያሳያል)
@bot.message_handler(commands=['profile'])
def my_profile(message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ለመመዝገብ /start ን ይጫኑ።")
        conn.close()
        return
        
    is_vip = user['is_vip']
    vip_expiry = user['vip_expiry']
    fullname = user['fullname']
    username = f"@{user['username']}" if user['username'] else "የለውም"
    
    vip_status = "❌ ቪአይፒ አይደሉም (ነጻ እቅድ)"
    if is_vip == 1 and vip_expiry:
        try:
            expiry_date = datetime.strptime(vip_expiry, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date:
                vip_status = f"✅ ቪአይፒ አባል (የሚያበቃበት ቀን: {expiry_date.strftime('%Y-%m-%d')})"
        except ValueError:
            pass
            
    profile_text = (
        "👤 **የእርስዎ መገለጫ (My Profile)** 👤\n\n"
        f"🏷 **ሙሉ ስም፦** {fullname}\n"
        f"🚻 **ጾታ፦** {user['gender']}\n"
        f"🔞 **እድሜ፦** {user['age']}\n"
        f"📍 **ከተማ፦** {user['city']}\n"
        f"⛪️ **ሃይማኖት፦** {user['religion']}\n"
        f"⭐️ **ኮከብ፦** {user['zodiac']}\n"
        f"🆔 **ቴሌግራም ID፦** `{user_id}`\n"
        f"🌐 **ዩዘርኔም፦** {username}\n"
        f"⭐️ **የአባልነት ሁኔታ፦** {vip_status}\n\n"
        "⚙️ መረጃዎን ለማስተካከል /edit ን ይጠቀሙ።"
    )
    bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")
    conn.close()

# 6️⃣ /edit ➔ ፕሮፋይል ማሻሻል
@bot.message_handler(commands=['edit'])
def edit_profile(message):
    if not is_registered(message.from_user.id):
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ለመመዝገብ /start ን ይጫኑ።")
        return
    edit_text = (
        "⚙️ **መገለጫዎን ማስተካከያ** ⚙️\n\n"
        "መረጃዎትን እንደ አዲስ ለማስገባት ከፈለጉ አድሚኑን ያነጋግሩ ወይም በቅርቡ የሚለቀቀውን ማሻሻያ ይጠብቁ!"
    )
    bot.send_message(message.chat.id, edit_text, parse_mode="Markdown")

# 7️⃣ /vip ➔ ቪአይፒ መሆን
@bot.message_handler(commands=['vip', 'buycoins', 'buy_vip'])
def show_payment_options(message):
    price_text = (
        "👑 **የVIP አባልነት ፓኬጆች እና የክፍያ አማራጮች** 👑\n\n"
        "የኛ የቪአይፒ አባል በመሆን በቀን ያለገደብ የብዙ ሺህ ሰዎችን ፕሮፋይል መመልከት እና መልዕክት መለዋወጥ ይችላሉ!\n\n"
        "💵 **የVIP ጥቅሎች፦**\n"
        "1️⃣ **የ 1 ወር አባልነት** ➔ **199 ብር**\n"
        "2️⃣ **የ 3 ወር አባልነት** ➔ **499 ብር**\n"
        "3️⃣ **የ 6 ወር አባልነት** ➔ **999 ብር**\n"
        "4️⃣ **የ 1 ዓመት አባልነት** ➔ **1799 ብር**\n\n"
        "👇 ለመክፈል ከታች ከቀረቡት አማራጮች አንዱን ይምረጡ፦"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn_1m = types.InlineKeyboardButton("የ 1 ወር (199 ብር) መክፈያ", url="https://dashboard.chapa.co")
    btn_3m = types.InlineKeyboardButton("የ 3 ወር (499 ብር) መክፈያ", url="https://dashboard.chapa.co")
    btn_6m = types.InlineKeyboardButton("የ 6 ወር (999 ብር) መክፈያ", url="https://dashboard.chapa.co")
    btn_1y = types.InlineKeyboardButton("የ 1 ዓመት (1799 ብር) መክፈያ", url="https://dashboard.chapa.co")
    
    markup.add(btn_1m, btn_3m, btn_6m, btn_1y)
    bot.send_message(message.chat.id, price_text, parse_mode="Markdown", reply_markup=markup)

# 8️⃣ /help ➔ እርዳታ
@bot.message_handler(commands=['help'])
def help_info(message):
    help_text = (
        "ℹ️ **የእርዳታ እና መረጃ ማዕከል** ℹ️\n\n"
        "📌 **የዋና ዋና አዝራሮች መመሪያ፦**\n"
        "• /start ➔ ቦቱን ለመጀመር እና ለመመዝገብ\n"
        "• /browse ➔ የሰዎችን መገለጫ ለማየት\n"
        "• /profile ➔ የእርስዎን ሙሉ መረጃ ለማረጋገጥ\n"
        "• /vip ➔ ቪአይፒ ለመሆን"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

# 🔄 9️⃣ /reset_db ➔ ዳታቤዙን ለአድሚን ብቻ (1883279841) ማጽጃ ኮድ
@bot.message_handler(commands=['reset_db'])
def reset_database(message):
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS daily_views")
        conn.commit()
        conn.close()
        
        init_db()
        bot.reply_to(message, "🔄 ሄሎ ሳሚ! ዳታቤዙ (Database) በስኬት ተጠርጎ አዲስ ሰንጠረዦች ተፈጥረዋል!")
    except Exception as e:
        conn.close()
        bot.reply_to(message, f"❌ ስህተት አጋጥሟል: {str(e)}")

# 6. ቦቱን የማስነሻ ዋና ክፍል
if __name__ == '__main__':
    print("የኢትዮ ላቭ ቦት በተሳካ ሁኔታ ስራ ጀምሯል...")
    keep_alive()
    # የድሮ ግንኙነቶችን በሙሉ አጽድቶ በንጽህና እንዲነሳ ያደርጋል
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
