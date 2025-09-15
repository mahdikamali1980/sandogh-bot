# -*- coding: utf-8 -*-
"""
bot.py
ربات کامل صندوق / وام‌ها / قرعه‌کشی / جلسات
نیازها:
 - python-telegram-bot (v13)
 - gspread
 - google-auth (elemental-day-471503-i1-fb4061ddc376.json)
نحوه استفاده:
 - فایل JSON سرویس اکانت را در همان پوشه بگذارید
 - TOKEN و SERVICE_JSON و SHEET_NAME را مطابق اطلاعات خودتان تنظیم کنید
"""

import sys, os
sys.path.append(os.path.dirname(__file__))
import imghdr

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler
)

import gspread
import re
import logging



# ---------------- تنظیمات ----------------
import os
from google.oauth2.service_account import Credentials

# خواندن توکن از محیطی variable (امن‌تر)
TOKEN = os.environ.get('TELEGRAM_TOKEN', '7993424762:AAE720NjiqTnrolJmYeZvl2fSK0vbOAKz-0')
SHEET_NAME = "SANDOGH"  # نام اسپریدشیت در Google Drive
# ------------------------------------------

# ---------------- اتصال به گوگل شیت ----------------
gc = None
sh = None
try:
    # ساخت credentials از محیط variables (مخصوص Koyeb)
    SERVICE_ACCOUNT_INFO = {
        "type": os.environ['TYPE'],
        "project_id": os.environ['PROJECT_ID'],
        "private_key_id": os.environ['PRIVATE_KEY_ID'],
        "private_key": os.environ['PRIVATE_KEY'].replace('\\n', '\n'),
        "client_email": os.environ['CLIENT_EMAIL'],
        "client_id": os.environ['CLIENT_ID'],
        "auth_uri": os.environ['AUTH_URI'],
        "token_uri": os.environ['TOKEN_URI'],
        "auth_provider_x509_cert_url": os.environ['AUTH_PROVIDER_X509_CERT_URL'],
        "client_x509_cert_url": os.environ['CLIENT_X509_CERT_URL']
    }
    
    credentials = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO)
    scoped_credentials = credentials.with_scopes([
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ])
    
    gc = gspread.authorize(scoped_credentials)
    sh = gc.open(SHEET_NAME)
    logger.info("Connected to Google Sheets: %s", SHEET_NAME)
    
except Exception as e:
    logger.exception("Error connecting to Google Sheets: %s", e)
    gc = None
    sh = None

#-----------حالتهای گفتگو ------------
REG_MOBILE, REG_NID, SAVING_MENU, SAVING_ASK_ACCOUNT, ASK_LOTTERY_CODE, SAVING_STATEMENT, LOAN_STATEMENT, ASK_LOAN_NO, ASK_PAYMENT_CODE = range(9)

# ---------------- توابع کمکی ----------------
def normalize_digits(s):
    """تبدیل ارقام فارسی/عربی به لاتین"""
    if not s:
        return ""
    s = str(s)
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    latin_digits = "0123456789"
    translation_table = str.maketrans(persian_digits + arabic_digits, latin_digits * 2)
    return s.translate(translation_table)

def try_get_field(row, candidates):
    """از یک ردیف (دیکشنری) یکی از نام‌های ممکن فیلد را برمی‌گرداند"""
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return ""

def extract_code(text):
    """استخراج عدد از متن‌های مختلف"""
    if not text:
        return ""

    text = str(text).strip()

    # اگر متن فقط عدد است
    if text.isdigit():
        return text

    # اگر به فرمت "نام(عدد)" است
    match = re.search(r'\((\d+)\)', text)
    if match:
        return match.group(1)

    # اگر به فرمت "نام عدد" است
    match = re.search(r'(\d+)$', text)
    if match:
        return match.group(1)

    # اگر عدد در anywhere متن وجود دارد
    match = re.search(r'\d+', text)
    if match:
        return match.group(0)

    return normalize_digits(text)  # آخرین راهکار
def clean_code(value: str) -> str:
    """تبدیل اعداد فارسی/عربی به انگلیسی و حذف فاصله و کوتیشن"""
    if not value:
        return ""
    value = str(value).strip().replace('"', '').replace("'", "")
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return value.translate(trans)

def ensure_sheet(sheet_name: str):
    """اتصال به شیت گوگل با اسم داده شده"""
    global sh
    try:
        if sh is None:
            return None
        ws = sh.worksheet(sheet_name)
        return ws
    except Exception as e:
        logger.error(f"Error opening sheet {sheet_name}: {e}")
        return None

def ensure_users_sheet_create():
    """شیت users را می‌سازد اگر وجود نداشته باشد و آن را برمی‌گرداند"""
    global sh
    if sh is None:
        return None
    try:
        ws = sh.worksheet("users")
        return ws
    except Exception:
        try:
            ws = sh.add_worksheet(title="users", rows="2000", cols="10")
            # هدرها (ردیف اول) — ترتیب: موبایل، کد ملی، chat_id
            ws.append_row(["موبایل", "کد ملی", "chat_id"])
            return ws
        except Exception:
            logger.exception("Could not create 'users' sheet")
            return None

def save_user_record(mobile, nid, chat_id):
    """اگر موبایل وجود داشت به‌روزرسانی کند، در غیر اینصورت append کند"""
    ws = ensure_users_sheet_create()
    if ws is None:
        return False, "شیت users در دسترس نیست."
    try:
        records = ws.get_all_records()
        norm_mobile = normalize_digits(mobile).lstrip("0")
        for i, r in enumerate(records, start=2):  # شمارش از ردیف 2
            row_mobile = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", ""))
            if row_mobile and row_mobile == norm_mobile:
                headers = ws.row_values(1)
                try:
                    nid_col = headers.index("کد ملی") + 1
                except ValueError:
                    nid_col = None
                try:
                    chat_col = headers.index("chat_id") + 1
                except ValueError:
                    chat_col = None
                if nid_col:
                    ws.update_cell(i, nid_col, nid)
                if chat_col:
                    ws.update_cell(i, chat_col, str(chat_id))
                return True, "به‌روزرسانی شد."
        ws.append_row([mobile, nid, str(chat_id)])
        return True, "ثبت شد."
    except Exception as e:
        logger.exception("save_user_record error")
        return False, str(e)

