import sqlite3
import jdatetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = "8778946797:AAFe83yVmiFcm1RtnHiFqt2A4uAx_fmNKuA"
ADMIN_PHONE = "09175272530"

DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
PERSIAN_MONTHS = ["", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

WEEK_MAP = {
    "cw": "لوحه کامل هفته جاری",
    "nw": "لوحه کامل هفته آینده",
    "pw": "لوحه کامل هفته گذشته",
    "n2w": "لوحه کامل ۲ هفته آینده"
}
WEEK_REV_MAP = {v: k for k, v in WEEK_MAP.items()}

def init_db():
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            name TEXT,
            is_admin INTEGER,
            chat_id INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            week_type TEXT,
            day_name TEXT,
            person1 TEXT,
            person2 TEXT,
            PRIMARY KEY (week_type, day_name)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shift_snapshots (
            week_type TEXT,
            day_name TEXT,
            person1 TEXT,
            person2 TEXT,
            PRIMARY KEY (week_type, day_name)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def normalize_phone(phone):
    if not phone:
        return ""
    phone = phone.strip().replace("+98", "0").replace(" ", "")
    if phone.startswith("9") and len(phone) == 10:
        phone = "0" + phone
    return phone

def clean_name(text):
    if not text:
        return ""
    return (text.strip()
            .replace(" ", "")
            .replace("\u200c", "")
            .replace("ك", "ک")
            .replace("ي", "ی"))

def get_chat_id_by_name(person_name):
    if not person_name or len(person_name.strip()) < 2:
        return None
    
    clean_target = clean_name(person_name)
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, chat_id FROM users WHERE chat_id IS NOT NULL')
    users = cursor.fetchall()
    conn.close()

    for db_name, chat_id in users:
        clean_db_name = clean_name(db_name)
        if clean_target in clean_db_name or clean_db_name in clean_target:
            return chat_id
    return None

def get_persian_day_name(j_date):
    days_map = {
        0: "شنبه",
        1: "یکشنبه",
        2: "دوشنبه",
        3: "سه‌شنبه",
        4: "چهارشنبه",
        5: "پنجشنبه",
        6: "جمعه"
    }
    return days_map.get(j_date.weekday(), "")

def get_week_start_date(week_title):
    today = jdatetime.date.today()
    wd = today.weekday()
    current_sat = today - jdatetime.timedelta(days=wd)
    
    if week_title == 'لوحه کامل هفته گذشته':
        start_date = current_sat - jdatetime.timedelta(days=7)
    elif week_title == 'لوحه کامل هفته جاری':
        start_date = current_sat
    elif week_title == 'لوحه کامل هفته آینده':
        start_date = current_sat + jdatetime.timedelta(days=7)
    elif week_title == 'لوحه کامل ۲ هفته آینده':
        start_date = current_sat + jdatetime.timedelta(days=14)
    else:
        start_date = current_sat
    return start_date

def get_week_dates(week_title):
    start_date = get_week_start_date(week_title)
    dates = {}
    for i, day in enumerate(DAYS):
        d = start_date + jdatetime.timedelta(days=i)
        dates[day] = f"{d.day} {PERSIAN_MONTHS[d.month]}"
    
    end_date = start_date + jdatetime.timedelta(days=6)
    range_str = f"{start_date.day} {PERSIAN_MONTHS[start_date.month]} الی {end_date.day} {PERSIAN_MONTHS[end_date.month]}"
    return dates, range_str

def get_db_week_key(week_title):
    return str(get_week_start_date(week_title))

def parse_persian_day(text_token):
    if not text_token:
        return None
    text_token = text_token.strip()
    for d in DAYS:
        if text_token.startswith(d) or d.startswith(text_token):
            return d
    mapping = {
        "ش": "شنبه",
        "شنبه": "شنبه",
        "یک": "یکشنبه",
        "یکشنبه": "یکشنبه",
        "دو": "دوشنبه",
        "دوشنبه": "دوشنبه",
        "سه": "سه‌شنبه",
        "سه‌شنبه": "سه‌شنبه",
        "سه‌": "سه‌شنبه",
        "چهار": "چهارشنبه",
        "چهارشنبه": "چهارشنبه",
        "پنج": "پنجشنبه",
        "پنجشنبه": "پنجشنبه",
        "جم": "جمعه",
        "جمعه": "جمعه"
    }
    return mapping.get(text_token, None)

def parse_bulk_shifts_text(text):
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM users')
    db_users = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    
    db_users.sort(key=len, reverse=True)
    parsed_data = []
    
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        
        day_name = None
        day_token_count = 1
        
        day_name = parse_persian_day(tokens[0])
        if not day_name and len(tokens) > 1:
            combined = tokens[0] + tokens[1]
            day_name = parse_persian_day(combined)
            if day_name:
                day_token_count = 2
        
        if not day_name:
            continue
        
        remaining_tokens = tokens[day_token_count:]
        remaining_text = " ".join(remaining_tokens)
        
        matched_names = []
        clean_rem = clean_name(remaining_text)
        
        for u_name in db_users:
            clean_u = clean_name(u_name)
            if clean_u and clean_u in clean_rem:
                if u_name not in matched_names:
                    matched_names.append(u_name)
                    clean_rem = clean_rem.replace(clean_u, "", 1)
                    if len(matched_names) >= 2:
                        break
        
        p1 = matched_names[0] if len(matched_names) > 0 else ""
        p2 = matched_names[1] if len(matched_names) > 1 else ""
        
        parsed_data.append((day_name, p1, p2))
        
    return parsed_data

def get_user_keyboard():
    return ReplyKeyboardMarkup([
        ['شیفت امروز', 'شیفت فردا'],
        ['لوحه کامل هفته جاری', 'لوحه کامل هفته آینده'],
        ['لوحه کامل هفته گذشته', 'لوحه کامل ۲ هفته آینده'],
        ['📞 تماس جهت تغییر لوحه']
    ], resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ['شیفت امروز', 'شیفت فردا'],
        ['لوحه کامل هفته جاری', 'لوحه کامل هفته آینده'],
        ['لوحه کامل هفته گذشته', 'لوحه کامل ۲ هفته آینده'],
        ['ارسال شیفت فردا به پرسنل', 'ارسال لوحه هفته آینده به همه'],
        ['ارسال تغییرات لوحه'],
        ['مدیریت نفرات', 'تنظیم لوحه و شیفت‌ها']
    ], resize_keyboard=True)

def is_user_admin(chat_id):
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM users WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0] == 1)

