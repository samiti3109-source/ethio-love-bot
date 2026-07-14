import os
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
from flask import Flask
from threading import Thread

# ለRender Free Web Service እንዲሰራ የሚረዳ የዌብ ሰርቨር መፍጠሪያ
app = Flask('')

@app.route('/')
def home():
    return "የቴሌግራም ቦቱ በሰላም እየሰራ ነው!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# የቦት ቶከን መቆጣጠሪያ
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("እባክዎ 'TELEGRAM_BOT_TOKEN' የሚለውን Environment Variable በRender ላይ ያስገቡ!")

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = 'ethio_love_bot.db'

# የአድሚን ቴሌግራም አይዲ (ID)
ADMIN_ID = 1883279841

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

init_db()

def register_user(user_id, username, fullname, language='am'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        now = datetime.now()
        # አዲስ ለሚመዘገብ ሰው የ 5 ቀን ነጻ ቪአይፒ ስጦታ
        free_vip_expiry = (now + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        reg_date = now.strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            INSERT INTO users (user_id, username, fullname, language, is_vip, vip_expiry, registered_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
        ''', (user_id, username, fullname, language, free_vip_expiry, reg_date))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False

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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    fullname = message.from_user.first_name
    
    is_new = register_user(user_id, username, fullname)
    
    welcome_text = "👋 እንኳን ወደ Ethio Love Bot በሰላም መጡ!\n\n"
    if is_new:
        welcome_text += "🎉 እንኳን ደስ አለዎት! የ 5 ቀን ነጻ ቪአይፒ (VIP) ተሰጥቶዎታል። ሁሉንም አገልግሎቶች ያለገደብ መጠቀም ይችላሉ!\n\n"
    
    welcome_text += "የራስዎን መገለጫ ለማየት /profile ን ይጠቀሙ።\nየሌሎችን የፍቅር አጋር መገለጫዎችን ለመፈለግ /view_profiles ን ይጠቀሙ።\nለክፍያ አማራጮች /buy_vip ን ይጫኑ።"
    bot.reply_to(message, welcome_text)

# 👤 1. የራስን መገለጫ (My Profile) ማሳያ ኮድ
@bot.message_handler(commands=['profile'])
def my_profile(message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        bot.reply_to(message, "❌ እባክዎ መጀመሪያ ቦቱን ለማስጀመር /start ን ይጫኑ።")
        conn.close()
        return
        
    is_vip = user['is_vip']
    vip_expiry = user['vip_expiry']
    fullname = user['fullname']
    username = f"@{user['username']}" if user['username'] else "የለውም"
    
    # የቪአይፒ ሁኔታን ፅሁፍ ማስተካከያ
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
        f"🏷 **ስም፦** {fullname}\n"
        f"🆔 **ቴሌግራም ID፦** `{user_id}`\n"
        f"🌐 **ዩዘርኔም፦** {username}\n"
        f"⭐️ **የአባልነት ሁኔታ፦** {vip_status}\n\n"
        "የሌሎችን አባላት መገለጫ ለማየት /view_profiles ን ይጠቀሙ።"
    )
    bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")
    conn.close()

# 🔍 2. የሌሎችን መገለጫ (View Other Profiles) ማሳያ ኮድ
@bot.message_handler(commands=['view_profiles'])
def view_profiles(message):
    user_id = message.from_user.id
    can_view = increment_and_check_profile_view(user_id)
    
    if not can_view:
        block_text = (
            "🚫 *የዛሬው የ30 ፕሮፋይል እይታ ገደብዎ አልቋል!*\n\n"
            "መመልከት ለመቀጠል እና ቀጥታ መልዕክት ለመላክ በወር *199 ብር* ብቻ በመክፈል ቪአይፒ (VIP) ይሁኑ!\n\n"
            "ለመክፈል /buy_vip ን ይጫኑ።"
        )
        bot.send_message(message.chat.id, block_text, parse_mode="Markdown")
        return
    
    profile_sample = (
        "👤 *የአባሉ መገለጫ*\n"
        "ስም: አስቴር\n"
        "እድሜ: 24\n"
        "ከተማ: አዲስ አበባ\n"
        "ስራ: ተማሪ\n\n"
        "ሌላ ፕሮፋይል ለማየት /view_profiles ን ይጫኑ።"
    )
    bot.send_message(message.chat.id, profile_sample, parse_mode="Markdown")

@bot.message_handler(commands=['buycoins', 'buy_vip'])
def show_payment_options(message):
    price_text = (
        "⭐ **የVIP አባልነት የክፍያ አማራጮች** ⭐\n\n"
        "የኛ ቪአይፒ አባል በመሆን በቀን ያለገደብ ፕሮፋይሎችን መመልከት እና መልዕክት መለዋወጥ ይችላሉ!\n\n"
        "የቪአይፒ ፓኬጆቻችን፦\n"
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

# 🔄 ዳታቤዙን ለአድሚን ብቻ (1883279841) የሚያጸዳው ኮድ
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
        bot.reply_to(message, "🔄 ሄሎ ሳሚ! ዳታቤዙ (Database) በስኬት ተጠርጓል!")
    except Exception as e:
        conn.close()
        bot.reply_to(message, f"❌ ስህተት አጋጥሟል: {str(e)}")

if __name__ == '__main__':
    print("ቦቱ በRender ላይ በተሳካ ሁኔታ ስራ ጀምሯል...")
    keep_alive()
    bot.infinity_polling()
