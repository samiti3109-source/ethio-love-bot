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

# የአድሚን ቴሌግራም ID
ADMIN_ID = 1883279841

# ጊዜያዊ ምዝገባ መረጃዎችን መያዣ
user_states = {}

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
# 5. ደረጃ በደረጃ የምዝገባ ሂደት (BILINGUAL REGISTRATION)
# =========================================================

# 1️⃣ /start ➔ ቋንቋ ማስመረጫ
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    
    if is_registered(user_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        lang = user['language'] if user else 'am'
        
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

# ጽሁፍ እና ፎቶ የሚቀበል የሜሴጅ ሃንድለር
@bot.message_handler(content_types=['text', 'photo'])
def registration_flow(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
        
    state = user_states[user_id]
    step = state.get('step')
    lang = state.get('language', 'am')
    
    # ሀ) ስም መቀበል
    if step == 'get_name' and message.text:
        if message.text.startswith('/'): return
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
        if message.text.startswith('/'): return
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
        if message.text.startswith('/'): return
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

    # ረ) ፎቶ መቀበል (የመጨረሻው ደረጃ)
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
                INSERT INTO users (user_id, username, fullname, gender, looking_for, age, city, religion, zodiac, photo_id, language, is_vip, vip_expiry, registered_at)
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
            bot.reply_to(message, err_photo, parse_mode="Markdown")

# 6. የInline Buttons ምርጫዎችን የሚቀበል የኮልባክ ሃንድለር
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_queries(call):
    user_id = call.from_user.id
    
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Please restart by sending /start")
        return
        
    state = user_states[user_id]
    
    # ቋንቋ ምርጫ ሲያደርግ
    if call.data.startswith("lang_"):
        selected_lang = call.data.split("_")[1]
        state['language'] = selected_lang
        state['step'] = 'get_name'
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        if selected_lang == 'am':
            prompt = "🇪🇹 ቋንቋ አማርኛ ተመርጧል።\n\n✍️ እባክዎ **ሙሉ ስምዎን** ያስገቡ፦"
        else:
            prompt = "🇬🇧 English Language Selected.\n\n✍️ Please enter your **Full Name**:"
            
        bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")
        
    # ጾታ ምርጫ ሲያደርግ
    elif call.data.startswith("gender_"):
        gender = call.data.split("_")[1]
        state['gender'] = gender
        state['step'] = 'get_looking_for'
        lang = state.get('language', 'am')
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        if lang == 'am':
            btn_m = types.InlineKeyboardButton("👨 ወንድ", callback_data="look_ወንድ")
            btn_f = types.InlineKeyboardButton("👩 ሴት", callback_data="look_ሴት")
            btn_b = types.InlineKeyboardButton("🧑‍🤝‍🧑 ሁለቱንም", callback_data="look_ሁለቱንም")
            prompt = f"👤 ጾታ፦ **{gender}** ተመርጧል።\n\n🔍 ለመሆኑ **ማንን ማግኘት ይፈልጋሉ?** (የሚፈልጉትን ጾታ ይምረጡ)፦"
        else:
            btn_m = types.InlineKeyboardButton("👨 Male", callback_data="look_Male")
            btn_f = types.InlineKeyboardButton("👩 Female", callback_data="look_Female")
            btn_b = types.InlineKeyboardButton("🧑‍🤝‍🧑 Both", callback_data="look_Both")
            prompt = f"👤 Gender: **{gender}** selected.\n\n🔍 Who are you **interested in?**:"
            
        markup.add(btn_m, btn_f, btn_b)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="Markdown")
        
    # የሚፈለገው ጾታ ምርጫ
    elif call.data.startswith("look_"):
        looking_for = call.data.split("_")[1]
        state['looking_for'] = looking_for
        state['step'] = 'get_age'
        lang = state.get('language', 'am')
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        if lang == 'am':
            prompt = f"🔍 የሚፈልጉት ጾታ፦ **{looking_for}** ተመርጧል።\n\n🎂 እባክዎ **እድሜዎን** በቁጥር ያስገቡ (ለምሳሌ፦ 24)፦"
        else:
            prompt = f"🔍 Interested in: **{looking_for}** selected.\n\n🎂 Please enter your **Age** in numbers (e.g., 24):"
            
        bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")
        
    # ከተማ ምርጫ (በአዝራር)
    elif call.data.startswith("city_"):
        city_choice = call.data.split("_")[1]
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
        religion = call.data.split("_")[1]
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
        if lang == 'am':
            prompt = f"⛪️ ሃይማኖት፦ **{religion}** ተመርጧል።\n\n⭐️ እባክዎ የእርስዎን የኮከብ (Zodiac Sign) ምልክት ይምረጡ፦"
        else:
            prompt = f"⛪️ Religion: **{religion}** selected.\n\n⭐️ Please select your Zodiac Sign:"
            
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="Markdown")

    # ዞዲያክ ምርጫ
    elif call.data.startswith("zod_"):
        zodiac = call.data.split("_")[1]
        state['zodiac'] = zodiac
        state['step'] = 'get_photo'
        lang = state.get('language', 'am')
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        if lang == 'am':
            prompt = f"⭐️ ኮከብ፦ **{zodiac}** ተመርጧል።\n\n📸 **የመጨረሻው ደረጃ!** እባክዎ ለሌሎች አባላት የሚታይ ምርጥ **ፎቶዎን** ይላኩ፦"
        else:
            prompt = f"⭐️ Zodiac: **{zodiac}** selected.\n\n📸 **Final step!** Please upload a nice **photo** for your profile:"
            
        bot.send_message(call.message.chat.id, prompt, pars)
