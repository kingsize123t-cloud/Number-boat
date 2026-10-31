import requests
import time
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import threading
import re
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime 

# ============================================================
# Load .env file (python-dotenv)
# ============================================================
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; use system environment variables

# ==========================================
# Configuration (Token & Owner ID)
# ==========================================
# ⚠️  DO NOT hardcode credentials here.
#     Put them in your .env file (see .env.example).
TOKEN = os.environ.get("BOT_TOKEN", "")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}/"

_owner_raw = os.environ.get("OWNER_ID", "0")
if not _owner_raw.isdigit():
    raise RuntimeError("OWNER_ID must be a numeric Telegram user ID. Set it in your .env file.")
OWNER_ID = int(_owner_raw)

BOT_USERNAME = ""
DB_FILE = "bot_data.json"

# ╔══════════════════════════════════════════════════════════════════╗
# ║  🗺️  BOT CODE MAP — নতুন ফিচার কোথায় বসাবেন (সংক্ষিপ্ত ম্যাপ)        ║
# ╠══════════════════════════════════════════════════════════════════╣
# ║  📂 ফাইল অর্ডার (উপর থেকে নিচে):                                   ║
# ║  1️⃣ CONFIG → 2️⃣ DATA (load/save) → 3️⃣ API HELPERS →             ║
# ║  4️⃣ USER BACKEND (balance/refer) → 5️⃣ KEYBOARDS + ZONE-A/A2 →    ║
# ║  6️⃣ FEATURE MODULES → 7️⃣ handle_message (ZONE-B/C) →            ║
# ║  8️⃣ handle_callback (ZONE-E) → 9️⃣ main()                        ║
# ║                                                                  ║
# ║  নতুন ফিচার যোগ করতে কোডের ভেতরে নিচের ZONE গুলো খুঁজুন            ║
# ║  (Ctrl+F করে লিখুন: ZONE-A অথবা ZONE-B ...)                     ║
# ║                                                                  ║
# ║  ZONE-A   → main_menu()               ইউজার কিবোর্ড বাটন যোগ      ║
# ║  ZONE-A2  → main_menu()               অ্যাডমিন কিবোর্ড বাটন যোগ    ║
# ║  ZONE-B   → handle_message()          ইউজার বাটনের "কাজ" বসান     ║
# ║  ZONE-C   → handle_message()          ইনপুট (লেখা পাঠানো) স্টেট   ║
# ║  ZONE-D   → admin_panel_keyboard()    অ্যাডমিন প্যানেল বাটন যোগ   ║
# ║  ZONE-D2  → system_settings_keyboard() System Settings বাটন যোগ  ║
# ║  ZONE-E   → handle_callback()         ইনলাইন বাটনের "কাজ" বসান   ║
# ║                                                                  ║
# ║  🧩 নতুন সিস্টেম = "FEATURE MODULE #N" ব্লক (helper + keyboard     ║
# ║     একসাথে) + ZONE হুক — লাইভ উদাহরণ: FEATURE MODULE #1          ║
# ║                                                                  ║
# ║  📖 বিস্তারিত গাইড: FEATURE-GUIDE-BANGLA.md (প্রজেক্ট ফোল্ডারে)    ║
# ║  📐 নিয়ম: বাটন (কিবোর্ড) → কাজ (handler) → ইনপুট লাগলে (state)    ║
# ╚══════════════════════════════════════════════════════════════════╝

# ==========================================
# Premium Emoji Database
# ==========================================
PEM = {
    "ok": '<tg-emoji emoji-id="5352694861990501856">✅</tg-emoji>',
    "no": '<tg-emoji emoji-id="5420130255174145507">❌</tg-emoji>',
    "warn": '<tg-emoji emoji-id="5336944168944047463">⚠️</tg-emoji>',
    "admin": '<tg-emoji emoji-id="5353032893096567467">📊</tg-emoji>',
    "user": '<tg-emoji emoji-id="5352861489541714456">👤</tg-emoji>',
    "file": '<tg-emoji emoji-id="5352721946054268944">📁</tg-emoji>',
    "rocket": '<tg-emoji emoji-id="5352597830089347330">🚀</tg-emoji>',
    "graph": '<tg-emoji emoji-id="5352877703043258544">📊</tg-emoji>',
    "money": '<tg-emoji emoji-id="5348469219761626211">💸</tg-emoji>',
    "gift": '<tg-emoji emoji-id="5420396762189831222">🎁</tg-emoji>',
    "msg": '<tg-emoji emoji-id="5337302974806922068">💬</tg-emoji>',
    "gear": '<tg-emoji emoji-id="5420155432272438703">⚙️</tg-emoji>',
    "link": '<tg-emoji emoji-id="5420517437885943844">🔗</tg-emoji>',
    "trash": '<tg-emoji emoji-id="5422557736330106570">🗑</tg-emoji>',
    "upload": '<tg-emoji emoji-id="5353001161878182134">📤</tg-emoji>',
    "world": '<tg-emoji emoji-id="5336972142066047577">🌐</tg-emoji>',
    "lock": '<tg-emoji emoji-id="5353022963132174959">🔐</tg-emoji>',
    "phone": '<tg-emoji emoji-id="5337132498965010628">📱</tg-emoji>',
    "num": '<tg-emoji emoji-id="5352862640592949843">🔢</tg-emoji>',
    "pin": '<tg-emoji emoji-id="5352922460897452503">📍</tg-emoji>',
    "star": '<tg-emoji emoji-id="5352552689983067014">✨</tg-emoji>',
    "hi": '<tg-emoji emoji-id="5353027129250453493">👋</tg-emoji>'
}

GLOBAL_BODY_EMOJIS = {
    "➖": "5870818207383686839", "🚫": "5334807341109908955", "😒": "5334763399299506604",
    "🖥": "5334880948259427772", "🌐": "5334590977837403844", "🌟": "5337102391244263212",
    "🕓": "5336983442125001376", "⌛": "5337172996211648018", "💬": "5337302974806922068",
    "🔐": "5337255927735163754", "🍏": "5337132498965010628", "❔": "5336850036145823599",
    "⚠️": "5336944168944047463", "🔥": "5337267511261960341", "💸": "5348469219761626211",
    "🥚": "5348390922507817684", "👨‍⚖": "5334763399299506604", "🐁": "5348494358205207761",
    "🧻": "5348486915026884464", "⚗": "5346311574221000149", "🛴": "5348075478634766440",
    "📊": "5353032893096567467", "🔢": "5352862640592949843", "👤": "5352861489541714456",
    "📁": "5352721946054268944", "🚀": "5352597830089347330", "💎": "5352838545826420397",
    "📍": "5352922460897452503", "👋": "5353027129250453493", "✅": "5352694861990501856",
    "1️⃣": "5352651766288652742", "2️⃣": "5355186458418257716", "3️⃣": "5352867219028091093",
    "4️⃣": "5352566657216714037", "5️⃣": "5353086880835474989", "6️⃣": "5354859211975071385",
    "7️⃣": "5352859127309707652", "8️⃣": "5352957533600389988", "9️⃣": "5353060913463204207",
    "🔤": "5352727417842606016", "📣": "5352980533150259581", "📤": "5353001161878182134",
    "✨": "5352552689983067014", "🔹": "5352638632278660622", "🎙": "5355102594886833928",
    "💴": "5352985330628730418", "📅": "5352585194295564660", "📴": "5352974971167611327",
    "✏️": "5395444784611480792", "📱": "5337132498965010628", "🔗": "5420517437885943844",
    "❌": "5420130255174145507", "⚙️": "5420155432272438703", "🫂": "5420145051336485498",
    "➕": "5420323438508155202", "🗑": "5422557736330106570", "🎁": "5420396762189831222",
    "➤": "5420618897898381296", "🏢": "5420156334215565595", "💳": "5190899075968441286",
    "📝": "5192739271886282680", "🛡": "5190447043545438788", "🤝": "5192805934073685937",
    "💰": "5190576863226933563", "👀": "5190645917711114179", "🕹": "5193100774988617665",
    "🟢": "5192812028632274956", "🧪": "5190781475468915802", "🎨": "5190751148704833975",
    "📂": "5257969839313526622", "🌍": "5780471598922337683", "📌": "5318986077455795572",
    "📢": "5789428375261023681", "🆔": "5352862640592949843", "📈": "5352877703043258544",
    "🔔": "5352980533150259581", "🏦": "5348469219761626211", "🧾": "5192739271886282680",
    "👨‍⚖️": "5334763399299506604", "🔍": "5463352748751753567",
    "🔑": "5197288647275071607"
}

DEFAULT_CUSTOM_MESSAGES = {
    "start": {"text": "╔═══════════╗\n       📊 NUMBER BOT\n╚═══════════╝\n🚀 Welcome to Number & OTP Service\n━━━━━━━━━━━━\n✅ Choose an option below\nto continue using the bot.\n━━━━━━━━━━━━\n💎 Premium OTP Service", "buttons": []},
    "refer": {"text": f"➖➖➖➖➖➖➖\n« {PEM['gift']} REFER & EARN »\n➖➖➖➖➖➖➖\n{PEM['link']} YOUR LINK:\n<code>{{ref_link}}</code>\n➖➖➖➖➖➖➖\n{PEM['user']} TOTAL REFERS: <b>{{total_ref}}</b>\n➖➖➖➖➖➖➖\n{PEM['money']} PER REFER: <b>{{ref_reward}} TK</b>\n➖➖➖➖➖➖➖", "buttons": []},
    "withdrawal": {"text": "➖➖➖➖➖➖➖\n《 😒 WITHDRAWAL 》\n➖➖➖➖➖➖➖\n👋 Total Otp: {total_otp}\n➖➖➖➖➖➖➖\n🫂 Total Reffer :{total_ref}\n➖➖➖➖➖➖➖\n📅 BALANCE: {bal}৳\n➖➖➖➖➖➖➖\n🔐 MINIMUM: {min_w} ৳\n➖➖➖➖➖➖➖\nSELECT METHOD:", "buttons": []},
    "support": {"text": f"{PEM['msg']} Contact us for any help:", "buttons": []},
    "community": {"text": f"➖➖➖➖➖➖➖\n« {PEM['user']} COMMUNITY »\n➖➖➖➖➖➖➖\n{PEM['msg']} Join our official community:\n➖➖➖➖➖➖➖", "buttons": []}
}

# ==========================================
# Firebase Setup
# ==========================================
# Load Firebase credentials from a JSON file (path set in .env → FIREBASE_CREDENTIALS_PATH)
_fb_creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")

try:
    if os.path.exists(_fb_creds_path):
        with open(_fb_creds_path, "r", encoding="utf-8") as _f:
            cred_dict = json.load(_f)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firebase Connected! (Full Sync Enabled)")
    else:
        print(f"⚠️  Firebase credentials file not found: {_fb_creds_path}")
        print("   Continuing without Firebase (local JSON only).")
        db = None
except Exception as e:
    print(f"❌ Firebase Error: {e}")
    db = None

# ─── Pre-load Force Join, Support Link from .env ─────────────────
_env_fj_on       = os.environ.get("FORCE_JOIN_ON", "false").lower() == "true"
_env_fj_channels_raw = os.environ.get("FORCE_JOIN_CHANNELS", "").strip()
_env_fj_channels = [ch.strip() for ch in _env_fj_channels_raw.split(",") if ch.strip()] if _env_fj_channels_raw else []
_env_support     = os.environ.get("SUPPORT_LINK",   "https://t.me/your_support")
_env_w_group     = os.environ.get("WITHDRAWAL_GROUP", "")

