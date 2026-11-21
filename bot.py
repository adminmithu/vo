import sys
import os
import time
import threading
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import config
import database
from vook_api import VookMailClient, VOOK_GROUPS

# Initialize database
database.init_db()

# Initialize VookMail Client
vook_client = VookMailClient()

# Initialize TeleBot
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

# Exact popular services from VookMail website
VOOK_SERVICES = [
    {"name": "ChatGPT", "icon": "🤖"},
    {"name": "Telegram", "icon": "💬"},
    {"name": "Discord", "icon": "🎮"},
    {"name": "Facebook", "icon": "🔵"},
    {"name": "Instagram", "icon": "📸"},
    {"name": "TikTok", "icon": "🎵"},
    {"name": "Twitter / X", "icon": "🐦"},
    {"name": "Reddit", "icon": "👽"},
    {"name": "Netflix", "icon": "🍿"},
    {"name": "Spotify", "icon": "🎧"},
    {"name": "Steam", "icon": "🕹️"},
    {"name": "Amazon", "icon": "🛒"},
    {"name": "10 Minute Mail", "icon": "⏱️"},
    {"name": "Burner Email", "icon": "🔥"},
    {"name": "Throwaway Email", "icon": "🗑️"},
]

# Track user states for interactive flows
USER_STATES = {}

def get_all_admin_ids():
    admins = list(config.ADMIN_IDS)
    admin_str = database.get_setting("extra_admins", "")
    if admin_str:
        extra_admins = [int(x.strip()) for x in admin_str.split(",") if x.strip().isdigit()]
        for a in extra_admins:
            if a not in admins:
                admins.append(a)
    return admins

def is_admin(user_id: int) -> bool:
    return user_id in get_all_admin_ids()

def is_maintenance_active() -> bool:
    return database.get_setting("maintenance_mode", "0") == "1"

# ----------------- Render Web Service Health Check -----------------

class RenderHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"VookMail Telegram Bot is Running 24/7 Live on Render!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logs to keep terminal logs clean

def run_render_web_server():
    """Runs a lightweight HTTP server to satisfy Render Free Web Service port binding."""
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), RenderHealthHandler)
        print(f"🌐 [Render Health Server] Listening on port {port} (Status: Live)")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ [Render Server Error] {e}")

# ----------------- Keyboard & UI Helpers -----------------

def get_copy_button(text_to_copy: str) -> types.InlineKeyboardButton:
    """Returns native Telegram copy button for email address."""
    try:
        if hasattr(types, "CopyTextButton"):
            return types.InlineKeyboardButton("📋 Copy Mail", copy_text=types.CopyTextButton(text=text_to_copy))
    except Exception:
        pass
    return types.InlineKeyboardButton("📋 Copy Mail", callback_data=f"copy_{text_to_copy}")

def get_code_copy_button(code: str) -> types.InlineKeyboardButton:
    """Returns an inline button displaying JUST the code with NO emoji."""
    clean_code = str(code).strip()
    try:
        if hasattr(types, "CopyTextButton"):
            return types.InlineKeyboardButton(clean_code, copy_text=types.CopyTextButton(text=clean_code))
    except Exception:
        pass
    return types.InlineKeyboardButton(clean_code, callback_data=f"copycode_{clean_code}")

def get_main_keyboard(user_id: int):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_create = types.KeyboardButton("📧 Create Mail")
    btn_login = types.KeyboardButton("🔑 Login Mail")
    btn_domain = types.KeyboardButton("🌐 Domain")
    btn_service = types.KeyboardButton("⚡ Service Select")
    btn_history = types.KeyboardButton("📜 History")
    btn_support = types.KeyboardButton("💬 Support")
    
    markup.add(btn_create, btn_login)
    markup.add(btn_domain, btn_service)
    markup.add(btn_history, btn_support)
    
    if is_admin(user_id):
        btn_admin = types.KeyboardButton("👑 Admin Panel")
        markup.add(btn_admin)
        
    return markup

def build_all_domains_markup(current_domain: str):
    domain_data = vook_client.get_domains_data()
    groups = domain_data.get("groups", VOOK_GROUPS)

    markup = types.InlineKeyboardMarkup(row_width=2)

    is_auto = not current_domain or current_domain.lower() in ("auto", "default", "")
    auto_text = "⚡ Auto / Random (Website Default) ✅" if is_auto else "⚡ Auto / Random (Website Default)"
    markup.add(types.InlineKeyboardButton(auto_text, callback_data="setdom_auto"))

    for g in groups:
        cat_header = f"── {g.get('icon', '📁')} {g.get('name', 'Domains')} ──"
        markup.add(types.InlineKeyboardButton(cat_header, callback_data="noop"))
        
        row = []
        for d in g.get("domains", []):
            clean_d = d.lstrip('@')
            is_selected = (clean_d == current_domain)
            label = f"@{clean_d} ✅" if is_selected else f"@{clean_d}"
            row.append(types.InlineKeyboardButton(label, callback_data=f"setdom_{clean_d}"))
            if len(row) == 2:
                markup.add(row[0], row[1])
                row = []
        if row:
            markup.add(row[0])

    return markup