def find_user_by_chat(chat_id):
    """جستجو در شیت users بر اساس chat_id و بازگرداندن رکورد"""
    ws = ensure_users_sheet_create()
    if ws is None:
        return None
    try:
        records = ws.get_all_records()
        for r in records:
            if str(r.get("chat_id", "")) == str(chat_id):
                return r
    except Exception:
        logger.exception("find_user_by_chat error")
    return None

def find_user_by_mobile(mobile):
    """جستجو در شیت users بر اساس موبایل"""
    ws = ensure_users_sheet_create()
    if ws is None:
        return None
    try:
        records = ws.get_all_records()
        norm_mobile = normalize_digits(mobile).lstrip("0")
        for r in records:
            rm = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", ""))
            if rm == norm_mobile or rm == normalize_digits(mobile):
                return r
    except Exception:
        logger.exception("find_user_by_mobile error")
    return None

def get_user_auth(context, chat_id):
    """بررسی می کند که کاربر ثبت نام کرده و اطلاعات را در context بارگذاری می کند"""
    user_rec = find_user_by_chat(chat_id)
    if user_rec:
        context.user_data['reg_mobile'] = normalize_digits(user_rec.get("موبایل", "")).lstrip("0")
        context.user_data['reg_nid'] = normalize_digits(user_rec.get("کد ملی", ""))
        return True
    return False

