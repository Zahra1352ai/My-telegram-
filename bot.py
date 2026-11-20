# -*- coding: utf-8 -*-
import threading
import os
import json
import random
import time
import re
import asyncio
import httpx
import logging
import zipfile
import sqlite3
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, 
    InlineKeyboardMarkup, CopyTextButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ApplicationBuilder
)
from faker import Faker

# ==========================================
# Logging Configuration
# ==========================================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"⚠️ Unexpected Bot Error: {context.error}", exc_info=context.error)

# ==========================================
# Mail.tm Configuration & Pool
# ==========================================
MAIL_TM_BASE = "https://api.mail.tm"
mail_tm_pool = []

# ==========================================
# Web Server to keep the bot alive on Render
# ==========================================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running on Render!")
        
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# ==========================================
# Main Bot Configuration (Token & Admin)
# ==========================================
TOKEN = "9009320488:AAEaG0F-yEKLuoKpiS_nRWC8sActNEeKJc0"
ADMIN_ID = 8093069505
SUPPORT_USERNAME = "@GlobalNumSupport" # For support button

fake_en = Faker('en_US')
fake_zh = Faker('zh_CN')

# ==========================================
# SQLite Database Management
# ==========================================
DB_FILE = "bot_database.db"

def init_sqlite_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kv_store (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

init_sqlite_db()

def load_db(name, default):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM kv_store WHERE key = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        save_db(name, default)
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default

def save_db(name, data_obj):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    val_str = json.dumps(data_obj, ensure_ascii=False)
    cursor.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (name, val_str))
    conn.commit()
    conn.close()

async def save_db_async(name, data_obj):
    await asyncio.to_thread(save_db, name, data_obj)

DEFAULT_COUNTRY_SETTINGS = {
    "USA": {
        "label": "🇺🇸 USA",
        "btn_text": "🇺🇸 USA +1 Telegram",
        "upload_label": "🇺🇸 USA (Upload)",
        "otp_digits": 5,
        "strip_prefix": True,
        "prefix": "1"
    },
    "China": {
        "label": "🇨🇳 China",
        "btn_text": "🇨🇳 China +86 Telegram",
        "upload_label": "🇨🇳 China (Upload)",
        "otp_digits": 6,
        "strip_prefix": True,
        "prefix": "86"
    },
    "Canada": {
        "label": "🇨🇦 Canada",
        "btn_text": "🇨🇦 Canada (+1)",
        "upload_label": "🇨🇦 Canada (Upload)",
        "otp_digits": 5,
        "strip_prefix": True,
        "prefix": "1"
    }
}

# Load database tables
data = load_db("data", {"USA": [], "China": [], "Canada": [], "used_names": [], "canceled": []})
for _ck in ["USA", "China", "Canada"]:
    if _ck not in data:
        data[_ck] = []
if "used_names" not in data:
    data["used_names"] = []
if "canceled" not in data:
    data["canceled"] = []

users_db = load_db("users", {})
config_db = load_db("config", {
    "active": True,
    "prices": {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01},
    "base_costs": {"USA": 0.100, "China": 0.120, "Canada": 0.100},
    "usdt_bep20_address": "0xYourDefaultUSDT_BEP20_Wallet_Address_Here",
    "total_deposits": 0.0,
    "country_settings": json.loads(json.dumps(DEFAULT_COUNTRY_SETTINGS)),
    "custom_countries": {}
})
mail_tokens_db = load_db("mail_tokens", {})