bot_settings = {
    "admins": [OWNER_ID],
    "withdraw_on": os.environ.get("WITHDRAW_ON", "true").lower() == "true",
    "min_withdraw": float(os.environ.get("MIN_WITHDRAW", "30.0")),
    "refer_reward": float(os.environ.get("REFER_REWARD", "0.2")),
    "support_link": _env_support,
    "w_methods": ["bKash", "Nagad"],
    "w_group": _env_w_group,
    "support_buttons": [],
    "community_buttons": [],

    "fj_on": _env_fj_on,
    "fj_channels": _env_fj_channels,
    "custom_messages": DEFAULT_CUSTOM_MESSAGES.copy()
}

FS_KEYS = [
    "admins", "withdraw_on",
    "min_withdraw", "refer_reward",
    "support_link", "w_methods", "w_group",
    "fj_on", "fj_channels",
    "support_buttons", "community_buttons"
]

user_banned_cache = {}

def load_db():
    global bot_settings
    if db:
        try:
            doc = db.collection('settings').document('bot_config').get()
            if doc.exists:
                fs_data = doc.to_dict()
                for k in FS_KEYS:
                    if k in fs_data:
                        bot_settings[k] = fs_data[k]
                print("✅ Config Loaded from Firestore!")
            else:
                fs_data = {k: bot_settings[k] for k in FS_KEYS}
                db.collection('settings').document('bot_config').set(fs_data)
                print("✅ Firestore Config Initialized!")
        except Exception as e:
            print(f"❌ Error loading from Firestore: {e}")

    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                saved_settings = data.get("bot_settings", {})
                for key, val in saved_settings.items():
                    if key not in FS_KEYS:
                        if key == "custom_messages":
                            for m_key, m_val in val.items():
                                bot_settings["custom_messages"][m_key] = m_val
                        else:
                            bot_settings[key] = val
                        
                for m_key, m_val in DEFAULT_CUSTOM_MESSAGES.items():
                    if m_key not in bot_settings["custom_messages"]:
                        bot_settings["custom_messages"][m_key] = m_val
                        
            print("✅ Local Stock/UI DB Loaded Successfully!")
        except Exception as e:
            print(f"❌ Error loading local DB: {e}")

def save_local_db():
    local_data = {
        "bot_settings": {k: v for k, v in bot_settings.items() if k not in FS_KEYS}
    }
    try:
        with open(DB_FILE, "w", encoding='utf-8') as f:
            json.dump(local_data, f, indent=4)
    except Exception as e:
        pass

def _sync_fs():
    if not db: return
    fs_data = {k: bot_settings[k] for k in FS_KEYS if k in bot_settings}
    try:
        db.collection('settings').document('bot_config').set(fs_data)
    except: pass

def save_db():
    save_local_db()
    # 🌟 Firestore Save Threading: মেইন বটকে স্লো না করার জন্য ব্যাকগ্রাউন্ডে সেভ হবে
    threading.Thread(target=_sync_fs, daemon=True).start()

load_db()

user_states = {}
temp_data = {}
pending_withdrawals = {}

# ==========================================
# Telegram API & Helpers
# ==========================================
tg_session = requests.Session() # 🌟 Keep-Alive Connection (Makes bot 10x faster)

def api_call(method, payload=None):
    url = f"{BASE_URL}/{method}"
    try:
        # 🌟 Added timeout to prevent hanging!
        res = tg_session.post(url, json=payload, timeout=15)
        return res.json()
    except Exception as e:
        return {}

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return api_call("sendMessage", payload)