# ---------------- کیبوردها ----------------
def main_menu_kb():
    keyboard = [["📅 جلسات", "💰 صندوق"], ["🔔 مدیریت اعلان‌ها"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def fund_menu_kb():
    keyboard = [["💵 پس‌انداز", "📑 وام قرض‌الحسنه"], ["🎲 وام قرعه‌کشی"], ["⬅️ بازگشت"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def savings_menu_kb():
    keyboard = [["📂 حساب‌های شما", "📜 صورتحساب"], ["⬅️ بازگشت به صندوق"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def loans_menu_kb():
    keyboard = [
        ["💳 وام‌های جاری", "✅ وام‌های تسویه‌شده"],
        ["صورتحساب وام"],
        ["⬅️ بازگشت به صندوق"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def lottery_menu_kb():
    keyboard = [
        ["📋 کدهای شما", "🔍 وضعیت کد"],
        ["📅 تاریخ قرعه‌کشی", "🏆 برندگان"],
        ["💰 گزارش پرداخت"],  # اضافه شدن این خط
        ["⬅️ بازگشت به صندوق"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def winners_menu_kb():
    keyboard = [["🥇 برندگان مرحله آخر", "🏆 برندگان قبلی"], ["⬅️ بازگشت به وام قرعه‌کشی"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def subscribe_menu_kb():
    keyboard = [["📅 اعلان جلسات", "🎲 اعلان قرعه‌کشی"], ["💸 اعلان اقساط"], ["⬅️ بازگشت"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------- فرمان‌ها و جریان‌ها ----------------
def start(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_rec = find_user_by_chat(chat_id)
    if user_rec:
        context.user_data['reg_mobile'] = normalize_digits(user_rec.get("موبایل", "")).lstrip("0")
        context.user_data['reg_nid'] = normalize_digits(user_rec.get("کد ملی", ""))
        update.message.reply_text(
            "🌹 خوش آمدید مجدد! از منوی زیر استفاده کنید:",
            reply_markup=main_menu_kb()
        )
        return ConversationHandler.END

    welcome = (
        "🌹 به ربات سیاره خوش‌آمدید!\n\n"
        "برای استفاده از امکانات ربات لطفاً اول موبایل خود را ارسال کنید:"
    )
    update.message.reply_text(welcome, reply_markup=ReplyKeyboardRemove())
    return REG_MOBILE

def reg_mobile(update: Update, context: CallbackContext):
    raw = update.message.text.strip()
    mobile = normalize_digits(raw)
    if not mobile or len(mobile) < 9:
        update.message.reply_text("❌ موبایل نامعتبر است، دوباره تلاش کن.")
        return REG_MOBILE
    context.user_data['reg_mobile'] = mobile.lstrip("0")
    update.message.reply_text("🔐 حالا کد ملی خود را ارسال کنید:")
    return REG_NID

def reg_nid(update: Update, context: CallbackContext):
    raw = update.message.text.strip()
    nid = normalize_digits(raw)
    if not nid or len(nid) < 8:
        update.message.reply_text("❌ کد ملی نامعتبر است، دوباره تلاش کن.")
        return REG_NID
    context.user_data['reg_nid'] = nid
    chat_id = update.message.chat_id
    success, msg = save_user_record(context.user_data['reg_mobile'], nid, chat_id)
    if success:
        update.message.reply_text("✅ ثبت‌نام انجام شد. از منو یکی را انتخاب کن:", reply_markup=main_menu_kb())
    else:
        update.message.reply_text(f"❌ ثبت‌نام با خطا مواجه شد: {msg}\n(دوباره تلاش کن.)")
    return ConversationHandler.END

# ---------- جلسات ----------
def handle_sessions(update: Update, context: CallbackContext):
    ws = ensure_sheet("sessions")
    if not ws:
        update.message.reply_text("❌ هیچ شیتی با نام 'sessions' پیدا نشد.")
        return
    try:
        records = ws.get_all_records()
    except Exception:
        update.message.reply_text("❌ خطا در خواندن شیت جلسات.")
        return
    if not records:
        update.message.reply_text("❌ هیچ جلسه‌ای ثبت نشده.")
        return
    last = records[-1]
    msg = "📌 آخرین جلسه:\n"
    for k, v in last.items():
        msg += f"{k}: {v}\n"
    update.message.reply_text(msg)

# ---------- صندوق -> پس‌انداز ----------
def savings_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    update.message.reply_text("بخش پس‌انداز:", reply_markup=savings_menu_kb())

def savings_accounts(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    mobile = context.user_data.get('reg_mobile')
    nid = context.user_data.get('reg_nid')

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return

    found = []
    try:
        for w in sh.worksheets():
            title = w.title
            if title.startswith("100") or title.startswith("10"):
                try:
                    rows = w.get_all_records()
                except Exception:
                    continue
                for r in rows:
                    rm = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", ""))
                    rn = normalize_digits(r.get("کد ملی", "") or r.get("کد ملی ", "") or r.get("کدملی", ""))
                    if (rm == mobile or rm == mobile.lstrip("0")) and (rn == nid):
                        found.append((title, r))
    except Exception:
        logger.exception("savings_accounts error")

    if not found:
        update.message.reply_text("❌ هیچ حسابی برای این موبایل/کدملی پیدا نشد.", reply_markup=fund_menu_kb())
        return

    msg = "📂 حساب‌های شما:\n"
    for title, r in found:
        acc = try_get_field(r, ["شماره حساب", "حساب", "سپرده", "شماره سپرده", "account"])
        name = try_get_field(r, ["نام و نام خانوادگی", "نام", "owner", "نام صاحب"])
        balance = try_get_field(r, ["موجودی", "مانده", "balance", "موجودی حساب"])
        msg += f"--- شیت: {title} ---\n"
        msg += f"نام صاحب: {name}\n"
        msg += f"شماره حساب: {acc}\n"
        msg += f"موجودی: {balance}\n"
        msg += "-----------\n"
    update.message.reply_text(msg)

# ---------- صورتحساب پس‌انداز ----------
def savings_statement_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    update.message.reply_text("📜 لطفاً شماره سپرده موردنظر خود را وارد کنید:")
    return SAVING_ASK_ACCOUNT

def savings_statement_check(update: Update, context: CallbackContext):
    account_no = normalize_digits(update.message.text.strip())
    mobile = context.user_data.get("reg_mobile")
    nid = context.user_data.get("reg_nid")

    if not mobile or not nid:
        update.message.reply_text("❌ ابتدا باید ثبت‌نام کنید.")
        return ConversationHandler.END

    found = False
    target_ws = None
    target_row = None

    # اول پیدا کردن شیت و ردیف مربوطه
    for ws in sh.worksheets():
        title = ws.title
        if title.startswith("100") or title.startswith("10"):
            try:
                all_values = ws.get_all_values()  # دریافت همه مقادیر به صورت خام
                records = ws.get_all_records()
            except Exception:
                continue

            for i, r in enumerate(records, start=2):  # start=2 because records start from row 2
                rm = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", "") or "")
                rn = normalize_digits(r.get("کد ملی", "") or r.get("کدملی", "") or r.get("کد ملی ", "") or "")
                racc = normalize_digits(r.get("شماره سپرده", "") or r.get("شماره حساب", "") or r.get("حساب", "") or "")

                if (rm == mobile or rm == mobile.lstrip("0")) and \
                   (rn == nid) and \
                   (racc.lstrip("0") == account_no.lstrip("0")):

                    target_ws = ws
                    target_row = i  # شماره ردیف اطلاعات حساب
                    found = True
                    break

    if not found:
        update.message.reply_text("❌ چنین شماره سپرده‌ای برای شما ثبت نشده.")
        return ConversationHandler.END

    # حالا نمایش اطلاعات حساب + گردش حساب
    msg = f"📜 صورتحساب شماره سپرده {account_no}:\n\n"

    # نمایش اطلاعات اصلی حساب
    msg += "💳 اطلاعات حساب:\n"
    account_data = target_ws.row_values(target_row)
    account_headers = target_ws.row_values(1)  # فرض: هدرها در خط 1

    for j in range(min(len(account_headers), len(account_data))):
        header = account_headers[j].strip()
        value = account_data[j].strip()
        if header and value:
            msg += f"{header}: {value}\n"

    # نمایش گردش حساب از خط 5 به بعد
    msg += "\n📊 گردش حساب:\n"
    all_values = target_ws.get_all_values()

    if len(all_values) >= 5:
        # هدرهای گردش حساب (خط 4)
        transaction_headers = all_values[3] if len(all_values) > 3 else ["تاریخ", "شرح", "بدهکار", "بستانکار"]

        # نمایش هدرها
        msg += " | ".join(transaction_headers) + "\n"
        msg += "--- | " * (len(transaction_headers) - 1) + "---\n"

        # نمایش داده‌های گردش از خط 5 به بعد
        for k in range(4, len(all_values)):
            row_data = all_values[k]
            if any(cell.strip() for cell in row_data):  # اگر خط خالی نیست
                row_msg = ""
                for i in range(len(transaction_headers)):
                    if i < len(row_data):
                        row_msg += f"{row_data[i].strip()} | "
                    else:
                        row_msg += " | "
                msg += row_msg.rstrip(" | ") + "\n"
            else:
                break  # اگر به خط خالی رسیدیم، گردش تمام شده

    update.message.reply_text(msg)
    return ConversationHandler.END

#-------------------وام قرض الحسنه-------------------
def loans_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    mobile = context.user_data.get('reg_mobile')
    nid = context.user_data.get('reg_nid')

    found = []
    if sh:
        try:
            for w in sh.worksheets():
                title = w.title
                if title.startswith("20000") or (title.isdigit() and title.startswith("2")):
                    try:
                        rows = w.get_all_records()
                    except Exception:
                        continue
                    for r in rows:
                        rm = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", ""))
                        rn = normalize_digits(r.get("کد ملی", "") or r.get("کدملی", ""))
                        if (rm == mobile or rm == mobile.lstrip("0")) and (rn == nid):
                            found.append((title, r))
        except Exception:
            logger.exception("loans_start search error")

    if not found:
        update.message.reply_text("❌ هیچ وامی برای این موبایل/کدملی پیدا نشد.", reply_markup=fund_menu_kb())
        return

    context.user_data['found_loans'] = found
    update.message.reply_text("📄 وام‌هایی که یافت شدند:", reply_markup=loans_menu_kb())

def loans_show_current(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    found = context.user_data.get('found_loans', [])
    if not found:
        update.message.reply_text("❌ موردی برای نمایش وجود ندارد.", reply_markup=loans_menu_kb())
        return

    ongoing = []
    for title, r in found:
        remain_str = try_get_field(r, ["مانده اقساط", "مانده", "ماندهاقساط", "مانده_اقساط", "باقیمانده"])
        if remain_str:
            try:
                remain = float(normalize_digits(str(remain_str)))
                if remain > 0:  # شرط وام جاری
                    ongoing.append((title, r))
            except ValueError:
                # اگر تبدیل به عدد نشد، نادیده بگیر
                pass

    if not ongoing:
        update.message.reply_text("✅ وام جاری‌ای پیدا نشد.", reply_markup=loans_menu_kb())
        return

    msg = "📋 وام‌های جاری:\n"
    for title, r in ongoing:
        msg += f"--- شیت: {title} ---\n"
        for k, v in r.items():
            if v not in (None, "") and str(v).strip() != "":
                msg += f"{k}: {v}\n"
        msg += "-----------\n"

    update.message.reply_text(msg, reply_markup=loans_menu_kb())

def loans_show_settled(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    found = context.user_data.get('found_loans', [])
    if not found:
        update.message.reply_text("❌ موردی برای نمایش وجود ندارد.", reply_markup=loans_menu_kb())
        return

    settled = []
    for title, r in found:
        remain_str = try_get_field(r, ["مانده اقساط", "مانده", "ماندهاقساط", "مانده_اقساط", "باقیمانده"])
        if remain_str:
            try:
                remain = float(normalize_digits(str(remain_str)))
                if remain == 0:  # شرط وام تسویه‌شده
                    settled.append((title, r))
            except ValueError:
                # اگر تبدیل به عدد نشد، نادیده بگیر
                pass
        else:
            # اگر فیلد مانده اقساط وجود نداشت، به عنوان تسویه‌شده در نظر بگیر
            settled.append((title, r))

    if not settled:
        update.message.reply_text("✅ وام تسویه‌شده‌ای پیدا نشد.", reply_markup=loans_menu_kb())
        return

    msg = "📋 وام‌های تسویه‌شده:\n"
    for title, r in settled:
        msg += f"--- شیت: {title} ---\n"
        for k, v in r.items():
            if v not in (None, "") and str(v).strip() != "":
                msg += f"{k}: {v}\n"
        msg += "-----------\n"

    update.message.reply_text(msg, reply_markup=loans_menu_kb())

# ---------- صورتحساب وام ----------
def loan_statement_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    update.message.reply_text("لطفاً شماره وام خود را وارد کنید:")
    return ASK_LOAN_NO

def loan_statement_handler(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return ConversationHandler.END

    loan_no = normalize_digits(update.message.text.strip())
    mobile = context.user_data.get("reg_mobile")
    nid = context.user_data.get("reg_nid")

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return ConversationHandler.END

    found = False
    for ws in sh.worksheets():
        title = ws.title
        if title.startswith("20000") or (title.isdigit() and title.startswith("2")):
            try:
                all_values = ws.get_all_values()
            except Exception:
                continue

            if len(all_values) < 2:
                continue

            row_mobile = normalize_digits(str(all_values[1][0] if len(all_values[1]) > 0 else ""))
            row_nid = normalize_digits(str(all_values[1][2] if len(all_values[1]) > 2 else ""))
            row_loan_no = normalize_digits(str(all_values[1][3] if len(all_values[1]) > 3 else ""))

            if (row_mobile == mobile) and (row_nid == nid) and (row_loan_no == loan_no):
                msg = f"📜 *صورتحساب وام شماره {loan_no}:*\n\n"

                # خلاصه اطلاعات وام
                msg += "💳 *اطلاعات وام:*\n"
                headers = all_values[0]
                data_row = all_values[1]

                for j in range(min(len(headers), len(data_row))):
                    header = headers[j].strip()
                    value = data_row[j].strip()
                    if header and value:
                        msg += f"• {header}: {value}\n"

                # گردش اقساط
                if len(all_values) >= 5:
                    msg += "\n📊 *گردش اقساط:*\n"
                    transaction_headers = all_values[3] if len(all_values) > 3 else ["تاریخ", "شرح", "مبلغ", "وضعیت"]

                    msg += "────────────────────────────\n"
                    msg += " | ".join(transaction_headers) + "\n"
                    msg += "────────────────────────────\n"

                    for k in range(4, len(all_values)):
                        row_data = all_values[k]
                        if any(cell.strip() for cell in row_data):
                            row_msg = " | ".join([str(cell).strip() for cell in row_data])
                            msg += row_msg + "\n"
                        else:
                            break

                update.message.reply_text(msg, parse_mode="Markdown")
                found = True
                break

    if not found:
        update.message.reply_text("❌ چنین شماره وامی برای شما ثبت نشده.")
    return ConversationHandler.END

# ---------- صندوق -> وام قرعه‌کشی ----------
def lottery_codes_handler(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    mobile = context.user_data.get('reg_mobile')

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return
    try:
        ws = sh.worksheet("lattary_codes")
    except Exception:
        update.message.reply_text("❌ شیت lattary_codes موجود نیست.")
        return
    try:
        rows = ws.get_all_records()
    except Exception:
        update.message.reply_text("❌ خطا در خواندن شیت lattary_codes.")
        return
    all_codes = []
    for r in rows:
        rm = normalize_digits(r.get("موبایل", "") or r.get("موبایل ", ""))
        if rm == mobile or rm == mobile.lstrip("0"):
            raw = r.get("کد", "") or r.get("کدها", "") or r.get("codes", "")
            if raw:
                parts = re.split(r"[,\-؛;|/\\\s]+", str(raw))
                parts = [p.strip() for p in parts if p.strip()]
                all_codes.extend(parts)
    unique_codes = []
    seen = set()
    for c in all_codes:
        if c not in seen:
            seen.add(c)
            unique_codes.append(c)
    if not unique_codes:
        update.message.reply_text("❌ هیچ کدی برای این موبایل ثبت نشده است.", reply_markup=lottery_menu_kb())
        return
    msg = f"📱 موبایل: {mobile}\n🔢 تعداد کدها: {len(unique_codes)}\n🎟️ کدها:\n" + "\n".join(unique_codes)
    update.message.reply_text(msg, reply_markup=lottery_menu_kb())

def lottery_date_handler(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return
    for name in ("Winners", "winners"):
        try:
            ws = sh.worksheet(name)
            recs = ws.get_all_records()
            if not recs:
                continue
            last = recs[-1]
            stage = last.get("مرحله") or last.get("stage", "")
            date = last.get("تاریخ") or last.get("date", "")
            codes = last.get("کدها") or last.get("کد", "")
            if not stage:
                update.message.reply_text("❌ آخرین ردیف فاقد نام مرحله است.", reply_markup=lottery_menu_kb())
                return
            if not date:
                update.message.reply_text(f"مرحله '{stage}' ثبت شده ولی تاریخ تعیین نشده.", reply_markup=lottery_menu_kb())
                return
            if date and not codes:
                update.message.reply_text(f"مرحله '{stage}' در تاریخ {date} ثبت شده اما کدها هنوز وارد نشده (درحال برگزاری).", reply_markup=lottery_menu_kb())
                return
            msg = f"🎯 آخرین مرحله: {stage}\n📅 تاریخ: {date}\n🎟️ کدها:\n{codes}"
            update.message.reply_text(msg, reply_markup=lottery_menu_kb())
            return
        except Exception:
            continue
    update.message.reply_text("❌ شیت Winners پیدا نشد.", reply_markup=lottery_menu_kb())

# ---------- برندگان ----------
def winners_show_last(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return
    try:
        ws = sh.worksheet("Winners")
    except Exception:
        try:
            ws = sh.worksheet("winners")
        except Exception:
            update.message.reply_text("❌ شیت winners پیدا نشد.", reply_markup=winners_menu_kb())
            return
    try:
        recs = ws.get_all_records()
    except Exception:
        update.message.reply_text("❌ خطا در خواندن شیت winners.", reply_markup=winners_menu_kb())
        return
    if not recs:
        update.message.reply_text("❌ شیت winners خالی است.", reply_markup=winners_menu_kb())
        return
    last = recs[-1]
    stage = last.get("مرحله") or last.get("stage", "")
    date = last.get("تاریخ") or last.get("date", "")
    codes = last.get("کدها") or last.get("کد", "")
    if not stage:
        update.message.reply_text("❌ آخرین ردیف فاقد نام مرحله است.", reply_markup=winners_menu_kb())
        return
    if not date:
        update.message.reply_text(f"مرحله '{stage}' ثبت شده ولی تاریخ تعیین نشده.", reply_markup=winners_menu_kb())
        return
    if date and not codes:
        update.message.reply_text(f"مرحله '{stage}' در تاریخ {date} ثبت شده اما کدها هنوز وارد نشده (درحال برگزاری).", reply_markup=winners_menu_kb())
        return
    msg = f"🎖️ مرحله: {stage}\n📅 تاریخ: {date}\n🎟️ کدها:\n{codes}"
    update.message.reply_text(msg, reply_markup=winners_menu_kb())

def winners_show_all(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return
    try:
        ws = sh.worksheet("Winners")
    except Exception:
        try:
            ws = sh.worksheet("winners")
        except Exception:
            update.message.reply_text("❌ شیت winners پیدا نشد.", reply_markup=winners_menu_kb())
            return
    try:
        recs = ws.get_all_records()
    except Exception:
        update.message.reply_text("❌ مشکل در خواندن شیت winners.", reply_markup=winners_menu_kb())
        return
    if not recs:
        update.message.reply_text("❌ شیت winners خالی است.", reply_markup=winners_menu_kb())
        return
    if len(recs) <= 1:
        update.message.reply_text("❌ ردیف قبلی‌ای برای نمایش وجود ندارد.", reply_markup=winners_menu_kb())
        return
    msg = "🏆 برندگان قبلی (بدون آخرین ردیف):\n"
    for r in recs[:-1]:
        stage = r.get("مرحله") or r.get("stage", "")
        date = r.get("تاریخ") or r.get("date", "")
        codes = r.get("کدها") or r.get("کد", "")
        msg += f"مرحله: {stage}\nتاریخ: {date}\nکدها: {codes}\n---\n"
    update.message.reply_text(msg, reply_markup=winners_menu_kb())

# ----------------- لاتاری (قرعه‌کشی) -----------------
def lottery_status_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return ConversationHandler.END

    update.message.reply_text("🔢 لطفاً شماره کد قرعه‌کشی خود را وارد کنید:")
    return ASK_LOTTERY_CODE

def show_user_codes(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return ConversationHandler.END

    user_data = context.user_data
    mobile = user_data.get('reg_mobile')
    nid = user_data.get('reg_nid')

    ws = ensure_sheet("lattary_codes")
    if not ws:
        update.message.reply_text("❌ شیت کدها پیدا نشد.")
        return ConversationHandler.END
    records = ws.get_all_records()
    user_codes = []
    for record in records:
        row_mobile = normalize_digits(str(record.get("موبایل", "")))
        if row_mobile == mobile:
            codes_str = str(record.get("کد", "")).strip()
            if not codes_str:
                continue
            parts = re.split(r'[-,،]', codes_str)
            for part in parts:
                part = part.strip()
                if part:
                    user_codes.append(part)
    if not user_codes:
        update.message.reply_text("❌ هیچ کدی برای شما ثبت نشده است.")
    else:
        codes_text = "\n".join(user_codes)
        update.message.reply_text(
            f"📱 موبایل: {mobile}\n"
            f"📋 تعداد کدها: {len(user_codes)}\n"
            f"🎟 کدها:\n{codes_text}"
        )
    return ConversationHandler.END

def check_code_status(update, context):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ شما ثبت‌نام نکرده‌اید.")
        return ConversationHandler.END

    user_data = context.user_data
    mobile = user_data.get('reg_mobile')

    entered_code = normalize_digits(update.message.text.strip())
    ws = ensure_sheet("lattary_codes")
    if not ws:
        update.message.reply_text("❌ شیت کدها پیدا نشد.")
        return ConversationHandler.END

    records = ws.get_all_records()
    user_codes = []

    # استخراج تمام کدهای کاربر
    for record in records:
        row_mobile = normalize_digits(str(record.get("موبایل", "")))
        if row_mobile == mobile:
            raw_code = record.get("کد", "")
            if raw_code:
                numbers = re.findall(r'\d+', str(raw_code))
                for number in numbers:
                    user_codes.append(number)

    user_codes = list(set(user_codes))

    # بررسی آیا کد متعلق به کاربر است
    if entered_code not in user_codes:
        update.message.reply_text(f"❌ کد {entered_code} متعلق به شما نیست.")
        return ConversationHandler.END

    # بررسی وضعیت کد در شیت وضعیت
    ws_status = ensure_sheet("lattary_status")
    if not ws_status:
        # اگر شیت وضعیت وجود ندارد → برنده نشده
        msg = f"🎯 وضعیت کد {entered_code}:\n"
        msg += "🔴 وضعیت: برنده نشده\n"
        update.message.reply_text(msg)
        return ConversationHandler.END

    status_records = ws_status.get_all_records()
    status_found = False

    for status in status_records:
        status_code = normalize_digits(str(status.get("کد", "")))
        if status_code == entered_code:
            status_found = True

            # دریافت مقادیر با بررسی دقیق
            date = str(status.get("تاریخ پرداخت", "")).strip()
            shaba = str(status.get("شماره شبا", "")).strip()
            stage = str(status.get("مرحله", "")).strip()
            prize = str(status.get("جایزه", "")).strip()

            msg = f"🎯 وضعیت کد {entered_code}:\n"

            # منطق اصلی وضعیت‌ها
            if date and shaba and stage:  # همه پر هستند → پرداخت شده
                msg += f"🏆 مرحله: {stage}\n"
                if prize:
                    msg += f"💰 جایزه: {prize}\n"
                msg += f"📅 تاریخ پرداخت: {date}\n"
                msg += f"💳 شماره شبا: {shaba}\n"
                msg += "✅ وضعیت: پرداخت شده\n"

            elif stage and not date and not shaba:  # فقط مرحله پر است → در انتظار پرداخت
                msg += f"🏆 مرحله: {stage}\n"
                if prize:
                    msg += f"💰 جایزه: {prize}\n"
                msg += "🟡 وضعیت: برنده شده - در انتظار پرداخت\n"

            else:  # سایر حالات → برنده نشده
                msg += "🔴 وضعیت: برنده نشده\n"

            update.message.reply_text(msg)
            break

    if not status_found:
        # اگر کد در شیت وضعیت پیدا نشد → برنده نشده
        msg = f"🎯 وضعیت کد {entered_code}:\n"
        msg += "🔴 وضعیت: برنده نشده\n"
        update.message.reply_text(msg)

    return ConversationHandler.END

    user_data = context.user_data
    mobile = user_data.get('reg_mobile')
    nid = user_data.get('reg_nid')

    ws = ensure_sheet("lattary_codes")
    if not ws:
        update.message.reply_text("❌ شیت کدها پیدا نشد.")
        return ConversationHandler.END
    records = ws.get_all_records()
    user_codes = []
    for record in records:
        row_mobile = normalize_digits(str(record.get("موبایل", "")))
        if row_mobile == mobile:
            codes_str = str(record.get("کد", "")).strip()
            if not codes_str:
                continue
            parts = re.split(r'[-,،]', codes_str)
            for part in parts:
                part = part.strip()
                if part:
                    user_codes.append(part)
    if not user_codes:
        update.message.reply_text("❌ هیچ کدی برای شما ثبت نشده است.")
    else:
        codes_text = "\n".join(user_codes)
        update.message.reply_text(
            f"📱 موبایل: {mobile}\n"
            f"📋 تعداد کدها: {len(user_codes)}\n"
            f"🎟 کدها:\n{codes_text}"
        )
    return ConversationHandler.END

def get_user_lottery_codes(mobile):
    """دریافت کدهای کاربر از شیت lattary_codes"""
    try:
        ws = ensure_sheet("lattary_codes")
        if not ws:
            return []

        records = ws.get_all_records()
        user_codes = []

        for record in records:
            row_mobile = normalize_digits(str(record.get("موبایل", "") or ""))
            if row_mobile == mobile:
                raw_code = record.get("کد", "")
                if raw_code:
                    numbers = re.findall(r'\d+', str(raw_code))
                    user_codes.extend(numbers)

        return list(set(user_codes))

    except Exception:
        return []
def ask_payment_code(update: Update, context: CallbackContext):
    """دریافت کد از کاربر برای گزارش پرداخت"""
    if not context.user_data.get('reg_mobile'):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return ConversationHandler.END

    mobile = context.user_data.get('reg_mobile')
    user_codes = get_user_lottery_codes(mobile)

    if user_codes:
        message = "📥 لطفاً کد خود را وارد کنید:\n"
        message += f"🎯 کدهای شما: {', '.join(user_codes)}"
    else:
        message = "❌ هیچ کدی برای شما ثبت نشده است."

    update.message.reply_text(message)
    return ASK_PAYMENT_CODE
#----------------
def show_payment_for_code(update: Update, context: CallbackContext):
    """نمایش گزارش پرداخت برای کد کاربر (نسخه مینی‌مال)"""
    try:
        if not context.user_data.get('reg_mobile'):
            update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
            return ConversationHandler.END

        mobile = context.user_data.get('reg_mobile')
        entered_code = normalize_digits(update.message.text.strip())

        # بررسی مالکیت کد
        user_codes = get_user_lottery_codes(mobile)
        if entered_code not in user_codes:
            update.message.reply_text(
                f"❌ کد {entered_code} متعلق به شما نیست.\n"
                f"🎯 کدهای شما: {', '.join(user_codes)}",
                reply_markup=lottery_menu_kb()
            )
            return ConversationHandler.END

        # خواندن داده‌های پرداخت از شیت
        ws = ensure_sheet("code_payment")
        if not ws:
            update.message.reply_text("❌ شیت code_payment در دسترس نیست.", reply_markup=lottery_menu_kb())
            return ConversationHandler.END

        all_values = ws.get_all_values()
        if len(all_values) < 3:
            update.message.reply_text("❌ داده‌ای در شیت پرداخت وجود ندارد.", reply_markup=lottery_menu_kb())
            return ConversationHandler.END

        # پیدا کردن ردیف کاربر
        found_row = None
        for row in all_values[2:]:
            if len(row) > 1 and normalize_digits(str(row[1])) == entered_code:
                found_row = row
                break

        if not found_row:
            update.message.reply_text(f"❌ هیچ پرداختی برای کد {entered_code} ثبت نشده.",
                                      reply_markup=lottery_menu_kb())
            return ConversationHandler.END

        # ساخت پیام
        name = found_row[0] if len(found_row) > 0 else "نامشخص"
        msg = f"💰 گزارش پرداخت‌های کد {entered_code}\n👤 نام: {name}\n\n📊 وضعیت پرداخت‌ها:\n\n"

        main_headers = all_values[0]
        stage_headers = all_values[1]

        # ردیف‌های پرداخت
        for i in range(2, len(found_row) - 3):
            if i < len(main_headers) and main_headers[i] and stage_headers[i]:
                month_year = main_headers[i]
                stage = stage_headers[i]
                amount = found_row[i].strip() if i < len(found_row) else "0"

                try:
                    amount_num = float(normalize_digits(amount))
                    status = "✅" if amount_num > 0 else "❌"
                    amount_str = f"{amount_num:,.0f}" if amount_num > 0 else "پرداخت نشده"
                except:
                    status = "❌"
                    amount_str = "پرداخت نشده"

                msg += f"{status} {month_year} ({stage}) | {amount_str}\n"

        # خلاصه
        if len(found_row) >= 3:
            msg += "\n📊 خلاصه وضعیت:\n"
            msg += f"• وام دریافتی: {found_row[-3]}\n"
            msg += f"• اقساط پرداختی: {found_row[-2]}\n"
            msg += f"• مانده اقساط: {found_row[-1]}\n"

        update.message.reply_text(msg, parse_mode='Markdown', reply_markup=lottery_menu_kb())

    except Exception as e:
        logger.error(f"خطا در نمایش پرداخت‌ها: {e}")
        update.message.reply_text("❌ خطا در دریافت اطلاعات پرداخت.", reply_markup=lottery_menu_kb())

    return ConversationHandler.END
# ---------- مدیریت اعلان‌ها ----------
def subscribe_start(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    update.message.reply_text("مدیریت اعلان‌ها:", reply_markup=subscribe_menu_kb())

def toggle_subscription(update: Update, context: CallbackContext):
    if not get_user_auth(context, update.message.chat_id):
        update.message.reply_text("❌ ابتدا ثبت‌نام کنید (/start).")
        return

    choice = update.message.text
    mobile = context.user_data.get('reg_mobile')

    if sh is None:
        update.message.reply_text("❌ اتصال به Google Sheets موجود نیست.")
        return
    ws = ensure_sheet("subscribers")
    if ws is None:
        try:
            ws = sh.add_worksheet(title="subscribers", rows="1000", cols="10")
            ws.append_row(["موبایل", "chat_id", "اعلان جلسات", "اعلان قرعه‌کشی", "اعلان اقساط"])
        except Exception:
            update.message.reply_text("❌ شیت subscribers پیدا نشد و نتونستم بسازم.")
            return
    headers = ws.row_values(1)
    col_map = {
        "📅 اعلان جلسات": "اعلان جلسات",
        "🎲 اعلان قرعه‌کشی": "اعلان قرعه‌کشی",
        "💸 اعلان اقساط": "اعلان اقساط"
    }
    col_name = col_map.get(choice)
    if not col_name:
        update.message.reply_text("❌ گزینه نامعتبر.")
        return
    try:
        cell = ws.find(mobile)
        row = cell.row
    except Exception:
        ws.append_row([mobile, str(update.message.chat_id), "❌", "❌", "❌"])
        try:
            cell = ws.find(mobile)
            row = cell.row
        except Exception:
            update.message.reply_text("❌ خطا در افزودن سابسکرایبر.")
            return
    try:
        if col_name in headers:
            col_index = headers.index(col_name) + 1
        else:
            ws.update_cell(1, len(headers) + 1, col_name)
            headers = ws.row_values(1)
            col_index = headers.index(col_name) + 1
        current = ws.cell(row, col_index).value
        new = "✅" if (current != "✅") else "❌"
        ws.update_cell(row, col_index, new)
        update.message.reply_text(f"وضعیت {col_name} تغییر کرد: {new}")
    except Exception:
        update.message.reply_text("❌ خطا در تغییر وضعیت اعلان.")

# ---------- منو و Router مرکزی ----------
def menu_router(update: Update, context: CallbackContext):
    t = update.message.text.strip()
    if not context.user_data.get('reg_mobile') or not context.user_data.get('reg_nid'):
        update.message.reply_text("برای استفاده از ربات ابتدا با /start ثبت‌نام کن.")
        return

    if t == "📅 جلسات":
        return handle_sessions(update, context)
    if t == "💰 صندوق":
        update.message.reply_text("📂 بخش صندوق:", reply_markup=fund_menu_kb())
        return
    if t == "🔔 مدیریت اعلان‌ها":
        return subscribe_start(update, context)

    # صندوق -> پس‌انداز، وام، قرعه‌کشی
    if t in ["💵 پس‌انداز", "پس‌انداز", "💵پس‌انداز"]:
        return savings_start(update, context)
    if t in ["📑 وام قرض‌الحسنه", "وام قرض‌الحسنه"]:
        return loans_start(update, context)
    if t in ["🎲 وام قرعه‌کشی", "وام قرعه‌کشی", "قرعه‌کشی"]:
        update.message.reply_text("🎲 بخش قرعه‌کشی:", reply_markup=lottery_menu_kb())
        return

    # ... کدهای قبلی ...

    if t == "💰 گزارش پرداخت":
        return ask_payment_code(update, context)

    if t == "⬅️ بازگشت به صندوق":
        update.message.reply_text("↩️ بازگشت به صندوق", reply_markup=fund_menu_kb())
        return

    # ... بقیه منوها ...
    # پس‌انداز زیرمنو
    if t == "📂 حساب‌های شما":
        return savings_accounts(update, context)
    if t == "📜 صورتحساب":
        return savings_statement_start(update, context)
    if t == "⬅️ بازگشت به صندوق":
        update.message.reply_text("↩️ بازگشت به صندوق", reply_markup=fund_menu_kb())
        return

    # وام زیرمنو
    if t in ["💳 وام‌های جاری", "وام‌های جاری"]:
        return loans_show_current(update, context)
    if t in ["✅ وام‌های تسویه‌شده", "وام‌های تسویه‌شده"]:
        return loans_show_settled(update, context)
    if t == "صورتحساب وام":
        return loan_statement_start(update, context)

    # قرعه‌کشی زیرمنو
    if t == "📋 کدهای شما":
        return show_user_codes(update, context)
    if t == "🔍 وضعیت کد":
        return lottery_status_start(update, context)
    if t == "📅 تاریخ قرعه‌کشی":
        return lottery_date_handler(update, context)
    if t == "🏆 برندگان":
        update.message.reply_text("🏆 بخش برندگان:", reply_markup=winners_menu_kb())
        return
    if t == "🥇 برندگان مرحله آخر":
        return winners_show_last(update, context)
    if t == "🏆 برندگان قبلی":
        return winners_show_all(update, context)
    if t == "⬅️ بازگشت به صندوق":
        update.message.reply_text("↩️ بازگشت به صندوق", reply_markup=fund_menu_kb())
        return
    if t == "⬅️ بازگشت به وام قرعه‌کشی":
        update.message.reply_text("↩️ بازگشت به وام قرعه‌کشی", reply_markup=lottery_menu_kb())
        return
    if t == "⬅️ بازگشت":
        update.message.reply_text("↩️ بازگشت به منو اصلی", reply_markup=main_menu_kb())
        return

    # اعلان‌ها toggle
    if t in ["📅 اعلان جلسات", "🎲 اعلان قرعه‌کشی", "💸 اعلان اقساط"]:
        return toggle_subscription(update, context)

    # fallback
    update.message.reply_text("❌ دستور نامعتبر است. از منو استفاده کن.", reply_markup=main_menu_kb())

# ---------- main ----------
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # ثبت‌نام conversation (/start)
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REG_MOBILE: [MessageHandler(Filters.text & ~Filters.command, reg_mobile)],
            REG_NID: [MessageHandler(Filters.text & ~Filters.command, reg_nid)],
        },
        fallbacks=[],
        allow_reentry=True
    )
    dp.add_handler(reg_conv)

    # conversation صورتحساب - SAVING_ASK_ACCOUNT
    save_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r"^📜\s*صورتحساب$"), savings_statement_start)],
        states={SAVING_ASK_ACCOUNT: [MessageHandler(Filters.text & ~Filters.command, savings_statement_check)]},
        fallbacks=[],
        allow_reentry=True
    )
    dp.add_handler(save_conv)

    # وضعیت کد conversation
    lottery_status_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r"^🔍\s*وضعیت کد$"), lottery_status_start)],
        states={ASK_LOTTERY_CODE: [MessageHandler(Filters.text & ~Filters.command, check_code_status)]},
        fallbacks=[],
        allow_reentry=True
    )
    dp.add_handler(lottery_status_conv)

    loan_statement_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^صورتحساب وام$"), loan_statement_start)],
        states={
            ASK_LOAN_NO: [MessageHandler(Filters.text & ~Filters.command, loan_statement_handler)]
        },
        fallbacks=[],
        allow_reentry=True
    )
    dp.add_handler(loan_statement_conv)

    # گفتگوی گزارش پرداخت
    payment_conv = ConversationHandler(
        entry_points=[
            MessageHandler(Filters.regex(r"^💰 گزارش پرداخت$"), ask_payment_code)
        ],
        states={
            ASK_PAYMENT_CODE: [MessageHandler(Filters.text & ~Filters.command, show_payment_for_code)]
        },
        fallbacks=[],
        allow_reentry=True
    )
    dp.add_handler(payment_conv)

    # بقیه handlerها (پیام‌های متنی منو)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, menu_router))

    # start polling (می‌خوای Polling بمونه چون webhook مشکلی داشت)
    updater.start_polling()
    logger.info("Bot started. Polling...")
    updater.idle()

if __name__ == "__main__":
    main()