config_db.setdefault("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
config_db["prices"].setdefault("USA", 0.175)
config_db["prices"].setdefault("China", 0.195)
config_db["prices"].setdefault("Canada", 0.175)
config_db["prices"].setdefault("MailTM", 0.01)

config_db.setdefault("base_costs", {"USA": 0.100, "China": 0.120, "Canada": 0.100})
config_db["base_costs"].setdefault("USA", 0.100)
config_db["base_costs"].setdefault("China", 0.120)
config_db["base_costs"].setdefault("Canada", 0.100)

config_db.setdefault("custom_countries", {})
config_db.setdefault("country_settings", {})
for _bk, _bcfg in DEFAULT_COUNTRY_SETTINGS.items():
    if _bk not in config_db["country_settings"]:
        config_db["country_settings"][_bk] = dict(_bcfg)
    else:
        for _sk, _sv in _bcfg.items():
            config_db["country_settings"][_bk].setdefault(_sk, _sv)

for _ck, _ccfg in config_db["custom_countries"].items():
    if _ck not in data:
        data[_ck] = []
    config_db["prices"].setdefault(_ck, _ccfg.get("price", 0.175))
    config_db["base_costs"].setdefault(_ck, _ccfg.get("base_cost", 0.100))
    _ccfg.setdefault("label", f"🌍 {_ck}")
    _ccfg.setdefault("btn_text", f"{_ccfg['label']} Number")
    _ccfg.setdefault("upload_label", f"{_ccfg['label']} (Upload)")
    _ccfg.setdefault("otp_digits", 5)
    _ccfg.setdefault("strip_prefix", False)
    _ccfg.setdefault("prefix", "")

save_db("data", data)
save_db("config", config_db)

admin_states = {}
user_deposit_amounts = {}
pending_new_country = {}

def get_all_country_keys():
    base = ["USA", "China", "Canada"]
    custom = list(config_db.get("custom_countries", {}).keys())
    return base + custom

def get_country_config(country_key):
    if country_key in config_db.get("country_settings", {}):
        return config_db["country_settings"][country_key]
    if country_key in config_db.get("custom_countries", {}):
        return config_db["custom_countries"][country_key]
    return {
        "label": country_key,
        "btn_text": f"🌍 {country_key}",
        "upload_label": f"{country_key} (Upload)",
        "otp_digits": 5,
        "strip_prefix": False,
        "prefix": ""
    }

def find_country_by_upload_text(text):
    for c_key in get_all_country_keys():
        cfg = get_country_config(c_key)
        if cfg.get("upload_label") == text:
            return c_key
    return None

# ==========================================
# Mail.tm Functions
# ==========================================
async def create_mail_tm_account():
    client_kwargs = {"timeout": 15.0}
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            domains_res = await client.get(f"{MAIL_TM_BASE}/domains")
            if domains_res.status_code != 200:
                return None, None
                
            domains = domains_res.json().get("hydra:member", [])
            if not domains:
                return None, None
            domain = domains[0]["domain"]

            username = f"user_{int(time.time())}_{random.randint(1000, 9999)}"
            password = "SecurePassword123!"
            address = f"{username}@{domain}"

            reg_res = await client.post(f"{MAIL_TM_BASE}/accounts", json={
                "address": address,
                "password": password
            })
            
            if reg_res.status_code in [200, 201]:
                token_res = await client.post(f"{MAIL_TM_BASE}/token", json={
                    "address": address,
                    "password": password
                })
                if token_res.status_code in [200, 201]:
                    token = token_res.json().get("token")
                    if token:
                        return address, token
    except Exception as e:
        logging.error(f"Exception in create_mail_tm_account: {e}")
    return None, None

async def prefetch_mail_tm_pool():
    global mail_tm_pool
    while True:
        try:
            if len(mail_tm_pool) < 5:
                addr, token = await create_mail_tm_account()
                if addr and token:
                    mail_tm_pool.append({"address": addr, "token": token})
        except Exception as e:
            logging.error(f"Error in prefetch pool: {e}")
        await asyncio.sleep(2)

async def check_mail_tm_code(token):
    client_kwargs = {"timeout": 15.0}
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            headers = {"Authorization": f"Bearer {token}"}
            messages_res = await client.get(f"{MAIL_TM_BASE}/messages", headers=headers)
            
            if messages_res.status_code != 200:
                return None
                
            messages = messages_res.json().get("hydra:member", [])
            if messages:
                msg_id = messages[0]["id"]
                msg_res = await client.get(f"{MAIL_TM_BASE}/messages/{msg_id}", headers=headers)
                if msg_res.status_code == 200:
                    msg_data = msg_res.json()
                    content = msg_data.get("text", "") or msg_data.get("intro", "")
                    
                    codes = re.findall(r'\b\d{5,6}\b', content)
                    if codes:
                        return codes[-1]
    except Exception as e:
        logging.error(f"Exception in check_mail_tm_code: {e}")
    return None

# ==========================================
# Helper Functions (Backup, Random Name, Line Processing)
# ==========================================
def save_all_dbs():
    save_db("data", data)
    save_db("users", users_db)
    save_db("config", config_db)
    save_db("mail_tokens", mail_tokens_db)

async def save_all_dbs_async():
    await asyncio.to_thread(save_all_dbs)

def create_backup_zip():
    save_all_dbs()
    backup_filename = "database_backup.zip"
    snapshot_db = "snapshot_bot_database.db"
    if os.path.exists(DB_FILE):
        src_conn = sqlite3.connect(DB_FILE)
        dst_conn = sqlite3.connect(snapshot_db)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(snapshot_db, arcname=DB_FILE)
        if os.path.exists(snapshot_db):
            os.remove(snapshot_db)
    return backup_filename

async def get_unique_name(country):
    while True:
        if country == "China":
            name = f"{fake_zh.first_name()} {fake_zh.last_name()}"
        else:
            name = f"{fake_en.first_name()} {fake_en.last_name()}"
            
        if name not in data["used_names"]:
            data["used_names"].append(name)
            await save_db_async("data", data)
            return name

def process_data_line(line, country="USA"):
    line = line.strip()
    if not line:
        return None, None
        
    link_match = re.search(r'(https?://[^\s]+)', line)
    if not link_match:
        return None, None
        
    link = link_match.group(1).strip()
    remainder = line.replace(link, "")
    phone = re.sub(r'[^\d+]', '', remainder)
    
    cfg = get_country_config(country)
    if cfg.get("strip_prefix", False):
        prefix = str(cfg.get("prefix", "")).strip()
        if prefix:
            phone_digits_only = re.sub(r'\D', '', phone)
            if phone_digits_only.startswith(prefix):
                phone = phone_digits_only[len(prefix):]

    if not phone:
        return None, None
        
    return link, phone

def get_user_record(user_id):
    u_str = str(user_id)
    if u_str not in users_db:
        users_db[u_str] = {
            "balance": 0.0,
            "total_purchased": 0,
            "total_spent": 0.0,
            "banned": False,
            "referrals": 0,
            "ref_earnings": 0.0,
            "referred_by": None,
            "deposit_history": [],
            "canceled_count": 0
        }
        save_db("users", users_db)
    if "canceled_count" not in users_db[u_str]:
        users_db[u_str]["canceled_count"] = 0
    return users_db[u_str]

# ==========================================
# Nightly Report — Only 24h cycle counts (resets at 12:00 AM Iran Time)
# ==========================================
def get_daily_stats():
    if "daily_stats" not in config_db:
        config_db["daily_stats"] = {
            "since_ts": time.time(),
            "last_sent_date": ""
        }
    for ck in get_all_country_keys():
        config_db["daily_stats"].setdefault(ck, {"assigned": 0, "nocode": 0})
    save_db("config", config_db)
    return config_db["daily_stats"]

def reset_daily_stats(sent_date_str=""):
    st = {
        "since_ts": time.time(),
        "last_sent_date": sent_date_str
    }
    for ck in get_all_country_keys():
        st[ck] = {"assigned": 0, "nocode": 0}
    config_db["daily_stats"] = st
    save_db("config", config_db)

def build_nightly_report():
    """Nightly report based only on current 24h cycle (resets to 0 after 12:00 AM report)"""
    d_stats = get_daily_stats()
    since_ts = d_stats.get("since_ts", 0)
    
    iran_tz = timezone(timedelta(hours=3, minutes=30))
    now_str = datetime.now(iran_tz).strftime("%Y-%m-%d %H:%M")
    
    lines = [f"📊 **Nightly 24-Hour Report — {now_str} (Iran Time)**", "━━━━━━━━━━━━━━━━━━"]
    
    total_otp = 0
    total_assigned = 0
    total_nocode = 0
    
    for country in get_all_country_keys():
        flag = get_country_config(country).get("label", country)
        
        otp_items = [
            n for n in data.get(country, [])
            if n.get("status") == "used"
            and n.get("has_code", False)
            and n.get("code_received_at", 0) >= since_ts
        ]
        
        c_stats = d_stats.get(country, {"assigned": 0, "nocode": 0})
        assigned_count = max(c_stats.get("assigned", 0), len(otp_items))
        nocode_count = c_stats.get("nocode", 0)
        
        count = len(otp_items)
        total_otp += count
        total_assigned += assigned_count
        total_nocode += nocode_count
        
        lines.append(f"{flag} **{country}:**")
        lines.append(f"   ├ ✅ OTP Received: `{count}`")
        lines.append(f"   ├ 📱 Assigned: `{assigned_count}`")
        lines.append(f"   └ ⏳ No OTP (Refunded/Canceled): `{nocode_count}`")
        lines.append("")
        
        if otp_items:
            lines.append(f"   📋 **{country} Details (OTP Received):**")
            for n in otp_items[-20:]:
                t = datetime.fromtimestamp(n["code_received_at"], iran_tz).strftime("%H:%M")
                lines.append(f"   • `{n['number']}` — {t}")
            lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 **24-Hour Total:**")
    lines.append(f"   ├ 🔢 Total OTP Received: `{total_otp}`")
    lines.append(f"   ├ 📱 Total Assigned: `{total_assigned}`")
    lines.append(f"   └ ⏳ Total No OTP: `{total_nocode}`")
    
    return "\n".join(lines)

async def nightly_report_worker(application: Application):
    """Checks every 20 seconds so 12:00 AM Iran Time is never missed, sends report, and resets stats to 0"""
    iran_tz = timezone(timedelta(hours=3, minutes=30))
    while True:
        try:
            now = datetime.now(iran_tz)
            today_str = now.strftime("%Y-%m-%d")
            d_stats = get_daily_stats()
            
            if now.hour == 0 and now.minute < 5 and d_stats.get("last_sent_date") != today_str:
                report = build_nightly_report()
                await application.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=report,
                    parse_mode="Markdown"
                )
                reset_daily_stats(sent_date_str=today_str)
                await save_db_async("config", config_db)
                logging.info(f"✅ Nightly report sent and daily stats reset for {today_str}")
        except Exception as e:
            logging.error(f"Nightly report error: {e}")
        await asyncio.sleep(20)

# ==========================================
# Full User Report
# ==========================================
def build_user_report():
    """Full activity report of all users"""
    iran_tz = timezone(timedelta(hours=3, minutes=30))
    now_str = datetime.now(iran_tz).strftime("%Y-%m-%d %H:%M")
    
    lines = [f"👥 **Full User Report — {now_str} (Iran Time)**", "━━━━━━━━━━━━━━━━━━"]
    
    if not users_db:
        lines.append("❌ No users registered yet.")
        return "\n".join(lines)
    
    for uid, u in users_db.items():
        per_c = {}
        any_used = False
        for country in get_all_country_keys():
            used_c = otp_c = nocode_c = 0
            for n in data.get(country, []):
                if n.get("user_id") == int(uid) and n.get("status") == "used":
                    used_c += 1
                    any_used = True
                    if n.get("has_code"):
                        otp_c += 1
                    else:
                        nocode_c += 1
            per_c[country] = (used_c, otp_c, nocode_c)
        
        canceled = u.get("canceled_count", 0)
        bal = u.get("balance", 0.0)
        
        if not any_used and canceled == 0 and bal == 0.0:
            continue
        
        lines.append(f"🆔 **User ID:** `{uid}`")
        lines.append(f"   ├ 💰 Balance: `${bal:.3f}`")
        for country in get_all_country_keys():
            used_c, otp_c, nocode_c = per_c[country]
            lbl = get_country_config(country).get("label", country)
            lines.append(f"   ├ {lbl} → Purchased: `{used_c}` | OTP: `{otp_c}` | No OTP: `{nocode_c}`")
        lines.append(f"   └ ❌ Canceled: `{canceled}`")
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 **Total Active Users:** `{len(users_db)}`")
    return "\n".join(lines)

# ==========================================
# Background Auto-Refund Worker (15-minute timeout)
# ==========================================
async def auto_refund_worker(application: Application):
    while True:
        await asyncio.sleep(60)
        try:
            current_time = time.time()
            updated = False
            for country in get_all_country_keys():
                for item in data.get(country, []):
                    if item.get("status") == "used" and not item.get("has_code", False):
                        assigned_time = item.get("assigned_at", 0)
                        if assigned_time > 0 and (current_time - assigned_time) >= 900: # 15 Mins
                            user_id = item.get("user_id")
                            if user_id:
                                u_rec = get_user_record(user_id)
                                refund_amount = item.get("paid_price", config_db.get("prices", {}).get(country, 0.175))
                                u_rec["balance"] = round(u_rec.get("balance", 0.0) + refund_amount, 4)
                                
                                data.setdefault("canceled", []).append({
                                    "country": country,
                                    "number": item.get("number", ""),
                                    "link": item.get("link", ""),
                                    "user_id": user_id,
                                    "reason": "auto_refund_15m",
                                    "ts": current_time
                                })
                                item["status"] = "free"
                                item["user_id"] = None
                                item["assigned_at"] = 0
                                d_st = get_daily_stats()
                                d_st[country]["nocode"] = d_st[country].get("nocode", 0) + 1
                                updated = True
                                
                                try:
                                    await application.bot.send_message(
                                        chat_id=int(user_id),
                                        text=f"⏰ **Automatic Refund (15-Min Timeout)**\n\nNo OTP was received within 15 minutes for your {country} number. `${refund_amount:.3f} USD` has been refunded to your balance.",
                                        parse_mode="Markdown"
                                    )
                                except Exception:
                                    pass
            if updated:
                await save_db_async("config", config_db)
                await save_db_async("users", users_db)
                await save_db_async("data", data)
        except Exception as e:
            logging.error(f"Error in auto_refund_worker: {e}")