def send_photo(chat_id, photo_url_or_file_id, caption="", reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "photo": photo_url_or_file_id, "caption": caption, "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = reply_markup
    return api_call("sendPhoto", payload)

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return api_call("editMessageText", payload)

def delete_message(chat_id, message_id):
    return api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def answer_callback(callback_id, text="", show_alert=False):
    api_call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": show_alert})

def send_document(chat_id, filename, text_content):
    url = f"{BASE_URL}/sendDocument"
    files = {'document': (filename, text_content)}
    data = {'chat_id': chat_id}
    try: requests.post(url, data=data, files=files)
    except: pass

# 🌟 Local User List to completely remove Firebase Read Costs!
all_known_users = set()

def sync_users_list():
    global all_known_users
    try:
        if os.path.exists("users_list.json"):
            with open("users_list.json", "r") as f:
                all_known_users = set(json.load(f))
        if not all_known_users and db:
            for doc in db.collection('users').select([]).stream():
                all_known_users.add(doc.id)
            with open("users_list.json", "w") as f:
                json.dump(list(all_known_users), f)
    except: pass

threading.Thread(target=sync_users_list, daemon=True).start()

def _save_users_list():
    try:
        with open("users_list.json", "w") as f:
            json.dump(list(all_known_users), f)
    except: pass

def register_user_local(uid):
    uid_str = str(uid)
    if uid_str not in all_known_users:
        all_known_users.add(uid_str)
        # 🌟 Non-blocking background save (Prevents lag)
        threading.Thread(target=_save_users_list, daemon=True).start()

def broadcast_copymessage(from_chat_id, msg_id):
    success = 0
    failed = 0
    users = list(all_known_users)
    
    # 🌟 Dedicated Connection Pool for Broadcast (Fixes Port Exhaustion & Network Lag)
    b_session = requests.Session()
    url = f"{BASE_URL}/copyMessage"
    
    for user_id in users:
        payload = {"chat_id": user_id, "from_chat_id": from_chat_id, "message_id": msg_id}
        try:
            res = b_session.post(url, json=payload, timeout=5).json()
            if res.get("ok"): success += 1
            else: failed += 1
        except:
            failed += 1
        time.sleep(0.035) # Safe speed (28 msgs/sec) to prevent Telegram Ban
        
    send_message(from_chat_id, render_body_text(f"📢 <b>Broadcast Completed!</b>\n✅ Success: {success}\n❌ Failed: {failed}\n👥 Total Sent: {len(users)}"))

def render_body_text(text):
    if not text: return str(text)
    parts = re.split(r'(<tg-emoji.*?</tg-emoji>)', str(text))
    for i in range(len(parts)):
        if not parts[i].startswith('<tg-emoji'):
            for normal_emj, prem_id in GLOBAL_BODY_EMOJIS.items():
                if normal_emj in parts[i]:
                    parts[i] = parts[i].replace(normal_emj, f'<tg-emoji emoji-id="{prem_id}">{normal_emj}</tg-emoji>')
    return "".join(parts)

def extract_premium_html(msg):
    text = msg.get("text", msg.get("caption", ""))
    entities = msg.get("entities", msg.get("caption_entities", []))
    if not entities: return text
    try:
        b_text = text.encode('utf-16-le')
        c_entities = [e for e in entities if e.get("type") == "custom_emoji"]
        c_entities.sort(key=lambda x: x["offset"], reverse=True)
        for ent in c_entities:
            offset = ent["offset"] * 2
            length = ent["length"] * 2
            eid = ent["custom_emoji_id"]
            emoji_char = b_text[offset:offset+length].decode('utf-16-le')
            html_tag = f'<tg-emoji emoji-id="{eid}">{emoji_char}</tg-emoji>'
            replacement = html_tag.encode('utf-16-le')
            b_text = b_text[:offset] + replacement + b_text[offset+length:]
        return b_text.decode('utf-16-le')
    except Exception as e:
        return text 

def parse_chat_id(text):
    text = text.strip()
    if text.startswith("-100") or (text.startswith("-") and text[1:].isdigit()):
        return text
    if "t.me/" in text:
        parts = text.split("/")
        username = parts[-1]
        if username: return "@" + username if not username.startswith("@") else username
    if text.startswith("@"):
        return text
    return "@" + text

def is_admin(user_id):
    return user_id in bot_settings["admins"] or user_id == OWNER_ID

def check_force_join(user_id):
    if not bot_settings["fj_on"] or not bot_settings["fj_channels"]: return True
    if is_admin(user_id): return True
    for ch in bot_settings["fj_channels"]:
        res = api_call("getChatMember", {"chat_id": ch, "user_id": user_id})
        if res.get("ok") and res["result"]["status"] not in ["left", "kicked"]: continue
        else: return False
    return True

def send_force_join_msg(chat_id):
    kb = []
    for ch in bot_settings["fj_channels"]:
        url = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        kb.append([{"text": f"Join Channel", "icon_custom_emoji_id": "5789428375261023681", "url": url, "style": "primary"}])
    kb.append([{"text": "Check Joined", "icon_custom_emoji_id": "5352694861990501856", "callback_data": "check_fj", "style": "success"}])
    send_message(chat_id, render_body_text(f"{PEM['warn']} <b>Please join our channels to use the bot!</b>"), reply_markup={"inline_keyboard": kb})

def is_user_banned(user_id):
    if is_admin(user_id): return False
    if user_id in user_banned_cache and time.time() - user_banned_cache[user_id]['time'] < 60:
        return user_banned_cache[user_id]['banned']
    banned = False
    if db:
        try:
            doc = db.collection('users').document(str(user_id)).get()
            banned = doc.exists and doc.to_dict().get("banned", False)
        except: pass
    user_banned_cache[user_id] = {'banned': banned, 'time': time.time()}
    return banned

# ==========================================
# Captcha Auto Login & Parsing Core
# ==========================================
# 🌟 Local User Cache
user_cache = {}

def get_user(user_id):
    if user_id in user_cache: return user_cache[user_id]
    if not db: return {"user_id": user_id, "balance": 0.0, "total_refers": 0, "total_otps": 0}
    
    doc_ref = db.collection('users').document(str(user_id))
    doc = doc_ref.get()
    if doc.exists: 
        data = doc.to_dict()
        if "total_otps" not in data: data["total_otps"] = 0
        if "banned" not in data: data["banned"] = False
        if "verified" not in data: data["verified"] = False
        user_cache[user_id] = data
        return data
    else:
        new_user = {"user_id": user_id, "balance": 0.0, "total_refers": 0, "total_otps": 0, "banned": False, "verified": False}
        doc_ref.set(new_user)
        user_cache[user_id] = new_user
        return new_user

def update_balance(user_id, amount):
    if user_id in user_cache:
        user_cache[user_id]["balance"] = user_cache[user_id].get("balance", 0.0) + float(amount)
    if not db: return
    try:
        doc_ref = db.collection('users').document(str(user_id))
        # 🌟 No more .get() before update! Saves 1 Read Cost instantly!
        doc_ref.set({"user_id": user_id, "balance": firestore.Increment(float(amount))}, merge=True)
    except: pass

def record_refer_income(inviter_id, new_user_id, reward):
    # 🧩 FEATURE MODULE #1: রেফার ইনকাম হিস্ট্রি সেভ (📜 Transaction History তে দেখাবে)
    if not db: return
    try:
        db.collection('refer_income').document(f"R_{str(uuid.uuid4())[:8].upper()}").set({
            "user_id": str(inviter_id), "amount": float(reward),
            "from_user": str(new_user_id), "timestamp": firestore.SERVER_TIMESTAMP})
    except: pass

def add_referral(inviter_id, new_user_id):
    if not db.collection('users').document(str(new_user_id)).get().exists:
        get_user(new_user_id) 
        reward = bot_settings.get("refer_reward", 0.2)
        update_balance(inviter_id, reward)
        db.collection('users').document(str(inviter_id)).update({"total_refers": firestore.Increment(1)})
        record_refer_income(inviter_id, new_user_id, reward)
        
        # আপনার দেওয়া নতুন ডিজাইন
        ref_msg = (
            f"{PEM['gift']} <b>New Referral !</b>\n"
            f"------------------\n"
            f"🔥 <b>You Received {reward} TK</b>\n"
            f"------------------\n"
            f"{PEM['user']} <b>From User ID:</b> <code>{new_user_id}</code>"
        )
        send_message(inviter_id, render_body_text(ref_msg))

# ==========================================
# UI Keyboards & Menu Builders
# ==========================================
def get_cancel_kb():
    return {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_state", "style": "danger"}]]}

# ══════════════════════════════════════════════════════════════
# 🧩 ZONE-A | USER MENU BUTTONS (ইউজার মেনু — রিপ্লাই কিবোর্ড)
# ──────────────────────────────────────────────────────────────
# 👉 নতুন ইউজার ফিচারের বাটন যোগ করুন নিচের main_menu() ফাংশনে।
#    বাটন চাপলে যা ঘটবে সেটি বসাতে হবে handle_message() এর
#    "ZONE-B | USER BUTTON ACTIONS" অংশে।
#
# ⚠️ নিয়ম: নতুন বাটনের নাম হুবহু এই লিস্টেও যোগ করতে হবে —
#    নাহলে ইউজার মাঝপথে ইনপুট দেওয়ার সময় বাটন চাপলে সেটি
#    ইনপুট হিসেবে গিনে নেওয়া হবে, মেনু কমান্ড হিসেবে নয়!
# ══════════════════════════════════════════════════════════════
USER_MENU_BUTTONS = ["🛒 tg sell", "💳 Account", "Refer", "WITHDRAWAL", "SUPPORT", "Community"]

def main_menu(user_id):
    kb = []
    # ── 🧩 ZONE-A: নতুন ইউজার বাটন এখানে যোগ করুন ───────────────────
    # 📌 TEMPLATE (কপি করে নাম বদলান, তারপর কাজ বসান ZONE-B তে):
    # kb.append([{"text": "🆕 MY NEW BUTTON", "style": "primary"}])
    # এবং উপরের USER_MENU_BUTTONS লিস্টেও "🆕 MY NEW BUTTON" যোগ করুন।
    # ─────────────────────────────────────────────────────────────
    # রো-১: সবার উপরে 💳 Account
    kb.append([
        {"text": "🛒 tg sell", "icon_custom_emoji_id": "5192812028632274956", "style": "primary"},
        {"text": "💳 Account", "icon_custom_emoji_id": "5352861489541714456", "style": "primary"}
    ])
    # রো-২: Refer | WITHDRAWAL
    kb.append([
        {"text": "Refer", "icon_custom_emoji_id": "5420396762189831222", "style": "success"},
        {"text": "WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "style": "danger"}
    ])
    # রো-৩: SUPPORT | Community
    kb.append([
        {"text": "SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "style": "primary"},
        {"text": "Community", "icon_custom_emoji_id": "5352980533150259581", "style": "primary"}
    ])

    # ── 🧩 ZONE-A2: শুধু অ্যাডমিনদের কিবোর্ড বাটন এখানে যোগ হয় ────────
    if is_admin(user_id): 
        kb.append([{"text": "Admin Panel", "icon_custom_emoji_id": "5420155432272438703", "style": "danger"}])
        # 📌 ZONE-A2 TEMPLATE (অ্যাডমিন কিবোর্ডে আরও বাটন লাগলে):
        # kb.append([{"text": "🆕 ADMIN TOOL", "style": "primary"}])
        # (এর কাজ বসাবেন ZONE-B তে: elif text == "🆕 ADMIN TOOL" and is_admin(chat_id):)
    return {"keyboard": kb, "resize_keyboard": True}

def get_admin_text():
    users_count = len(all_known_users) # 🌟 Zero Cost User Count!

    txt = f"""
{PEM['admin']} <b>ADMIN CONTROL PANEL</b> {PEM['admin']}
━━━━━━━━━━━━━━━━━━

{PEM['graph']} <b>DATABASE OVERVIEW</b>
— — — — — — — — — —
{PEM['user']} Users      » {users_count}
"""
    return render_body_text(txt)

def admin_panel_keyboard():
    return {"inline_keyboard": [
        [{"text": "LEADER BOARD SYSTEM", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "lb_main", "style": "success"}],
        [{"text": "Broadcast", "icon_custom_emoji_id": "5789428375261023681", "callback_data": "broadcast_msg", "style": "success"},
         {"text": "System", "icon_custom_emoji_id": "5420155432272438703", "callback_data": "system_settings", "style": "primary"}],
        [{"text": "Support Buttons", "icon_custom_emoji_id": "5337302974806922068", "callback_data": "manage_sb", "style": "success"},
         {"text": "Community", "icon_custom_emoji_id": "5352980533150259581", "callback_data": "manage_cb", "style": "primary"}],
        # ═════════════════════════════════════════════════════════
        # 🧩 ZONE-D | ADMIN PANEL BUTTONS (অ্যাডমিন প্যানেলে নতুন বাটন এখানে)
        # 👉 প্রতিটি বাটনের callback_data ইউনিক হতে হবে (যেমন: adm_xxx)।
        #    বাটনের "কাজ" বসাতে হবে handle_callback() এর ZONE-E অংশে।
        # 📌 TEMPLATE (কপি করে নাম বদলান):
        # [{"text": "🆕 MY ADMIN FEATURE", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "adm_my_feature", "style": "success"}],
        # ═════════════════════════════════════════════════════════
        [{"text": "🛒 Tg Sell Settings", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "adm_tgsell_set", "style": "success"}],
        [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]
    ]}

def system_settings_keyboard():
    return {"inline_keyboard": [
        [{"text": "Force Join System", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "manage_fj", "style": "primary"},
         {"text": "Admin Management", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "manage_admins", "style": "danger"}],
        [{"text": "User Management", "icon_custom_emoji_id": "5193063022226086560", "callback_data": "user_management", "style": "primary"}],
        [{"text": "Subscription", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "dummy_alert", "style": "success"}],
        [{"text": "DXA Control", "icon_custom_emoji_id": "5193100774988617665", "callback_data": "dxa_control", "style": "primary"},
         {"text": "Menu Design", "icon_custom_emoji_id": "5190751148704833975", "callback_data": "menu_design_list", "style": "primary"}],
        # ═════════════════════════════════════════════════════════
        # 🧩 ZONE-D2 | SYSTEM SETTINGS BUTTONS (System Settings এ নতুন বাটন)
        # 👉 সেটিংস-ধর্মী নতুন ফিচারের বাটন এখানে যোগ করুন (callback_data:
        #    ss_xxx রাখুন)। কাজ বসাবেন handle_callback() এর ZONE-E তে।
        # 📌 TEMPLATE:
        # [{"text": "🆕 MY SETTING", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "ss_my_setting", "style": "primary"}],
        # ═════════════════════════════════════════════════════════
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
    ]}

def get_user_management_text():
    # 🌟 Fast & Free User Management Stats!
    total = len(all_known_users)
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    txt = f"""➖➖➖➖➖➖➖➖
《 👋 USER VIEW 》
➖➖➖➖➖➖➖➖
📊 LIVE STATISTICS:
➖➖➖➖➖➖➖➖
🫂 TOTAL USERS: {total}
✅ VERIFIED USERS: (Hidden to save DB Cost)
🚫 BANNED USERS: (Hidden to save DB Cost)
➖➖➖➖➖➖➖➖
⌛ UPDATED: {now_str}"""
    return render_body_text(txt)

def user_management_keyboard():
    return {"inline_keyboard": [
        [{"text": "Manage Balance", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "um_manage_balance", "style": "primary"},
         {"text": "Ban/Unban User", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "um_ban_unban", "style": "danger"}],
        [{"text": "User Profile", "icon_custom_emoji_id": "5352861489541714456", "callback_data": "um_user_profile", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def menu_design_list_keyboard():
    return {"inline_keyboard": [
        [{"text": "Edit /start Menu", "icon_custom_emoji_id": "5395444784611480792", "callback_data": "md_edit_start", "style": "primary"}],
        [{"text": "Edit Refer", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "md_edit_refer", "style": "primary"}],
        [{"text": "Edit WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "callback_data": "md_edit_withdrawal", "style": "danger"},
         {"text": "Edit SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "md_edit_support", "style": "danger"}],
        [{"text": "Edit Community", "icon_custom_emoji_id": "5352980533150259581", "callback_data": "md_edit_community", "style": "primary"}],
        [{"text": "Reset Defaults", "icon_custom_emoji_id": "5192812028632274956", "callback_data": "md_reset_defaults", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def menu_edit_options_keyboard(menu_key):
    return {"inline_keyboard": [
        [{"text": "Edit Body (Text)", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"md_text_{menu_key}", "style": "primary"}],
        [{"text": "Edit Inline Buttons", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"md_btns_{menu_key}", "style": "success"}],
        [{"text": "Back to Menus", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "menu_design_list", "style": "danger"}]
    ]}

def menu_buttons_list_keyboard(menu_key):
    kb = []
    btns = bot_settings["custom_messages"].get(menu_key, {}).get("buttons", [])
    for idx, btn in enumerate(btns):
        kb.append([{"text": f"Del: {btn['text']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"md_delbtn_{menu_key}_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Inline Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"md_addbtn_{menu_key}", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{menu_key}", "style": "primary"}])
    return {"inline_keyboard": kb}

def fj_settings_keyboard():
    status_text = 'ON' if bot_settings['fj_on'] else 'OFF'
    status_icon = "5352694861990501856" if bot_settings['fj_on'] else "5318840353510408444"
    kb = [[{"text": f"STATUS: {status_text}", "icon_custom_emoji_id": status_icon, "callback_data": "toggle_fj", "style": "primary"}]]
    for idx, ch in enumerate(bot_settings["fj_channels"]):
        kb.append([{"text": f"Delete: {ch}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_fj_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Channel", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_fj", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}])
    return {"inline_keyboard": kb}

def admin_settings_keyboard():
    kb = []
    for idx, adm in enumerate(bot_settings["admins"]):
        text_btn = f"Owner: {adm}" if adm == OWNER_ID else f"Delete: {adm}"
        icon_id = "5353032893096567467" if adm == OWNER_ID else "5420130255174145507"
        cb_data = "ignore" if adm == OWNER_ID else f"del_adm_{idx}"
        kb.append([{"text": text_btn, "icon_custom_emoji_id": icon_id, "callback_data": cb_data, "style": "danger" if adm != OWNER_ID else "primary"}])
    kb.append([{"text": "Add Admin", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_adm", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}])
    return {"inline_keyboard": kb}

def dxa_control_keyboard():
    w_status = "ON" if bot_settings["withdraw_on"] else "OFF"
    sup_status = "ON" if bot_settings.get("support_link") else "OFF"
    grp_status = "ON" if bot_settings.get("w_group") else "OFF"
    return {"inline_keyboard": [
        [{"text": f"WITHDRAW: {w_status}", "icon_custom_emoji_id": "5348469219761626211", "callback_data": "dxa_toggle_w", "style": "primary"}],
        [{"text": f"MIN WITHDRAW: {bot_settings['min_withdraw']}", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "dxa_min_w", "style": "success"}],
        [{"text": f"REFER REWARD: {bot_settings['refer_reward']}", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "dxa_ref_r", "style": "success"}],
        [{"text": f"SUPPORT LINK: {sup_status}", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "dxa_sup_link", "style": "success"},
         {"text": "W. METHODS", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "manage_w_methods", "style": "primary"}],
        [{"text": f"W. GROUP: {grp_status}", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "dxa_w_group", "style": "success"},
         {"text": "BACK", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
    ]}

def w_methods_keyboard():
    kb = []
    for idx, m in enumerate(bot_settings["w_methods"]):
        kb.append([{"text": f"Delete: {m}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_wm_{idx}", "style": "danger"}])
    kb.append([{"text": "Add Method", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_wm", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "dxa_control", "style": "primary"}])
    return {"inline_keyboard": kb}

# ══════════════════════════════════════════════════════════════
# 🧩 FEATURE MODULE #1 | ACCOUNT SYSTEM (💳 Account + 📜 Transaction History)
# ──────────────────────────────────────────────────────────────
# 👉 নতুন সিস্টেম বানানোর রেসিপি (একাধিক সিস্টেম গুছিয়ে রাখার নিয়ম):
#    ধাপ-১: নিচের মতো একটা "FEATURE MODULE #N" ব্লক খুলুন — ওই সিস্টেমের
#           সব helper + keyboard ফাংশন এক ব্লকে একসাথে থাকবে।
#    ধাপ-২: ZONE হুক বসান — বাটন (ZONE-A/A2/D/D2), কাজ (ZONE-B/E),
#           ইনপুট লাগলে (ZONE-C)।
#    ধাপ-৩: নতুন সেটিংস লাগলে bot_settings + FS_KEYS দুই জায়গায়ই যোগ করুন।
#
# 👉 ইউজার: 💳 Account → Username, User ID, Balance, Available, Pending,
#    Total Withdrawal + 📜 Transaction History (উইথড্র + রেফার ইনকাম)
# 👉 Firestore collections: withdrawals (স্ট্যাটাস সহ), refer_income (রেফার ইনকাম)
# ══════════════════════════════════════════════════════════════
MAX_LINK_BUTTONS = 20        # প্রতি সিস্টেমে (Support/Community) সর্বোচ্চ কতগুলো বাটন রাখা যাবে

def _fmt_ts(ts):
    # Firestore timestamp → ছোট তারিখ (defensive: datetime / string / None সব চলবে)
    try:
        if hasattr(ts, "strftime"): return ts.strftime("%d %b %Y")
        s = str(ts or "").strip()
        if not s or s == "None": return ""
        return s.split(" ")[0].split("T")[0]
    except: return ""

def _acc_pending_amount(user_id):
    # ⏳ Pending Balance: চলমান উইথড্র রিকোয়েস্টের মোট টাকা
    # (রিকোয়েস্টের সময়ই ব্যালেন্স থেকে কাটা হয়, অ্যাডমিন Reject করলে অটো রিফান্ড হয়)
    if not db: return 0.0
    total = 0.0
    try:
        for d in db.collection('withdrawals').where('user_id', '==', str(user_id)).stream():
            w = d.to_dict() or {}
            if str(w.get("status", "")).lower() == "pending":
                total += float(w.get("amount", 0) or 0)
    except: pass
    return total

def _acc_total_withdrawn(user_id):
    # 📤 Total Withdrawal: আজ পর্যন্ত যতগুলো উইথড্র Approve হয়েছে তার যোগফল
    if not db: return 0.0
    total = 0.0
    try:
        for d in db.collection('withdrawals').where('user_id', '==', str(user_id)).stream():
            w = d.to_dict() or {}
            if str(w.get("status", "")).lower() == "approved":
                total += float(w.get("amount", 0) or 0)
    except: pass
    return total

def account_screen_text(chat_id, u_data, username=""):
    # 💳 Account স্ক্রিনের লেখা — ZONE-B (নতুন মেসেজ) ও ZONE-E (edit) দুই জায়গাতেই এক লেখা যায়
    avail = float(u_data.get('balance', 0.0) or 0)
    pend = _acc_pending_amount(chat_id)
    tot_w = _acc_total_withdrawn(chat_id)
    uname = ("@" + username) if username else f"User-{chat_id}"
    return (
        f"{PEM['user']} <b>MY ACCOUNT</b>\n"
        f"━━━━━━━━━━━━\n"
        f"{PEM['user']} <b>Username:</b> {uname}\n"
        f"{PEM['num']} <b>User ID:</b> <code>{chat_id}</code>\n"
        f"━━━━━━━━━━━━\n"
        f"{PEM['money']} <b>Balance:</b> {avail + pend:g} ৳\n"
        f"{PEM['ok']} <b>Available Balance:</b> {avail:g} ৳\n"
        f"⌛ <b>Pending Balance:</b> {pend:g} ৳\n"
        f"{PEM['upload']} <b>Total Withdrawal:</b> {tot_w:g} ৳")

def account_keyboard():
    # 💳 Account স্ক্রিনের বাটন — ভবিষ্যতে নতুন সাব-সিস্টেমের রো এখানে যোগ করুন
    return {"inline_keyboard": [
        [{"text": "📜 Transaction History", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "acc_history", "style": "primary"}],
        [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]
    ]}

def _acc_fetch_history(user_id):
    # ইউজারের শেষ ১০টা উইথড্র + ১০টা রেফার ইনকাম (নতুনটা আগে)
    # Python-side sort — Firestore composite index লাগে না
    wd_rows, ref_rows = [], []
    if not db: return wd_rows, ref_rows
    try:
        for d in db.collection('withdrawals').where('user_id', '==', str(user_id)).stream():
            w = d.to_dict() or {}
            w["_id"] = d.id
            wd_rows.append(w)
    except: pass
    try:
        for d in db.collection('refer_income').where('user_id', '==', str(user_id)).stream():
            r = d.to_dict() or {}
            r["_id"] = d.id
            ref_rows.append(r)
    except: pass
    wd_rows.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    ref_rows.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    return wd_rows[:10], ref_rows[:10]

def transaction_history_text(user_id):
    # 📜 ট্রানজেকশন হিস্ট্রি — উইথড্র (স্ট্যাটাস সহ) + রেফার ইনকাম, সব তারিখসহ
    if not db:
        return (f"📜 <b>TRANSACTION HISTORY</b>\n\n"
                f"😕 এই ফিচারটা Firebase ডেটাবেজ ছাড়া কাজ করে না।\n"
                f"firebase_credentials.json সেটআপ করুন।")
    wd_rows, ref_rows = _acc_fetch_history(user_id)
    if not wd_rows and not ref_rows:
        return f"📜 <b>TRANSACTION HISTORY</b>\n\n📭 আপনার কোনো লেনদেন পাওয়া যায়নি।"
    txt = f"📜 <b>TRANSACTION HISTORY</b>\n"
    if wd_rows:
        txt += f"\n{PEM['money']} <b>WITHDRAWALS</b> (শেষ {len(wd_rows)}টা)\n➖➖➖➖➖➖➖\n"
        for w in wd_rows:
            st = str(w.get("status", "pending")).lower()
            icon = "✅" if st == "approved" else ("❌" if st == "rejected" else "⌛")
            dt = _fmt_ts(w.get("timestamp"))
            dt_part = f" — {dt}" if dt else ""
            amt = float(w.get("amount", 0) or 0)
            txt += f"{icon} <b>{amt:g} ৳</b> — {w.get('method', '—')}{dt_part}\n"
    if ref_rows:
        txt += f"\n{PEM['gift']} <b>REFER INCOME</b> (শেষ {len(ref_rows)}টা)\n➖➖➖➖➖➖➖\n"
        for r in ref_rows:
            dt = _fmt_ts(r.get("timestamp"))
            dt_part = f" — {dt}" if dt else ""
            amt = float(r.get("amount", 0) or 0)
            txt += f"➕ <b>{amt:g} ৳</b> — ID: <code>{r.get('from_user', '—')}</code>{dt_part}\n"
    return txt

# ══════════════════════════════════════════════════════════════
# 🧩 FEATURE MODULE #2 | LINK BUTTONS (💬 Support / 👥 Community)
# ──────────────────────────────────────────────────────────────
# 👉 অ্যাডমিন: Admin Panel → Support Buttons / Community → ➕ Add Button
#    ফরম্যাট: Button Text - https://link.com
# 👉 ইউজার: SUPPORT / Community বাটন চাপলে এই বাটনগুলো দেখাবে —
#    ক্লিক করলে যুক্ত লিংক (সাপোর্ট চ্যাট / টেলিগ্রাম গ্রুপ-চ্যানেল) ওপেন হবে
# ══════════════════════════════════════════════════════════════

def _lb_parse(text):
    # "Button Text - https://link.com" পার্স করে {"text","url"} বানায়
    if "-" not in text: return None
    btn_text, btn_url = text.split("-", 1)
    btn_text, btn_url = btn_text.strip(), btn_url.strip()
    if not btn_text or not btn_url: return None
    if not (btn_url.startswith("http://") or btn_url.startswith("https://") or btn_url.startswith("tg://")):
        return None
    return {"text": btn_text[:64], "url": btn_url}

def _link_buttons_keyboard(setting_key, add_cb, del_prefix, back_cb):
    # অ্যাডমিন ম্যানেজার স্ক্রিন: প্রতিটি বাটনের 🗑 রো (ক্লিক = ডিলিট) + Add + Back
    kb = []
    for i, b in enumerate(bot_settings[setting_key]):
        kb.append([{"text": f"🗑 {b.get('text', '?')}", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"{del_prefix}{i}", "style": "danger"}])
    kb.append([{"text": "➕ Add Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": add_cb, "style": "success"},
               {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": back_cb, "style": "primary"}])
    return {"inline_keyboard": kb}

def support_admin_keyboard():
    return _link_buttons_keyboard("support_buttons", "sb_add", "sb_del_", "back_to_admin")

def community_admin_keyboard():
    return _link_buttons_keyboard("community_buttons", "cb_add", "cb_del_", "back_to_admin")

# ══════════════════════════════════════════════════════════════
# 🆕 FEATURE MODULE #3 | নতুন সিস্টেমের helper + keyboard এখানে বসান
#    (MODULE #1 এর ৩ ধাপ রেসিপি ফলো করুন)
# ══════════════════════════════════════════════════════════════

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    chat_type = msg["chat"].get("type", "private")
    
    if chat_type != "private":
        return
        
    text = msg.get("text", "")
    register_user_local(chat_id) # 🌟 Save User locally for Free Broadcasts!

    if is_user_banned(chat_id):
        send_message(chat_id, render_body_text("🚫 <b>You are banned from using this bot!</b>\nIf you think this is a mistake, please contact support."))
        return
    
    # --- REFERRAL FIX: Save inviter BEFORE Force Join ---
    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1 and parts[1].isdigit():
            inviter = int(parts[1])
            if inviter != chat_id:
                if db:
                    doc = db.collection('users').document(str(chat_id)).get()
                    if not doc.exists:
                        get_user(chat_id)
                        db.collection('users').document(str(chat_id)).update({"referred_by": inviter, "ref_paid": False})
                        
    if not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return
        
    # 🧩 মেনু বাটন (USER_MENU_BUTTONS / "Admin Panel") চাপলে চলমান
    #    ইনপুট-স্টেট রিসেট হয় — তাই নতুন বাটনের নাম USER_MENU_BUTTONS এ রাখা জরুরি
    is_main_cmd = False
    if text in USER_MENU_BUTTONS or text == "Admin Panel" or text.startswith("/start"):
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        is_main_cmd = True
    
    if chat_id in user_states and not is_main_cmd:
        state = user_states[chat_id]
        
        # --- User Management Flows ---
        if state == "wait_for_um_bal_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID! Please send a numeric User ID."), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc = db.collection('users').document(str(target_uid)).get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                current_bal = doc.to_dict().get('balance', 0.0)
                temp_data[chat_id]["target_uid"] = target_uid
                user_states[chat_id] = "wait_for_um_bal_amt"
                send_message(chat_id, render_body_text(f"✅ User found!\n💰 Current Balance: {current_bal} ৳\n\n📝 Send the amount to ADD (e.g. 50) or REMOVE (e.g. -50):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_bal_amt" and text:
            try:
                amt = float(text.strip())
                target_uid = temp_data[chat_id]["target_uid"]
                update_balance(target_uid, amt)
                send_message(chat_id, render_body_text(f"{PEM['ok']} Balance updated successfully for {target_uid}!"), reply_markup=main_menu(chat_id))
                send_message(target_uid, render_body_text(f"🔔 Your balance has been adjusted by <b>{amt} ৳</b> by an Admin."))
                del user_states[chat_id]
                del temp_data[chat_id]
            except ValueError:
                send_message(chat_id, render_body_text("❌ Invalid amount! Please send a number."), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_ban_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID!"), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc_ref = db.collection('users').document(str(target_uid))
                doc = doc_ref.get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                current_status = doc.to_dict().get("banned", False)
                new_status = not current_status
                doc_ref.update({"banned": new_status})
                
                user_banned_cache[target_uid] = {'banned': new_status, 'time': time.time()}
                
                status_text = "BANNED 🚫" if new_status else "UNBANNED ✅"
                send_message(chat_id, render_body_text(f"✅ User {target_uid} has been {status_text}!"), reply_markup=main_menu(chat_id))
                del user_states[chat_id]
                del temp_data[chat_id]
            return

        elif state == "wait_for_um_prof_uid" and text:
            target_uid_str = text.strip()
            if not target_uid_str.isdigit():
                send_message(chat_id, render_body_text("❌ Invalid ID!"), reply_markup=get_cancel_kb())
                return
            target_uid = int(target_uid_str)
            if db:
                doc = db.collection('users').document(str(target_uid)).get()
                if not doc.exists:
                    send_message(chat_id, render_body_text("❌ User not found in database!"), reply_markup=get_cancel_kb())
                    return
                data = doc.to_dict()
                is_verified = True if data.get('total_otps', 0) > 0 else data.get('verified', False)
                prof_text = f"""➖➖➖➖➖➖➖➖
👤 <b>USER PROFILE</b>
➖➖➖➖➖➖➖➖
🆔 ID: <code>{target_uid}</code>
💰 Balance: {data.get('balance', 0.0)} ৳
🤝 Total Refers: {data.get('total_refers', 0)}
🔐 Total OTPs: {data.get('total_otps', 0)}
✅ Verified: {is_verified}
🚫 Banned: {data.get('banned', False)}
➖➖➖➖➖➖➖➖"""
                kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "user_management", "style": "primary"}]]}
                send_message(chat_id, render_body_text(prof_text), reply_markup=kb)
                del user_states[chat_id]
                del temp_data[chat_id]
            return

        # --- Menu Design Flow ---
        elif state == "wait_for_menu_text" and text:
            try:
                menu_key = temp_data[chat_id]["menu_key"]
                formatted_html_text = extract_premium_html(msg)
                
                bot_settings["custom_messages"][menu_key]["text"] = formatted_html_text
                save_db()
                
                delete_message(chat_id, msg["message_id"])
                
                preview_text = render_body_text(formatted_html_text)
                success_text = f"{PEM['ok']} <b>Message Body Updated successfully!</b>\n\n🎨 <b>Editing: {menu_key.upper()}</b>\n\nPreview of current Text:\n{preview_text}"
                edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(success_text), reply_markup=menu_edit_options_keyboard(menu_key))
            except Exception as e:
                send_message(chat_id, f"❌ Error saving text: {e}")
            finally:
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
            return
            
        elif state == "wait_for_menu_btn" and text:
            try:
                menu_key = temp_data[chat_id]["menu_key"]
                if "-" in text:
                    parts = text.split("-", 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    
                    emoji_id = None
                    emoji_char = ""
                    for ent in msg.get("entities", []):
                        if ent.get("type") == "custom_emoji":
                            emoji_id = ent.get("custom_emoji_id")
                            offset = ent.get("offset", 0)
                            length = ent.get("length", 0)
                            b_text = text.encode('utf-16-le')
                            emoji_char = b_text[offset*2:(offset+length)*2].decode('utf-16-le')
                            break
                            
                    if emoji_char:
                        btn_text = btn_text.replace(emoji_char, "").strip()
                        
                    btn_data = {"text": btn_text, "url": btn_url, "style": "primary"}
                    if emoji_id:
                        btn_data["icon_custom_emoji_id"] = emoji_id
                        
                    bot_settings["custom_messages"][menu_key]["buttons"].append(btn_data)
                    save_db()
                    delete_message(chat_id, msg["message_id"])
                    edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"{PEM['gear']} <b>Edit Inline Buttons: {menu_key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(menu_key))
                else:
                    send_message(chat_id, render_body_text(f"{PEM['no']} Invalid format. Use <code>Button Text - https://link.com</code>"))
            except Exception as e:
                 pass
            finally:
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
            return

        elif state == "wait_for_broadcast":
            msg_id = msg["message_id"]
            send_message(chat_id, render_body_text(f"{PEM['ok']} Broadcast started..."))
            threading.Thread(target=broadcast_copymessage, args=(chat_id, msg_id)).start()
            del user_states[chat_id]
            return

        elif state == "wait_for_add_wm" and text:
            bot_settings["w_methods"].append(text.strip())
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_fj" and text:
            bot_settings["fj_channels"].append(parse_chat_id(text))
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:\n<i>(Note: For private links, use numeric IDs like -100...)</i>"), reply_markup=fj_settings_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return
            
        elif state == "wait_for_add_adm" and text:
            if text.isdigit():
                bot_settings["admins"].append(int(text))
                save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("👥 <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "set_dxa":
            msg_id = temp_data[chat_id]["msg_id"]
            key = temp_data[chat_id]["key"]
            try:
                if key in ["min_withdraw", "refer_reward"]: bot_settings[key] = float(text)
                else: bot_settings[key] = text
                save_db()
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())
            except:
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>\n\n❌ Invalid value!"), reply_markup=dxa_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_withdraw_amount" and text:
            msg_id_to_edit = temp_data[chat_id].get("msg_id")
            try:
                amount = float(text.strip())
                bal = temp_data[chat_id]["balance"]
                min_w = bot_settings['min_withdraw']
                
                if amount < min_w:
                    if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ Minimum withdrawal is {min_w} ৳!\n💰 Balance: {bal} ৳\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return
                if amount > bal:
                    if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ You don't have enough balance!\n💰 Balance: {bal} ৳\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return
                    
                temp_data[chat_id]["amount"] = amount
                user_states[chat_id] = "wait_for_withdraw_number"
                if msg_id_to_edit:
                    edit_message(chat_id, msg_id_to_edit, render_body_text(f"✅ Amount: {amount} ৳\n\n📱 Now send your <b>{temp_data[chat_id]['method']}</b> account number:"), reply_markup=get_cancel_kb())
            except ValueError:
                if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text("❌ Invalid amount!\n\n📝 Please send a valid number:"), reply_markup=get_cancel_kb())
            return
            
        elif state == "wait_for_withdraw_number":
            msg_id_to_edit = temp_data[chat_id].get("msg_id")
            
            method = temp_data[chat_id]["method"]
            amount = temp_data[chat_id]["amount"]
            number = text
            req_id = f"W_{str(uuid.uuid4())[:6].upper()}"
            
            first_name = msg.get("from", {}).get("first_name", "User")
            last_name = msg.get("from", {}).get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()
            
            update_balance(chat_id, -amount)
            pending_withdrawals[req_id] = {"user_id": chat_id, "amount": amount, "method": method, "number": number, "full_name": full_name}
            
            # Save to Firestore for History
            if db:
                try:
                    db.collection('withdrawals').document(req_id).set({
                        "user_id": str(chat_id),
                        "amount": amount,
                        "method": method,
                        "status": "pending",
                        "timestamp": firestore.SERVER_TIMESTAMP
                    })
                except: pass
                
            admin_msg = f"🎙 <b>NEW WITHDRAWAL REQUEST</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={chat_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amount} TK\n🍏 <b>NUMBER:</b> <code>{number}</code>\n🏦 <b>METHOD:</b> {method}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
            admin_kb = {"inline_keyboard": [[{"text": "APPROVE", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"wapp_{req_id}", "style": "success"}, {"text": "REJECT", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"wrej_{req_id}", "style": "danger"}]]}
            if bot_settings["w_group"]:
                send_message(bot_settings["w_group"], render_body_text(admin_msg), reply_markup=admin_kb)
            else:
                # গ্রুপ সেট না থাকলে রিকোয়েস্ট সরাসরি সব অ্যাডমিনের ইনবক্সে যাবে
                for adm in set(list(bot_settings.get("admins", [])) + [OWNER_ID]):
                    if adm != chat_id:
                        try: send_message(adm, render_body_text(admin_msg), reply_markup=admin_kb)
                        except: pass
            
            kb = {"inline_keyboard": [[{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]}
            success_text = f"{PEM['ok']} Your withdrawal request has been submitted!\n\n🧾 <b>Req ID:</b> {req_id}\n💰 <b>Amount:</b> {amount} ৳\n🏦 <b>Method:</b> {method}\n📱 <b>Number:</b> <code>{number}</code>"
            
            if msg_id_to_edit:
                edit_message(chat_id, msg_id_to_edit, render_body_text(success_text), reply_markup=kb)
            else:
                send_message(chat_id, render_body_text(success_text), reply_markup=kb)
                
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        # ── 💬 FEATURE MODULE #2: Support/Community বাটন ইনপুট স্টেটসমূহ ──
        elif state == "wait_for_add_sb" and text:
            # অ্যাডমিন নতুন Support বাটন পাঠিয়েছে (ফরম্যাট: Button Text - URL)
            td = temp_data.get(chat_id, {})
            msg_id_to_edit = td.get("msg_id")
            parsed = _lb_parse(text)
            if not parsed:
                err = ("❌ ফরম্যাট ভুল!\n\n📝 আবার পাঠান এই ফরম্যাটে:\n"
                       "<code>Contact Admin - https://t.me/your_admin</code>")
                if msg_id_to_edit:
                    edit_message(chat_id, msg_id_to_edit, render_body_text(err), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_sb", "style": "danger"}]]})
                return
            bot_settings["support_buttons"].append(parsed)
            save_db()
            delete_message(chat_id, msg["message_id"])
            if msg_id_to_edit:
                edit_message(chat_id, msg_id_to_edit, render_body_text(f"{PEM['ok']} <b>Button Added!</b>"), reply_markup=support_admin_keyboard())
            if chat_id in user_states: del user_states[chat_id]
            if chat_id in temp_data: del temp_data[chat_id]
            return

        elif state == "wait_for_add_cb" and text:
            # অ্যাডমিন নতুন Community বাটন পাঠিয়েছে (ফরম্যাট: Button Text - URL)
            td = temp_data.get(chat_id, {})
            msg_id_to_edit = td.get("msg_id")
            parsed = _lb_parse(text)
            if not parsed:
                err = ("❌ ফরম্যাট ভুল!\n\n📝 আবার পাঠান এই ফরম্যাটে:\n"
                       "<code>Our Channel - https://t.me/your_channel</code>")
                if msg_id_to_edit:
                    edit_message(chat_id, msg_id_to_edit, render_body_text(err), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_cb", "style": "danger"}]]})
                return
            bot_settings["community_buttons"].append(parsed)
            save_db()
            delete_message(chat_id, msg["message_id"])
            if msg_id_to_edit:
                edit_message(chat_id, msg_id_to_edit, render_body_text(f"{PEM['ok']} <b>Button Added!</b>"), reply_markup=community_admin_keyboard())
            if chat_id in user_states: del user_states[chat_id]
            if chat_id in temp_data: del temp_data[chat_id]
            return

        # ═══════════════════════════════════════════════════════════
        # 🧩 ZONE-C | INPUT STATES (ইউজার/অ্যাডমিনের টাইপ করা লেখা ধরার জায়গা)
        # ──────────────────────────────────────────────────────────
        # 👉 কোনো ফিচারে ইউজার বা অ্যাডমিনের কাছ থেকে লেখা-ইনপুট নিতে হলে
        #    (যেমন: ID, টাকার পরিমাণ, লিংক, নতুন মান) সেটি ধরার কোড এখানে
        #    বসান। এখানে ইউজার-ইনপুট ও অ্যাডমিন-ইনপুট দুটোই আসে।
        #
        # 🔗 কীভাবে কাজ করে (২ ধাপ):
        #    ধাপ-১: বাটনের কাজে (ZONE-E বা ZONE-B) লিখুন—
        #           user_states[chat_id] = "wait_for_my_feature"
        #           temp_data[chat_id]  = {"msg_id": msg_id, ...যা দরকার}
        #    ধাপ-২: নিচের TEMPLATE অনুযায়ী সেই স্টেট ধরে ইনপুট প্রসেস করুন।
        #
        # 📌 TEMPLATE (কপি করে স্টেটের নাম বদলে ব্যবহার করুন):
        # elif state == "wait_for_my_feature" and text:
        #     value = text.strip()                # ইউজার/অ্যাডমিন যা টাইপ করেছে
        #     # ...এখানে আপনার কোড (value দিয়ে কাজ)...
        #     save_db()                           # সেটিংস বদলালে অবশ্যই সেভ
        #     send_message(chat_id, render_body_text(f"{PEM['ok']} Saved!"), reply_markup=main_menu(chat_id))
        #     del user_states[chat_id]            # স্টেট পরিষ্কার করা বাধ্যতামূলক!
        #     del temp_data[chat_id]
        #     return
        # ═══════════════════════════════════════════════════════════

        elif state == "WAITING_FOR_NUMBER" and text:
            phone_number = text.strip()
            temp_data[chat_id]["phone"] = phone_number
            user_states[chat_id] = "WAITING_FOR_OTP"
            send_message(chat_id, "🔢 এখন আপনার টেলিগ্রামে আসা **OTP কোডটি** পাঠান:", reply_markup=get_cancel_kb())
            return

        elif state == "WAITING_FOR_OTP" and text:
            otp_code = text.strip()
            temp_data[chat_id]["otp"] = otp_code
            user_states[chat_id] = "WAITING_FOR_PASSWORD"
            send_message(chat_id, "🔐 যদি টু-স্টেপ ভেরিফিকেশন (2FA) পাসওয়ার্ড থাকে সেটি পাঠান, না থাকলে 'skip' লিখুন:", reply_markup=get_cancel_kb())
            return

        elif state == "WAITING_FOR_PASSWORD" and text:
            password = text.strip() if text.strip().lower() != "skip" else ""
            temp_data[chat_id]["password"] = password
            
            # এখানে আপনার অ্যাকাউন্ট সাবমিশন ও ব্যালেন্স যোগ করার মূল লজিক কাজ করবে
            
            send_message(chat_id, f"✅ আপনার অ্যাকাউন্ট সফলভাবে সাবমিট হয়েছে এবং ব্যালেন্স আপডেট করা হয়েছে!", reply_markup=main_menu(chat_id))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

    # --- Regular Commands ---
    if text.startswith("/start"):
        get_user(chat_id)
        
        # --- PROCESS PENDING REFERRAL ---
        if db:
            doc = db.collection('users').document(str(chat_id)).get()
            if doc.exists:
                u_data = doc.to_dict()
                if u_data.get("referred_by") and not u_data.get("ref_paid"):
                    inviter = u_data["referred_by"]
                    db.collection('users').document(str(chat_id)).update({"ref_paid": True})
                    reward = bot_settings.get("refer_reward", 0.2)
                    update_balance(inviter, reward)
                    db.collection('users').document(str(inviter)).update({"total_refers": firestore.Increment(1)})
                    record_refer_income(inviter, chat_id, reward)
                    ref_msg = (
                        f"{PEM['gift']} <b>New Referral !</b>\n"
                        f"------------------\n"
                        f"🔥 <b>You Received {reward} TK</b>\n"
                        f"------------------\n"
                        f"{PEM['user']} <b>From User ID:</b> <code>{chat_id}</code>"
                    )
                    send_message(inviter, render_body_text(ref_msg))
                    
        c_msg = bot_settings["custom_messages"].get("start", {})
        txt = render_body_text(c_msg.get("text", f"{PEM['hi']} Welcome!"))
        kb = []
        for b in c_msg.get("buttons", []):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        
        if kb:
            send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})
            send_message(chat_id, render_body_text(f"{PEM['gear']} Navigation Menu:"), reply_markup=main_menu(chat_id))
        else:
            send_message(chat_id, txt, reply_markup=main_menu(chat_id))
            
    elif text == "Refer":
        u_data = get_user(chat_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        c_msg = bot_settings["custom_messages"].get("refer", {})
        
        raw_txt = c_msg.get("text", f"{PEM['gift']} Refer").replace("{ref_link}", ref_link).replace("{total_ref}", str(u_data.get('total_refers', 0))).replace("{ref_reward}", str(bot_settings['refer_reward']))
        txt = render_body_text(raw_txt)
        
        kb = [[{"text": "COPY LINK", "icon_custom_emoji_id": "5192739271886282680", "copy_text": {"text": ref_link}, "style": "success"}]]
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "CLOSE", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif text == "WITHDRAWAL":
        if not bot_settings["withdraw_on"]:
            send_message(chat_id, render_body_text(f"{PEM['no']} Withdrawals are currently disabled."))
            return
        
        u_data = get_user(chat_id)
        bal = u_data.get('balance', 0.0)
        
        c_msg = bot_settings["custom_messages"].get("withdrawal", {})
        raw_txt = c_msg.get("text", "Withdrawal").replace("{bal}", str(bal)).replace("{total_otp}", str(u_data.get('total_otps', 0))).replace("{total_ref}", str(u_data.get('total_refers', 0))).replace("{min_w}", str(bot_settings['min_withdraw']))
        txt = render_body_text(raw_txt)
        
        kb = []
        for m in bot_settings["w_methods"]:
            kb.append([{"text": m.strip(), "icon_custom_emoji_id": "5190899075968441286", "callback_data": f"sel_wm_{m.strip()}", "style": "primary"}])
        
        for b in c_msg.get("buttons", []): 
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Cancel", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif text == "Admin Panel" and is_admin(chat_id):
        send_message(chat_id, get_admin_text(), reply_markup=admin_panel_keyboard())

    elif text == "SUPPORT":
        # 🧩 FEATURE MODULE #2 — Support বাটনগুলো (অ্যাডমিন সেট করে)
        c_msg = bot_settings["custom_messages"].get("support", {})
        txt = render_body_text(c_msg.get("text", f"{PEM['msg']} Support"))
        if not txt.strip(): txt = render_body_text(f"{PEM['msg']} Support")
        kb = []
        for b in bot_settings.get("support_buttons", []):
            kb.append([{"text": b.get("text", "Support"), "icon_custom_emoji_id": "5337302974806922068", "url": b.get("url", ""), "style": "success"}])
        if not kb:
            sup_link = bot_settings.get("support_link", "")
            if sup_link:
                kb.append([{"text": "Contact Support", "icon_custom_emoji_id": "5337302974806922068", "url": sup_link, "style": "success"}])
        for b in c_msg.get("buttons", []):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb} if kb else None)

    elif text == "Community":
        # 🧩 FEATURE MODULE #2 — Community বাটনগুলো (অ্যাডমিন সেট করে)
        c_msg = bot_settings["custom_messages"].get("community", {})
        txt = render_body_text(c_msg.get("text", f"{PEM['user']} Community"))
        com_btns = bot_settings.get("community_buttons", [])
        kb = []
        for b in com_btns:
            kb.append([{"text": b.get("text", "Join"), "icon_custom_emoji_id": "5352980533150259581", "url": b.get("url", ""), "style": "primary"}])
        if not com_btns:
            txt += "\n\n😕 এখনো কোনো কমিউনিটি লিংক যোগ করা হয়েছে না!"
        for b in c_msg.get("buttons", []):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})
        
    elif text == "🛒 tg sell":
        country_data = db.get("settings", {}).get("country_prices", {})
        if not country_data:
            send_message(chat_id, "❌ বর্তমানে কোনো কান্ট্রি এভেলেবল নেই।")
            return

        kb = []
        for code, info in country_data.items():
            btn_text = f"{info['country']} ({code}) = {info['price']}$"
            kb.append([{"text": btn_text, "callback_data": f"select_country:{code}"}])
        
        send_message(chat_id, "<b>প্রথমে আপনার কান্ট্রি কোড সিলেক্ট করুন:</b>", reply_markup={"inline_keyboard": kb})
    
    elif text == "💳 Account":
        # 🧩 FEATURE MODULE #1 — Account স্ক্রিন (ব্যালেন্স + Transaction History)
        u_data = get_user(chat_id)
        uname = msg.get("from", {}).get("username", "")
        send_message(chat_id, render_body_text(account_screen_text(chat_id, u_data, uname)), reply_markup=account_keyboard())

    # ═══════════════════════════════════════════════════════════════
    # 🧩 ZONE-B | USER BUTTON ACTIONS (ইউজার কিবোর্ড বাটনের "কাজ" এখানে)
    # ──────────────────────────────────────────────────────────────
    # 👉 ZONE-A (main_menu) তে যোগ করা প্রতিটি বাটনের কাজ এখানে বসান।
    #    শর্ত হুবহু বাটনের নামের সাথে মিলতে হবে: text == "বাটনের নাম"
    #    নতুন elif সবসময় এই চেইনের একদম শেষে যোগ করুন।
    #
    # 📌 TEMPLATE-১ — তথ্য/স্ক্রিন দেখায় (ইনপুট লাগে না):
    # elif text == "🆕 MY NEW BUTTON":
    #     u_data = get_user(chat_id)
    #     send_message(chat_id, render_body_text(
    #         f"{PEM['user']} <b>My New Feature</b>\n"
    #         f"━━━━━━━━━━━━\n"
    #         f"💰 Balance: {u_data.get('balance', 0.0)} ৳\n"
    #         f"🤝 Refers: {u_data.get('total_refers', 0)}"),
    #         reply_markup=main_menu(chat_id))
    #
    # 📌 TEMPLATE-২ — ইউজারের কাছ থেকে ইনপুট নিতে হলে (লেখা ধরা হবে ZONE-C তে):
    # elif text == "🆕 MY INPUT BUTTON":
    #     user_states[chat_id] = "wait_for_my_feature"
    #     temp_data[chat_id] = {}
    #     send_message(chat_id, render_body_text("📝 আপনার তথ্য পাঠান:"), reply_markup=get_cancel_kb())
    #
    # 📌 TEMPLATE-৩ — শুধু অ্যাডমিনের কিবোর্ড বাটন (ZONE-A2 এর সাথে যুক্ত):
    # elif text == "🆕 ADMIN TOOL" and is_admin(chat_id):
    #     send_message(chat_id, render_body_text("🛠 <b>Admin Tool</b>"), reply_markup=main_menu(chat_id))
    # ═══════════════════════════════════════════════════════════════

def handle_callback(call):
    chat_id = call["message"]["chat"]["id"]
    chat_type = call["message"]["chat"].get("type", "private")
    data = call.get("data", "")

    # 🌟 Button Loading Fix: বাটন চাপার সাথে সাথেই টেলিগ্রামকে Response দিয়ে দেওয়া, যাতে বাটন আটকে না থাকে!
    try: threading.Thread(target=answer_callback, args=(call["id"],)).start()
    except: pass

    if chat_type != "private" and not (data.startswith("wapp_") or data.startswith("wrej_")):
        return

    msg_id = call["message"]["message_id"]

    if chat_type == "private":
        if is_user_banned(chat_id):
            answer_callback(call["id"], "🚫 You are banned from using this bot!", show_alert=True)
            return

        if not check_force_join(chat_id) and data != "check_fj":
            send_force_join_msg(chat_id)
            return

    if data == "check_fj":
        if check_force_join(chat_id):
            delete_message(chat_id, msg_id)
            send_message(chat_id, render_body_text(f"{PEM['ok']} Thanks for joining! You can now use the bot."), reply_markup=main_menu(chat_id))
            
            # --- PROCESS PENDING REFERRAL ---
            if db:
                doc = db.collection('users').document(str(chat_id)).get()
                if doc.exists:
                    u_data = doc.to_dict()
                    if u_data.get("referred_by") and not u_data.get("ref_paid"):
                        inviter = u_data["referred_by"]
                        db.collection('users').document(str(chat_id)).update({"ref_paid": True})
                        reward = bot_settings.get("refer_reward", 0.2)
                        update_balance(inviter, reward)
                        db.collection('users').document(str(inviter)).update({"total_refers": firestore.Increment(1)})
                        record_refer_income(inviter, chat_id, reward)
                        ref_msg = (
                            f"{PEM['gift']} <b>New Referral !</b>\n"
                            f"------------------\n"
                            f"🔥 <b>You Received {reward} TK</b>\n"
                            f"------------------\n"
                            f"{PEM['user']} <b>From User ID:</b> <code>{chat_id}</code>"
                        )
                        send_message(inviter, render_body_text(ref_msg))
        else:
            answer_callback(call["id"], "❌ You haven't joined all channels yet!", show_alert=True)
        return

    if data == "close_msg":
        delete_message(chat_id, msg_id)
        
    elif data == "cancel_state":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        delete_message(chat_id, msg_id)

    elif data == "cancel_dxa_edit":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())
        
    elif data == "dummy_alert":
        answer_callback(call["id"], "This feature will be added later!", show_alert=True)
        
    # --- User Management Flows Integration ---
    elif data == "user_management":
        edit_message(chat_id, msg_id, get_user_management_text(), reply_markup=user_management_keyboard())

    elif data == "um_manage_balance":
        user_states[chat_id] = "wait_for_um_bal_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to Manage Balance:"), reply_markup=get_cancel_kb())
        
    elif data == "um_ban_unban":
        user_states[chat_id] = "wait_for_um_ban_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to Ban or Unban:"), reply_markup=get_cancel_kb())

    elif data == "um_user_profile":
        user_states[chat_id] = "wait_for_um_prof_uid"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID to View Profile:"), reply_markup=get_cancel_kb())

    # --- Menu Design Integration ---
    elif data == "menu_design_list":
        edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Menu Design Editor</b>\n\nSelect a menu block to edit its Body Text and Inline Buttons. You can use Premium Emojis too!"), reply_markup=menu_design_list_keyboard())

    elif data == "md_reset_defaults":
        bot_settings["custom_messages"] = DEFAULT_CUSTOM_MESSAGES.copy()
        save_db()
        answer_callback(call["id"], "✅ Resetted to Premium Defaults!", show_alert=True)

    elif data.startswith("md_edit_"):
        answer_callback(call["id"])
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        key = data.replace("md_edit_", "")
        cm_text = render_body_text(bot_settings["custom_messages"].get(key, {}).get("text", "..."))
        try:
            edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Editing: {key.upper()}</b>\n\nPreview of current Text:\n{cm_text}"), reply_markup=menu_edit_options_keyboard(key))
        except: pass

    elif data.startswith("md_text_"):
        key = data.replace("md_text_", "")
        user_states[chat_id] = "wait_for_menu_text"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"📝 <b>Edit Body: {key.upper()}</b>\n\nSend the new text. You can use Premium Emojis directly here.\n(Use standard HTML like <b>bold</b>, <i>italic</i> for formatting)"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{key}", "style": "danger"}]]})

    elif data.startswith("md_btns_"):
        answer_callback(call["id"]) 
        if chat_id in user_states: del user_states[chat_id] 
        if chat_id in temp_data: del temp_data[chat_id]
        key = data.replace("md_btns_", "")
        try:
            edit_message(chat_id, msg_id, render_body_text(f"⚙️ <b>Edit Inline Buttons: {key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(key))
        except: pass

    elif data.startswith("md_addbtn_"):
        key = data.replace("md_addbtn_", "")
        user_states[chat_id] = "wait_for_menu_btn"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"➕ <b>Add Button: {key.upper()}</b>\n\nSend custom button in this format:\n<code>Button Text - https://link.com</code>\n\n<i>(Only normal Emojis supported here!)</i>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_btns_{key}", "style": "danger"}]]})

    elif data.startswith("md_delbtn_"):
        parts = data.split("_")
        key = parts[2]
        b_idx = int(parts[3])
        if b_idx < len(bot_settings["custom_messages"][key]["buttons"]):
            del bot_settings["custom_messages"][key]["buttons"][b_idx]
            save_db()
            answer_callback(call["id"], "✅ Button Deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"⚙️ <b>Edit Inline Buttons: {key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(key))

    elif data.startswith("sel_wm_"):
        method = data.replace("sel_wm_", "")
        bal = get_user(chat_id).get('balance', 0.0)
        min_w = bot_settings['min_withdraw']
        
        if bal < min_w:
            answer_callback(call["id"], f"❌ আপনার ব্যালেন্স অপর্যাপ্ত! মিনিমাম {min_w} ৳ প্রয়োজন।", show_alert=True)
            return
            
        temp_data[chat_id] = {"method": method, "balance": bal, "msg_id": msg_id}
        user_states[chat_id] = "wait_for_withdraw_amount"
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} Method: {method}\n💰 Available Balance: {bal} ৳\n\n📝 Enter the amount you want to withdraw (Min: {min_w} ৳):"), reply_markup=get_cancel_kb())
        answer_callback(call["id"])

    elif data == "broadcast_msg":
        user_states[chat_id] = "wait_for_broadcast"
        edit_message(chat_id, msg_id, render_body_text("📢 <b>Broadcast Mode</b>\n\nSend the message you want to broadcast (Text, Photo, Video, File etc)."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]})

    elif data == "lb_main":
        txt = f"━━━━━━━━━━━━━━━\n《 {PEM['admin']} <b>LEADER BOARD MENU</b> 》\n━━━━━━━━━━━━━━━\n<i>Select a category to view the top performers or history.</i>\n━━━━━━━━━━━━━━━"
        kb = [
            [{"text": "Top Referrers", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "lb_top_refs", "style": "primary"}],
            [{"text": "Withdrawal History", "icon_custom_emoji_id": "5348469219761626211", "callback_data": "lb_w_history", "style": "success"}],
            [{"text": "Back to Admin", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
        ]
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("lb_"):
        sub = data.replace("lb_", "")
        edit_message(chat_id, msg_id, render_body_text("⌛ <i>Fetching Data...</i>"))
        
        num_map = {"1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣", "0": "0️⃣"}
        def get_p_num(n): return "".join([num_map.get(c, c) for c in str(n)])
        
        try:
            if sub == "top_refs":
                title, field, limit, icon = "TOP 5 REFERRERS", "total_refers", 5, PEM.get('user', '👥')
                users = db.collection('users').order_by(field, direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for u in users:
                    d = u.to_dict()
                    if d.get(field, 0) > 0:
                        p = "└" if count == limit else "├"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "└ <i>No data found.</i>\n"

            elif sub == "w_history":
                title, limit, icon = "LAST 10 WITHDRAWALS", 10, PEM.get('money', '💸')
                ws = db.collection('withdrawals').order_by('timestamp', direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for w in ws:
                    d = w.to_dict()
                    s = str(d.get('status','Pending')).lower()
                    stat_icon = PEM.get('ok','✅') if s in ["approved","success"] else PEM.get('no','❌') if s=="rejected" else "⏳"
                    uid = d.get('user_id','User')
                    p = "└" if count == limit else "├"
                    res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={uid}'>{uid}</a> ➔ <b>{d.get('amount',0)}৳</b> {stat_icon}\n"
                    count += 1
                if not res_txt: res_txt = "└ <i>No history found.</i>\n"

            final_msg = f"━━━━━━━━━━━━━━━\n{icon} <b>{title}</b>\n━━━━━━━━━━━━━━━\n{res_txt}━━━━━━━━━━━━━━━"
            kb = [[{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": data, "style": "success"}, {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]
            edit_message(chat_id, msg_id, render_body_text(final_msg), reply_markup={"inline_keyboard": kb})

        except Exception as e:
            edit_message(chat_id, msg_id, render_body_text(f"❌ Error: {e}"), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]})

    elif data == "back_to_admin":
        if chat_id in user_states: del user_states[chat_id]
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard())
        
    elif data == "system_settings":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>System Settings</b>\nManage advanced bot configurations below:"), reply_markup=system_settings_keyboard())

    elif data == "manage_fj":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "toggle_fj":
        bot_settings["fj_on"] = not bot_settings["fj_on"]
        save_db()
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "add_fj":
        user_states[chat_id] = "wait_for_add_fj"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send Channel Username or Invite Link:\n<i>(Note: For private channels, use the numeric ID like -100...)</i>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_fj", "style": "danger"}]]})

    elif data.startswith("del_fj_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fj_channels"]):
            del bot_settings["fj_channels"][idx]
            save_db()
            answer_callback(call["id"], "✅ Channel deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>FORCE JOIN SYSTEM</b>\nManage channels below:"), reply_markup=fj_settings_keyboard())

    elif data == "manage_admins":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['user']} <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())

    elif data == "add_adm":
        user_states[chat_id] = "wait_for_add_adm"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the User ID of the new Admin:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_admins", "style": "danger"}]]})

    elif data.startswith("del_adm_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["admins"]):
            del bot_settings["admins"][idx]
            save_db()
            answer_callback(call["id"], "✅ Admin deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['user']} <b>ADMIN MANAGEMENT</b>\nManage your bot admins below:"), reply_markup=admin_settings_keyboard())

    elif data == "dxa_control":
        if chat_id in user_states: del user_states[chat_id]
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())

    elif data == "dxa_toggle_w":
        bot_settings["withdraw_on"] = not bot_settings["withdraw_on"]
        save_db()
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())

    elif data == "manage_w_methods":
        edit_message(chat_id, msg_id, render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())

    elif data == "add_wm":
        user_states[chat_id] = "wait_for_add_wm"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the name of the new Withdrawal Method:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_w_methods", "style": "danger"}]]})

    elif data.startswith("del_wm_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["w_methods"]):
            del bot_settings["w_methods"][idx]
            save_db()
            answer_callback(call["id"], "✅ Method deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your withdrawal methods below:"), reply_markup=w_methods_keyboard())

    elif data.startswith("dxa_"):
        key = data.replace("dxa_", "")
        key_map = {"min_w": "min_withdraw", "ref_r": "refer_reward", "sup_link": "support_link", "w_group": "w_group"}
        if key in key_map:
            temp_data[chat_id] = {"msg_id": msg_id, "key": key_map[key]}
            user_states[chat_id] = "set_dxa"
            cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_dxa_edit", "style": "danger"}]]}
            edit_message(chat_id, msg_id, render_body_text(f"📝 Please send the new value for <code>{key_map[key]}</code>:"), reply_markup=cancel_kb)
            answer_callback(call["id"])

    elif data.startswith("wapp_") or data.startswith("wrej_"):
        # অ্যাডমিন চেক (User ID চেক করতে হবে)
        user_id_clicked = call["from"]["id"]
        if not is_admin(user_id_clicked):
            answer_callback(call["id"], "🚫 Only Bot Admins can process withdrawals!", show_alert=True)
            return
            
        action = "APPROVE" if data.startswith("wapp_") else "REJECT"
        req_id = data.replace("wapp_", "").replace("wrej_", "")
        
        if req_id in pending_withdrawals:
            req_data = pending_withdrawals[req_id]
            u_id, amt = req_data["user_id"], req_data["amount"]
            num = req_data["number"]
            full_name = req_data.get("full_name", u_id)
            
            if action == "APPROVE" and len(num) >= 7:
                masked_num = f"{num[:4]}❖DXA❖{num[-3:]}"
            else:
                masked_num = num
            
            status_text = "APPROVED" if action == "APPROVE" else "REJECTED"
            emoji_icon_id = "5352694861990501856" if action == "APPROVE" else "5420130255174145507"
            new_text = f"🎙 <b>WITHDRAWAL {status_text}</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={u_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amt} TK\n🍏 <b>NUMBER:</b> <code>{masked_num}</code>\n🏦 <b>METHOD:</b> {req_data['method']}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
            
            kb = {"inline_keyboard": [[{"text": status_text, "icon_custom_emoji_id": emoji_icon_id, "callback_data": "ignore", "style": "success" if action == "APPROVE" else "danger"}]]}
            edit_message(chat_id, msg_id, render_body_text(new_text), reply_markup=kb)
            
            if action == "REJECT":
                update_balance(u_id, amt) 
                send_message(u_id, render_body_text(f"❌ Your {amt} TK withdrawal request was rejected. Balance refunded."))
            else:
                send_message(u_id, render_body_text(f"{PEM['ok']} Your {amt} TK withdrawal request has been paid successfully!"))
            
            if db:
                try: db.collection('withdrawals').document(req_id).update({"status": "approved" if action == "APPROVE" else "rejected"})
                except: pass
                
            del pending_withdrawals[req_id]
        else:
            answer_callback(call["id"], "❌ Request already processed!", show_alert=True)

    # ═══════════════════════════════════════════════════════════════
    # 🧩 ZONE-E | INLINE BUTTON ACTIONS (ইনলাইন বাটনের "কাজ" এখানে)
    # ──────────────────────────────────────────────────────────────
    # 👉 ZONE-D / ZONE-D2 / ইউজার-সাইড — যেকোনো ইনলাইন বাটনের কাজ এখানে
    #    বসান (ইউজার ও অ্যাডমিন দুটোই)। নতুন elif সবসময় শেষে যোগ করুন।
    #
    # ⚠️ নিয়ম-১: নির্দিষ্ট ম্যাচ (data == "adm_xxx") আগে রাখুন, prefix
    #    ম্যাচ (data.startswith("xxx_")) পরে — নাহলে নির্দিষ্ট বাটন আটকে যাবে।
    # ⚠️ নিয়ম-২: অ্যাডমিন-অনলি স্ক্রিন হলে handler-এর শুরুতে চেক দিন:
    #    if not is_admin(chat_id):
    #         answer_callback(call["id"], "🚫 Admins only!", show_alert=True); return
    #
    # 📌 TEMPLATE-১ — অ্যাডমিন প্যানেলের নতুন স্ক্রিন (ZONE-D বাটনের কাজ):
    # elif data == "adm_my_feature":
    #     txt = f"🆕 <b>MY ADMIN FEATURE</b>\n\nএখানে আপনার তথ্য/স্ট্যাটাস দেখুন..."
    #     kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176",
    #            "callback_data": "back_to_admin", "style": "danger"}]]}
    #     edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
    #
    # 📌 TEMPLATE-২ — ইনপুট নেওয়া শুরু করে (লেখা ধরা হবে ZONE-C তে):
    # elif data == "adm_my_feature_input":
    #     user_states[chat_id] = "wait_for_my_feature"
    #     temp_data[chat_id] = {"msg_id": msg_id}
    #     edit_message(chat_id, msg_id, render_body_text("📝 নতুন মান পাঠান:"), reply_markup=get_cancel_kb())
    #
    # 📌 TEMPLATE-৩ — সেটিংস টগল (ON/OFF স্যুইচ) (ZONE-D2 বাটনের কাজ):
    # elif data == "ss_my_toggle":
    #     bot_settings["my_toggle"] = not bot_settings.get("my_toggle", False)
    #     save_db()
    #     edit_message(chat_id, msg_id, render_body_text("⚙️ <b>System Settings</b>"), reply_markup=system_settings_keyboard())
    # ═══════════════════════════════════════════════════════════════
    elif data == "adm_tgsell_set":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        txt = "🛒 <b>Tg Sell Settings</b>\n\nএখানে আপনি কান্ট্রি এবং প্রতি অ্যাকাউন্টের প্রাইস ম্যানেজ করতে পারবেন।"
        kb = {"inline_keyboard": [
            [{"text": "➕ Add/Update Country Price", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "adm_add_country_price", "style": "success"}],
            [{"text": "Back to Admin", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
        ]}
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
        
    # ─────────────────────────────────────────────────────────────
    # 🧩 FEATURE MODULE #1 হুক | ACCOUNT + TRANSACTION HISTORY (ইউজার সাইড)
    # ─────────────────────────────────────────────────────────────
    elif data.startswith("select_country:"):
        country_code = data.split(":")[1]
        user_states[chat_id] = "WAITING_FOR_NUMBER"
        temp_data[chat_id] = {"country": country_code}
        edit_message(chat_id, msg_id, render_body_text(f"✅ আপনি কান্ট্রি সিলেক্ট করেছেন: <b>{country_code}</b>\n\n📱 এখন আপনার টেলিগ্রাম অ্যাকাউন্ট খোলার নাম্বারটি পাঠান:"), reply_markup=get_cancel_kb())
           
    elif data == "acc_history":
        # 📜 ট্রানজেকশন হিস্ট্রি — উইথড্র (✅/⌛/❌) + রেফার ইনকাম, তারিখসহ
        edit_message(chat_id, msg_id, render_body_text(transaction_history_text(chat_id)),
                     reply_markup={"inline_keyboard": [[{"text": "🔙 Back to Account", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_account", "style": "primary"}]]})

    elif data == "back_to_account":
        u_data = get_user(chat_id)
        uname = call.get("from", {}).get("username", "")
        edit_message(chat_id, msg_id, render_body_text(account_screen_text(chat_id, u_data, uname)), reply_markup=account_keyboard())

    # ─────────────────────────────────────────────────────────────
    # 🧩 FEATURE MODULE #2 হুক | SUPPORT / COMMUNITY BUTTONS (অ্যাডমিন ম্যানেজার)
    # ─────────────────────────────────────────────────────────────
    elif data == "manage_sb":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        txt = (f"💬 <b>SUPPORT BUTTONS</b>\n\n"
               f"📊 <b>Total Buttons:</b> {len(bot_settings['support_buttons'])}\n\n"
               f"👉 ইউজার SUPPORT চাপলে এই বাটনগুলো দেখাবে\n"
               f"👉 ডিলিট করতে বাটনের 🗑 এ ক্লিক করুন\n"
               f"👉 নতুন বাটন যোগ করতে ➕ Add Button")
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=support_admin_keyboard())

    elif data == "sb_add":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        if len(bot_settings["support_buttons"]) >= MAX_LINK_BUTTONS:
            answer_callback(call["id"], f"❌ Maximum {MAX_LINK_BUTTONS} buttons!", show_alert=True)
            return
        user_states[chat_id] = "wait_for_add_sb"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(
            "📝 <b>নতুন Support বাটন এই ফরম্যাটে পাঠান:</b>\n\n"
            "<code>Contact Admin - https://t.me/your_admin</code>\n\n"
            "👉 ফরম্যাট: বাটনের নাম - লিংক (http/https সহ)"),
            reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_sb", "style": "danger"}]]})

    elif data.startswith("sb_del_"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        try: idx = int(data.split("_")[2])
        except: return
        if 0 <= idx < len(bot_settings["support_buttons"]):
            removed = bot_settings["support_buttons"].pop(idx)
            save_db()
            answer_callback(call["id"], f"✅ Deleted: {removed.get('text', '')}", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"💬 <b>SUPPORT BUTTONS</b>\n\n📊 <b>Total Buttons:</b> {len(bot_settings['support_buttons'])}"), reply_markup=support_admin_keyboard())

    elif data == "manage_cb":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        txt = (f"👥 <b>COMMUNITY BUTTONS</b>\n\n"
               f"📊 <b>Total Buttons:</b> {len(bot_settings['community_buttons'])}\n\n"
               f"👉 ইউজার Community চাপলে এই বাটনগুলো দেখাবে\n"
               f"👉 বাটনে টেলিগ্রাম গ্রুপ/চ্যানেলের লিংক যুক্ত হবে\n"
               f"👉 ডিলিট করতে বাটনের 🗑 এ ক্লিক করুন")
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=community_admin_keyboard())

    elif data == "cb_add":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        if len(bot_settings["community_buttons"]) >= MAX_LINK_BUTTONS:
            answer_callback(call["id"], f"❌ Maximum {MAX_LINK_BUTTONS} buttons!", show_alert=True)
            return
        user_states[chat_id] = "wait_for_add_cb"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(
            "📝 <b>নতুন Community বাটন এই ফরম্যাটে পাঠান:</b>\n\n"
            "<code>Our Channel - https://t.me/your_channel</code>\n\n"
            "👉 ফরম্যাট: বাটনের নাম - টেলিগ্রাম গ্রুপ/চ্যানেল লিংক"),
            reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_cb", "style": "danger"}]]})

    elif data.startswith("cb_del_"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True)
            return
        try: idx = int(data.split("_")[2])
        except: return
        if 0 <= idx < len(bot_settings["community_buttons"]):
            removed = bot_settings["community_buttons"].pop(idx)
            save_db()
            answer_callback(call["id"], f"✅ Deleted: {removed.get('text', '')}", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"👥 <b>COMMUNITY BUTTONS</b>\n\n📊 <b>Total Buttons:</b> {len(bot_settings['community_buttons'])}"), reply_markup=community_admin_keyboard())

# ==========================================
# Polling Loop
# ==========================================
def main():
    global BOT_USERNAME
    res = api_call("getMe")
    if res.get("ok"): BOT_USERNAME = res["result"]["username"]
    print(f"🤖 Bot is starting... @{BOT_USERNAME}")
    
    # 🌟 PRO-LEVEL FAST SYSTEM: 500 Workers Pool
    executor = ThreadPoolExecutor(max_workers=500)
    
    offset = None
    while True:
        try:
            updates = api_call(f"getUpdates?timeout=50&offset={offset}")
            if updates and "result" in updates:
                for update in updates["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update: 
                        executor.submit(handle_message, update["message"])
                    elif "callback_query" in update: 
                        executor.submit(handle_callback, update["callback_query"])
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    main()    
