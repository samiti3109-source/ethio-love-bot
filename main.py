import os
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
from flask import Flask
from threading import Thread

# 1. ለRender ዌብ ሰርቨር ማዘጋጃ (የቦቱን 24 ሰዓት መስራት የሚያረጋግጥ)
app = Flask('')

@app.route('/')
def home():
    return "የኢትዮ ላቭ ቴሌግራም ቦት በሰላም እየሰራ ነው!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. የቦት ቶከን ማረጋገጫ (ከRender Environment Variables የሚነበብ)
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("እባክዎ 'TELEGRAM_BOT_TOKEN' የሚለውን Environment Variable በRender ላይ ያስገቡ!")

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = 'ethio_love_bot.db'

# የአድሚን (የሳሚ) ቴሌግራም ID
ADMIN_ID = 1883279841

# 3. የዳታቤዝ (Database) ግንኙነት መቆጣጠሪያዎች
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # የተጠቃሚዎች ሰንጠረዥ (የቪአይፒ ሁኔታን እና የተመዘገቡበትን ቀን ጨምሮ)
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
    # የእይታዎች ገደብ መቆጣጠሪያ ሰንጠረዥ (ለነጻ ተጠቃሚዎች በቀን 30 ፕሮፋይል ብቻ)
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

# 4. አጋዥ የዳታቤዝ ተግባራት (Helper Functions)
def register_user(user_id, username, fullname, language='am'):
    """አዲስ ተጠቃሚ ሲመጣ መዝግቦ የ5 ቀን ነጻ ቪአይፒ ይሰጣል"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        now = datetime.now()
        # አዲስ ለተመዘገበ ሰው የ 5 ቀን ነጻ ቪአይፒ ስጦታ ማስላት
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
    """የተጠቃሚው ቪአይፒ የአባልነት ጊዜ ማለፉን ወይም አለማለፉን ያረጋግጣል"""
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
                # ጊዜው ካለቀ ቪአይፒነቱን ወደ 0 (ነጻ እቅድ) ይቀይራል
                cursor.execute("UPDATE users SET is_vip = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
        except ValueError:
            pass
            
    conn.close()
    return False

def increment_and_check_profile_view(user_id):
    """የነጻ ተጠቃሚዎችን የዕለት እይታ ይቆጣጠራል (በቀን ከ30 በላይ እንዳያዩ ይከለክላል)"""
    if check_vip_status(user_id):
        return True # ቪአይፒ ከሆነ ገደብ የለውም
    
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT view_count FROM daily_views WHERE user_id = ? AND view_date = ?", (user_id, today))
    row = cursor.fetchone()
    
    if row:
        current_views = row['view_count']
        if current_views >= 30:
            conn.close()
            return False # 30 እይታ ከሞላ ይከለክላል
        else:
            cursor.execute("UPDATE daily_views SET view_count = view_count + 1 WHERE user_id = ? AND view_date = ?", (user_id, today))
    else:
        cursor.execute("INSERT INTO daily_views (user_id, view_date, view_count) VALUES (?, ?, 1)", (user_id, today))
        
    conn.commit()
    conn.close()
    return True

# ==========================================
# 5. የቴሌግራም ሜኑ ትዕዛዞች (BOT COMMANDS)
# ==========================================

# 1️⃣ /start ➔ ምዝገባ / ዋና ምናሌ
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    fullname = message.from_user.first_name
    
    is_new = register_user(user_id, username, fullname)
    
    welcome_text = "👋 እንኳን ወደ **Ethio Love Bot** በሰላም መጡ!\n\n"
    if is_new:
        welcome_text += "🎉 **እንኳን ደስ አለዎት!** የ 5 ቀን ነጻ ቪአይፒ (VIP) ስጦታ በራስ-ሰር ተሰጥቶዎታል። ሁሉንም የቦቱን አገልግሎቶች ያለገደብ መጠቀም ይችላሉ!\n\n"
    
    welcome_text += (
        "📌 **የቦቱ ዋና መመሪያዎች፦**\n"
        "• የሌሎችን መገለጫ ለማሰስ ➔ /browse ን ይጫኑ\n"
        "• የራስዎን መገለጫ ለማየት ➔ /profile ን ይጫኑ\n"
        "• ቪአይፒ አባል ለመሆን ➔ /vip ን ይጫኑ\n\n"
        "መልካም የፍቅር ጉዞ!"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# 2️⃣ /browse ➔ ፕሮፋይሎችን ማሰስ
@bot.message_handler(commands=['browse'])
def view_profiles(message):
    user_id = message.from_user.id
    can_view = increment_and_check_profile_view(user_id)
    
    if not can_view:
        block_text = (
            "🚫 **የዛሬው የ30 ፕሮፋይል እይታ ገደብዎ አልቋል!**\n\n"
            "መገለጫዎችን ማሰስ ለመቀጠል እና ለሚወዷቸው ሰዎች ቀጥታ መልዕክት ለመላክ በወር **199 ብር** ብቻ በመክፈል የቪአይፒ (VIP) አባል ይሁኑ!\n\n"
            "👉 ለመክፈል እና ፈጣን አገልግሎት ለማግኘት /vip ን ይጫኑ።"
        )
        bot.send_message(message.chat.id, block_text, parse_mode="Markdown")
        return
    
    # የፕሮፋይል ናሙና ማሳያ (በቀጣይ ከዳታቤዝ እንዲመጣ ይደረጋል)
    profile_sample = (
        "🔍 **የአባላት መገለጫዎች (Browse)** 🔍\n\n"
        "👤 **ስም፦** አስቴር\n"
        "🔞 **እድሜ፦** 24\n"
        "📍 **ከተማ፦** አዲስ አበባ\n"
        "💼 **ስራ፦** ተማሪ\n\n"
        "⏭ ሌላ ፕሮፋይል ለማየት መልሰው /browse ን ይጫኑ።"
    )
    bot.send_message(message.chat.id, profile_sample, parse_mode="Markdown")

# 3️⃣ /likes ➔ እኔን ላይክ ያደረጉኝ
@bot.message_handler(commands=['likes'])
def show_likes(message):
    likes_text = (
        "❤️ **እርስዎን ላይክ ያደረጉ ሰዎች** ❤️\n\n"
        "እስካሁን ምንም አዲስ ላይክ አልተደረጉም። መገለጫዎን በተሟላ መረጃ እና ፎቶ ሲያሳምሩ ብዙ ተጠቃሚዎች መውደዳቸውን ይገልጻሉ!"
    )
    bot.send_message(message.chat.id, likes_text, parse_mode="Markdown")

# 4️⃣ /matches ➔ ማች የሆኑ ፕሮፋይሎች
@bot.message_handler(commands=['matches'])
def show_matches(message):
    matches_text = (
        "🎉 **የእርስዎ ምርጫዎች (My Matches)** 🎉\n\n"
        "እስካሁን እርስ በእርስ የተወደዳችሁበት (Match) አዲስ መገለጫ የለም። የሌሎችን መገለጫ በ /browse መመልከትዎን ይቀጥሉ!"
    )
    bot.send_message(message.chat.id, matches_text, parse_mode="Markdown")

# 5️⃣ /profile ➔ የእኔ ፕሮፋይል
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
    
    # የቪአይፒ የአባልነት ሁኔታን ማረጋገጥ
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
        "⚙️ መረጃዎን ለማስተካከል /edit ን ይጠቀሙ።"
    )
    bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")
    conn.close()

# 6️⃣ /edit ➔ ፕሮፋይል ማሻሻል
@bot.message_handler(commands=['edit'])
def edit_profile(message):
    edit_text = (
        "⚙️ **መገለጫዎን ማስተካከያ ክፍል** ⚙️\n\n"
        "እባክዎ ማስተካከል የሚፈልጉትን መረጃ ይምረጡ፦\n"
        "• ስም ለመቀየር ➔ ስምዎን ይላኩ\n"
        "• ፎቶ ለመቀየር ➔ ፎቶ ይላኩ\n\n"
        "*(የፕሮፋይል ማስተካከያ ቅጾች እና ምርጫዎች በቅርቡ በዚህ ይዘመናሉ)*"
    )
    bot.send_message(message.chat.id, edit_text, parse_mode="Markdown")

# 7️⃣ /vip ➔ ቪአይፒ ለመሆን (Upgrade to VIP)
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
        "👇 በChapa በኩል በቀላሉ ለመክፈል ከታች ከቀረቡት አማራጮች አንዱን ይምረጡ፦"
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
        "ይህ ቦት በኢትዮጵያ ውስጥ ያሉ የፍቅር አጋር ፈላጊዎችን ለማገናኘት የተዘጋጀ መድረክ ነው።\n\n"
        "📌 **የዋና ዋና አዝራሮች መመሪያ፦**\n"
        "• /start ➔ ቦቱን እንደገና ለመጀመር\n"
        "• /browse ➔ የሰዎችን መገለጫ ለማየት\n"
        "• /profile ➔ የእርስዎን መረጃ እና የቪአይፒ ቀሪ ጊዜ ለማረጋገጥ\n"
        "• /vip ➔ ቪአይፒ በመሆን ሙሉ ጥቅሞችን ለማግኘት\n\n"
        "ማንኛውም ጥያቄ ወይም ቅሬታ ካለዎት የአገልግሎት መስጫ ክፍላችንን ማነጋገር ይችላሉ።"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

# 🔄 9️⃣ /reset_db ➔ ዳታቤዙን ለአድሚን ብቻ (1883279841) ማጽጃ ኮድ
@bot.message_handler(commands=['reset_db'])
def reset_database(message):
    user_id = message.from_user.id
    
    # ለአድሚን ብቻ የተፈቀደ መሆኑን ማረጋገጫ
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
        bot.reply_to(message, "🔄 ሄሎ ሳሚ! ዳታቤዙ (Database) በስኬት ተጠርጎ እንደ አዲስ ተፈጥሯል!")
    except Exception as e:
        conn.close()
        bot.reply_to(message, f"❌ ዳታቤዙን ሲያጸዳ ስህተት አጋጥሟል: {str(e)}")

# 6. ቦቱን የማስነሻ ዋና ክፍል
if __name__ == '__main__':
    print("የኢትዮ ላቭ ቦት በተሳካ ሁኔታ ስራ ጀምሯል...")
    keep_alive() # የዌብ ሰርቨሩን ያስነሳል
    bot.infinity_polling() # ቦቱን ያለማቋረጥ እንዲሰራ ያደርገዋል