def build_services_markup(current_service: str):
    markup = types.InlineKeyboardMarkup(row_width=2)

    is_auto = not current_service or current_service.lower() in ("auto", "general", "general / auto", "")
    auto_text = "⚡ Auto / General (Default) ✅" if is_auto else "⚡ Auto / General (Default)"
    markup.add(types.InlineKeyboardButton(auto_text, callback_data="setserv_auto"))

    row = []
    for item in VOOK_SERVICES:
        name = item["name"]
        icon = item["icon"]
        is_selected = (name.lower() == (current_service or "").lower())
        label = f"{icon} {name} ✅" if is_selected else f"{icon} {name}"
        row.append(types.InlineKeyboardButton(label, callback_data=f"setserv_{name}"))
        if len(row) == 2:
            markup.add(row[0], row[1])
            row = []
    if row:
        markup.add(row[0])

    return markup

def build_message_markup(address: str, msg_id: str, code: str = "", link: str = "") -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    if code:
        markup.add(get_code_copy_button(code))

    if link:
        markup.add(
            types.InlineKeyboardButton("🔗 Open Link", url=link),
            types.InlineKeyboardButton("📖 View Full Message", callback_data=f"view_{address}_{msg_id}")
        )
    else:
        markup.add(types.InlineKeyboardButton("📖 View Full Message", callback_data=f"view_{address}_{msg_id}"))

    return markup

def build_admin_panel_markup() -> types.InlineKeyboardMarkup:
    m_active = is_maintenance_active()
    m_status_btn = "⚙️ Mnt: ON 🔴" if m_active else "⚙️ Mnt: OFF 🟢"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("📋 User Live Activities", callback_data="adm_activities"))
    markup.add(
        types.InlineKeyboardButton("🔍 Search User", callback_data="adm_search_user"),
        types.InlineKeyboardButton(m_status_btn, callback_data="adm_toggle_maintenance")
    )
    markup.add(
        types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
        types.InlineKeyboardButton("🔑 Set API Key", callback_data="adm_setkey")
    )
    markup.add(
        types.InlineKeyboardButton("💬 Set Support ID", callback_data="adm_setsupport"),
        types.InlineKeyboardButton("🚫 Ban/Unban User", callback_data="adm_ban")
    )
    markup.add(
        types.InlineKeyboardButton("🔄 Refresh Stats", callback_data="adm_refresh"),
        types.InlineKeyboardButton("⚡ Restart Bot", callback_data="adm_restart_bot")
    )
    return markup

# ----------------- Start / Help Handlers -----------------

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\n\nকিছুক্ষণের মধ্যেই বট পুনরায় চালু করা হবে। অনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        bot.reply_to(message, "⛔ You are suspended from using this bot.")
        return

    database.register_user(user_id=user_id, username=username, first_name=first_name)
    database.log_activity(user_id, username, first_name, "START_BOT", "Started the bot")

    user = database.get_user(user_id) or {}
    saved_domain = user.get("selected_domain") or "Auto / Random"
    saved_service = user.get("selected_service") or "General / Auto"

    welcome_text = (
        f"👋 <b>Welcome, {first_name}!</b>\n\n"
        f"🔥 <b>VookMail Temporary Email Bot</b>-এ আপনাকে স্বাগতম!\n\n"
        f"📌 <b>বর্তমান ডোমেইন:</b> <code>@{saved_domain}</code>\n"
        f"🎯 <b>বর্তমান সার্ভিস:</b> <code>{saved_service}</code>\n\n"
        f"নিচের মেনু বোতামগুলো ব্যবহার করে কাজ করুন:\n"
        f"• <b>📧 Create Mail:</b> তাৎক্ষণিক নতুন ইমেইল তৈরি করুন।\n"
        f"• <b>🔑 Login Mail:</b> আগের ব্যবহৃত মেইল অ্যাড্রেস দিয়ে ইনবক্স ওপেন করুন।\n"
        f"• <b>🌐 Domain:</b> ৩৬টি ডোমেইন থেকে পছন্দের ডোমেইন বেছে নিন।\n"
        f"• <b>⚡ Service Select:</b> ফেসবুক, টেলিগ্রাম, ChatGPT ইত্যাদি সার্ভিস বেছে নিন।\n"
        f"• <b>📜 History:</b> আপনার আগের সব ইমেইল দেখুন ও ইনবক্স চেক করুন।\n"
        f"• <b>💬 Support:</b> সরাসরি এডমিনকে মেসেজ পাঠাতে ক্লিক করুন।"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))