# ==========================================
# Reply Keyboards
# ==========================================
def get_main_keyboard(user_id):
    keys = [
        ["⚡ Buy Number", "📧 Mail.tm Email"],
        ["💼 Deposit", "🆔 Profile"],
        ["🎁 Refer & Earn", "👀 Support"]
    ]
    if user_id == ADMIN_ID:
        keys.append(["⚙️ Admin Panel"])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Add Numbers", "💰 Manage Balance"],
        ["💵 Set Prices", "🏦 Set USDT Wallet"],
        ["📊 Statistics", "👥 User Report"],
        ["🗑 Delete", "📥 Export"],
        ["📢 Broadcast", "⚙️ System Toggle"],
        ["📁 Send Database", "🔙 User Menu"]
    ], resize_keyboard=True)

def get_country_upload_keyboard():
    rows = []
    row = []
    for c_key in get_all_country_keys():
        cfg = get_country_config(c_key)
        row.append(cfg.get("upload_label", f"{c_key} (Upload)"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(["🔙 Back to Admin"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def get_price_country_keyboard():
    prices = config_db.get("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
    rows = []
    row = []
    for c_key in get_all_country_keys():
        cfg = get_country_config(c_key)
        p_val = prices.get(c_key, 0.175)
        row.append(f"💵 {cfg.get('label', c_key)} (${p_val:.3f})")
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([f"📧 Mail.tm (${prices.get('MailTM', 0.01):.3f})", "➕ Add Number Menu"])
    rows.append(["💲 Set Base Costs", "🔙 Back to Admin"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def get_prefix_choice_keyboard():
    return ReplyKeyboardMarkup([
        ["✂️ Strip Prefix", "📌 Keep Prefix"],
        ["🔙 Back to Admin"]
    ], resize_keyboard=True)

def get_delete_keyboard():
    return ReplyKeyboardMarkup([
        ["♻️ Delete Used (OTP Received)", "🗑 Delete All Numbers"],
        ["🔙 Back to Admin"]
    ], resize_keyboard=True)

def get_export_keyboard():
    return ReplyKeyboardMarkup([
        ["✅ OTP Received", "⏳ No OTP"],
        ["❌ Canceled", "🔙 Back to Admin"]
    ], resize_keyboard=True)

def get_target_keyboard():
    return ReplyKeyboardMarkup([
        ["🌐 All Users", "👤 Specific User"],
        ["🔙 Back to Admin"]
    ], resize_keyboard=True)

def get_cancel_admin_keyboard():
    return ReplyKeyboardMarkup([["🔙 Back to Admin"]], resize_keyboard=True)

def get_cancel_user_keyboard():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)

# ==========================================
# Inline Keyboard Builder
# ==========================================
def build_country_selection_markup():
    prices = config_db.get("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
    buttons = []
    for c_key in get_all_country_keys():
        free_cnt = len([n for n in data.get(c_key, []) if n.get("status") == "free"])
        if free_cnt > 0:
            cfg = get_country_config(c_key)
            p_val = prices.get(c_key, 0.175)
            btn_label = f"{cfg.get('btn_text', cfg.get('label', c_key))} USD {p_val:.3f}"
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"buy_country_{c_key}")])
    if not buttons:
        return None
    return InlineKeyboardMarkup(buttons)

# ==========================================
# Command & Text Message Handlers
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    u_rec = get_user_record(user_id)
    admin_states.pop(user_id, None)
    user_deposit_amounts.pop(user_id, None)

    if user_id != ADMIN_ID:
        if not config_db.get("active", True):
            await update.message.reply_text("🔴 The bot is currently under maintenance. Please try again later.")
            return
        if u_rec.get("banned", False):
            await update.message.reply_text("⛔ You have been banned from using this bot.")
            return

    if len(context.args) > 0 and u_rec.get("referred_by") is None and str(user_id) not in users_db.get("dummy", {}):
        referrer_id = context.args[0]
        if referrer_id != str(user_id) and referrer_id in users_db:
            u_rec["referred_by"] = referrer_id
            users_db[referrer_id]["referrals"] = users_db[referrer_id].get("referrals", 0) + 1
            await save_db_async("users", users_db)

    welcome_text = (
        f"👋 **Welcome, {user.first_name}!**\n\n"
        f"⚡ Instant Virtual Numbers, Temp Emails & Automated OTP Delivery.\n"
        f"Select an option from the menu below:"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

async def send_export_file(update, export_lines, filename="export.txt"):
    if not export_lines:
        await update.message.reply_text("❌ No records found matching your criteria.", reply_markup=get_admin_keyboard())
        return
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(export_lines))
        
    with open(filename, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=filename,
            caption=f"📥 **Exported Numbers**\n\nTotal Count: `{len(export_lines)}`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    if os.path.exists(filename):
        os.remove(filename)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    u_rec = get_user_record(user_id)

    state = admin_states.get(user_id)

    is_deposit_step = state in ["WAITING_DEPOSIT_AMOUNT", "WAITING_DEPOSIT_HASH"]

    if user_id != ADMIN_ID and not is_deposit_step:
        if not config_db.get("active", True):
            await update.message.reply_text("🔴 The bot is currently under maintenance.")
            return
        if u_rec.get("banned", False):
            await update.message.reply_text("⛔ You are banned from using this bot.")
            return

    if text == "❌ Cancel":
        admin_states.pop(user_id, None)
        user_deposit_amounts.pop(user_id, None)
        pending_new_country.pop(user_id, None)
        await update.message.reply_text("❌ Process canceled.", reply_markup=get_main_keyboard(user_id))
        return

    if text == "🔙 User Menu":
        admin_states.pop(user_id, None)
        await update.message.reply_text("🏠 Switched to User Menu:", reply_markup=get_main_keyboard(user_id))
        return
    elif text == "🔙 Back to Admin" and user_id == ADMIN_ID:
        admin_states.pop(user_id, None)
        pending_new_country.pop(user_id, None)
        await update.message.reply_text("⚙️ Admin Panel:", reply_markup=get_admin_keyboard())
        return

    # ==========================================
    # Mail.tm Email Purchase Flow
    # ==========================================
    if text == "📧 Mail.tm Email":
        prices = config_db.get("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
        price = prices.get("MailTM", 0.01)

        if u_rec.get("balance", 0.0) < price:
            await update.message.reply_text(
                f"❌ **Insufficient Balance!**\n\n"
                f"💵 **Email Price:** `${price:.3f} USD`\n"
                f"💰 **Your Balance:** `${u_rec.get('balance', 0.0):.3f} USD`\n\n"
                f"Please top up your account via **💼 Deposit**.",
                parse_mode="Markdown"
            )
            return

        email_addr, mail_token = None, None
        if mail_tm_pool:
            item = mail_tm_pool.pop(0)
            email_addr, mail_token = item["address"], item["token"]
        else:
            wait_msg = await update.message.reply_text("⏳ Generating fresh Mail.tm address...")
            email_addr, mail_token = await create_mail_tm_account()
            try:
                await wait_msg.delete()
            except Exception:
                pass

        if email_addr and mail_token:
            u_rec["balance"] = round(u_rec.get("balance", 0.0) - price, 4)
            u_rec["total_purchased"] = u_rec.get("total_purchased", 0) + 1
            u_rec["total_spent"] = round(u_rec.get("total_spent", 0.0) + price, 4)
            await save_db_async("users", users_db)

            req_key = f"mtm_{int(time.time())}_{random.randint(1000, 9999)}"
            mail_tokens_db[req_key] = {
                "token": mail_token,
                "email": email_addr,
                "user_id": user_id,
                "attempts": 0,
                "price": price,
                "codes": []
            }
            await save_db_async("mail_tokens", mail_tokens_db)

            msg = (
                f"📧 **Mail.tm Temporary Email**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✉️ **Email:** `{email_addr}`\n"
                f"💵 **Price:** `${price:.3f} USD`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 *Tap the email above to copy, request your verification code, then press* **Get Code** *below (up to 2 codes per email).*"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Get Code", callback_data=f"mtm_code_{req_key}")]
            ])
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        else:
            await update.message.reply_text("❌ Failed to generate a Mail.tm address right now. No balance was deducted. Please try again.")
        return

    # ==========================================
    # Deposit Flow
    # ==========================================
    if text == "💼 Deposit":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 BEP20 (USDT)", callback_data="deposit_bep20")]
        ])
        await update.message.reply_text("💰 Choose a deposit method:", reply_markup=markup)
        return

    if state == "WAITING_DEPOSIT_AMOUNT":
        try:
            amount = float(text.strip())
            if amount <= 0:
                raise ValueError
            
            user_deposit_amounts[user_id] = round(amount, 4)
            admin_states[user_id] = "WAITING_DEPOSIT_HASH"
            
            msg = "💯 Now enter your Order ID / Transaction Hash (TxID):"
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_deposit_inline")]
            ])
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount! Please enter a valid positive number in USD (e.g., `10`).", parse_mode="Markdown")
        return

    if state == "WAITING_DEPOSIT_HASH":
        tx_hash = text.strip()
        if len(tx_hash) < 10:
            await update.message.reply_text("❌ Invalid Transaction Hash! Please send a valid TxID.")
            return

        amount = user_deposit_amounts.pop(user_id, 0.0)
        admin_states.pop(user_id, None)
        
        user_obj = update.message.from_user
        username_str = f"@{user_obj.username}" if user_obj.username else "No Username"
        
        admin_invoice = (
            f"🔔 **NEW DEPOSIT REQUEST**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **User:** {user_obj.first_name} ({username_str})\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"💵 **Amount:** `${amount:.3f} USD (USDT BEP20)`\n"
            f"🔗 **Transaction Hash (TxID):**\n`{tx_hash}`\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        
        admin_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm & Add Balance", callback_data=f"dep_approve_{user_id}_{amount}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"dep_reject_{user_id}_{amount}")
            ]
        ])
        
        invoice_sent = False
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_invoice,
                parse_mode="Markdown",
                reply_markup=admin_markup
            )
            invoice_sent = True
        except Exception as e:
            logging.error(f"Failed to send deposit invoice to admin: {e}")
            await update.message.reply_text(
                f"⚠️ **System Error:**\nCould not forward your invoice to the admin.\n"
                f"Error: `{str(e)}`\n\nPlease contact support directly.",
                parse_mode="Markdown"
            )
            return

        if invoice_sent:
            await update.message.reply_text(
                "⏳ **Transaction Submitted!**\n\n"
                "Your payment invoice and transaction hash have been sent to the admin for verification. "
                "You will be notified as soon as it is approved.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
        return

    # ==========================================
    # Profile, Referral & Support
    # ==========================================
    if text == "🆔 Profile":
        bal = u_rec.get("balance", 0.0)
        purchased = u_rec.get("total_purchased", 0)
        spent = u_rec.get("total_spent", 0.0)
        refs = u_rec.get("referrals", 0)
        ref_earn = u_rec.get("ref_earnings", 0.0)
        
        profile_msg = (
            f"🎉 **Your Profile**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📩 **Name:** {update.message.from_user.first_name}\n"
            f"💰 **Balance:** {bal:.3f} USDT\n"
            f"👑 **Total Purchased:** {purchased} items\n"
            f"💵 **Total Spent:** {spent:.3f} USDT\n"
            f"📊 **Referrals:** {refs} ({ref_earn:.3f} USDT earned)"
        )
        
        profile_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏅 My Referrals", callback_data="my_referrals"), 
             InlineKeyboardButton("💳 My Orders", callback_data="my_orders")]
        ])
        await update.message.reply_text(profile_msg, parse_mode="Markdown", reply_markup=profile_markup)
        return

    if text == "👀 Support":
        support_text = (
            "🌟 **Support & Refund Policy**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚨 • Fresh Link numbers have no auto refunds.\n"
            "• Panel numbers can be canceled after 5 mins and auto-refund after **15 mins** if no OTP arrives.\n\n"
            "For any issue, please message our Admin directly:"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗣 Contact Admin Support", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")]
        ])
        await update.message.reply_text(support_text, parse_mode="Markdown", reply_markup=markup)
        return

    if text == "🎁 Refer & Earn":
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        refs = u_rec.get("referrals", 0)
        ref_earn = u_rec.get("ref_earnings", 0.0)
        
        ref_msg = (
            "📊 **Refer & Earn Program**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Invite friends using your referral link and earn **3% Commission** on every deposit they make!\n\n"
            f"🎉 **Total Referrals:** {refs}\n"
            f"💰 **Referral Earnings:** {ref_earn:.3f} USDT\n\n"
            f"🔗 **Your Referral Link (Tap to copy):**\n`{ref_link}`"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Share Referral Link", url=f"https://t.me/share/url?url={ref_link}&text=Join%20and%20earn!")]
        ])
        await update.message.reply_text(ref_msg, parse_mode="Markdown", reply_markup=markup)
        return

    if text == "⚡ Buy Number":
        markup = build_country_selection_markup()
        if not markup:
            await update.message.reply_text("❌ **Out of Stock!**\nNo numbers are currently available. Please check back later.", parse_mode="Markdown")
            return
        await update.message.reply_text("🌍 **Select a country:**", parse_mode="Markdown", reply_markup=markup)
        return

    # ==========================================
    # Admin Panel Section
    # ==========================================
    if user_id != ADMIN_ID:
        return

    if text == "⚙️ Admin Panel":
        admin_states.pop(user_id, None)
        await update.message.reply_text("⚙️ **Welcome to Admin Panel:**", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        return

    if text == "🏦 Set USDT Wallet":
        current_wallet = config_db.get("usdt_bep20_address", "Not Set")
        admin_states[user_id] = "WAITING_USDT_WALLET"
        await update.message.reply_text(
            f"🏦 **USDT (BEP20) Wallet Settings**\n\n📍 **Current Address:**\n`{current_wallet}`\n\n✍️ Send the new wallet address:",
            parse_mode="Markdown",
            reply_markup=get_cancel_admin_keyboard()
        )
        return

    if state == "WAITING_USDT_WALLET":
        new_wallet = text.strip()
        if len(new_wallet) < 15:
            await update.message.reply_text("❌ Invalid wallet address!")
            return
        config_db["usdt_bep20_address"] = new_wallet
        await save_db_async("config", config_db)
        admin_states.pop(user_id, None)
        await update.message.reply_text(f"✅ Wallet Updated to:\n`{new_wallet}`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        return

    if text == "📁 Send Database":
        try:
            backup_filename = await asyncio.to_thread(create_backup_zip)
            if os.path.exists(backup_filename):
                with open(backup_filename, "rb") as f:
                    await update.message.reply_document(document=f, filename=backup_filename, caption="📁 Database Backup", reply_markup=get_admin_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Backup error: {e}")
        return

    if text == "➕ Add Numbers":
        await update.message.reply_text("📂 Select country to upload numbers:", reply_markup=get_country_upload_keyboard())
        return

    upload_ck = find_country_by_upload_text(text)
    if upload_ck:
        admin_states[user_id] = f"WAITING_FILE_{upload_ck}"
        await update.message.reply_text("📄 Please send the `.txt` file:", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
        return

    if text == "💰 Manage Balance":
        admin_states[user_id] = "WAITING_BAL_USER_ID"
        await update.message.reply_text("🆔 Enter the **User ID**:", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
        return

    if state == "WAITING_BAL_USER_ID":
        if not text.isdigit():
            await update.message.reply_text("❌ Invalid User ID.")
            return
        target_rec = get_user_record(int(text))
        admin_states[user_id] = f"WAITING_BAL_AMOUNT_{text}"
        await update.message.reply_text(f"👤 User ID: `{text}`\n💵 Current Balance: `${target_rec.get('balance', 0.0):.3f} USD`\n\n✍️ Enter amount to add/deduct:", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
        return

    if state and state.startswith("WAITING_BAL_AMOUNT_"):
        target_id = state.split("_")[-1]
        try:
            amount = float(text)
            target_rec = get_user_record(int(target_id))
            target_rec["balance"] = round(max(0.0, target_rec.get("balance", 0.0) + amount), 4)
            await save_db_async("users", users_db)
            await update.message.reply_text(f"✅ Balance Updated for `{target_id}`. New: `${target_rec['balance']:.3f} USD`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
            admin_states.pop(user_id, None)
        except ValueError:
            await update.message.reply_text("❌ Invalid number format.")
        return

    if text == "💵 Set Prices":
        prices = config_db.get("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
        base_costs = config_db.get("base_costs", {"USA": 0.100, "China": 0.120, "Canada": 0.100})
        lines_p = ["💵 **Current Prices:**"]
        for ck in get_all_country_keys():
            cfg = get_country_config(ck)
            lines_p.append(f"{cfg.get('label', ck)}: `${prices.get(ck, 0.175):.3f}` (Cost: ${base_costs.get(ck, 0.100):.3f})")
        lines_p.append(f"📧 Mail.tm: `${prices.get('MailTM', 0.01):.3f}`")
        lines_p.append("\nSelect an option or add a new number menu:")
        await update.message.reply_text(
            "\n".join(lines_p),
            parse_mode="Markdown",
            reply_markup=get_price_country_keyboard()
        )
        return

    if text == "➕ Add Number Menu":
        pending_new_country[user_id] = {}
        admin_states[user_id] = "NEW_COUNTRY_NAME"
        await update.message.reply_text(
            "🆕 **Add New Number Menu**\n\nEnter the menu/country name (e.g., `UAE`, `UK`, or `Turkey`):",
            parse_mode="Markdown",
            reply_markup=get_cancel_admin_keyboard()
        )
        return

    if state == "NEW_COUNTRY_NAME":
        title_clean = text.strip()
        if not title_clean:
            await update.message.reply_text("❌ Name cannot be empty.")
            return
        safe_key = re.sub(r'[^A-Za-z0-9_]', '_', title_clean)
        if not safe_key or safe_key in get_all_country_keys():
            safe_key = f"Custom_{int(time.time()) % 10000}"
        label = title_clean if any(ord(ch) > 127 for ch in title_clean) else f"🌍 {title_clean}"
        pending_new_country[user_id] = {
            "key": safe_key,
            "label": label,
            "btn_text": f"{label} Number",
            "upload_label": f"{label} (Upload)"
        }
        admin_states[user_id] = "NEW_COUNTRY_PRICE"
        await update.message.reply_text(
            f"💵 Enter the **Sell Price** in USD for **{label}** (e.g., `0.18`):",
            parse_mode="Markdown",
            reply_markup=get_cancel_admin_keyboard()
        )
        return

    if state == "NEW_COUNTRY_PRICE":
        try:
            p_val = float(text.strip())
            if p_val < 0:
                raise ValueError
            pending_new_country[user_id]["price"] = round(p_val, 4)
            admin_states[user_id] = "NEW_COUNTRY_OTP_DIGITS"
            await update.message.reply_text(
                "🔢 How many digits is the **OTP code** for this menu? (Usually `5` or `6` — enter a number):",
                parse_mode="Markdown",
                reply_markup=get_cancel_admin_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid price.")
        return

    if state == "NEW_COUNTRY_OTP_DIGITS":
        try:
            digits = int(text.strip())
            if digits < 3 or digits > 10:
                raise ValueError
            pending_new_country[user_id]["otp_digits"] = digits
            admin_states[user_id] = "NEW_COUNTRY_PREFIX_MODE"
            await update.message.reply_text(
                "✂️ Should numbers in this menu strip a prefix when uploaded?",
                parse_mode="Markdown",
                reply_markup=get_prefix_choice_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid digit count (e.g., `5` or `6`).")
        return

    if state == "NEW_COUNTRY_PREFIX_MODE":
        if text == "✂️ Strip Prefix":
            pending_new_country[user_id]["strip_prefix"] = True
            admin_states[user_id] = "NEW_COUNTRY_PREFIX_VAL"
            await update.message.reply_text(
                "🔢 Enter the prefix to strip from the beginning of numbers (e.g., `1`, `971`, or `44`):",
                parse_mode="Markdown",
                reply_markup=get_cancel_admin_keyboard()
            )
        elif text == "📌 Keep Prefix":
            cfg_draft = pending_new_country.pop(user_id, {})
            c_key = cfg_draft["key"]
            new_cfg = {
                "label": cfg_draft["label"],
                "btn_text": cfg_draft["btn_text"],
                "upload_label": cfg_draft["upload_label"],
                "price": cfg_draft["price"],
                "otp_digits": cfg_draft["otp_digits"],
                "strip_prefix": False,
                "prefix": ""
            }
            config_db["custom_countries"][c_key] = new_cfg
            config_db["prices"][c_key] = new_cfg["price"]
            config_db.setdefault("base_costs", {}).setdefault(c_key, round(new_cfg["price"] * 0.6, 4))
            if c_key not in data:
                data[c_key] = []
            get_daily_stats()
            await save_all_dbs_async()
            admin_states.pop(user_id, None)
            await update.message.reply_text(
                f"✅ New menu **{new_cfg['label']}** created and added to **Buy Number** and **Add Numbers**.\n"
                f"▫️ Price: `${new_cfg['price']:.3f}` | OTP: `{new_cfg['otp_digits']}` digits | Strip Prefix: No",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
        return

    if state == "NEW_COUNTRY_PREFIX_VAL":
        prefix_clean = re.sub(r'\D', '', text.strip())
        cfg_draft = pending_new_country.pop(user_id, {})
        c_key = cfg_draft["key"]
        new_cfg = {
            "label": cfg_draft["label"],
            "btn_text": cfg_draft["btn_text"],
            "upload_label": cfg_draft["upload_label"],
            "price": cfg_draft["price"],
            "otp_digits": cfg_draft["otp_digits"],
            "strip_prefix": bool(prefix_clean),
            "prefix": prefix_clean
        }
        config_db["custom_countries"][c_key] = new_cfg
        config_db["prices"][c_key] = new_cfg["price"]
        config_db.setdefault("base_costs", {}).setdefault(c_key, round(new_cfg["price"] * 0.6, 4))
        if c_key not in data:
            data[c_key] = []
        get_daily_stats()
        await save_all_dbs_async()
        admin_states.pop(user_id, None)
        await update.message.reply_text(
            f"✅ New menu **{new_cfg['label']}** created and added to **Buy Number** and **Add Numbers**.\n"
            f"▫️ Price: `${new_cfg['price']:.3f}` | OTP: `{new_cfg['otp_digits']}` digits | Stripped Prefix: `{prefix_clean or 'None'}`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
        return

    if text.startswith("📧 Mail.tm"):
        admin_states[user_id] = "WAITING_PRICE_MailTM"
        await update.message.reply_text("✍️ Enter new **Sell Price** for **MailTM**:", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
        return

    for _ck in get_all_country_keys():
        _cfg = get_country_config(_ck)
        if text.startswith(f"💵 {_cfg.get('label', _ck)}"):
            admin_states[user_id] = f"WAITING_PRICE_{_ck}"
            await update.message.reply_text(f"✍️ Enter new **Sell Price** for **{_cfg.get('label', _ck)}**:", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
            return

    if state and state.startswith("WAITING_PRICE_"):
        c_key = state.replace("WAITING_PRICE_", "", 1)
        try:
            new_price = float(text)
            if new_price < 0:
                raise ValueError
            if "prices" not in config_db:
                config_db["prices"] = {}
            config_db["prices"][c_key] = round(new_price, 4)
            if c_key in config_db.get("custom_countries", {}):
                config_db["custom_countries"][c_key]["price"] = round(new_price, 4)
            await save_db_async("config", config_db)
            await update.message.reply_text(f"✅ **{c_key}** Price updated to `${new_price:.3f}`.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
            admin_states.pop(user_id, None)
        except ValueError:
            await update.message.reply_text("❌ Invalid price.")
        return
        
    if text == "💲 Set Base Costs":
        admin_states[user_id] = "WAITING_BASE_COST_COUNTRY"
        await update.message.reply_text("💲 Enter country to set base cost (`USA`, `China`, `Canada` or custom key):", parse_mode="Markdown", reply_markup=get_cancel_admin_keyboard())
        return

    if state == "WAITING_BASE_COST_COUNTRY":
        raw_c = text.strip()
        c_key = None
        for ck in get_all_country_keys():
            if ck.lower() == raw_c.lower() or get_country_config(ck).get("label") == raw_c:
                c_key = ck
                break
        if not c_key:
            await update.message.reply_text("❌ Invalid country.")
            return
        admin_states[user_id] = f"WAITING_BASE_COST_AMT_{c_key}"
        await update.message.reply_text(f"✍️ Enter new **Base Cost** for **{c_key}**:", parse_mode="Markdown")
        return

    if state and state.startswith("WAITING_BASE_COST_AMT_"):
        c_key = state.replace("WAITING_BASE_COST_AMT_", "", 1)
        try:
            new_cost = float(text)
            config_db.setdefault("base_costs", {})[c_key] = round(new_cost, 4)
            await save_db_async("config", config_db)
            await update.message.reply_text(f"✅ **{c_key}** Base Cost updated to `${new_cost:.3f}`.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
            admin_states.pop(user_id, None)
        except ValueError:
            await update.message.reply_text("❌ Invalid number.")
        return

    if text == "📊 Statistics":
        total_users = len(users_db)
        total_bal = sum(u.get("balance", 0.0) for u in users_db.values())
        
        base_costs = config_db.get("base_costs", {"USA": 0.100, "China": 0.120, "Canada": 0.100})
        total_cost = 0.0
        inv_lines = []
        for ck in get_all_country_keys():
            c_all = data.get(ck, [])
            c_free = len([n for n in c_all if n.get("status") == "free"])
            c_otp = len([n for n in c_all if n.get("status") == "used" and n.get("has_code")])
            total_cost += c_otp * base_costs.get(ck, 0.100)
            cfg = get_country_config(ck)
            inv_lines.append(f"{cfg.get('label', ck)} Inventory:\n   ├ 🆓 Free: `{c_free}`\n   └ ✅ OTP Received: `{c_otp}`")

        total_deposits = config_db.get("total_deposits", 0.0)
        total_spent = sum(u.get("total_spent", 0.0) for u in users_db.values())
        net_profit = total_spent - total_cost

        stats_msg = (
            f"📊 **BOT STATISTICS**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 **Total Users:** `{total_users}`\n"
            f"💵 **Users Balance:** `${total_bal:.3f} USD`\n\n"
            + "\n\n".join(inv_lines) +
            f"\n\n💰 **Financials:**\n"
            f"   ├ Total Deposits: `${total_deposits:.3f}`\n"
            f"   ├ Total Sales: `${total_spent:.3f}`\n"
            f"   └ **Net Profit:** `${net_profit:.3f} USD`"
        )
        await update.message.reply_text(stats_msg, parse_mode="Markdown")

        report = build_nightly_report()
        await update.message.reply_text(report, parse_mode="Markdown")
        return

    if text == "👥 User Report":
        report = build_user_report()
        if len(report) > 4000:
            filename = "user_report.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(report)
            with open(filename, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption="👥 **User Report** (Too long, sent as file)",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard()
                )
            os.remove(filename)
        else:
            await update.message.reply_text(report, parse_mode="Markdown", reply_markup=get_admin_keyboard())
        return

    if text == "🗑 Delete":
        admin_states[user_id] = "DELETE_MENU"
        await update.message.reply_text("🗑 **Delete Management:**", parse_mode="Markdown", reply_markup=get_delete_keyboard())
        return

    if state == "DELETE_MENU":
        if text == "♻️ Delete Used (OTP Received)":
            for country in get_all_country_keys():
                new_list = []
                for n in data.get(country, []):
                    if n.get("status") == "used":
                        if n.get("has_code", False):
                            continue
                        else:
                            n["status"] = "free"
                            n["user_id"] = None
                            n["assigned_at"] = 0
                            new_list.append(n)
                    else:
                        new_list.append(n)
                data[country] = new_list
            await save_db_async("data", data)
            await update.message.reply_text("✅ OTP-Received deleted, No-OTP returned to free stock.", reply_markup=get_admin_keyboard())
            admin_states.pop(user_id, None)
            
        elif text == "🗑 Delete All Numbers":
            for ck in get_all_country_keys():
                data[ck] = []
            await save_db_async("data", data)
            await update.message.reply_text("✅ All numbers cleared.", reply_markup=get_admin_keyboard())
            admin_states.pop(user_id, None)
        return

    if text == "📥 Export":
        admin_states[user_id] = "EXPORT_MENU"
        await update.message.reply_text("📥 **Export Numbers:**", parse_mode="Markdown", reply_markup=get_export_keyboard())
        return

    if state == "EXPORT_MENU":
        if text == "✅ OTP Received":
            admin_states[user_id] = "EXPORT_OTP"
            await update.message.reply_text("Export OTP-received numbers for which users?", reply_markup=get_target_keyboard())
        elif text == "⏳ No OTP":
            admin_states[user_id] = "EXPORT_NOCODE"
            await update.message.reply_text("Export No-OTP numbers for which users?", reply_markup=get_target_keyboard())
        elif text == "❌ Canceled":
            admin_states[user_id] = "EXPORT_CANCELED"
            await update.message.reply_text("Export canceled numbers for which users?", reply_markup=get_target_keyboard())
        return

    if state in ["EXPORT_OTP", "EXPORT_NOCODE", "EXPORT_CANCELED"]:
        if text == "🌐 All Users":
            export_lines = []
            if state == "EXPORT_OTP":
                for country in get_all_country_keys():
                    for item in data.get(country, []):
                        if item.get("status") == "used" and item.get("has_code", False):
                            export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                await send_export_file(update, export_lines, "otp_received.txt")
            elif state == "EXPORT_NOCODE":
                for country in get_all_country_keys():
                    for item in data.get(country, []):
                        if item.get("status") == "used" and not item.get("has_code", False):
                            export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                await send_export_file(update, export_lines, "no_otp.txt")
            elif state == "EXPORT_CANCELED":
                for item in data.get("canceled", []):
                    export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                await send_export_file(update, export_lines, "canceled_numbers.txt")
            admin_states.pop(user_id, None)
        elif text == "👤 Specific User":
            admin_states[user_id] = f"WAITING_{state}_ID"
            await update.message.reply_text("🆔 Please send the User ID:", reply_markup=get_cancel_admin_keyboard())
        return

    if state and state.startswith("WAITING_EXPORT_"):
        try:
            target_id = int(text)
            export_lines = []
            if "EXPORT_OTP" in state:
                for country in get_all_country_keys():
                    for item in data.get(country, []):
                        if item.get("status") == "used" and item.get("has_code", False) and item.get("user_id") == target_id:
                            export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                fname = f"user_{target_id}_otp_received.txt"
            elif "EXPORT_NOCODE" in state:
                for country in get_all_country_keys():
                    for item in data.get(country, []):
                        if item.get("status") == "used" and not item.get("has_code", False) and item.get("user_id") == target_id:
                            export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                fname = f"user_{target_id}_no_otp.txt"
            elif "EXPORT_CANCELED" in state:
                for item in data.get("canceled", []):
                    if item.get("user_id") == target_id:
                        export_lines.append(f"{item.get('number', '')}:{item.get('link', '')}")
                fname = f"user_{target_id}_canceled.txt"
            else:
                fname = f"user_{target_id}.txt"
            await send_export_file(update, export_lines, fname)
        except ValueError:
            await update.message.reply_text("❌ Invalid User ID.")
        admin_states.pop(user_id, None)
        return

    if text == "📢 Broadcast":
        admin_states[user_id] = "WAITING_BROADCAST"
        await update.message.reply_text("📢 Send the message to broadcast:", reply_markup=get_cancel_admin_keyboard())
        return

    if state == "WAITING_BROADCAST":
        sent_count = 0
        for uid in list(users_db.keys()):
            try:
                await context.bot.send_message(chat_id=int(uid), text=text)
                sent_count += 1
            except Exception:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to `{sent_count}` users.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        admin_states.pop(user_id, None)
        return

    if text == "⚙️ System Toggle":
        config_db["active"] = not config_db.get("active", True)
        await save_db_async("config", config_db)
        status = "ONLINE 🟢" if config_db["active"] else "OFFLINE 🔴"
        await update.message.reply_text(f"🤖 Bot Status: **{status}**", parse_mode="Markdown")
        return

# ==========================================
# Document Handler
# ==========================================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return

    state = admin_states.get(user_id)
    doc_name = update.message.document.file_name

    if doc_name and doc_name.endswith('.zip'):
        status_msg = await update.message.reply_text("⏳ Restoring SQLite database from backup...")
        file = await context.bot.get_file(update.message.document.file_id)
        zip_path = "temp_backup.zip"
        await file.download_to_drive(zip_path)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(".")
            os.remove(zip_path)
            global data, users_db, config_db, mail_tokens_db
            data = load_db("data", {"USA": [], "China": [], "Canada": [], "used_names": [], "canceled": []})
            for _ck in ["USA", "China", "Canada"]:
                if _ck not in data:
                    data[_ck] = []
            if "canceled" not in data:
                data["canceled"] = []
            users_db = load_db("users", {})
            config_db = load_db("config", {
                "active": True,
                "prices": {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01},
                "base_costs": {"USA": 0.100, "China": 0.120, "Canada": 0.100},
                "usdt_bep20_address": "0xYourDefaultUSDT_BEP20_Wallet_Address_Here",
                "total_deposits": 0.0,
                "country_settings": json.loads(json.dumps(DEFAULT_COUNTRY_SETTINGS)),
                "custom_countries": {}
            })
            config_db.setdefault("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
            config_db["prices"].setdefault("USA", 0.175)
            config_db["prices"].setdefault("China", 0.195)
            config_db["prices"].setdefault("Canada", 0.175)
            config_db["prices"].setdefault("MailTM", 0.01)
            config_db.setdefault("base_costs", {"USA": 0.100, "China": 0.120, "Canada": 0.100})
            config_db.setdefault("usdt_bep20_address", "0xYourDefaultUSDT_BEP20_Wallet_Address_Here")
            config_db.setdefault("total_deposits", 0.0)
            config_db.setdefault("custom_countries", {})
            config_db.setdefault("country_settings", json.loads(json.dumps(DEFAULT_COUNTRY_SETTINGS)))
            mail_tokens_db = load_db("mail_tokens", {})
            await save_all_dbs_async()
            prices = config_db["prices"]
            wallet = config_db["usdt_bep20_address"]
            stock_summary = " | ".join([f"{ck}: `{len([n for n in data.get(ck, []) if n.get('status') == 'free'])}`" for ck in get_all_country_keys()])
            await status_msg.edit_text(
                f"✅ **Full Database Restored!**\n\n"
                f"👥 Users: `{len(users_db)}`\n"
                f"📦 Stock: {stock_summary}\n"
                f"💵 Prices: USA `${prices.get('USA', 0.175):.3f}` | China `${prices.get('China', 0.195):.3f}` | Canada `${prices.get('Canada', 0.175):.3f}` | Mail.tm `${prices.get('MailTM', 0.01):.3f}`\n"
                f"🏦 Wallet: `{wallet}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Restore error: {e}")
        return

    if state and state.startswith("WAITING_FILE_"):
        if not doc_name or not doc_name.lower().endswith('.txt'):
            await update.message.reply_text("❌ Please upload a valid `.txt` file!")
            return

        status_msg = await update.message.reply_text("⏳ Processing...")
        country = state.replace("WAITING_FILE_", "", 1)
        data.setdefault(country, [])
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
        batch_id = f"{country}_{timestamp_str}"
        
        file = await context.bot.get_file(update.message.document.file_id)
        file_path = f"temp_{country}.txt"
        await file.download_to_drive(file_path)
        
        valid_count = 0
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        
        for line in lines:
            link, phone = process_data_line(line, country)
            if link and phone:
                unique_name = await get_unique_name(country)
                data[country].append({
                    "number": phone, "link": link, "identity": unique_name,
                    "status": "free", "user_id": None, "assigned_at": 0,
                    "has_code": False, "batch_id": batch_id
                })
                valid_count += 1
                
        await save_db_async("data", data)
        os.remove(file_path)
        await status_msg.edit_text(f"✅ File Processed! Added: `{valid_count}` numbers.", parse_mode="Markdown")
        await update.message.reply_text("⚙️ Back to Admin Panel:", reply_markup=get_admin_keyboard())
        admin_states.pop(user_id, None)

# ==========================================
# Inline Callback Handler
# ==========================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user_id = query.from_user.id
    u_rec = get_user_record(user_id)

    if user_id != ADMIN_ID and (not config_db.get("active", True) or u_rec.get("banned", False)):
        await query.answer("⛔ Access denied.", show_alert=True)
        return

    # ==========================================
    # Mail.tm Get Code Callback (Max 2 attempts)
    # ==========================================
    if action.startswith("mtm_code_"):
        req_key = action.replace("mtm_code_", "")
        item_data = mail_tokens_db.get(req_key)

        if not item_data:
            await query.answer("❌ Email session expired or not found.", show_alert=True)
            return

        if item_data.get("user_id") and item_data.get("user_id") != user_id:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return

        attempts = item_data.get("attempts", 0)
        if attempts >= 2:
            await query.answer("⚠️ Maximum code checks (2) reached for this email.", show_alert=True)
            return

        mail_token = item_data["token"]
        email_addr = item_data["email"]
        prev_codes = item_data.get("codes", [])

        code = await check_mail_tm_code(mail_token)

        if code:
            if attempts == 1 and prev_codes and code == prev_codes[-1]:
                await query.answer("⏳ No new code arrived yet. Please wait and try again.", show_alert=True)
                return

            attempts += 1
            prev_codes.append(code)
            mail_tokens_db[req_key]["attempts"] = attempts
            mail_tokens_db[req_key]["codes"] = prev_codes
            await save_db_async("mail_tokens", mail_tokens_db)

            if attempts == 1:
                new_text = (
                    f"📧 **Mail.tm Temporary Email**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✉️ **Email:** `{email_addr}`\n"
                    f"🔐 **Code:** `{code}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ *Code received! Need a second code on this email? Click below:*"
                )
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get Code Again", callback_data=f"mtm_code_{req_key}")]
                ])
            else:
                new_text = (
                    f"📧 **Mail.tm Temporary Email**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✉️ **Email:** `{email_addr}`\n"
                    f"🔐 **Code 1:** `{prev_codes[0]}`\n"
                    f"🔐 **Code 2:** `{code}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✔️ *Both codes received. This email session is now complete.*"
                )
                markup = None

            try:
                await query.edit_message_text(text=new_text, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                logging.error(f"Edit message error in mtm_code: {e}")
            await query.answer("✅ Code received!")
        else:
            await query.answer("⏳ No code received yet. Please wait a few seconds and try again.", show_alert=True)
        return

    if action == "deposit_bep20":
        admin_states[user_id] = "WAITING_DEPOSIT_AMOUNT"
        await query.answer()
        
        wallet_addr = config_db.get("usdt_bep20_address", "0xYourDefaultUSDT_BEP20_Wallet_Address_Here")
        invoice_msg = (
            f"💎 **BEP20 (USDT) Deposit**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 **Wallet Address (Tap to copy):**\n`{wallet_addr}`\n\n"
            f"⚠️ **Network: BNB Smart Chain (BEP20) only!**\n"
            f"🔢 **Now enter the Deposit Amount in USDT (e.g. 5 or 6.75):**"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_deposit_inline")]])
        
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text=invoice_msg, parse_mode="Markdown", reply_markup=markup)
        return

    if action == "cancel_deposit_inline":
        admin_states.pop(user_id, None)
        user_deposit_amounts.pop(user_id, None)
        await query.edit_message_text("❌ **Payment Invoice Canceled.**", parse_mode="Markdown")
        await query.answer("Invoice canceled.")
        await context.bot.send_message(chat_id=user_id, text="🏠 Main Menu:", reply_markup=get_main_keyboard(user_id))
        return

    if action.startswith("dep_approve_") and user_id == ADMIN_ID:
        parts = action.split("_")
        target_id = parts[2]
        amount = float(parts[3])
        
        target_rec = get_user_record(int(target_id))
        target_rec["balance"] = round(target_rec.get("balance", 0.0) + amount, 4)
        target_rec["deposit_history"].append({"amount": amount, "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
        
        config_db["total_deposits"] = round(config_db.get("total_deposits", 0.0) + amount, 4)
        
        if target_rec.get("referred_by"):
            ref_id = target_rec["referred_by"]
            if ref_id in users_db:
                ref_rec = users_db[ref_id]
                commission = round(amount * 0.03, 4)
                ref_rec["balance"] = round(ref_rec.get("balance", 0.0) + commission, 4)
                ref_rec["ref_earnings"] = round(ref_rec.get("ref_earnings", 0.0) + commission, 4)
                await save_db_async("users", users_db)
                try:
                    await context.bot.send_message(
                        chat_id=int(ref_id),
                        text=f"🎁 **Referral Commission!**\n\nYou earned `${commission:.4f} USDT` from a referral's deposit.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        
        await save_db_async("config", config_db)
        await save_db_async("users", users_db)
        
        await query.edit_message_text(f"{query.message.text}\n\n✅ **APPROVED BY ADMIN** (`+${amount:.3f} USD`)", parse_mode="Markdown")
        await query.answer("✅ Approved!")
        
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text=f"🎉 **DEPOSIT APPROVED!**\n\n💵 **Amount:** `${amount:.3f} USD`\n💰 **Balance:** `${target_rec['balance']:.3f} USD`",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(int(target_id))
            )
        except Exception:
            pass
        return

    if action.startswith("dep_reject_") and user_id == ADMIN_ID:
        parts = action.split("_")
        target_id = parts[2]
        await query.edit_message_text(f"{query.message.text}\n\n❌ **REJECTED BY ADMIN**", parse_mode="Markdown")
        await query.answer("❌ Rejected.")
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text=f"❌ **DEPOSIT REJECTED**\n\nYour deposit could not be verified. Contact Support.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(int(target_id))
            )
        except Exception:
            pass
        return

    if action == "my_referrals":
        refs = u_rec.get("referrals", 0)
        await query.answer(f"🎉 You have invited {refs} users so far!", show_alert=True)
        return
        
    if action == "my_orders":
        orders = []
        for country in get_all_country_keys():
            for item in data.get(country, []):
                if item.get("user_id") == user_id:
                    status_icon = "✅" if item.get("has_code") else "⏳"
                    orders.append(f"{status_icon} {item.get('number')} ({country})")
        
        if not orders:
            await query.answer("You have no orders yet.", show_alert=True)
        else:
            orders_text = "\n".join(orders[-10:])
            await query.answer(f"Your recent orders:\n\n{orders_text}", show_alert=True)
        return

    if action.startswith("buy_country_") or action.startswith("buy_another_"):
        is_buy_another = action.startswith("buy_another_")
        country = action.replace("buy_another_", "") if is_buy_another else action.replace("buy_country_", "")
        prices = config_db.get("prices", {"USA": 0.175, "China": 0.195, "Canada": 0.175, "MailTM": 0.01})
        price = prices.get(country, 0.175)
        
        if u_rec.get("balance", 0.0) < price:
            await query.answer(f"❌ Insufficient balance!\nPrice: ${price:.3f} USD\nYour Balance: ${u_rec.get('balance', 0.0):.3f} USD", show_alert=True)
            return

        free_indices = [i for i, n in enumerate(data.get(country, [])) if n.get("status") == "free"]
        if not free_indices:
            await query.answer(f"❌ Out of stock for {country}!", show_alert=True)
            return

        idx = free_indices[0]
        item = data[country][idx]
        
        u_rec["balance"] = round(u_rec["balance"] - price, 4)
        await save_db_async("users", users_db)
        
        item["status"] = "used"
        item["user_id"] = user_id
        item["assigned_at"] = time.time()
        item["has_code"] = False
        item["paid_price"] = price
        d_st = get_daily_stats()
        d_st[country]["assigned"] = d_st[country].get("assigned", 0) + 1
        await save_db_async("config", config_db)
        await save_db_async("data", data)

        flag = get_country_config(country).get("label", country)
        
        num_msg = (
            f"📱 **NUMBER ASSIGNED**\n\n"
            f"🌍 **Country :** {flag} **{country}**\n"
            f"📞 **Number :** `{item['number']}`\n"
            f"💵 **Price :** `${price:.3f} USD`\n\n"
            f"⏳ *You have 15 minutes to receive the OTP.*\n\n"
            f"💡 *Request OTP in Telegram, then click* **Get Code**."
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Get Code", callback_data=f"check_otp_{country}_{idx}")],
            [InlineKeyboardButton("❌ Cancel Number", callback_data=f"cancel_num_{country}_{idx}")]
        ])
        
        if is_buy_another:
            await context.bot.send_message(chat_id=user_id, text=num_msg, parse_mode="Markdown", reply_markup=markup)
        else:
            await query.edit_message_text(num_msg, parse_mode="Markdown", reply_markup=markup)
        await query.answer("✅ Number assigned!")
        return

    if action.startswith("cancel_num_"):
        parts = action.split("_")
        country = parts[2]
        idx = int(parts[3])
        
        if idx >= len(data.get(country, [])):
            await query.answer("❌ Not found.", show_alert=True)
            return
            
        item = data[country][idx]
        if item.get("user_id") != user_id:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
            
        if item.get("has_code", False):
            await query.answer("❌ Cannot cancel, OTP already received.", show_alert=True)
            return

        refund_amount = item.get("paid_price", config_db.get("prices", {}).get(country, 0.175))
        u_rec["balance"] = round(u_rec.get("balance", 0.0) + refund_amount, 4)
        u_rec["canceled_count"] = u_rec.get("canceled_count", 0) + 1
        await save_db_async("users", users_db)
        
        data.setdefault("canceled", []).append({
            "country": country,
            "number": item.get("number", ""),
            "link": item.get("link", ""),
            "user_id": user_id,
            "reason": "user_canceled",
            "ts": time.time()
        })
        item["status"] = "free"
        item["user_id"] = None
        item["assigned_at"] = 0
        d_st = get_daily_stats()
        d_st[country]["nocode"] = d_st[country].get("nocode", 0) + 1
        await save_db_async("config", config_db)
        await save_db_async("data", data)
        
        await query.edit_message_text(f"❌ **CANCELED**\n\n💰 `${refund_amount:.3f} USD` refunded.\n💵 Balance: `${u_rec['balance']:.3f} USD`", parse_mode="Markdown")
        await query.answer("✅ Canceled!")
        return

    if action.startswith("check_otp_"):
        parts = action.split("_")
        country = parts[2]
        idx = int(parts[3])
        
        if idx >= len(data.get(country, [])):
            await query.answer("❌ Not found.", show_alert=True)
            return
            
        item = data[country][idx]
        link = item.get("link")
        if not link:
            await query.answer("❌ No API link.", show_alert=True)
            return
            
        target_url = link
        if "/sms/" in link and "/api/sms/" not in link:
            target_url = link.replace("/sms/", "/api/sms/")
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(target_url, timeout=10.0)
                if response.status_code != 200 and target_url != link:
                    response = await client.get(link, timeout=10.0)
                    
            text_response = str(response.text)
            otp_digits = int(get_country_config(country).get("otp_digits", 6 if country == "China" else 5))
            sms_codes = re.findall(rf'\b\d{{{otp_digits}}}\b', text_response)
            sms_code = sms_codes[-1] if sms_codes else None
            
            if sms_code:
                if not item.get("has_code", False):
                    item["has_code"] = True
                    item["code_received_at"] = time.time()
                    paid = item.get("paid_price", config_db.get("prices", {}).get(country, 0.175))
                    u_rec["total_purchased"] = u_rec.get("total_purchased", 0) + 1
                    u_rec["total_spent"] = round(u_rec.get("total_spent", 0.0) + paid, 4)
                    await save_db_async("data", data)
                    await save_db_async("users", users_db)
                
                flag = get_country_config(country).get("label", country)
                identity_name = item.get("identity") or await get_unique_name(country)
                
                otp_msg = (
                    f"⚡ **INSTANT OTP NOTIFICATION**\n\n"
                    f"📩 **YOUR OTP RECEIVED**\n\n"
                    f"🌐 **Country :** {flag} **{country}**\n"
                    f"📱 **Number :** `{item['number']}`\n"
                    f"🔐 **Your TG OTP :** `{sms_code}`\n"
                    f"👤 **Account Name :** `{identity_name}`"
                )
                
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📋 Copy OTP: {sms_code}", copy_text=CopyTextButton(text=str(sms_code)))],
                    [InlineKeyboardButton("🛒 Buy Another", callback_data=f"buy_another_{country}")]
                ])
                
                await query.edit_message_text(text=otp_msg, parse_mode="Markdown", reply_markup=markup)
                await query.answer("✅ OTP Received!")
            else:
                otp_digits = int(get_country_config(country).get("otp_digits", 6 if country == "China" else 5))
                await query.answer(f"⏳ No {otp_digits}-digit OTP yet. Please wait and try again.", show_alert=True)
        except Exception as e:
            await query.answer(f"❌ API Error.", show_alert=True)
        return

# ==========================================
# Background Startup
# ==========================================
async def post_init(application: Application):
    asyncio.create_task(auto_refund_worker(application))
    asyncio.create_task(nightly_report_worker(application))
    asyncio.create_task(prefetch_mail_tm_pool())

    async def periodic_backup():
        while True:
            await asyncio.sleep(3600)
            try:
                backup_filename = await asyncio.to_thread(create_backup_zip)
                if os.path.exists(backup_filename):
                    with open(backup_filename, "rb") as f:
                        await application.bot.send_document(
                            chat_id=ADMIN_ID,
                            document=f,
                            filename=backup_filename,
                            caption="⏰ **Automatic 1-Hour Database Backup**",
                            parse_mode="Markdown"
                        )
            except Exception as e:
                logging.error(f"Backup error: {e}")
                
    asyncio.create_task(periodic_backup())

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    app.add_error_handler(error_handler)

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
