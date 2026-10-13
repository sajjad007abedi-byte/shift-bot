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
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    main_menu_buttons = [
        'شیفت امروز', 'شیفت فردا',
        'لوحه کامل هفته جاری', 'لوحه کامل هفته آینده',
        'لوحه کامل هفته گذشته', 'لوحه کامل ۲ هفته آینده',
        'ارسال شیفت فردا به پرسنل', 'ارسال لوحه هفته آینده به همه', 'ارسال تغییرات لوحه',
        '📞 تماس جهت تغییر لوحه', 'مدیریت نفرات', 'تنظیم لوحه و شیفت‌ها'
    ]

    if text in main_menu_buttons:
        clear_user_state(context)

    if context.user_data.get('awaiting_bulk_shift'):
        week_code = context.user_data.get('bulk_week_code')
        full_week_name = WEEK_MAP.get(week_code, week_code)
        db_week_key = get_db_week_key(full_week_name)
        
        parsed_shifts = parse_bulk_shifts_text(text)
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        
        parsed_count = 0
        for day_name, p1, p2 in parsed_shifts:
            cursor.execute('''
                INSERT OR REPLACE INTO shifts (week_type, day_name, person1, person2)
                VALUES (?, ?, ?, ?)
            ''', (db_week_key, day_name, p1, p2))
            parsed_count += 1
        conn.commit()
        conn.close()

        clear_user_state(context)
        await update.message.reply_text(f"✅ برنامه {parsed_count} روز با موفقیت به صورت یکجا ثبت شد.")
        msg, keyboard = await render_week_overview(week_code)
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return

    if context.user_data.get('awaiting_shift_names'):
        target_info = context.user_data.get('shift_target')
        week_code, day = target_info['week_code'], target_info['day']
        full_week_name = WEEK_MAP.get(week_code, week_code)
        db_week_key = get_db_week_key(full_week_name)
        
        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
        p1 = lines[0] if len(lines) > 0 else ""
        p2 = lines[1] if len(lines) > 1 else ""

        if p1.lower() in ['هیچ', 'هیچکدام', 'خالی', 'none']:
            p1, p2 = "", ""

        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO shifts (week_type, day_name, person1, person2)
            VALUES (?, ?, ?, ?)
        ''', (db_week_key, day, p1, p2))
        conn.commit()
        conn.close()

        clear_user_state(context)

        await update.message.reply_text(f"✅ اسامی روز **{day}** ثبت شد:\n👤 نفر اول: **{p1 or 'خالی'}**\n👤 نفر دوم: **{p2 or 'خالی'}**", parse_mode="Markdown")
        msg, keyboard = await render_week_overview(week_code)
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return

    if context.user_data.get('awaiting_add_user'):
        if is_user_admin(chat_id):
            try:
                parts = text.split('-')
                if len(parts) < 2:
                    raise ValueError("فرمت نادرست")
                name = parts[0].strip()
                phone = normalize_phone(parts[1].strip())
                
                conn = sqlite3.connect('shift_bot.db')
                cursor = conn.cursor()
                cursor.execute('INSERT OR REPLACE INTO users (phone, name, is_admin) VALUES (?, ?, 0)', (phone, name))
                conn.commit()
                conn.close()
                
                clear_user_state(context)
                await update.message.reply_text(f"✅ فرد جدید اضافه شد:\n👤 **{name}** (`{phone}`)", parse_mode="Markdown")
                return
            except Exception:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="cancel_action")]])
                await update.message.reply_text("❌ فرمت اشتباه است. لطفاً به این شکل وارد کنید:\n`رضایی - 09171234567`", parse_mode="Markdown", reply_markup=kb)
                return

    clean_text = normalize_phone(text)
    if len(clean_text) == 11 and clean_text.startswith("09"):
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, is_admin FROM users WHERE phone = ?', (clean_text,))
        u = cursor.fetchone()
        if u:
            cursor.execute('UPDATE users SET chat_id = ? WHERE phone = ?', (clean_text, clean_text))
            conn.commit()
            kb = get_admin_keyboard() if u[1] else get_user_keyboard()
            await update.message.reply_text(f"خوش آمدید {u[0]} عزیز. هویت شما تایید شد.", reply_markup=kb)
        else:
            await update.message.reply_text("شماره شما در لیست پرسنل ثبت نشده است.")
        conn.close()
        return

    is_admin = is_user_admin(chat_id)

    if text == '📞 تماس جهت تغییر لوحه':
        await update.message.reply_text(
            f"📞 **هرگونه تغییر یا جابه‌جایی در لوحه شیفت فقط از طریق تماس تلفنی انجام می‌شود.**\n\n"
            f"لطفاً مستقیماً با مسئول شیفت‌ها تماس بگیرید:\n\n"
            f"📱 **شماره تماس:** `{ADMIN_PHONE}`",
            parse_mode="Markdown"
        )

    elif text == 'ارسال شیفت فردا به پرسنل':
        if not is_admin:
            await update.message.reply_text("⛔️ شما دسترسی به این بخش ندارید.")
            return

        today_j = jdatetime.date.today()
        target_j = today_j + jdatetime.timedelta(days=1)
        day_name = get_persian_day_name(target_j)
        date_str = f"{target_j.day} {PERSIAN_MONTHS[target_j.month]}"

        target_week_title = 'لوحه کامل هفته آینده' if today_j.weekday() == 6 else 'لوحه کامل هفته جاری'
        db_week_key = get_db_week_key(target_week_title)

        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT person1, person2 FROM shifts WHERE week_type = ? AND day_name = ?', (db_week_key, day_name))
        row = cursor.fetchone()
        conn.close()

        if not row or (not row[0] and not row[1]):
            await update.message.reply_text(f"⚠️ برنامه شیفت فردا ({day_name} {date_str}) هنوز ثبت نشده است.")
            return

        p1, p2 = row[0], row[1]
        sent_count = 0
        
        for person_name in [p1, p2]:
            if not person_name:
                continue
            
            target_chat_id = get_chat_id_by_name(person_name)
            if target_chat_id:
                msg = f"🔔 **یادآوری شیفت فردا**\n\n📅 **{day_name} ({date_str})**\n👤 نفر اول: **{p1 or 'تعیین نشده'}**\n👤 نفر دوم: **{p2 or 'تعیین نشده'}**"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁‍🗨 مطالعه کردم / تایید دریافت", callback_data="read_tomorrow")]
                ])
                try:
                    await context.bot.send_message(chat_id=target_chat_id, text=msg, parse_mode="Markdown", reply_markup=keyboard)
                    sent_count += 1
                except Exception:
                    pass
        
        await update.message.reply_text(f"✅ شیفت فردا برای {sent_count} نفر مربوطه ارسال شد.")

    elif text == 'ارسال لوحه هفته آینده به همه':
        if not is_admin:
            await update.message.reply_text("⛔️ شما دسترسی به این بخش ندارید.")
            return

        week_title = 'لوحه کامل هفته آینده'
        week_dates, range_str = get_week_dates(week_title)
        db_week_key = get_db_week_key(week_title)
        
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT day_name, person1, person2 FROM shifts WHERE week_type = ?', (db_week_key,))
        rows = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}
        
        msg = f"📅 **{week_title} ({range_str}):**\n\n"
        for day in DAYS:
            date_str = week_dates.get(day, "")
            if day in rows:
                p1, p2 = rows[day]
                msg += f"🔹 **{day} ({date_str}):** {p1 or 'تعیین نشده'} | {p2 or 'تعیین نشده'}\n"
            else:
                msg += f"🔹 **{day} ({date_str}):** تعیین نشده | تعیین نشده\n"

        cursor.execute('SELECT chat_id FROM users WHERE chat_id IS NOT NULL')
        all_users = cursor.fetchall()
        conn.close()

        sent_count = 0
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👁‍🗨 مطالعه کردم / تایید دریافت", callback_data="read_nw")]
        ])

        for u in all_users:
            try:
                await context.bot.send_message(chat_id=u[0], text=msg, parse_mode="Markdown", reply_markup=keyboard)
                sent_count += 1
            except Exception:
                pass

        await update.message.reply_text(f"✅ لوحه هفته آینده به {sent_count} نفر از پرسنل ارسال شد.")

    elif text == 'ارسال تغییرات لوحه':
        if not is_admin:
            await update.message.reply_text("⛔️ شما دسترسی به این بخش ندارید.")
            return

        week_title = 'لوحه کامل هفته آینده'
        week_dates, _ = get_week_dates(week_title)
        db_week_key = get_db_week_key(week_title)

        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT day_name, person1, person2 FROM shift_snapshots WHERE week_type = ?', (db_week_key,))
        snapshot_rows = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

        if not snapshot_rows:
            await update.message.reply_text(
                "⚠️ **لوحه هنوز ثبت نهایی نشده است!**\n\n"
                "ثبت اولیه لوحه جزو تغییرات محسوب نمی‌شود. ابتدا از بخش «تنظیم لوحه و شیفت‌ها» دکمه **«اتمام و ذخیره نهایی لوحه»** را بزنید.",
                parse_mode="Markdown"
            )
            conn.close()
            return

        cursor.execute('SELECT day_name, person1, person2 FROM shifts WHERE week_type = ?', (db_week_key,))
        current_rows = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

        changes = []
        affected_persons = set()

        for day in DAYS:
            curr = current_rows.get(day, ("", ""))
            snap = snapshot_rows.get(day, ("", ""))
            date_str = week_dates.get(day, "")

            if curr != snap:
                p1_curr, p2_curr = curr
                p1_snap, p2_snap = snap

                p1_c_str = p1_curr if p1_curr else "خالی"
                p1_s_str = p1_snap if p1_snap else "خالی"
                p2_c_str = p2_curr if p2_curr else "خالی"
                p2_s_str = p2_snap if p2_snap else "خالی"

                changes.append(f"🔹 **{day} ({date_str}):** تغییر از ({p1_s_str} | {p2_s_str}) به ({p1_c_str} | {p2_c_str})")
                
                if p1_curr: affected_persons.add(p1_curr.strip())
                if p1_snap: affected_persons.add(p1_snap.strip())
                if p2_curr: affected_persons.add(p2_curr.strip())
                if p2_snap: affected_persons.add(p2_snap.strip())

        if not changes:
            await update.message.reply_text("ℹ️ هیچ تغییر جدیدی پس از آخرین ثبت نهایی ایجاد نشده است.")
            conn.close()
            return

        fixed_targets = ["صدیقی", "مرادی", "غریبی"]
        for fp in fixed_targets:
            affected_persons.add(fp)

        change_text = "⚠️ **اعلام تغییرات جدید در لوحه شیفت (پس از ثبت نهایی):**\n\n" + "\n".join(changes)

        sent_count = 0
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👁‍🗨 مطالعه کردم / تایید دریافت", callback_data="read_changes")]
        ])

        for person_name in affected_persons:
            target_chat_id = get_chat_id_by_name(person_name)
            if target_chat_id:
                try:
                    await context.bot.send_message(chat_id=target_chat_id, text=change_text, parse_mode="Markdown", reply_markup=keyboard)
                    sent_count += 1
                except Exception:
                    pass

        cursor.execute('DELETE FROM shift_snapshots WHERE week_type = ?', (db_week_key,))
        for day in DAYS:
            curr = current_rows.get(day, ("", ""))
            cursor.execute('INSERT INTO shift_snapshots (week_type, day_name, person1, person2) VALUES (?, ?, ?, ?)', (db_week_key, day, curr[0], curr[1]))
        conn.commit()

        conn.close()
        await update.message.reply_text(f"✅ پیام تغییرات لوحه برای {sent_count} نفر ارسال شد.")

    elif text in ['لوحه کامل هفته جاری', 'لوحه کامل هفته آینده', 'لوحه کامل هفته گذشته', 'لوحه کامل ۲ هفته آینده']:
        week_dates, range_str = get_week_dates(text)
        db_week_key = get_db_week_key(text)
        
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT day_name, person1, person2 FROM shifts WHERE week_type = ?', (db_week_key,))
        rows = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}
        conn.close()
        
        msg = f"📅 **{text} ({range_str}):**\n\n"
        for day in DAYS:
            date_str = week_dates.get(day, "")
            if day in rows:
                p1, p2 = rows[day]
                msg += f"🔹 **{day} ({date_str}):** {p1 or 'تعیین نشده'} | {p2 or 'تعیین نشده'}\n"
            else:
                msg += f"🔹 **{day} ({date_str}):** تعیین نشده | تعیین نشده\n"

        code = WEEK_REV_MAP.get(text, "cw")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👁‍🗨 مطالعه کردم / تایید دریافت", callback_data=f"read_{code}")]
        ])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

    elif text in ['شیفت امروز', 'شیفت فردا']:
        today_j = jdatetime.date.today()
        if text == 'شیفت امروز':
            target_j = today_j
            target_week_title = 'لوحه کامل هفته جاری'
        else:
            target_j = today_j + jdatetime.timedelta(days=1)
            target_week_title = 'لوحه کامل هفته آینده' if today_j.weekday() == 6 else 'لوحه کامل هفته جاری'

        day_name = get_persian_day_name(target_j)
        date_str = f"{target_j.day} {PERSIAN_MONTHS[target_j.month]}"
        db_week_key = get_db_week_key(target_week_title)

        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT person1, person2 FROM shifts WHERE week_type = ? AND day_name = ?', (db_week_key, day_name))
        row = cursor.fetchone()
        conn.close()

        title = "امروز" if text == 'شیفت امروز' else "فردا"
        if row and (row[0] or row[1]):
            p1 = row[0] if row[0] else "تعیین نشده"
            p2 = row[1] if row[1] else "تعیین نشده"
            msg = f"📋 **{text} ({day_name} {date_str}):**\n\n👤 نفر اول: **{p1}**\n👤 نفر دوم: **{p2}**"
        else:
            msg = f"📋 **{text} ({day_name} {date_str}):**\nبرنامه شیفت برای {title} ({day_name} {date_str}) هنوز ثبت نشده است."

        code = "today" if text == 'شیفت امروز' else "tomorrow"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👁‍🗨 مطالعه کردم / تایید دریافت", callback_data=f"read_{code}")]
        ])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

    elif text == 'مدیریت نفرات':
        if is_admin:
            conn = sqlite3.connect('shift_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT name, phone FROM users')
            users_list = cursor.fetchall()
            conn.close()
            
            msg = "👥 **مدیریت پرسنل:**\n\n"
            for u in users_list:
                msg += f"• {u[0]}: `{u[1]}`\n"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ افزودن نفر جدید", callback_data="add_user")],
                [InlineKeyboardButton("➖ حذف یک نفر", callback_data="delete_user_menu")]
            ])
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update.message.reply_text("⛔️ شما دسترسی به بخش مدیریت ندارید.")

    elif text == 'تنظیم لوحه و شیفت‌ها':
        if is_admin:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("هفته جاری", callback_data="sw_cw")],
                [InlineKeyboardButton("هفته آینده", callback_data="sw_nw")],
                [InlineKeyboardButton("۲ هفته آینده", callback_data="sw_n2w")]
            ])
            await update.message.reply_text("⚙️ **کدام هفته را می‌خواهید تنظیم کنید؟**", reply_markup=keyboard)
        else:
            await update.message.reply_text("⛔️ شما دسترسی به بخش تنظیم لوحه و شیفت‌ها را ندارید.")

    else:
        await start(update, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "add_user":
        clear_user_state(context)
        context.user_data['awaiting_add_user'] = True
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="cancel_action")]])
        await query.message.reply_text("نام و شماره نفر جدید را بفرستید:\nمثال: `رضایی - 09171112233`", parse_mode="Markdown", reply_markup=kb)

    elif data == "cancel_action":
        clear_user_state(context)
        await query.edit_message_text("❌ عملیات لغو شد.")

    elif data == "delete_user_menu":
        clear_user_state(context)
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, phone FROM users WHERE is_admin = 0')
        users = cursor.fetchall()
        conn.close()

        buttons = [[InlineKeyboardButton(f"❌ حذف {name}", callback_data=f"dl_{phone}")] for name, phone in users]
        buttons.append([InlineKeyboardButton("🔙 انصراف", callback_data="cancel_action")])
        await query.edit_message_text("کدام فرد را می‌خواهید حذف کنید؟", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("dl_"):
        phone = data.split("_")[1]
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE phone = ?', (phone,))
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ فرد مورد نظر با موفقیت حذف شد.")

    elif data.startswith("sw_"):
        week_code = data.split("_")[1]
        msg, keyboard = await render_week_overview(week_code)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)

    elif data.startswith("bulk_"):
        week_code = data.split("_")[1]
        full_week_name = WEEK_MAP.get(week_code, week_code)
        clear_user_state(context)
        context.user_data['awaiting_bulk_shift'] = True
        context.user_data['bulk_week_code'] = week_code

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="cancel_action")]])
        await query.message.reply_text(
            f"📥 لطفاً برنامه کامل **{full_week_name}** را به‌صورت خط‌به‌خط ارسال کنید (حتی با روزهای مخفف مثل یکشنبه یا یک):\n\n"
            f"📌 **مثال:**\n"
            f"شنبه طهمورثی یوسفی\n"
            f"یک بوستانی احمدی\n"
            f"دو دریایی عبدالله زاده\n"
            f"سه پوربهی کریمی\n"
            f"چهار عابدی اسکندپور\n"
            f"پنج حیدری شفیعی\n"
            f"جمعه طهمورثی یوسفی",
            parse_mode="Markdown",
            reply_markup=kb
        )

    elif data.startswith("finish_week_"):
        week_code = data.split("_")[1]
        full_week_name = WEEK_MAP.get(week_code, week_code)
        db_week_key = get_db_week_key(full_week_name)
        
        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM shift_snapshots WHERE week_type = ?', (db_week_key,))
        cursor.execute('SELECT day_name, person1, person2 FROM shifts WHERE week_type = ?', (db_week_key,))
        rows = cursor.fetchall()
        for r in rows:
            cursor.execute('INSERT INTO shift_snapshots (week_type, day_name, person1, person2) VALUES (?, ?, ?, ?)', (db_week_key, r[0], r[1], r[2]))
        conn.commit()
        conn.close()

        clear_user_state(context)
       await query.edit_message_text(f"✅ تنظیمات و لوحه **{full_week_name}** با موفقیت ذخیره و قفل شد.")

    elif data.startswith("ed_"):
        parts = data.split("_")
        week_code, day = parts[1], parts[2]
        full_week_name = WEEK_MAP.get(week_code, week_code)
        week_dates, _ = get_week_dates(full_week_name)
        date_str = week_dates.get(day, "")
        
        clear_user_state(context)
        context.user_data['awaiting_shift_names'] = True
        context.user_data['shift_target'] = {'week_code': week_code, 'day': day}
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="cancel_action")]])
        await query.message.reply_text(
            f"✏️ لطفاً اسامی شیفت **{day} ({date_str})** را ارسال کنید:\n\n"
            f"📌 **فرمت ارسال (دو سطر):**\n"
            f"`پوربهی`\n"
            f"`عبدالله زاده`\n\n"
            f"*(برای خالی کردن روز کلمه «خالی» را بفرستید)*",
            parse_mode="Markdown",
            reply_markup=kb
        )

    elif data.startswith("read_"):
        code = data.split("_")[1]
        label_map = {
            "today": "شیفت امروز",
            "tomorrow": "شیفت فردا",
            "cw": "لوحه کامل هفته جاری",
            "nw": "لوحه کامل هفته آینده",
            "pw": "لوحه کامل هفته گذشته",
            "n2w": "لوحه کامل ۲ هفته آینده",
            "changes": "تغییرات لوحه شیفت"
        }
        week_info = label_map.get(code, "پیام شیفت")

        conn = sqlite3.connect('shift_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM users WHERE chat_id = ?', (query.from_user.id,))
        user = cursor.fetchone()

        if user and user[0]:
            user_name = user[0]
        else:
            user_name = query.from_user.full_name or "یکی از پرسنل"

        cursor.execute('SELECT chat_id FROM users WHERE is_admin = 1 AND chat_id IS NOT NULL')
        admins = cursor.fetchall()
        conn.close()

        for admin in admins:
            try:
                await context.bot.send_message(
                    chat_id=admin[0],
                    text=f"👁‍🗨 **{week_info}** به رویت **{user_name}** رسید.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ تایید مطالعه شما برای ادمین ارسال شد.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("ربات فعال شد...")
    app.run_polling()

if __name__ == '__main__':
    main()