# ----------------- 📧 Create Mail Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "📧 Create Mail")
def handle_create_mail(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\nঅনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        return

    user = database.get_user(user_id) or {}
    selected_domain = user.get("selected_domain", "")
    target_domain = selected_domain if (selected_domain and selected_domain.lower() != "auto") else None
    service = user.get("selected_service") or "General / Auto"

    wait_msg = bot.send_message(message.chat.id, "⏳ <i>Generating your email address...</i>")

    res = vook_client.create_mailbox(domain=target_domain)
    if not res.get("success"):
        err = res.get("error", "Unknown error")
        bot.edit_message_text(
            f"❌ <b>Error creating mail:</b> {err}",
            chat_id=message.chat.id,
            message_id=wait_msg.message_id
        )
        return

    data = res["data"]
    address = data.get("address", "")
    token = data.get("token", "")
    cookie = data.get("cookie", "")
    expires_at = data.get("expires_at", "24 Hours")

    database.add_mail_history(
        user_id=user_id,
        email=address,
        token=token,
        cookie=cookie,
        service=service,
        expires_at=str(expires_at)
    )

    database.log_activity(user_id, username, first_name, "CREATE_MAIL", f"{address} ({service})")

    mail_domain_display = address.split("@")[1] if "@" in address else (selected_domain or "Auto")

    mail_text = (
        f"✨ <b>New Temporary Mail Created!</b>\n\n"
        f"📬 <b>Email:</b> <code>{address}</code>\n"
        f"🌐 <b>Domain:</b> <code>@{mail_domain_display}</code>\n"
        f"🎯 <b>Service:</b> <code>{service}</code>\n"
        f"⏳ <b>Validity:</b> <code>{expires_at}</code>"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_copy = get_copy_button(address)
    btn_check = types.InlineKeyboardButton("🔄 Check Inbox", callback_data=f"chk_{address}")
    btn_del = types.InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{address}")
    
    markup.add(btn_copy)
    markup.add(btn_check, btn_del)

    bot.edit_message_text(mail_text, chat_id=message.chat.id, message_id=wait_msg.message_id, reply_markup=markup)

# ----------------- 🔑 Login Mail Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "🔑 Login Mail")
def handle_login_mail(message):
    user_id = message.from_user.id
    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\nঅনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        return

    USER_STATES[user_id] = "awaiting_login_email"

    text = (
        f"🔑 <b>Login to Existing Mailbox</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"আপনার পূর্বে ব্যবহৃত সম্পূর্ণ ইমেইল অ্যাড্রেসটি লিখে সেন্ড করুন:\n"
        f"(উদাহরণ: <code>user482@lockomail.com</code>)"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_login"))

    bot.send_message(message.chat.id, text, reply_markup=markup)

# ----------------- 🌐 Domain Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "🌐 Domain")
def handle_domain(message):
    user_id = message.from_user.id
    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\nঅনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        return

    user = database.get_user(user_id) or {}
    current = user.get("selected_domain") or ""
    current_display = current if current and current.lower() != "auto" else "Auto / Random (Website Default)"

    text = (
        f"🌐 <b>VookMail Domain Selection</b>\n\n"
        f"📌 <b>বর্তমান সেভ থাকা ডোমেইন:</b> <code>@{current_display}</code>\n\n"
        f"নিচের তালিকা থেকে আপনার পছন্দের ডোমেইনটি বেছে নিন:"
    )
    markup = build_all_domains_markup(current)
    bot.send_message(message.chat.id, text, reply_markup=markup)

# ----------------- ⚡ Service Select Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "⚡ Service Select")
def handle_service_select(message):
    user_id = message.from_user.id
    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\nঅনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        return

    user = database.get_user(user_id) or {}
    current = user.get("selected_service") or "General / Auto"

    text = (
        f"⚡ <b>VookMail Service Selection</b>\n\n"
        f"🎯 <b>বর্তমান সেভ থাকা সার্ভিস:</b> <code>{current}</code>\n\n"
        f"যে সার্ভিসের জন্য ইমেইল ব্যবহার করবেন সেটি বেছে নিন:"
    )
    markup = build_services_markup(current)
    bot.send_message(message.chat.id, text, reply_markup=markup)

# ----------------- 📜 History Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "📜 History")
def handle_history(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    if is_maintenance_active() and not is_admin(user_id):
        bot.reply_to(message, "⚠️ <b>বটের কাজ চলছে (Maintenance Mode)</b>\nঅনুগ্রহ করে একটু পর চেষ্টা করুন।")
        return

    if database.is_banned(user_id):
        return

    database.log_activity(user_id, username, first_name, "VIEW_HISTORY", "Viewed mail history")

    history = database.get_user_history(user_id, limit=8)
    if not history:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Close", callback_data="hist_close"))
        bot.send_message(message.chat.id, "ℹ️ আপনার কোনো পূর্ববর্তী ইমেইল হিস্ট্রি পাওয়া যায়নি। '📧 Create Mail' চাপুন।", reply_markup=markup)
        return

    text = "📜 <b>আপনার স্থায়ী ইমেইল হিস্ট্রি:</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n"

    markup = types.InlineKeyboardMarkup(row_width=1)

    for idx, item in enumerate(history, 1):
        email = item["email"]
        service = item.get("service") or "General"
        date = item.get("created_at", "")[:16]
        text += f"<b>{idx}.</b> <code>{email}</code>\n   ↳ 🎯 <i>{service}</i> | 📅 {date}\n\n"
        markup.add(types.InlineKeyboardButton(f"📥 Check Inbox: {email[:18]}...", callback_data=f"chk_{email}"))

    btn_clear = types.InlineKeyboardButton("🗑️ Clear History", callback_data="hist_clear")
    btn_close = types.InlineKeyboardButton("❌ Cancel / Close", callback_data="hist_close")
    markup.row(btn_clear, btn_close)

    bot.send_message(message.chat.id, text, reply_markup=markup)

# ----------------- 💬 Support Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "💬 Support")
def handle_support(message):
    user_id = message.from_user.id
    if database.is_banned(user_id):
        return

    USER_STATES[user_id] = "awaiting_support_text"

    text = (
        f"💬 <b>Support & Help Desk</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"আপনার কোনো সমস্যা, মতামত বা সাহায্যের প্রয়োজন হলে নিচে মেসেজটি লিখে সেন্ড করুন।"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_support"))

    bot.send_message(message.chat.id, text, reply_markup=markup)

# ----------------- 👑 Admin Panel Handler -----------------

@bot.message_handler(func=lambda msg: msg.text == "👑 Admin Panel")
def handle_admin_panel(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ You are not authorized to view this panel.")
        return

    stats = database.get_stats()
    m_active = is_maintenance_active()

    text = (
        f"👑 <b>Admin Control Panel</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Users:</b> <code>{stats['total_users']}</code>\n"
        f"📧 <b>Total Emails Created:</b> <code>{stats['total_mails']}</code>\n"
        f"📋 <b>Total Logged Actions:</b> <code>{stats.get('total_logs', 0)}</code>\n"
        f"🚫 <b>Banned Users:</b> <code>{stats['banned_users']}</code>\n"
        f"⚙️ <b>Maintenance Mode:</b> <code>{'ENABLED 🔴' if m_active else 'DISABLED 🟢'}</code>\n"
        f"🔑 <b>API Key Status:</b> <code>{'Configured ✅' if vook_client.get_api_key() else 'Direct Live Engine ⚡'}</code>"
    )

    bot.send_message(message.chat.id, text, reply_markup=build_admin_panel_markup())

# ----------------- Inline Callbacks -----------------

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    username = call.from_user.username or ""
    first_name = call.from_user.first_name or ""
    data = call.data

    if is_maintenance_active() and not is_admin(user_id):
        bot.answer_callback_query(call.id, "⚠️ বটের কাজ চলছে (Maintenance Mode)", show_alert=True)
        return

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    if data.startswith("copy_"):
        address = data.split("copy_")[1]
        bot.answer_callback_query(call.id, f"📋 {address}\n(Copied!)", show_alert=True)
        return

    if data.startswith("copycode_"):
        code = data.split("copycode_")[1]
        bot.answer_callback_query(call.id, f"{code}", show_alert=True)
        return

    if data == "cancel_login":
        USER_STATES.pop(user_id, None)
        bot.answer_callback_query(call.id, "Cancelled.")
        try:
            bot.edit_message_text("❌ লগইন বাতিল করা হয়েছে।", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    if data == "cancel_support":
        USER_STATES.pop(user_id, None)
        bot.answer_callback_query(call.id, "Cancelled.")
        try:
            bot.edit_message_text("❌ বাতিল করা হয়েছে।", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    if data == "hist_clear":
        database.clear_user_history(user_id)
        database.log_activity(user_id, username, first_name, "CLEAR_HISTORY", "Cleared email history")
        bot.answer_callback_query(call.id, "History cleared!")
        try:
            bot.edit_message_text(
                "🗑️ <b>আপনার সকল ইমেইল হিস্ট্রি সফলভাবে মুছে ফেলা হয়েছে!</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        return

    if data == "hist_close":
        bot.answer_callback_query(call.id, "Closed")
        try:
            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception:
            try:
                bot.edit_message_text("❌ হিস্ট্রি বন্ধ করা হয়েছে।", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            except Exception:
                pass
        return

    # Check Inbox
    if data.startswith("chk_"):
        address = data.split("chk_")[1]
        database.log_activity(user_id, username, first_name, "CHECK_INBOX", address)

        mail_row = database.get_mail_by_address(address) or {}
        token = mail_row.get("token")
        cookie = mail_row.get("cookie")

        res = vook_client.get_messages(address, token=token, cookie=cookie)
        if not res.get("success"):
            bot.answer_callback_query(call.id, f"Error: {res.get('error')}", show_alert=True)
            return

        messages = res.get("messages", [])
        if not messages:
            bot.answer_callback_query(call.id, "📭 Inbox is empty.", show_alert=True)
            return

        bot.answer_callback_query(call.id, f"📬 {len(messages)} message(s) found!")
        for msg in messages:
            sender = msg.get("from", "Unknown")
            subject = msg.get("subject", "No Subject")
            code = msg.get("verification_code", "") or msg.get("code", "")
            link = msg.get("verification_link", "") or msg.get("link", "")
            msg_id = msg.get("id", "")

            msg_text = (
                f"📨 <b>New Message Received!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📬 <b>To:</b> <code>{address}</code>\n"
                f"👤 <b>From:</b> <code>{sender}</code>\n"
                f"📝 <b>Subject:</b> <b>{subject}</b>\n"
            )

            if code:
                msg_text += f"\n🔑 <b>Verification Code:</b> <code>{code}</code>\n"
            if link:
                msg_text += f"\n🔗 <b>Verification Link:</b> <a href=\"{link}\">Click Here</a>\n"

            msg_markup = build_message_markup(address=address, msg_id=msg_id, code=code, link=link)
            bot.send_message(call.message.chat.id, msg_text, reply_markup=msg_markup)

    # View Single Message Detail
    elif data.startswith("view_"):
        parts = data.split("_")
        if len(parts) >= 3:
            address = parts[1]
            msg_id = parts[2]
            mail_row = database.get_mail_by_address(address) or {}
            res = vook_client.get_message_detail(address, msg_id, token=mail_row.get("token"), cookie=mail_row.get("cookie"))
            if res.get("success"):
                item = res["data"]
                body = item.get("text") or item.get("snippet") or "No text content"
                if len(body) > 3000:
                    body = body[:3000] + "\n...(truncated)"
                bot.send_message(call.message.chat.id, f"📄 <b>Message Body:</b>\n\n<pre>{body}</pre>")
            else:
                bot.answer_callback_query(call.id, "Could not fetch message detail", show_alert=True)

    # Delete Mailbox
    elif data.startswith("del_"):
        address = data.split("del_")[1]
        mail_row = database.get_mail_by_address(address) or {}
        vook_client.delete_mailbox(address, token=mail_row.get("token"), cookie=mail_row.get("cookie"))
        database.log_activity(user_id, username, first_name, "DELETE_MAIL", address)
        bot.answer_callback_query(call.id, "🗑️ Mailbox deleted successfully!")
        try:
            bot.edit_message_text(f"🗑️ Mailbox <code>{address}</code> has been deleted.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception:
            pass

    # Domain Select
    elif data.startswith("setdom_"):
        chosen = data.split("setdom_")[1]
        if chosen in ("auto", "default"):
            database.set_user_domain(user_id, "")
            database.log_activity(user_id, username, first_name, "SELECT_DOMAIN", "Auto / Random")
            bot.answer_callback_query(call.id, "✅ Set to: Auto / Random")
            success_text = "✅ <b>Domain Selected Successfully!</b>\n\n📌 <b>Saved Domain:</b> <code>⚡ Auto / Website Default</code>"
        else:
            database.set_user_domain(user_id, chosen)
            database.log_activity(user_id, username, first_name, "SELECT_DOMAIN", f"@{chosen}")
            bot.answer_callback_query(call.id, f"✅ @{chosen} selected!")
            success_text = f"✅ <b>Domain Selected Successfully!</b>\n\n📌 <b>Saved Domain:</b> <code>@{chosen}</code>"

        try:
            bot.edit_message_text(success_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass

    # Service Select
    elif data.startswith("setserv_"):
        chosen = data.split("setserv_")[1]
        if chosen in ("auto", "general"):
            database.set_user_service(user_id, "General / Auto")
            database.log_activity(user_id, username, first_name, "SELECT_SERVICE", "General / Auto")
            bot.answer_callback_query(call.id, "✅ Set to: Auto / General")
            serv_text = "✅ <b>Service Selected Successfully!</b>\n\n🎯 <b>Saved Service:</b> <code>⚡ Auto / General (Default)</code>"
        else:
            database.set_user_service(user_id, chosen)
            database.log_activity(user_id, username, first_name, "SELECT_SERVICE", chosen)
            bot.answer_callback_query(call.id, f"✅ Service set to {chosen}")
            serv_text = f"✅ <b>Service Selected Successfully!</b>\n\n🎯 <b>Saved Service:</b> <code>{chosen}</code>"
            
        try:
            bot.edit_message_text(serv_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass

    # Admin: Toggle Maintenance Mode
    elif data == "adm_toggle_maintenance":
        if not is_admin(user_id):
            return
        current_m = is_maintenance_active()
        new_m = "0" if current_m else "1"
        database.set_setting("maintenance_mode", new_m)
        status_word = "ACTIVATED 🔴" if new_m == "1" else "DEACTIVATED 🟢"
        bot.answer_callback_query(call.id, f"Maintenance Mode {status_word}")

        stats = database.get_stats()
        text = (
            f"👑 <b>Admin Control Panel</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Users:</b> <code>{stats['total_users']}</code>\n"
            f"📧 <b>Total Emails Created:</b> <code>{stats['total_mails']}</code>\n"
            f"📋 <b>Total Logged Actions:</b> <code>{stats.get('total_logs', 0)}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{stats['banned_users']}</code>\n"
            f"⚙️ <b>Maintenance Mode:</b> <code>{'ENABLED 🔴' if new_m == '1' else 'DISABLED 🟢'}</code>\n"
            f"🔑 <b>API Key Status:</b> <code>{'Configured ✅' if vook_client.get_api_key() else 'Direct Live Engine ⚡'}</code>"
        )
        try:
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=build_admin_panel_markup())
        except Exception:
            pass

    # Admin: Search User
    elif data == "adm_search_user":
        if not is_admin(user_id):
            return
        USER_STATES[user_id] = "awaiting_search_user_id"
        bot.send_message(call.message.chat.id, "🔍 ইউজারের <b>Telegram User ID</b> লিখুন:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

    # Admin: View User Live Activities
    elif data in ("adm_activities", "adm_act_refresh"):
        if not is_admin(user_id):
            return
        
        logs = database.get_recent_activity_logs(limit=15)
        text = "📋 <b>User Live Activities (সর্বশেষ ১৫টি অ্যাকশন):</b>\n"
        text += "━━━━━━━━━━━━━━━━━━\n"

        if not logs:
            text += "<i>এখনো কোনো রেকর্ড পাওয়া যায়নি।</i>"
        else:
            for idx, log in enumerate(logs, 1):
                u_name = log.get("first_name") or log.get("username") or str(log.get("user_id"))
                uid = log.get("user_id")
                action = log.get("action", "")
                details = log.get("details", "")
                timestamp = str(log.get("created_at", ""))[-8:]

                action_badge = action
                if action == "CREATE_MAIL": action_badge = "📧 Create Mail"
                elif action == "LOGIN_MAIL": action_badge = "🔑 Login Mail"
                elif action == "SELECT_DOMAIN": action_badge = "🌐 Domain"
                elif action == "SELECT_SERVICE": action_badge = "⚡ Service"
                elif action == "CHECK_INBOX": action_badge = "📥 Check Inbox"
                elif action == "SUPPORT_MSG": action_badge = "💬 Support Msg"
                elif action == "START_BOT": action_badge = "🚀 Started"
                elif action == "CLEAR_HISTORY": action_badge = "🗑️ Clear History"

                text += f"<b>{idx}.</b> 👤 <b>{u_name}</b> (<code>{uid}</code>)\n   ↳ <i>{action_badge}: {details}</i> | 🕒 {timestamp}\n\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔄 Refresh Logs", callback_data="adm_act_refresh"),
            types.InlineKeyboardButton("🔙 Back to Admin", callback_data="adm_refresh")
        )

        try:
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Logs Updated!")

    # Admin: 1-Click Bot Restart
    elif data == "adm_restart_bot":
        if not is_admin(user_id):
            return
        
        bot.answer_callback_query(call.id, "Restarting bot...")
        database.set_setting("restart_chat_id", str(call.message.chat.id))
        
        try:
            bot.edit_message_text(
                "🔄 <b>বট রিস্টার্ট হচ্ছে...</b>\n<i>কয়েক সেকেন্ডের মধ্যে বট পুনরায় চালু হয়ে নোটিফিকেশন দেবে।</i>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

        def execute_restart():
            time.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        threading.Thread(target=execute_restart).start()

    # Admin: Toggle Ban from user profile
    elif data.startswith("admtoggleban_"):
        if not is_admin(user_id):
            return
        target_uid = int(data.split("admtoggleban_")[1])
        new_ban = 0 if database.is_banned(target_uid) else 1
        database.set_ban_status(target_uid, new_ban)
        bot.answer_callback_query(call.id, f"User {target_uid} is now {'Banned' if new_ban else 'Unbanned'}!")

    # Admin: Reply directly to a support user
    elif data.startswith("admreply_"):
        if not is_admin(user_id):
            return
        target_uid = int(data.split("admreply_")[1])
        USER_STATES[user_id] = f"replying_user_{target_uid}"
        bot.send_message(call.message.chat.id, f"✍️ User <code>{target_uid}</code>-কে রিপ্লাই পাঠান:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

    # Admin: Refresh Stats
    elif data == "adm_refresh":
        if not is_admin(user_id):
            return
        stats = database.get_stats()
        m_active = is_maintenance_active()
        text = (
            f"👑 <b>Admin Control Panel</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Users:</b> <code>{stats['total_users']}</code>\n"
            f"📧 <b>Total Emails Created:</b> <code>{stats['total_mails']}</code>\n"
            f"📋 <b>Total Logged Actions:</b> <code>{stats.get('total_logs', 0)}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{stats['banned_users']}</code>\n"
            f"⚙️ <b>Maintenance Mode:</b> <code>{'ENABLED 🔴' if m_active else 'DISABLED 🟢'}</code>\n"
            f"🔑 <b>API Key Status:</b> <code>{'Configured ✅' if vook_client.get_api_key() else 'Direct Live Engine ⚡'}</code>"
        )
        try:
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=build_admin_panel_markup())
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Refreshed!")

    # Admin: Broadcast
    elif data == "adm_broadcast":
        if not is_admin(user_id):
            return
        USER_STATES[user_id] = "awaiting_broadcast"
        bot.send_message(call.message.chat.id, "📢 ব্রডকাস্ট মেসেজটি লিখুন:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

    # Admin: Set API Key
    elif data == "adm_setkey":
        if not is_admin(user_id):
            return
        USER_STATES[user_id] = "awaiting_api_key"
        bot.send_message(call.message.chat.id, "🔑 VookMail API Key (<code>vk_...</code>) সেন্ড করুন:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

    # Admin: Set Support
    elif data == "adm_setsupport":
        if not is_admin(user_id):
            return
        USER_STATES[user_id] = "awaiting_support"
        bot.send_message(call.message.chat.id, "💬 নতুন সাপোর্ট আইডি লিখুন:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

    # Admin: Ban User
    elif data == "adm_ban":
        if not is_admin(user_id):
            return
        USER_STATES[user_id] = "awaiting_ban_id"
        bot.send_message(call.message.chat.id, "🚫 যাকে Ban/Unban করতে চান তার <b>User ID</b> লিখুন:\n(বাতিল করতে /cancel লিখুন)")
        bot.answer_callback_query(call.id)

# ----------------- Interactive State Handler (User & Admin) -----------------

@bot.message_handler(func=lambda msg: msg.from_user.id in USER_STATES)
def handle_user_states(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    state = USER_STATES.get(user_id)

    if message.text == "/cancel":
        USER_STATES.pop(user_id, None)
        bot.reply_to(message, "❌ অ্যাকশন বাতিল করা হয়েছে।", reply_markup=get_main_keyboard(user_id))
        return

    # Admin: Search User ID Lookup
    if state == "awaiting_search_user_id":
        USER_STATES.pop(user_id, None)
        target_str = message.text.strip()
        if not target_str.isdigit():
            bot.reply_to(message, "❌ ইনভ্যালিড আইডি। সংখ্যা হতে হবে।", reply_markup=get_main_keyboard(user_id))
            return

        target_uid = int(target_str)
        user_info = database.get_user(target_uid)
        if not user_info:
            bot.reply_to(message, f"❌ User <code>{target_uid}</code>-কে ডাটাবেজে পাওয়া যায়নি।", reply_markup=get_main_keyboard(user_id))
            return

        user_history = database.get_user_history(target_uid, limit=5)
        ban_status = "BANNED ⛔" if user_info.get("is_banned") else "ACTIVE ✅"

        info_text = (
            f"🔍 <b>User Profile & Analytics</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>User ID:</b> <code>{target_uid}</code>\n"
            f"👤 <b>Name:</b> {user_info.get('first_name', 'N/A')}\n"
            f"🔗 <b>Username:</b> @{user_info.get('username') or 'NoUsername'}\n"
            f"📅 <b>Joined:</b> {user_info.get('created_at', '')[:19]}\n"
            f"🌐 <b>Saved Domain:</b> <code>@{user_info.get('selected_domain') or 'Auto'}</code>\n"
            f"🎯 <b>Saved Service:</b> <code>{user_info.get('selected_service') or 'General'}</code>\n"
            f"🚦 <b>Status:</b> <b>{ban_status}</b>\n"
            f"📧 <b>Total Recent Mails:</b> <code>{len(user_history)}</code>\n\n"
        )

        if user_history:
            info_text += "<b>সাম্প্রতিক মেইলসমূহ:</b>\n"
            for h in user_history:
                info_text += f"• <code>{h['email']}</code> ({h.get('service', 'General')})\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_ban = types.InlineKeyboardButton("🚫 Toggle Ban", callback_data=f"admtoggleban_{target_uid}")
        btn_dm = types.InlineKeyboardButton("💬 Send DM", callback_data=f"admreply_{target_uid}")
        btn_back = types.InlineKeyboardButton("🔙 Back to Admin", callback_data="adm_refresh")
        markup.add(btn_ban, btn_dm)
        markup.add(btn_back)

        bot.send_message(message.chat.id, info_text, reply_markup=markup)

    # User Login to Existing Mail
    elif state == "awaiting_login_email":
        USER_STATES.pop(user_id, None)
        target_email = message.text.strip().lower()

        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", target_email):
            bot.reply_to(
                message,
                "❌ <b>ইনভ্যালিড ইমেইল ফরম্যাট!</b>\nসঠিক ইমেইল দিন (যেমন: <code>user123@lockomail.com</code>)।",
                reply_markup=get_main_keyboard(user_id)
            )
            return

        wait_msg = bot.send_message(message.chat.id, "🔍 <i>Checking mailbox status...</i>")

        mail_row = database.get_mail_by_address(target_email) or {}
        res = vook_client.get_messages(target_email, token=mail_row.get("token"), cookie=mail_row.get("cookie"))
        
        if res.get("success"):
            database.add_mail_history(
                user_id=user_id,
                email=target_email,
                token=mail_row.get("token", ""),
                cookie=mail_row.get("cookie", ""),
                service="Logged In",
                expires_at="Active"
            )

            database.log_activity(user_id, username, first_name, "LOGIN_MAIL", target_email)

            target_domain = target_email.split("@")[1] if "@" in target_email else ""

            login_text = (
                f"✨ <b>Mailbox Logged In Successfully!</b>\n\n"
                f"📬 <b>Email:</b> <code>{target_email}</code>\n"
                f"🌐 <b>Domain:</b> <code>@{target_domain}</code>\n"
                f"🎯 <b>Status:</b> <code>Active Inbox</code>"
            )

            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_copy = get_copy_button(target_email)
            btn_check = types.InlineKeyboardButton("🔄 Check Inbox", callback_data=f"chk_{target_email}")
            btn_del = types.InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{target_email}")
            markup.add(btn_copy)
            markup.add(btn_check, btn_del)

            bot.edit_message_text(login_text, chat_id=message.chat.id, message_id=wait_msg.message_id, reply_markup=markup)
        else:
            bot.edit_message_text(
                f"❌ <b>মেইলবক্স পাওয়া যায়নি বা মেয়াদ শেষ হয়ে গেছে!</b>\n\n<i>{res.get('error', 'Mailbox expired or unreachable')}</i>",
                chat_id=message.chat.id,
                message_id=wait_msg.message_id
            )

    # User Support Message Forwarding to Admin
    elif state == "awaiting_support_text":
        USER_STATES.pop(user_id, None)
        user_message_text = message.text

        database.log_activity(user_id, username, first_name, "SUPPORT_MSG", user_message_text[:40])

        all_admins = get_all_admin_ids()
        admin_alert_text = (
            f"📩 <b>New Support Message Received!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>From:</b> {first_name} (@{username if username else 'NoUsername'})\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🕒 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"📝 <b>Message:</b>\n"
            f"<i>{user_message_text}</i>"
        )

        admin_reply_markup = types.InlineKeyboardMarkup()
        admin_reply_markup.add(types.InlineKeyboardButton("💬 Reply to User", callback_data=f"admreply_{user_id}"))

        for admin_id in all_admins:
            try:
                bot.send_message(admin_id, admin_alert_text, reply_markup=admin_reply_markup)
            except Exception as e:
                print(f"[Admin Alert Failed] {admin_id}: {e}")

        confirm_text = "✅ আপনার মেসেজটি সফলভাবে এডমিনের কাছে পৌঁছে গেছে!"
        bot.reply_to(message, confirm_text, reply_markup=get_main_keyboard(user_id))

    # Admin replying to a user's support message
    elif state and state.startswith("replying_user_"):
        USER_STATES.pop(user_id, None)
        target_uid = int(state.split("replying_user_")[1])
        reply_content = message.text

        user_reply_text = (
            f"👑 <b>Support Team Response:</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{reply_content}"
        )
        try:
            bot.send_message(target_uid, user_reply_text)
            bot.reply_to(message, f"✅ User <code>{target_uid}</code>-কে মেসেজ পাঠানো হয়েছে!", reply_markup=get_main_keyboard(user_id))
        except Exception as e:
            bot.reply_to(message, f"❌ মেসেজ পাঠাতে ব্যর্থ হয়েছে: {e}", reply_markup=get_main_keyboard(user_id))

    # Admin: Broadcast
    elif state == "awaiting_broadcast":
        USER_STATES.pop(user_id, None)
        all_users = database.get_all_users()
        sent = 0
        failed = 0
        status_msg = bot.send_message(message.chat.id, f"🚀 ব্রডকাস্ট শুরু হচ্ছে... (মোট: {len(all_users)})")

        for uid in all_users:
            try:
                bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
                sent += 1
                time.sleep(0.04)
            except Exception:
                failed += 1

        bot.edit_message_text(f"✅ <b>Broadcast Completed!</b>\n\n🎯 Sent: {sent}\n❌ Failed/Blocked: {failed}", chat_id=message.chat.id, message_id=status_msg.message_id)

    # Set API Key
    elif state == "awaiting_api_key":
        USER_STATES.pop(user_id, None)
        key = message.text.strip()
        database.set_setting("vook_api_key", key)
        bot.reply_to(message, "✅ API Key আপডেট করা হয়েছে!", reply_markup=get_main_keyboard(user_id))

    # Set Support
    elif state == "awaiting_support":
        USER_STATES.pop(user_id, None)
        sup = message.text.strip()
        database.set_setting("support_link", sup)
        bot.reply_to(message, f"✅ Support Link আপডেট করা হয়েছে: {sup}", reply_markup=get_main_keyboard(user_id))

    # Ban User
    elif state == "awaiting_ban_id":
        USER_STATES.pop(user_id, None)
        target_str = message.text.strip()
        if not target_str.isdigit():
            bot.reply_to(message, "❌ ইনভ্যালিড ইউজার আইডি।")
            return
        target_id = int(target_str)
        currently_banned = database.is_banned(target_id)
        new_status = 0 if currently_banned else 1
        database.set_ban_status(target_id, new_status)
        action_word = "Unbanned ✅" if new_status == 0 else "Banned ⛔"
        bot.reply_to(message, f"User {target_id} is now {action_word}.", reply_markup=get_main_keyboard(user_id))

# ----------------- Background Inbox Listener -----------------

def background_inbox_poller():
    """
    Periodically checks recent active mailboxes in real-time.
    Uses authentic tokens and session cookies to fetch incoming messages from VookMail.
    """
    while True:
        try:
            active_mails = database.get_all_active_mails(limit=30)
            for item in active_mails:
                user_id = item["user_id"]
                email = item["email"]
                token = item.get("token")
                cookie = item.get("cookie")
                
                res = vook_client.get_messages(email, token=token, cookie=cookie)
                if res.get("success"):
                    for msg in res.get("messages", []):
                        msg_id = str(msg.get("id", ""))
                        if msg_id and not database.is_message_seen(msg_id):
                            database.mark_message_seen(msg_id, email)

                            sender = msg.get("from", "Unknown")
                            subject = msg.get("subject", "No Subject")
                            code = msg.get("verification_code", "") or msg.get("code", "")
                            link = msg.get("verification_link", "") or msg.get("link", "")

                            notify_text = (
                                f"📨 <b>New Message Received!</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📬 <b>To:</b> <code>{email}</code>\n"
                                f"👤 <b>From:</b> <code>{sender}</code>\n"
                                f"📝 <b>Subject:</b> <b>{subject}</b>\n"
                            )
                            if code:
                                notify_text += f"\n🔑 <b>Verification Code:</b> <code>{code}</code>\n"
                            if link:
                                notify_text += f"\n🔗 <b>Verification Link:</b> <a href=\"{link}\">Click Here</a>\n"

                            markup = build_message_markup(address=email, msg_id=msg_id, code=code, link=link)

                            try:
                                bot.send_message(user_id, notify_text, reply_markup=markup)
                            except Exception as e:
                                print(f"[Notifier] Failed to notify {user_id}: {e}")
        except Exception as e:
            print(f"[Poller Exception] {e}")

        time.sleep(8)

# ----------------- Main Entrypoint -----------------

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 VookMail Telegram Bot is Starting...")
    print(f"👑 Admin IDs: {get_all_admin_ids()}")
    print(f"💾 Database Engine: {'Supabase PostgreSQL (Cloud 24/7)' if database.USE_POSTGRES else 'Local SQLite (Fallback)'}")
    print("=" * 50)

    # 1. Start lightweight Render Health Check web server in background daemon
    web_thread = threading.Thread(target=run_render_web_server, daemon=True)
    web_thread.start()

    # 2. Check if recovering from a 1-click admin restart
    restart_chat = database.get_setting("restart_chat_id", "")
    if restart_chat and restart_chat.isdigit():
        database.set_setting("restart_chat_id", "")
        try:
            bot.send_message(
                int(restart_chat),
                "✅ <b>বট সফলভাবে রিস্টার্ট সম্পন্ন হয়েছে এবং সম্পূর্ণ লাইভ ও সক্রিয় আছে!</b>",
                reply_markup=get_main_keyboard(int(restart_chat))
            )
        except Exception as e:
            print(f"[Restart Notify Error] {e}")

    # 3. Start background inbox listener thread
    poller_thread = threading.Thread(target=background_inbox_poller, daemon=True)
    poller_thread.start()
    print("⚡ Background live inbox notifier started.")

    # 4. Start bot polling
    print("🚀 Bot is now polling for messages...")
    bot.infinity_polling(skip_pending=True)