def clear_user_state(context):
    context.user_data['awaiting_shift_names'] = False
    context.user_data['awaiting_bulk_shift'] = False
    context.user_data['awaiting_add_user'] = False
    context.user_data['shift_target'] = None
    context.user_data['bulk_week_code'] = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_user_state(context)
    chat_id = update.effective_chat.id
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, is_admin FROM users WHERE chat_id = ?', (chat_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        name, is_admin = user
        kb = get_admin_keyboard() if is_admin else get_user_keyboard()
        await update.message.reply_text(f"سلام {name} عزیز، گزینه مورد نظر را انتخاب کنید:", reply_markup=kb)
    else:
        keyboard = ReplyKeyboardMarkup([
            [{'text': 'ارسال شماره موبایل جهت احراز هویت', 'request_contact': True}]
        ], resize_keyboard=True)
        await update.message.reply_text("به ربات شیفت خوش آمدید. برای ورود، دکمه ارسال شماره موبایل را بزنید یا شماره خود را تایپ کنید:", reply_markup=keyboard)

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_user_state(context)
    contact = update.message.contact
    phone = normalize_phone(contact.phone_number)
    chat_id = update.effective_chat.id
    
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, is_admin FROM users WHERE phone = ?', (phone,))
    user = cursor.fetchone()
    
    if user:
        cursor.execute('UPDATE users SET chat_id = ? WHERE phone = ?', (chat_id, phone))
        conn.commit()
        name, is_admin = user
        kb = get_admin_keyboard() if is_admin else get_user_keyboard()
        await update.message.reply_text(f"خوش آمدید {name} عزیز. هویت شما تایید شد.", reply_markup=kb)
    else:
        await update.message.reply_text("شماره شما در لیست پرسنل ثبت نشده است.")
    conn.close()

async def render_week_overview(week_code):
    full_week_name = WEEK_MAP.get(week_code, week_code)
    week_dates, range_str = get_week_dates(full_week_name)
    db_week_key = get_db_week_key(full_week_name)
    
    conn = sqlite3.connect('shift_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT day_name, person1, person2 FROM shifts WHERE week_type=?', (db_week_key,))
    rows = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}
    conn.close()

    msg = f"🛠 **تنظیم {full_week_name} ({range_str}):**\n\nبرای ثبت دسته‌جمعی یا ویرایش تکی روزها انتخاب کنید:\n\n"
    for day in DAYS:
        p1, p2 = rows.get(day, ("ثبت نشده", "ثبت نشده"))
        p1_str = p1 if p1 else "ثبت نشده"
        p2_str = p2 if p2 else "ثبت نشده"
        date_str = week_dates.get(day, "")
        msg += f"🔹 **{day} ({date_str}):** {p1_str} | {p2_str}\n"
    
    buttons = [
        [InlineKeyboardButton("📥 ثبت یکجای کل هفته (متن کلی)", callback_data=f"bulk_{week_code}")],
        [InlineKeyboardButton("✅ اتمام و ذخیره نهایی لوحه", callback_data=f"finish_week_{week_code}")]
    ]
    for day in DAYS:
        date_str = week_dates.get(day, "")
        buttons.append([InlineKeyboardButton(f"✏️ ویرایش تکی {day} ({date_str})", callback_data=f"ed_{week_code}_{day}")])
    
    return msg, InlineKeyboardMarkup(buttons)
