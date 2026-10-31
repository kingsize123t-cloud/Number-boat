# ============================================================================
#                        NUMBER BOAT BOT  —  main.py
#              Telegram SMS / OTP Bot (raw Telegram API + requests)
# ----------------------------------------------------------------------------
#  STRUCTURE MAP: every section below is marked with a matching banner inside
#  the file. Behavior is 100% identical to the original — only comments were
#  added (verified by AST equality before shipping).
#
#  NOTE ON THE PATCH LAYER: this file intentionally contains later
#  re-definitions of some functions (main_menu, handle_message,
#  handle_callback, _api_monitor_thread, ...). The earlier versions are NOT
#  dead code — they are captured into `_original_*` variables and wrapped or
#  delegated by the newer versions. Do NOT delete either side.
# ============================================================================
#
# TABLE OF CONTENTS
# -----------------

#   [01]  L62      MODULE IMPORTS & ENV LOADING
#   [02]  L124     CONFIGURATION — TOKEN, OWNER & PATHS
#   [03]  L145     PREMIUM EMOJI ASSETS & DEFAULT MESSAGE / CARD TEMPLATES
#   [04]  L315     FIREBASE INIT (OPTIONAL — FALLS BACK TO LOCAL JSON)
#   [05]  L370     BOT SETTINGS & ENV DEFAULTS
#   [06]  L452     RUNTIME STATE — STOCK, TRAFFIC, SESSIONS
#   [07]  L471     PROVIDER PANEL SESSIONS & CDR FETCH
#   [08]  L579     DATABASE & PERSISTENCE (LOCAL JSON + FIRESTORE)
#   [09]  L820     USER RUNTIME STATE, TEMP-MAIL & TIMEOUT CONFIG
#   [10]  L851     TELEGRAM API HELPERS & BUTTON EMOJI OVERRIDES
#   [11]  L983     USERS SYNC & REGISTRATION
#   [12]  L1015    BROADCASTING ENGINE
#   [13]  L1076    TEXT & BRAND RENDERING
#   [14]  L1198    PREMIUM MEMBERSHIP SYSTEM
#   [15]  L1492    PREMIUM CALLBACK CHECKS & CUSTOM EMOJI PACK TOOLS
#   [16]  L1651    NUMBER, FLAG & REWARD UTILITIES
#   [17]  L1702    FACEBOOK TOOLS — RECORDS & SESSION HELPERS
#   [18]  L1986    SERVICE & LANGUAGE DETECTION
#   [19]  L2093    OTP CARD TEMPLATES & GROUP FORWARDING
#   [20]  L2387    ACCESS CONTROL — ADMIN, FORCE-JOIN, BANS
#   [21]  L2436    OTP EXTRACTION & PANEL RESPONSE PARSING
#   [22]  L2884    USER ACCOUNTS — BALANCE & REFERRALS
#   [23]  L2943    USER MENUS & KEYBOARDS
#   [24]  L3123    NUMBER RESULTS & DELIVERY
#   [25]  L3365    STOCK ROUTES & ALLOCATION
#   [26]  L3511    USER FLOW SCREENS
#   [27]  L3565    FACEBOOK TOOLS — PLANS, PAYMENTS & ADMIN
#   [28]  L4503    STOCK SCREENS
#   [29]  L4599    PROFILE, BALANCE, WITHDRAWAL & SUPPORT SCREENS
#   [30]  L4729    TEMP MAIL SYSTEM
#   [31]  L5119    USER TEXT & CALLBACK ROUTING
#   [32]  L5275    ADMIN PANEL & SETTINGS KEYBOARDS
#   [33]  L5783    LIVE TRAFFIC UI & FORWARDER
#   [34]  L5955    UPLOAD EMOJI FLOW & BATCH FINALIZE
#   [35]  L6101    CORE HANDLER — handle_message (V1, wrapped by patch layer)
#   [36]  L7662    NUMBER EXPIRY HELPER
#   [37]  L7694    CORE HANDLER — handle_callback (V1, wrapped by patch layer)
#   [38]  L9343    OTP POLLING & PROVIDER SMS LISTENERS
#   [39]  L9596    MK / NP API PROVIDER LAYER (V1)
#   [40]  L10187   PATCH LAYER — V2 WRAPPERS (intentionally override earlier defs)
#   [41]  L11574   SAFE UPDATE WRAPPER & UPDATE NOTICES
#   [42]  L11653   DYNAMIC SETTINGS MONITOR
#   [43]  L11720   ENTRY POINT — main()
#
#==============================================================================
#  [01]  MODULE IMPORTS & ENV LOADING
#==============================================================================
import requests
import time
import json
import io
import sys
import subprocess
import os
import base64
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    # Firebase is optional; the bot can run with local JSON persistence.
    firebase_admin = None
    credentials = None
    firestore = None
import uuid
import threading
import random
import re
import html
import textwrap
try:
    import pyotp
except ImportError:
    pyotp = None
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, quote, unquote

#==============================================================================
#  INLINE MODULE: premium_emoji (was a separate premium_emoji.py file)
#  Merged here so a Railway deployment needs ONLY this single main.py file.
#  Content is byte-identical to the standalone module; html/re are already
#  imported above. The standalone file (if present) is simply unused.
#==============================================================================
LOCAL_DIGIT_TRANSLATION = str.maketrans(
    "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9",
    "012345678901234567890123456789",
)

ID_RE = re.compile(r"^[0-9]+$")
PE_SINGLE_RE = re.compile(r":pe:([0-9\u09e6-\u09ef\u0660-\u0669\u06f0-\u06f9]+):")
PE_BRACE_RE = re.compile(r"\{([^{}]+)\}")
TG_EMOJI_TAG_RE = re.compile(
    r'<tg-emoji\s+emoji-id=["\']([^"\']+)["\']>(.*?)</tg-emoji>',
    re.DOTALL | re.IGNORECASE,
)
ANGLE_EMOJI_ID_RE = re.compile(r"<([0-9\u09e6-\u09ef\u0660-\u0669\u06f0-\u06f9]+)>")


def normalize_local_digits(value):
    """Convert Bengali, Arabic and Persian digits to ASCII digits."""
    return str(value or "").translate(LOCAL_DIGIT_TRANSLATION)


def _canonical_id(value):
    value = normalize_local_digits(value).strip()
    return value if ID_RE.fullmatch(value) else None


def _unique(values):
    result = []
    seen = set()
    for value in values:
        canonical = _canonical_id(value)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def premium_emoji_ids_in_text(text):
    """Return explicit IDs in {id,id,} and :pe:id: syntax, once each."""
    text = normalize_local_digits(text)
    found = []
    for match in PE_BRACE_RE.finditer(text):
        content = match.group(1).strip()
        # Only treat a brace block as Premium Emoji syntax when every non-empty
        # item is numeric. This preserves {first_name}, {brand_name}, etc.
        items = [item.strip() for item in content.split(",") if item.strip()]
        if items and all(ID_RE.fullmatch(item) for item in items):
            found.extend(items)
    found.extend(match.group(1) for match in PE_SINGLE_RE.finditer(text))
    return _unique(found)


def plain_custom_emoji_ids(text):
    """Parse comma, whitespace and newline separated plain numeric IDs."""
    normalized = normalize_local_digits(text)
    return _unique(re.split(r"[\s,]+", normalized.strip()))


def custom_emoji_ids_in_html(text):
    return _unique(match.group(1) for match in TG_EMOJI_TAG_RE.finditer(str(text or "")))


def angle_custom_emoji_ids_in_text(text):
    """Return IDs written in the compact <123456> syntax."""
    return _unique(match.group(1) for match in ANGLE_EMOJI_ID_RE.finditer(str(text or "")))


def compile_angle_custom_emoji_syntax(text, fallback_map):
    """Replace <custom_emoji_id> tokens with Telegram custom-emoji HTML."""
    fallback_map = fallback_map or {}

    def replace(match):
        emoji_id = _canonical_id(match.group(1))
        fallback = fallback_map.get(emoji_id)
        return _entity_html_tag(emoji_id, fallback) if fallback else f"&lt;{html.escape(emoji_id)}&gt;"

    return ANGLE_EMOJI_ID_RE.sub(replace, str(text or ""))


def _api_sticker_map(response):
    if not isinstance(response, dict) or response.get("ok") is not True:
        return None
    rows = response.get("result")
    if not isinstance(rows, list):
        return None
    result = {}
    for sticker in rows:
        if not isinstance(sticker, dict):
            continue
        emoji_id = _canonical_id(sticker.get("custom_emoji_id"))
        fallback = sticker.get("emoji")
        if emoji_id and isinstance(fallback, str) and fallback:
            result[emoji_id] = fallback
    return result


def validate_custom_emoji_ids(ids, api_call, cache=None, max_ids=200):
    """Validate IDs with getCustomEmojiStickers.

    Returns a dict with ``valid`` mapping ID to Telegram's fallback character,
    ``invalid`` IDs and an ``error`` string. API failures never count as valid.
    ``cache`` is a process-level dict and stores both valid and invalid results.
    """
    cache = cache if cache is not None else {}
    unique = _unique(ids)
    if len(unique) > max_ids:
        return {
            "ok": False,
            "valid": {},
            "invalid": unique[max_ids:],
            "error": f"At most {max_ids} unique custom-emoji IDs can be validated at once.",
            "requested": unique,
        }

    valid = {}
    uncached = []
    for emoji_id in unique:
        if emoji_id not in cache:
            uncached.append(emoji_id)
        elif isinstance(cache.get(emoji_id), str) and cache.get(emoji_id):
            valid[emoji_id] = cache[emoji_id]

    api_error = ""
    if uncached:
        try:
            response = api_call(
                "getCustomEmojiStickers",
                {"custom_emoji_ids": uncached},
            )
            sticker_map = _api_sticker_map(response)
            if sticker_map is None:
                api_error = "Telegram custom-emoji validation is unavailable."
                for emoji_id in uncached:
                    cache[emoji_id] = None
            else:
                for emoji_id in uncached:
                    fallback = sticker_map.get(emoji_id)
                    cache[emoji_id] = fallback if fallback else None
                    if fallback:
                        valid[emoji_id] = fallback
        except Exception as exc:
            api_error = f"Telegram custom-emoji validation is unavailable: {type(exc).__name__}."
            for emoji_id in uncached:
                cache[emoji_id] = None

    invalid = [emoji_id for emoji_id in unique if emoji_id not in valid]
    return {
        "ok": not invalid and not api_error,
        "valid": valid,
        "invalid": invalid,
        "error": api_error,
        "requested": unique,
    }


def _entity_html_tag(emoji_id, fallback):
    return f'<tg-emoji emoji-id="{html.escape(str(emoji_id), quote=True)}">{fallback}</tg-emoji>'


def _replace_explicit_syntax(text, fallback_map):
    text = normalize_local_digits(text)

    def replace_single(match):
        emoji_id = match.group(1)
        fallback = fallback_map.get(emoji_id)
        return _entity_html_tag(emoji_id, fallback) if fallback else match.group(0)

    text = PE_SINGLE_RE.sub(replace_single, text)

    def replace_braces(match):
        content = match.group(1)
        items = [item.strip() for item in content.split(",") if item.strip()]
        if not items or not all(ID_RE.fullmatch(item) for item in items):
            return match.group(0)
        return "".join(
            _entity_html_tag(item, fallback_map[item]) if item in fallback_map else "{" + item + "}"
            for item in items
        )

    return PE_BRACE_RE.sub(replace_braces, text)


def compile_premium_emoji_syntax(text, fallback_map):
    """Compile explicit Premium Emoji syntax with validated fallback characters."""
    return _replace_explicit_syntax(str(text or ""), fallback_map or {})


def expand_premium_emoji_syntax(text, fallback_map):
    return compile_premium_emoji_syntax(text, fallback_map)


def compile_premium_html(text, fallback_map):
    """Compile explicit syntax and replace already extracted tg-emoji tags."""
    text = compile_premium_emoji_syntax(text, fallback_map)

    def replace_tag(match):
        emoji_id = _canonical_id(match.group(1))
        if emoji_id and emoji_id in (fallback_map or {}):
            return _entity_html_tag(emoji_id, fallback_map[emoji_id])
        return match.group(0)

    return TG_EMOJI_TAG_RE.sub(replace_tag, text)


def _utf16_slice(text, offset, length):
    raw = str(text or "").encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


def custom_emoji_entities(message):
    text = message.get("text", message.get("caption", "")) if isinstance(message, dict) else ""
    entities = message.get("entities", message.get("caption_entities", [])) if isinstance(message, dict) else []
    found = []
    for entity in entities or []:
        if entity.get("type") != "custom_emoji":
            continue
        emoji_id = _canonical_id(entity.get("custom_emoji_id"))
        if not emoji_id:
            continue
        try:
            fallback = _utf16_slice(text, int(entity.get("offset", 0)), int(entity.get("length", 0)))
        except Exception:
            fallback = "✅"
        found.append({"id": emoji_id, "fallback": fallback, "offset": int(entity.get("offset", 0)), "length": int(entity.get("length", 0))})
    return found


def parse_menu_button_input(text, message=None):
    """Parse a menu button without splitting hyphens inside its URL."""
    original = str(text or "")
    working = original
    icon_ids = []

    for match in re.finditer(r"\|\s*emoji\s*:\s*([0-9\u09e6-\u09ef\u0660-\u0669\u06f0-\u06f9]+)\s*$", working, re.IGNORECASE):
        icon_ids.append(_canonical_id(match.group(1)))
        working = working[:match.start()].rstrip()
        break
    working = normalize_local_digits(working)

    # A single explicit icon is allowed per button.
    for match in PE_SINGLE_RE.finditer(working):
        icon_ids.append(_canonical_id(match.group(1)))
    for match in PE_BRACE_RE.finditer(working):
        content = [item.strip() for item in match.group(1).split(",") if item.strip()]
        if content and all(ID_RE.fullmatch(item) for item in content):
            icon_ids.extend(content)
    icon_ids.extend(angle_custom_emoji_ids_in_text(working))
    icon_ids = _unique(icon_ids)

    direct_entities = custom_emoji_entities(message or {})
    icon_ids.extend(item["id"] for item in direct_entities)
    icon_ids = _unique(icon_ids)
    if len(icon_ids) > 1:
        return {"ok": False, "error": "Each button can have only one custom emoji icon."}

    # Remove icon syntax from the label before parsing the URL.
    working = re.sub(r"\|\s*emoji\s*:\s*[0-9]+\s*$", "", working, flags=re.IGNORECASE).rstrip()
    working = PE_SINGLE_RE.sub("", working)
    working = PE_BRACE_RE.sub(
        lambda m: "" if all(ID_RE.fullmatch(item.strip()) for item in m.group(1).split(",") if item.strip()) else m.group(0),
        working,
    )
    working = ANGLE_EMOJI_ID_RE.sub("", working).strip()
    for entity in reversed(direct_entities):
        if entity.get("fallback"):
            working = working.replace(entity["fallback"], "", 1).strip()

    separator = re.search(r"\s+-\s+", working)
    if not separator:
        return {"ok": False, "error": "Use: Button Text - https://example.com"}
    label = working[:separator.start()].strip()
    url = working[separator.end():].strip()
    if not label or not url:
        return {"ok": False, "error": "Button label and URL are required."}
    return {
        "ok": True,
        "text": label,
        "url": normalize_telegram_url(url),
        "icon_custom_emoji_id": icon_ids[0] if icon_ids else None,
    }


def normalize_telegram_url(url):
    value = str(url or "").strip()
    if value.startswith("@"):
        return "https://t.me/" + value[1:]
    if value.startswith("t.me/"):
        return "https://" + value
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:/.*)?$", value):
        return "https://" + value
    return value


def render_menu_placeholders(template, first_name="User", full_name="User", username="", user_id="", brand_name_html="", replacements=None):
    """Render safe dynamic menu placeholders; brand_name_html is trusted HTML."""
    raw = str(template or "")
    for placeholder, value in (replacements or {}).items():
        raw = raw.replace("{" + str(placeholder) + "}", html.escape(str(value)))
    values = {
        "first_name": html.escape(str(first_name or "User")),
        "full_name": html.escape(str(full_name or first_name or "User")),
        "username": html.escape(str(username or "")),
        "user_id": html.escape(str(user_id or "")),
    }
    for placeholder, value in values.items():
        raw = raw.replace("{" + placeholder + "}", value)
    return raw.replace("{brand_name}", str(brand_name_html or ""))


def premium_emoji_preview_messages(ids, fallback_map, invalid=None, chunk_size=3500):
    invalid = set(invalid or [])
    lines = []
    for emoji_id in _unique(ids):
        if emoji_id in fallback_map:
            entity = _entity_html_tag(emoji_id, fallback_map[emoji_id])
            lines.append(f"<code>{html.escape(emoji_id)}</code> — This code emoji: {entity}")
        else:
            lines.append(f"<code>{html.escape(emoji_id)}</code> — ❌ Invalid custom-emoji ID")
    chunks = []
    current = ""
    for line in lines:
        candidate = line if not current else current + "\n" + line
        if current and len(candidate) > chunk_size:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or ["No custom-emoji IDs found."]


def _replace_direct_custom_entities(message, fallback_map):
    kind, body, _ = _message_body(message)
    if not body:
        return body
    raw = body.encode("utf-16-le")
    for entity in reversed(custom_emoji_entities(message)):
        emoji_id = entity["id"]
        fallback = (fallback_map or {}).get(emoji_id)
        if not fallback:
            continue
        start = entity["offset"] * 2
        end = start + entity["length"] * 2
        replacement = _entity_html_tag(emoji_id, fallback).encode("utf-16-le")
        raw = raw[:start] + replacement + raw[end:]
    return raw.decode("utf-16-le")


def _message_body(message):
    if message.get("text") is not None:
        return "text", message.get("text", ""), message.get("entities", [])
    if message.get("caption") is not None:
        return "caption", message.get("caption", ""), message.get("caption_entities", [])
    return "", "", []


def build_premium_broadcast_payload(message, validate_func, api_call=None):
    """Prepare send-method payloads; copyMessage remains available when unused."""
    kind, body, entities = _message_body(message)
    explicit_ids = premium_emoji_ids_in_text(body)
    angle_ids = angle_custom_emoji_ids_in_text(body)
    direct_ids = [item["id"] for item in custom_emoji_entities(message)]
    strict_ids = _unique(explicit_ids + direct_ids)
    if not strict_ids and not angle_ids:
        return {"ok": True, "use_copy": True, "kind": "copy", "ids": [], "payload": None}

    fallback_map = {}
    if strict_ids:
        strict_result = validate_func(strict_ids)
        if not strict_result.get("ok"):
            invalid = ", ".join(strict_result.get("invalid") or strict_ids)
            error = strict_result.get("error") or "Invalid custom-emoji ID."
            return {"ok": False, "use_copy": False, "invalid": invalid, "error": error}
        fallback_map.update(strict_result.get("valid", {}))
    if angle_ids:
        # Invalid angle IDs are preserved as literal text instead of blocking
        # the broadcast. Valid angle IDs still become Premium Custom Emojis.
        angle_result = validate_func(angle_ids)
        fallback_map.update(angle_result.get("valid", {}))
    valid_ids = list(fallback_map)
    if not valid_ids:
        return {"ok": True, "use_copy": True, "kind": "copy", "ids": [], "payload": None}

    body_with_entities = _replace_direct_custom_entities(message, fallback_map)
    compiled = compile_premium_html(body_with_entities, fallback_map)
    compiled = compile_angle_custom_emoji_syntax(compiled, fallback_map)
    payload = {"parse_mode": "HTML"}
    if kind == "text":
        payload.update({"text": compiled, "disable_web_page_preview": True})
    elif kind == "caption":
        payload["caption"] = compiled
    else:
        return {"ok": False, "use_copy": False, "invalid": "", "error": "Premium Emoji syntax requires text or a media caption."}

    media_specs = (
        ("photo", "photo"),
        ("video", "video"),
        ("animation", "animation"),
        ("document", "document"),
        ("audio", "audio"),
        ("voice", "voice"),
    )
    method = "sendMessage" if kind == "text" else None
    for field, api_field in media_specs:
        if field in message:
            value = message[field]
            if isinstance(value, list):
                value = value[-1] if value else {}
            if isinstance(value, dict):
                value = value.get("file_id", "")
            payload[api_field] = value
            method = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation", "document": "sendDocument", "audio": "sendAudio", "voice": "sendVoice"}[field]
            break
    if not method:
        return {"ok": False, "use_copy": False, "invalid": "", "error": "Unsupported broadcast message type."}
    if message.get("reply_markup"):
        payload["reply_markup"] = message["reply_markup"]
    return {"ok": True, "use_copy": False, "kind": method, "method": method, "payload": payload, "ids": _unique(strict_ids + angle_ids), "fallback_map": fallback_map}


__all__ = [
    "normalize_local_digits", "premium_emoji_ids_in_text", "plain_custom_emoji_ids",
    "angle_custom_emoji_ids_in_text", "compile_angle_custom_emoji_syntax",
    "validate_custom_emoji_ids", "expand_premium_emoji_syntax", "compile_premium_emoji_syntax",
    "compile_premium_html", "premium_emoji_preview_messages", "parse_menu_button_input",
    "normalize_telegram_url", "custom_emoji_entities", "custom_emoji_ids_in_html",
    "build_premium_broadcast_payload", "render_menu_placeholders",
]

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
#==============================================================================
#  [02]  CONFIGURATION — TOKEN, OWNER & PATHS
#==============================================================================
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "bot_data.json")
_db_file_lock = threading.RLock()

# ==========================================
# Premium Emoji Database
# ==========================================
#==============================================================================
#  [03]  PREMIUM EMOJI ASSETS & DEFAULT MESSAGE / CARD TEMPLATES
#==============================================================================
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
    "start": {"text": "", "buttons": []},
    "get_number": {"text": "", "buttons": []},
    "select_country": {"text": f"📌 Select a country for {{service}}:", "buttons": []},
    "search_number": {"text": "", "buttons": []},
    "traffic": {"text": "{traffic_content}", "buttons": []},
    "refer": {"text": "", "buttons": []},
    "withdrawal": {"text": "", "buttons": []},
    "support": {"text": "", "buttons": []},
    "access_type": {"text": f"{PEM['phone']} <b>{{brand_name}}</b>\n\n{PEM['link']} <b>Select access type</b>", "buttons": [
        {"text": "FREE NUMBER", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "ux_free_number", "style": "primary"},
        {"text": "PREMIUM NUMBER", "icon_custom_emoji_id": "5352838545826420397", "callback_data": "ux_premium_number", "style": "primary"},
        {"text": "FB TOOLS USER", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "ux_fb_tools", "style": "primary"},
    ]},
    "service_menu": {"text": "{brand_name}\n\n<b>ACCESS TYPE - {access_title}</b>\n\n<b>Select platform</b>", "buttons": []},
    "fb_tools_menu": {"text": "{fb_info}", "buttons": []},
    "fb_service_menu": {"text": "{fb_service_info}", "buttons": []},
    "number_broadcast": {"text": f"{PEM['rocket']} <b>NEW STOCK ADDED</b>\n━\n<b>Country:</b> {{country}} <b>{{country1}}</b>\n<b>Service:</b> {{service}}\n<b>Quantity:</b> <b>{{total}}</b>\n━\n<b>Tap Get Number to receive a number from this exact batch.</b>", "buttons": []},
    "otp_inbox": {"text": f"{PEM['msg']} <b>OTP RECEIVED</b>\n━\n<b>Service:</b> {{service}}\n<b>Country:</b> {{country}} <b>{{country1}}</b>\n<b>Number:</b> <code>{{number}}</code> {{lang}}\n<b>OTP:</b> <code>{{otp}}</code>\n{{provider_line}}{{range_line}}<b>SMS:</b> <code>{{sms}}</code>\n━", "buttons": []},
    "otp_group": {"text": "{brand_name}\n🔐 <b>OTP RECEIVED</b>\n\n📱 <b>Service:</b> {service}\n🌍 <b>Country:</b> {country1}\n#️⃣ <b>Prefix:</b> <code>{prefix}</code>\n☎️ <b>Number:</b> <code>{number}</code>\n🔑 <b>OTP:</b> <code>{otp}</code>", "buttons": []},
    "referral_dashboard":  {"text": f"{PEM['graph']} <b>Your Referral Dashboard</b>\n\n{PEM['gift']} <b>You Referred:</b> {{total_ref}} users\n{PEM['money']} <b>Commission:</b> You receive ${{ref_reward}} when your referral verifies their account!\n\n{PEM['link']} <b>Referral Link:</b>\n<code>{{ref_link}}</code>", "buttons": []},
    "stock_categories": {"text": "", "buttons": []},
    "stock_list": {"text": "<b>{stock_title}</b>\n<b>TOTAL COUNTRY ENTRIES:</b> {total_entries}\n<b>PAGE:</b> 1/1\n\n{stock_entries}", "buttons": []},
    "temp_mail_waiting": {"text": f"{PEM['msg']} <b>Temp Mail</b>\n\n<b>Email:</b> <code>{{email}}</code>\n<b>Status:</b> {{status}}", "buttons": []},
    "temp_mail_otp": {"text": f"{PEM['msg']} <b>New Email Received</b>\n\n<b>Email:</b> <code>{{email}}</code>\n{{status}}\n<b>From:</b> {{sender}}\n<b>Subject:</b> {{subject}}{{body_line}}", "buttons": []},
    "temp_mail_inbox": {"text": f"{PEM['msg']} <b>Current email address:</b> <code>{{email}}</code>\n\n{{inbox_entries}}", "buttons": []},
    "temp_mail_received": {"text": f"{PEM['msg']} <b>Email Received</b>\n\n<b>Email:</b> <code>{{email}}</code>\n<b>From:</b> {{sender}}\n<b>Subject:</b> {{subject}}\n{{body_line}}", "buttons": []}
}

# Card templates are separate from free-form message templates. Each row has
# an independently editable label and value; values may contain runtime
# placeholders such as {country}, {country1}, {service1}, {number}, or {otp}.
DEFAULT_CARD_TEMPLATES = {
    "access_type": {"title": "ACCESS TYPE", "rows": [
        {"label": "ACCESS", "value": "{access_type}"}, {"label": "STOCK", "value": "{stock}"},
        {"label": "REWARD", "value": "{reward}"}, {"label": "STATUS", "value": "{status}"},
    ]},
    "service_menu": {"title": "SELECT SERVICE", "rows": [
        {"label": "ACCESS TYPE", "value": "{access_title}"}, {"label": "SERVICES", "value": "{service_count}"},
    ]},
    "country_menu": {"title": "SELECT COUNTRY", "rows": [
        {"label": "SERVICE", "value": "{service}"}, {"label": "COUNTRIES", "value": "{country_count}"},
    ]},
    "number_card": {"title": "{service1} NUMBER", "rows": [
        {"label": "COUNTRY", "value": "{country} {country1}"}, {"label": "SERVICE", "value": "{service}"},
        {"label": "ACCESS TYPE", "value": "{category}"}, {"label": "NUMBER", "value": "{number}"},
        {"label": "REWARD", "value": "{reward}"}, {"label": "OTP STATUS", "value": "{status}"},
    ]},
    "number_broadcast": {"title": "🔔 <b>NEW STOCK ADDED</b>", "rows": [
        {"label": "COUNTRY", "value": "{country} {country1}"},
        {"label": "SERVICE", "value": "{service}"},
        {"label": "QUANTITY", "value": "{total}"},
    ]},
    "otp_inbox": {"title": "{country} {country1} · {service_header} · {lang}", "rows": [
        {"label": "PREFIX", "value": "{prefix}"},
        {"label": "NUMBER", "value": "{number1}"},
        {"label": "OTP", "value": "{otp}"},
        {"label": "REWARD", "value": "{reward}"},
    ]},
    "otp_group": {"title": "{country} {country1} · {service_header} · {lang}", "rows": [
        {"label": "PREFIX", "value": "{prefix}"},
        {"label": "NUMBER", "value": "{number1}"},
        {"label": "OTP", "value": "{otp}"},
    ]},
    "profile": {"title": "🎈 <b>USER DASHBOARD</b>", "rows": [
        {"label": "🪪 USER ID", "value": "{user_id}"}, {"label": "👥 USERNAME", "value": "{username}"},
        {"label": "📅 JOINED ON", "value": "{joined_on}"}, {"label": "🔄 TOTAL OTP", "value": "{total_otp}"},
        {"label": "🛡 FREE OTP", "value": "{total_free} · TODAY {today_free}"},
        {"label": "💎 PREMIUM OTP", "value": "{total_premium} · TODAY {today_premium}"},
        {"label": "🫂 REFERRALS", "value": "{total_ref}"}, {"label": "🕒 ACCESS VALID UNTIL", "value": "{access_valid_until}"},
    ]},
    "balance": {"title": "💰 <b>BALANCE OVERVIEW</b>", "rows": [
        {"label": "💵 AVAILABLE BALANCE", "value": "{bal}"}, {"label": "🫂 TOTAL OTP EARNING", "value": "{earned_otp}"},
        {"label": "🎁 TOTAL REFERRAL EARNINGS", "value": "{earned_ref}"}, {"label": "💸 TOTAL WITHDRAWN", "value": "{withdrawn}"},
    ]},
    "withdrawal": {"title": "💸 <b>WITHDRAWAL</b>", "rows": [
        {"label": "🔄 TOTAL OTP", "value": "{total_otp}"}, {"label": "👥 TOTAL REFERRAL", "value": "{total_ref}"},
        {"label": "💵 BALANCE", "value": "{bal}"}, {"label": "🔒 MINIMUM", "value": "{min_w}"},
    ]},
    "stock_list": {"title": "{stock_title}", "rows": [
        {"label": "TOTAL COUNTRY ENTRIES", "value": "{total_entries}"}, {"label": "PAGE", "value": "{page}"},
        {"label": "STOCK", "value": "{stock_entries}"},
    ]},
    "admin_panel": {"title": "⚙️ <b>ADMIN CONTROL PANEL</b>", "rows": [
        {"label": "USERS", "value": "{users}"}, {"label": "FILES", "value": "{files}"},
        {"label": "NUMBERS", "value": "{numbers}"}, {"label": "ASSIGNED", "value": "{assigned}"},
        {"label": "AVAILABLE", "value": "{available}"},
    ]},
    "traffic": {"title": "📊 <b>LIVE TRAFFIC</b>", "rows": [
        {"label": "🕒 WINDOW", "value": "{window}"}, {"label": "🔑 TOTAL OTP", "value": "{total}"},
        {"label": "📊 TOP SERVICES", "value": "{traffic_content}"},
    ]},
    "referral_dashboard": {"title": "🔗 <b>REFERRAL DASHBOARD</b>", "rows": [
        {"label": "🔗 REFERRAL LINK", "value": "{ref_link}"}, {"label": "👥 TOTAL REFERRALS", "value": "{total_ref}"},
        {"label": "💵 PER REFERRAL", "value": "{ref_reward}"},
    ]},
    "support": {"title": "ℹ️ <b>NEED HELP?</b>", "rows": [
        {"label": "🎧 SUPPORT", "value": "CONTACT OUR SUPPORT TEAM FOR ANY QUESTION OR ISSUE. ✅"},
    ]},
    "temp_mail_waiting": {"title": "TEMP MAIL", "rows": [
        {"label": "EMAIL", "value": "{email}"}, {"label": "STATUS", "value": "{status}"},
    ]},
    "fb_tools": {"title": "FACEBOOK TOOLS USER", "rows": [
        {"label": "MODE", "value": "{mode}"}, {"label": "FREE LIMIT", "value": "{free_limit}"},
        {"label": "STATUS", "value": "{status}"},
    ]},
}

# ==========================================
# Firebase Setup
# ==========================================
# Firebase credentials can be supplied as a local JSON file or as a Railway
# environment variable. Secrets are never embedded in source code.
#==============================================================================
#  [04]  FIREBASE INIT (OPTIONAL — FALLS BACK TO LOCAL JSON)
#==============================================================================
_fb_creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")
_fb_creds_json = (
    os.environ.get("FIREBASE_CREDENTIALS_JSON")
    or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or ""
).strip()
_fb_creds_b64 = (
    os.environ.get("FIREBASE_CREDENTIALS_JSON_B64")
    or os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")
    or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON_B64")
    or ""
).strip()

try:
    cred_dict = None
    if _fb_creds_b64:
        cred_dict = json.loads(base64.b64decode(_fb_creds_b64).decode("utf-8"))
    elif _fb_creds_json:
        cred_dict = json.loads(_fb_creds_json)
    elif os.path.exists(_fb_creds_path):
        with open(_fb_creds_path, "r", encoding="utf-8") as _f:
            cred_dict = json.load(_f)

    if cred_dict:
        if isinstance(cred_dict, dict) and isinstance(cred_dict.get("private_key"), str):
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firebase Connected! (Full Sync Enabled)")
    else:
        # Never print the configured path value: a user may accidentally paste
        # a whole credential JSON into FIREBASE_CREDENTIALS_PATH.
        if _fb_creds_path.lstrip().startswith("{"):
            print("❌ FIREBASE_CREDENTIALS_PATH must be a file path, not JSON.")
        else:
            print("⚠️  Firebase credentials not configured.")
            print("   Set FIREBASE_CREDENTIALS_JSON_B64 (recommended) or provide a valid credential file.")
        print("   Continuing without Firebase (local JSON only).")
        db = None
except Exception as e:
    print(f"❌ Firebase Error: {type(e).__name__}: {e}")
    db = None

def disable_firestore(reason=""):
    global db
    if db is not None:
        print(f"⚠️ Firestore disabled for this runtime. Local JSON fallback active. {reason}")
    db = None


# ─── Pre-load Force Join, OTP Group, Support Link from .env ─────────────────
#==============================================================================
#  [05]  BOT SETTINGS & ENV DEFAULTS
#==============================================================================
_env_fj_on       = os.environ.get("FORCE_JOIN_ON", "false").lower() == "true"
_env_fj_channels_raw = os.environ.get("FORCE_JOIN_CHANNELS", "").strip()
_env_fj_channels = [ch.strip() for ch in _env_fj_channels_raw.split(",") if ch.strip()] if _env_fj_channels_raw else []
# Keep all Telegram destinations empty by default. Add your own values in .env
# or through the Admin Panel before using these features.
_env_otp_link    = os.environ.get("OTP_GROUP_LINK", "").strip()
_env_support     = os.environ.get("SUPPORT_LINK", "").strip()
_env_w_group     = os.environ.get("WITHDRAWAL_GROUP", "").strip()

bot_settings = {
    "admins": [OWNER_ID],
    "panels": [],
    "fw_groups": [],
    "otp_link": _env_otp_link,
    "withdraw_on": os.environ.get("WITHDRAW_ON", "true").lower() == "true",
    "min_withdraw": float(os.environ.get("MIN_WITHDRAW", "1.0")),
    "otp_reward": float(os.environ.get("OTP_REWARD", "0.003")),
    "refer_reward": float(os.environ.get("REFER_REWARD", "0.01")),
    "cooldown": int(os.environ.get("COOLDOWN", "10")),
    "traffic_forward_interval": int(os.environ.get("TRAFFIC_FORWARD_INTERVAL", "7200")),
    "num_req": int(os.environ.get("NUM_REQ", "3")),
    "num_share": int(os.environ.get("NUM_SHARE", "1")),
    "support_link": _env_support,
    "w_methods": ["Binance Pay", "USDT Wallet (TRC20)", "PayPal", "Wise", "Payoneer", "SEPA Bank Transfer"],
    "w_group": _env_w_group,
    "brand_name": os.environ.get("BRAND_NAME", "Versia SMS 🔥"),
    "premium_users": {},
    "premium_support_link": os.environ.get("PREMIUM_SUPPORT_LINK", os.environ.get("SUPPORT_LINK", "")),
    "premium_number_plans": [
        {"label": "1 DAY - 1 USD", "days": 1, "price": "1 USD"},
        {"label": "7 DAYS - 3 USD", "days": 7, "price": "3 USD"},
        {"label": "30 DAYS - 10 USD", "days": 30, "price": "10 USD"},
    ],
    "premium_number_requests": {},
    "fb_tools": {
        "enabled": True,
        "free_limit": int(os.environ.get("FB_TOOLS_FREE_LIMIT", "200")),
        "free_cooldown": int(os.environ.get("FB_TOOLS_FREE_COOLDOWN", "600")),
        "max_per_request": int(os.environ.get("FB_TOOLS_MAX_PER_REQUEST", "200")),
        "binance_id": os.environ.get("FB_TOOLS_BINANCE_ID", os.environ.get("BINANCE_ID", "")),
        "info_text": "<b>FACEBOOK TOOLS USER</b>\n\n<b>FREE:</b> Free users can request {free_limit} numbers once every {free_minutes} minutes per country.\n\n<b>PREMIUM:</b> Approved premium users can request unlimited numbers with no waiting time.",
        "required_text": "<b>PREMIUM NUMBER Required</b>\n\n<b>Feature:</b> Premium Tools User\n<b>User ID:</b> <code>{user_id}</code>\n<b>Username:</b> {username}\n\n<b>Your PREMIUM NUMBER is not approved yet.</b>\nPlease send a premium request and wait for Owner/Admin approval.",
        "plans": [
            {"label": "1Day-1$", "days": 1, "price": "1 USD"},
            {"label": "2Day-2$", "days": 2, "price": "2 USD"},
            {"label": "7Day-3$", "days": 7, "price": "3 USD"},
        ],
        "payment_methods": ["Binance"],
    },

    "fj_on": _env_fj_on,
    "fj_channels": _env_fj_channels,
    "stex_keys": [],
    "voltx_keys": [],
    "search_countries": [],
    "stex_services": {},
    "voltx_services": {},
    "premium_flags": {
        "1": {"char": "🇺🇸", "iso": "US", "name": "United States", "id": "5913463998522592692"},
        "880": {"char": "🇧🇩", "iso": "BD", "name": "Bangladesh", "id": "5911365056594973179"},
        "91": {"char": "🇮🇳", "iso": "IN", "name": "India", "id": "5913754823643107921"},
        "92": {"char": "🇵🇰", "iso": "PK", "name": "Pakistan", "id": "5913705895375672082"},
        "44": {"char": "🇬🇧", "iso": "GB", "name": "United Kingdom", "id": "5913443365499703513"}
    },
    "premium_apps": {
        "FACEBOOK": {"char": "🚫", "id": "5334807341109908955", "name": "Facebook"},
        "WHATSAPP": {"char": "🚫", "id": "5334759662677957452", "name": "WhatsApp"}
    },
    "button_emojis": {},
    "body_emojis": dict(GLOBAL_BODY_EMOJIS),
    "custom_messages": DEFAULT_CUSTOM_MESSAGES.copy(),
    "card_templates": json.loads(json.dumps(DEFAULT_CARD_TEMPLATES))
}

FS_KEYS = [
    "admins", "panels", "fw_groups", "otp_link", "withdraw_on",
    "min_withdraw", "otp_reward", "refer_reward", "cooldown", "traffic_forward_interval",
    "num_req", "num_share", "support_link", "w_methods", "w_group", "brand_name", "premium_users", "premium_support_link", "premium_number_plans", "premium_number_requests", "fb_tools", "button_emojis", "stex_keys", "voltx_keys", "search_countries", "stex_services", "voltx_services",
    "fj_on", "fj_channels", "card_templates"
]

#==============================================================================
#  [06]  RUNTIME STATE — STOCK, TRAFFIC, SESSIONS
#==============================================================================
number_batches = {}
used_numbers_list = []
stex_assigned_numbers = {}
voltx_assigned_numbers = {}
STEX_BASE_URL = os.environ.get("STEX_BASE_URL", "").rstrip("/")
VOLTX_BASE_URL = os.environ.get("VOLTX_BASE_URL", "").rstrip("/")
total_uploaded_stats = 0
total_assigned_stats = 0
processed_otps = set()
# Traffic screen reports OTP activity from the last five minutes.
TRAFFIC_WINDOW_SECONDS = 5 * 60
recent_traffic = []
user_banned_cache = {}

# Active HTTP sessions for Auto Captcha Panels
panel_sessions = {}

# 🌟 sAjaxSource (AJAX/DataTable)  Fallback HTML Parser Helper Function
#==============================================================================
#  [07]  PROVIDER PANEL SESSIONS & CDR FETCH
#==============================================================================
def fetch_cpt_panel_cdrs(p, session, check_url):
    res = session.get(check_url, timeout=15)
    html_text = res.text

    #
    if "login" in html_text.lower() or "signin" in html_text.lower() or any(x in html_text for x in ["Sign in to your account", "Please sign in", "Welcome back!"]):
        raise Exception("Session expired")

    soup = BeautifulSoup(html_text, 'html.parser')
    s_ajax_source = ""
    for script in soup.find_all("script"):
        script_text = script.string or ""
        match = re.search(r'sAjaxSource":\s*"([^"]+)"', script_text)
        if match:
            s_ajax_source = match.group(1)
            break

    results = []

    n_col_name = p.get("num_col_name", "number").lower()
    m_col_name = p.get("msg_col_name", "message").lower()
    n_idx = int(p.get("num_col_idx", 1)) - 1 if p.get("num_col_idx") else 1
    m_idx = int(p.get("msg_col_idx", 2)) - 1 if p.get("msg_col_idx") else 2

    # .  sAjaxSource AJAX
    if s_ajax_source:
        baseUrl = p.get("login_url", "").split("/client")[0].split("/login")[0].strip()
        if not baseUrl.startswith("http"):
            baseUrl = "http://" + baseUrl

        full_ajax_url = ""
        if s_ajax_source.startswith("http"):
            full_ajax_url = s_ajax_source
        elif s_ajax_source.startswith("/"):
            full_ajax_url = f"{baseUrl}{s_ajax_source}"
        else:
            last_slash_idx = check_url.rfind("/")
            current_dir = check_url[:last_slash_idx]
            full_ajax_url = f"{current_dir}/{s_ajax_source}"

        if "iDisplayLength" not in full_ajax_url:
            query_params = "sEcho=1&iColumns=7&iDisplayStart=0&iDisplayLength=250&sSearch=&iSortingCols=1&iSortCol_0=0&sSortDir_0=desc"
            divider = "&" if "?" in full_ajax_url else "?"
            full_ajax_url += f"{divider}{query_params}"

        ajax_headers = {
            "Referer": check_url,
            "X-Requested-With": "XMLHttpRequest"
        }

        ajax_res = session.get(full_ajax_url, headers=ajax_headers, timeout=15)
        data_dict = ajax_res.json()
        rows = data_dict.get("aaData", [])
        for row_val in rows:
            if not isinstance(row_val, list):
                continue

            if len(row_val) < max(n_idx, m_idx) + 1:
                continue

            num_val = row_val[n_idx] if (0 <= n_idx < len(row_val)) else row_val[2]
            msg_val = row_val[m_idx] if (0 <= m_idx < len(row_val)) else row_val[4]

            clean_num = re.sub(r'\D', '', str(num_val))
            if clean_num and 5 <= len(clean_num) <= 18:
                otp = extract_otp_code(msg_val)
                if otp and len(msg_val) > 4:
                    results.append({"number": clean_num, "message": msg_val, "otp": otp})

    else:
        # .  HTML
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            if not rows: continue

            final_n_idx = n_idx
            final_m_idx = m_idx

            header_cells = rows[0].find_all(['th', 'td'])
            for i, cell in enumerate(header_cells):
                c_text = cell.get_text(strip=True).lower()
                if n_col_name in c_text: final_n_idx = i
                if m_col_name in c_text: final_m_idx = i

            for row in rows:
                cols = row.find_all(['td', 'th'])
                if all(c.name == 'th' for c in cols): continue

                if len(cols) > max(final_n_idx, final_m_idx):
                    num_text = cols[final_n_idx].get_text(separator=" ", strip=True)
                    msg_text = cols[final_m_idx].get_text(separator=" ", strip=True)

                    clean_num = re.sub(r'\D', '', num_text)
                    if clean_num and 5 <= len(clean_num) <= 18:
                        otp = extract_otp_code(msg_text)
                        if otp and len(msg_text) > 4:
                            results.append({"number": clean_num, "message": msg_text, "otp": otp})

    return results, html_text

# Track active number sessions to expire them automatically
user_active_sessions = {}
# Facebook Tools numbers keep receiving OTP inbox delivery for 24 hours.
fb_tools_sessions = {}
FB_TOOLS_SESSION_TTL = 24 * 60 * 60

#==============================================================================
#  [08]  DATABASE & PERSISTENCE (LOCAL JSON + FIRESTORE)
#==============================================================================
def sanitize_premium_assets():
    """Keep custom-emoji data safe so one bad record cannot stop bot startup."""
    specs = {
        "premium_flags": ("🌍", False),
        "premium_apps": ("📦", True),
    }
    for setting_name, (default_char, uppercase_names) in specs.items():
        source = bot_settings.get(setting_name, {})
        if not isinstance(source, dict):
            source = {}
        cleaned = {}
        for raw_name, raw_record in source.items():
            name = str(raw_name or "").strip()
            if not name:
                continue
            record = {"id": raw_record} if isinstance(raw_record, (str, int)) else raw_record
            if not isinstance(record, dict):
                continue
            emoji_id = normalize_local_digits(str(record.get("id") or record.get("custom_emoji_id") or "")).strip()
            if not emoji_id.isdigit():
                continue
            safe_name = name.upper() if uppercase_names else name.lower()
            fallback = str(record.get("char") or record.get("emoji") or default_char)
            cleaned[safe_name] = {
                "id": emoji_id,
                "char": fallback[:32],
                "name": str(record.get("name") or name),
            }
            if record.get("iso") is not None:
                cleaned[safe_name]["iso"] = str(record.get("iso") or "XX").upper()
            if record.get("code") is not None:
                cleaned[safe_name]["code"] = str(record.get("code") or "")
        bot_settings[setting_name] = cleaned
    raw_buttons = bot_settings.get("button_emojis", {})
    if not isinstance(raw_buttons, dict):
        raw_buttons = {}
    bot_settings["button_emojis"] = {
        str(label).strip().casefold(): normalize_local_digits(str(value.get("id") if isinstance(value, dict) else value)).strip()
        for label, value in raw_buttons.items()
        if str(label).strip() and normalize_local_digits(str(value.get("id") if isinstance(value, dict) else value)).strip().isdigit()
    }
    raw_body_emojis = bot_settings.get("body_emojis", GLOBAL_BODY_EMOJIS)
    if not isinstance(raw_body_emojis, dict):
        raw_body_emojis = GLOBAL_BODY_EMOJIS
    bot_settings["body_emojis"] = {
        str(char): normalize_local_digits(str(value.get("id") if isinstance(value, dict) else value)).strip()
        for char, value in raw_body_emojis.items()
        if str(char) and normalize_local_digits(str(value.get("id") if isinstance(value, dict) else value)).strip().isdigit()
    }


def load_db():
    global db, bot_settings, number_batches, used_numbers_list, total_uploaded_stats, total_assigned_stats, recent_traffic, fb_tools_sessions
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
            disable_firestore("Firestore config read failed.")

    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                saved_settings = data.get("bot_settings", {})
                for key, val in saved_settings.items():
                    if key == "premium_emojis":
                        continue
                    if key not in FS_KEYS or key in {"brand_name", "premium_users", "premium_support_link", "fb_tools", "button_emojis", "card_templates", "traffic_forward_interval"}:
                        if key == "custom_messages":
                            if isinstance(val, dict):
                                for m_key, m_val in val.items():
                                    bot_settings["custom_messages"][m_key] = m_val
                            else:
                                print(f"⚠️ Saved custom_messages ignored (type={type(val).__name__}).")
                        else:
                            bot_settings[key] = val

                for m_key, m_val in DEFAULT_CUSTOM_MESSAGES.items():
                    if m_key not in bot_settings["custom_messages"]:
                        bot_settings["custom_messages"][m_key] = m_val
                saved_cards = bot_settings.get("card_templates", {})
                if not isinstance(saved_cards, dict):
                    saved_cards = {}
                for card_key, card_value in DEFAULT_CARD_TEMPLATES.items():
                    if card_key not in saved_cards or not isinstance(saved_cards.get(card_key), dict):
                        saved_cards[card_key] = card_value
                bot_settings["card_templates"] = saved_cards

                number_batches = data.get("number_batches", {})
                used_numbers_list = data.get("used_numbers_list", [])
                total_uploaded_stats = data.get("total_uploaded_stats", 0)
                total_assigned_stats = data.get("total_assigned_stats", 0)
                recent_traffic = data.get("recent_traffic", [])
                stex_assigned_numbers = data.get("stex_assigned_numbers", {})
                voltx_assigned_numbers = data.get("voltx_assigned_numbers", {})
                fb_tools_sessions = data.get("fb_tools_sessions", {}) if isinstance(data.get("fb_tools_sessions", {}), dict) else {}
            print("✅ Local Stock/UI DB Loaded Successfully!")
        except Exception as e:
            print(f"❌ Error loading local DB: {e}")

#==============================================================================
#  [08B] MENU DESIGN SAFETY ENGINE — dead-button protection & design repair
#==============================================================================
# Admin-created buttons (Menu Design, Card Templates, OTP Groups) live in the
# DB and are rendered on nearly every user screen. One invalid button (broken
# URL, unknown callback, empty label) makes Telegram reject the WHOLE keyboard
# — which looks exactly like "the bot died right after I edited a design".
# This engine:
#   1. Validates button actions at SAVE time (no dead button can be stored).
#   2. Sanitizes every stored button at RENDER time (defense in depth).
#   3. Repairs the whole design DB at STARTUP (guaranteed clean boot).

KNOWN_CALLBACK_ACTIONS = frozenset({
"add_adm",
    "add_api_panel",
    "add_cpt_panel",
    "add_fj",
    "add_fw",
    "add_search_country",
    "add_single_emoji",
    "add_stex_key",
    "add_voltx_key",
    "add_voltx_search_country",
    "add_wm",
    "back_to_admin",
    "bc_start",
    "body_emoji_editor",
    "broadcast_msg",
    "button_emoji_editor",
    "cancel_2fa",
    "cancel_dxa_edit",
    "cancel_state",
    "check_fj",
    "clear_emoji_id",
    "close_msg",
    "del_all_flags",
    "delete_files",
    "dl_apps_txt",
    "dl_flags_txt",
    "dl_unused",
    "dl_used",
    "dummy_alert",
    "edit_otp_link",
    "extract_emoji_ids",
    "extract_pack_emoji_ids",
    "gen_2fa",
    "get_number_menu",
    "ignore",
    "md_remove_start_media",
    "md_reset_defaults",
    "md_user_menu",
    "menu_design_list",
    "mk_manage_panels",
    "nx_add_srv",
    "prefix_search",
    "prefix_toggle",
    "preview_emoji_ids",
    "refresh_traffic",
    "send_update_notify",
    "show_unused",
    "show_used",
    "stex_control",
    "stex_search_country",
    "system_settings",
    "test_message_flow",
    "toggle_fj",
    "traffic_main_menu",
    "um_ban_unban",
    "um_manage_balance",
    "um_user_profile",
    "up_apps_txt",
    "up_flags_txt",
    "update_start",
    "upload_num",
    "user_management",
    "user_menu_editor",
    "ux_fb_tools",
    "ux_free_number",
    "ux_get_number",
    "ux_premium_number",
    "ux_set_binance",
    "ux_stock",
    "ux_stock_fb",
    "ux_stock_free",
    "ux_stock_premium",
    "ux_support",
    "ux_withdraw",
    "view_stex_keys",
    "view_voltx_keys",
    "voltx_control",
    "voltx_search_country",
    "vx_add_srv",
})

KNOWN_CALLBACK_PREFIXES = (
"add_fwbtn_",
    "add_ptype_",
    "api_",
    "api_provider",
    "api_provider:",
    "batch_get",
    "batch_get:",
    "bme_set_",
    "c_n_",
    "c_n_s_",
    "card_",
    "card_btn_action",
    "card_btn_add",
    "card_btn_add:",
    "card_btn_delete",
    "card_btn_delete:",
    "card_btn_icon",
    "card_btn_text",
    "card_btn_text:",
    "card_buttons",
    "card_buttons:",
    "card_open",
    "card_open:",
    "card_preview",
    "card_preview:",
    "card_row",
    "card_row:",
    "card_rows",
    "card_rows:",
    "card_save",
    "card_save:",
    "card_title",
    "card_title:",
    "cnc:",
    "cnc:PREMIUM",
    "conf_pnl_",
    "del_adm_",
    "del_b_",
    "del_fj_",
    "del_fw_",
    "del_fwbtn_",
    "del_nxa_",
    "del_sc_",
    "del_vsc_",
    "del_vtx_",
    "del_wm_",
    "do_del_pnl_",
    "dxa_",
    "exp_c_",
    "exp_rng_",
    "fb",
    "fb_del_payment",
    "fb_del_payment:",
    "fb_del_plan",
    "fb_del_plan:",
    "fb_mode:",
    "fb_pay:",
    "fb_plan:",
    "fbapprove",
    "fbapprove:",
    "fbcnt",
    "fbcnt:",
    "fbqty",
    "fbqty:",
    "fbreject",
    "fbreject:",
    "fbsvc:",
    "g_c_",
    "g_s_",
    "gcc",
    "gcc:",
    "gcc:PREMIUM",
    "gsc:",
    "gsc:PREMIUM",
    "lb_",
    "list_del_",
    "manage_",
    "manage_fw_",
    "md_addbtn_",
    "md_btns_",
    "md_delbtn_",
    "md_edit_",
    "md_seticon_",
    "md_text_",
    "mks_",
    "mks_delete",
    "mks_delete:",
    "mks_route_add",
    "mks_route_add:",
    "mks_route_delete",
    "mks_route_delete:",
    "mks_routes",
    "mks_routes:",
    "mks_test",
    "mks_test:",
    "mks_toggle",
    "mks_toggle:",
    "nps_",
    "nx_add_cnt_",
    "nx_addr_",
    "nx_cnt_",
    "nx_del_cnt_",
    "nx_del_srv_",
    "nx_dr_",
    "nx_srv_",
    "otpgrp:",
    "pn",
    "pn_payment:",
    "pn_plan:",
    "pnapprove:",
    "pnreject:",
    "premium_",
    "premium_remove",
    "premium_remove:",
    "ref_2fa_",
    "sel_wm_",
    "set_p_api_",
    "set_p_fapi_",
    "set_p_rec_",
    "set_p_tok_",
    "stock_category:",
    "stock_platform:",
    "stock_platforms:",
    "stocksvc:",
    "test_p_conn_",
    "tog_pnl_",
    "traffic_get:",
    "traffic_interval",
    "traffic_interval:",
    "ume_icon_",
    "ume_text_",
    "vx_add_cnt_",
    "vx_addr_",
    "vx_cnt_",
    "vx_del_cnt_",
    "vx_del_srv_",
    "vx_dr_",
    "vx_srv_",
    "wapp_",
    "wrej_",
)

# Curated hints shown to Admins when a proposed action is rejected.
KNOWN_BUTTON_ACTION_HINTS = (
    "ux_get_number", "ux_free_number", "ux_premium_number", "ux_fb_tools",
    "ux_stock", "ux_support", "ux_set_binance", "ux_withdraw", "close_msg",
)

_URL_SCHEME_RE = re.compile(r"^(https?://|tg://)", re.IGNORECASE)


def is_known_button_action(action):
    """True when the bot really handles this callback action."""
    action = str(action or "").strip()
    if not action:
        return False
    if action in KNOWN_CALLBACK_ACTIONS:
        return True
    return any(action.startswith(prefix) for prefix in KNOWN_CALLBACK_PREFIXES)


def valid_button_url(url):
    """Return a Telegram-safe http/https/tg URL, or an empty string."""
    value = str(url or "").strip()
    if not value:
        return ""
    value = normalize_telegram_url(value)
    if _URL_SCHEME_RE.match(value) and len(value) <= 256:
        return value
    return ""


def validate_button_action(raw_action):
    """Save-time check for a Menu Design button action.

    Accepts a Telegram-safe URL or a callback the bot actually handles.
    Anything else is a dead button and must not be stored.
    """
    action = str(raw_action or "").strip()
    if not action:
        return {"ok": False, "error": "Action is empty. Use: Button Text - https://example.com"}
    url = valid_button_url(action)
    if url:
        return {"ok": True, "url": url}
    if is_known_button_action(action):
        return {"ok": True, "callback": action[:64]}
    sample = ", ".join(KNOWN_BUTTON_ACTION_HINTS)
    return {
        "ok": False,
        "error": (
            f"'{action[:40]}' has no function inside the bot, so this button would be DEAD. "
            f"Use a URL (https://example.com or t.me/your_link) or a real bot action such as: {sample}"
        ),
    }


def safe_inline_button(btn):
    """Return a Telegram-safe copy of a stored button, or None when dead."""
    if not isinstance(btn, dict):
        return None
    text = str(btn.get("text") or "").strip()
    if not text:
        return None
    if len(text) > 64:
        text = text[:64].rstrip() or "Button"
    clean = {"text": text}
    url = valid_button_url(btn.get("url"))
    callback = str(btn.get("callback_data") or "").strip()
    if url:
        clean["url"] = url
    elif callback and is_known_button_action(callback):
        clean["callback_data"] = callback[:64]
    else:
        # Not a valid URL and not a handled callback: a dead button. Drop it
        # so one broken entry can never blank out the whole keyboard.
        return None
    copy_text = btn.get("copy_text")
    if isinstance(copy_text, dict) and str(copy_text.get("text") or ""):
        clean["copy_text"] = {"text": str(copy_text["text"])[:64]}
    icon = str(btn.get("icon_custom_emoji_id") or "").strip()
    if icon.isdigit() and len(icon) <= 64:
        clean["icon_custom_emoji_id"] = icon
    if isinstance(btn.get("style"), str) and btn.get("style"):
        clean["style"] = btn["style"]
    return clean


def safe_custom_buttons(buttons):
    """Filter a stored button list down to the buttons that actually work."""
    if not isinstance(buttons, list):
        return []
    result = []
    for btn in buttons:
        clean = safe_inline_button(btn)
        if clean:
            result.append(clean)
    return result


def sanitize_design_data(persist=False):
    """Repair stored Menu Design data so a bad save can never break startup.

    Returns a list of human-readable repair notes (empty list = data clean).
    """
    problems = []
    try:
        cm = bot_settings.get("custom_messages")
        if not isinstance(cm, dict):
            bot_settings["custom_messages"] = {}
            cm = bot_settings["custom_messages"]
            problems.append("custom_messages was not a dict (reset)")
        for m_key in list(cm.keys()):
            entry = cm.get(m_key)
            if not isinstance(entry, dict):
                cm[m_key] = {"text": "", "buttons": []}
                problems.append(f"custom_messages[{m_key}] reset (bad type)")
                continue
            if not isinstance(entry.get("text"), str):
                entry["text"] = ""
            media = entry.get("media")
            if media is not None and not isinstance(media, dict):
                entry.pop("media", None)
            btns = entry.get("buttons")
            if btns is None:
                entry["buttons"] = []
            elif not isinstance(btns, list):
                entry["buttons"] = []
                problems.append(f"custom_messages[{m_key}].buttons reset (bad type)")
            else:
                fixed = safe_custom_buttons(btns)
                if len(fixed) != len(btns):
                    problems.append(f"custom_messages[{m_key}]: removed {len(btns) - len(fixed)} dead button(s)")
                entry["buttons"] = fixed
        ct = bot_settings.get("card_templates")
        if not isinstance(ct, dict):
            bot_settings["card_templates"] = {}
            ct = bot_settings["card_templates"]
            problems.append("card_templates was not a dict (reset)")
        for c_key in list(ct.keys()):
            tpl = ct.get(c_key)
            if not isinstance(tpl, dict):
                ct[c_key] = json.loads(json.dumps(DEFAULT_CARD_TEMPLATES.get(c_key, {"title": str(c_key).upper(), "rows": []})))
                problems.append(f"card_templates[{c_key}] reset (bad type)")
                continue
            if not isinstance(tpl.get("title"), str):
                tpl["title"] = str(c_key).upper()
            if not isinstance(tpl.get("body_text", ""), str):
                tpl.pop("body_text", None)
            rows = tpl.get("rows")
            if not isinstance(rows, list):
                tpl["rows"] = []
            else:
                tpl["rows"] = [row for row in rows if isinstance(row, dict)]
            btns = tpl.get("buttons")
            if not isinstance(btns, list):
                tpl["buttons"] = []
            else:
                fixed = safe_custom_buttons(btns)
                if len(fixed) != len(btns):
                    problems.append(f"card_templates[{c_key}]: removed {len(btns) - len(fixed)} dead button(s)")
                tpl["buttons"] = fixed
        fws = bot_settings.get("fw_groups")
        if isinstance(fws, list):
            for idx, fw in enumerate(fws):
                if not isinstance(fw, dict):
                    continue
                btns = fw.get("buttons")
                if not isinstance(btns, list):
                    fw["buttons"] = []
                    continue
                fixed = safe_custom_buttons(btns)
                if len(fixed) != len(btns):
                    problems.append(f"otp_groups[{idx}]: removed {len(btns) - len(fixed)} dead button(s)")
                fw["buttons"] = fixed
    except Exception as exc:
        problems.append(f"sanitizer error: {type(exc).__name__}")
    if problems:
        print("🎨 Design Safety:", "; ".join(problems))
        if persist and callable(globals().get("save_db")):
            try:
                save_db()
            except Exception:
                pass
    return problems


def save_local_db():
    # Handlers run concurrently; atomic replacement prevents a partial JSON
    # write from breaking startup or the dynamic-settings monitor.
    with _db_file_lock:
        local_data = {
            "bot_settings": {k: v for k, v in bot_settings.items() if k not in FS_KEYS or k in {"brand_name", "premium_users", "premium_support_link", "fb_tools", "button_emojis", "card_templates", "traffic_forward_interval"}},
            "number_batches": number_batches,
            "used_numbers_list": used_numbers_list,
            "total_uploaded_stats": total_uploaded_stats,
            "total_assigned_stats": total_assigned_stats,
            "recent_traffic": recent_traffic,
            "stex_assigned_numbers": stex_assigned_numbers,
            "voltx_assigned_numbers": voltx_assigned_numbers,
            "fb_tools_sessions": fb_tools_sessions
        }
        tmp_path = f"{DB_FILE}.tmp.{os.getpid()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(local_data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, DB_FILE)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

def _sync_fs():
    if not db: return
    fs_data = {k: bot_settings[k] for k in FS_KEYS if k in bot_settings}
    try:
        db.collection('settings').document('bot_config').set(fs_data)
    except: pass

def save_db():
    global _editable_settings_snapshot
    previous_signature = _editable_settings_snapshot
    current_signature = _editable_settings_signature() if "bot_settings" in globals() else ""
    save_local_db()
    _editable_settings_snapshot = current_signature
    # Settings are persisted silently. User update notifications are manual:
    # an Admin must press UPDATE NOTIFY in the Admin Panel.
    # Avoid creating a thread for every local-only write.
    if db:
        threading.Thread(target=_sync_fs, daemon=True).start()


def load_premium_assets_from_files():
    """Load the supplied Premium App/Flag ID databases from JSON files.
    Existing custom emojis remain available, but the supplied IDs take priority.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        apps_path = os.path.join(base_dir, "premium_apps.json")
        if os.path.exists(apps_path):
            with open(apps_path, "r", encoding="utf-8") as f:
                apps = json.load(f)
            if isinstance(apps, dict):
                bot_settings.setdefault("premium_apps", {}).update(apps)
                print(f"✅ Premium App IDs loaded: {len(apps)}")
    except Exception as e:
        print(f"⚠️ Premium app DB load failed: {type(e).__name__}")
    try:
        flags_path = os.path.join(base_dir, "premium_flags.json")
        if os.path.exists(flags_path):
            with open(flags_path, "r", encoding="utf-8") as f:
                flags = json.load(f)
            if isinstance(flags, dict):
                # Backward compatibility: older records used the dialing code as dict key.
                for k, v in flags.items():
                    if isinstance(v, dict) and "code" not in v and str(k).isdigit():
                        v["code"] = str(k)
                bot_settings.setdefault("premium_flags", {}).update(flags)
                print(f"✅ Premium Flag IDs loaded: {len(flags)}")
    except Exception as e:
        print(f"⚠️ Premium flag DB load failed: {type(e).__name__}")


DEFAULT_USD_WITHDRAW_METHODS = ["Binance Pay", "USDT Wallet (TRC20)", "PayPal", "Wise", "Payoneer", "SEPA Bank Transfer"]
DISALLOWED_WITHDRAW_KEYWORDS = ("bkash", "b-kash", "nagad", "rocket", "upay")


def sanitize_withdrawal_methods_for_usd():
    methods = bot_settings.get("w_methods", [])
    cleaned = []
    for method in methods if isinstance(methods, list) else []:
        m = str(method).strip()
        if not m:
            continue
        if any(bad in m.lower() for bad in DISALLOWED_WITHDRAW_KEYWORDS):
            continue
        if m not in cleaned:
            cleaned.append(m)
    if not cleaned:
        cleaned = DEFAULT_USD_WITHDRAW_METHODS.copy()
    # Binance must always remain available for this USD/European setup.
    if not any("binance" in m.lower() for m in cleaned):
        cleaned.insert(0, "Binance Pay")
    bot_settings["w_methods"] = cleaned


def configure_usd_money_defaults():
    # Convert the old BDT/TK defaults to sensible USD defaults unless explicitly overridden.
    try:
        if "MIN_WITHDRAW" not in os.environ and float(bot_settings.get("min_withdraw", 0)) == 30.0:
            bot_settings["min_withdraw"] = 1.0
        if "OTP_REWARD" not in os.environ and float(bot_settings.get("otp_reward", 0)) == 0.1:
            bot_settings["otp_reward"] = 0.003
        if "REFER_REWARD" not in os.environ and float(bot_settings.get("refer_reward", 0)) == 0.2:
            bot_settings["refer_reward"] = 0.01
    except Exception:
        pass


_EDITABLE_SETTINGS_FOR_NOTICE = set(FS_KEYS) | {"custom_messages", "card_templates", "body_emojis", "user_menu_emojis", "user_menu_labels", "premium_apps", "premium_flags"}
_editable_settings_snapshot = ""


def _editable_settings_signature():
    values = {key: bot_settings.get(key) for key in sorted(_EDITABLE_SETTINGS_FOR_NOTICE)}
    return json.dumps(values, sort_keys=True, ensure_ascii=True, default=str)


load_db()
sanitize_design_data(persist=True)
try:
    load_premium_assets_from_files()
except Exception as _init_exc:
    print(f"⚠️ Premium assets init skipped: {type(_init_exc).__name__}")
try:
    sanitize_premium_assets()
except Exception as _init_exc:
    print(f"⚠️ Premium asset sanitize skipped: {type(_init_exc).__name__}")
try:
    sanitize_withdrawal_methods_for_usd()
except Exception as _init_exc:
    print(f"⚠️ Withdrawal sanitize skipped: {type(_init_exc).__name__}")
try:
    configure_usd_money_defaults()
except Exception as _init_exc:
    print(f"⚠️ Money defaults skipped: {type(_init_exc).__name__}")
_editable_settings_snapshot = _editable_settings_signature()

#==============================================================================
#  [09]  USER RUNTIME STATE, TEMP-MAIL & TIMEOUT CONFIG
#==============================================================================
user_states = {}
temp_data = {}
temp_mail_sessions = {}
group_card_sessions = {}
TEMP_MAIL_POLL_SECONDS = max(2, int(os.environ.get("TEMP_MAIL_POLL_SECONDS", "3")))
TEMP_MAIL_SESSION_TTL = max(300, int(os.environ.get("TEMP_MAIL_SESSION_TTL", "1800")))
TEMP_MAIL_READ_WORKERS = max(2, min(8, int(os.environ.get("TEMP_MAIL_READ_WORKERS", "4"))))
# External providers are never allowed to block a user action indefinitely.
# The UI acknowledges first; these short network limits keep normal responses
# inside the requested five-second target.
FAST_PROVIDER_TIMEOUT = max(2.0, min(4.0, float(os.environ.get("FAST_PROVIDER_TIMEOUT", "4"))))
TELEGRAM_ACTION_TIMEOUT = max(3.0, min(5.0, float(os.environ.get("TELEGRAM_ACTION_TIMEOUT", "5"))))
OTP_POLL_INTERVAL = max(2, int(os.environ.get("OTP_POLL_INTERVAL", "3")))
temp_mail_lock = threading.RLock()
temp_mail_read_executor = ThreadPoolExecutor(max_workers=TEMP_MAIL_READ_WORKERS)
user_cooldowns = {}
fb_tools_free_usage = {}
pending_withdrawals = {}

# ==========================================
# Telegram API & Helpers
# ==========================================
tg_session = requests.Session() # 🌟 Keep-Alive Connection (Makes bot 10x faster)
try:
    from requests.adapters import HTTPAdapter
    tg_session.mount("https://", HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0))
except Exception:
    pass


#==============================================================================
#  [10]  TELEGRAM API HELPERS & BUTTON EMOJI OVERRIDES
#==============================================================================
def apply_button_emoji_overrides(markup):
    """Apply Admin button-icon overrides to every outgoing keyboard."""
    if not isinstance(markup, (dict, list)):
        return markup
    overrides = bot_settings.get("button_emojis", {})
    if not isinstance(overrides, dict) or not overrides:
        return markup

    def clone(value):
        if isinstance(value, list):
            return [clone(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: clone(item) for key, item in value.items()}
        label = str(result.get("text") or "").strip().casefold()
        label_for_match = label
        for legacy_emoji in GLOBAL_BODY_EMOJIS:
            label_for_match = label_for_match.replace(legacy_emoji.casefold(), "")
        label_for_match = re.sub(r"[ \t]{2,}", " ", label_for_match).strip()
        if label_for_match:
            for configured_name, emoji_id in sorted(overrides.items(), key=lambda item: len(str(item[0])), reverse=True):
                configured_name = str(configured_name).strip().casefold()
                if label_for_match == configured_name or label_for_match.startswith(configured_name + " "):
                    # Replacement mode: the new custom icon replaces the old
                    # icon instead of being added beside it.
                    result.pop("icon_custom_emoji_id", None)
                    result["icon_custom_emoji_id"] = str(emoji_id)
                    old_text = str(result.get("text") or "")
                    old_text = re.sub(r"<tg-emoji[ \t]+emoji-id=[^>]+>.*?</tg-emoji>", "", old_text, flags=re.IGNORECASE | re.DOTALL)
                    for legacy_emoji in GLOBAL_BODY_EMOJIS:
                        old_text = old_text.replace(legacy_emoji, "")
                    result["text"] = re.sub(r"[ \t]{2,}", " ", old_text).strip()
                    break
        return result

    return clone(markup)


def api_call(method, payload=None):
    url = f"{BASE_URL}/{method}"
    request_payload = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(request_payload, dict) and "reply_markup" in request_payload:
        request_payload["reply_markup"] = apply_button_emoji_overrides(request_payload["reply_markup"])
    try:
        # Long polling needs a socket timeout longer than getUpdates' 50s wait.
        # All interactive Telegram actions use a bounded timeout so a slow
        # network cannot make a button appear frozen.
        request_timeout = 65 if str(method).startswith("getUpdates") else TELEGRAM_ACTION_TIMEOUT
        res = tg_session.post(url, json=request_payload, timeout=request_timeout)
        return res.json()
    except Exception as e:
        return {}

# Process-level cache: both valid fallback characters and failed IDs are cached.
custom_emoji_validation_cache = {}
# The built-in UI packs are already known locally. Pre-seeding them avoids a
# Telegram validation round-trip on the first button click after restart.
for _body_char, _body_id in GLOBAL_BODY_EMOJIS.items():
    if str(_body_id).isdigit():
        custom_emoji_validation_cache[str(_body_id)] = _body_char
for _pem_value in PEM.values():
    for _pem_id, _pem_fallback in re.findall(r"<tg-emoji\\s+emoji-id=['\"]([0-9]+)['\"]>(.*?)</tg-emoji>", str(_pem_value), flags=re.IGNORECASE | re.DOTALL):
        custom_emoji_validation_cache.setdefault(str(_pem_id), _pem_fallback)


def validate_premium_ids(ids):
    """Validate any number of IDs in Telegram's 200-ID API batches."""
    unique_ids = []
    seen = set()
    for raw_id in ids or []:
        emoji_id = normalize_local_digits(str(raw_id or "")).strip()
        if emoji_id.isdigit() and emoji_id not in seen:
            seen.add(emoji_id)
            unique_ids.append(emoji_id)
    valid = {}
    invalid = []
    errors = []
    for start in range(0, len(unique_ids), 200):
        result = validate_custom_emoji_ids(
            unique_ids[start:start + 200],
            api_call,
            cache=custom_emoji_validation_cache,
            max_ids=200,
        )
        valid.update(result.get("valid", {}))
        invalid.extend(result.get("invalid", []))
        if result.get("error"):
            errors.append(str(result["error"]))
    invalid = list(dict.fromkeys(invalid))
    errors = list(dict.fromkeys(errors))
    return {
        "ok": not invalid and not errors,
        "valid": valid,
        "invalid": invalid,
        "error": "; ".join(errors),
        "requested": unique_ids,
    }


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
    result = api_call("editMessageText", payload)
    # Board cards now travel as photos. A photo message carries no editable
    # text, so opening a classic text screen over it would fail with
    # "there is no text in the message to edit" — replace the photo instead
    # of breaking the navigation.
    if result and not result.get("ok") and "no text in the message to edit" in str(result.get("description", "")).lower():
        try:
            delete_message(chat_id, message_id)
        except Exception:
            pass
        return send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    return result

def delete_message(chat_id, message_id):
    return api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def answer_callback(callback_id, text="", show_alert=False):
    api_call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": show_alert})

def send_document(chat_id, filename, text_content):
    url = f"{BASE_URL}/sendDocument"
    files = {'document': (filename, text_content)}
    data = {'chat_id': chat_id}
    try: requests.post(url, data=data, files=files, timeout=TELEGRAM_ACTION_TIMEOUT)
    except: pass

# Local User List to keep update broadcasts off the user database path.
all_known_users = set()
all_known_users_ready = threading.Event()

#==============================================================================
#  [11]  USERS SYNC & REGISTRATION
#==============================================================================
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
    except Exception:
        pass
    finally:
        all_known_users_ready.set()

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

#==============================================================================
#  [12]  BROADCASTING ENGINE
#==============================================================================
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


def broadcast_premium_message(from_chat_id, msg_id, message, prepared=None):
    """Broadcast a rebuilt Premium Emoji message without downloading media."""
    prepared = prepared or build_premium_broadcast_payload(message, validate_premium_ids)
    if prepared.get("use_copy"):
        return broadcast_copymessage(from_chat_id, msg_id)
    if not prepared.get("ok"):
        return {"ok": False, "error": prepared.get("error", "Invalid broadcast message.")}

    success = 0
    failed = 0
    users = list(all_known_users)
    method = prepared["method"]
    url = f"{BASE_URL}/{method}"
    b_session = requests.Session()
    for user_id in users:
        payload = dict(prepared.get("payload") or {})
        payload["chat_id"] = user_id
        try:
            res = b_session.post(url, json=payload, timeout=5).json()
            if res.get("ok"):
                success += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(0.035)
    send_message(
        from_chat_id,
        render_body_text(
            f"📢 <b>Broadcast Completed!</b>\n"
            f"✅ Success: {success}\n❌ Failed: {failed}\n"
            f"👥 Total Sent: {len(users)}"
        ),
    )
    return {"ok": True, "success": success, "failed": failed, "total": len(users), "method": method}



#==============================================================================
#  [13]  TEXT & BRAND RENDERING
#==============================================================================
def render_body_text(text):
    if not text:
        return str(text)
    raw_text = str(text)
    # Explicit IDs are compiled only from the process cache here. New IDs are
    # validated by the relevant admin save/broadcast flow before persistence.
    cached_ids = premium_emoji_ids_in_text(raw_text)
    cached_map = {
        emoji_id: custom_emoji_validation_cache[emoji_id]
        for emoji_id in cached_ids
        if isinstance(custom_emoji_validation_cache.get(emoji_id), str)
        and custom_emoji_validation_cache.get(emoji_id)
    }
    if cached_map:
        raw_text = compile_premium_emoji_syntax(raw_text, cached_map)
    angle_ids = angle_custom_emoji_ids_in_text(raw_text)
    angle_map = {
        emoji_id: custom_emoji_validation_cache[emoji_id]
        for emoji_id in angle_ids
        if isinstance(custom_emoji_validation_cache.get(emoji_id), str)
        and custom_emoji_validation_cache.get(emoji_id)
    }
    uncached_angle_ids = [emoji_id for emoji_id in angle_ids if emoji_id not in custom_emoji_validation_cache]
    if uncached_angle_ids:
        angle_result = validate_premium_ids(uncached_angle_ids)
        angle_map.update(angle_result.get("valid", {}))
    if angle_ids:
        raw_text = compile_angle_custom_emoji_syntax(raw_text, angle_map)
    body_emoji_map = bot_settings.get("body_emojis") or GLOBAL_BODY_EMOJIS
    # Re-map legacy hardcoded PEM tags through the editable body-emoji map.
    fixed_body_ids = set(str(value) for value in GLOBAL_BODY_EMOJIS.values())
    fixed_body_ids.update(custom_emoji_ids_in_html("".join(str(value) for value in PEM.values())))
    def remap_legacy_body_tag(match):
        emoji_id, fallback = match.group(1), match.group(2)
        replacement_id = body_emoji_map.get(fallback)
        if emoji_id in fixed_body_ids and str(replacement_id or "").isdigit():
            return f'<tg-emoji emoji-id="{replacement_id}">{fallback}</tg-emoji>'
        return match.group(0)
    raw_text = re.sub(r'<tg-emoji\s+emoji-id=["\']([0-9]+)["\']>(.*?)</tg-emoji>', remap_legacy_body_tag, raw_text, flags=re.IGNORECASE | re.DOTALL)
    parts = re.split(r'(<tg-emoji.*?</tg-emoji>)', raw_text, flags=re.DOTALL)
    for i in range(len(parts)):
        if not parts[i].startswith('<tg-emoji'):
            for normal_emj, prem_id in body_emoji_map.items():
                if normal_emj in parts[i] and str(prem_id).isdigit():
                    parts[i] = parts[i].replace(normal_emj, f'<tg-emoji emoji-id="{prem_id}">{normal_emj}</tg-emoji>')
    return "".join(parts)


def _brand_custom_tag_pattern():
    return re.compile(r'''<tg-emoji +emoji-id=["']([0-9]+)["']>(.*?)</tg-emoji>''', re.IGNORECASE | re.DOTALL)


def _safe_brand_html(value):
    """Keep valid custom-emoji tags and remove malformed markup from the brand."""
    raw = html.unescape(str(value or "")).strip()
    tags = {}

    def hold_tag(match):
        key = f"__BRAND_TAG_{len(tags)}__"
        tags[key] = match.group(0)
        return key

    held = _brand_custom_tag_pattern().sub(hold_tag, raw)
    # Do not expose a stale or incomplete tag saved by an older deployment.
    held = re.sub(r"<tg-emoji\b[^>]*$", "", held, flags=re.IGNORECASE)
    held = re.sub(r"</?tg-emoji\b[^>]*>", "", held, flags=re.IGNORECASE)
    safe = html.escape(held)
    for key, tag in tags.items():
        safe = safe.replace(html.escape(key), tag)
    return safe


def get_brand_name_html():
    """Dynamic brand/name shown in user and OTP cards, configurable from Admin Panel."""
    name = _safe_brand_html(bot_settings.get("brand_name", "Versia SMS 🔥") or "Versia SMS 🔥")
    return render_body_text(name)


def get_brand_name_plain(limit=28):
    """Return a plain preview-safe fallback without changing the Telegram profile name."""
    raw = html.unescape(str(bot_settings.get("brand_name", "Versia SMS 🔥") or "Versia SMS 🔥"))
    raw = _brand_custom_tag_pattern().sub(lambda match: match.group(2), raw)
    # Strip both complete and stale incomplete tags before using plain previews.
    raw = re.sub(r"</?tg-emoji\b[^>]*>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<tg-emoji\b[^>]*$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]*>", "", raw).strip()
    raw = html.unescape(raw)
    return (raw[:limit] + "…") if len(raw) > limit else raw


def brand_header():
    name = get_brand_name_html().strip()
    return f"{name}\n" if name else ""


def render_custom_menu_body(menu_key, msg, replacements=None, trusted_html=None):
    """Render a menu body: an admin-saved body wins; otherwise screens in
    DEFAULT_MENU_GRIDS draw the bordered grid table so the whole bot shares
    one table style. Finished <pre>/<code> blocks are shielded from the
    emoji conversion exactly like the card templates."""
    c_msg = _menu_body_block(menu_key)
    raw = str(c_msg.get("text", "") or "")
    if menu_key == "start" and (raw.startswith("╔════════") or "Choose an option below" in raw):
        raw = ""
        c_msg["text"] = ""
    if not raw.strip():
        spec = DEFAULT_MENU_GRIDS.get(menu_key)
        specs = _menu_grid_specs(menu_key, msg, replacements)
        if specs:
            footer = _menu_grid_footer(spec, replacements)
            # Title joins the table inside the single <pre> block; user-derived
            # values are pre-escaped here and _pre_plain_text keeps the
            # entities intact inside the block.
            title_values = {
                key: html.escape(str(val))
                for key, val in _menu_grid_values(msg, replacements).items()
                if key != "brand_name"
            }
            return _menu_grid(_menu_grid_title(spec.get("title", menu_key.upper()), title_values), specs, footer)
    user = (msg or {}).get("from", {})
    first_name = str(user.get("first_name") or "User")
    last_name = str(user.get("last_name") or "")
    full_name = (first_name + (" " + last_name if last_name else "")).strip()
    username = str(user.get("username") or "")
    raw = render_menu_placeholders(
        raw,
        first_name=first_name,
        full_name=full_name,
        username=("@" + username if username and not username.startswith("@") else username),
        user_id=(msg or {}).get("chat", {}).get("id", ""),
        brand_name_html=get_brand_name_html(),
        replacements=replacements,
    )
    for key, value in (trusted_html or {}).items():
        raw = raw.replace("{" + str(key) + "}", str(value))
    return _hold_and_render([raw])


#==============================================================================
#  [14]  PREMIUM MEMBERSHIP SYSTEM
#==============================================================================
def _premium_users_store():
    store = bot_settings.setdefault("premium_users", {})
    if not isinstance(store, dict):
        store = {}
        bot_settings["premium_users"] = store
    return store


def _premium_record(user_id):
    return _premium_users_store().get(str(user_id)) or {}


def _premium_expiry_ts(user_id):
    rec = _premium_record(user_id)
    try:
        return float(rec.get("expires_at", 0) or 0)
    except Exception:
        return 0.0


def is_premium_user(user_id):
    if is_admin(user_id):
        return True
    expires_at = _premium_expiry_ts(user_id)
    if expires_at and expires_at > time.time():
        return True
    if expires_at and str(user_id) in _premium_users_store():
        revoke_premium_user(user_id, notify=True, reason="expired")
    return False


def premium_days_left(user_id):
    expires_at = _premium_expiry_ts(user_id)
    if not expires_at:
        return 0
    return max(0, int((expires_at - time.time() + 86399) // 86400))


def grant_premium_user(user_id, days, admin_id=None):
    days = max(1, int(days))
    expires_at = time.time() + days * 86400
    _premium_users_store()[str(user_id)] = {
        "expires_at": expires_at,
        "days": days,
        "added_at": time.time(),
        "added_by": str(admin_id or ""),
    }
    save_db()
    try:
        send_message(
            user_id,
            render_body_text(
                f"✅ <b>Premium access activated.</b>\n\n"
                f"Your premium access is active for <b>{days}</b> day(s).\n"
                f"Expires on: <code>{datetime.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')}</code>"
            )
        )
    except Exception:
        pass
    return expires_at


def revoke_premium_user(user_id, notify=False, reason="removed"):
    existed = _premium_users_store().pop(str(user_id), None)
    if existed:
        save_db()
        if notify:
            text = "Your premium access has expired." if reason == "expired" else "Your premium access has been removed."
            try:
                send_message(user_id, render_body_text(f"⚠️ <b>{text}</b>"))
            except Exception:
                pass
    return bool(existed)


def cleanup_expired_premium_users():
    now = time.time()
    expired = []
    for uid, rec in list(_premium_users_store().items()):
        try:
            if float(rec.get("expires_at", 0) or 0) <= now:
                expired.append(uid)
        except Exception:
            expired.append(uid)
    for uid in expired:
        revoke_premium_user(uid, notify=True, reason="expired")
    return expired


def premium_expiry_monitor():
    while True:
        try:
            cleanup_expired_premium_users()
        except Exception as e:
            print(f"[Premium] expiry monitor error: {e}")
        time.sleep(3600)


def premium_required_text():
    return render_body_text(
        "🔒 <b>Premium access required.</b>\n\n"
        "Premium numbers are available only for users with active premium access. "
        "Please contact support to activate premium access."
    )


def _premium_support_link():
    return str(bot_settings.get("premium_support_link") or bot_settings.get("support_link") or "").strip()


def _premium_support_button():
    link = _premium_support_link()
    btn = {"text": "Contact Support", "icon_custom_emoji_id": "5337302974806922068", "style": "primary"}
    if link:
        btn["url"] = link
    else:
        btn["callback_data"] = "ux_support"
    return btn


def _premium_support_markup(back_cb="ux_get_number"):
    return {"inline_keyboard": [
        [_premium_support_button()],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": back_cb, "style": "danger"}],
    ]}


def show_premium_required(chat_id, message_id=None):
    markup = _premium_support_markup("ux_get_number")
    if message_id:
        return edit_message(chat_id, message_id, premium_required_text(), reply_markup=markup)
    return send_message(chat_id, premium_required_text(), reply_markup=markup)


def _premium_number_plans():
    plans = bot_settings.get("premium_number_plans", [])
    if not isinstance(plans, list) or not plans:
        return [
            {"label": "1 DAY - 1 USD", "days": 1, "price": "1 USD"},
            {"label": "7 DAYS - 3 USD", "days": 7, "price": "3 USD"},
            {"label": "30 DAYS - 10 USD", "days": 30, "price": "10 USD"},
        ]
    return [plan for plan in plans if isinstance(plan, dict) and int(plan.get("days", 0) or 0) > 0]


def _premium_number_plan(index):
    plans = _premium_number_plans()
    try:
        return plans[int(index)]
    except (IndexError, TypeError, ValueError):
        return None


def show_premium_number_plan_menu(chat_id, message_id=None):
    rows = []
    for index, plan in enumerate(_premium_number_plans()):
        label = str(plan.get("label") or f"{plan.get('days', 1)} DAYS - {plan.get('price', '')}")
        rows.append([ui_button(label, "premium", f"pn_plan:{index}", style="primary")])
    rows.append([ui_button("BACK", "back", "ux_get_number", style="danger")])
    txt = render_body_text("💎 <b>PREMIUM NUMBER</b>\n\nSelect a plan to continue with payment.")
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_premium_number_payment(chat_id, plan_index, message_id=None):
    plan = _premium_number_plan(plan_index)
    if not plan:
        return show_premium_number_plan_menu(chat_id, message_id)
    text = render_body_text(
        "💎 <b>PREMIUM NUMBER PAYMENT</b>\n\n"
        f"<b>Plan:</b> {html.escape(str(plan.get('label', '')))}\n"
        f"<b>Duration:</b> {int(plan.get('days', 1))} day(s)\n"
        f"<b>Price:</b> {html.escape(str(plan.get('price', '')))}\n\n"
        "Pay using the configured payment method, then send the payment screenshot. "
        "A transaction ID will be requested next."
    )
    rows = [[ui_button("SEND PAYMENT SCREENSHOT", "premium", f"pn_payment:{plan_index}", style="success")], [ui_button("BACK", "back", "pn_back", style="danger")]]
    return _send_or_edit(chat_id, text, {"inline_keyboard": rows}, message_id)


def _premium_number_requests_store():
    store = bot_settings.setdefault("premium_number_requests", {})
    if not isinstance(store, dict):
        store = {}
        bot_settings["premium_number_requests"] = store
    return store


def _premium_number_admin_request_keyboard(request_id):
    return {"inline_keyboard": [[
        ui_button("APPROVE", "ok", f"pnapprove:{request_id}", style="success"),
        ui_button("REJECT", "no", f"pnreject:{request_id}", style="danger"),
    ]]}


def _premium_number_submit_request(user_id, plan_index, screenshot_id, transaction_id):
    plan = _premium_number_plan(plan_index)
    if not plan:
        return None
    request_id = uuid.uuid4().hex[:10].upper()
    record = {
        "request_id": request_id,
        "user_id": int(user_id),
        "plan_index": int(plan_index),
        "plan": dict(plan),
        "screenshot_id": screenshot_id,
        "transaction_id": transaction_id,
        "status": "PENDING",
        "created_at": time.time(),
    }
    _premium_number_requests_store()[request_id] = record
    save_db()
    return record


def _notify_premium_number_admins(record):
    plan = record.get("plan", {})
    caption = render_body_text(
        "💎 <b>NEW PREMIUM NUMBER REQUEST</b>\n\n"
        f"<b>Request:</b> <code>{html.escape(str(record.get('request_id')))}</code>\n"
        f"<b>User ID:</b> <code>{record.get('user_id')}</code>\n"
        f"<b>Plan:</b> {html.escape(str(plan.get('label', '')))}\n"
        f"<b>Transaction ID:</b> <code>{html.escape(str(record.get('transaction_id', '')))}</code>"
    )
    for admin_id in bot_settings.get("admins", []):
        try:
            if record.get("screenshot_id"):
                send_photo(admin_id, record["screenshot_id"], caption=caption, reply_markup=_premium_number_admin_request_keyboard(record["request_id"]))
            else:
                send_message(admin_id, caption, reply_markup=_premium_number_admin_request_keyboard(record["request_id"]))
        except Exception:
            pass


def show_premium_number_requests(chat_id, message_id=None):
    pending = [item for item in _premium_number_requests_store().values() if isinstance(item, dict) and item.get("status") == "PENDING"]
    if not pending:
        text = render_body_text("💎 <b>PREMIUM NUMBER REQUESTS</b>\n\nNo pending requests.")
    else:
        lines = ["💎 <b>PREMIUM NUMBER REQUESTS</b>", ""]
        for item in pending:
            lines.append(f"<b>{html.escape(str(item.get('request_id')))}</b> — User <code>{item.get('user_id')}</code> — {html.escape(str(item.get('plan', {}).get('label', '')))}")
        text = render_body_text("\n".join(lines))
    return _send_or_edit(chat_id, text, {"inline_keyboard": [[ui_button("BACK", "back", "premium_manage", style="danger")]]}, message_id)


def _handle_premium_number_payment_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    state = user_states.get(chat_id)
    if state not in {"pn_wait_screenshot", "pn_wait_txid"}:
        return False
    if state == "pn_wait_screenshot":
        screenshot_id = ""
        if msg.get("photo"):
            screenshot_id = msg["photo"][-1].get("file_id", "")
        elif msg.get("document", {}).get("mime_type", "").startswith("image/"):
            screenshot_id = msg.get("document", {}).get("file_id", "")
        if not screenshot_id:
            send_message(chat_id, render_body_text("Please send an image payment screenshot."), reply_markup=get_cancel_kb())
            return True
        temp_data.setdefault(chat_id, {})["screenshot_id"] = screenshot_id
        user_states[chat_id] = "pn_wait_txid"
        send_message(chat_id, render_body_text("🔖 Now send the payment Transaction ID."), reply_markup=get_cancel_kb())
        return True
    transaction_id = str(msg.get("text") or "").strip()
    if len(transaction_id) < 4:
        send_message(chat_id, render_body_text("Send a valid Transaction ID."), reply_markup=get_cancel_kb())
        return True
    data = temp_data.get(chat_id, {})
    record = _premium_number_submit_request(chat_id, data.get("plan_index", 0), data.get("screenshot_id", ""), transaction_id)
    user_states.pop(chat_id, None)
    temp_data.pop(chat_id, None)
    if not record:
        send_message(chat_id, render_body_text("The selected Premium Number plan is no longer available."))
        return True
    _notify_premium_number_admins(record)
    send_message(chat_id, render_body_text("✅ Premium Number request submitted. Wait for Admin approval."), reply_markup=main_menu(chat_id))
    return True


def premium_unavailable_text():
    return render_body_text(
        f"{ui_emoji('no')} <b>Premium number is not available right now.</b>\n\n"
        "Please contact support for premium stock or premium access help."
    )


def show_premium_unavailable(chat_id, message_id=None, back_cb="ux_get_number"):
    markup = _premium_support_markup(back_cb)
    if message_id:
        return edit_message(chat_id, message_id, premium_unavailable_text(), reply_markup=markup)
    return send_message(chat_id, premium_unavailable_text(), reply_markup=markup)


#==============================================================================
#  [15]  PREMIUM CALLBACK CHECKS & CUSTOM EMOJI PACK TOOLS
#==============================================================================
def _callback_batch_category(data):
    if not str(data).startswith("batch_get:"):
        return None
    batch_id = str(data).split(":", 1)[1]
    batch = number_batches.get(batch_id) or {}
    return _batch_category(batch) if batch else None


def callback_requires_premium(data):
    data = str(data or "")
    if data == "ux_premium_number":
        return True
    if data.startswith("gsc:PREMIUM") or data.startswith("gcc:PREMIUM") or data.startswith("cnc:PREMIUM"):
        return True
    return _callback_batch_category(data) == "PREMIUM"

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

def premium_emoji_items_from_message(msg):
    """Extract custom emoji entities and custom-emoji sticker IDs from one update."""
    items = []
    for entity in custom_emoji_entities(msg or {}):
        items.append({"id": str(entity["id"]), "fallback": entity.get("fallback") or "✅"})
    sticker = (msg or {}).get("sticker") or {}
    sticker_id = normalize_local_digits(str(sticker.get("custom_emoji_id", ""))).strip()
    if sticker_id and sticker_id.isdigit():
        items.append({"id": sticker_id, "fallback": sticker.get("emoji") or "✅"})
    unique = []
    seen = set()
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return unique


def custom_emoji_pack_name_from_link(value):
    """Return the sticker-set short name from a public addemoji link."""
    raw = str(value or "").strip()
    match = re.fullmatch(
        r"(?:https?://)?(?:t[.]me|telegram[.]me)/addemoji/([A-Za-z0-9_]+)(?:/)?(?:[?].*)?",
        raw,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def get_custom_emoji_pack_from_link(value):
    """Resolve an addemoji link through Telegram's Bot API getStickerSet."""
    short_name = custom_emoji_pack_name_from_link(value)
    if not short_name:
        return {"ok": False, "error": "Send a valid link like https://t.me/addemoji/PackName"}
    response = api_call("getStickerSet", {"name": short_name})
    if not response.get("ok"):
        return {
            "ok": False,
            "error": str(response.get("description") or "Telegram could not open this emoji pack."),
            "short_name": short_name,
        }
    pack = response.get("result") or {}
    stickers = pack.get("stickers") or []
    items = []
    seen = set()
    for sticker in stickers:
        if not isinstance(sticker, dict):
            continue
        emoji_id = normalize_local_digits(str(sticker.get("custom_emoji_id") or "")).strip()
        if not emoji_id.isdigit() or emoji_id in seen:
            continue
        seen.add(emoji_id)
        items.append({"id": emoji_id, "fallback": str(sticker.get("emoji") or "✅")})
    return {
        "ok": True,
        "short_name": short_name,
        "title": str(pack.get("title") or short_name),
        "sticker_type": str(pack.get("sticker_type") or ""),
        "items": items,
    }


def custom_emoji_pack_messages(pack, chunk_size=3500):
    """Build HTML messages listing every custom emoji ID in a pack."""
    items = pack.get("items") or []
    lines = [
        f"{PEM['star']} <b>Premium Emoji Pack IDs</b>",
        f"<b>Pack:</b> {html.escape(str(pack.get('title') or pack.get('short_name') or 'Unknown'))}",
        f"<b>Total IDs:</b> <code>{len(items)}</code>",
        "",
    ]
    for index, item in enumerate(items, 1):
        emoji_id = str(item.get("id"))
        fallback = html.escape(str(item.get("fallback") or "✅"))
        entity = f'<tg-emoji emoji-id="{html.escape(emoji_id, quote=True)}">{fallback}</tg-emoji>'
        lines.append(f"<b>{index}.</b> {entity} — <code>{html.escape(emoji_id)}</code>")
    chunks = []
    current = ""
    for line in lines:
        candidate = line if not current else current + "\n" + line
        if current and len(candidate) > chunk_size:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [f"{PEM['no']} No custom emoji IDs were found in this pack."]


def compile_admin_premium_input(msg):
    """Compile custom emoji syntax while leaving invalid angle IDs as text."""
    raw = extract_premium_html(msg)
    strict_ids = premium_emoji_ids_in_text(raw) + custom_emoji_ids_in_html(raw)
    angle_ids = angle_custom_emoji_ids_in_text(raw)
    fallback_map = {}
    if strict_ids:
        strict_result = validate_premium_ids(strict_ids)
        if not strict_result.get("ok"):
            invalid = ", ".join(strict_result.get("invalid") or strict_ids)
            detail = strict_result.get("error") or "Invalid custom-emoji ID."
            raise ValueError(f"Invalid custom-emoji ID(s): {invalid}. {detail}")
        fallback_map.update(strict_result.get("valid", {}))
    if angle_ids:
        # Angle-bracket IDs are deliberately lenient: valid IDs become custom
        # emojis, while invalid IDs remain visible as the original <ID> text.
        angle_result = validate_premium_ids(angle_ids)
        fallback_map.update(angle_result.get("valid", {}))
    if not strict_ids and not angle_ids:
        return raw
    compiled = compile_premium_html(raw, fallback_map)
    return compile_angle_custom_emoji_syntax(compiled, fallback_map)


def compile_dynamic_name_input(msg):
    """Compile the complete Dynamic Name without an application-side length cap."""
    compiled = compile_admin_premium_input(msg).strip()
    if not compiled:
        raise ValueError("Empty dynamic name")
    return compiled


#==============================================================================
#  [16]  NUMBER, FLAG & REWARD UTILITIES
#==============================================================================
def get_flag_info_from_num(num):
    clean = re.sub(r'\D', '', str(num))
    code_rows = []
    for key, data in bot_settings.get("premium_flags", {}).items():
        if not isinstance(data, dict):
            continue
        code = str(data.get("code") or (key if str(key).isdigit() else "")).strip()
        if code and code.isdigit():
            code_rows.append((code, data))
    # Longest dialing prefixes first, so 880 wins over 8/88, etc.
    for code, data in sorted(code_rows, key=lambda x: len(x[0]), reverse=True):
        if clean.startswith(code):
            return data.get("char", "🌍"), data.get("iso", "XX"), data.get("id")
    return "🌍", "XX", None

def get_flag_and_code(num):
    char, iso, _ = get_flag_info_from_num(num)
    return char, iso


def clean_number_key(num):
    return re.sub(r'\D', '', str(num or ''))


def batch_otp_reward(batch_id):
    try:
        return float(number_batches.get(batch_id, {}).get("otp_reward", bot_settings.get("otp_reward", 0.0)) or 0.0)
    except Exception:
        return float(bot_settings.get("otp_reward", 0.0) or 0.0)


def reward_for_session_number(user_id, num):
    """Return per-upload reward for active or 24-hour Facebook Tools numbers.
    Falls back to the global OTP reward for API/dynamic numbers.
    """
    default = float(bot_settings.get("otp_reward", 0.0) or 0.0)
    clean = clean_number_key(num)
    session = user_active_sessions.get(user_id, {})
    rewards = session.get("reward_by_num", {}) if isinstance(session, dict) else {}
    if isinstance(rewards, dict):
        for assigned_num, reward in rewards.items():
            assigned_clean = clean_number_key(assigned_num)
            if assigned_clean and (assigned_clean == clean or (len(assigned_clean) >= 8 and assigned_clean.endswith(clean[-8:])) or (len(clean) >= 8 and clean.endswith(assigned_clean[-8:]))):
                try:
                    return float(reward)
                except Exception:
                    return default
    return _fb_reward_for_number(user_id, num, default)


#==============================================================================
#  [17]  FACEBOOK TOOLS — RECORDS & SESSION HELPERS
#==============================================================================
def _fb_record_list(user_id):
    store = fb_tools_sessions.setdefault(str(user_id), {"records": []})
    if isinstance(store, list):
        store = {"records": store}
        fb_tools_sessions[str(user_id)] = store
    if not isinstance(store, dict):
        store = {"records": []}
        fb_tools_sessions[str(user_id)] = store
    records = store.setdefault("records", [])
    if not isinstance(records, list):
        records = []
        store["records"] = records
    return records


def _fb_cleanup_tool_sessions(save=False):
    now = time.time()
    changed = False
    for uid in list(fb_tools_sessions.keys()):
        records = _fb_record_list(uid)
        kept = []
        for rec in records:
            try:
                if float(rec.get("expires_at", 0) or 0) > now:
                    kept.append(rec)
            except Exception:
                changed = True
        if len(kept) != len(records):
            changed = True
        if kept:
            fb_tools_sessions[str(uid)] = {"records": kept}
        else:
            fb_tools_sessions.pop(str(uid), None)
    if changed and save:
        save_local_db()
    return changed


def _fb_numbers_match(first, second):
    try:
        return _numbers_match(first, second)
    except Exception:
        left = clean_number_key(first)
        right = clean_number_key(second)
        if not left or not right:
            return False
        return left == right or (len(left) >= 8 and left.endswith(right[-8:])) or (len(right) >= 8 and right.endswith(left[-8:]))


def _fb_find_matching_records(user_id, number):
    _fb_cleanup_tool_sessions(save=False)
    matches = []
    for rec in _fb_record_list(user_id):
        for assigned in rec.get("numbers", []) or []:
            if _fb_numbers_match(assigned, number):
                matches.append(rec)
                break
    return matches


def _find_fb_tool_owners(number):
    _fb_cleanup_tool_sessions(save=False)
    owners = []
    for uid, store in list(fb_tools_sessions.items()):
        records = store.get("records", []) if isinstance(store, dict) else (store if isinstance(store, list) else [])
        for rec in records:
            try:
                if float(rec.get("expires_at", 0) or 0) <= time.time():
                    continue
            except Exception:
                continue
            for assigned in rec.get("numbers", []) or []:
                if _fb_numbers_match(assigned, number):
                    try:
                        owners.append(int(uid))
                    except Exception:
                        owners.append(uid)
                    break
            if str(uid) in {str(x) for x in owners}:
                break
    return list(dict.fromkeys(owners))


def _fb_reward_for_number(user_id, num, default=0.0):
    for rec in _fb_find_matching_records(user_id, num):
        rewards = rec.get("reward_by_num", {}) or {}
        if isinstance(rewards, dict):
            for assigned_num, reward in rewards.items():
                if _fb_numbers_match(assigned_num, num):
                    try:
                        return float(reward)
                    except Exception:
                        return default
    return default


def _fb_remember_numbers(chat_id, nums, reward_by_num=None, service="FACEBOOK", country="", mode="free", category="FREE"):
    clean_nums = []
    for num in nums or []:
        clean = clean_number_key(num)
        if clean and clean not in clean_nums:
            clean_nums.append(clean)
    if not clean_nums:
        return False
    now = time.time()
    record = {
        "numbers": clean_nums,
        "reward_by_num": reward_by_num or {},
        "service": str(service or "FACEBOOK"),
        "country": str(country or ""),
        "mode": str(mode or "free"),
        "category": _normalize_stock_category(category),
        "created": now,
        "expires_at": now + FB_TOOLS_SESSION_TTL,
    }
    try:
        with api_session_lock:
            api_session = api_number_sessions.get(chat_id) or {}
            assignments = []
            for assignment in api_session.get("assignments", []) or []:
                if any(_fb_numbers_match(assignment.get("number"), n) for n in clean_nums):
                    copied = dict(assignment)
                    copied.setdefault("service", str(service or "FACEBOOK"))
                    copied.setdefault("country", str(country or ""))
                    copied.setdefault("category", _normalize_stock_category(category))
                    assignments.append(copied)
            if assignments:
                record["api_assignments"] = assignments
                record["panel_id"] = assignments[0].get("panel_id", "")
                record["panel_name"] = assignments[0].get("panel_name", "API Panel")
                api_session["expires_at"] = now + FB_TOOLS_SESSION_TTL
                api_session["fb_tools"] = True
                api_number_sessions[chat_id] = api_session
    except Exception:
        pass
    records = _fb_record_list(chat_id)
    records.append(record)
    fb_tools_sessions[str(chat_id)] = {"records": records[-100:]}
    save_local_db()
    return True


def _fb_api_sessions():
    _fb_cleanup_tool_sessions(save=False)
    sessions = []
    for uid, store in list(fb_tools_sessions.items()):
        records = store.get("records", []) if isinstance(store, dict) else (store if isinstance(store, list) else [])
        for rec in records:
            assignments = [dict(x) for x in (rec.get("api_assignments") or []) if isinstance(x, dict)]
            if not assignments:
                continue
            try:
                user_id = int(uid)
            except Exception:
                user_id = uid
            sessions.append({
                "user_id": user_id,
                "range": assignments[0].get("range", ""),
                "panel_id": assignments[0].get("panel_id", rec.get("panel_id", "")),
                "panel_name": assignments[0].get("panel_name", rec.get("panel_name", "API Panel")),
                "assignments": assignments,
                "numbers": rec.get("numbers", []),
                "reward_by_num": rec.get("reward_by_num", {}),
                "category": rec.get("category", "FREE"),
                "service": rec.get("service", "FACEBOOK"),
                "country": rec.get("country", ""),
                "created": rec.get("created", time.time()),
                "expires_at": rec.get("expires_at", time.time()),
                "fb_tools": True,
            })
    return sessions


def get_flag_info_html(num_or_iso):
    query_raw = str(num_or_iso or "").strip()
    query = query_raw.upper()
    flags = bot_settings.get("premium_flags", {})

    for _, data in flags.items():
        if not isinstance(data, dict):
            continue
        iso = str(data.get("iso", "")).upper()
        name = str(data.get("name", "")).upper()
        if query and (query == iso or query == name or query in name or name in query):
            eid = data.get("id")
            char = data.get("char", "🌍")
            return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>' if eid else char

    char, _, eid = get_flag_info_from_num(query_raw)
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
    return char

def mask_number(num):
    clean = num.replace("+", "").replace(" ", "")
    if len(clean) > 6: return f"{clean[:3]}❖DXA❖{clean[-3:]}"
    elif len(clean) > 2: return f"{clean[:1]}❖DXA❖{clean[-1:]}"
    return clean

# ==========================================
# 🌟 ADVANCED SERVICE & LANGUAGE DETECTION
# ==========================================

SERVICE_SMS_KEYWORDS = {
    # 🟢 Social Media & Chat (Added Arabic Keywords)
    "whatsapp": ["whatsapp", "wa", "wap", "w/a", "whatsapp business", "wa.me", "wa code", "wh", "واتساب", "واتساپ", "واٹس ایپ", "व्हाट्सएप", "वाट्सएप", "वॉट्सऐप", "व्हाट्सप्प", "ватсап", "уотсап", "вотсап", "ватс апп", "వాట్సాప్", "വാട്‌സ്ആപ്പ്", "வாட்ஸ்அப்", "ವಾಟ್ಸಾಪ್", "વોટ્સએપ", "ਵਟਸਐਪ", "ହ୍ଵାଟସ୍ ଆପ୍", "වට්ස්ඇප්", "วอตส์แอปป์", "วอทส์แอพ", "ဝက်စ်အက်ပ်", "វ៉តសាប់", "ວອດແອັບ", "ワッツアップ", "왓츠앱", "whatsapp的", "whatsapp验证码", "וואטסאפ", "γουάτσαπ", "ዋትስአፕ", "ვოთსאფი", "վոթսափ"],
    "facebook": ["facebook", "fb", "meta", "fbook", "fb code", "facebook code", "فيسبوك", "فيس بوك"],
    "instagram": ["instagram", "insta", "ig", "ig code", "instagram code", "انستغرام", "انستقرام"],
    "telegram": ["telegram", "tg", "tele", "telegram code", "tg code", "t.me", "تيليجرام", "تليجرام"],
    "tiktok": ["tiktok", "tik tok", "tikvideo", "tiktok code", "tik code", "تيك توك"],
    "snapchat": ["snapchat", "snap", "snap code", "سناب شات"],
    "twitter": ["twitter", "x.com", "x code", "twitter code", "تويتر"],
    "discord": ["discord", "discord code", "ديسكورد"],
    "viber": ["viber", "viber code", "فايبر"],
    "line": ["line", "line code", "line verification", "لاين"],
    "wechat": ["wechat", "we chat", "wechat code", "وي تشات"],
    "signal": ["signal", "signal code", "سيجنال"],
    "linkedin": ["linkedin", "linked in", "لينكد إن"],
    "imo": ["imo", "imo code", "imo verification", "ايمو"],
    "kakaotalk": ["kakao", "kakaotalk", "كاكاو"],
    "qq": ["qq", "tencent qq"],
    "vk": ["vk", "vkontakte"],

    # 🔵 Tech & Mail
    "google": ["google", "gmail", "youtube", "g-", "google voice", "جوجل", "غوغل"],
    "microsoft": ["microsoft", "ms", "outlook", "live.com", "hotmail"],
    "apple": ["apple", "icloud", "itunes", "apple id"],
    "yahoo": ["yahoo", "yahoo code", "ymail"],
    "protonmail": ["proton", "protonmail"],

    # 💰 Crypto & Trading
    "binance": ["binance", "bnb", "binances"],
    "coinbase": ["coinbase"],
    "okx": ["okx", "okex"],
    "kucoin": ["kucoin"],
    "bybit": ["bybit"],
    "huobi": ["huobi", "htx"],
    "mexc": ["mexc"],
    "trustwallet": ["trust wallet", "trustwallet"],

    # 💳 Finance & Wallets
    "bkash": ["bkash", "b-kash", "bkash code"],
    "nagad": ["nagad", "nagad code"],
    "rocket": ["rocket", "dutch bangla"],
    "upay": ["upay", "upay code"],
    "paypal": ["paypal", "pay pal"],
    "paytm": ["paytm"],
    "cashapp": ["cash app", "cashapp"],
    "wise": ["wise", "transferwise"],

    # 🛒 E-commerce & Delivery
    "amazon": ["amazon", "amzn", "amazon code"],
    "ebay": ["ebay"],
    "aliexpress": ["aliexpress", "ali express"],
    "alibaba": ["alibaba"],
    "daraz": ["daraz", "daraz code"],
    "foodpanda": ["foodpanda", "food panda"],
    "uber": ["uber", "uber code", "uber verification", "uber eats"],
    "pathao": ["pathao", "pathao ride"],

    # 🎮 Gaming & Entertainment
    "netflix": ["netflix", "netflix code"],
    "spotify": ["spotify", "spotify code"],
    "steam": ["steam", "steam guard"],
    "epicgames": ["epic games", "epicgames"],
    "roblox": ["roblox", "roblox code"],
    "riotgames": ["riot", "riot games", "valorant", "league of legends"],
    "garena": ["garena", "free fire", "freefire"],
    "playstation": ["playstation", "psn"],

    # 🎲 Betting & Casino
    "1xbet": ["1xbet", "1x bet"],
    "melbet": ["melbet", "melbet code"],
    "linebet": ["linebet"],
    "bet365": ["bet365"],
    "megapari": ["megapari"],

    # ❤️ Dating
    "tinder": ["tinder", "tinder code"],
    "bumble": ["bumble"],
    "badoo": ["badoo"]
}

#==============================================================================
#  [18]  SERVICE & LANGUAGE DETECTION
#==============================================================================
def detect_service(text):
    text_lower = str(text).lower()
    for service_key, keywords in SERVICE_SMS_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return service_key.upper()
    return None

def get_service_info_html(service_text, msg_text=""):
    s = str(service_text).upper().strip()
    m = str(msg_text).lower().strip()
    apps = bot_settings.get("premium_apps", {})

    detected_service = s
    if m:
        for service_key, keywords in SERVICE_SMS_KEYWORDS.items():
            for kw in keywords:
                if kw in m:
                    detected_service = service_key.upper()
                    break
            if detected_service != s: break

    clean_s = re.sub(r'[^\w\s]', '', detected_service).strip()

    for app_name, data in apps.items():
        if app_name == detected_service or app_name == clean_s or app_name in detected_service or detected_service in app_name:
            full_name = data.get("name", app_name.title())
            char = data.get("char", "📱")
            eid = data.get("id")
            if eid: return full_name, f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
            return full_name, char

    if len(detected_service) > 20:
        return "Message", "💬"

    return detected_service.title(), "📱"

def detect_language(text):
    if not text: return "#EN"
    text_str = str(text)

    # . Unicode Block     (100% Accurate for scripts)
    if any('\u0600' <= c <= '\u06ff' for c in text_str): return "#AR" # Arabic / Persian / Urdu
    if any('\u0980' <= c <= '\u09ff' for c in text_str): return "#BN" # Bengali
    if any('\u0900' <= c <= '\u097f' for c in text_str): return "#HI" # Hindi / Marathi / Nepali
    if any('\u0a00' <= c <= '\u0a7f' for c in text_str): return "#PA" # Punjabi (Gurmukhi)
    if any('\u0a80' <= c <= '\u0aff' for c in text_str): return "#GU" # Gujarati
    if any('\u0b00' <= c <= '\u0b7f' for c in text_str): return "#OR" # Odia
    if any('\u0b80' <= c <= '\u0bff' for c in text_str): return "#TA" # Tamil
    if any('\u0c00' <= c <= '\u0c7f' for c in text_str): return "#TE" # Telugu
    if any('\u0c80' <= c <= '\u0cff' for c in text_str): return "#KN" # Kannada
    if any('\u0d00' <= c <= '\u0d7f' for c in text_str): return "#ML" # Malayalam
    if any('\u0d80' <= c <= '\u0dff' for c in text_str): return "#SI" # Sinhala
    if any('\u0e00' <= c <= '\u0e7f' for c in text_str): return "#TH" # Thai
    if any('\u0e80' <= c <= '\u0eff' for c in text_str): return "#LO" # Lao
    if any('\u0f00' <= c <= '\u0fff' for c in text_str): return "#BO" # Tibetan
    if any('\u1000' <= c <= '\u109f' for c in text_str): return "#MY" # Burmese (Myanmar)
    if any('\u1200' <= c <= '\u137f' for c in text_str): return "#AM" # Amharic (Ethiopic)
    if any('\u1780' <= c <= '\u17ff' for c in text_str): return "#KM" # Khmer
    if any('\u10a0' <= c <= '\u10ff' for c in text_str): return "#KA" # Georgian
    if any('\u0530' <= c <= '\u058f' for c in text_str): return "#HY" # Armenian
    if any('\u0590' <= c <= '\u05ff' for c in text_str): return "#HE" # Hebrew
    if any('\u0370' <= c <= '\u03ff' for c in text_str): return "#EL" # Greek
    if any('\u0400' <= c <= '\u04ff' for c in text_str): return "#RU" # Russian / Ukrainian (Cyrillic)
    if any('\u4e00' <= c <= '\u9fff' for c in text_str): return "#ZH" # Chinese
    if any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in text_str): return "#JA" # Japanese
    if any('\uac00' <= c <= '\ud7af' for c in text_str): return "#KO" # Korean

    # . OTP Keyword    (Latin script languages)
    text_lower = text_str.lower()

    # Asian / Pacific
    if any(w in text_lower for w in ["kode verifikasi", "jangan bagikan", "rahasia"]): return "#ID" # Indonesian
    if any(w in text_lower for w in ["kod pengesahan", "jangan kongsi"]): return "#MS" # Malay
    if any(w in text_lower for w in ["mã của bạn", "không chia sẻ", "mã xác minh"]): return "#VN" # Vietnamese
    if any(w in text_lower for w in ["ang iyong code", "huwag ibahagi"]): return "#TL" # Tagalog / Filipino

    # European / Americas
    if any(w in text_lower for w in ["código", "tu código", "verificación", "no compartas"]): return "#ES" # Spanish
    if any(w in text_lower for w in ["seu código", "código de verificação", "não compartilhe"]): return "#PT" # Portuguese
    if any(w in text_lower for w in ["code secret", "ne partagez pas", "votre code"]): return "#FR" # French
    if any(w in text_lower for w in ["dein code", "bestätigungscode", "nicht teilen"]): return "#DE" # German
    if any(w in text_lower for w in ["il tuo codice", "codice di verifica", "non condividere"]): return "#IT" # Italian
    if any(w in text_lower for w in ["twój kod", "nie udostępniaj", "kod weryfikacyjny"]): return "#PL" # Polish
    if any(w in text_lower for w in ["doğrulama kodu", "paylaşmayın", "onay kodu"]): return "#TR" # Turkish
    if any(w in text_lower for w in ["jouw code", "verificatiecode", "niet delen"]): return "#NL" # Dutch
    if any(w in text_lower for w in ["din kod", "verifieringskod", "dela inte"]): return "#SV" # Swedish
    if any(w in text_lower for w in ["bekræftelseskode", "del ikke"]): return "#DA" # Danish
    if any(w in text_lower for w in ["bekreftelseskode", "ikke del"]): return "#NO" # Norwegian
    if any(w in text_lower for w in ["vahvistuskoodi", "älä jaa"]): return "#FI" # Finnish
    if any(w in text_lower for w in ["váš kód", "ověřovací kód", "nesdílejte"]): return "#CS" # Czech
    if any(w in text_lower for w in ["overovací kód", "nezdieľajte"]): return "#SK" # Slovak
    if any(w in text_lower for w in ["ellenőrző kód", "ne oszd meg"]): return "#HU" # Hungarian
    if any(w in text_lower for w in ["codul tău", "codul de verificare", "nu partaja"]): return "#RO" # Romanian
    if any(w in text_lower for w in ["kontrolni kod", "kod za potvrdu", "ne delite"]): return "#HR" # Croatian/Serbian
    if any(w in text_lower for w in ["код за потвърждение", "не споделяйте"]): return "#BG" # Bulgarian
    if any(w in text_lower for w in ["ваш код", "код підтвердження"]): return "#UK" # Ukrainian

    # African
    if any(w in text_lower for w in ["msimbo wako", "usishiriki"]): return "#SW" # Swahili
    if any(w in text_lower for w in ["verifikasiekode", "moenie deel nie"]): return "#AF" # Afrikaans

    # .
    return "#EN"


#==============================================================================
#  [19]  OTP CARD TEMPLATES & GROUP FORWARDING
#==============================================================================
def _otp_group_prefix(number):
    clean = re.sub(r"\D", "", str(number or ""))
    if not clean:
        return "XXXX"
    return clean[:8] + "XXXX"


def _otp_group_masked_number(number):
    clean = re.sub(r"\D", "", str(number or ""))
    if not clean:
        return "+•••••"
    return f"+•••••{clean[-2:]}"


def _country_display_name(value):
    """Resolve an ISO, country label, or phone number to an editable name value."""
    raw = str(value or "").strip()
    raw_up = raw.upper()
    if raw:
        for key, data in bot_settings.get("premium_flags", {}).items():
            if not isinstance(data, dict):
                continue
            iso = str(data.get("iso", "")).upper()
            name = str(data.get("name", "")).strip()
            if raw_up == iso or raw_up == name.upper() or raw_up in name.upper() or name.upper() in raw_up:
                return name or iso or raw
    _, iso = get_flag_and_code(raw)
    if iso and iso != "XX":
        for _, data in bot_settings.get("premium_flags", {}).items():
            if isinstance(data, dict) and str(data.get("iso", "")).upper() == str(iso).upper():
                return str(data.get("name") or iso).strip()
        return str(iso).upper()
    return raw or "Unknown"


def _card_visible_text(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<tg-emoji\s+emoji-id=[^>]+>(.*?)</tg-emoji>", r"\1", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _card_token(raw, replacements=None, trusted_html=None):
    text = str(raw or "")
    trusted_html = trusted_html or {}
    replacements = replacements or {}
    for key, value in replacements.items():
        text = text.replace("{" + str(key) + "}", html.escape(str(value)))
    for key, value in trusted_html.items():
        text = text.replace("{" + str(key) + "}", str(value))
    return text


# Drawn-grid card layout: every card renders as a real bordered monospace
# table — label in its own cell, value in its own cell, one row pair per
# line, like a classic table grid. Long values wrap inside their cell into
# continuation rows so every border stays aligned. The whole table travels
# inside one <pre> block, which _hold_and_render shields from the final
# emoji conversion (Telegram rejects entities nested inside <pre>).

_CARD_ROW_EMOJIS = {
    "COUNTRY": "🌍", "SERVICE": "📱", "ACCESS": "🔑", "ACCESS TYPE": "🔑",
    "STOCK": "📦", "NUMBER": "☎️", "REWARD": "💵", "OTP": "🔐",
    "OTP STATUS": "✅", "QUANTITY": "🔢", "PAGE": "📄", "TOTAL": "📊",
    "WINDOW": "🕒", "TRAFFIC": "📈", "TOP SERVICES": "📊", "USERS": "👥",
    "FILES": "📁", "NUMBERS": "🔢", "ASSIGNED": "✅", "AVAILABLE": "📦",
    "STATUS": "✅", "BALANCE": "💵", "MINIMUM": "🔒", "USERNAME": "👤",
    "JOINED": "📅", "REFERRAL": "👥", "SUPPORT": "🎧", "EMAIL": "📧",
}


def _card_row_emoji(label):
    visible = _card_visible_text(label).strip()
    if not visible:
        return "🔹"
    # Keep an existing custom/unicode emoji at the start of an editable label.
    first = visible[0]
    if not (first.isalnum() or first in "<_"):
        return ""
    upper = visible.upper()
    for key, emoji in sorted(_CARD_ROW_EMOJIS.items(), key=lambda item: len(item[0]), reverse=True):
        if key in upper:
            return emoji + " "
    return "🔹 "


def _card_boxed_value(raw):
    """One value, one cell: return the value wrapped in its own grey <code> box
    so every card line reads as label + boxed value beside it.
    Safety rule: Telegram rejects other entities nested inside a <code> block,
    so markup is never allowed to enter a box. The value is first pushed
    through render_body_text on its own — if any markup survives (trusted HTML,
    tg-emoji premium entities, invalid angle tags) the value keeps the bold
    style instead of a box, and a plain value can never gain markup later
    because the same conversion already ran on it."""
    value_html = render_body_text(str(raw or ""))
    if not value_html.strip():
        return ""
    if "<" in value_html:
        return f"<b>{value_html}</b>"
    return f"<code>{value_html}</code>"


def _card_boxed_label(label, prefix=""):
    """The label gets its own separate box too, so every card row reads as two
    cells side by side: [LABEL] [VALUE] — exactly like the reference design.
    The label is boxed raw: the final box-shield step (_hold_and_render) keeps
    emoji conversion out of boxes, so a label emoji stays a plain emoji. If the
    label already carries HTML markup (trusted placeholders) it falls back to
    the bold style instead of a box."""
    label_text = str(label or "").strip()
    if not label_text:
        return ""
    content = f"{prefix}{label_text}".strip()
    if "<" in content:
        return f"<b>{content}:</b>"
    return f"<code>{content}</code>"


def _hold_and_render(lines):
    """Join the card lines and shield finished monospace blocks from the
    full-text emoji conversion. render_body_text rewrites mapped emojis into
    tg-emoji tags, and Telegram rejects any entity nested inside a <pre> or
    <code> block — so finished <pre> tables and <code> boxes are held out of
    the conversion, then restored untouched."""
    text = "\n".join(lines)
    held = []

    def _keep(match):
        held.append(match.group(0))
        return "\x00CB%d\x00" % (len(held) - 1)

    text = re.sub(r"<pre>.*?</pre>", _keep, text, flags=re.DOTALL)
    text = re.sub(r"<code>[^<]*</code>", _keep, text)
    text = render_body_text(text)
    for index, box in enumerate(held):
        text = text.replace("\x00CB%d\x00" % index, box)
    return text


def _card_title_line(title):
    title = str(title or "").strip()
    if not title:
        return ""
    if "<" in title:
        return title
    return f"<b>{title}</b>"


def _pre_plain_text(html_text):
    """Plain single-line text for use INSIDE a <pre> block.
    tg-emoji/HTML tags are stripped to their visible text (custom-emoji
    entities are rejected by Telegram inside <pre>), leftover angle brackets
    and bare ampersands are escaped, newlines collapse to spaces. Existing
    entities such as &amp; are kept — they parse correctly inside <pre> too."""
    text = re.sub(r"<br\s*/?>", " ", str(html_text or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def _pre_whole_block(title, grid, footer=""):
    """Wrap title (+ optional footer) and the drawn table into ONE <pre>
    block, so the entire screen lives between a single pair of triple
    backticks. Title/footer are flattened with _pre_plain_text; the grid is
    already pre-escaped plain table text."""
    lines = []
    title_plain = _pre_plain_text(title)
    if title_plain:
        lines.extend([title_plain, ""])
    lines.append(grid)
    footer_plain = _pre_plain_text(footer)
    if footer_plain:
        lines.extend(["", footer_plain])
    return _hold_and_render(["<pre>" + "\n".join(lines) + "</pre>"])


def _grid_width(text):
    """Monospace display width of one line. Box-drawing characters, text,
    punctuation and general punctuation (bullets, dashes, quotes) take one
    cell; colour emoji take two; variation selectors and ZWJ joiners take
    none; a regional-indicator pair (flag) takes two."""
    width = 0
    for ch in str(text or ""):
        code = ord(ch)
        if code in (0xFE0E, 0xFE0F, 0x200D):
            continue
        if 0x1F1E6 <= code <= 0x1F1FF:
            width += 1
        elif code <= 0x206F or 0x2500 <= code <= 0x257F:
            width += 1
        else:
            width += 2
    return width


def _grid_pad(text, width):
    text = str(text or "")
    return text + " " * max(0, width - _grid_width(text))


def _grid_wrap(text, width):
    """Wrap one plain line at a monospace display width (emoji = two cells).
    Splits on spaces when possible, hard-breaks tokens longer than a cell."""
    text = str(text or "").strip()
    if not text:
        return [""]
    if _grid_width(text) <= width:
        return [text]
    chunks, current = [], ""
    for word in text.split(" "):
        while _grid_width(word) > width:
            if current:
                chunks.append(current)
                current = ""
            acc, cut = 0, len(word)
            for i, ch in enumerate(word):
                code = ord(ch)
                acc += 1 if (code <= 0x206F or 0x2500 <= code <= 0x257F) else 2
                if acc > width:
                    cut = i
                    break
            chunks.append(word[:cut])
            word = word[cut:]
        candidate = word if not current else current + " " + word
        if _grid_width(candidate) <= width:
            current = candidate
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks or [""]


def _card_grid_body(specs):
    """Build the bordered two-column monospace table for one card.
    specs: list of (label, value-lines or a single string) with plain tag-free
    text. Cell text is HTML-escaped FIRST, then wrapped and padded, so escaped
    entities such as &amp; keep their true monospace display width and every
    border line stays perfectly aligned."""
    if not specs:
        return ""
    norm = []
    for label, value_lines in specs:
        # Accept either a list of lines or a single plain string value.
        if isinstance(value_lines, str):
            value_lines = [value_lines]
        esc_lines = [html.escape(str(ln)) for ln in value_lines if str(ln).strip()] or [""]
        norm.append((html.escape(str(label)), esc_lines))
    label_w = max(8, min(20, max(_grid_width(lbl) for lbl, _ in norm)))
    value_widths = [_grid_width(ln) for _, lines in norm for ln in lines]
    value_w = max(10, min(26, max(value_widths) if value_widths else 10))
    top = "┌" + "─" * (label_w + 2) + "┬" + "─" * (value_w + 2) + "┐"
    sep = "├" + "─" * (label_w + 2) + "┼" + "─" * (value_w + 2) + "┤"
    bottom = "└" + "─" * (label_w + 2) + "┴" + "─" * (value_w + 2) + "┘"

    def _row(label, value):
        return "│ " + _grid_pad(label, label_w) + " │ " + _grid_pad(value, value_w) + " │"

    blocks = []
    for label, value_lines in norm:
        label_chunks = _grid_wrap(label, label_w)
        value_chunks = []
        for line in value_lines:
            value_chunks.extend(_grid_wrap(line, value_w))
        if not value_chunks:
            value_chunks = [""]
        size = max(len(label_chunks), len(value_chunks))
        blocks.append([
            _row(label_chunks[i] if i < len(label_chunks) else "",
                 value_chunks[i] if i < len(value_chunks) else "")
            for i in range(size)
        ])
    lines = [top]
    for i, block in enumerate(blocks):
        lines.extend(block)
        if i < len(blocks) - 1:
            lines.append(sep)
    lines.append(bottom)
    # Cells are pre-escaped and borders are box-drawing characters, so the
    # table is safe for the <pre> context as-is. Returns the bare table —
    # callers wrap it (with their title) in a single <pre> block.
    return "\n".join(lines)



# ==========================================
# Menu Grid — one drawn table style for the whole bot
# ==========================================
# Screens rendered through render_custom_menu_body (start, refer, withdrawal,
# get_number, search_number, support, stock_categories) draw the same bordered
# monospace table family as the card templates when no admin body is saved.
DEFAULT_MENU_GRIDS = {
    "start": {
        # User names can contain complex-script characters whose monospace
        # width cannot be computed reliably — they stay in the title (normal
        # HTML, no alignment) while grid cells keep fixed ASCII text.
        "title": PEM['star'] + " <b>WELCOME, {full_name}!</b>",
        "rows": [
            ("BRAND", "{brand_name}"),
            ("QUALITY", "SMART · FAST · RELIABLE"),
            ("REMINDER", "HAVE YOU PRAYED YOUR SALAH TODAY?"),
            ("FAITH", "KEEP ALLAH IN YOUR HEART, ALWAYS"),
            ("DEVELOPED BY", "@Antuleftyouronread"),
        ],
    },
    "refer": {
        "title": PEM['gift'] + " <b>REFER & EARN</b>",
        "rows": [
            ("YOUR LINK", "{ref_link}"),
            ("TOTAL REFERS", "{total_ref}"),
            ("PER REFER", "{ref_reward} USD"),
        ],
    },
    "withdrawal": {
        "title": PEM['money'] + " <b>WITHDRAWAL</b>",
        "rows": [
            ("TOTAL OTP", "{total_otp}"),
            ("TOTAL REFERRAL", "{total_ref}"),
            ("BALANCE", "${bal} USD"),
            ("MINIMUM", "${min_w} USD"),
        ],
        "footer": "👇 SELECT A METHOD BELOW",
    },
    "get_number": {
        "title": PEM['pin'] + " <b>SELECT A SERVICE</b>",
        "rows": [
            ("STEP 1", "PICK A SERVICE FROM THE LIST"),
            ("STEP 2", "GET YOUR NUMBER INSTANTLY"),
        ],
    },
    "search_number": {
        "title": "🔍 SEARCH NUMBER",
        "rows": [
            ("INPUT", "3 TO 9 DIGITS"),
            ("EXAMPLE", "880 / 9227373"),
            ("SPEED", "FAST NUMBER LOOKUP"),
        ],
    },
    "support": {
        "title": PEM['msg'] + " <b>NEED HELP?</b>",
        "rows": [
            ("SUPPORT", "CONTACT US FOR ANY HELP"),
            ("STATUS", "ONLINE"),
        ],
    },
    "stock_categories": {
        "title": "📊 STOCK AVAILABLE",
        "rows": [
            ("STOCK", "LIVE COUNTRY-WISE NUMBERS"),
            ("ACTION", "SELECT A CATEGORY BELOW"),
        ],
    },
}

# Layout generation for the free-form menu bodies. v2 = grid everywhere:
# a full-body text saved under an older generation is dropped so the new
# grid design shows up; bodies saved while already on v2 are respected.
_MENU_GRID_LAYOUT_VERSION = 2
_MENU_GRID_KEYS = ("start", "refer", "withdrawal", "get_number", "search_number", "support", "stock_categories")


def _menu_body_block(menu_key):
    """Return the custom_messages block for a menu key, migrating stale
    layout-v1 bodies (same policy as the card templates)."""
    msgs = bot_settings.setdefault("custom_messages", {})
    c_msg = msgs.get(menu_key)
    if not isinstance(c_msg, dict):
        c_msg = {"text": "", "buttons": []}
        msgs[menu_key] = c_msg
    if menu_key in _MENU_GRID_KEYS and c_msg.get("_layout_version") != _MENU_GRID_LAYOUT_VERSION:
        saved_buttons = c_msg.get("buttons")
        saved_media = c_msg.get("media")
        c_msg["text"] = ""
        c_msg["_layout_version"] = _MENU_GRID_LAYOUT_VERSION
        if isinstance(saved_buttons, list):
            c_msg["buttons"] = saved_buttons
        if isinstance(saved_media, dict) and saved_media:
            c_msg["media"] = saved_media
        try:
            save_db()
        except Exception:
            pass
    if not isinstance(c_msg.get("buttons"), list):
        c_msg["buttons"] = []
    return c_msg


def _menu_grid(title, specs, footer=""):
    """Whole-screen triple-backtick block: plain title, blank line, the drawn
    grid table and the optional footer inside ONE <pre> block, emoji-safe
    (the finished block is shielded from the tg-emoji conversion)."""
    grid = _card_grid_body(specs)
    if not grid:
        return render_body_text(_card_title_line(str(title)))
    return _pre_whole_block(str(title), grid, footer=footer)


def _menu_grid_title(template_title, values=None):
    title = str(template_title or "")
    for key, val in (values or {}).items():
        title = title.replace("{" + str(key) + "}", str(val))
    return title.replace("{brand_name}", get_brand_name_html())


def _menu_grid_footer(spec, replacements=None):
    footer = str((spec or {}).get("footer", "") or "")
    if not footer.strip():
        return ""
    for key, val in (replacements or {}).items():
        footer = footer.replace("{" + str(key) + "}", str(val))
    return re.sub(r"\{[a-zA-Z0-9_]+\}", "", footer).strip()


def _menu_grid_values(msg, replacements=None):
    """Plain runtime values available to menu grids (cells and titles)."""
    user = ((msg or {}).get("from", {}) or {})
    first_name = str(user.get("first_name") or "User")
    last_name = str(user.get("last_name") or "")
    username = str(user.get("username") or "")
    values = {
        "first_name": first_name,
        "full_name": (first_name + (" " + last_name if last_name else "")).strip() or first_name,
        "username": ("@" + username) if username and not username.startswith("@") else username,
        "user_id": str((msg or {}).get("chat", {}).get("id", "") or ""),
        "brand_name": get_brand_name_plain(24),
    }
    values.update({str(k): v for k, v in (replacements or {}).items()})
    return values


def _menu_grid_specs(menu_key, msg, replacements=None):
    """Resolve DEFAULT_MENU_GRIDS rows into plain (label, value-lines) specs.
    Values are plain text; _card_grid_body escapes them into the <pre> block."""
    spec = DEFAULT_MENU_GRIDS.get(menu_key)
    if not spec:
        return None
    values = _menu_grid_values(msg, replacements)
    specs = []
    for label_tpl, value_tpl in spec.get("rows", []):
        label, value = str(label_tpl), str(value_tpl)
        for key, val in values.items():
            label = label.replace("{" + key + "}", str(val))
            value = value.replace("{" + key + "}", str(val))
        label = re.sub(r"\{[a-zA-Z0-9_]+\}", "", label).strip()
        value = re.sub(r"\{[a-zA-Z0-9_]+\}", "", value).strip()
        value_lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
        if not label and not value_lines:
            continue
        specs.append((label, value_lines or [""]))
    return specs or None


def render_card_template(card_key, values=None, trusted_html=None, collapsed=False, fallback_title=None):
    """Render an editable card as a drawn monospace table: label in its own
    bordered cell, value in its own bordered cell, one row per line.
    Admins can still replace the whole body from Menu Design (body_text wins)."""
    template = _card_template(card_key)
    values = values or {}
    trusted_html = trusted_html or {}
    body_text = str(template.get("body_text") or "").strip()
    if body_text:
        # Admin replaced the whole card body from Menu Design; render it with
        # every runtime placeholder instead of the built-in title + rows.
        return render_body_text(_card_token(body_text, values, trusted_html))
    title = _card_token(template.get("title", fallback_title or card_key.upper()), values, trusted_html)
    rows = []
    for row in template.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        if collapsed and row.get("collapsed"):
            continue
        label = _card_token(row.get("label", ""), values, trusted_html)
        value = _card_token(row.get("value", ""), values, trusted_html)
        if not label and not value:
            continue
        rows.append((label, value))
    if card_key == "otp_inbox" and not any(_card_visible_text(label).strip().upper() == "OTP" for label, _ in rows):
        rows.append(("OTP", _card_token("{otp}", values, trusted_html)))
    if not rows:
        return render_body_text(str(title))

    # Drawn-grid layout: blank line under the title, then one bordered table
    # where every label and value sits in its own cell. Multi-line values
    # (traffic/stock) keep the author's line breaks as extra rows; long values
    # wrap inside their cell so every border stays aligned.
    specs = []
    for label, value in rows:
        label_text = _card_visible_text(label).strip()
        value_lines = [ln for ln in (_card_visible_text(part) for part in str(value or "").splitlines()) if ln.strip()]
        if not label_text and not value_lines:
            continue
        if label_text:
            prefix = _card_row_emoji(label)
            if prefix:
                label_text = (prefix + label_text).strip()
        specs.append((label_text, value_lines or [""]))
    grid = _card_grid_body(specs)
    if not grid:
        return render_body_text(str(title))
    # Whole-card triple-backtick block: the title joins the table inside ONE
    # <pre> block, so the entire card text lives between the backticks.
    return _pre_whole_block(title, grid)

def render_minimal_card_template(card_key, values=None, trusted_html=None, fallback_title=None):
    """Render profile/account cards as a drawn monospace table: label cell +
    value cell per row — same grid family as render_card_template."""
    template = _card_template(card_key)
    values = values or {}
    trusted_html = trusted_html or {}
    body_text = str(template.get("body_text") or "").strip()
    if body_text:
        # Admin-provided body from Menu Design wins over the built-in rows.
        return render_body_text(_card_token(body_text, values, trusted_html))
    title = _card_token(template.get("title", fallback_title or card_key.upper()), values, trusted_html)
    specs = []
    for row in template.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        label = _card_token(row.get("label", ""), values, trusted_html)
        value = _card_token(row.get("value", ""), values, trusted_html)
        label_text = _card_visible_text(label).strip()
        value_lines = [ln for ln in (_card_visible_text(part) for part in str(value or "").splitlines()) if ln.strip()]
        if not label_text and not value_lines:
            continue
        if label_text:
            prefix = _card_row_emoji(label)
            if prefix:
                label_text = (prefix + label_text).strip()
        specs.append((label_text, value_lines or [""]))
    if not specs:
        return render_body_text(str(title))
    grid = _card_grid_body(specs)
    if not grid:
        return render_body_text(str(title))
    # Same whole-card rule: title + table together inside one <pre> block.
    return _pre_whole_block(title, grid)


#==============================================================================
#  IMAGE BOARD (PIL) — account/dashboard cards rendered as a photo: the
#  table and borders live INSIDE the picture, so selecting the message
#  copies only the clean caption text (no border characters, no COPY CODE
#  chip). Falls back to the classic one-<pre> text grid without Pillow.
#==============================================================================
_BOARD_BG       = (18, 21, 27)
_BOARD_LABEL_BG = (31, 36, 45)
_BOARD_LINE     = (62, 72, 88)
_BOARD_LABEL    = (148, 160, 174)
_BOARD_VALUE    = (241, 244, 248)
_BOARD_TITLE    = (241, 244, 248)
_BOARD_ACCENT   = (88, 158, 255)
_BOARD_FOOTER   = (148, 160, 174)

_PIL_STATE = {"tried": False, "ok": False}

def _pil_ready():
    """Lazy Pillow availability check; auto-installs once when missing."""
    if _PIL_STATE["tried"]:
        return _PIL_STATE["ok"]
    try:
        import PIL  # noqa: F401
        _PIL_STATE["ok"] = True
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--disable-pip-version-check", "Pillow"],
                timeout=180, check=False,
            )
        except Exception:
            pass
        try:
            import PIL  # noqa: F401
            _PIL_STATE["ok"] = True
        except ImportError:
            _PIL_STATE["ok"] = False
    _PIL_STATE["tried"] = True
    return _PIL_STATE["ok"]

_BOARD_FONT_CACHE = {}
_BOARD_FONT_DOWNLOADED = {"done": False}
_BOARD_FONT_URLS = {
    False: "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
    True:  "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
}
_BOARD_FONT_TMP = {False: "/tmp/_board_noto_regular.ttf", True: "/tmp/_board_noto_bold.ttf"}

def _board_font(size, bold=False):
    cached = _BOARD_FONT_CACHE.get((size, bool(bold)))
    if cached is not None:
        return cached
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
        "/usr/share/fonts/truetype/noto/NotoSans-%s.ttf" % ("Bold" if bold else "Regular"),
        _BOARD_FONT_TMP[bool(bold)],
    ]
    font = None
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None and not _BOARD_FONT_DOWNLOADED["done"]:
        _BOARD_FONT_DOWNLOADED["done"] = True
        for bold_flag, url in _BOARD_FONT_URLS.items():
            try:
                resp = requests.get(url, timeout=10)
                if resp.ok and resp.content[:4] == b"\x00\x01\x00\x00":
                    with open(_BOARD_FONT_TMP[bold_flag], "wb") as fh:
                        fh.write(resp.content)
            except Exception:
                pass
        for path in candidates:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, size)
                    break
                except Exception:
                    continue
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except Exception:
            font = ImageFont.load_default()
    _BOARD_FONT_CACHE[(size, bool(bold))] = font
    return font

def _board_safe_text(text):
    """Keep only PIL-drawable chars for the board image (emoji, Bengali and
    other non-latin glyphs are dropped — the caption still carries them)."""
    cleaned = re.sub(r"[^\x20-\x7E\u00B7\u2013\u2014\u2022\u2713]", "", str(text or ""))
    return re.sub(r"\s{2,}", " ", cleaned).strip()

def _render_board_png(title, rows, footer=""):
    """Draw the label/value table as a PNG — borders are pixels, not text."""
    if not _pil_ready() or not rows:
        return None
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    scale = 2  # supersample so lines stay crisp after Telegram compression
    cell, title_size, footer_size = 17, 21, 14
    f_title = _board_font(title_size * scale, bold=True)
    f_label = _board_font(cell * scale)
    f_value = _board_font(cell * scale, bold=True)
    f_footer = _board_font(footer_size * scale)
    meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    padx, pady = 14 * scale, 11 * scale
    line_h = int(cell * scale * 1.5)

    label_w = value_w = 0
    for label, value_lines in rows:
        label_w = max(label_w, meas.textlength(_board_safe_text(label), font=f_label))
        for vline in value_lines:
            value_w = max(value_w, meas.textlength(_board_safe_text(vline), font=f_value))
    label_w = int(label_w + padx * 2)
    value_w = max(int(value_w + padx * 2), 150 * scale)
    table_w = label_w + value_w

    title_h = int(title_size * scale * 1.9)
    gap = 13 * scale
    row_h = [pady * 2 + max(1, len(vl)) * line_h for _, vl in rows]
    table_h = sum(row_h)
    foot_txt = _board_safe_text(footer)
    footer_h = int(footer_size * scale * 2.0) + 10 * scale if foot_txt else 0
    safe_title = _board_safe_text(title)
    width = int(max(table_w, meas.textlength(safe_title, font=f_title) + 40 * scale) + padx)
    height = int(pady + title_h + gap + table_h + footer_h + pady)

    img = Image.new("RGB", (width, height), _BOARD_BG)
    d = ImageDraw.Draw(img)
    # Title with accent bar
    d.rectangle([padx, pady + 3 * scale, padx + 4 * scale, pady + title_h - 3 * scale], fill=_BOARD_ACCENT)
    d.text((padx + 12 * scale, pady), safe_title, font=f_title, fill=_BOARD_TITLE)
    # Centred table
    x0 = max(padx, (width - table_w) // 2)
    y0 = pady + title_h + gap
    d.rectangle([x0, y0, x0 + table_w, y0 + table_h], outline=_BOARD_LINE, width=2 * scale)
    cy = y0
    for (label, value_lines), h in zip(rows, row_h):
        d.rectangle([x0, cy, x0 + label_w, cy + h], fill=_BOARD_LABEL_BG)
        n = max(1, len(value_lines))
        d.text((x0 + padx, cy + h // 2), _board_safe_text(label), font=f_label, fill=_BOARD_LABEL, anchor="lm")
        for k, vline in enumerate(value_lines):
            vy = int(cy + h // 2 + (k - (n - 1) / 2.0) * line_h)
            d.text((x0 + label_w + padx, vy), _board_safe_text(vline), font=f_value, fill=_BOARD_VALUE, anchor="lm")
        cy += h
        if cy < y0 + table_h:
            d.line([x0, cy, x0 + table_w, cy], fill=_BOARD_LINE, width=2 * scale)
    d.line([x0 + label_w, y0, x0 + label_w, y0 + table_h], fill=_BOARD_LINE, width=2 * scale)
    if foot_txt:
        d.text((x0, y0 + table_h + 10 * scale), foot_txt, font=f_footer, fill=_BOARD_FOOTER, anchor="la")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

def _send_board_photo(chat_id, title, rows, footer="", caption_html="", reply_markup=None, replace_message_id=None, fallback_html=None):
    """Send the board as a photo (clean caption copies without borders).
    Falls back to the classic one-<pre> text grid when Pillow is missing."""
    sent = None
    if rows:
        try:
            png = _render_board_png(str(title), rows, footer=str(footer or ""))
            if png:
                data = {"chat_id": str(chat_id), "caption": caption_html or "", "parse_mode": "HTML"}
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)
                resp = requests.post(
                    f"{BASE_URL}/sendPhoto", data=data,
                    files={"photo": ("board.png", png, "image/png")},
                    timeout=TELEGRAM_ACTION_TIMEOUT + 20,
                )
                if resp.ok:
                    try:
                        result = resp.json()
                    except Exception:
                        result = {}
                    if result.get("ok"):
                        sent = result
        except Exception:
            sent = None
    if sent is None:
        if fallback_html is not None:
            txt = fallback_html
        else:
            txt = render_body_text(_pre_whole_block(str(title), _card_grid_body(rows), footer=str(footer or "")))
        sent = send_message(chat_id, txt, reply_markup=reply_markup)
    if replace_message_id:
        try:
            delete_message(chat_id, replace_message_id)
        except Exception:
            pass
    return sent

def _send_text_replacing(chat_id, txt, reply_markup=None, message_id=None):
    """Send a text status message; edit in place when the old message is
    text, otherwise send fresh and remove the old photo message."""
    if message_id and not _pil_ready():
        return _send_or_edit(chat_id, txt, reply_markup, message_id)
    sent = send_message(chat_id, txt, reply_markup=reply_markup)
    if message_id:
        try:
            delete_message(chat_id, message_id)
        except Exception:
            pass
    return sent

def _minimal_card_board_data(card_key, values=None, fallback_title=None, trusted_html=None, collapsed=False):
    """Visible-text (label, value_lines) specs for the image board. Emoji are
    kept here — the caption reuses them — while _render_board_png strips
    whatever PIL cannot draw. Returns None when the admin saved a custom body
    in Menu Design — the text path wins then."""
    template = _card_template(card_key)
    values = values or {}
    trusted_html = trusted_html or {}
    if str(template.get("body_text") or "").strip():
        return None
    title = _card_visible_text(_card_token(template.get("title", fallback_title or card_key.upper()), values, trusted_html))
    specs = []
    for row in template.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        if collapsed and row.get("collapsed"):
            continue
        label_text = _card_visible_text(_card_token(row.get("label", ""), values, trusted_html))
        value = _card_token(row.get("value", ""), values, trusted_html)
        value_lines = [_card_visible_text(ln) for ln in str(value or "").splitlines()]
        value_lines = [ln for ln in value_lines if ln]
        if not label_text and not value_lines:
            continue
        if label_text:
            prefix = _card_row_emoji(label_text)
            if prefix:
                label_text = (prefix + label_text).strip()
        specs.append((label_text or " ", value_lines or [" "]))
    if card_key == "otp_inbox" and not any("OTP" in str(label).upper() for label, _ in specs):
        otp_text = _card_visible_text(_card_token("{otp}", values, trusted_html))
        if otp_text:
            specs.append(("OTP", [otp_text]))
    if not specs:
        return None
    return (title or _card_visible_text(fallback_title or card_key.upper()), specs)


def _board_caption_html(header_html, specs, extra_lines=None):
    """Clean copyable caption: header line, then every board row as plain
    'label: value' text. Selecting the message copies exactly this text —
    never the drawn borders."""
    lines = [str(header_html or ""), ""]
    for label, vlines in specs or []:
        value = " ".join(str(v) for v in vlines).strip()
        lines.append(f"{html.escape(str(label))}: <b>{html.escape(value)}</b>")
    for extra in extra_lines or []:
        if str(extra).strip():
            lines.append(str(extra))
    return "\n".join(lines)


def _caption_plain_length(caption_html):
    text = re.sub(r"<[^>]+>", "", html.unescape(str(caption_html or "")))
    return len(text)


def _send_card_board(chat_id, card_key, caption_header, values=None, trusted_html=None,
                     fallback_title=None, reply_markup=None, message_id=None,
                     collapsed=False, extra_caption_lines=None):
    """Universal image-board sender for every bordered card: the table and
    its borders live inside the photo, the clean text travels in the caption.
    Falls back to the classic one-<pre> text grid without Pillow or when the
    admin saved a custom body in Menu Design."""
    fallback = render_card_template(
        card_key, values=values, trusted_html=trusted_html,
        collapsed=collapsed, fallback_title=fallback_title,
    )
    board = _minimal_card_board_data(
        card_key, values=values, fallback_title=fallback_title,
        trusted_html=trusted_html, collapsed=collapsed,
    )
    if board is None:
        return _send_or_edit(chat_id, fallback, reply_markup, message_id)
    title, specs = board
    caption = _board_caption_html(caption_header, specs, extra_caption_lines)
    if _caption_plain_length(caption) > 1000:
        return _send_or_edit(chat_id, fallback, reply_markup, message_id)
    return _send_board_photo(
        chat_id, title, specs, caption_html=caption,
        reply_markup=reply_markup, replace_message_id=message_id,
        fallback_html=fallback,
    )


def _otp_template_context(service="", country="", number="", otp="", lang="#EN", sms_text="", reward="", provider="", range_text="", category="", batch_id="", total=""):
    """Shared placeholder computation for the OTP inbox/group boards and the
    classic text templates (single source of truth)."""
    app_name, app_html = get_service_info_html(service, sms_text)
    service_label = {"WHATSAPP": "WS", "FACEBOOK": "FB"}.get(str(app_name).upper(), str(app_name).upper())
    clean = re.sub(r"\D", "", str(number or ""))
    country_value = country or clean
    lang_text = str(lang or "#EN").lstrip("#").upper()
    flag_html = get_flag_info_html(country_value)
    country_name = _country_display_name(country_value)
    full_number = f"+{clean}" if clean else str(number or "")
    provider_line = f"<b>Provider:</b> {html.escape(str(provider))}\n" if provider else ""
    range_line = f"<b>Range:</b> <code>{html.escape(str(range_text))}</code>\n" if range_text else ""
    trusted_html = {
        "service": f"{app_html} <b>{html.escape(service_label)}</b>",
        "service_header": f"{app_html} <b>{html.escape(str(app_name).upper())}</b>",
        "country": flag_html,
        "provider_line": provider_line,
        "range_line": range_line,
    }
    replacements = {
        "service1": app_name,
        "country1": country_name.upper(),
        "number": full_number,
        "number1": _otp_group_masked_number(number) if number else "",
        "otp": str(otp or ""),
        "prefix": _otp_group_prefix(number),
        "lang": lang_text,
        "sms": str(sms_text or ""),
        "reward": reward,
        "provider": provider,
        "range": range_text,
        "category": category,
        "batch_id": batch_id,
        "total": total,
    }
    if not replacements.get("reward"):
        replacements["reward"] = f"{float(bot_settings.get('otp_reward', 0.0) or 0.0):g} USD"
    return replacements, trusted_html


def _render_otp_template(menu_key, service="", country="", number="", otp="", lang="#EN", sms_text="", reward="", provider="", range_text="", category="", batch_id="", total=""):
    """Render inbox, group, and number-broadcast bodies with safe placeholders."""
    replacements, trusted_html = _otp_template_context(
        service=service, country=country, number=number, otp=otp,
        lang=lang, sms_text=sms_text, reward=reward, provider=provider,
        range_text=range_text, category=category, batch_id=batch_id, total=total,
    )
    if menu_key in bot_settings.get("card_templates", {}):
        return render_card_template(
            menu_key,
            values=replacements,
            trusted_html=trusted_html,
            collapsed=(menu_key == "otp_group"),
        )
    return render_custom_menu_body(
        menu_key,
        {"chat": {}, "from": {}},
        replacements=replacements,
        trusted_html=trusted_html,
    )


def _otp_sms_caption_line(sms_text):
    sms = str(sms_text or "").strip()
    if not sms:
        return ""
    return f"💬 SMS: <b>{html.escape(sms[:300])}</b>"


def _send_otp_inbox(chat_id, service, number, otp, lang="#EN", sms_text="", reward="", provider="", range_text="", country="", markup=None):
    """Private OTP inbox as an image board: borders live in the photo, the
    clean text (number + OTP) travels in the caption and stays copyable."""
    replacements, trusted_html = _otp_template_context(
        service=service, country=country, number=number, otp=otp,
        lang=lang, sms_text=sms_text, reward=reward,
        provider=provider, range_text=range_text,
    )
    fallback = _render_otp_template(
        "otp_inbox", service=service, country=country, number=number,
        otp=otp, lang=lang, sms_text=sms_text, reward=reward,
        provider=provider, range_text=range_text,
    )
    board = _minimal_card_board_data(
        "otp_inbox", values=replacements, trusted_html=trusted_html,
        fallback_title="OTP RECEIVED",
    )
    if board is None:
        return send_message(chat_id, fallback, reply_markup=markup)
    title, specs = board
    extra = []
    flag_plain = _card_visible_text(trusted_html.get("country", ""))
    headline = " ".join(part for part in [
        flag_plain,
        str(replacements.get("country1", "")),
        "·",
        str(replacements.get("service1", "")).upper(),
        "·",
        str(replacements.get("lang", "")),
    ] if part)
    if headline.strip(" ·"):
        extra.append(f"<b>{html.escape(headline)}</b>")
    sms_line = _otp_sms_caption_line(sms_text)
    if sms_line:
        extra.append(sms_line)
    caption = _board_caption_html("📥 <b>OTP RECEIVED</b>", specs, extra)
    if _caption_plain_length(caption) > 1000:
        return send_message(chat_id, fallback, reply_markup=markup)
    return _send_board_photo(
        chat_id, title, specs, caption_html=caption,
        reply_markup=markup, fallback_html=fallback,
    )


def _send_otp_group_card(chat_id, session, markup=None, replace_message_id=None, collapsed=True):
    """OTP group card as an image board (used by the forwarder and the
    expand/collapse button). Session carries service/country/number/otp."""
    service = session.get("service", "")
    number = session.get("number", "")
    otp = session.get("otp", "")
    lang = session.get("lang", "#EN")
    sms_text = session.get("sms_text", "")
    country = session.get("country", "")
    reward = session.get("reward", "")
    replacements, trusted_html = _otp_template_context(
        service=service, country=country, number=number, otp=otp,
        lang=lang, sms_text=sms_text, reward=reward,
    )
    fallback = _otp_group_message(service, number, otp, lang, sms_text, country, reward)
    board = _minimal_card_board_data(
        "otp_group", values=replacements, trusted_html=trusted_html,
        fallback_title="OTP RECEIVED", collapsed=collapsed,
    )
    if board is None:
        return _send_text_replacing(chat_id, fallback, markup, replace_message_id)
    title, specs = board
    extra = []
    flag_plain = _card_visible_text(trusted_html.get("country", ""))
    headline = " ".join(part for part in [
        flag_plain,
        str(replacements.get("country1", "")),
        "·",
        str(replacements.get("service1", "")).upper(),
        "·",
        str(replacements.get("lang", "")),
    ] if part)
    if headline.strip(" ·"):
        extra.append(f"<b>{html.escape(headline)}</b>")
    caption = _board_caption_html("🔐 <b>OTP RECEIVED</b>", specs, extra)
    if _caption_plain_length(caption) > 1000:
        return _send_text_replacing(chat_id, fallback, markup, replace_message_id)
    return _send_board_photo(
        chat_id, title, specs, caption_html=caption,
        reply_markup=markup, replace_message_id=replace_message_id,
        fallback_html=fallback,
    )


def _number_broadcast_text(service, country, category, total, reward, batch_id):
    return _render_otp_template(
        "number_broadcast",
        service=service,
        country=country,
        category=category,
        total=total,
        reward=reward,
        batch_id=batch_id,
    )


def _otp_inbox_message(service, number, otp, lang="#EN", sms_text="", reward="", provider="", range_text="", country=""):
    return _render_otp_template(
        "otp_inbox",
        service=service,
        country=country,
        number=number,
        otp=otp,
        lang=lang,
        sms_text=sms_text,
        reward=reward,
        provider=provider,
        range_text=range_text,
    )


def _otp_group_message(service, number, otp, lang="#EN", sms_text="", country="", reward=""):
    return _render_otp_template(
        "otp_group",
        service=service,
        country=country,
        number=number,
        otp=otp,
        lang=lang,
        sms_text=sms_text,
        reward=reward,
    )


def _otp_copy_markup(number, otp):
    prefix = _otp_group_prefix(number)
    return [
        [{"text": "# PREFIX", "icon_custom_emoji_id": "5192739271886282680", "copy_text": {"text": prefix}, "style": "primary"}],
        [{"text": "Copy OTP", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": str(otp)}, "style": "success"}],
    ]


def _otp_inbox_markup(number, otp):
    rows = _otp_copy_markup(number, otp)
    pending = []
    for button in safe_custom_buttons(_card_template("otp_inbox").get("buttons", []) or []):
        label = str(button.get("text", "Button"))
        if label.strip().upper() in {"CHANNEL", "NUMBER BOT"}:
            continue
        obj = {
            "text": label,
            "icon_custom_emoji_id": button.get("icon_custom_emoji_id", "5420517437885943844"),
            "style": button.get("style", "primary"),
        }
        if button.get("url"):
            obj["url"] = button["url"]
        elif button.get("callback_data"):
            obj["callback_data"] = button["callback_data"]
        pending.append(obj)
    for index in range(0, len(pending), 2):
        rows.append(pending[index:index + 2])
    return {"inline_keyboard": rows}


def _otp_group_markup(number, otp, extra_buttons=None, session_key="", expanded=False):
    # The only built-in group controls are the two copy actions. All remaining
    # controls come from the Admin Panel card configuration.
    rows = _otp_copy_markup(number, otp)
    if not extra_buttons:
        extra_buttons = safe_custom_buttons(_card_template("otp_group").get("buttons", []))
    pending = []
    for button in extra_buttons or []:
        label = str(button.get("text", "Button"))
        if label.strip().upper() in {"CHANNEL", "NUMBER BOT"}:
            continue
        obj = {
            "text": label,
            "icon_custom_emoji_id": button.get("icon_custom_emoji_id", "5420517437885943844"),
            "style": button.get("style", "primary"),
        }
        if button.get("url"):
            obj["url"] = button["url"]
        elif button.get("callback_data"):
            obj["callback_data"] = button["callback_data"]
        pending.append(obj)
    for index in range(0, len(pending), 2):
        rows.append(pending[index:index + 2])
    return {"inline_keyboard": rows}


def _forward_otp_to_groups(service, number, otp, lang="#EN", sms_text="", country="", reward=""):
    for fw in bot_settings.get("fw_groups", []):
        try:
            session_key = uuid.uuid4().hex[:16]
            session = {
                "service": service,
                "country": country,
                "number": number,
                "otp": otp,
                "lang": lang,
                "reward": reward,
                "sms_text": sms_text,
                "buttons": safe_custom_buttons(fw.get("buttons", []) or []),
                "created_at": time.time(),
            }
            group_card_sessions[session_key] = session
            markup = _otp_group_markup(number, otp, fw.get("buttons", []), session_key=session_key, expanded=False)
            _send_otp_group_card(fw["chat_id"], session, markup=markup, collapsed=True)
        except Exception as exc:
            print(f"[OTP Group] forward error: {exc}")


#==============================================================================
#  [20]  ACCESS CONTROL — ADMIN, FORCE-JOIN, BANS
#==============================================================================
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
#==============================================================================
#  [21]  OTP EXTRACTION & PANEL RESPONSE PARSING
#==============================================================================
def extract_otp_code(text):
    raw_text = html.unescape(str(text or ""))
    if "<" in raw_text and ">" in raw_text:
        try:
            raw_text = BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass
    clean_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', raw_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()

    # Multi-part OTPs such as 123-456 or 80-91-22.
    multi_part = re.search(r'(\d{3}[-\s]+\d{3})|(\d{2}[-\s]+\d{2}[-\s]+\d{2})', clean_text)
    if multi_part:
        return re.sub(r"\s+", "", multi_part.group(0))

    # Google-style codes such as G-123456, including a possible space.
    g_match = re.search(r'\bG\s*-\s*(\d{6})\b', clean_text, re.IGNORECASE)
    if g_match:
        return g_match.group(1)

    # Common email wording: Your verification code is 123456.
    keyword_match = re.search(
        r'\b(?:verification|security|confirmation|one[- ]time|otp|pin|passcode|auth(?:entication)?|code)\b'
        r'.{0,60}?(?:is|:|=|-|your)?\s*([0-9]{4,8})\b',
        clean_text,
        re.IGNORECASE,
    )
    if keyword_match:
        return keyword_match.group(1)

    # Reverse wording: 123456 is your verification code.
    reverse_match = re.search(r'\b([0-9]{4,8})\b.{0,30}\b(?:is your|is the)\b', clean_text, re.IGNORECASE)
    if reverse_match:
        return reverse_match.group(1)

    # Last-resort standalone 4-8 digit code.
    digit_matches = re.findall(r'(?<!\d)\d{4,8}(?!\d)', clean_text)
    if digit_matches:
        return digit_matches[0]
    return None

def parse_panel_response(response_text, p_config=None):
    results = []
    p_type = p_config.get("type", "API Panel") if p_config else "API Panel"

    n_col_name = p_config.get("num_col_name", "number").lower() if p_config else "number"
    m_col_name = p_config.get("msg_col_name", "message").lower() if p_config else "message"
    n_idx = int(p_config.get("num_col_idx", 1)) - 1 if p_config and p_config.get("num_col_idx") else 1
    m_idx = int(p_config.get("msg_col_idx", 2)) - 1 if p_config and p_config.get("msg_col_idx") else 2

    if p_type == "Auto Captcha Panel":
        try:
            soup = BeautifulSoup(response_text, 'html.parser')
            tables = soup.find_all('table')

            for table in tables:
                rows = table.find_all('tr')
                if not rows: continue

                # 🌟 Option 1 + Smart HTML Detection:
                final_n_idx = n_idx
                final_m_idx = m_idx

                #   (Header)
                header_cells = rows[0].find_all(['th', 'td'])
                for i, cell in enumerate(header_cells):
                    c_text = cell.get_text(strip=True).lower()
                    if n_col_name in c_text: final_n_idx = i
                    if m_col_name in c_text: final_m_idx = i

                for row in rows:
                    cols = row.find_all(['td', 'th'])

                    #   (  th )
                    if all(c.name == 'th' for c in cols): continue

                    if len(cols) > max(final_n_idx, final_m_idx):
                        # HTML
                        num_text = cols[final_n_idx].get_text(separator=" ", strip=True)
                        msg_text = cols[final_m_idx].get_text(separator=" ", strip=True)

                        clean_num = re.sub(r'\D', '', num_text)

                        #   -      (    )
                        if clean_num and 5 <= len(clean_num) <= 18:
                            otp = extract_otp_code(msg_text)
                            if otp and len(msg_text) > 4:
                                results.append({"number": clean_num, "message": msg_text, "otp": otp})
        except Exception as e:
            pass
    else:
        try:
            data = json.loads(response_text)
            temp_results = []

            def process_item(item):
                pot_nums_list = []
                pot_msg = None
                values = []

                if isinstance(item, dict):
                    # .   JSON Key (: num, phone, sms)
                    lower_keys = {str(k).lower(): v for k, v in item.items()}
                    for k in ["number", "num", "phone", "msisdn", "sender"]:
                        if k in lower_keys:
                            clean_val = re.sub(r'\D', '', str(lower_keys[k]))
                            if 5 <= len(clean_val) <= 18:
                                if clean_val not in pot_nums_list: pot_nums_list.append(clean_val)
                    for k in ["message", "msg", "sms", "content", "text"]:
                        if k in lower_keys:
                            val = str(lower_keys[k])
                            if len(val) > 4:
                                pot_msg = val
                                break
                    values = list(item.values())
                elif isinstance(item, list):
                    values = item

                # .  Key    ,  Smart Blind Scan (   )
                for v in values:
                    if isinstance(v, (dict, list)) or v is None: continue
                    v_str = str(v).strip()

                    # Number Detection: 7  18
                    clean_v = re.sub(r'\D', '', v_str)
                    if 7 <= len(clean_v) <= 18 and not re.search(r'[a-zA-Z]', v_str):
                        # Date/Time/IP
                        if not re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', v_str) and not re.search(r'\d{2}:\d{2}:\d{2}', v_str) and "." not in v_str:
                            if clean_v not in pot_nums_list:
                                pot_nums_list.append(clean_v)

                    # Message Detection: 5
                    if len(v_str) > 4 and not v_str.isdigit():
                        if extract_otp_code(v_str):
                            if pot_msg is None or len(v_str) > len(pot_msg):
                                pot_msg = v_str

                # 🌟 . Multiple Numbers Logic (User Priority > Second Number > First Number)
                pot_num = None
                if pot_nums_list:
                    matched_user_num = None
                    for n in pot_nums_list:
                        #
                        if n in stex_assigned_numbers or any(n in str(key) for key in stex_assigned_numbers.keys()):
                            matched_user_num = n
                            break

                    if matched_user_num:
                        pot_num = matched_user_num
                    elif len(pot_nums_list) >= 2:
                        pot_num = pot_nums_list[1] #
                    else:
                        pot_num = pot_nums_list[0]

                if pot_num and pot_msg:
                    otp = extract_otp_code(pot_msg)
                    if otp:
                        temp_results.append({"number": pot_num, "message": pot_msg, "otp": otp})

            def traverse_json(node):
                if isinstance(node, list):
                    if len(node) > 0 and not isinstance(node[0], (dict, list)):
                        # It's a flat list representing one record
                        process_item(node)
                    for child in node:
                        if isinstance(child, (dict, list)):
                            traverse_json(child)
                elif isinstance(node, dict):
                    process_item(node)
                    for val in node.values():
                        if isinstance(val, (dict, list)):
                            traverse_json(val)

            traverse_json(data)

            # Remove duplicates
            seen = set()
            for r in temp_results:
                uid = f"{r['number']}_{r['otp']}"
                if uid not in seen:
                    seen.add(uid)
                    results.append(r)
        except: pass

    return results

# 🌟 Advanced Automated Background Captcha Solver 🌟
def attempt_auto_login(p, idx):
    login_url = p.get("login_url", "").strip()
    if not login_url.startswith("http"):
        login_url = "http://" + login_url

    if not login_url.lower().endswith('/login') and not login_url.lower().endswith('.php'):
        login_url = f"{login_url.rstrip('/')}/login"

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    })

    try:
        res = session.get(login_url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        all_text = res.text

        # 1. SOLVE CAPTCHA (Exact bot 3.py logic)
        captcha_match = re.search(r'(\d+\s*[\+\-\*]\s*\d+)\s*[=\?:]', all_text)
        if not captcha_match:
            captcha_match = re.search(r'what is\s*(\d+\s*[\+\-\*]\s*\d+)', all_text, re.I)
        if not captcha_match:
            elements = soup.find_all(["label", "div", "span", "p", "strong"])
            for el in elements:
                txt = el.get_text(separator=" ", strip=True)
                if any(op in txt for op in ["+", "-", "*"]):
                    m = re.search(r'(\d+\s*[\+\-\*]\s*\d+)', txt)
                    if m:
                        captcha_match = m
                        break

        captcha_text = captcha_match.group(1) if captcha_match else "0 + 0"
        answer = "0"
        m2 = re.search(r'(\d+)\s*([\+\-\*])\s*(\d+)', captcha_text)
        if m2:
            a, op, b = int(m2.group(1)), m2.group(2), int(m2.group(3))
            if op == '+': answer = str(a + b)
            elif op == '-': answer = str(a - b)
            elif op == '*': answer = str(a * b)

        # 2. FIND FORM
        form = soup.find("form")
        if not form:
            p["login_status"] = "❌ No login form found"
            return False

        action = form.get("action")
        from urllib.parse import urljoin, quote
        post_url = urljoin(login_url, action) if action else login_url

        form_data = {}
        for hidden in form.find_all("input", type="hidden"):
            name = hidden.get("name")
            if name: form_data[name] = hidden.get("value") or ""

        user_input = form.find("input", {"name": re.compile(r"user|email|id", re.I)}) or \
                     form.find("input", {"type": "text", "placeholder": re.compile(r"user|email", re.I)}) or \
                     form.find("input", {"type": "text"})

        pass_input = form.find("input", {"name": re.compile(r"pass", re.I)}) or \
                     form.find("input", {"type": "password"})

        captcha_input = form.find("input", {"placeholder": re.compile(r"answer|ans|code|verification|value|captcha", re.I)}) or \
                        form.find("input", {"name": re.compile(r"ans|captcha|ver|code", re.I)})

        user_field = user_input.get("name") if user_input else "username"
        pass_field = pass_input.get("name") if pass_input else "password"
        captcha_field = captcha_input.get("name") if captcha_input else "answer"

        form_data[user_field] = p.get("username", "")
        form_data[pass_field] = p.get("password", "")
        if captcha_field:
            form_data[captcha_field] = answer

        # 3. SUBMIT
        login_req = session.post(post_url, data=form_data, allow_redirects=True, timeout=15)

        # 4. VERIFY (Exact bot 3.py check logic)
        msg_link = p.get("msg_link", "").strip()
        if not msg_link.startswith("http") and msg_link != "":
            msg_link = "http://" + msg_link

        check_url = msg_link if msg_link else f"{login_url.split('/login')[0]}/client/SMSCDRStats"

        check_res = session.get(check_url, timeout=FAST_PROVIDER_TIMEOUT)

        if 'logout' in login_req.text.lower() or 'logout' in check_res.text.lower() or 'sms reports' in check_res.text.lower() or 'dashboard' in check_res.text.lower() or 'cdrs' in check_res.text.lower():
            panel_sessions[idx] = session
            p["login_status"] = "✅ Active & Fetching"
            return True
        else:
            #
            p["login_status"] = f"❌ Login Failed (Math: {captcha_text} = {answer})"
            return False

    except Exception as e:
        p["login_status"] = f"❌ Error: {str(e)[:20]}"

    return False

def panel_monitor_thread():
    global processed_otps, recent_traffic, panel_sessions
    while True:
        try:
            for idx, p in enumerate(bot_settings.get("panels", [])):
                if p.get("status") == "ON":

                    if p.get("type") == "Auto Captcha Panel":
                        sess = panel_sessions.get(idx)

                        if not sess:
                            now = time.time()
                            if now - p.get("last_login_attempt", 0) < 30:
                                continue
                            p["last_login_attempt"] = now

                            success = attempt_auto_login(p, idx)
                            save_db() # Save login status text to show in settings
                            if not success:
                                continue
                            sess = panel_sessions.get(idx)

                        try:
                            # 🌟 auto sessions with sAjaxSource and Fallback HTML Parser
                            parsed_data, res_text = fetch_cpt_panel_cdrs(p, sess, p["msg_link"])
                            p["login_status"] = "✅ Active & Fetching"
                        except Exception as e:
                            p["login_status"] = "❌ Session Expired (Retrying...)"
                            del panel_sessions[idx]
                            save_db()
                            continue

                    elif p.get("api_url") or p.get("full_api_url"):
                        full_url = p.get("full_api_url", "").strip()
                        url = p.get("api_url", "").strip()
                        token = p.get("token", "").strip()
                        if not full_url and not url: continue

                        urls_to_try = []
                        if full_url:
                            urls_to_try.append(full_url)
                        else:
                            if "{token}" in url or "{key}" in url:
                                urls_to_try.append(url.replace("{token}", token).replace("{key}", token))
                            elif "token=" in url or "key=" in url:
                                urls_to_try.append(url)
                            else:
                                sep = '&' if '?' in url else '?'
                                urls_to_try.append(f"{url}{sep}token={token}")
                                urls_to_try.append(f"{url}{sep}key={token}&start=0")
                                urls_to_try.append(f"{url}{sep}key={token}")

                        parsed_data = []
                        # 🌟 Browser Bypass (403 Forbidden Fix)
                        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                        for try_url in urls_to_try:
                            try:
                                res = requests.get(try_url, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                                parsed_data = parse_panel_response(res.text, p)
                                if parsed_data:
                                    if not full_url and try_url != url and token:
                                        p["api_url"] = try_url.replace(token, "{token}")
                                        save_db()
                                    break
                            except: continue
                        if not parsed_data: continue
                    else:
                        continue

                    if p.get("type") != "Auto Captcha Panel":
                        limit = p.get("records", 0)
                        if limit > 0: parsed_data = parsed_data[:limit]

                    for item in parsed_data:
                        num = item["number"]
                        otp = item["otp"]
                        msg_text = item["message"]
                        unique_id = f"{num}_{otp}"

                        if unique_id not in processed_otps:
                            processed_otps.add(unique_id)
                            if len(processed_otps) > 5000: processed_otps.clear()

                            char, iso = get_flag_and_code(num)
                            app_full_name, prem_app_html = get_service_info_html(p.get("name", "Panel"), msg_text)
                            current_time = time.time()

                            if _number_has_get_number_owner(num):
                                recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS]
                                recent_traffic.append({
                                    "source": "GET NUMBER",
                                    "service": app_full_name,
                                    "iso": iso,
                                    "flag": char,
                                    "number": num,
                                    "time": current_time
                                })
                                # Only allocated GET NUMBER traffic is counted.
                                save_local_db()

                            display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                            masked = mask_number(display_num)
                            lang = detect_language(msg_text)

                            _forward_otp_to_groups(p.get("name", "Panel"), display_num, otp, lang, msg_text)

                            owners = []
                            clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()

                            # 🌟 ALGORITHM FIX:  Active Sessions
                            # ( Local Stock   Assign      )
                            for uid, session_data in user_active_sessions.items():
                                for act_num in session_data.get("nums", []):
                                    act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                    if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                        owners.append(uid)
                                        break

                            #   StexSMS-
                            if not owners:
                                for stex_n, n_owner in stex_assigned_numbers.items():
                                    clean_stex = str(stex_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                    if clean_stex == clean_api_num or (len(clean_stex) >= 8 and clean_stex.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_stex[-8:])):
                                        owners.append(n_owner)
                            if not owners:
                                owners.extend(_find_fb_tool_owners(clean_api_num))

                            owners = list(set(owners))
                            for owner_id in owners:
                                inbox_kb = _otp_copy_markup(display_num, otp)

                                #
                                reward = reward_for_session_number(owner_id, display_num)
                                if reward > 0:
                                    update_balance(owner_id, reward)
                                    inbox_kb.append([{"text": f"Added {reward} USD", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                _send_otp_inbox(
                                    owner_id,
                                    app_full_name,
                                    display_num,
                                    otp,
                                    lang,
                                    msg_text,
                                    reward=f"{float(reward or 0):g} USD",
                                    markup={"inline_keyboard": inbox_kb},
                                )
                                if db:
                                    try: db.collection('users').document(str(owner_id)).update({"total_otps": firestore.Increment(1)})
                                    except: pass
        except Exception as e:
            pass
        time.sleep(OTP_POLL_INTERVAL)

# ==========================================
# Firebase User Management
# ==========================================
# 🌟 Local User Cache:  Firestore  Read   !
user_cache = {}

#==============================================================================
#  [22]  USER ACCOUNTS — BALANCE & REFERRALS
#==============================================================================
def get_user(user_id):
    global db
    if user_id in user_cache:
        return user_cache[user_id]
    fallback_user = {"user_id": user_id, "balance": 0.0, "total_refers": 0, "total_otps": 0, "banned": False, "verified": False}
    if not db:
        user_cache[user_id] = fallback_user
        return fallback_user
    try:
        doc_ref = db.collection('users').document(str(user_id))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            if "total_otps" not in data: data["total_otps"] = 0
            if "banned" not in data: data["banned"] = False
            if "verified" not in data: data["verified"] = False
            user_cache[user_id] = data
            return data
        new_user = fallback_user.copy()
        doc_ref.set(new_user)
        user_cache[user_id] = new_user
        return new_user
    except Exception as e:
        print(f"❌ Firestore user read/write failed: {type(e).__name__}: {e}")
        disable_firestore("User read/write failed.")
        user_cache[user_id] = fallback_user
        return fallback_user

def update_balance(user_id, amount):
    if user_id in user_cache:
        user_cache[user_id]["balance"] = user_cache[user_id].get("balance", 0.0) + float(amount)
    if not db: return
    try:
        doc_ref = db.collection('users').document(str(user_id))
        # 🌟 No more .get() before update! Saves 1 Read Cost instantly!
        doc_ref.set({"user_id": user_id, "balance": firestore.Increment(float(amount))}, merge=True)
    except: pass

def _send_referral_reward_board(chat_id, reward, from_user_id):
    """Referral reward notification as an image board (borders are pixels)."""
    specs = [("AMOUNT", [f"{reward} USD"]), ("FROM USER ID", [str(from_user_id)])]
    fallback = _menu_grid(PEM['gift'] + " <b>NEW REFERRAL REWARD</b>", [
        ("AMOUNT", f"{reward} USD"),
        ("FROM USER ID", str(from_user_id)),
    ])
    caption = _board_caption_html("🎁 <b>NEW REFERRAL REWARD</b>", specs)
    _send_board_photo(chat_id, "NEW REFERRAL REWARD", specs, caption_html=caption, fallback_html=render_body_text(fallback))


def add_referral(inviter_id, new_user_id):
    if not db.collection('users').document(str(new_user_id)).get().exists:
        get_user(new_user_id)
        reward = bot_settings.get("refer_reward", 0.2)
        update_balance(inviter_id, reward)
        db.collection('users').document(str(inviter_id)).update({"total_refers": firestore.Increment(1)})

        #
        _send_referral_reward_board(inviter_id, reward, str(new_user_id))

# ==========================================
# UI Keyboards & Menu Builders
# ==========================================
#==============================================================================
#  [23]  USER MENUS & KEYBOARDS
#==============================================================================
def get_cancel_kb():
    return {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_state", "style": "danger"}]]}

def main_menu(user_id):
    kb = [
        [{"text": "GET NUMBER", "icon_custom_emoji_id": "5337132498965010628", "style": "primary"}],
        [
            {"text": "TRAFFIC", "icon_custom_emoji_id": "5352877703043258544", "style": "success"},
            {"text": "2FA ONLINE", "icon_custom_emoji_id": "5267421176841398765", "style": "primary"}
        ],
        [
            {"text": "Refer", "icon_custom_emoji_id": "5420396762189831222", "style": "success"},
            {"text": "WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "style": "danger"}
        ],
        [
            {"text": "SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "style": "primary"}
        ]
    ]
    if is_admin(user_id):
        kb.append([{"text": "Admin Panel", "icon_custom_emoji_id": "5420155432272438703", "style": "danger"}])
    return {"keyboard": kb, "resize_keyboard": True}

# ==========================================
# Versia-style User Menu (Premium Emoji Only)
# ==========================================
# Button text intentionally contains NO normal Unicode emoji.
# Premium/custom emoji is attached through icon_custom_emoji_id for buttons
# and <tg-emoji> tags for message bodies.
UIE = {
    "phone": {"char": "☎️", "id": "5337132498965010628"},
    "get": {"char": "⬇️", "id": "5353001161878182134"},
    "refer": {"char": "🫂", "id": "5420145051336485498"},
    "stock": {"char": "📊", "id": "5352877703043258544"},
    "mail": {"char": "📧", "id": "5337302974806922068"},
    "profile": {"char": "👤", "id": "5193063022226086560"},
    "balance": {"char": "💎", "id": "5352838545826420397"},
    "support": {"char": "💬", "id": "5337302974806922068"},
    "admin": {"char": "📊", "id": "5420155432272438703"},
    "traffic": {"char": "📈", "id": "5352877703043258544"},
    "search": {"char": "🔍", "id": "5463352748751753567"},
    "free": {"char": "🌐", "id": "5336972142066047577"},
    "premium": {"char": "💎", "id": "5352838545826420397"},
    "facebook": {"char": "🔵", "id": "5334807341109908955"},
    "back": {"char": "↩️", "id": "5267490665117275176"},
    "copy": {"char": "📋", "id": "5192739271886282680"},
    "refresh": {"char": "🔄", "id": "5465368548702446780"},
    "link": {"char": "🔗", "id": "5420517437885943844"},
    "ok": {"char": "✅", "id": "5352694861990501856"},
    "no": {"char": "❌", "id": "5420130255174145507"},
    "binance": {"char": "💳", "id": "5190899075968441286"},
    "withdraw": {"char": "💸", "id": "5348469219761626211"},
    "question": {"char": "❔", "id": "5336850036145823599"},
    "country": {"char": "🌍", "id": "5336972142066047577"},
    "service": {"char": "📱", "id": "5337132498965010628"},
    "otp": {"char": "🔑", "id": "5197288647275071607"},
}

USER_MENU_LABEL_DEFAULTS = {
    "get_number": "Get Number",
    "refer": "Refer & Earn",
    "stock": "Stock",
    "traffic": "Live Traffic",
    "temp_mail": "Temp Mail",
    "profile": "My Account",
    "balance": "Balance",
    "support": "Support",
    "admin_panel": "Admin Panel",
    "tm_generate": "Generate New Email",
    "tm_refresh": "Refresh",
    "tm_cancel": "Cancel",
    "tm_copy_email": "Copy Email",
    "tm_copy_otp": "Copy OTP",
    "tm_open_browser": "Open in Browser",
}

bot_settings.setdefault("user_menu_emojis", {key: value["id"] for key, value in UIE.items()})
bot_settings.setdefault("user_menu_labels", dict(USER_MENU_LABEL_DEFAULTS))


def menu_label(key):
    labels = bot_settings.get("user_menu_labels")
    if not isinstance(labels, dict):
        labels = {}
    value = labels.get(key, USER_MENU_LABEL_DEFAULTS.get(key, key))
    return str(value or USER_MENU_LABEL_DEFAULTS.get(key, key))


def _user_menu_icon_id(name):
    overrides = bot_settings.get("user_menu_emojis", {})
    value = normalize_local_digits(str(overrides.get(name, ""))).strip()
    if value.isdigit():
        return value
    return UIE.get(name, UIE["ok"])["id"]


def USER_MENU_COMMANDS():
    return {menu_label(key) for key in USER_MENU_LABEL_DEFAULTS} | set(USER_MENU_LABEL_DEFAULTS.values()) | {"GET NUMBER", "SUPPORT"}


def ui_emoji(name):
    data = UIE.get(name, UIE["ok"])
    return f'<tg-emoji emoji-id="{_user_menu_icon_id(name)}">{data["char"]}</tg-emoji>'


def ui_icon(name):
    return _user_menu_icon_id(name)


def user_main_menu(user_id):
    # Keep the screenshot layout: Get Number is full width; Temp Mail sits
    # between Refer & Earn and Balance; the remaining two actions share the
    # final row. Button sizing is left to Telegram's reply-keyboard renderer.
    kb = [
        [{"text": menu_label("get_number"), "icon_custom_emoji_id": ui_icon("phone"), "style": "success"}],
        [
            {"text": menu_label("traffic"), "icon_custom_emoji_id": ui_icon("traffic"), "style": "primary"},
            {"text": menu_label("stock"), "icon_custom_emoji_id": ui_icon("stock"), "style": "primary"},
        ],
        [
            {"text": menu_label("refer"), "icon_custom_emoji_id": ui_icon("refer"), "style": "primary"},
            {"text": menu_label("temp_mail"), "icon_custom_emoji_id": ui_icon("mail"), "style": "primary"},
            {"text": menu_label("balance"), "icon_custom_emoji_id": ui_icon("balance"), "style": "primary"},
        ],
        [
            {"text": menu_label("profile"), "icon_custom_emoji_id": ui_icon("profile"), "style": "success"},
            {"text": menu_label("support"), "icon_custom_emoji_id": ui_icon("support"), "style": "success"},
        ],
    ]
    if is_admin(user_id):
        kb.append([{"text": menu_label("admin_panel"), "icon_custom_emoji_id": _user_menu_icon_id("admin"), "style": "danger"}])
    return {"keyboard": kb, "resize_keyboard": True, "one_time_keyboard": False}


def ui_button(text, icon="ok", callback_data=None, url=None, copy_text=None, style="primary"):
    btn = {"text": text, "icon_custom_emoji_id": ui_icon(icon), "style": style}
    if callback_data:
        btn["callback_data"] = callback_data
    if url:
        btn["url"] = url
    if copy_text is not None:
        btn["copy_text"] = {"text": copy_text}
    return btn


def chunk_buttons(buttons, size=2):
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def _service_icon_id(service):
    emoji_id = ui_icon("service")
    for app_key, app_data in bot_settings.get("premium_apps", {}).items():
        s_up = str(service).upper()
        if s_up == app_key or s_up in app_key or app_key in s_up:
            if app_data.get("id"):
                return app_data["id"]
    return emoji_id


def _country_icon_id(country):
    emoji_id = ui_icon("country")
    c_raw = str(country or "").strip()
    c_up = c_raw.upper()
    digits = re.sub(r"\D", "", c_raw)
    for code, flag_data in bot_settings.get("premium_flags", {}).items():
        iso = str(flag_data.get("iso", "")).upper()
        name = str(flag_data.get("name", "")).upper()
        code_str = str(code).strip()
        if c_up and (c_up == iso or c_up == name or c_up in name or name in c_up):
            if flag_data.get("id"):
                return flag_data["id"]
        if digits and code_str and digits.startswith(code_str):
            if flag_data.get("id"):
                return flag_data["id"]
    if digits:
        _, _, eid = get_flag_info_from_num(digits)
        if eid:
            return eid
    return emoji_id



#==============================================================================
#  [24]  NUMBER RESULTS & DELIVERY
#==============================================================================
def _number_access_label(category):
    cat = _normalize_stock_category(category)
    if cat == "PREMIUM":
        return "PREMIUM NUMBER"
    if cat == "FB":
        return "FB TOOLS USER"
    return "FREE NUMBER"


def _country_dial_code(country):
    raw = str(country or "").strip()
    if not raw:
        return ""
    raw_up = raw.upper()
    raw_digits = re.sub(r"\D", "", raw)
    if raw_digits and len(raw_digits) <= 4:
        return raw_digits
    for key, data in bot_settings.get("premium_flags", {}).items():
        if not isinstance(data, dict):
            continue
        code = str(data.get("code") or (key if str(key).isdigit() else "")).strip()
        iso = str(data.get("iso", "")).upper()
        name = str(data.get("name", "")).upper()
        if raw_up and (raw_up == iso or raw_up == name or raw_up in name or name in raw_up):
            return code
    return ""


def _strip_country_prefix(num, country=None):
    clean = re.sub(r"\D", "", str(num or ""))
    if not clean:
        return ""
    prefixes = []
    c_code = _country_dial_code(country)
    if c_code:
        prefixes.append(c_code)
    for key, data in bot_settings.get("premium_flags", {}).items():
        if not isinstance(data, dict):
            continue
        code = str(data.get("code") or (key if str(key).isdigit() else "")).strip()
        if code and code.isdigit() and clean.startswith(code):
            prefixes.append(code)
    for prefix in sorted(set(prefixes), key=len, reverse=True):
        if prefix and clean.startswith(prefix) and len(clean) - len(prefix) >= 5:
            return clean[len(prefix):]
    return clean


def _number_display_value(num, country=None, show_prefix=True):
    clean = re.sub(r"\D", "", str(num or ""))
    if not clean:
        return str(num or "").strip()
    if show_prefix:
        return f"+{clean}"
    return _strip_country_prefix(clean, country)


def _search_local_numbers_by_prefix(chat_id, session, prefix):
    """Allocate only the requested prefix within the active service/country/category."""
    global total_assigned_stats
    wanted_service = _route_key(session.get("service", ""))
    wanted_country = _route_key(session.get("country", ""))
    wanted_category = _normalize_stock_category(session.get("category", "FREE"))
    prefix = re.sub(r"\D", "", str(prefix or ""))
    found = []
    for batch_id, batch in number_batches.items():
        if not isinstance(batch, dict) or _batch_category(batch) != wanted_category:
            continue
        if _route_key(batch.get("service")) != wanted_service or _route_key(batch.get("country")) != wanted_country:
            continue
        for index, number_obj in enumerate(batch.get("numbers", []) or []):
            if not isinstance(number_obj, dict):
                continue
            raw_number = str(number_obj.get("num", ""))
            clean_number = re.sub(r"\D", "", raw_number)
            if not clean_number.startswith(prefix):
                continue
            if chat_id in (number_obj.get("used_by", []) or []):
                continue
            found.append((batch_id, index, clean_number))

    random.shuffle(found)
    limit = max(1, int(bot_settings.get("num_req", 1) or 1))
    fetched_nums, reward_by_num = [], {}
    selected = found[:limit]
    for batch_id, index, clean_number in selected:
        batch = number_batches.get(batch_id, {})
        number_obj = batch.get("numbers", [])[index]
        fetched_nums.append(clean_number)
        reward_by_num[clean_number] = batch_otp_reward(batch_id)
        number_obj["shares"] = int(number_obj.get("shares", 0) or 0) + 1
        number_obj.setdefault("used_by", []).append(chat_id)
        total_assigned_stats += 1
        if number_obj["shares"] >= bot_settings.get("num_share", 1):
            number_obj["to_remove"] = True
            used_numbers_list.append(clean_number)

    if selected:
        for batch_id in {item[0] for item in selected}:
            batch = number_batches.get(batch_id, {})
            batch["numbers"] = [item for item in batch.get("numbers", []) if not item.get("to_remove")]
        save_db()
    return fetched_nums, reward_by_num


def _number_result_text(service, country, category, fetched_nums, show_prefix=True, reward=None):
    access_label = _number_access_label(category)
    app_name, app_html = get_service_info_html(service)
    country_value = country or (fetched_nums[0] if fetched_nums else "")
    display_numbers = ", ".join(_number_display_value(num, country, show_prefix) for num in (fetched_nums or []))
    if reward is None:
        reward = bot_settings.get("otp_reward", 0.0)
    try:
        reward_text = f"{float(reward or 0.0):g} USD"
    except (TypeError, ValueError):
        reward_text = f"{html.escape(str(reward))} USD"
    return render_card_template(
        "number_card",
        values={
            "service1": app_name,
            "country1": _country_display_name(country_value),
            "category": access_label,
            "number": display_numbers,
            "reward": reward_text,
            "status": "OTP SYSTEM READY",
        },
        trusted_html={"service": f"{app_html} <b>{html.escape(str(app_name).upper())}</b>", "country": get_flag_info_html(country_value)},
        fallback_title=f"{app_name} NUMBER",
    )


def _plain_number_result_text(service, country, category, fetched_nums, show_prefix=True):
    access_label = _number_access_label(category)
    title = str(service or "NUMBER").upper()
    country_txt = str(country or "AUTO").upper()
    numbers = "\n".join(_number_display_value(num, country, show_prefix) for num in (fetched_nums or []))
    return (
        f"{title} NUMBER:\n\n"
        "OTP SYSTEM READY\n"
        "Stay here and wait for OTP.\n\n"
        f"ACCESS TYPE - {access_label}\n"
        f"COUNTRY - {country_txt}\n\n"
        "CLICK THE NUMBER TO COPY\n"
        f"{numbers}"
    ).strip()


def _number_result_markup(service, country, category, fetched_nums, change_country_cb, change_number_cb, show_prefix=True):
    rows = []
    for num in fetched_nums or []:
        display = _number_display_value(num, country, show_prefix)
        rows.append([{
            "text": display,
            "icon_custom_emoji_id": _country_icon_id(num or country),
            "copy_text": {"text": display},
            "style": "primary",
        }])
    rows.append([
        {"text": "Change Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": change_country_cb, "style": "success"},
        {"text": "Change Number", "icon_custom_emoji_id": "5465368548702446780", "callback_data": change_number_cb, "style": "danger"},
    ])
    rows.append([
        {"text": "Find by Prefix", "icon_custom_emoji_id": "5352862640592949843", "callback_data": "prefix_search", "style": "primary"},
    ])
    otp_link = str(bot_settings.get("otp_link", "") or "").strip()
    get_otp_btn = {"text": "Get OTP", "icon_custom_emoji_id": "5190447043545438788", "style": "success"}
    if otp_link:
        get_otp_btn["url"] = otp_link
    else:
        get_otp_btn["callback_data"] = "ignore"
    rows.append([get_otp_btn])
    for button in safe_custom_buttons(_card_template("number_card").get("buttons", [])):
        rows.append([dict(button)])
    return {"inline_keyboard": rows}


def _number_session_payload(message_id, fetched_nums, reward_by_num, service, country, category, change_country_cb, change_number_cb, show_prefix=True):
    return {
        "msg_id": message_id,
        "nums": list(fetched_nums or []),
        "reward_by_num": reward_by_num or {},
        "service": service,
        "country": country,
        "category": _normalize_stock_category(category),
        "change_country_cb": change_country_cb,
        "change_number_cb": change_number_cb,
        "show_prefix": bool(show_prefix),
    }


def _number_card_board(service, country, category, fetched_nums, show_prefix=True, reward=None):
    """Image-board data for the number result card. Returns None when the
    admin replaced the card body in Menu Design (text path wins)."""
    app_name, _app_html = get_service_info_html(service)
    country_value = country or (fetched_nums[0] if fetched_nums else "")
    display_numbers = ", ".join(_number_display_value(num, country, show_prefix) for num in (fetched_nums or []))
    if reward is None:
        reward = bot_settings.get("otp_reward", 0.0)
    try:
        reward_text = f"{float(reward or 0.0):g} USD"
    except (TypeError, ValueError):
        reward_text = f"{html.escape(str(reward))} USD"
    values = {
        "service1": app_name,
        "country1": _country_display_name(country_value),
        "category": _number_access_label(category),
        "number": display_numbers,
        "reward": reward_text,
        "status": "OTP SYSTEM READY",
    }
    trusted_html = {
        "service": f"<b>{html.escape(str(app_name).upper())}</b>",
        "country": get_flag_info_html(country_value),
    }
    board = _minimal_card_board_data(
        "number_card", values=values, trusted_html=trusted_html,
        fallback_title=f"{app_name} NUMBER",
    )
    if board is None:
        return None
    title, specs = board
    caption = _board_caption_html(
        f"📱 <b>{html.escape(str(app_name).upper())} NUMBER</b>", specs,
    )
    return title, specs, caption


def _refresh_number_card(chat_id, message_id=None):
    session = user_active_sessions.get(chat_id) or {}
    msg_id = message_id or session.get("msg_id")
    if not msg_id:
        return False
    service = session.get("service", "NUMBER")
    country = session.get("country", "AUTO")
    category = session.get("display_category", session.get("category", "FREE"))
    nums = session.get("nums", [])
    show_prefix = bool(session.get("show_prefix", True))
    reward_by_num = session.get("reward_by_num") or {}
    session_reward = next(iter(reward_by_num.values()), None)
    text = _number_result_text(service, country, category, nums, show_prefix=show_prefix, reward=session_reward)
    markup = _number_result_markup(
        service,
        country,
        category,
        nums,
        session.get("change_country_cb", "ux_get_number"),
        session.get("change_number_cb", "ux_get_number"),
        show_prefix=show_prefix,
    )
    board = _number_card_board(service, country, category, nums, show_prefix=show_prefix, reward=session_reward)
    sent = None
    if board is not None:
        title, specs, caption = board
        if _caption_plain_length(caption) <= 1000:
            sent = _send_board_photo(
                chat_id, title, specs, caption_html=caption,
                reply_markup=markup, replace_message_id=msg_id,
                fallback_html=text,
            )
    if sent is None:
        res = edit_message(chat_id, msg_id, text, reply_markup=markup)
        sent = res
    if not sent or not sent.get("ok"):
        print(f"[NumberCard] refresh failed: {sent}")
        return False
    new_id = (sent.get("result") or {}).get("message_id")
    if new_id and session.get("msg_id"):
        session["msg_id"] = new_id
    return True


def _deliver_number_card(chat_id, message_id, text, markup, service, country, category, fetched_nums, show_prefix=True, reward=None):
    board = _number_card_board(service, country, category, fetched_nums, show_prefix=show_prefix, reward=reward)
    if board is not None:
        title, specs, caption = board
        if _caption_plain_length(caption) <= 1000:
            sent = _send_board_photo(
                chat_id, title, specs, caption_html=caption,
                reply_markup=markup, replace_message_id=message_id,
                fallback_html=text,
            )
            if sent and sent.get("ok"):
                return (sent.get("result") or {}).get("message_id", message_id)
    active_msg_id = message_id
    edit_res = edit_message(chat_id, message_id, text, reply_markup=markup) if message_id else {}
    if edit_res and edit_res.get("ok"):
        return active_msg_id
    if edit_res and not edit_res.get("ok"):
        print(f"[NumberCard] edit failed: {edit_res}")
    msg_res = send_message(chat_id, text, reply_markup=markup)
    if msg_res and msg_res.get("ok") and msg_res.get("result"):
        return msg_res["result"].get("message_id")
    print(f"[NumberCard] send failed: {msg_res}")
    fallback = api_call("sendMessage", {
        "chat_id": chat_id,
        "text": _plain_number_result_text(service, country, category, fetched_nums, show_prefix=show_prefix),
        "disable_web_page_preview": True,
    })
    if fallback and fallback.get("ok") and fallback.get("result"):
        return fallback["result"].get("message_id")
    print(f"[NumberCard] plain fallback failed: {fallback}")
    return None


#==============================================================================
#  [25]  STOCK ROUTES & ALLOCATION
#==============================================================================
def _all_number_services():
    local_srvs = {b["service"] for b in number_batches.values() if b.get("numbers")}
    stex_srvs = set(bot_settings.get("stex_services", {}).keys())
    voltx_srvs = set(bot_settings.get("voltx_services", {}).keys())
    return sorted(local_srvs.union(stex_srvs).union(voltx_srvs), key=lambda x: str(x).upper())

def _normalize_stock_category(value, default="FREE"):
    raw = str(value or default).upper().strip()
    if "PREMIUM" in raw or raw in {"P", "VIP"}:
        return "PREMIUM"
    if "FB" in raw or "FACEBOOK" in raw:
        return "FB"
    return "FREE"


def _category_title_to_key(access_title):
    return _normalize_stock_category(access_title)


def _batch_category(batch):
    return _normalize_stock_category(batch.get("category", "FREE") if isinstance(batch, dict) else "FREE")


def _route_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _route_ranges(route):
    ranges = route.get("ranges", []) if isinstance(route, dict) else []
    if isinstance(ranges, str):
        ranges = re.split(r"[,;\s]+", ranges)
    return [str(x).strip().upper() for x in (ranges or []) if str(x).strip()]


def _route_category(route):
    return _normalize_stock_category(route.get("category", "FREE") if isinstance(route, dict) else "FREE")


def _route_reward(route):
    try:
        return float(route.get("otp_reward", bot_settings.get("otp_reward", 0.0)))
    except Exception:
        return float(bot_settings.get("otp_reward", 0.0) or 0.0)


def _panel_routes(category_key=None, service=None, country=None):
    try:
        panels = _mk_panels(enabled_only=True)
    except Exception:
        panels = []
    wanted_category = _normalize_stock_category(category_key) if category_key else None
    wanted_service = _route_key(service) if service else None
    wanted_country = _route_key(country) if country else None
    result = []
    for panel in panels:
        for route in panel.get("routes", []) or []:
            ranges = _route_ranges(route)
            if not ranges:
                continue
            if wanted_category and _route_category(route) != wanted_category:
                continue
            if wanted_service and _route_key(route.get("service")) != wanted_service:
                continue
            if wanted_country and _route_key(route.get("country")) != wanted_country:
                continue
            result.append((panel, route))
    return result


def _route_label(route):
    return f"{route.get('service', '?')} / {route.get('country', '?')} / {_route_category(route)} / {_route_reward(route):g} USD"


def _fetch_panel_route_numbers(service, country, category_key, owner_id, limit):
    global total_assigned_stats
    fetched, seen, assignments, reward_by_num = [], set(), [], {}
    limit = max(1, int(limit or 1))
    for panel, route in _panel_routes(category_key, service, country):
        if len(fetched) >= limit:
            break
        reward = _route_reward(route)
        category = _route_category(route)
        for range_text in _route_ranges(route):
            while len(fetched) < limit:
                item = _mk_get_number(panel, range_text)
                number = re.sub(r"\D", "", str((item or {}).get("number", "")))
                if not number:
                    break
                if number in seen:
                    break
                seen.add(number)
                fetched.append(number)
                reward_by_num[number] = reward
                reward_by_num[f"+{number}"] = reward
                assignments.append({
                    "number": number,
                    "panel_id": panel.get("id", ""),
                    "panel_name": panel.get("name", "API Panel"),
                    "range": str(range_text),
                    "reward": reward,
                    "category": category,
                    "service": str(service),
                    "country": str(country),
                })
                total_assigned_stats += 1
            if len(fetched) >= limit:
                break
    if assignments:
        with api_session_lock:
            api_number_sessions[owner_id] = {
                "user_id": owner_id,
                "range": assignments[0].get("range", ""),
                "panel_id": assignments[0].get("panel_id", ""),
                "panel_name": assignments[0].get("panel_name", "API Panel"),
                "assignments": assignments,
                "numbers": [x["number"] for x in assignments],
                "reward_by_num": reward_by_num,
                "category": _normalize_stock_category(category_key),
                "service": str(service),
                "country": str(country),
                "created": time.time(),
            }
    return fetched, reward_by_num, assignments


def _all_number_services_by_category(category_key=None, service_filter=None):
    cat = _normalize_stock_category(category_key) if category_key else None
    services = set()
    for b in number_batches.values():
        if not b.get("numbers"):
            continue
        if cat and _batch_category(b) != cat:
            continue
        services.add(b.get("service"))
    for _, route in _panel_routes(cat):
        services.add(route.get("service"))
    if not cat or cat == "FREE":
        services.update(bot_settings.get("stex_services", {}).keys())
        services.update(bot_settings.get("voltx_services", {}).keys())
    if service_filter:
        f_up = str(service_filter).upper()
        services = {s for s in services if f_up in str(s).upper() or str(s).upper() in f_up}
    return sorted([s for s in services if s], key=lambda x: str(x).upper())


#==============================================================================
#  [26]  USER FLOW SCREENS
#==============================================================================
def _send_or_edit(chat_id, text, reply_markup=None, message_id=None):
    if message_id:
        return edit_message(chat_id, message_id, text, reply_markup=reply_markup)
    return send_message(chat_id, text, reply_markup=reply_markup)


def show_access_menu(chat_id, message_id=None):
    values = {
        "access_type": "FREE / PREMIUM / FB",
        "stock": "LIVE",
        "reward": f"{float(bot_settings.get('otp_reward', 0.0) or 0.0):g} USD",
        "status": "READY",
    }
    buttons = safe_custom_buttons(_card_template("access_type").get("buttons")) or [
        {"text": "FREE NUMBER", "icon_custom_emoji_id": ui_icon("free"), "callback_data": "ux_free_number", "style": "primary"},
        {"text": "PREMIUM NUMBER", "icon_custom_emoji_id": ui_icon("premium"), "callback_data": "ux_premium_number", "style": "primary"},
        {"text": "FB TOOLS USER", "icon_custom_emoji_id": ui_icon("facebook"), "callback_data": "ux_fb_tools", "style": "primary"},
    ]
    return _send_card_board(
        chat_id, "access_type", "☎️ <b>ACCESS TYPE</b>",
        values=values, fallback_title="ACCESS TYPE",
        reply_markup={"inline_keyboard": [[dict(button)] for button in buttons]},
        message_id=message_id,
    )


def show_service_menu(chat_id, message_id=None, access_title="FREE NUMBER", service_filter=None):
    category_key = _category_title_to_key(access_title)
    services = _all_number_services_by_category(category_key, service_filter)
    if not services:
        if category_key == "PREMIUM":
            return show_premium_unavailable(chat_id, message_id, back_cb="ux_get_number")
        txt = render_body_text(
            f"{ui_emoji('no')} <b>{html.escape(access_title)}</b>\n\n"
            "No services available right now."
        )
        kb = {"inline_keyboard": [[ui_button("Back", "back", "ux_get_number", style="danger")]]}
        return _send_or_edit(chat_id, txt, kb, message_id)

    buttons = [ui_button(str(s).upper(), "service", f"gsc:{category_key}:{s}", style="primary") | {"icon_custom_emoji_id": _service_icon_id(s)} for s in services]
    rows = chunk_buttons(buttons, 2)
    for button in safe_custom_buttons(_card_template("service_menu").get("buttons") or bot_settings.get("custom_messages", {}).get("service_menu", {}).get("buttons", [])):
        rows.append([dict(button)])
    rows.append([ui_button("Back", "back", "ux_get_number", style="danger")])
    return _send_card_board(
        chat_id, "service_menu", "📱 <b>SELECT SERVICE</b>",
        values={"access_title": access_title, "service_count": len(services)},
        fallback_title="SELECT SERVICE",
        reply_markup={"inline_keyboard": rows}, message_id=message_id,
    )



#==============================================================================
#  [27]  FACEBOOK TOOLS — PLANS, PAYMENTS & ADMIN
#==============================================================================
def _fb_tools_cfg():
    defaults = {
        "enabled": True,
        "free_limit": 200,
        "free_cooldown": 600,
        "max_per_request": 200,
        "binance_id": os.environ.get("FB_TOOLS_BINANCE_ID", os.environ.get("BINANCE_ID", "")),
        "info_text": "<b>FACEBOOK TOOLS USER</b>\n\n<b>FREE:</b> Free users can request {free_limit} numbers once every {free_minutes} minutes per country.\n\n<b>PREMIUM:</b> Approved premium users can request unlimited numbers with no waiting time.",
        "required_text": "<b>PREMIUM NUMBER Required</b>\n\n<b>Feature:</b> Premium Tools User\n<b>User ID:</b> <code>{user_id}</code>\n<b>Username:</b> {username}\n\n<b>Your PREMIUM NUMBER is not approved yet.</b>\nPlease send a premium request and wait for Owner/Admin approval.",
        "plans": [
            {"label": "1Day-1$", "days": 1, "price": "1 USD"},
            {"label": "2Day-2$", "days": 2, "price": "2 USD"},
            {"label": "7Day-3$", "days": 7, "price": "3 USD"},
        ],
        "payment_methods": ["Binance"],
    }
    cfg = bot_settings.setdefault("fb_tools", {})
    if not isinstance(cfg, dict):
        cfg = {}
        bot_settings["fb_tools"] = cfg
    for key, value in defaults.items():
        if key not in cfg or cfg.get(key) in (None, ""):
            cfg[key] = value
    if not isinstance(cfg.get("plans"), list):
        cfg["plans"] = defaults["plans"]
    old_default_plans = [
        {"label": "3Day-1$", "days": 3, "price": "1 USD"},
        {"label": "7Day-2$", "days": 7, "price": "2 USD"},
    ]
    if cfg.get("plans") == old_default_plans:
        cfg["plans"] = defaults["plans"]
    if not isinstance(cfg.get("payment_methods"), list):
        cfg["payment_methods"] = defaults["payment_methods"]
    return cfg


def _fb_free_minutes():
    try:
        seconds = int(_fb_tools_cfg().get("free_cooldown", 600) or 600)
    except Exception:
        seconds = 600
    return max(1, int(round(seconds / 60)))


def _fb_format_template(raw, chat_id=None, extra=None):
    cfg = _fb_tools_cfg()
    user = get_user(chat_id) if chat_id else {}
    username = str(user.get("username") or "None")
    if username != "None" and not username.startswith("@"):
        username = "@" + username
    data = {
        "free_limit": cfg.get("free_limit", 200),
        "free_cooldown": cfg.get("free_cooldown", 600),
        "free_minutes": _fb_free_minutes(),
        "user_id": chat_id or "",
        "username": html.escape(username),
    }
    if extra:
        data.update(extra)
    try:
        return str(raw).format(**data)
    except Exception:
        return str(raw)


def _fb_is_service(service):
    s = str(service or "").upper().strip()
    return s in {"FB", "FACEBOOK"} or "FACEBOOK" in s or s.startswith("FB ") or s.endswith(" FB")


def _fb_service_list(category):
    services = _all_number_services_by_category(category)
    return sorted([s for s in services if _fb_is_service(s)], key=lambda x: str(x).upper())


def show_fb_tools_menu(chat_id, message_id=None, back_cb="ux_get_number"):
    cfg = _fb_tools_cfg()
    raw = cfg.get("info_text") or "<b>FACEBOOK TOOLS USER</b>"
    generated = f"{ui_emoji('facebook')} " + _fb_format_template(raw, chat_id)
    txt = render_custom_menu_body("fb_tools_menu", {"chat": {"id": chat_id}, "from": {}}, trusted_html={"fb_info": generated})
    rows = [
        [ui_button("FREE", "free", "fb_mode:free", style="primary"), ui_button("PREMIUM", "premium", "fb_mode:premium", style="success")],
        [ui_button("Back", "back", back_cb, style="danger")],
    ]
    for button in safe_custom_buttons(bot_settings.get("custom_messages", {}).get("fb_tools_menu", {}).get("buttons", [])):
        rows.append([dict(button)])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_fb_service_menu(chat_id, message_id=None, mode="free"):
    category = "PREMIUM" if str(mode).lower() == "premium" else "FREE"
    if category == "PREMIUM" and not is_premium_user(chat_id):
        return show_fb_premium_required(chat_id, message_id)
    services = _fb_service_list(category)
    if not services:
        text = render_body_text(
            f"{ui_emoji('facebook')} <b>FACEBOOK TOOLS USER</b>\n\n"
            f"{ui_emoji('no')} <b>No Facebook service stock is available right now.</b>"
        )
        rows = []
        if category == "PREMIUM":
            rows.append([_premium_support_button()])
        rows.append([ui_button("Back", "back", "ux_fb_tools", style="danger")])
        return _send_or_edit(chat_id, text, {"inline_keyboard": rows}, message_id)
    generated = render_body_text(
        f"{ui_emoji('facebook')} <b>FACEBOOK TOOLS USER</b>\n\n"
        f"{ui_emoji('service')} <b>Select platform</b>\n"
        f"<b>MODE:</b> {category}"
    )
    rows = chunk_buttons([
        ui_button(str(s).upper(), "facebook", f"fbsvc:{mode}:{s}", style="primary") | {"icon_custom_emoji_id": _service_icon_id(s)}
        for s in services
    ], 2)
    for button in safe_custom_buttons(bot_settings.get("custom_messages", {}).get("fb_service_menu", {}).get("buttons", [])):
        rows.append([dict(button)])
    rows.append([ui_button("Back", "back", "ux_fb_tools", style="danger")])
    return _send_card_board(
        chat_id, "fb_tools", "🔵 <b>FACEBOOK TOOLS USER</b>",
        values={"mode": category, "free_limit": _fb_tools_cfg().get("free_limit", 200), "status": "READY"},
        fallback_title="FACEBOOK TOOLS USER",
        reply_markup={"inline_keyboard": rows}, message_id=message_id,
    )


def show_fb_country_menu(chat_id, message_id, mode, service):
    category = "PREMIUM" if str(mode).lower() == "premium" else "FREE"
    if category == "PREMIUM" and not is_premium_user(chat_id):
        return show_fb_premium_required(chat_id, message_id)
    local_cnts = {b.get("country") for b in number_batches.values() if b.get("service") == service and b.get("numbers") and _batch_category(b) == category}
    route_cnts = {route.get("country") for _, route in _panel_routes(category, service=service) if route.get("country")}
    stex_cnts = set()
    voltx_cnts = set()
    if category == "FREE":
        stex_cnts = set(bot_settings.get("stex_services", {}).get(service, {}).keys())
        voltx_cnts = set(bot_settings.get("voltx_services", {}).get(service, {}).keys())
    countries = sorted([c for c in local_cnts.union(route_cnts).union(stex_cnts).union(voltx_cnts) if c], key=lambda x: str(x).upper())
    if not countries:
        text = render_body_text(
            f"{ui_emoji('facebook')} <b>FACEBOOK TOOLS USER</b>\n\n"
            f"{ui_emoji('no')} <b>No country stock is available right now.</b>"
        )
        return _send_or_edit(chat_id, text, {"inline_keyboard": [[ui_button("Back", "back", f"fb_mode:{mode}", style="danger")]]}, message_id)
    rows = [[{"text": str(c), "icon_custom_emoji_id": _country_icon_id(c), "callback_data": f"fbcnt:{mode}:{category}:{service}:{c}", "style": "success"}] for c in countries]
    rows.append([ui_button("Back", "back", f"fb_mode:{mode}", style="danger")])
    return _send_card_board(
        chat_id, "country_menu", "🌍 <b>SELECT COUNTRY</b>",
        values={"service1": service, "country_count": len(countries)},
        trusted_html={"service": f"<b>{html.escape(str(service).upper())}</b>"},
        fallback_title=f"{str(service).upper()} COUNTRIES",
        reply_markup={"inline_keyboard": rows}, message_id=message_id,
    )


def show_fb_premium_required(chat_id, message_id=None):
    cfg = _fb_tools_cfg()
    raw = cfg.get("required_text") or "<b>PREMIUM NUMBER Required</b>"
    txt = render_body_text(f"{ui_emoji('premium')} " + _fb_format_template(raw, chat_id))
    kb = {"inline_keyboard": [
        [ui_button("Request Premium", "binance", "fb_request", style="primary")],
        [ui_button("Back", "back", "ux_fb_tools", style="danger")],
    ]}
    return _send_or_edit(chat_id, txt, kb, message_id)


def _fb_plan_button_text(plan):
    label = str(plan.get("label") or "Premium Plan").strip()
    price = str(plan.get("price") or "").strip()
    return label if not price or price.lower() in label.lower() else f"{label} • {price}"


def show_fb_plan_menu(chat_id, message_id=None):
    cfg = _fb_tools_cfg()
    plans = [p for p in cfg.get("plans", []) if isinstance(p, dict)]
    txt = render_body_text("<b>Select a plan below to unlock Premium features.</b>")
    rows = []
    for idx, plan in enumerate(plans):
        rows.append([ui_button(_fb_plan_button_text(plan), "binance", f"fb_plan:{idx}", style="primary")])
    if not rows:
        rows.append([_premium_support_button()])
    rows.append([ui_button("Back", "back", "ux_fb_tools", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_fb_payment_menu(chat_id, message_id, plan_idx):
    cfg = _fb_tools_cfg()
    plans = cfg.get("plans", [])
    if plan_idx < 0 or plan_idx >= len(plans):
        return show_fb_plan_menu(chat_id, message_id)
    methods = [str(m).strip() for m in cfg.get("payment_methods", []) if str(m).strip()]
    plan = plans[plan_idx]
    txt = render_body_text(f"<b>{html.escape(_fb_plan_button_text(plan))}</b>\n\n<b>Choose payment method:</b>")
    rows = [[ui_button(method, "binance", f"fb_pay:{plan_idx}:{idx}", style="primary")] for idx, method in enumerate(methods)]
    if not rows:
        rows.append([_premium_support_button()])
    rows.append([ui_button("Back", "back", "fb_request", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def _send_fb_premium_request(chat_id, plan_idx, method_idx):
    cfg = _fb_tools_cfg()
    plans = cfg.get("plans", [])
    methods = cfg.get("payment_methods", [])
    if plan_idx < 0 or plan_idx >= len(plans):
        return False
    plan = plans[plan_idx]
    method = str(methods[method_idx]).strip() if 0 <= method_idx < len(methods) else "Manual"
    try:
        days = max(1, int(plan.get("days", 1)))
    except Exception:
        days = 1
    user = get_user(chat_id)
    username = str(user.get("username") or "None")
    if username != "None" and not username.startswith("@"):
        username = "@" + username
    admin_text = render_body_text(
        f"{ui_emoji('premium')} <b>NEW FACEBOOK PREMIUM REQUEST</b>\n\n"
        f"<b>User ID:</b> <code>{chat_id}</code>\n"
        f"<b>Username:</b> {html.escape(username)}\n"
        f"<b>Plan:</b> {html.escape(_fb_plan_button_text(plan))}\n"
        f"<b>Days:</b> {days}\n"
        f"<b>Payment Method:</b> {html.escape(method)}"
    )
    markup = {"inline_keyboard": [[
        {"text": "Approve", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"fbapprove:{chat_id}:{days}", "style": "success"},
        {"text": "Reject", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"fbreject:{chat_id}", "style": "danger"},
    ]]}
    sent = False
    for admin_id in bot_settings.get("admins", []):
        try:
            res = send_message(admin_id, admin_text, reply_markup=markup)
            sent = bool(res and res.get("ok")) or sent
        except Exception:
            pass
    return sent



def _fb_plan_days(plan):
    try:
        return max(1, int(plan.get("days", 1)))
    except Exception:
        return 1


def _fb_payment_method(plan_idx, method_idx):
    cfg = _fb_tools_cfg()
    plans = cfg.get("plans", [])
    methods = cfg.get("payment_methods", [])
    if plan_idx < 0 or plan_idx >= len(plans):
        return None, None, "Manual"
    plan = plans[plan_idx]
    method = str(methods[method_idx]).strip() if 0 <= method_idx < len(methods) else "Manual"
    return cfg, plan, method


def _fb_payment_destination(method):
    cfg = _fb_tools_cfg()
    if "binance" in str(method or "").lower():
        return str(cfg.get("binance_id") or "").strip()
    key = re.sub(r"[^a-z0-9]+", "_", str(method or "").lower()).strip("_")
    return str(cfg.get(f"{key}_id") or cfg.get("binance_id") or "").strip()


def show_fb_payment_instruction(chat_id, message_id, plan_idx, method_idx):
    cfg, plan, method = _fb_payment_method(plan_idx, method_idx)
    if not plan:
        return show_fb_plan_menu(chat_id, message_id)
    destination = _fb_payment_destination(method)
    if not destination:
        txt = render_body_text(
            f"{ui_emoji('no')} <b>Payment details are not configured.</b>\n\n"
            "Please contact support or try again later."
        )
        return _send_or_edit(chat_id, txt, {"inline_keyboard": [[_premium_support_button()], [ui_button("Back", "back", "fb_request", style="danger")]]}, message_id)
    user_states[chat_id] = "fb_wait_payment_screenshot"
    temp_data[chat_id] = {
        "msg_id": message_id,
        "plan_idx": plan_idx,
        "method_idx": method_idx,
        "plan": plan,
        "method": method,
        "days": _fb_plan_days(plan),
        "destination": destination,
    }
    txt = render_body_text(
        f"{ui_emoji('binance')} <b>PAYMENT DETAILS</b>\n\n"
        f"<b>Plan:</b> {html.escape(_fb_plan_button_text(plan))}\n"
        f"<b>Premium days:</b> {_fb_plan_days(plan)}\n"
        f"<b>Payment method:</b> {html.escape(method)}\n"
        f"<b>Pay to:</b> <code>{html.escape(destination)}</code>\n\n"
        "After payment, send the payment screenshot here."
    )
    rows = [[ui_button("Back", "back", "fb_request", style="danger")]]
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def _fb_extract_screenshot(msg):
    photos = msg.get("photo") or []
    if photos:
        best = photos[-1]
        return "photo", best.get("file_id")
    doc = msg.get("document") or {}
    if doc.get("file_id"):
        return "document", doc.get("file_id")
    return None, None


def _fb_admin_request_text(user_id, plan, method, destination, txid):
    user = get_user(user_id)
    username = str(user.get("username") or "None")
    if username != "None" and not username.startswith("@"):
        username = "@" + username
    return render_body_text(
        f"{ui_emoji('premium')} <b>NEW FACEBOOK PREMIUM PAYMENT</b>\n\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<b>Username:</b> {html.escape(username)}\n"
        f"<b>Plan:</b> {html.escape(_fb_plan_button_text(plan))}\n"
        f"<b>Days:</b> {_fb_plan_days(plan)}\n"
        f"<b>Payment method:</b> {html.escape(method)}\n"
        f"<b>Pay to:</b> <code>{html.escape(destination)}</code>\n"
        f"<b>Transaction ID:</b> <code>{html.escape(str(txid))}</code>"
    )


def _fb_update_admin_request_message(chat_id, message_id, text):
    clean_text = render_body_text(text)
    res = api_call("editMessageCaption", {"chat_id": chat_id, "message_id": message_id, "caption": clean_text, "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}})
    if not res or not res.get("ok"):
        edit_message(chat_id, message_id, clean_text, reply_markup={"inline_keyboard": []})


def _submit_fb_payment_request(user_id, txid):
    data = temp_data.get(user_id, {})
    plan = data.get("plan") or {}
    method = str(data.get("method") or "Manual")
    destination = str(data.get("destination") or "")
    days = _fb_plan_days(plan)
    screenshot_type = data.get("screenshot_type")
    screenshot_file_id = data.get("screenshot_file_id")
    admin_text = _fb_admin_request_text(user_id, plan, method, destination, txid)
    markup = {"inline_keyboard": [[
        {"text": "Accept", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"fbapprove:{user_id}:{days}", "style": "success"},
        {"text": "Reject", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"fbreject:{user_id}", "style": "danger"},
    ]]}
    sent = False
    for admin_id in bot_settings.get("admins", []):
        try:
            if screenshot_type == "photo" and screenshot_file_id:
                res = send_photo(admin_id, screenshot_file_id, caption=admin_text, reply_markup=markup)
            elif screenshot_type == "document" and screenshot_file_id:
                res = api_call("sendDocument", {"chat_id": admin_id, "document": screenshot_file_id, "caption": admin_text, "parse_mode": "HTML", "reply_markup": markup})
            else:
                res = send_message(admin_id, admin_text, reply_markup=markup)
            sent = bool(res and res.get("ok")) or sent
        except Exception:
            pass
    return sent


def _handle_fb_payment_message(msg):
    chat_id = msg["chat"]["id"]
    state = user_states.get(chat_id)
    text = (msg.get("text") or "").strip()
    if state == "fb_wait_payment_screenshot":
        if text in ("Cancel", "CANCEL", "BACK"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            show_fb_plan_menu(chat_id)
            return True
        screenshot_type, screenshot_file_id = _fb_extract_screenshot(msg)
        if not screenshot_file_id:
            send_message(chat_id, render_body_text("Please send the payment screenshot as a photo or image document."), reply_markup=get_cancel_kb())
            return True
        temp_data.setdefault(chat_id, {})["screenshot_type"] = screenshot_type
        temp_data.setdefault(chat_id, {})["screenshot_file_id"] = screenshot_file_id
        user_states[chat_id] = "fb_wait_payment_txid"
        send_message(chat_id, render_body_text("Screenshot received. Now send the transaction ID."), reply_markup=get_cancel_kb())
        return True
    if state == "fb_wait_payment_txid":
        if text in ("Cancel", "CANCEL", "BACK"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            show_fb_plan_menu(chat_id)
            return True
        if len(text) < 3:
            send_message(chat_id, render_body_text("Send a valid transaction ID."), reply_markup=get_cancel_kb())
            return True
        sent = _submit_fb_payment_request(chat_id, text)
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        if sent:
            send_message(chat_id, render_body_text("Payment request submitted to admin. Please wait for approval."), reply_markup=main_menu(chat_id))
        else:
            send_message(chat_id, render_body_text("Could not submit the request. Please contact support."), reply_markup=main_menu(chat_id))
        return True
    return False


def _fb_usage_key(chat_id, service, country):
    return f"{chat_id}:{str(service).upper()}:{str(country).upper()}"


def _fb_free_allowed(chat_id, service, country):
    cfg = _fb_tools_cfg()
    try:
        limit = max(1, int(cfg.get("free_limit", 200) or 200))
        window = max(1, int(cfg.get("free_cooldown", 600) or 600))
    except Exception:
        limit, window = 200, 600
    key = _fb_usage_key(chat_id, service, country)
    now = time.time()
    items = [t for t in fb_tools_free_usage.get(key, []) if now - float(t) <= window]
    fb_tools_free_usage[key] = items
    if len(items) >= limit:
        wait = max(1, int(window - (now - min(items))))
        return False, wait, limit
    return True, 0, limit


def _fb_record_free_usage(chat_id, service, country, amount):
    if amount <= 0:
        return
    key = _fb_usage_key(chat_id, service, country)
    now = time.time()
    ok, _, limit = _fb_free_allowed(chat_id, service, country)
    items = fb_tools_free_usage.get(key, [])
    items.extend([now] * int(amount))
    fb_tools_free_usage[key] = items[-max(limit * 2, limit):]



def _fb_usage_window(chat_id, service, country):
    cfg = _fb_tools_cfg()
    try:
        limit = max(1, int(cfg.get("free_limit", 200) or 200))
        window = max(1, int(cfg.get("free_cooldown", 600) or 600))
    except Exception:
        limit, window = 200, 600
    key = _fb_usage_key(chat_id, service, country)
    now = time.time()
    items = [t for t in fb_tools_free_usage.get(key, []) if now - float(t) <= window]
    fb_tools_free_usage[key] = items
    remaining = max(0, limit - len(items))
    wait = 0 if remaining > 0 or not items else max(1, int(window - (now - min(items))))
    return remaining, wait, limit, window


def _fb_max_per_request():
    try:
        return max(1, int(_fb_tools_cfg().get("max_per_request", 200) or 200))
    except Exception:
        return 200


def _fb_quantity_cap(chat_id, mode, service, country):
    # Premium users have no admin quantity cap. Free users are limited by
    # the admin-defined TXT quantity and the free usage window.
    if str(mode).lower() == "premium":
        return None, 0
    cap = _fb_max_per_request()
    remaining, wait, _, _ = _fb_usage_window(chat_id, service, country)
    return min(cap, remaining), wait


def show_fb_quantity_prompt(chat_id, message_id, mode, category, service, country):
    category = _normalize_stock_category(category)
    if category == "PREMIUM" and not is_premium_user(chat_id):
        return show_fb_premium_required(chat_id, message_id)
    cap, wait = _fb_quantity_cap(chat_id, mode, service, country)
    if cap is not None and cap <= 0:
        txt = render_body_text(
            f"{ui_emoji('no')} <b>Free limit reached.</b>\n\n"
            f"Please try again after <b>{wait}</b> second(s)."
        )
        return _send_or_edit(chat_id, txt, {"inline_keyboard": [[ui_button("Back", "back", f"fbsvc:{mode}:{service}", style="danger")]]}, message_id)
    user_states[chat_id] = "fb_wait_quantity"
    temp_data[chat_id] = {
        "msg_id": message_id,
        "mode": mode,
        "category": category,
        "service": service,
        "country": country,
        "cap": cap,
    }
    limit_line = "Premium users can request unlimited numbers." if cap is None else f"Admin limit: <b>{cap}</b> number(s) for this request."
    txt = render_body_text(
        f"{ui_emoji('facebook')} <b>FACEBOOK TOOLS USER</b>\n\n"
        f"<b>Service:</b> {html.escape(str(service).upper())}\n"
        f"<b>Country:</b> {html.escape(str(country).upper())}\n\n"
        f"Send how many numbers you want.\n"
        f"{limit_line}\n"
        "Numbers will be delivered as a TXT file.\n"
        "OTP inbox delivery stays active for 24 hours."
    )
    rows = []
    quick = []
    quick_values = (10, 50, 100, 500) if cap is None else (10, 50, 100, cap)
    for value in quick_values:
        if value and value >= 1 and (cap is None or value <= cap) and value not in quick:
            quick.append(value)
    for value in quick:
        rows.append([{"text": f"{value} Number", "icon_custom_emoji_id": "5337132498965010628", "callback_data": f"fbqty:{value}", "style": "primary"}])
    rows.append([ui_button("Back", "back", f"fbsvc:{mode}:{service}", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def _fb_extract_api_assignments(chat_id, nums):
    clean_nums = [clean_number_key(n) for n in nums or []]
    try:
        with api_session_lock:
            api_session = api_number_sessions.get(chat_id) or {}
            return [dict(a) for a in api_session.get("assignments", []) or [] if any(_fb_numbers_match(a.get("number"), n) for n in clean_nums)]
    except Exception:
        return []


def _allocate_fb_tools_numbers(chat_id, service, country, category, count):
    global total_assigned_stats
    fetched_nums = []
    reward_by_num = {}
    count = max(1, int(count or 1))
    category = _normalize_stock_category(category)
    expire_previous_number(chat_id)

    available_indices = []
    for b_id, b_data in number_batches.items():
        if b_data.get("service") == service and b_data.get("country") == country and _batch_category(b_data) == category:
            for idx, n_obj in enumerate(b_data.get("numbers", [])):
                if chat_id not in n_obj.get("used_by", []):
                    available_indices.append((b_id, idx))
    random.shuffle(available_indices)
    for b_id, idx in available_indices:
        if len(fetched_nums) >= count:
            break
        n_obj = number_batches[b_id]["numbers"][idx]
        assigned_num = str(n_obj.get("num", "")).strip()
        if not assigned_num:
            continue
        fetched_nums.append(assigned_num)
        reward = batch_otp_reward(b_id)
        reward_by_num[assigned_num] = reward
        clean_assigned = clean_number_key(assigned_num)
        if clean_assigned:
            reward_by_num[clean_assigned] = reward
            reward_by_num[f"+{clean_assigned}"] = reward
        n_obj["shares"] = int(n_obj.get("shares", 0)) + 1
        n_obj.setdefault("used_by", []).append(chat_id)
        total_assigned_stats += 1
        if n_obj["shares"] >= bot_settings.get("num_share", 1):
            n_obj["to_remove"] = True
            used_numbers_list.append(assigned_num)
    for b_id in number_batches:
        number_batches[b_id]["numbers"] = [n for n in number_batches[b_id].get("numbers", []) if not n.get("to_remove")]

    remaining = count - len(fetched_nums)
    if remaining > 0:
        panel_nums, panel_rewards, _ = _fetch_panel_route_numbers(service, country, category, chat_id, remaining)
        for num in panel_nums:
            if len(fetched_nums) >= count:
                break
            if any(_fb_numbers_match(num, existing) for existing in fetched_nums):
                continue
            fetched_nums.append(num)
        reward_by_num.update(panel_rewards or {})

    remaining = count - len(fetched_nums)
    if remaining > 0 and category == "FREE":
        providers = []
        stex_ranges = bot_settings.get("stex_services", {}).get(service, {}).get(country, []) or []
        voltx_ranges = bot_settings.get("voltx_services", {}).get(service, {}).get(country, []) or []
        if isinstance(stex_ranges, str):
            stex_ranges = [stex_ranges]
        if isinstance(voltx_ranges, str):
            voltx_ranges = [voltx_ranges]
        if stex_ranges:
            providers.append(("stex", list(stex_ranges), bot_settings.get("stex_keys", []), STEX_BASE_URL, stex_assigned_numbers))
        if voltx_ranges:
            providers.append(("voltx", list(voltx_ranges), bot_settings.get("voltx_keys", []), VOLTX_BASE_URL, voltx_assigned_numbers))
        for _ in range(remaining):
            got_num = None
            for _, ranges, keys, base_url, assigned_store in providers:
                if not base_url or not keys or not ranges:
                    continue
                random.shuffle(ranges)
                for range_text in ranges:
                    for api_key in keys:
                        try:
                            headers = {"mauthapi": api_key}
                            res = requests.post(f"{base_url}/getnum", json={"rid": range_text}, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                            data = res.json()
                            if data.get("meta", {}).get("code") == 200 and data.get("data"):
                                raw = data["data"]
                                num = str(raw.get("no_plus_number") or raw.get("national_number") or raw.get("number") or "").replace("+", "")
                                num = clean_number_key(num)
                                if num and not any(_fb_numbers_match(num, existing) for existing in fetched_nums):
                                    got_num = num
                                    assigned_store[num] = chat_id
                                    reward_by_num[num] = float(bot_settings.get("otp_reward", 0.0) or 0.0)
                                    reward_by_num[f"+{num}"] = reward_by_num[num]
                                    total_assigned_stats += 1
                                    break
                        except Exception:
                            continue
                    if got_num:
                        break
                if got_num:
                    break
            if got_num:
                fetched_nums.append(got_num)
            else:
                break
    save_db()
    return fetched_nums, reward_by_num


def _fb_numbers_file_content(service, country, mode, requested, fetched_nums):
    numbers = [_number_display_value(num, country, True) for num in fetched_nums or []]
    lines = [
        "FACEBOOK TOOLS USER NUMBERS",
        f"Service: {str(service).upper()}",
        f"Country: {str(country).upper()}",
        f"Mode: {str(mode).upper()}",
        f"Requested: {requested}",
        f"Delivered: {len(numbers)}",
        "OTP inbox active: 24 hours",
        "",
        "Numbers:",
    ]
    lines.extend(numbers)
    return "\n".join(lines).strip() + "\n"


def _fb_numbers_filename(service, country):
    safe_service = re.sub(r"[^A-Za-z0-9_-]+", "_", str(service or "FACEBOOK").upper()).strip("_") or "FACEBOOK"
    safe_country = re.sub(r"[^A-Za-z0-9_-]+", "_", str(country or "AUTO").upper()).strip("_") or "AUTO"
    return f"facebook_tools_{safe_service}_{safe_country}_{int(time.time())}.txt"


def _allocate_fb_tools_file(chat_id, message_id, mode, category, service, country, count):
    category = _normalize_stock_category(category)
    if category == "PREMIUM" and not is_premium_user(chat_id):
        return show_fb_premium_required(chat_id, message_id)
    cap, wait = _fb_quantity_cap(chat_id, mode, service, country)
    if cap is not None and count > cap:
        txt = render_body_text(
            f"{ui_emoji('no')} <b>Quantity is too high.</b>\n\n"
            f"Admin limit for this request: <b>{cap}</b> number(s)."
        )
        return _send_or_edit(chat_id, txt, {"inline_keyboard": [[ui_button("Back", "back", f"fbcnt:{mode}:{category}:{service}:{country}", style="danger")]]}, message_id)
    edit_message(chat_id, message_id, render_body_text("Finding numbers and preparing TXT file..."))
    fetched_nums, reward_by_num = _allocate_fb_tools_numbers(chat_id, service, country, category, count)
    if not fetched_nums:
        txt = render_body_text(f"{ui_emoji('no')} <b>No number is available right now.</b>")
        return edit_message(chat_id, message_id, txt, reply_markup={"inline_keyboard": [[ui_button("Back", "back", f"fbsvc:{mode}:{service}", style="danger")]]})
    content = _fb_numbers_file_content(service, country, mode, count, fetched_nums)
    send_document(chat_id, _fb_numbers_filename(service, country), content)
    session = _number_session_payload(message_id, fetched_nums, reward_by_num, service, country, category, f"fbsvc:{mode}:{service}", f"fbcnt:{mode}:{category}:{service}:{country}", show_prefix=True)
    session["display_category"] = "FB"
    session["fb_tools_mode"] = mode
    session["expires_at"] = time.time() + FB_TOOLS_SESSION_TTL
    user_active_sessions[chat_id] = session
    _fb_remember_numbers(chat_id, fetched_nums, reward_by_num, service, country, mode, category)
    if str(mode).lower() != "premium":
        _fb_record_free_usage(chat_id, service, country, len(fetched_nums))
    note = ""
    if len(fetched_nums) < count:
        note = f"\nOnly <b>{len(fetched_nums)}</b> number(s) were available now."
    txt = render_body_text(
        f"{ui_emoji('ok')} <b>TXT file sent.</b>\n\n"
        f"<b>Requested:</b> {count}\n"
        f"<b>Delivered:</b> {len(fetched_nums)}{note}\n\n"
        "OTP inbox delivery is active for <b>24 hours</b>."
    )
    rows = [
        [ui_button("Get More", "get", f"fbcnt:{mode}:{category}:{service}:{country}", style="primary")],
        [ui_button("Change Country", "country", f"fbsvc:{mode}:{service}", style="success"), ui_button("Back", "back", "ux_fb_tools", style="danger")],
    ]
    return edit_message(chat_id, message_id, txt, reply_markup={"inline_keyboard": rows})


def _handle_fb_quantity_text(chat_id, text):
    data = temp_data.get(chat_id, {})
    if text in ("Cancel", "CANCEL", "BACK"):
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        return show_fb_country_menu(chat_id, data.get("msg_id"), data.get("mode", "free"), data.get("service", "FACEBOOK"))
    if not str(text).strip().isdigit():
        send_message(chat_id, render_body_text("Send only a number. Example: <code>50</code>"), reply_markup=get_cancel_kb())
        return True
    count = int(str(text).strip())
    mode = data.get("mode", "free")
    category = data.get("category", "FREE")
    service = data.get("service", "FACEBOOK")
    country = data.get("country", "")
    cap, _ = _fb_quantity_cap(chat_id, mode, service, country)
    if count < 1 or (cap is not None and count > cap):
        if cap is None:
            send_message(chat_id, render_body_text("Please send a number greater than <b>0</b>."), reply_markup=get_cancel_kb())
        else:
            send_message(chat_id, render_body_text(f"Please send a number between <b>1</b> and <b>{cap}</b>."), reply_markup=get_cancel_kb())
        return True
    msg_id = data.get("msg_id")
    user_states.pop(chat_id, None)
    temp_data.pop(chat_id, None)
    send_message(chat_id, render_body_text("⌛ <i>Preparing numbers and TXT file...</i>"), reply_markup=get_cancel_kb())
    threading.Thread(
        target=_safe_handle_update,
        args=(lambda _: _allocate_fb_tools_file(chat_id, msg_id, mode, category, service, country, count), None, "fb_number_allocation_text"),
        daemon=True,
    ).start()
    return True


def _show_fb_admin(chat_id, message_id=None):
    cfg = _fb_tools_cfg()
    plans = cfg.get("plans", [])
    methods = cfg.get("payment_methods", [])
    text = render_body_text(
        f"{ui_emoji('facebook')} <b>FACEBOOK TOOLS CONTROL</b>\n\n"
        f"<b>Free limit:</b> {cfg.get('free_limit', 200)} numbers\n"
        f"<b>Free window:</b> {cfg.get('free_cooldown', 600)} seconds\n"
        f"<b>Max free TXT:</b> {cfg.get('max_per_request', 200)} numbers\n"
        f"<b>Plans:</b> {len(plans)}\n"
        f"<b>Payment methods:</b> {len(methods)}\n"
        f"<b>Binance ID:</b> {html.escape(str(cfg.get('binance_id') or 'Not set'))}"
    )
    rows = [
        [ui_button("SET FREE LIMIT", "stock", "fb_set_limit", style="primary"), ui_button("SET FREE WINDOW", "refresh", "fb_set_cooldown", style="primary")],
        [ui_button("SET FREE TXT QTY", "get", "fb_set_max", style="primary")],
        [ui_button("SET INFO TEXT", "facebook", "fb_set_info", style="success")],
        [ui_button("SET REQUIRED TEXT", "premium", "fb_set_required", style="success")],
        [ui_button("ADD PLAN", "get", "fb_add_plan", style="primary"), ui_button("ADD PAYMENT", "binance", "fb_add_payment", style="primary")],
        [ui_button("SET BINANCE ID", "binance", "fb_set_binance", style="success")],
    ]
    for idx, plan in enumerate(plans):
        rows.append([{"text": f"Delete Plan: {_fb_plan_button_text(plan)}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"fb_del_plan:{idx}", "style": "danger"}])
    for idx, method in enumerate(methods):
        rows.append([{"text": f"Delete Payment: {method}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"fb_del_payment:{idx}", "style": "danger"}])
    rows.append([ui_button("Back", "back", "system_settings", style="danger")])
    if message_id:
        return edit_message(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})
    return send_message(chat_id, text, reply_markup={"inline_keyboard": rows})


def _handle_fb_admin_text(chat_id, text):
    mode = user_states.get(chat_id)
    if text in ("Cancel", "CANCEL", "❌ CANCEL"):
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        _show_fb_admin(chat_id)
        return True
    cfg = _fb_tools_cfg()
    try:
        if mode == "fb_wait_limit":
            value = int(text)
            if value < 1:
                raise ValueError
            cfg["free_limit"] = value
        elif mode == "fb_wait_cooldown":
            value = int(text)
            if value < 1:
                raise ValueError
            cfg["free_cooldown"] = value
        elif mode == "fb_wait_max_per_request":
            value = int(text)
            if value < 1:
                raise ValueError
            cfg["max_per_request"] = value
        elif mode == "fb_wait_info":
            cfg["info_text"] = text
        elif mode == "fb_wait_required":
            cfg["required_text"] = text
        elif mode == "fb_wait_plan":
            parts = [x.strip() for x in text.split("|")]
            if len(parts) < 3 or not parts[1].isdigit():
                raise ValueError
            cfg.setdefault("plans", []).append({"label": parts[0], "days": int(parts[1]), "price": parts[2]})
        elif mode == "fb_wait_payment":
            method = text.strip()
            if len(method) < 2:
                raise ValueError
            methods = cfg.setdefault("payment_methods", [])
            if method not in methods:
                methods.append(method)
        elif mode == "fb_wait_binance_id":
            value = text.strip()
            if len(value) < 2:
                raise ValueError
            cfg["binance_id"] = value
        else:
            return False
    except Exception:
        send_message(chat_id, render_body_text("Invalid input. Please try again."), reply_markup=get_cancel_kb())
        return True
    bot_settings["fb_tools"] = cfg
    save_db()
    user_states.pop(chat_id, None)
    temp_data.pop(chat_id, None)
    send_message(chat_id, render_body_text("Saved successfully."))
    _show_fb_admin(chat_id)
    return True


def handle_fb_tools_callback(call):
    chat_id = call["message"]["chat"]["id"]
    msg_id = call["message"].get("message_id")
    data = call.get("data", "")
    if data == "fb_admin":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return True
        _show_fb_admin(chat_id, msg_id)
        return True
    if data in {"fb_set_limit", "fb_set_cooldown", "fb_set_max", "fb_set_info", "fb_set_required", "fb_add_plan", "fb_add_payment", "fb_set_binance"}:
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return True
        state_map = {
            "fb_set_limit": "fb_wait_limit",
            "fb_set_cooldown": "fb_wait_cooldown",
            "fb_set_max": "fb_wait_max_per_request",
            "fb_set_info": "fb_wait_info",
            "fb_set_required": "fb_wait_required",
            "fb_add_plan": "fb_wait_plan",
            "fb_add_payment": "fb_wait_payment",
            "fb_set_binance": "fb_wait_binance_id",
        }
        prompts = {
            "fb_set_limit": "Send free limit as a number. Example: <code>200</code>",
            "fb_set_cooldown": "Send free window in seconds. Example: <code>600</code>",
            "fb_set_max": "Send maximum free-user numbers per TXT file. Example: <code>200</code>",
            "fb_set_info": "Send Facebook Tools info text. Placeholders: <code>{free_limit}</code>, <code>{free_minutes}</code>",
            "fb_set_required": "Send premium required text. Placeholders: <code>{user_id}</code>, <code>{username}</code>",
            "fb_add_plan": "Send plan as: <code>LABEL | DAYS | PRICE</code>\nExample: <code>3Day-1$ | 3 | 1 USD</code>",
            "fb_add_payment": "Send payment method name. Example: <code>Binance</code>",
            "fb_set_binance": "Send the Binance Pay ID or Binance payment details that users must pay to.",
        }
        user_states[chat_id] = state_map[data]
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(prompts[data]), reply_markup=get_cancel_kb())
        return True
    if data.startswith("fb_del_plan:"):
        if is_admin(chat_id):
            idx = int(data.split(":", 1)[1])
            plans = _fb_tools_cfg().setdefault("plans", [])
            if 0 <= idx < len(plans):
                plans.pop(idx)
                save_db()
            _show_fb_admin(chat_id, msg_id)
        return True
    if data.startswith("fb_del_payment:"):
        if is_admin(chat_id):
            idx = int(data.split(":", 1)[1])
            methods = _fb_tools_cfg().setdefault("payment_methods", [])
            if 0 <= idx < len(methods):
                methods.pop(idx)
                save_db()
            _show_fb_admin(chat_id, msg_id)
        return True
    if data.startswith("fbapprove:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return True
        _, user_id, days = data.split(":", 2)
        grant_premium_user(int(user_id), int(days), chat_id)
        _fb_update_admin_request_message(chat_id, msg_id, f"Approved premium access for <code>{user_id}</code> for <b>{int(days)}</b> day(s).")
        return True
    if data.startswith("fbreject:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return True
        user_id = data.split(":", 1)[1]
        try:
            send_message(int(user_id), render_body_text("Your premium request was rejected."))
        except Exception:
            pass
        _fb_update_admin_request_message(chat_id, msg_id, f"Rejected premium request for <code>{user_id}</code>.")
        return True
    if data == "fb_request":
        show_fb_plan_menu(chat_id, msg_id)
        return True
    if data.startswith("fb_plan:"):
        show_fb_payment_menu(chat_id, msg_id, int(data.split(":", 1)[1]))
        return True
    if data.startswith("fb_pay:"):
        _, plan_idx, method_idx = data.split(":", 2)
        show_fb_payment_instruction(chat_id, msg_id, int(plan_idx), int(method_idx))
        return True
    if data.startswith("fb_mode:"):
        mode = data.split(":", 1)[1]
        show_fb_service_menu(chat_id, msg_id, mode)
        return True
    if data.startswith("fbsvc:"):
        _, mode, service = data.split(":", 2)
        show_fb_country_menu(chat_id, msg_id, mode, service)
        return True
    if data.startswith("fbqty:"):
        try:
            count = int(data.split(":", 1)[1])
        except Exception:
            answer_callback(call["id"], "Invalid quantity", show_alert=True)
            return True
        q_data = dict(temp_data.get(chat_id, {}) or {})
        target_msg_id = q_data.get("msg_id", msg_id)
        mode_value = q_data.get("mode", "free")
        category_value = q_data.get("category", "FREE")
        service_value = q_data.get("service", "FACEBOOK")
        country_value = q_data.get("country", "")
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        edit_message(chat_id, target_msg_id, render_body_text("⌛ <i>Preparing numbers and TXT file...</i>"))
        threading.Thread(
            target=_safe_handle_update,
            args=(lambda _: _allocate_fb_tools_file(chat_id, target_msg_id, mode_value, category_value, service_value, country_value, count), None, "fb_number_allocation"),
            daemon=True,
        ).start()
        return True
    if data.startswith("fbcnt:"):
        try:
            _, mode, category, service, country = data.split(":", 4)
        except ValueError:
            answer_callback(call["id"], "Invalid request", show_alert=True)
            return True
        category = _normalize_stock_category(category)
        show_fb_quantity_prompt(chat_id, msg_id, mode, category, service, country)
        return True
    return False


STOCK_PLATFORM_ORDER = [
    ("TELEGRAM", "service"), ("FACEBOOK", "service"), ("WHATSAPP", "service"),
    ("INSTAGRAM", "service"), ("IMO", "service"), ("GOOGLE", "service"),
    ("PAYPAL", "service"), ("TIKTOK", "service"), ("1XBET", "service"),
    ("MELBET", "service"), ("BINANCE", "service"),
]


#==============================================================================
#  [28]  STOCK SCREENS
#==============================================================================
def show_stock_categories(chat_id, message_id=None):
    """Show the required Free/Premium stock split before any platform filter."""
    cm_default = str(DEFAULT_CUSTOM_MESSAGES.get("stock_categories", {}).get("text", "") or "")
    cm_text = str(bot_settings.get("custom_messages", {}).get("stock_categories", {}).get("text", "") or "")
    if cm_text.strip() and cm_text != cm_default:
        # Admin edited this block in Menu Design; render the saved body.
        txt = render_custom_menu_body("stock_categories", {"chat": {"id": chat_id}, "from": {}})
    else:
        txt = render_body_text(
            "📊 <b>STOCK</b>\n\n"
            "Select a stock category to see every available uploaded service."
        )
    rows = [
        [ui_button("💎 PREMIUM NUMBERS", "premium", "stock_category:PREMIUM", style="success")],
        [ui_button("🆓 FREE NUMBERS", "free", "stock_category:FREE", style="success")],
    ]
    for b in safe_custom_buttons(bot_settings.get("custom_messages", {}).get("stock_categories", {}).get("buttons", [])):
        b_copy = dict(b)
        if "style" not in b_copy:
            b_copy["style"] = "primary"
        rows.append([b_copy])
    rows.append([ui_button("BACK", "back", "traffic_main_menu", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_stock_platforms(chat_id, category="FREE", message_id=None):
    category = _normalize_stock_category(category)
    label = "PREMIUM" if category == "PREMIUM" else "FREE"
    txt = render_body_text(f"📊 <b>{label} NUMBERS — FILTER BY PLATFORM</b>")
    rows = []
    for index in range(0, len(STOCK_PLATFORM_ORDER), 2):
        row = []
        for service, _icon_key in STOCK_PLATFORM_ORDER[index:index + 2]:
            row.append(ui_button(service, "stock", f"stock_platform:{category}:{service}", style="success"))
        rows.append(row)
    rows.append([ui_button("ALL SERVICES", "stock", f"stock_category:{category}", style="primary")])
    rows.append([ui_button("BACK", "back", "ux_stock", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def _stock_counter(category="FREE NUMBER"):
    cat = _category_title_to_key(category)
    counts = Counter()
    for b in number_batches.values():
        nums = b.get("numbers", [])
        if not nums:
            continue
        if cat == "FB":
            if "FACEBOOK" not in str(b.get("service", "")).upper() and str(b.get("service", "")).upper() != "FB":
                continue
        elif _batch_category(b) != cat:
            continue
        counts[(str(b.get("country", "UNKNOWN")).upper(), str(b.get("service", "UNKNOWN")).upper())] += len(nums)
    for _, route in _panel_routes(cat):
        country = str(route.get("country", "UNKNOWN")).upper()
        service = str(route.get("service", "UNKNOWN")).upper()
        counts[(country, service)] += max(1, len(_route_ranges(route)))
    if cat == "FREE":
        for service, countries in bot_settings.get("stex_services", {}).items():
            if isinstance(countries, dict):
                for country, ranges in countries.items():
                    n = len(ranges) if isinstance(ranges, list) else 1
                    counts[(str(country).upper(), str(service).upper())] += n
        for service, countries in bot_settings.get("voltx_services", {}).items():
            if isinstance(countries, dict):
                for country, ranges in countries.items():
                    n = len(ranges) if isinstance(ranges, list) else 1
                    counts[(str(country).upper(), str(service).upper())] += n
    return counts

def show_stock_list(chat_id, message_id=None, category="FREE NUMBER", platform=None):
    category_key = _normalize_stock_category(category)
    counts = _stock_counter(category_key)
    if platform:
        target = str(platform).upper()
        counts = Counter({key: amount for key, amount in counts.items() if str(key[1]).upper() == target})
    label = "PREMIUM NUMBERS" if category_key == "PREMIUM" else "FREE NUMBERS"
    if platform:
        label = f"{str(platform).upper()} · {label}"

    entry_lines = []
    if not counts:
        entry_lines.append(f"{ui_emoji('no')} <b>No stock available right now.</b>")
    else:
        for index, ((country, service), amount) in enumerate(sorted(counts.items()), start=1):
            flag_html = get_flag_info_html(country)
            service_name, service_html = get_service_info_html(service)
            service_icon = service_html or f"<tg-emoji emoji-id=\"{_service_icon_id(service)}\">📱</tg-emoji>"
            entry_lines.append(
                f"<b>{index}. {flag_html} {html.escape(str(country).upper())}</b> — "
                f"{service_icon} <b>{html.escape(str(service_name).upper())}</b> · "
                f"<code>{amount}</code> available"
            )
    entries_text = "\n".join(entry_lines)
    stock_body = str(_card_template("stock_list").get("body_text") or "").strip()
    if stock_body:
        # Menu Design body wins; {stock_entries} injects the live entry list.
        txt = render_body_text(_card_token(
            stock_body,
            replacements={"stock_title": label, "total_entries": str(len(counts)), "page": "1"},
            trusted_html={"stock_entries": entries_text},
        ))
    else:
        txt = render_body_text("\n".join([f"📊 <b>{html.escape(label)}</b>", "", entries_text]))
    rows = []
    if not counts and category_key == "PREMIUM":
        rows.append([_premium_support_button()])
    rows.append([ui_button("PLATFORMS", "stock", f"stock_platforms:{category_key}", style="primary")])
    for b in safe_custom_buttons(_card_template("stock_list").get("buttons") or []):
        b_copy = dict(b)
        if "style" not in b_copy:
            b_copy["style"] = "primary"
        rows.append([b_copy])
    rows.append([ui_button("BACK", "back", "ux_stock", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_platform_stock_list(chat_id, platform, category="FREE", message_id=None):
    return show_stock_list(chat_id, message_id, category, platform=str(platform).upper())


def show_stock_services(chat_id, category="FREE", message_id=None):
    """STOCK → Premium/Free numbers → one button per added service."""
    cat = _normalize_stock_category(category)
    label = "PREMIUM" if cat == "PREMIUM" else ("FB TOOLS" if cat == "FB" else "FREE")
    services = _all_number_services_by_category(cat)
    counts = _stock_counter(cat)
    totals = {}
    for (_country, service), amount in counts.items():
        key = str(service).upper()
        totals[key] = totals.get(key, 0) + amount
    rows = []
    for index, svc in enumerate(services):
        total = totals.get(str(svc).upper(), 0)
        rows.append([ui_button(f"{str(svc).upper()} · {total}", "stock", f"stocksvc:{cat}:{index}", style="success")])
    if rows:
        txt = render_body_text(
            f"📊 <b>{label} NUMBERS — SELECT SERVICE</b>\n\n"
            "Tap a service to see country-wise stock."
        )
    else:
        txt = render_body_text(
            f"📊 <b>{label} NUMBERS — SERVICES</b>\n\n"
            f"{ui_emoji('no')} No {label.lower()} services added yet."
        )
        if cat == "PREMIUM":
            rows.append([_premium_support_button()])
    rows.append([ui_button("BACK", "back", "ux_stock", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": rows}, message_id)


def show_stock_country_list(chat_id, category="FREE", service_index=0, message_id=None):
    """One service → country-wise stock table (image board) + PLATFORMS button
    that returns to the service selection page."""
    cat = _normalize_stock_category(category)
    label = "PREMIUM" if cat == "PREMIUM" else ("FB TOOLS" if cat == "FB" else "FREE")
    services = _all_number_services_by_category(cat)
    try:
        idx = int(service_index)
    except (TypeError, ValueError):
        idx = -1
    if idx < 0 or idx >= len(services):
        return show_stock_services(chat_id, cat, message_id)
    svc = str(services[idx]).upper()
    counts = _stock_counter(cat)
    board_rows = []
    total = 0
    for (country, service), amount in sorted(counts.items()):
        if str(service).upper() != svc:
            continue
        total += amount
        board_rows.append((str(country).upper(), [str(amount)]))
    title = f"{svc} · {label} STOCK"
    footer = f"TOTAL IN STOCK: {total}"
    caption_lines = [f"📊 <b>{html.escape(svc)}</b> — {label} NUMBERS", ""]
    if board_rows:
        for country, vlines in board_rows:
            caption_lines.append(f"• {html.escape(country)}: <b>{vlines[0]}</b>")
        caption_lines += ["", f"📦 <b>TOTAL:</b> {total}"]
    else:
        caption_lines.append(f"{ui_emoji('no')} No stock available for this service right now.")
    caption = "\n".join(caption_lines)
    kb_rows = []
    if not board_rows and cat == "PREMIUM":
        kb_rows.append([_premium_support_button()])
    kb_rows.append([ui_button("PLATFORMS", "stock", f"stock_category:{cat}", style="primary")])
    kb_rows.append([ui_button("BACK", "back", "ux_stock", style="danger")])
    if not board_rows:
        # Nothing to draw — plain status message with the PLATFORM button.
        return _send_text_replacing(chat_id, caption, {"inline_keyboard": kb_rows}, message_id)
    return _send_board_photo(
        chat_id, title, board_rows, footer=footer, caption_html=caption,
        reply_markup={"inline_keyboard": kb_rows}, replace_message_id=message_id,
    )


#==============================================================================
#  [29]  PROFILE, BALANCE, WITHDRAWAL & SUPPORT SCREENS
#==============================================================================
def show_referral_dashboard(chat_id, message_id=None):
    u_data = get_user(chat_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
    total_ref = u_data.get("total_refers", 0)
    reward = bot_settings.get("refer_reward", 0.2)
    values = {"ref_link": ref_link, "total_ref": total_ref, "ref_reward": f"{reward:g} USD"}
    c_msg = bot_settings.get("custom_messages", {}).get("referral_dashboard", {})
    share_url = "https://t.me/share/url?url=" + quote(ref_link, safe="")
    rows = [
        [ui_button("Refer Now", "refer", url=share_url, style="primary")],
        [ui_button("Copy Link", "copy", copy_text=ref_link, style="success"), ui_button("Close", "no", "close_msg", style="danger")],
    ]
    for button in safe_custom_buttons(_card_template("referral_dashboard").get("buttons") or c_msg.get("buttons", [])):
        rows.append([dict(button)])
    return _send_card_board(
        chat_id, "referral_dashboard", "🔗 <b>REFERRAL DASHBOARD</b>",
        values=values, fallback_title="REFERRAL DASHBOARD",
        reply_markup={"inline_keyboard": rows}, message_id=message_id,
    )


def _touch_user_profile(msg):
    chat_id = msg["chat"]["id"]
    user = get_user(chat_id)
    from_user = msg.get("from", {})
    updates = {}
    username = from_user.get("username") or user.get("username") or "None"
    if username != user.get("username"):
        updates["username"] = username
    if not user.get("joined_on"):
        updates["joined_on"] = datetime.now().strftime("%d %B %Y")
    if updates:
        user.update(updates)
        user_cache[chat_id] = user
        if db:
            try:
                db.collection('users').document(str(chat_id)).set(updates, merge=True)
            except Exception:
                pass
    return user


def show_profile(chat_id, msg=None, message_id=None):
    u_data = _touch_user_profile(msg) if msg else get_user(chat_id)
    username = u_data.get("username") or "None"
    if username != "None" and not str(username).startswith("@"):
        username = "@" + str(username)
    total_otp = u_data.get("total_otps", 0)
    total_free = u_data.get("total_free_otps", total_otp)
    total_premium = u_data.get("total_premium_otps", 0)
    values = {
        "user_id": chat_id,
        "username": username,
        "joined_on": u_data.get("joined_on", "None"),
        "total_otp": total_otp,
        "total_free": total_free,
        "today_free": u_data.get("today_free_otps", 0),
        "total_premium": total_premium,
        "today_premium": u_data.get("today_premium_otps", 0),
        "total_ref": u_data.get("total_refers", 0),
        "access_valid_until": u_data.get("access_valid_until", "None"),
    }
    fallback_txt = render_minimal_card_template("profile", values=values, fallback_title="USER PROFILE")
    board = _minimal_card_board_data("profile", values=values, fallback_title="USER PROFILE")
    if board is None:
        # Admin saved a custom body in Menu Design — keep the text path.
        return _send_or_edit(chat_id, fallback_txt, None, message_id)
    title, specs = board
    caption_lines = ["👤 <b>USER PROFILE</b>", ""]
    for label, vlines in specs:
        caption_lines.append(f"{html.escape(label)}: <b>{html.escape(' '.join(vlines))}</b>")
    return _send_board_photo(
        chat_id, title, specs, caption_html="\n".join(caption_lines),
        reply_markup=None, replace_message_id=message_id, fallback_html=fallback_txt,
    )


def show_balance(chat_id, message_id=None):
    u_data = get_user(chat_id)
    bal = float(u_data.get("balance", 0.0) or 0.0)
    earned_otp = float(u_data.get("total_otps", 0) or 0.0) * float(bot_settings.get("otp_reward", 0.0) or 0.0)
    earned_ref = float(u_data.get("total_refers", 0) or 0) * float(bot_settings.get("refer_reward", 0.0) or 0.0)
    withdrawn = float(u_data.get("total_withdrawn", 0.0) or 0.0)
    values = {
        "bal": f"${bal:.2f} USD",
        "earned_otp": f"${earned_otp:.2f} USD",
        "earned_ref": f"${earned_ref:.2f} USD",
        "withdrawn": f"${withdrawn:.2f} USD",
    }
    fallback_txt = render_minimal_card_template("balance", values=values, fallback_title="BALANCE")
    board = _minimal_card_board_data("balance", values=values, fallback_title="BALANCE")
    kb = {"inline_keyboard": [
        [ui_button("LINK BINANCE PAY", "binance", "ux_set_binance", style="primary")],
        [ui_button("WITHDRAW FUNDS", "withdraw", "ux_withdraw", style="success")],
    ]}
    if board is None:
        # Admin saved a custom body in Menu Design — keep the text path.
        return _send_or_edit(chat_id, fallback_txt, kb, message_id)
    title, specs = board
    caption_lines = ["💰 <b>BALANCE</b>", ""]
    for label, vlines in specs:
        caption_lines.append(f"{html.escape(label)}: <b>{html.escape(' '.join(vlines))}</b>")
    return _send_board_photo(
        chat_id, title, specs, caption_html="\n".join(caption_lines),
        reply_markup=kb, replace_message_id=message_id, fallback_html=fallback_txt,
    )


def show_withdrawal_menu(chat_id, message_id=None):
    if not bot_settings.get("withdraw_on", True):
        txt = render_body_text(f"{ui_emoji('no')} Withdrawals are currently disabled.")
        return _send_or_edit(chat_id, txt, None, message_id)
    u_data = get_user(chat_id)
    bal = u_data.get('balance', 0.0)
    txt = render_minimal_card_template(
        "withdrawal",
        values={
            "total_otp": u_data.get("total_otps", 0),
            "total_ref": u_data.get("total_refers", 0),
            "bal": f"{bal} USD",
            "min_w": f"{bot_settings.get('min_withdraw', 0)} USD",
        },
        fallback_title="WITHDRAWAL",
    )
    kb = []
    for m in bot_settings.get("w_methods", []):
        kb.append([ui_button(str(m).strip(), "binance", f"sel_wm_{str(m).strip()}", style="primary")])
    kb.append([ui_button("Cancel", "no", "close_msg", style="danger")])
    return _send_or_edit(chat_id, txt, {"inline_keyboard": kb}, message_id)


def _quick_withdraw_start(chat_id, msg_id=None):
    """WITHDRAW FUNDS → one-click withdrawal to the user's saved Binance Pay
    ID: deducts the whole balance, records the request, then tells the user
    the payout went to their set Binance ID and is waiting for admin confirm."""
    if not bot_settings.get("withdraw_on", True):
        txt = render_body_text(f"{ui_emoji('no')} Withdrawals are currently disabled.")
        return _send_text_replacing(chat_id, txt, None, msg_id)
    u_data = get_user(chat_id)
    bal = float(u_data.get("balance", 0.0) or 0.0)
    payout = str(u_data.get("payment_details", "") or "").strip()
    min_w = float(bot_settings.get("min_withdraw", 0) or 0)
    if not payout:
        txt = render_body_text(
            f"{ui_emoji('binance')} <b>NO BINANCE ID SET</b>\n\n"
            "Set your Binance Pay ID first, then tap WITHDRAW FUNDS again."
        )
        kb = {"inline_keyboard": [
            [ui_button("LINK BINANCE PAY", "binance", "ux_set_binance", style="primary")],
            [ui_button("Close", "no", "close_msg", style="danger")],
        ]}
        return _send_text_replacing(chat_id, txt, kb, msg_id)
    if bal <= 0:
        txt = render_body_text(
            f"{ui_emoji('no')} <b>INSUFFICIENT BALANCE</b>\n\nYour balance is empty right now."
        )
        return _send_text_replacing(chat_id, txt, None, msg_id)
    if bal < min_w:
        txt = render_body_text(
            f"{ui_emoji('no')} <b>MINIMUM WITHDRAW IS {min_w:g} USD</b>\n\nYour balance: {bal:.2f} USD"
        )
        return _send_text_replacing(chat_id, txt, None, msg_id)

    amount = bal
    method = "BINANCE PAY"
    req_id = f"W_{str(uuid.uuid4())[:6].upper()}"

    update_balance(chat_id, -amount)
    u_data["total_withdrawn"] = float(u_data.get("total_withdrawn", 0.0) or 0.0) + amount
    user_cache[chat_id] = u_data
    if db:
        try:
            db.collection('users').document(str(chat_id)).set(
                {"total_withdrawn": firestore.Increment(amount)}, merge=True)
        except Exception:
            pass
    pending_withdrawals[req_id] = {
        "user_id": chat_id, "amount": amount, "method": method,
        "number": payout, "full_name": "",
    }
    if db:
        try:
            db.collection('withdrawals').document(req_id).set({
                "user_id": str(chat_id), "amount": amount, "method": method,
                "status": "pending", "timestamp": firestore.SERVER_TIMESTAMP})
        except Exception:
            pass

    admin_msg = (
        f"🎙 <b>NEW WITHDRAWAL REQUEST</b>\n\n"
        f"👤 <b>USER:</b> <a href='tg://user?id={chat_id}'>{chat_id}</a>\n"
        f"💳 <b>WITHDRAWAL:</b> {amount} USD\n"
        f"🍏 <b>PAYOUT DETAILS:</b> <code>{html.escape(payout)}</code>\n"
        f"🏦 <b>METHOD:</b> {method}\n\n"
        f"🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
    )
    wkb = {"inline_keyboard": [[
        {"text": "APPROVE", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"wapp_{req_id}", "style": "success"},
        {"text": "REJECT", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"wrej_{req_id}", "style": "danger"},
    ]]}
    notified = set()
    if bot_settings.get("w_group"):
        try:
            send_message(bot_settings["w_group"], render_body_text(admin_msg), reply_markup=wkb)
            notified.add(str(bot_settings["w_group"]))
        except Exception:
            pass
    for admin_id in bot_settings.get("admins", []):
        if str(admin_id) in notified:
            continue
        try:
            send_message(admin_id, render_body_text(admin_msg), reply_markup=wkb)
        except Exception:
            pass

    txt = render_body_text(
        f"{ui_emoji('ok')} <b>WITHDRAWAL SENT</b>\n\n"
        f"💳 <b>Binance ID:</b> <code>{html.escape(payout)}</code>\n"
        f"💰 <b>Amount:</b> {amount:.2f} USD\n\n"
        f"⏳ Waiting for admin confirmation."
    )
    kb = {"inline_keyboard": [[ui_button("Close", "no", "close_msg", style="danger")]]}
    return _send_text_replacing(chat_id, txt, kb, msg_id)


def show_support(chat_id, message_id=None):
    sup_link = bot_settings.get("support_link", "") or bot_settings.get("premium_support_link", "")
    values = {"status": "ONLINE" if sup_link else "NOT CONFIGURED", "contact": sup_link or "Admin support link unavailable"}
    sup_url = valid_button_url(sup_link)
    if sup_url:
        action = ui_button("CONTACT SUPPORT", "support", url=sup_url, style="primary")
    else:
        action = ui_button("CONTACT SUPPORT", "support", callback_data="ux_support", style="primary")
    return _send_card_board(
        chat_id, "support", "ℹ️ <b>NEED HELP?</b>",
        values=values, fallback_title="NEED HELP?",
        reply_markup={"inline_keyboard": [[action]]}, message_id=message_id,
    )


#==============================================================================
#  [30]  TEMP MAIL SYSTEM
#==============================================================================
def _temp_parts(email):
    login, domain = email.split("@", 1)
    return login, domain


def _generate_temp_email():
    try:
        res = requests.get("https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1", timeout=FAST_PROVIDER_TIMEOUT)
        data = res.json()
        if isinstance(data, list) and data:
            return str(data[0])
    except Exception:
        pass
    return f"dx{random.randint(100000, 999999)}@1secmail.com"


def _temp_mail_fetch_messages(email):
    login, domain = _temp_parts(email)
    try:
        res = requests.get(
            f"https://www.1secmail.com/api/v1/?action=getMessages&login={quote(login)}&domain={quote(domain)}",
            timeout=FAST_PROVIDER_TIMEOUT,
        )
        if not getattr(res, "ok", False):
            return None
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception:
        return None


def _temp_mail_message_key(message):
    return str(message.get("id") or "|".join([
        str(message.get("date", "")),
        str(message.get("from", "")),
        str(message.get("subject", "")),
    ]))


def _temp_mail_read_message(email, message):
    login, domain = _temp_parts(email)
    message_id = message.get("id")
    fallback_subject = str(message.get("subject") or "")
    fallback_sender = str(message.get("from") or "Unknown")
    try:
        read = requests.get(
            f"https://www.1secmail.com/api/v1/?action=readMessage&login={quote(login)}&domain={quote(domain)}&id={quote(str(message_id))}",
            timeout=FAST_PROVIDER_TIMEOUT,
        ).json()
        text_body = str(read.get("textBody") or "")
        html_body = str(read.get("body") or read.get("htmlBody") or "")
        html_text = ""
        if html_body:
            html_text = BeautifulSoup(html_body, "html.parser").get_text(" ", strip=True)
        subject = str(read.get("subject") or fallback_subject)
        sender = str(read.get("from") or fallback_sender)
        body = text_body or html_text or subject
        # Providers may put the OTP only in the HTML version. Scan both
        # versions so Browser and Telegram produce the same code.
        code = extract_otp_code(f"{subject}\n{text_body}\n{html_text}")
        return {
            "id": _temp_mail_message_key(message),
            "message_id": message_id,
            "sender": sender,
            "subject": subject,
            "body": body,
            "code": code,
            "read_ok": True,
        }
    except Exception:
        return {
            "id": _temp_mail_message_key(message),
            "message_id": message_id,
            "sender": fallback_sender,
            "subject": fallback_subject,
            "body": fallback_subject,
            "code": extract_otp_code(fallback_subject),
            "read_ok": False,
        }


def _temp_mail_store_detail(chat_id, detail):
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
        if not session:
            return detail
        messages = session.setdefault("full_messages", {})
        token = detail.get("full_token") or uuid.uuid4().hex[:20]
        detail["full_token"] = token
        messages[token] = detail
        # Keep the latest 50 full-message records for callback buttons.
        while len(messages) > 50:
            messages.pop(next(iter(messages)))
        if detail.get("code"):
            session["latest"] = detail
        return detail


def _temp_mail_browser_url(email):
    """Open the current mailbox in the provider's browser inbox."""
    login, domain = _temp_parts(email)
    return f"https://www.1secmail.com/?login={quote(login)}&domain={quote(domain)}"


def _temp_reply_button(text, icon="ok", style="primary"):
    return {"text": text, "icon_custom_emoji_id": ui_icon(icon), "style": style}


def _temp_mail_reply_markup(email, detail=None):
    """Replace the main menu with only the current Temp Mail controls."""
    if not email:
        rows = [
            [_temp_reply_button(menu_label("tm_generate"), "mail", "success")],
            [_temp_reply_button(menu_label("tm_refresh"), "refresh", "primary")],
            [_temp_reply_button(menu_label("tm_cancel"), "no", "danger")],
        ]
    else:
        rows = [
            [_temp_reply_button(menu_label("tm_generate"), "mail", "primary")],
            [_temp_reply_button(menu_label("tm_refresh"), "refresh", "primary")],
            [_temp_reply_button(menu_label("tm_cancel"), "no", "danger")],
        ]
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": False}


def _temp_mail_card_parts(card_key, header_html, values, fallback_title, extra_caption_lines=None):
    """Build (text, board, caption) for a temp mail card. The board travels
    as a photo; the caption keeps the clean copyable text. When the caption
    will not fit (1024-char Telegram limit) the text path wins."""
    text = render_card_template(card_key, values=values, fallback_title=fallback_title)
    board = _minimal_card_board_data(card_key, values=values, fallback_title=fallback_title)
    caption = ""
    if board is not None:
        caption = _board_caption_html(header_html, board[1], extra_caption_lines)
        if _caption_plain_length(caption) > 1000:
            board = None
            caption = ""
    return text, board, caption


def _send_temp_mail_screen(chat_id, text, email, detail=None, old_message_id=None, inline_actions=None, board=None, caption=""):
    if old_message_id:
        delete_message(chat_id, old_message_id)
    admin_rows = [[button] for button in safe_custom_buttons(_card_template("temp_mail_waiting").get("buttons") or [])]
    kb_rows = ([inline_actions] if inline_actions else []) + admin_rows
    markup = {"inline_keyboard": kb_rows} if kb_rows else None
    result = None
    if board is not None:
        title, specs = board
        result = _send_board_photo(chat_id, title, specs, caption_html=caption, reply_markup=markup, fallback_html=text)
        if result and not result.get("ok"):
            result = None
    if result is None:
        result = send_message(chat_id, text, reply_markup=markup) if markup else send_message(chat_id, text)
    send_message(chat_id, "Temp Mail Controls", reply_markup=_temp_mail_reply_markup(email, detail))
    return result


def _temp_mail_waiting_text(email, status="Waiting for Verification"):
    text, board, caption = _temp_mail_waiting_parts(email, status)
    return text


def _temp_mail_waiting_parts(email, status="Waiting for Verification"):
    return _temp_mail_card_parts(
        "temp_mail_waiting", "📧 <b>TEMP MAIL</b>",
        values={"email": email, "status": status},
        fallback_title="TEMP MAIL",
    )


def _temp_mail_code_text(email, detail):
    text, _board, _caption = _temp_mail_code_parts(email, detail)
    return text


def _temp_mail_code_parts(email, detail):
    code = str(detail.get("code") or "")
    if code:
        status = f"Verification Code: {code}"
    else:
        status = "No verification code has arrived in your inbox yet."
    status = f"{status} | From: {detail.get('sender', 'Unknown')} | {detail.get('subject', '')}"
    if len(status) > 200:
        status = status[:200] + "..."
    return _temp_mail_card_parts(
        "temp_mail_otp", "📩 <b>NEW EMAIL RECEIVED</b>",
        values={
            "email": email,
            "status": status,
            "sender": str(detail.get("sender", "Unknown")),
            "subject": str(detail.get("subject", "")),
        },
        fallback_title="TEMP MAIL OTP",
        extra_caption_lines=[f"🔑 CODE: <b>{html.escape(code)}</b>"] if code else None,
    )


def _temp_mail_received_text(email, detail):
    text, _board, _caption = _temp_mail_received_parts(email, detail)
    return text


def _temp_mail_received_parts(email, detail):
    if detail.get("code"):
        return _temp_mail_code_parts(email, detail)
    return _temp_mail_card_parts(
        "temp_mail_received", "📩 <b>EMAIL RECEIVED</b>",
        values={
            "email": email,
            "status": f"Received from {detail.get('sender', 'Unknown')}: {detail.get('subject', '')}"[:200],
            "sender": str(detail.get("sender", "Unknown")),
            "subject": str(detail.get("subject", "")),
        },
        fallback_title="TEMP MAIL RECEIVED",
    )


def _temp_mail_mark_seen(chat_id, detail):
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
        if not session:
            return
        session.setdefault("seen", set()).add(detail.get("id"))
    return _temp_mail_store_detail(chat_id, detail)


def _temp_mail_read_all(email):
    messages = _temp_mail_fetch_messages(email)
    if messages is None:
        return None
    if not messages:
        return []
    # Read multiple inbox messages concurrently so Refresh stays responsive.
    details = list(temp_mail_read_executor.map(
        lambda message: _temp_mail_read_message(email, message),
        messages,
    ))
    return [detail for detail in details if detail.get("read_ok")]


def _temp_mail_inbox_text(email, details):
    text, _board, _caption = _temp_mail_inbox_parts(email, details)
    return text


def _temp_mail_inbox_parts(email, details):
    entries = []
    if not details:
        entries.append("<b>Your inbox is empty</b>")
    else:
        entries.append("<b>Email messages</b>")
        for index, detail in enumerate(details, 1):
            entry = (
                f"<b>{index}) From:</b> {html.escape(str(detail.get('sender', 'Unknown')))}\n"
                f"<b>Subject:</b> {html.escape(str(detail.get('subject', '')))}"
            )
            if detail.get("code"):
                entry += f"\n<b>Verification Code:</b> <code>{html.escape(str(detail['code']))}</code>"
            preview = str(detail.get("body") or "").strip()
            if preview and preview != str(detail.get("subject") or "").strip():
                preview = preview[:500] + ("..." if len(preview) > 500 else "")
                entry += f"\n<b>Preview:</b> {html.escape(preview)}"
            entries.append(entry)
    summary = f"{len(details)} message(s)" if details else "Inbox is empty"
    caption_entries = []
    for index, detail in enumerate(details or [], 1):
        line = f"{index}) {detail.get('sender', 'Unknown')} — {detail.get('subject', '')}"
        if detail.get("code"):
            line += f" — CODE: {detail['code']}"
        caption_entries.append(html.escape(line[:150]))
    return _temp_mail_card_parts(
        "temp_mail_inbox", "📧 <b>TEMP MAIL INBOX</b>",
        values={"email": email, "status": summary},
        fallback_title="TEMP MAIL INBOX",
        extra_caption_lines=caption_entries,
    )


def _temp_mail_scan_new(chat_id, email, token):
    messages = _temp_mail_fetch_messages(email)
    if messages is None:
        return
    new_messages = []
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
        if not session or session.get("email") != email or session.get("monitor_token") != token:
            return
        seen = session.setdefault("seen", set())
    for message in messages:
        detail_id = _temp_mail_message_key(message)
        if detail_id in seen:
            continue
        detail = _temp_mail_read_message(email, message)
        if not detail.get("read_ok"):
            continue
        with temp_mail_lock:
            session = temp_mail_sessions.get(chat_id)
            if not session or session.get("email") != email or session.get("monitor_token") != token:
                return
            session.setdefault("seen", set()).add(detail_id)
        detail = _temp_mail_store_detail(chat_id, detail)
        new_messages.append(detail)
    for detail in new_messages:
        extra = "\n\n<b>This email was delivered automatically to your Telegram inbox.</b>"
        actions = []
        if detail.get("code"):
            actions.append(ui_button(menu_label("tm_copy_otp"), "copy", copy_text=str(detail.get("code")), style="success"))
        actions.append(ui_button(menu_label("tm_open_browser"), "link", url=_temp_mail_browser_url(email), style="primary"))
        txt, board, caption = _temp_mail_received_parts(email, detail)
        _send_temp_mail_screen(
            chat_id,
            txt + extra,
            email,
            detail=detail,
            inline_actions=actions,
            board=board,
            caption=caption,
        )


def _temp_mail_monitor(chat_id, email, token):
    try:
        while True:
            with temp_mail_lock:
                session = temp_mail_sessions.get(chat_id)
                if not session or session.get("email") != email or session.get("monitor_token") != token:
                    return
                if time.time() >= float(session.get("expires_at", 0) or 0):
                    return
            _temp_mail_scan_new(chat_id, email, token)
            time.sleep(TEMP_MAIL_POLL_SECONDS)
    finally:
        with temp_mail_lock:
            session = temp_mail_sessions.get(chat_id)
            if session and session.get("monitor_token") == token:
                session["monitor_running"] = False


def _start_temp_mail_monitor(chat_id):
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
        if not session or session.get("monitor_running"):
            return
        session["monitor_running"] = True
        email = session["email"]
        token = session["monitor_token"]
    threading.Thread(target=_temp_mail_monitor, args=(chat_id, email, token), daemon=True).start()


def show_temp_mail(chat_id, message_id=None, new=False):
    with temp_mail_lock:
        existing = temp_mail_sessions.get(chat_id)
        expired = existing and time.time() >= float(existing.get("expires_at", 0) or 0)
        if new or not existing or expired:
            temp_mail_sessions[chat_id] = {
                "email": _generate_temp_email() if new else "",
                "seen": set(),
                "latest": None,
                "full_messages": {},
                "expires_at": time.time() + TEMP_MAIL_SESSION_TTL,
                "monitor_token": uuid.uuid4().hex,
                "monitor_running": False,
            }
        session = temp_mail_sessions[chat_id]
        email = session.get("email", "")
    if email:
        _start_temp_mail_monitor(chat_id)
        status = "Waiting for Verification"
    else:
        status = "Press Generate New Email to create a mailbox"
    txt, board, caption = _temp_mail_waiting_parts(email or "Not created yet", status)
    inline_actions = None
    if new and email:
        inline_actions = [ui_button(menu_label("tm_copy_email"), "copy", copy_text=email, style="success")]
    return _send_temp_mail_screen(chat_id, txt, email, old_message_id=message_id, inline_actions=inline_actions, board=board, caption=caption)


def show_temp_mail_full_message(chat_id, token):
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id) or {}
        detail = (session.get("full_messages") or {}).get(str(token))
        email = session.get("email", "")
    if not detail:
        return send_message(chat_id, render_body_text("<b>Full message is no longer available. Please press Refresh Code.</b>"))
    body = str(detail.get("body") or "(The email body is empty.)")
    header = (
        f"{ui_emoji('mail')} <b>Full Email Message</b>\n\n"
        f"<b>Email:</b> <code>{html.escape(str(email))}</code>\n"
        f"<b>From:</b> {html.escape(str(detail.get('sender', 'Unknown')))}\n"
        f"<b>Subject:</b> {html.escape(str(detail.get('subject', '')))}\n\n"
        "<b>Message:</b>\n"
    )
    escaped_body = html.escape(body)
    first_limit = max(500, 3500 - len(header))
    chunks = [escaped_body[:first_limit]]
    rest = escaped_body[first_limit:]
    while rest:
        chunks.append(rest[:3500])
        rest = rest[3500:]
    for index, chunk in enumerate(chunks):
        text = header + chunk if index == 0 else f"<b>Full Email Message (continued)</b>\n\n{chunk}"
        if index == len(chunks) - 1:
            actions = []
            if detail.get("code"):
                actions.append(ui_button(menu_label("tm_copy_otp"), "copy", copy_text=str(detail.get("code")), style="success"))
            actions.append(ui_button(menu_label("tm_open_browser"), "link", url=_temp_mail_browser_url(email), style="primary"))
            _send_temp_mail_screen(chat_id, text, email, detail=detail, inline_actions=actions)
        else:
            send_message(chat_id, text)


def refresh_temp_mail(chat_id, message_id=None):
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
    if not session or not session.get("email"):
        return show_temp_mail(chat_id, message_id=message_id, new=False)
    _start_temp_mail_monitor(chat_id)
    email = session["email"]
    details = _temp_mail_read_all(email)
    if details is None:
        txt, board, caption = _temp_mail_waiting_parts(email, "Unable to refresh the inbox right now. Please try again.")
        return _send_temp_mail_screen(chat_id, txt, email, old_message_id=message_id, board=board, caption=caption)
    for detail in details:
        _temp_mail_mark_seen(chat_id, detail)

    latest_code_detail = next((item for item in reversed(details) if item.get("code")), None)
    if latest_code_detail:
        # An OTP refresh shows the focused OTP card and Copy OTP button.
        txt, board, caption = _temp_mail_code_parts(email, latest_code_detail)
        actions = [ui_button(menu_label("tm_copy_otp"), "copy", copy_text=str(latest_code_detail.get("code")), style="success"), ui_button(menu_label("tm_open_browser"), "link", url=_temp_mail_browser_url(email), style="primary")]
        return _send_temp_mail_screen(chat_id, txt, email, detail=latest_code_detail, old_message_id=message_id, inline_actions=actions, board=board, caption=caption)
    if details:
        # Non-OTP messages remain visible without a Copy OTP button.
        txt, board, caption = _temp_mail_inbox_parts(email, details)
        actions = [ui_button(menu_label("tm_open_browser"), "link", url=_temp_mail_browser_url(email), style="primary")]
        return _send_temp_mail_screen(chat_id, txt, email, old_message_id=message_id, inline_actions=actions, board=board, caption=caption)

    # Empty inbox returns to the original waiting card.
    txt, board, caption = _temp_mail_waiting_parts(email, "Waiting for Verification")
    return _send_temp_mail_screen(chat_id, txt, email, old_message_id=message_id, board=board, caption=caption)


#==============================================================================
#  [31]  USER TEXT & CALLBACK ROUTING
#==============================================================================
def handle_binance_pay_id(chat_id, text):
    pay_id = str(text).strip()
    if len(pay_id) < 3:
        send_message(chat_id, render_body_text(f"{ui_emoji('no')} Invalid Binance Pay ID / payment details. Please send again."), reply_markup=get_cancel_kb())
        return True
    user_states.pop(chat_id, None)
    user = get_user(chat_id)
    user["payment_details"] = pay_id
    user_cache[chat_id] = user
    if db:
        try:
            db.collection('users').document(str(chat_id)).set({"payment_details": pay_id}, merge=True)
        except Exception:
            pass
    send_message(chat_id, render_body_text(f"{ui_emoji('ok')} Binance Pay ID / payment details saved successfully."), reply_markup=main_menu(chat_id))
    return True


def handle_temp_mail_text(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    with temp_mail_lock:
        session = temp_mail_sessions.get(chat_id)
        session_copy = dict(session) if session else None
    temp_labels = {key: menu_label(key) for key in ("tm_copy_email", "tm_generate", "tm_refresh", "tm_copy_otp", "tm_open_browser", "tm_cancel")}
    allowed = set(temp_labels.values()) | {"Copy Email", "Generate New Email", "New Email", "Refresh", "Copy OTP", "Open in Browser", "Cancel", "Back"}
    if not session_copy or text not in allowed:
        return False
    email = session_copy.get("email", "")
    if text in {temp_labels["tm_generate"], "Generate New Email", "New Email"}:
        send_message(chat_id, render_body_text("⌛ <b>Generating a new email address...</b>"), reply_markup=_temp_mail_reply_markup(""))
        threading.Thread(target=_safe_handle_update, args=(lambda _: show_temp_mail(chat_id, new=True), None, "temp_mail_generate"), daemon=True).start()
    elif text in {temp_labels["tm_refresh"], "Refresh"}:
        send_message(chat_id, render_body_text("⌛ <b>Refreshing inbox and checking for OTP...</b>"), reply_markup=_temp_mail_reply_markup(session.get("email", ""), session.get("latest")))
        threading.Thread(target=_safe_handle_update, args=(lambda _: refresh_temp_mail(chat_id), None, "temp_mail_refresh"), daemon=True).start()
    elif text in {temp_labels["tm_cancel"], "Cancel", "Back"}:
        with temp_mail_lock:
            temp_mail_sessions.pop(chat_id, None)
        send_message(chat_id, render_body_text("<b>Temp Mail closed.</b>"), reply_markup=main_menu(chat_id))
    elif text in {temp_labels["tm_copy_email"], "Copy Email"}:
        send_message(chat_id, render_body_text(f"<b>Email:</b> <code>{html.escape(email)}</code>"), reply_markup=_temp_mail_reply_markup(email, session_copy.get("latest")))
    elif text in {temp_labels["tm_copy_otp"], "Copy OTP"}:
        latest = session_copy.get("latest") or {}
        code = str(latest.get("code") or "")
        if code:
            send_message(chat_id, render_body_text(f"<b>OTP:</b> <code>{html.escape(code)}</code>"), reply_markup=_temp_mail_reply_markup(email, latest))
        else:
            send_message(chat_id, render_body_text("<b>No OTP is available yet.</b>"), reply_markup=_temp_mail_reply_markup(email))
    elif text in {temp_labels["tm_open_browser"], "Open in Browser"}:
        url = _temp_mail_browser_url(email)
        send_message(chat_id, render_body_text(f"<b>Open your mailbox:</b>\n<a href=\"{html.escape(url, quote=True)}\">{html.escape(url)}</a>"), reply_markup=_temp_mail_reply_markup(email, session_copy.get("latest")))
    return True


def handle_user_menu_text(msg):
    chat_id = msg["chat"]["id"]
    chat_type = msg["chat"].get("type", "private")
    text = (msg.get("text") or "").strip()
    wants_user_menu = text in USER_MENU_COMMANDS() or user_states.get(chat_id) == "wait_binance_pay_id"
    if not wants_user_menu:
        return False
    if chat_type != "private":
        return True
    register_user_local(chat_id)
    if is_user_banned(chat_id):
        send_message(chat_id, render_body_text(f"{ui_emoji('no')} <b>You are banned from using this bot.</b>"))
        return True
    if not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return True
    if user_states.get(chat_id) == "wait_binance_pay_id":
        return handle_binance_pay_id(chat_id, text)
    user_states.pop(chat_id, None)
    temp_data.pop(chat_id, None)
    if text in {menu_label("get_number"), "Get Number", "GET NUMBER"}:
        show_access_menu(chat_id)
    elif text in {menu_label("traffic"), "Live Traffic", "TRAFFIC"}:
        traffic_text, traffic_markup = build_traffic_ui()
        send_message(chat_id, traffic_text, reply_markup=traffic_markup)
    elif text in {menu_label("refer"), "Refer & Earn", "Refer"}:
        show_referral_dashboard(chat_id)
    elif text in {menu_label("stock"), "Stock"}:
        show_stock_categories(chat_id)
    elif text in {menu_label("temp_mail"), "Temp Mail"}:
        show_temp_mail(chat_id)
    elif text in {menu_label("profile"), "Profile"}:
        show_profile(chat_id, msg=msg)
    elif text in {menu_label("balance"), "Balance"}:
        show_balance(chat_id)
    elif text in {menu_label("support"), "Support", "SUPPORT"}:
        show_support(chat_id)
    elif text in {menu_label("admin_panel"), "Admin Panel"} and is_admin(chat_id):
        send_message(chat_id, get_admin_text(), reply_markup=admin_panel_keyboard())
    return True


def is_user_menu_callback(data):
    return data in {
        "ux_get_number", "ux_free_number", "ux_premium_number", "ux_fb_tools",
        "ux_stock", "ux_stock_free", "ux_stock_premium", "ux_stock_fb",
        "ux_set_binance", "ux_withdraw", "ux_support",
    } or str(data).startswith("stock_category:") or str(data).startswith("stock_platform:") or str(data).startswith("stock_platforms:") or str(data).startswith("stocksvc:") or str(data).startswith("pn_")


def handle_user_menu_callback(call):
    chat_id = call["message"]["chat"]["id"]
    msg_id = call["message"]["message_id"]
    data = call.get("data", "")
    if data == "ux_get_number":
        return show_access_menu(chat_id, msg_id)
    if data == "ux_support":
        return show_support(chat_id, msg_id)
    if data == "ux_free_number":
        return show_service_menu(chat_id, msg_id, "FREE NUMBER")
    if data == "ux_premium_number":
        cleanup_expired_premium_users()
        if not is_premium_user(chat_id):
            return show_premium_number_plan_menu(chat_id, msg_id)
        return show_service_menu(chat_id, msg_id, "PREMIUM NUMBER")
    if data == "ux_fb_tools":
        return show_fb_tools_menu(chat_id, msg_id, back_cb="ux_get_number")
    if data == "ux_stock":
        return show_stock_categories(chat_id, msg_id)
    if data.startswith("stock_category:"):
        return show_stock_services(chat_id, data.split(":", 1)[1], msg_id)
    if data.startswith("stock_platforms:"):
        return show_stock_platforms(chat_id, data.split(":", 1)[1], msg_id)
    if data.startswith("stock_platform:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            return show_platform_stock_list(chat_id, parts[2], parts[1], msg_id)
        return show_platform_stock_list(chat_id, parts[1], "FREE", msg_id)
    if data.startswith("stocksvc:"):
        parts = data.split(":")
        if len(parts) == 3:
            try:
                return show_stock_country_list(chat_id, parts[1], int(parts[2]), msg_id)
            except (TypeError, ValueError):
                pass
        return show_stock_categories(chat_id, msg_id)
    if data == "pn_back":
        return show_premium_number_plan_menu(chat_id, msg_id)
    if data.startswith("pn_plan:"):
        return show_premium_number_payment(chat_id, data.split(":", 1)[1], msg_id)
    if data.startswith("pn_payment:"):
        plan_index = data.split(":", 1)[1]
        user_states[chat_id] = "pn_wait_screenshot"
        temp_data[chat_id] = {"msg_id": msg_id, "plan_index": int(plan_index)}
        return edit_message(chat_id, msg_id, render_body_text("📸 Send the payment screenshot now."), reply_markup=get_cancel_kb())
    if data == "ux_stock_free":
        return show_stock_services(chat_id, "FREE NUMBER", msg_id)
    if data == "ux_stock_premium":
        return show_stock_services(chat_id, "PREMIUM NUMBER", msg_id)
    if data == "ux_stock_fb":
        return show_fb_tools_menu(chat_id, msg_id, back_cb="ux_stock")
    if data == "ux_set_binance":
        user_states[chat_id] = "wait_binance_pay_id"
        txt = render_body_text(f"{ui_emoji('binance')} <b>Send your Binance Pay ID or payout details</b>")
        return edit_message(chat_id, msg_id, txt, reply_markup=get_cancel_kb())
    if data == "ux_withdraw":
        return _quick_withdraw_start(chat_id, msg_id)


#==============================================================================
#  [32]  ADMIN PANEL & SETTINGS KEYBOARDS
#==============================================================================
def get_admin_text():
    """Render the compact screenshot-style Admin Control Panel card."""
    users_count = len(all_known_users)
    total_files = len(number_batches)
    available_nums = sum(len(b.get("numbers", [])) for b in number_batches.values())
    return render_card_template(
        "admin_panel",
        values={
            "users": users_count,
            "files": total_files,
            "numbers": total_uploaded_stats,
            "assigned": total_assigned_stats,
            "available": available_nums,
        },
        fallback_title="ADMIN CONTROL PANEL",
    )

def admin_panel_keyboard():
    return {"inline_keyboard": [
        [{"text": "🔔 UPDATE NOTIFY", "icon_custom_emoji_id": "5465368548702446780", "callback_data": "send_update_notify", "style": "success"}],
        [{"text": "LEADER BOARD SYSTEM", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "lb_main", "style": "success"}],
        [{"text": "Upload Number", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "upload_num", "style": "primary"},
         {"text": "Delete files", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "delete_files", "style": "danger"}],
        [{"text": "Broadcast", "icon_custom_emoji_id": "5789428375261023681", "callback_data": "broadcast_msg", "style": "success"},
         {"text": "System", "icon_custom_emoji_id": "5420155432272438703", "callback_data": "system_settings", "style": "primary"}],
        [{"text": "Used number", "icon_custom_emoji_id": "5352694861990501856", "callback_data": "show_used", "style": "success"},
         {"text": "Unused number", "icon_custom_emoji_id": "5352597830089347330", "callback_data": "show_unused", "style": "success"}],
        [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]
    ]}

def system_settings_keyboard():
    return {"inline_keyboard": [
        [{"text": "StexSMS Control", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "stex_control", "style": "success"},
         {"text": "Voltx Control", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "voltx_control", "style": "primary"}],
        [{"text": "Force Join System", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "manage_fj", "style": "primary"},
         {"text": "Admin Management", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "manage_admins", "style": "danger"}],
        [{"text": "OTP Group", "icon_custom_emoji_id": "5190447043545438788", "callback_data": "manage_otp_groups", "style": "danger"},
         {"text": "User Management", "icon_custom_emoji_id": "5193063022226086560", "callback_data": "user_management", "style": "primary"}],
        [{"text": "Panel MANAGEMENT", "icon_custom_emoji_id": "5336879280578138635", "callback_data": "manage_panels", "style": "danger"},
         {"text": "Subscription", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "dummy_alert", "style": "success"}],
        [{"text": "DXA Control", "icon_custom_emoji_id": "5193100774988617665", "callback_data": "dxa_control", "style": "primary"},
         {"text": "Premium Emoji", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "manage_emojis", "style": "success"}],
        [{"text": "Menu Design", "icon_custom_emoji_id": "5190751148704833975", "callback_data": "menu_design_list", "style": "primary"},
         {"text": "Test", "icon_custom_emoji_id": "5190781475468915802", "callback_data": "test_message_flow", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]
    ]}

def get_user_management_text():
    # 🌟 Fast & Free User Management Stats!
    total = len(all_known_users)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _menu_grid(PEM['hi'] + " <b>USER VIEW</b>", [
        ("TOTAL USERS", str(total)),
        ("VERIFIED", "HIDDEN TO SAVE DB COST"),
        ("BANNED", "HIDDEN TO SAVE DB COST"),
        ("UPDATED", now_str),
    ])

def user_management_keyboard():
    return {"inline_keyboard": [
        [{"text": "Manage Balance", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "um_manage_balance", "style": "primary"},
         {"text": "Ban/Unban User", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "um_ban_unban", "style": "danger"}],
        [{"text": "User Profile", "icon_custom_emoji_id": "5193063022226086560", "callback_data": "um_user_profile", "style": "success"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def menu_design_list_keyboard():
    # Every user-facing screen is editable here. Card-backed screens open the
    # full Card Template editor (title, rows, values, body text, buttons).
    return {"inline_keyboard": [
        [{"text": "Edit /start Menu", "icon_custom_emoji_id": "5395444784611480792", "callback_data": "md_edit_start", "style": "primary"},
         {"text": "Edit GET NUMBER", "icon_custom_emoji_id": "5337132498965010628", "callback_data": "md_edit_get_number", "style": "primary"}],
        [{"text": "Edit Select Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "md_edit_select_country", "style": "primary"},
         {"text": "Edit Access Type", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "md_edit_access_type", "style": "primary"}],
        [{"text": "Edit Service Menu", "icon_custom_emoji_id": "5352694861990501856", "callback_data": "md_edit_service_menu", "style": "primary"},
         {"text": "Edit Search Number", "icon_custom_emoji_id": "5463352748751753567", "callback_data": "md_edit_search_number", "style": "primary"}],
        [{"text": "Edit Number Result", "icon_custom_emoji_id": "5197288647275071607", "callback_data": "md_edit_number_card", "style": "primary"},
         {"text": "Edit Number Broadcast", "icon_custom_emoji_id": "5789428375261023681", "callback_data": "md_edit_number_broadcast", "style": "primary"}],
        [{"text": "Edit Stock Categories", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "md_edit_stock_categories", "style": "primary"},
         {"text": "Edit Stock List", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "md_edit_stock_list", "style": "primary"}],
        [{"text": "Edit OTP Inbox", "icon_custom_emoji_id": "5197288647275071607", "callback_data": "md_edit_otp_inbox", "style": "primary"},
         {"text": "Edit OTP Group", "icon_custom_emoji_id": "5190447043545438788", "callback_data": "md_edit_otp_group", "style": "primary"}],
        [{"text": "Edit Traffic", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "md_edit_traffic", "style": "primary"},
         {"text": "Edit Refer Dashboard", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "md_edit_referral_dashboard", "style": "primary"}],
        [{"text": "Edit Refer Text", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "md_edit_refer", "style": "primary"},
         {"text": "Edit Profile", "icon_custom_emoji_id": "5193063022226086560", "callback_data": "md_edit_profile", "style": "primary"}],
        [{"text": "Edit Balance", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "md_edit_balance", "style": "primary"},
         {"text": "Edit WITHDRAWAL", "icon_custom_emoji_id": "5352585194295564660", "callback_data": "md_edit_withdrawal", "style": "danger"}],
        [{"text": "Edit SUPPORT", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "md_edit_support", "style": "danger"},
         {"text": "Edit Admin Panel", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "md_edit_admin_panel", "style": "danger"}],
        [{"text": "Edit FB Tools Menu", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "md_edit_fb_tools_menu", "style": "primary"},
         {"text": "Edit FB Service Menu", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "md_edit_fb_service_menu", "style": "primary"}],
        [{"text": "Edit Temp Mail Waiting", "icon_custom_emoji_id": "5337302974806922068", "callback_data": "md_edit_temp_mail_waiting", "style": "primary"},
         {"text": "Edit Temp Mail OTP", "icon_custom_emoji_id": "5197288647275071607", "callback_data": "md_edit_temp_mail_otp", "style": "primary"}],
        [{"text": "Edit Temp Mail Inbox", "icon_custom_emoji_id": "5337302974806922068", "callback_data": "md_edit_temp_mail_inbox", "style": "primary"},
         {"text": "Edit Temp Mail Received", "icon_custom_emoji_id": "5337302974806922068", "callback_data": "md_edit_temp_mail_received", "style": "primary"}],
        [{"text": "All Card Templates", "icon_custom_emoji_id": "5395444784611480792", "callback_data": "card_templates_list", "style": "success"},
         {"text": "Fix Dead Buttons", "icon_custom_emoji_id": "5192812028632274956", "callback_data": "md_fix_dead_buttons", "style": "success"}],
        [{"text": "Reset Defaults", "icon_custom_emoji_id": "5192812028632274956", "callback_data": "md_reset_defaults", "style": "success"},
         {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

CARD_TEMPLATE_LABELS = {
    "access_type": "Access Type",
    "service_menu": "Service Menu",
    "country_menu": "Country Menu",
    "number_card": "Number Result",
    "number_broadcast": "Number Broadcast",
    "otp_inbox": "Private OTP Inbox",
    "otp_group": "OTP Group",
    "profile": "Profile",
    "balance": "Balance",
    "withdrawal": "Withdrawal",
    "stock_list": "Stock List",
    "traffic": "Live Traffic",
    "referral_dashboard": "Refer & Earn",
    "support": "Support",
    "temp_mail_waiting": "Temp Mail",
    "fb_tools": "Facebook Tools",
    "admin_panel": "Admin Panel Card",
}


_TEMP_CARD_KEYS = {"temp_mail_otp", "temp_mail_received", "temp_mail_inbox"}


def _card_template(card_key):
    templates = bot_settings.setdefault("card_templates", {})
    if card_key not in templates or not isinstance(templates.get(card_key), dict):
        if card_key in _TEMP_CARD_KEYS and "temp_mail_waiting" in DEFAULT_CARD_TEMPLATES:
            # Temp Mail OTP / Received / Inbox cards clone the Waiting layout
            # by default, so each Menu Design block can be styled on its own.
            templates[card_key] = json.loads(json.dumps(DEFAULT_CARD_TEMPLATES["temp_mail_waiting"]))
        else:
            templates[card_key] = json.loads(json.dumps(DEFAULT_CARD_TEMPLATES.get(card_key, {"title": card_key.upper(), "rows": []})))
    template = templates[card_key]
    template.setdefault("title", card_key.upper())
    template.setdefault("rows", [])
    template.setdefault("buttons", [])

    # Migrate legacy saved cards to the current two-box layouts. Preserve
    # Admin-created buttons, but do not preserve obsolete row structures or
    # full-body texts saved under an older layout generation — a stale plain
    # body keeps covering the new boxed design, which defeats the upgrade.
    # Custom bodies saved from now on (while already on this version) win.
    layout_versions = {
        "access_type": 5, "service_menu": 5, "country_menu": 5,
        "number_card": 5, "number_broadcast": 5, "otp_inbox": 5,
        "otp_group": 5, "profile": 5, "balance": 5, "withdrawal": 5,
        "stock_list": 5, "traffic": 5, "referral_dashboard": 5,
        "support": 5, "temp_mail_waiting": 5, "fb_tools": 5,
        "admin_panel": 5, "temp_mail_otp": 5, "temp_mail_received": 5,
        "temp_mail_inbox": 5,
    }
    if card_key in layout_versions and template.get("_layout_version") != layout_versions[card_key]:
        saved_buttons = json.loads(json.dumps(template.get("buttons") or []))
        base = (DEFAULT_CARD_TEMPLATES.get(card_key)
                or DEFAULT_CARD_TEMPLATES.get("temp_mail_waiting")
                or {"title": card_key.upper(), "rows": []})
        fresh = json.loads(json.dumps(base))
        fresh["buttons"] = saved_buttons
        fresh["_layout_version"] = layout_versions[card_key]
        templates[card_key] = fresh
        template = fresh
        try:
            save_db()
        except Exception:
            pass

    if not template["buttons"]:
        source_buttons = bot_settings.get("custom_messages", {}).get(card_key, {}).get("buttons", [])
        if source_buttons:
            template["buttons"] = json.loads(json.dumps(source_buttons))
    return template


def _card_editor_keyboard(card_key):
    return {"inline_keyboard": [
        [{"text": "Edit Card Title", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"card_title:{card_key}", "style": "primary"}],
        [{"text": "Edit Body (Full Text)", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"card_body:{card_key}", "style": "success"}],
        [{"text": "Edit Row Label", "icon_custom_emoji_id": "5352862640592949843", "callback_data": f"card_rows:label:{card_key}", "style": "primary"},
         {"text": "Edit Row Value", "icon_custom_emoji_id": "5190576863226933563", "callback_data": f"card_rows:value:{card_key}", "style": "primary"}],
        [{"text": "Edit Placeholder", "icon_custom_emoji_id": "5336850036145823599", "callback_data": f"card_rows:placeholder:{card_key}", "style": "primary"}],
        [{"text": "Edit Card Buttons", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"card_buttons:{card_key}", "style": "success"}],
        [{"text": "Preview", "icon_custom_emoji_id": "5353032893096567467", "callback_data": f"card_preview:{card_key}", "style": "success"},
         {"text": "Save", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"card_save:{card_key}", "style": "success"}],
        [{"text": "Back to Card Templates", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "card_templates_list", "style": "danger"}],
    ]}


def _card_templates_list_keyboard():
    rows = []
    for key, label in CARD_TEMPLATE_LABELS.items():
        rows.append([{"text": label, "icon_custom_emoji_id": "5352877703043259581", "callback_data": f"card_open:{key}", "style": "primary"}])
    rows.append([{"text": "Back to Menu Design", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "menu_design_list", "style": "danger"}])
    return {"inline_keyboard": rows}


def _card_rows_keyboard(card_key, field):
    rows = []
    for index, row in enumerate(_card_template(card_key).get("rows", [])):
        label = _card_visible_text(row.get("label", "")) or f"Row {index + 1}"
        current = _card_visible_text(row.get(field, "")) or "Empty"
        rows.append([{"text": f"{index + 1}. {label}: {current[:28]}", "icon_custom_emoji_id": "5352862640592949843", "callback_data": f"card_row:{field}:{card_key}:{index}", "style": "primary"}])
    rows.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"card_open:{card_key}", "style": "danger"}])
    return {"inline_keyboard": rows}


def _card_buttons_keyboard(card_key):
    template = _card_template(card_key)
    rows = []
    buttons = template.get("buttons", [])
    for index, button in enumerate(buttons):
        label = str(button.get("text", "Button"))[:22]
        rows.append([
            {"text": f"Delete {label}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"card_btn_delete:{card_key}:{index}", "style": "danger"},
            {"text": "Edit Text", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"card_btn_text:{card_key}:{index}", "style": "primary"},
        ])
        rows.append([
            {"text": "Edit Action", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"card_btn_action:{card_key}:{index}", "style": "primary"},
            {"text": "Edit Emoji", "icon_custom_emoji_id": "5352552689983067014", "callback_data": f"card_btn_icon:{card_key}:{index}", "style": "primary"},
        ])
    rows.append([{"text": "Add Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"card_btn_add:{card_key}", "style": "success"}])
    rows.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"card_open:{card_key}", "style": "danger"}])
    return {"inline_keyboard": rows}


def _card_preview_values(card_key):
    return {
        "access_type": "FREE NUMBER", "stock": "LIVE", "reward": "0.003 USD", "status": "READY",
        "access_title": "FREE NUMBER", "service_count": "4", "country_count": "12",
        "service1": "WhatsApp", "service_header": "WhatsApp", "country": "🇺🇸", "country1": "United States", "number": "+15551234567",
        "number1": "+•••••67", "otp": "123456", "prefix": "1555123xxxx", "lang": "EN",
        "sms": "Your verification code is 123456", "category": "FREE NUMBER", "total": "5",
        "batch_id": "preview", "user_id": "10001", "username": "@user", "joined_on": "2026-01-01",
        "total_otp": "20", "total_free": "18", "today_free": "2", "total_premium": "2",
        "today_premium": "1", "total_ref": "4", "access_valid_until": "Never", "bal": "$1.00 USD",
        "earned_otp": "$2.00 USD", "earned_ref": "$0.40 USD", "withdrawn": "$0.00 USD",
        "min_w": "$1.00 USD", "stock_title": "FREE NUMBER STOCK", "total_entries": "12",
        "page": "1/1", "stock_entries": "United States — WhatsApp — 10", "window": "LAST 5 MINUTES", "traffic_content": "WhatsApp: 10 OTP", "ref_link": "https://t.me/example?start=10001",
        "ref_reward": "0.01 USD", "contact": "https://t.me/support", "email": "demo@example.com",
        "mode": "FREE", "free_limit": "200",
    }


def _card_editor_text(card_key, prefix="CARD TEMPLATE EDITOR"):
    template = _card_template(card_key)
    rows = []
    for index, row in enumerate(template.get("rows", []), 1):
        collapsed = " [collapsed]" if row.get("collapsed") else ""
        placeholder = row.get("placeholder", "")
        suffix = f" | Placeholder: {placeholder}" if placeholder else ""
        rows.append(f"{index}. {_card_visible_text(row.get('label', ''))} -> {_card_visible_text(row.get('value', ''))}{suffix}{collapsed}")
    body = f"<b>{prefix}</b>\n\n<b>Title:</b> {_card_visible_text(template.get('title', ''))}\n\n" + "\n".join(html.escape(item) for item in rows)
    return render_body_text(body)


def _show_card_editor(chat_id, card_key, message_id=None):
    if not card_key or card_key not in CARD_TEMPLATE_LABELS:
        return _send_or_edit(chat_id, render_body_text("Card template not found."), _card_templates_list_keyboard(), message_id)
    text = _card_editor_text(card_key)
    return _send_or_edit(chat_id, text, _card_editor_keyboard(card_key), message_id)


def _show_card_buttons(chat_id, card_key, message_id=None):
    if not card_key or card_key not in CARD_TEMPLATE_LABELS:
        return _send_or_edit(chat_id, render_body_text("Card template not found."), _card_templates_list_keyboard(), message_id)
    return _send_or_edit(chat_id, _card_editor_text(card_key, "CARD BUTTON EDITOR"), _card_buttons_keyboard(card_key), message_id)


def handle_card_editor_callback(call):
    chat_id = call["message"]["chat"]["id"]
    message_id = call["message"].get("message_id")
    data = str(call.get("data", ""))
    answer_callback(call["id"])
    if data == "card_templates_list":
        return _send_or_edit(chat_id, render_body_text("<b>Card Template Editor</b>\n\nSelect a card. Each card has a separate title, row label, row value, runtime placeholder, and button editor."), _card_templates_list_keyboard(), message_id)
    if data.startswith("card_open:"):
        return _show_card_editor(chat_id, data.split(":", 1)[1], message_id)
    if data.startswith("card_title:"):
        card_key = data.split(":", 1)[1]
        user_states[chat_id] = "card_wait_title"
        temp_data[chat_id] = {"card_key": card_key, "msg_id": message_id}
        return edit_message(chat_id, message_id, render_body_text("Send the new Card Title. Runtime placeholders are allowed."), reply_markup=get_cancel_kb())
    if data.startswith("card_body:"):
        card_key = data.split(":", 1)[1]
        user_states[chat_id] = "card_wait_body"
        temp_data[chat_id] = {"card_key": card_key, "msg_id": message_id}
        current = str(_card_template(card_key).get("body_text") or "").strip()
        note = "A custom body is currently set." if current else "Currently using the built-in title + rows layout."
        return edit_message(chat_id, message_id, render_body_text(f"📝 <b>Edit Body: {card_key.upper()}</b>\n\n{note}\n\nSend the new full body text. Placeholders such as <code>{{otp}}</code>, <code>{{number}}</code>, <code>{{country1}}</code>, <code>{{service1}}</code>, <code>{{brand_name}}</code> are allowed. Send <code>RESET</code> to return to the built-in layout."), reply_markup=get_cancel_kb())
    if data.startswith("card_rows:"):
        _, field, card_key = data.split(":", 2)
        return edit_message(chat_id, message_id, render_body_text(f"Select a row to edit its {field}."), reply_markup=_card_rows_keyboard(card_key, field))
    if data.startswith("card_row:"):
        _, field, card_key, index_raw = data.split(":", 3)
        try:
            index = int(index_raw)
            row = _card_template(card_key)["rows"][index]
        except Exception:
            return edit_message(chat_id, render_body_text("Card row not found."), reply_markup=_card_editor_keyboard(card_key))
        user_states[chat_id] = "card_wait_row"
        temp_data[chat_id] = {"card_key": card_key, "field": field, "row_index": index, "msg_id": message_id}
        current = _card_visible_text(row.get(field, "")) or "Empty"
        return edit_message(chat_id, message_id, render_body_text(f"Send the new {field} for row {index + 1}.\n\nCurrent: <code>{html.escape(current)}</code>\n\nUse placeholders such as <code>{{number}}</code>, <code>{{otp}}</code>, <code>{{country1}}</code> or <code>{{service1}}</code>."), reply_markup=get_cancel_kb())
    if data.startswith("card_buttons:"):
        return _show_card_buttons(chat_id, data.split(":", 1)[1], message_id)
    if data.startswith("card_btn_add:"):
        card_key = data.split(":", 1)[1]
        user_states[chat_id] = "card_wait_button"
        temp_data[chat_id] = {"card_key": card_key, "msg_id": message_id}
        return edit_message(chat_id, message_id, render_body_text("Send: <code>Button Text | callback_data</code> or <code>Button Text | https://example.com | custom_emoji_id</code>"), reply_markup=get_cancel_kb())
    if data.startswith("card_btn_delete:"):
        _, card_key, index_raw = data.split(":", 2)
        try:
            _card_template(card_key).setdefault("buttons", []).pop(int(index_raw))
            save_db()
        except Exception:
            pass
        return _show_card_buttons(chat_id, card_key, message_id)
    if data.startswith(("card_btn_text:", "card_btn_action:", "card_btn_icon:")):
        prefix, card_key, index_raw = data.split(":", 2)
        state = {"card_btn_text": "card_wait_button_text", "card_btn_action": "card_wait_button_action", "card_btn_icon": "card_wait_button_icon"}[prefix]
        user_states[chat_id] = state
        temp_data[chat_id] = {"card_key": card_key, "button_index": int(index_raw), "msg_id": message_id}
        prompt = {"card_wait_button_text": "Send the new button text.", "card_wait_button_action": "Send the new callback data or URL.", "card_wait_button_icon": "Send one valid custom emoji ID or Premium Emoji."}[state]
        return edit_message(chat_id, message_id, render_body_text(prompt), reply_markup=get_cancel_kb())
    if data.startswith("card_preview:"):
        card_key = data.split(":", 1)[1]
        preview = render_card_template(card_key, values=_card_preview_values(card_key), collapsed=False, fallback_title="CARD PREVIEW")
        return edit_message(chat_id, message_id, preview, reply_markup=_card_editor_keyboard(card_key))
    if data.startswith("card_save:"):
        card_key = data.split(":", 1)[1]
        save_db()
        return edit_message(chat_id, message_id, _card_editor_text(card_key, "CARD TEMPLATE SAVED"), reply_markup=_card_editor_keyboard(card_key))
    return False


def menu_edit_options_keyboard(menu_key):
    rows = [
        [{"text": "Edit Body (Text)", "icon_custom_emoji_id": "5395444784611480792", "callback_data": f"md_text_{menu_key}", "style": "primary"}],
        [{"text": "Edit Inline Buttons", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"md_btns_{menu_key}", "style": "success"}],
    ]
    if menu_key == "start":
        rows.append([{"text": "Remove /start Image", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "md_remove_start_media", "style": "danger"}])
    rows.append([{"text": "Back to Menus", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "menu_design_list", "style": "danger"}])
    return {"inline_keyboard": rows}

_MD_CM_BUTTON_KEYS = {"start", "get_number", "select_country", "withdrawal", "support", "fb_tools_menu", "fb_service_menu", "stock_categories", "refer", "search_number"}
_MD_CARD_ONLY_KEYS = {"profile", "balance", "number_card", "admin_panel"}
_MD_BODY_CARD_MAP = {"select_country": "country_menu", "fb_service_menu": "fb_tools"}
_MD_PLACEHOLDERS = {
    "traffic": "<code>{window}</code>, <code>{total}</code>, <code>{traffic_content}</code>, <code>{brand_name}</code>",
    "stock_list": "<code>{stock_title}</code>, <code>{total_entries}</code>, <code>{page}</code>, <code>{stock_entries}</code>",
    "referral_dashboard": "<code>{ref_link}</code>, <code>{total_ref}</code>, <code>{ref_reward}</code>",
    "withdrawal": "<code>{total_otp}</code>, <code>{total_ref}</code>, <code>{bal}</code>, <code>{min_w}</code>",
    "access_type": "<code>{access_type}</code>, <code>{stock}</code>, <code>{reward}</code>, <code>{status}</code>",
    "service_menu": "<code>{access_title}</code>, <code>{service_count}</code>",
    "country_menu": "<code>{service1}</code>, <code>{country_count}</code>",
    "fb_tools": "<code>{mode}</code>, <code>{free_limit}</code>, <code>{status}</code>",
    "temp_mail_waiting": "<code>{email}</code>, <code>{status}</code>",
    "temp_mail_otp": "<code>{email}</code>, <code>{status}</code>, <code>{sender}</code>, <code>{subject}</code>, <code>{body_line}</code>",
    "temp_mail_received": "<code>{email}</code>, <code>{sender}</code>, <code>{subject}</code>, <code>{body_line}</code>",
    "temp_mail_inbox": "<code>{email}</code>, <code>{inbox_entries}</code>",
}


def _md_body_card_key(menu_key):
    return _MD_BODY_CARD_MAP.get(menu_key, menu_key)


def _md_uses_card(menu_key):
    card_key = _md_body_card_key(menu_key)
    return card_key in DEFAULT_CARD_TEMPLATES or card_key in _TEMP_CARD_KEYS


def _md_placeholder_help(menu_key):
    card_key = _md_body_card_key(menu_key)
    return _MD_PLACEHOLDERS.get(card_key) or _MD_PLACEHOLDERS.get(menu_key, "")


def _md_buttons_store(menu_key):
    """Buttons for a Menu Design block live in the same store its renderer reads."""
    if menu_key not in _MD_CM_BUTTON_KEYS and _md_uses_card(menu_key):
        return _card_template(_md_body_card_key(menu_key)).setdefault("buttons", [])
    c_msg = bot_settings.setdefault("custom_messages", {}).setdefault(menu_key, {})
    if not isinstance(c_msg, dict):
        c_msg = {}
        bot_settings["custom_messages"][menu_key] = c_msg
    if not isinstance(c_msg.get("buttons"), list):
        c_msg["buttons"] = []
    return c_msg["buttons"]


def menu_buttons_list_keyboard(menu_key):
    kb = []
    btns = _md_buttons_store(menu_key)
    for idx, btn in enumerate(btns):
        has_icon = bool(btn.get("icon_custom_emoji_id"))
        icon_action = "Change Icon" if has_icon else "Set Icon"
        kb.append([
            {"text": f"Del: {btn.get('text', 'Button')}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"md_delbtn_{menu_key}_{idx}", "style": "danger"},
            {"text": icon_action, "icon_custom_emoji_id": "5352552689983067014", "callback_data": f"md_seticon_{menu_key}_{idx}", "style": "primary"},
        ])
    kb.append([{"text": "Add Inline Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"md_addbtn_{menu_key}", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{menu_key}", "style": "primary"}])
    return {"inline_keyboard": kb}

def body_emoji_editor_keyboard():
    rows = []
    for index, (char, emoji_id) in enumerate(sorted((bot_settings.get("body_emojis") or {}).items(), key=lambda item: item[0])):
        label = str(char).replace("\n", " ")[:8]
        rows.append([{"text": f"{label}  {str(emoji_id)[:18]}", "icon_custom_emoji_id": str(emoji_id), "callback_data": f"bme_set_{index}", "style": "primary"}])
    rows.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}])
    return {"inline_keyboard": rows}


def user_menu_editor_keyboard():
    rows = []
    icon_keys = {"get_number": "phone", "refer": "refer", "stock": "stock", "traffic": "traffic", "search_number": "search", "temp_mail": "mail", "profile": "profile", "balance": "balance", "support": "support", "admin_panel": "admin", "tm_generate": "mail", "tm_refresh": "refresh", "tm_cancel": "no", "tm_copy_email": "copy", "tm_copy_otp": "copy", "tm_open_browser": "link"}
    for key in USER_MENU_LABEL_DEFAULTS:
        icon_key = icon_keys.get(key, "ok")
        rows.append([{"text": f"Text: {menu_label(key)}", "icon_custom_emoji_id": _user_menu_icon_id(icon_key), "callback_data": f"ume_text_{key}", "style": "primary"}])
        rows.append([{"text": f"Emoji: {key}", "icon_custom_emoji_id": _user_menu_icon_id(icon_key), "callback_data": f"ume_icon_{key}", "style": "success"}])
    rows.append([{"text": "Edit User Menu Body Emojis", "icon_custom_emoji_id": _user_menu_icon_id("gear"), "callback_data": "body_emoji_editor", "style": "primary"}])
    rows.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}])
    return {"inline_keyboard": rows}


def _body_emoji_by_index(index):
    rows = sorted((bot_settings.get("body_emojis") or {}).items(), key=lambda item: item[0])
    try:
        return rows[int(index)]
    except (IndexError, TypeError, ValueError):
        return None


def emoji_settings_keyboard():
    return {"inline_keyboard": [
        [{"text": "Upload Flags (TXT)", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "up_flags_txt", "style": "primary"},
         {"text": "Download Flags", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_flags_txt", "style": "success"}],
        [{"text": "Upload Services (TXT)", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "up_apps_txt", "style": "primary"},
         {"text": "Download Services", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_apps_txt", "style": "success"}],
        [{"text": "Delete All Flags", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "del_all_flags", "style": "danger"},
         {"text": "Add Single Emoji", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_single_emoji", "style": "success"}],
        [{"text": "Preview Emoji IDs", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "preview_emoji_ids", "style": "primary"}],
        [{"text": "Extract Emoji IDs", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "extract_emoji_ids", "style": "primary"},
         {"text": "Extract Pack IDs", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "extract_pack_emoji_ids", "style": "primary"}],
        [{"text": "Clear Specific Emoji ID", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "clear_emoji_id", "style": "danger"}],
        [{"text": "Button Emoji Editor", "icon_custom_emoji_id": "5420155432272438703", "callback_data": "button_emoji_editor", "style": "primary"}],
        [{"text": "Back",  "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
    ]}

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

def otp_groups_list_keyboard():
    kb = [[{"text": "Edit OTP Button Link", "icon_custom_emoji_id": "5420517437885943844", "callback_data": "edit_otp_link", "style": "primary"}]]
    for idx, fg in enumerate(bot_settings["fw_groups"]):
        kb.append([{"text": f"Group: {fg['chat_id']}", "icon_custom_emoji_id": "5193063022226086560", "callback_data": f"manage_fw_{idx}", "style": "primary"}])
    kb.append([{"text": "Add Forward Group", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_fw", "style": "success"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}])
    return {"inline_keyboard": kb}

def stex_control_keyboard():
    return {"inline_keyboard": [
        [{"text": "Add StexSMS Key", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_stex_key", "style": "success"},
         {"text": "View/Del Keys", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "view_stex_keys", "style": "danger"}],
        [{"text": "Manage StexSMS Services", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "manage_stex_srv", "style": "success"}],
        [{"text": "Search Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "stex_search_country", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def voltx_control_keyboard():
    return {"inline_keyboard": [
        [{"text": "Add Voltx Key", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_voltx_key", "style": "success"},
         {"text": "View/Del Keys", "icon_custom_emoji_id": "5422557736330106570", "callback_data": "view_voltx_keys", "style": "danger"}],
        [{"text": "Manage Voltx Services", "icon_custom_emoji_id": "5192739271886282680", "callback_data": "manage_voltx_srv", "style": "success"}],
        [{"text": "Search Country", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "voltx_search_country", "style": "primary"}],
        [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "primary"}]
    ]}

def specific_fw_group_keyboard(idx):
    group = bot_settings["fw_groups"][idx]
    kb = []
    for b_idx, btn in enumerate(group.get("buttons", [])):
        kb.append([{"text": f"Del: {btn['text']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_fwbtn_{idx}_{b_idx}", "style": "danger"}])

    kb.append([{"text": "Add Inline Button", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"add_fwbtn_{idx}", "style": "success"}])
    kb.append([{"text": "Delete Entire Group", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"del_fw_{idx}", "style": "danger"}])
    kb.append([{"text": "Back to Groups", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "primary"}])
    return {"inline_keyboard": kb}

def dxa_control_keyboard():
    w_status = "ON" if bot_settings["withdraw_on"] else "OFF"
    sup_status = "ON" if bot_settings.get("support_link") else "OFF"
    grp_status = "ON" if bot_settings.get("w_group") else "OFF"
    return {"inline_keyboard": [
        [{"text": f"DYNAMIC NAME: {get_brand_name_plain()}", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "dxa_brand", "style": "success"}],
        [{"text": f"WITHDRAW: {w_status}", "icon_custom_emoji_id": "5348469219761626211", "callback_data": "dxa_toggle_w", "style": "primary"}],
        [{"text": f"MIN WITHDRAW: {bot_settings['min_withdraw']}", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "dxa_min_w", "style": "success"},
         {"text": f"OTP REWARD: {bot_settings['otp_reward']}", "icon_custom_emoji_id": "5190576863226933563", "callback_data": "dxa_otp_r", "style": "primary"}],
        [{"text": f"REFER REWARD: {bot_settings['refer_reward']}", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "dxa_ref_r", "style": "success"},
         {"text": f"COOLDOWN: {bot_settings['cooldown']}s", "icon_custom_emoji_id": "5337172996211648018", "callback_data": "dxa_cool", "style": "primary"}],
        [{"text": f"NUM/REQ: {bot_settings['num_req']}", "icon_custom_emoji_id": "5337132498965010628", "callback_data": "dxa_num_req", "style": "success"},
         {"text": f"NUM/SHARE: {bot_settings['num_share']}", "icon_custom_emoji_id": "5352862640592949843", "callback_data": "dxa_num_share", "style": "primary"}],
        [{"text": f"TRAFFIC GROUP: {_format_duration(_traffic_forward_interval_seconds())}", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "traffic_interval_menu", "style": "success"}],
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

def typed_panels_list_keyboard(p_type):
    kb = []
    for idx, p in enumerate(bot_settings["panels"]):
        if p.get("type", "API Panel") != p_type: continue
        action_text = f"Turn OFF {p['name']}" if p['status'] == 'ON' else f"Turn ON {p['name']}"
        action_icon = "5318840353510408444" if p['status'] == 'ON' else "5192812028632274956"
        icon_id = "5420155432272438703"
        kb.append([
            {"text": action_text, "icon_custom_emoji_id": action_icon, "callback_data": f"tog_pnl_{idx}", "style": "danger" if p['status'] == 'ON' else "success"},
            {"text": f"{p['name']}", "icon_custom_emoji_id": icon_id, "callback_data": f"conf_pnl_{idx}", "style": "primary"}
        ])
    add_cb = "add_api_panel" if p_type == "API Panel" else "add_cpt_panel"
    kb.append([{"text": "Add New Provider", "icon_custom_emoji_id": "5420323438508155202", "callback_data": add_cb, "style": "success"}])
    kb.append([{"text": "Delete Provider", "icon_custom_emoji_id": "5336944168944047463", "callback_data": f"list_del_{'api' if p_type=='API Panel' else 'cpt'}", "style": "danger"}])
    kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_panels", "style": "primary"}])
    return {"inline_keyboard": kb}

def panel_config_keyboard(idx):
    p = bot_settings["panels"][idx]

    kb = []
    action_text = "Turn OFF" if p['status'] == 'ON' else "Turn ON"
    action_icon = "5318840353510408444" if p['status'] == 'ON' else "5192812028632274956"
    kb.append([{"text": action_text, "icon_custom_emoji_id": action_icon, "callback_data": f"tog_pnl_{idx}", "style": "danger" if p['status'] == 'ON' else "success"}])

    if p["type"] != "Auto Captcha Panel":
        rec_count_text = "All (Unlimited)" if p.get('records', 0) == 0 else str(p.get('records'))
        kb.append([{"text": "Set API URL", "icon_custom_emoji_id": "5420517437885943844", "callback_data": f"set_p_api_{idx}", "style": "primary"}])
        kb.append([{"text": "Set Token", "icon_custom_emoji_id": "5353022963132174959", "callback_data": f"set_p_tok_{idx}", "style": "primary"}])
        kb.append([{"text": "🌐 Full API (URL+Token)", "icon_custom_emoji_id": "5420517437885943844", "callback_data": f"set_p_fapi_{idx}", "style": "primary"}])
        kb.append([{"text": f"Set Records Count: {rec_count_text}", "icon_custom_emoji_id": "5192739271886282680", "callback_data": f"set_p_rec_{idx}", "style": "primary"}])

    kb.append([{"text": "Test Connection", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"test_p_conn_{idx}", "style": "success"}])

    back_data = "manage_api_panels" if p.get("type", "API Panel") == "API Panel" else "manage_cpt_panels"
    kb.append([{"text": "Back to Providers", "icon_custom_emoji_id": "5267490665117275176", "callback_data": back_data, "style": "danger"}])
    return {"inline_keyboard": kb}

#==============================================================================
#  [33]  LIVE TRAFFIC UI & FORWARDER
#==============================================================================
def _traffic_country_name(iso):
    iso = str(iso or "XX").upper()
    for _, fdata in bot_settings.get("premium_flags", {}).items():
        if str(fdata.get("iso", "")).upper() == iso:
            return fdata.get("name", iso)
    return iso


def _traffic_otp_count_for_number(number, window=TRAFFIC_WINDOW_SECONDS):
    clean = re.sub(r"\D", "", str(number or ""))
    if not clean:
        return 0
    now = time.time()
    return sum(
        1 for item in recent_traffic
        if now - item.get("time", 0) <= window
        and re.sub(r"\D", "", str(item.get("number", ""))) == clean
    )


def _traffic_forward_interval_seconds():
    try:
        value = int(float(bot_settings.get("traffic_forward_interval", TRAFFIC_WINDOW_SECONDS)))
    except Exception:
        value = TRAFFIC_WINDOW_SECONDS
    return max(60, min(172800, value))


def _format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hour" + ("s" if seconds // 3600 != 1 else "")
    if seconds % 60 == 0:
        return f"{seconds // 60} minute" + ("s" if seconds // 60 != 1 else "")
    return f"{seconds} seconds"


def traffic_interval_keyboard():
    presets = [
        (60, "1 Minute"), (120, "2 Minutes"), (180, "3 Minutes"),
        (300, "5 Minutes"), (600, "10 Minutes"), (1800, "30 Minutes"),
        (3600, "1 Hour"), (7200, "2 Hours"),
    ]
    rows = []
    for index in range(0, len(presets), 2):
        rows.append([
            {"text": presets[index][1], "icon_custom_emoji_id": "5465368548702446780", "callback_data": f"traffic_interval:{presets[index][0]}", "style": "primary"},
            {"text": presets[index + 1][1], "icon_custom_emoji_id": "5465368548702446780", "callback_data": f"traffic_interval:{presets[index + 1][0]}", "style": "primary"},
        ])
    rows.append([{"text": "Custom Seconds", "icon_custom_emoji_id": "5352877703043258544", "callback_data": "traffic_interval_custom", "style": "success"}])
    rows.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "dxa_control", "style": "danger"}])
    return {"inline_keyboard": rows}


def _number_has_get_number_owner(number):
    """Return True only for numbers allocated through the legacy GET NUMBER flow."""
    clean = re.sub(r"\D", "", str(number or ""))
    if not clean:
        return False
    for session in user_active_sessions.values():
        for assigned in session.get("nums", []):
            assigned_clean = re.sub(r"\D", "", str(assigned or ""))
            if assigned_clean == clean or (len(assigned_clean) >= 8 and assigned_clean.endswith(clean[-8:])) or (len(clean) >= 8 and clean.endswith(assigned_clean[-8:])):
                return True
    for assigned in list(stex_assigned_numbers) + list(voltx_assigned_numbers):
        assigned_clean = re.sub(r"\D", "", str(assigned or ""))
        if assigned_clean == clean or (len(assigned_clean) >= 8 and assigned_clean.endswith(clean[-8:])) or (len(clean) >= 8 and clean.endswith(assigned_clean[-8:])):
            return True
    return bool(_find_fb_tool_owners(clean))


def _traffic_entry_box(service_html, traffic_text):
    """Render one compact traffic entry without a bulky frame."""
    return (
        f"📱 <b>SERVICE:</b> {service_html}\n"
        f"📈 <b>TRAFFIC:</b> <b>{html.escape(str(traffic_text))}</b>"
    )


def build_traffic_ui():
    """Show a screenshot-style five-minute traffic card."""
    global recent_traffic
    now = time.time()
    recent_traffic = [
        item for item in recent_traffic
        if now - float(item.get("time", 0) or 0) <= TRAFFIC_WINDOW_SECONDS
    ]

    # The screenshot groups traffic by country and service, not by provider
    # source. This keeps every row consistent for GET NUMBER and API Number.
    grouped = {}
    for item in recent_traffic:
        iso = str(item.get("iso") or "XX").upper()
        service = str(item.get("service") or "Unknown").strip() or "Unknown"
        key = (iso, service.casefold())
        entry = grouped.setdefault(key, {"iso": iso, "service": service, "count": 0})
        entry["count"] += 1

    all_total = sum(entry["count"] for entry in grouped.values())
    ranked = sorted(grouped.values(), key=lambda item: (-item["count"], item["iso"], item["service"].upper()))[:5]

    custom = bot_settings.get("custom_messages", {}).get("traffic", {})
    kb = []
    if ranked:
        for entry in ranked:
            callback = "traffic_get:{}:{}".format(quote(entry["service"], safe=""), entry["iso"])
            kb.append([ui_button("GET NUMBER", "get", callback, style="primary")])
    kb.append([ui_button("REFRESH", "refresh", "refresh_traffic", style="primary")])
    kb.append([ui_button("MAIN MENU", "back", "traffic_main_menu", style="danger")])
    for button in safe_custom_buttons(_card_template("traffic").get("buttons") or custom.get("buttons", [])):
        kb.append([dict(button)])

    if not ranked:
        # No empty boxed/table card: keep this to one short line as requested.
        return (
            render_body_text("📈 <b>NO OTP TRAFFIC IN LAST 5 MINUTES.</b>"),
            {"inline_keyboard": kb},
        )

    entry_lines = []
    for index, entry in enumerate(ranked, 1):
        app_name, app_html = get_service_info_html(entry["service"])
        country = _traffic_country_name(entry["iso"]).upper()
        flag_html = get_flag_info_html(entry["iso"])
        percentage = (entry["count"] / all_total * 100.0) if all_total else 0.0
        entry_lines.append(f"<b>{index}. {flag_html} {html.escape(country)}</b>")
        entry_lines.append(_traffic_entry_box(
            f"{app_html} {html.escape(str(app_name).upper())}",
            f"{percentage:.1f}% · 5 MIN",
        ))
        if index < len(ranked):
            entry_lines.append("")
    entries_text = "\n".join(entry_lines)
    traffic_body = str(_card_template("traffic").get("body_text") or "").strip()
    if traffic_body:
        # Menu Design body wins; {traffic_content} injects the live entries.
        body = _card_token(
            traffic_body,
            replacements={"window": "5 MIN", "total": str(all_total)},
            trusted_html={"traffic_content": entries_text, "brand_name": get_brand_name_html()},
        )
        return render_body_text(body), {"inline_keyboard": kb}
    lines = []
    brand = brand_header().strip()
    if brand:
        lines.append(brand)
    lines.append("📈 <b>LIVE PERFORMANCE • LAST 5 MINUTES</b>")
    lines.append("")
    lines.append(entries_text)
    return render_body_text("\n".join(lines)), {"inline_keyboard": kb}


def traffic_group_forwarder():
    """Forward a rolling five-minute live-traffic card to configured OTP groups."""
    last_forward_at = 0.0
    while True:
        try:
            interval = _traffic_forward_interval_seconds()
            time.sleep(5)
            now = time.time()
            if now - last_forward_at < interval:
                continue
            groups = [group for group in bot_settings.get("fw_groups", []) if group.get("chat_id")]
            if not groups:
                continue
            recent = [
                item for item in recent_traffic
                if now - float(item.get("time", 0) or 0) <= TRAFFIC_WINDOW_SECONDS
            ]
            if not recent:
                last_forward_at = now
                continue
            traffic_text, _ = build_traffic_ui()
            for group in groups:
                try:
                    send_message(group["chat_id"], traffic_text)
                except Exception as exc:
                    print(f"[Traffic Group] forward error: {type(exc).__name__}")
            last_forward_at = now
        except Exception as exc:
            print(f"[Traffic Group] worker error: {type(exc).__name__}")
            time.sleep(5)

#==============================================================================
#  [34]  UPLOAD EMOJI FLOW & BATCH FINALIZE
#==============================================================================
def _service_emoji_record(service):
    raw = str(service or "").strip()
    upper = raw.upper()
    for key, data in bot_settings.get("premium_apps", {}).items():
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or key).strip()
        if upper == str(key).upper() or upper == name.upper() or upper in name.upper() or name.upper() in upper:
            eid = normalize_local_digits(str(data.get("id") or "")).strip()
            return data if eid.isdigit() else None
    return None


def _country_emoji_record(country):
    raw = str(country or "").strip()
    upper = raw.upper()
    digits = re.sub(r"\D", "", raw)
    for key, data in bot_settings.get("premium_flags", {}).items():
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or "").strip()
        iso = str(data.get("iso") or "").upper()
        code = str(data.get("code") or key).strip()
        matches = upper == name.upper() or upper == iso or (digits and digits.startswith(code))
        if matches:
            eid = normalize_local_digits(str(data.get("id") or "")).strip()
            return data if eid.isdigit() else None
    return None


def _missing_upload_emoji_fields(service, country):
    missing = []
    if not _service_emoji_record(service):
        missing.append("service")
    if not _country_emoji_record(country):
        missing.append("country")
    return missing


def _save_uploaded_emoji_id(field, service, country, emoji_id):
    eid = normalize_local_digits(str(emoji_id or "")).strip()
    if field == "service":
        key = str(service or "UNKNOWN").upper()
        current = bot_settings.setdefault("premium_apps", {}).get(key) or {}
        bot_settings["premium_apps"][key] = {
            "char": current.get("char") or "📱",
            "id": eid,
            "name": current.get("name") or str(service or key),
        }
        return
    raw = str(country or "UNKNOWN").strip()
    digits = re.sub(r"\D", "", raw)
    key = digits or raw.upper()
    current = bot_settings.setdefault("premium_flags", {}).get(key) or {}
    bot_settings["premium_flags"][key] = {
        "char": current.get("char") or "🏳️",
        "iso": current.get("iso") or (raw[:2].upper() if raw else "XX"),
        "name": current.get("name") or raw,
        "id": eid,
    }


def _emoji_upload_prompt(chat_id):
    data = temp_data.get(chat_id, {})
    missing = data.get("pending_emoji_fields") or []
    field = missing[0] if missing else "service"
    label = "service" if field == "service" else "country flag"
    send_message(
        chat_id,
        render_body_text(
            f"{PEM['warn']} <b>Emoji ID required for {label}</b>\n\n"
            f"Service: <b>{html.escape(str(data.get('service', '')))}</b>\n"
            f"Country: <b>{html.escape(str(data.get('country', '')))}</b>\n\n"
            "Automatic emoji lookup could not find a valid Premium Emoji ID. "
            f"Send the numeric custom Emoji ID for the {label}."
        ),
        reply_markup=get_cancel_kb(),
    )


def _finish_uploaded_number_batch(chat_id, otp_reward):
    global total_uploaded_stats
    data = temp_data.get(chat_id, {})
    country = data["country"]
    service = data["service"]
    raw_numbers = data["numbers"]
    clean_nums = []
    for num in raw_numbers:
        num = str(num).strip()
        if num:
            if not num.startswith('+'):
                num = '+' + num
            clean_nums.append(num)

    batch_id = str(uuid.uuid4())[:8]
    number_batches[batch_id] = {
        "filename": data["filename"],
        "service": service,
        "country": country,
        "category": data.get("category", "FREE"),
        "otp_reward": otp_reward,
        "numbers": [{"num": n, "shares": 0, "used_by": []} for n in clean_nums],
    }
    total_uploaded_stats += len(clean_nums)
    save_db()

    category_label = data.get("category", "FREE")
    broadcast_txt = _number_broadcast_text(service, country, category_label, len(clean_nums), otp_reward, batch_id)
    broadcast_markup = {"inline_keyboard": [[
        {"text": "Get Number", "icon_custom_emoji_id": "5337132498965010628", "callback_data": f"batch_get:{batch_id}", "style": "success"},
    ]]}
    for button in safe_custom_buttons(_card_template("number_broadcast").get("buttons", [])):
        broadcast_markup["inline_keyboard"].append([dict(button)])

    send_message(
        chat_id,
        render_body_text(
            f"{PEM['ok']} Numbers added to <b>{category_label}</b> stock. "
            f"Per OTP reward: <b>{otp_reward} USD</b>\nStarting broadcast..."
        ),
    )

    def simple_broadcast(txt, markup):
        b_session = requests.Session()
        url = f"{BASE_URL}/sendMessage"
        for u_id in list(all_known_users):
            try:
                b_session.post(
                    url,
                    json={"chat_id": u_id, "text": txt, "parse_mode": "HTML", "disable_web_page_preview": True, "reply_markup": markup},
                    timeout=5,
                )
            except Exception:
                pass
            time.sleep(0.035)

    threading.Thread(target=simple_broadcast, args=(broadcast_txt, broadcast_markup), daemon=True).start()
    user_states.pop(chat_id, None)
    temp_data.pop(chat_id, None)
    return True


# ==========================================
# Message Handler
# ==========================================
#==============================================================================
#  [35]  CORE HANDLER — handle_message (V1, wrapped by patch layer)
#==============================================================================
def handle_message(msg):
    global total_uploaded_stats
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
            if inviter != chat_id and db:
                try:
                    doc = db.collection('users').document(str(chat_id)).get()
                    if not doc.exists:
                        get_user(chat_id)
                        if db:
                            db.collection('users').document(str(chat_id)).update({"referred_by": inviter, "ref_paid": False})
                except Exception as e:
                    print(f"❌ Referral pre-save skipped: {type(e).__name__}: {e}")
                    disable_firestore("Referral pre-save failed.")

    if not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return

    MAIN_MENU_CMDS = ["Get Number", "GET NUMBER", "Refer & Earn", "Stock", "Temp Mail", "Profile", "Balance", "Support", "SUPPORT", "Search Number", "TRAFFIC", "Refer", "WITHDRAWAL", "Admin Panel", "2FA ONLINE"]

    is_main_cmd = False
    if text in MAIN_MENU_CMDS or text.startswith("/start"):
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        is_main_cmd = True

    if chat_id in user_states and not is_main_cmd:
        state = user_states[chat_id]

        # 🌟 Auto Captcha Panel Setup Flow
        if state == "wait_for_clear_emoji_id" and text:
            emoji_id = normalize_local_digits(str(text).strip()).strip()
            if not emoji_id.isdigit():
                send_message(chat_id, render_body_text(f"{PEM['no']} Send a numeric Premium Emoji ID."), reply_markup=get_cancel_kb())
                return
            removed = []
            for store_name in ("premium_apps", "premium_flags"):
                store = bot_settings.get(store_name, {})
                for key, item in list(store.items()):
                    if isinstance(item, dict) and normalize_local_digits(str(item.get("id") or "")).strip() == emoji_id:
                        item.pop("id", None)
                        removed.append(f"{store_name}:{key}")
            if removed:
                save_db()
                msg_id = temp_data.get(chat_id, {}).get("msg_id")
                user_states.pop(chat_id, None)
                temp_data.pop(chat_id, None)
                text_out = f"{PEM['ok']} Cleared Emoji ID <code>{html.escape(emoji_id)}</code> from <b>{len(removed)}</b> record(s)."
                if msg_id:
                    edit_message(chat_id, msg_id, render_body_text(text_out), reply_markup=emoji_settings_keyboard())
                else:
                    send_message(chat_id, render_body_text(text_out), reply_markup=emoji_settings_keyboard())
            else:
                send_message(chat_id, render_body_text(f"{PEM['no']} Emoji ID <code>{html.escape(emoji_id)}</code> was not found."), reply_markup=get_cancel_kb())
            return

        if state == "wait_for_cpanel_url" and text:
            temp_data[chat_id]["p_data"]["login_url"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_user"
            send_message(chat_id, render_body_text("2️⃣ <b>Username</b>\nSend the panel username:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_user" and text:
            temp_data[chat_id]["p_data"]["username"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_pass"
            send_message(chat_id, render_body_text("3️⃣ <b>Password</b>\nSend the panel password:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_pass" and text:
            temp_data[chat_id]["p_data"]["password"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_msg_link"
            send_message(chat_id, render_body_text("4️⃣ <b>Message Link</b>\nSend the URL where SMS/OTP data is available:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_msg_link" and text:
            temp_data[chat_id]["p_data"]["msg_link"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_num_col_name"
            send_message(chat_id, render_body_text("5️⃣ <b>Number Column Name</b>\nSend the number column name, e.g. number or phone:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_num_col_name" and text:
            temp_data[chat_id]["p_data"]["num_col_name"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_num_col_idx"
            send_message(chat_id, render_body_text("6️⃣ <b>Number Column Serial</b>\nSend the number column index, e.g. 3 or 5:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_num_col_idx" and text:
            if text.isdigit():
                temp_data[chat_id]["p_data"]["num_col_idx"] = int(text)
                user_states[chat_id] = "wait_for_cpanel_msg_col_name"
                send_message(chat_id, render_body_text("7️⃣ <b>Message Column Name</b>\nSend the message/OTP column name, e.g. message or sms:"), reply_markup=get_cancel_kb())
            else:
                 send_message(chat_id, render_body_text("❌ Please enter a valid number serial!"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_msg_col_name" and text:
            temp_data[chat_id]["p_data"]["msg_col_name"] = text.strip()
            user_states[chat_id] = "wait_for_cpanel_msg_col_idx"
            send_message(chat_id, render_body_text("8️⃣ <b>Message Column Serial</b>\nSend the message column index, e.g. 5 or 7:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_cpanel_msg_col_idx" and text:
            if text.isdigit():
                temp_data[chat_id]["p_data"]["msg_col_idx"] = int(text)
                temp_data[chat_id]["p_data"]["login_status"] = "⏳ Pending Auto-Login..."

                # Save the panel configuration
                bot_settings["panels"].append(temp_data[chat_id]["p_data"])
                save_db()

                send_message(chat_id, render_body_text(f"{PEM['ok']} <b>Auto Captcha Panel Added Successfully!</b>\nThe bot will now solve captcha and log in automatically in the background."), reply_markup=main_menu(chat_id))

                msg_id = temp_data[chat_id]["msg_id"]
                handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_cpt_panels", "id": "internal"})

                del user_states[chat_id]
                del temp_data[chat_id]
            else:
                 send_message(chat_id, render_body_text("❌ Please enter a valid number serial!"), reply_markup=get_cancel_kb())
            return

        # --- User Management Flows ---
        elif state == "wait_for_um_bal_uid" and text:
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
                send_message(chat_id, render_body_text(f"✅ User found!\n💰 Current Balance: {current_bal} $\n\n📝 Send the amount to ADD (e.g. 50) or REMOVE (e.g. -50):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_um_bal_amt" and text:
            try:
                amt = float(text.strip())
                target_uid = temp_data[chat_id]["target_uid"]
                update_balance(target_uid, amt)
                send_message(chat_id, render_body_text(f"{PEM['ok']} Balance updated successfully for {target_uid}!"), reply_markup=main_menu(chat_id))
                send_message(target_uid, render_body_text(f"🔔 Your balance has been adjusted by <b>{amt} $</b> by an Admin."))
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
                prof_text = _menu_grid(PEM['user'] + " <b>USER PROFILE</b>", [
                    ("ID", str(target_uid)),
                    ("BALANCE", "{} $".format(data.get('balance', 0.0))),
                    ("TOTAL REFERS", str(data.get('total_refers', 0))),
                    ("TOTAL OTPS", str(data.get('total_otps', 0))),
                    ("VERIFIED", str(is_verified)),
                    ("BANNED", str(data.get('banned', False))),
                ])
                kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "user_management", "style": "primary"}]]}
                send_message(chat_id, render_body_text(prof_text), reply_markup=kb)
                del user_states[chat_id]
                del temp_data[chat_id]
            return

        # --- Menu Design Flow ---
        elif state == "wait_for_menu_text" and (text or msg.get("photo") or msg.get("document")):
            menu_key = temp_data[chat_id]["menu_key"]
            try:
                is_photo = bool(msg.get("photo"))
                is_document = bool(msg.get("document"))
                if (is_photo or is_document) and menu_key != "start":
                    raise ValueError("Only the /start body currently supports an attached photo.")
                if is_document and not str(msg.get("document", {}).get("mime_type", "")).startswith("image/"):
                    raise ValueError("Send an image file or a Telegram photo.")
                formatted_html_text = compile_admin_premium_input(msg) if (text or msg.get("caption")) else str(bot_settings["custom_messages"].get(menu_key, {}).get("text", ""))
                bot_settings["custom_messages"].setdefault(menu_key, {"text": "", "buttons": []})["text"] = formatted_html_text
                if _md_uses_card(menu_key):
                    # Mirror the saved body into the card template the screen
                    # actually renders, so "Edit Body" affects the live screen.
                    card_tpl = _card_template(_md_body_card_key(menu_key))
                    if str(formatted_html_text or "").strip():
                        card_tpl["body_text"] = formatted_html_text
                    else:
                        card_tpl.pop("body_text", None)
                if menu_key == "start":
                    media = bot_settings["custom_messages"][menu_key].setdefault("media", {})
                    if is_photo:
                        media.clear()
                        media.update({"type": "photo", "file_id": msg["photo"][-1].get("file_id", "")})
                    elif is_document:
                        media.clear()
                        media.update({"type": "document", "file_id": msg["document"].get("file_id", "")})
                save_db()
                delete_message(chat_id, msg.get("message_id"))
                preview_text = render_body_text(formatted_html_text)
                success_text = f"{PEM['ok']} <b>Message Body Updated successfully!</b>\n\n🎨 <b>Editing: {menu_key.upper()}</b>\n\nPreview of current Text:\n{preview_text}"
                if menu_key == "start" and (is_photo or is_document):
                    media = bot_settings["custom_messages"][menu_key].get("media", {})
                    media_id = media.get("file_id")
                    if media_id:
                        if is_photo:
                            send_photo(chat_id, media_id, caption=preview_text, reply_markup=menu_edit_options_keyboard(menu_key))
                        else:
                            api_call("sendDocument", {"chat_id": chat_id, "document": media_id, "caption": preview_text, "parse_mode": "HTML", "reply_markup": menu_edit_options_keyboard(menu_key)})
                    else:
                        edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(success_text), reply_markup=menu_edit_options_keyboard(menu_key))
                else:
                    edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(success_text), reply_markup=menu_edit_options_keyboard(menu_key))
            except Exception as exc:
                # Do not clear state on invalid IDs; the admin can correct input.
                send_message(chat_id, render_body_text(f"{PEM['no']} <b>Body was not saved.</b>\n<code>{html.escape(str(exc))}</code>\n\nSend corrected text."), reply_markup=get_cancel_kb())
                return
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_menu_btn" and text:
            menu_key = temp_data[chat_id]["menu_key"]
            button_input = text
            parsed = parse_menu_button_input(button_input, msg)
            if not parsed.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} {html.escape(parsed.get('error', 'Invalid button format.'))}"), reply_markup=get_cancel_kb())
                return
            # Dead-button guard: the action must be a valid URL or a callback
            # this bot actually handles, and the label must fit Telegram limits.
            action_check = validate_button_action(parsed.get("url"))
            if not action_check.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Button was not saved. {html.escape(action_check.get('error', ''))}"), reply_markup=get_cancel_kb())
                return
            if not (1 <= len(parsed.get("text", "")) <= 64):
                send_message(chat_id, render_body_text(f"{PEM['no']} Button label must be 1-64 characters (yours: {len(parsed.get('text', ''))})."), reply_markup=get_cancel_kb())
                return
            icon_id = parsed.get("icon_custom_emoji_id")
            angle_ids = angle_custom_emoji_ids_in_text(button_input)
            if icon_id:
                result = validate_premium_ids([icon_id])
                if not result.get("ok"):
                    if angle_ids:
                        parsed["text"] = parsed["text"] + " " + " ".join(f"<{item}>" for item in angle_ids)
                        icon_id = None
                    else:
                        invalid = ", ".join(result.get("invalid") or [icon_id])
                        send_message(chat_id, render_body_text(f"{PEM['no']} Button was not saved. Invalid custom-emoji ID: <code>{invalid}</code>"), reply_markup=get_cancel_kb())
                        return
                else:
                    icon_id = next(iter(result.get("valid", {})), icon_id)
            btn_data = {
                "text": parsed["text"],
                "icon_custom_emoji_id": icon_id or "5420517437885943844",
                "style": "primary",
            }
            if action_check.get("url"):
                btn_data["url"] = action_check["url"]
            else:
                btn_data["callback_data"] = action_check["callback"]
            _md_buttons_store(menu_key).append(btn_data)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"{PEM['gear']} <b>Edit Inline Buttons: {menu_key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(menu_key))
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_menu_icon":
            menu_key = temp_data[chat_id]["menu_key"]
            button_index = temp_data[chat_id]["button_index"]
            direct_ids = [item["id"] for item in custom_emoji_entities(msg)]
            typed_ids = plain_custom_emoji_ids(text) if text else []
            icon_ids = list(dict.fromkeys(typed_ids + direct_ids))
            if len(icon_ids) != 1:
                send_message(chat_id, render_body_text(f"{PEM['no']} Send exactly one numeric ID or one Premium Emoji."), reply_markup=get_cancel_kb())
                return
            result = validate_premium_ids(icon_ids)
            if not result.get("ok"):
                invalid = ", ".join(result.get("invalid") or icon_ids)
                send_message(chat_id, render_body_text(f"{PEM['no']} Icon was not changed. Invalid custom-emoji ID: <code>{invalid}</code>"), reply_markup=get_cancel_kb())
                return
            btns_store = _md_buttons_store(menu_key)
            if button_index >= len(btns_store):
                user_states.pop(chat_id, None)
                temp_data.pop(chat_id, None)
                return
            # Change only the icon field; label, URL and style stay untouched.
            btns_store[button_index]["icon_custom_emoji_id"] = icon_ids[0]
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"{PEM['ok']} Icon updated.\n\n{PEM['gear']} <b>Edit Inline Buttons: {menu_key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(menu_key))
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_test_service" and text:
            service = text.strip()
            if not service:
                send_message(chat_id, render_body_text("Please send a Service name."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["service"] = service
            user_states[chat_id] = "wait_for_test_country"
            send_message(chat_id, render_body_text("📝 Send the Country name (e.g. Haiti):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_test_country" and text:
            country = text.strip()
            if not country:
                send_message(chat_id, render_body_text("Please send a Country name."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["country"] = country
            user_states[chat_id] = "wait_for_test_number"
            send_message(chat_id, render_body_text("📝 Send the Number (e.g. +509563881234):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_test_number" and text:
            number = text.strip()
            if not re.search(r"\d", number):
                send_message(chat_id, render_body_text("Please send a valid Number containing digits."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["number"] = number
            user_states[chat_id] = "wait_for_test_otp"
            send_message(chat_id, render_body_text("📝 Send the OTP (e.g. 961837):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_test_otp" and text:
            otp = text.strip()
            if not otp:
                send_message(chat_id, render_body_text("Please send the OTP."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["otp"] = otp
            user_states[chat_id] = "wait_for_test_lang"
            send_message(chat_id, render_body_text("📝 Send the Language or display country (e.g. FRANCE):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_test_lang" and text:
            lang = text.strip().upper()
            if not lang:
                send_message(chat_id, render_body_text("Please send the Language."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["lang"] = lang
            user_states[chat_id] = "wait_for_test_reward"
            send_message(chat_id, render_body_text("📝 Send the Reward amount (e.g. 0.003 USD):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_test_reward" and text:
            reward_match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", "."))
            if not reward_match:
                send_message(chat_id, render_body_text("Please send a numeric Reward amount."), reply_markup=get_cancel_kb())
                return
            try:
                reward_value = float(reward_match.group(0))
            except (TypeError, ValueError):
                reward_value = -1
            if reward_value < 0:
                send_message(chat_id, render_body_text("Reward cannot be negative."), reply_markup=get_cancel_kb())
                return
            reward = f"{reward_value:g} USD"
            data = temp_data.get(chat_id, {})
            service = data.get("service", "")
            country = data.get("country", "")
            number = data.get("number", "")
            otp = data.get("otp", "")
            lang = data.get("lang", "EN")

            _forward_otp_to_groups(
                service,
                number,
                otp,
                lang,
                "",
                country=country,
                reward=reward,
            )
            _send_otp_inbox(
                chat_id,
                service,
                number,
                otp,
                lang,
                "",
                reward=reward,
                country=country,
                markup=_otp_inbox_markup(number, otp),
            )
            send_message(
                chat_id,
                render_body_text(f"{PEM['ok']} Test card sent to the configured OTP groups and your Private OTP Inbox."),
                reply_markup=main_menu(chat_id),
            )
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_emoji_pack_link" and text:
            pack = get_custom_emoji_pack_from_link(text)
            if not pack.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} {html.escape(str(pack.get('error') or 'Could not read this emoji pack.'))}"), reply_markup=get_cancel_kb())
                return
            if not pack.get("items"):
                send_message(chat_id, render_body_text(f"{PEM['no']} No custom emoji IDs were found in this pack."), reply_markup=get_cancel_kb())
                return
            pack_chunks = custom_emoji_pack_messages(pack)
            for index, chunk in enumerate(pack_chunks):
                markup = emoji_settings_keyboard() if index == len(pack_chunks) - 1 else None
                send_message(chat_id, render_body_text(chunk), reply_markup=markup)
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_body_emoji" and text:
            direct_ids = [item["id"] for item in custom_emoji_entities(msg)]
            typed_ids = angle_custom_emoji_ids_in_text(text) or plain_custom_emoji_ids(text)
            ids = list(dict.fromkeys(direct_ids + typed_ids))
            if len(ids) != 1:
                send_message(chat_id, render_body_text(f"{PEM['no']} Send exactly one Premium Emoji or one numeric ID."), reply_markup=get_cancel_kb())
                return
            validation = validate_premium_ids(ids)
            if not validation.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Invalid custom-emoji ID."), reply_markup=get_cancel_kb())
                return
            body_char = temp_data[chat_id]["body_char"]
            bot_settings.setdefault("body_emojis", {})[body_char] = ids[0]
            sanitize_premium_assets()
            save_db()
            msg_id = temp_data[chat_id]["msg_id"]
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} Body emoji updated for <code>{html.escape(body_char)}</code>."), reply_markup=emoji_settings_keyboard())
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_user_menu_emoji" and text:
            direct_ids = [item["id"] for item in custom_emoji_entities(msg)]
            typed_ids = angle_custom_emoji_ids_in_text(text) or plain_custom_emoji_ids(text)
            ids = list(dict.fromkeys(direct_ids + typed_ids))
            if len(ids) != 1:
                send_message(chat_id, render_body_text(f"{PEM['no']} Send exactly one Premium Emoji or one numeric ID."), reply_markup=get_cancel_kb())
                return
            validation = validate_premium_ids(ids)
            if not validation.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Invalid custom-emoji ID."), reply_markup=get_cancel_kb())
                return
            menu_key = temp_data[chat_id]["menu_key"]
            icon_key = {"get_number": "phone", "refer": "refer", "stock": "stock", "traffic": "traffic", "search_number": "search", "temp_mail": "mail", "profile": "profile", "balance": "balance", "support": "support", "admin_panel": "admin", "tm_generate": "mail", "tm_refresh": "refresh", "tm_cancel": "no", "tm_copy_email": "copy", "tm_copy_otp": "copy", "tm_open_browser": "link"}.get(menu_key, "ok")
            bot_settings.setdefault("user_menu_emojis", {})[icon_key] = ids[0]
            save_db()
            msg_id = temp_data[chat_id]["msg_id"]
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} User Menu emoji updated."), reply_markup=user_menu_editor_keyboard())
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_user_menu_text" and text:
            menu_key = temp_data[chat_id]["menu_key"]
            new_text = text.strip()
            if not new_text or len(new_text) > 64:
                send_message(chat_id, render_body_text(f"{PEM['no']} Button text must be 1 to 64 characters."), reply_markup=get_cancel_kb())
                return
            bot_settings.setdefault("user_menu_labels", {})[menu_key] = new_text
            save_db()
            msg_id = temp_data[chat_id]["msg_id"]
            edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} User Menu button text updated."), reply_markup=user_menu_editor_keyboard())
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_button_emoji_edit" and text:
            ids = angle_custom_emoji_ids_in_text(text)
            button_name = re.sub(r"<[0-9\u09e6-\u09ef\u0660-\u0669\u06f0-\u06f9]+>", "", str(text)).strip()
            button_name = re.sub(r"\s+", " ", button_name)
            if len(ids) != 1 or not button_name:
                send_message(chat_id, render_body_text(f"{PEM['no']} Use exactly: <code>BUTTON NAME &lt;CUSTOM_EMOJI_ID&gt;</code>"), reply_markup=get_cancel_kb())
                return
            emoji_id = ids[0]
            validation = validate_premium_ids([emoji_id])
            if not validation.get("ok"):
                invalid = ", ".join(validation.get("invalid") or [emoji_id])
                send_message(chat_id, render_body_text(f"{PEM['no']} Button icon was not saved. Invalid ID: <code>{html.escape(invalid)}</code>"), reply_markup=get_cancel_kb())
                return
            bot_settings.setdefault("button_emojis", {})[button_name.casefold()] = emoji_id
            save_db()
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            send_message(chat_id, render_body_text(f"{PEM['ok']} Button icon updated.\n\n<b>Button:</b> {html.escape(button_name)}\n<b>Emoji ID:</b> <code>{html.escape(emoji_id)}</code>\n\nThis icon will be applied to every matching button."), reply_markup=emoji_settings_keyboard())
            return

        elif state == "wait_for_emoji_id_extract":
            extracted_items = premium_emoji_items_from_message(msg)
            ids = [item["id"] for item in extracted_items]
            if not ids:
                send_message(chat_id, render_body_text(f"{PEM['no']} No Premium Custom Emoji ID was found. Forward or send a Premium Custom Emoji or custom emoji sticker."), reply_markup=get_cancel_kb())
                return
            if len(ids) > 200:
                send_message(chat_id, render_body_text(f"{PEM['no']} Maximum 200 unique IDs can be extracted at once."), reply_markup=get_cancel_kb())
                return
            result = validate_premium_ids(ids)
            valid_map = result.get("valid", {})
            lines = []
            for item in extracted_items:
                emoji_id = item["id"]
                if emoji_id in valid_map:
                    lines.append(f"<tg-emoji emoji-id=\"{html.escape(emoji_id, quote=True)}\">{html.escape(valid_map[emoji_id])}</tg-emoji> — <code>{html.escape(emoji_id)}</code>")
                else:
                    lines.append(f"{html.escape(item.get('fallback') or '❌')} <code>{html.escape(emoji_id)}</code> — ❌ Invalid custom-emoji ID")
            chunks = []
            current = ""
            for line in lines:
                candidate = line if not current else current + "\n\n" + line
                if current and len(candidate) > 3500:
                    chunks.append(current)
                    current = line
                else:
                    current = candidate
            if current:
                chunks.append(current)
            for index, chunk in enumerate(chunks):
                send_message(chat_id, chunk, reply_markup=emoji_settings_keyboard() if index == len(chunks) - 1 else None)
            # Keep extraction mode active so separately forwarded stickers/emojis
            # can be processed one after another until the admin leaves the menu.
            return

        elif state == "wait_for_emoji_id_preview" and text:
            ids = plain_custom_emoji_ids(text)
            if not ids:
                send_message(chat_id, render_body_text(f"{PEM['no']} Send one or more numeric custom-emoji IDs."), reply_markup=get_cancel_kb())
                return
            if len(ids) > 200:
                send_message(chat_id, render_body_text(f"{PEM['no']} Maximum 200 unique IDs per preview."), reply_markup=get_cancel_kb())
                return
            result = validate_premium_ids(ids)
            preview_chunks = premium_emoji_preview_messages(ids, result.get("valid", {}), result.get("invalid", []), chunk_size=3500)
            for index, chunk in enumerate(preview_chunks):
                markup = emoji_settings_keyboard() if index == len(preview_chunks) - 1 else None
                send_message(chat_id, chunk, reply_markup=markup)
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_emoji_extract":
            extracted_items = premium_emoji_items_from_message(msg)
            custom_emoji_id = extracted_items[0]["id"] if extracted_items else None
            emoji_text = extracted_items[0].get("fallback", "") if extracted_items else ""

            if custom_emoji_id:
                custom_emoji_id = normalize_local_digits(str(custom_emoji_id)).strip()
                validation = validate_premium_ids([custom_emoji_id])
                if not validation.get("ok"):
                    invalid = ", ".join(validation.get("invalid") or [custom_emoji_id])
                    send_message(chat_id, render_body_text(f"{PEM['no']} Invalid custom-emoji ID: <code>{invalid}</code>"), reply_markup=get_cancel_kb())
                    return
                fallback = validation.get("valid", {}).get(str(custom_emoji_id), emoji_text)
                temp_data[chat_id] = {"id": str(custom_emoji_id), "char": fallback}
                user_states[chat_id] = "wait_for_emoji_details"
                send_message(chat_id, render_body_text(f"{PEM['ok']} Emoji ID found: <code>{custom_emoji_id}</code>\n\nSend the type and name to save it.\n\n<b>Format:</b>\n`FLAG | 880 | BD | Bangladesh`\nor\n`APP | WhatsApp`"), reply_markup=get_cancel_kb())
            else:
                send_message(chat_id, render_body_text(f"{PEM['no']} No premium emoji found. Please send a custom emoji."), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_emoji_details" and text:
            parts = [p.strip() for p in text.split("|")]
            mode = parts[0].upper()
            eid = temp_data[chat_id]["id"]
            char = temp_data[chat_id]["char"]

            if mode == "FLAG" and len(parts) == 4:
                code, iso, name = parts[1], parts[2], parts[3]
                bot_settings["premium_flags"][code] = {"char": char, "iso": iso.upper(), "name": name, "id": eid}
                save_db()
                send_message(chat_id, render_body_text(f"{PEM['ok']} Flag emoji saved.\nCode: {code} | Name: {name}"), reply_markup=emoji_settings_keyboard())
            elif mode == "APP" and len(parts) == 2:
                name = parts[1]
                bot_settings["premium_apps"][name.upper()] = {"char": char, "id": eid, "name": name.title()}
                save_db()
                send_message(chat_id, render_body_text(f"{PEM['ok']} App emoji saved.\nName: {name}"), reply_markup=emoji_settings_keyboard())
            else:
                send_message(chat_id, render_body_text(f"{PEM['no']} Invalid format.\n\nCorrect format:\n`FLAG | 880 | BD | Bangladesh`\n`APP | WhatsApp`"))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state in ["wait_for_flag_txt", "wait_for_app_txt"] and "document" in msg:
            doc = msg["document"]
            if not doc["file_name"].endswith(".txt"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Please upload a .txt file only."))
                return
            file_id = doc["file_id"]
            file_info = requests.get(f"{BASE_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            content = requests.get(f"{FILE_URL}{file_path}").text

            mode = "flags" if state == "wait_for_flag_txt" else "apps"
            count = 0
            # Validate every uploaded custom-emoji ID before changing mappings.
            uploaded_ids = []
            for line in content.splitlines():
                json_match = re.search(r'(\{.*\})', line)
                if not json_match:
                    continue
                try:
                    uploaded_record = json.loads(json_match.group(1))
                    uploaded_id = normalize_local_digits(str(uploaded_record.get("id", ""))).strip()
                    if uploaded_id:
                        uploaded_ids.append(uploaded_id)
                except Exception:
                    continue
            if uploaded_ids:
                uploaded_validation = validate_premium_ids(uploaded_ids)
                if not uploaded_validation.get("ok"):
                    invalid = ", ".join(uploaded_validation.get("invalid") or uploaded_ids)
                    send_message(chat_id, render_body_text(f"{PEM['no']} Upload was not saved. Invalid custom-emoji ID: <code>{invalid}</code>"), reply_markup=get_cancel_kb())
                    return

            if mode == "flags":
                for line in content.splitlines():
                    json_match = re.search(r'(\{.*\})', line)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            char = data.get("emoji")
                            eid = normalize_local_digits(str(data.get("id", ""))).strip()

                            prefix_str = line[:json_match.start()].strip()
                            code_match = re.search(r'\((\d+)\)', prefix_str)
                            iso_match = re.search(r'\(([A-Za-z]+)\)', prefix_str)

                            if code_match and iso_match and char and eid:
                                code = code_match.group(1)
                                iso = iso_match.group(1).upper()
                                name = prefix_str.replace(f"({code})", "").replace(f"({iso_match.group(1)})", "").replace(char, "").strip()
                                bot_settings["premium_flags"][code] = {"char": char, "iso": iso, "name": name, "id": eid}
                                count += 1
                        except: pass
            else:
                for line in content.splitlines():
                    json_match = re.search(r'(\{.*\})', line)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            char = data.get("emoji")
                            eid = normalize_local_digits(str(data.get("id", ""))).strip()

                            name_part = line[:json_match.start()].strip()
                            name = name_part.replace(char, '').strip() if char else name_part

                            if char and eid and name:
                                bot_settings["premium_apps"][name.upper()] = {"char": char, "id": eid, "name": name}
                                count += 1
                        except: pass

            save_db()
            send_message(chat_id, render_body_text(f"{PEM['ok']} Successfully loaded {count} Emojis!"), reply_markup=emoji_settings_keyboard())
            del user_states[chat_id]
            return

        elif state == "wait_for_broadcast":
            msg_id = msg["message_id"]
            prepared = build_premium_broadcast_payload(msg, validate_premium_ids)
            if not prepared.get("ok"):
                invalid = prepared.get("invalid") or "unknown"
                detail = prepared.get("error") or "Telegram rejected the custom-emoji ID."
                # Keep the state active so the admin can send a corrected message.
                send_message(
                    chat_id,
                    render_body_text(
                        f"{PEM['no']} <b>Broadcast not started.</b>\n\n"
                        f"Invalid custom-emoji ID: <code>{html.escape(str(invalid))}</code>\n"
                        f"{html.escape(str(detail))}\n\n"
                        "Send a corrected message to try again."
                    ),
                    reply_markup=get_cancel_kb(),
                )
                return
            send_message(chat_id, render_body_text(f"{PEM['ok']} Broadcast started..."))
            threading.Thread(
                target=broadcast_premium_message,
                args=(chat_id, msg_id, msg, prepared),
                daemon=True,
            ).start()
            del user_states[chat_id]
            return

        elif state == "wait_for_txt" and "document" in msg:
            doc = msg["document"]
            if not doc["file_name"].endswith(".txt"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Please upload a .txt file only."))
                return
            file_id = doc["file_id"]
            file_info = requests.get(f"{BASE_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            file_content = requests.get(f"{FILE_URL}{file_path}").text

            temp_data[chat_id] = {"numbers": file_content.splitlines(), "filename": doc["file_name"]}
            user_states[chat_id] = "wait_for_service"
            send_message(chat_id, render_body_text(f"{PEM['ok']} File received.\n\n📌 Enter the service name (e.g., WHATSAPP):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_service" and text:
            temp_data[chat_id]["service"] = text.upper()
            user_states[chat_id] = "wait_for_country"
            send_message(chat_id, render_body_text(f"{PEM['ok']} Service set.\n\n🌍 Enter the country name (e.g., YEMEN):"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_country" and text:
            temp_data[chat_id]["country"] = text.upper()
            user_states[chat_id] = "wait_for_batch_category"
            send_message(
                chat_id,
                render_body_text(
                    f"{PEM['ok']} Country set.\n\n"
                    f"Service: <b>{html.escape(temp_data[chat_id]['service'])}</b>\n"
                    f"Country: <b>{html.escape(temp_data[chat_id]['country'])}</b>\n"
                    f"Numbers: <b>{len(temp_data[chat_id]['numbers'])}</b>\n\n"
                    "Where should these numbers be added?\n"
                    "Type <code>FREE</code> or <code>PREMIUM</code>."
                ),
                reply_markup=get_cancel_kb()
            )
            return

        elif state == "wait_for_batch_category" and text:
            cat = _normalize_stock_category(text)
            if cat == "FB":
                cat = "FREE"
            if cat not in {"FREE", "PREMIUM"}:
                send_message(chat_id, render_body_text(f"{PEM['no']} Invalid category. Type <code>FREE</code> or <code>PREMIUM</code>."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["category"] = cat
            user_states[chat_id] = "wait_for_batch_otp_reward"
            default_reward = bot_settings.get("otp_reward", 0.0)
            send_message(
                chat_id,
                render_body_text(
                    f"{PEM['money']} <b>Set per-OTP reward</b>\n\n"
                    f"Category: <b>{cat}</b>\n"
                    f"Service: <b>{html.escape(temp_data[chat_id]['service'])}</b>\n"
                    f"Country: <b>{html.escape(temp_data[chat_id]['country'])}</b>\n"
                    f"Numbers: <b>{len(temp_data[chat_id]['numbers'])}</b>\n\n"
                    "How much USD should the user receive per OTP?\n"
                    f"Example: <code>0.01</code>\n"
                    f"Default global reward: <code>{default_reward}</code>"
                ),
                reply_markup=get_cancel_kb()
            )
            return

        elif state == "wait_for_batch_emoji_ids" and text:
            data = temp_data.get(chat_id, {})
            emoji_id = normalize_local_digits(str(text).strip()).strip()
            if not emoji_id.isdigit():
                send_message(chat_id, render_body_text(f"{PEM['no']} Send a numeric Premium Emoji ID."), reply_markup=get_cancel_kb())
                return
            validation = validate_premium_ids([emoji_id])
            invalid = validation.get("invalid") if isinstance(validation, dict) else []
            if invalid and emoji_id in invalid:
                send_message(chat_id, render_body_text(f"{PEM['no']} That Premium Emoji ID could not be validated. Send another numeric ID."), reply_markup=get_cancel_kb())
                return

            missing = list(data.get("pending_emoji_fields") or [])
            field = missing.pop(0) if missing else "service"
            _save_uploaded_emoji_id(field, data.get("service"), data.get("country"), emoji_id)
            data["pending_emoji_fields"] = missing
            data.setdefault("pending_emoji_ids", {})[field] = emoji_id
            if missing:
                _emoji_upload_prompt(chat_id)
                return
            save_db()
            send_message(chat_id, render_body_text(f"{PEM['ok']} Service and country emojis saved. Completing the upload."))
            _finish_uploaded_number_batch(chat_id, float(data.get("pending_otp_reward", 0.0) or 0.0))
            return

        elif state == "wait_for_batch_otp_reward" and text:
            try:
                otp_reward = float(text.strip())
                if otp_reward < 0:
                    raise ValueError
            except Exception:
                send_message(chat_id, render_body_text(f"{PEM['no']} Invalid amount. Example: <code>0.01</code>"), reply_markup=get_cancel_kb())
                return

            data = temp_data.get(chat_id, {})
            missing = _missing_upload_emoji_fields(data.get("service"), data.get("country"))
            if missing:
                data["pending_emoji_fields"] = missing
                data["pending_emoji_ids"] = {}
                data["pending_otp_reward"] = otp_reward
                user_states[chat_id] = "wait_for_batch_emoji_ids"
                _emoji_upload_prompt(chat_id)
                return
            _finish_uploaded_number_batch(chat_id, otp_reward)
            return

        elif state == "wait_for_add_stex_key" and text:
            bot_settings["stex_keys"].append(text.strip())
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"✅ StexSMS API Key Added! Total Keys: {len(bot_settings.get('stex_keys', []))}"), reply_markup=stex_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_voltx_key" and text:
            bot_settings["voltx_keys"].append(text.strip())
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"✅ Voltx API Key Added! Total Keys: {len(bot_settings.get('voltx_keys', []))}"), reply_markup=voltx_control_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_sc" and text:
            code = text.strip().replace("+", "")
            if "search_countries" not in bot_settings: bot_settings["search_countries"] = []
            bot_settings["search_countries"].append(code)
            save_db()
            delete_message(chat_id, msg["message_id"])
            kb = []
            for idx, c in enumerate(bot_settings.get("search_countries", [])):
                kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_sc_{idx}", "style": "danger"}])
            kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_search_country", "style": "success"}])
            kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🌍 <b>Allowed Search Countries:</b>\nOnly these country codes will be allowed in Search Number."), reply_markup={"inline_keyboard": kb})
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_vsc" and text:
            code = text.strip().replace("+", "")
            if "voltx_search_countries" not in bot_settings: bot_settings["voltx_search_countries"] = []
            bot_settings["voltx_search_countries"].append(code)
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "voltx_search_country", "id": "internal"})
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_nx_srv_name" and text:
            srv = text.strip().upper()
            if "stex_services" not in bot_settings: bot_settings["stex_services"] = {}
            if srv not in bot_settings["stex_services"]: bot_settings["stex_services"][srv] = {}
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "manage_stex_srv", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_nx_cnt_name" and text:
            cnt = text.strip()
            srv = temp_data[chat_id]["srv"]
            if cnt not in bot_settings["stex_services"][srv]: bot_settings["stex_services"][srv][cnt] = []
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"nx_srv_{srv}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_nx_addr" and text:
            srv, cnt = temp_data[chat_id]["srv"], temp_data[chat_id]["cnt"]
            new_range = text.strip().replace("+", "")

            if new_range not in bot_settings["stex_services"][srv][cnt]:
                bot_settings["stex_services"][srv][cnt].append(new_range)

                if "search_countries" not in bot_settings:
                    bot_settings["search_countries"] = []
                if new_range not in bot_settings["search_countries"]:
                    bot_settings["search_countries"].append(new_range)

                save_db()

            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"nx_cnt_{srv}_{cnt}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_srv_name" and text:
            srv = text.strip().upper()
            if "voltx_services" not in bot_settings: bot_settings["voltx_services"] = {}
            if srv not in bot_settings["voltx_services"]: bot_settings["voltx_services"][srv] = {}
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": "manage_voltx_srv", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_cnt_name" and text:
            cnt = text.strip()
            srv = temp_data[chat_id]["srv"]
            if cnt not in bot_settings["voltx_services"][srv]: bot_settings["voltx_services"][srv][cnt] = []
            save_db()
            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"vx_srv_{srv}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_vx_addr" and text:
            srv, cnt = temp_data[chat_id]["srv"], temp_data[chat_id]["cnt"]
            new_range = text.strip().replace("+", "")

            if new_range not in bot_settings["voltx_services"][srv][cnt]:
                bot_settings["voltx_services"][srv][cnt].append(new_range)

                if "voltx_search_countries" not in bot_settings:
                    bot_settings["voltx_search_countries"] = []
                if new_range not in bot_settings["voltx_search_countries"]:
                    bot_settings["voltx_search_countries"].append(new_range)

                save_db()

            delete_message(chat_id, msg["message_id"])
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": temp_data[chat_id]["msg_id"]}, "data": f"vx_cnt_{srv}_{cnt}", "id": "internal"})
            del user_states[chat_id]
            return

        elif state == "wait_for_add_wm" and text:
            method_name = text.strip()
            if any(bad in method_name.lower() for bad in DISALLOWED_WITHDRAW_KEYWORDS):
                send_message(chat_id, render_body_text(f"{PEM['no']} This withdrawal method is disabled for USD mode. Use Binance Pay, USDT Wallet, PayPal, Wise, Payoneer, or SEPA Bank Transfer."), reply_markup=get_cancel_kb())
                return
            bot_settings["w_methods"].append(method_name)
            sanitize_withdrawal_methods_for_usd()
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your USD withdrawal methods below:"), reply_markup=w_methods_keyboard())
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

        elif state == "wait_for_add_fw_id" and text:
            bot_settings["fw_groups"].append({"chat_id": text.strip(), "buttons": []})
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_add_fw_btn" and text:
            fw_idx = temp_data[chat_id]["fw_idx"]
            button_input = text
            parsed = parse_menu_button_input(button_input, msg)
            if not parsed.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} {html.escape(parsed.get('error', 'Invalid button format.'))}"), reply_markup=get_cancel_kb())
                return
            # Same dead-button guard as Menu Design buttons.
            action_check = validate_button_action(parsed.get("url"))
            if not action_check.get("ok"):
                send_message(chat_id, render_body_text(f"{PEM['no']} Button was not saved. {html.escape(action_check.get('error', ''))}"), reply_markup=get_cancel_kb())
                return
            if not (1 <= len(parsed.get("text", "")) <= 64):
                send_message(chat_id, render_body_text(f"{PEM['no']} Button label must be 1-64 characters (yours: {len(parsed.get('text', ''))})."), reply_markup=get_cancel_kb())
                return
            icon_id = parsed.get("icon_custom_emoji_id")
            angle_ids = angle_custom_emoji_ids_in_text(button_input)
            if icon_id:
                validation = validate_premium_ids([icon_id])
                if not validation.get("ok"):
                    if angle_ids:
                        parsed["text"] = parsed["text"] + " " + " ".join(f"<{item}>" for item in angle_ids)
                        icon_id = None
                    else:
                        invalid = ", ".join(validation.get("invalid") or [icon_id])
                        send_message(chat_id, render_body_text(f"{PEM['no']} Button was not saved. Invalid custom-emoji ID: <code>{html.escape(invalid)}</code>"), reply_markup=get_cancel_kb())
                        return
                else:
                    icon_id = next(iter(validation.get("valid", {})), icon_id)
            fw_btn_data = {
                "text": parsed["text"],
                "icon_custom_emoji_id": icon_id or "5420517437885943844",
                "style": "primary",
            }
            if action_check.get("url"):
                fw_btn_data["url"] = action_check["url"]
            else:
                fw_btn_data["callback_data"] = action_check["callback"]
            bot_settings["fw_groups"][fw_idx].setdefault("buttons", []).append(fw_btn_data)
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(f"🛡 <b>Manage Group:</b> {bot_settings['fw_groups'][fw_idx]['chat_id']}"), reply_markup=specific_fw_group_keyboard(fw_idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_otp_link" and text:
            bot_settings["otp_link"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_panel_name" and text:
            p_name = text.strip()
            t_key = temp_data[chat_id].get("add_type", "api")
            msg_id = temp_data[chat_id]["msg_id"]
            delete_message(chat_id, msg["message_id"])

            if t_key == "logc":
                user_states[chat_id] = "wait_for_cpanel_url"
                temp_data[chat_id] = {"msg_id": msg_id, "p_data": {
                    "name": p_name, "type": "Auto Captcha Panel", "status": "ON", "records": 0, "login_status": "⏳ Pending First Login"
                }}
                edit_message(chat_id, msg_id, render_body_text("1️⃣ <b>Login URL</b>\nSend the panel login URL:"), reply_markup=get_cancel_kb())
                return
            else:
                bot_settings["panels"].append({
                    "name": p_name, "type": "API Panel", "status": "OFF", "api_url": "", "token": "", "records": 0
                })
                save_db()
                handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_api_panels", "id": "internal"})
                if chat_id in user_states: del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
                return

        elif state == "wait_for_p_api" and text:
            idx = temp_data[chat_id]["p_idx"]
            bot_settings["panels"][idx]["api_url"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            p = bot_settings["panels"][idx]
            ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_p_tok" and text:
            idx = temp_data[chat_id]["p_idx"]
            bot_settings["panels"][idx]["token"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            p = bot_settings["panels"][idx]
            ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_p_fapi" and text:
            idx = temp_data[chat_id]["p_idx"]
            bot_settings["panels"][idx]["full_api_url"] = text.strip()
            save_db()
            delete_message(chat_id, msg["message_id"])
            p = bot_settings["panels"][idx]
            ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Full API URL:</b> <code>{p.get('full_api_url', 'None')}</code>"
            edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_for_p_rec" and text:
            if text.isdigit():
                idx = temp_data[chat_id]["p_idx"]
                bot_settings["panels"][idx]["records"] = int(text)
                save_db()
                delete_message(chat_id, msg["message_id"])
                p = bot_settings["panels"][idx]

                ui_text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
                edit_message(chat_id, temp_data[chat_id]["msg_id"], render_body_text(ui_text), reply_markup=panel_config_keyboard(idx))
            else:
                send_message(chat_id, render_body_text("❌ Please enter a valid number! Try again."), reply_markup=get_cancel_kb())
            del user_states[chat_id]
            del temp_data[chat_id]
            return

        elif state == "wait_traffic_interval" and text:
            msg_id = temp_data.get(chat_id, {}).get("msg_id")
            raw_interval = text.strip().lower()
            try:
                if raw_interval.endswith("h"):
                    interval = int(float(raw_interval[:-1]) * 3600)
                elif raw_interval.endswith("m"):
                    interval = int(float(raw_interval[:-1]) * 60)
                else:
                    interval = int(raw_interval)
                if interval < 60 or interval > 172800:
                    raise ValueError
                bot_settings["traffic_forward_interval"] = interval
                save_db()
                user_states.pop(chat_id, None)
                temp_data.pop(chat_id, None)
                if msg_id:
                    edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())
                else:
                    send_message(chat_id, render_body_text("Traffic interval saved."), reply_markup=main_menu(chat_id))
            except (TypeError, ValueError):
                send_message(chat_id, render_body_text("Invalid interval. Use 60, 5m, 1h, or 2h."), reply_markup=get_cancel_kb())
            return

        elif state == "set_dxa":
            msg_id = temp_data[chat_id]["msg_id"]
            key = temp_data[chat_id]["key"]
            try:
                if key == "brand_name":
                    brand_text = compile_dynamic_name_input(msg)
                    bot_settings[key] = brand_text
                    # Keep the original Telegram profile name unchanged. The dynamic name is rendered in bot messages.
                elif key in ["min_withdraw", "otp_reward", "refer_reward"]: bot_settings[key] = float(text)
                elif key in ["cooldown", "num_req", "num_share"]: bot_settings[key] = int(text)
                else: bot_settings[key] = text
                save_db()
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())
            except Exception as exc:
                if key == "brand_name":
                    send_message(chat_id, render_body_text(f"{PEM['no']} <b>Dynamic name was not saved.</b>\n<code>{html.escape(str(exc))}</code>\n\nSend corrected name or Premium Emoji."), reply_markup=get_cancel_kb())
                    return
                delete_message(chat_id, msg["message_id"])
                edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>\n\n❌ Invalid value!"), reply_markup=dxa_control_keyboard())
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            return

        elif state == "wait_for_search" and text:
            query = text.strip().replace("+", "")
            if not query.isdigit() or len(query) < 3 or len(query) > 9:
                send_message(chat_id, render_body_text("❌ Please enter a valid 3 to 9 digit number!"))
                return

            wait_msg = send_message(chat_id, render_body_text("⌛ <i>Processing... Finding Number...</i>"))
            wait_msg_id = wait_msg.get("result", {}).get("message_id")

            # 🌟 .  Local    (   )
            found_indices = []
            for b_id, b_data in number_batches.items():
                for idx, n_obj in enumerate(b_data["numbers"]):
                    if n_obj["num"].replace("+", "").startswith(query) and chat_id not in n_obj.get("used_by", []):
                        found_indices.append((b_id, idx))

            fetched_nums = []
            reward_by_num = {}
            if not found_indices:
                # 🌟 .  Local   ,    Voltx  StexSMS
                stex_allowed = bot_settings.get("search_countries", [])
                voltx_allowed = bot_settings.get("voltx_search_countries", [])

                # :        Block
                is_stex_allowed = any(query.startswith(c) for c in stex_allowed) if stex_allowed else False
                is_voltx_allowed = any(query.startswith(c) for c in voltx_allowed) if voltx_allowed else False

                if not is_stex_allowed and not is_voltx_allowed:
                    if wait_msg_id: delete_message(chat_id, wait_msg_id)
                    send_message(chat_id, render_body_text("❌ This country code is not allowed!"), reply_markup=main_menu(chat_id))
                    del user_states[chat_id]
                    return

                if wait_msg_id: edit_message(chat_id, wait_msg_id, render_body_text("⌛ <i>Processing... Finding Number via API...</i>"))

                is_voltx_used = False
                req_count = bot_settings.get("num_req", 1)

                # 🌟  Voltx
                if is_voltx_allowed:
                    voltx_keys = bot_settings.get("voltx_keys", [])
                    for _ in range(req_count):
                        if len(fetched_nums) >= req_count: break
                        for api_key in voltx_keys:
                            try:
                                headers = {"mauthapi": api_key}
                                res = requests.post(f"{VOLTX_BASE_URL}/getnum", json={"rid": query}, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                                resp_data = res.json()
                                if resp_data.get("meta", {}).get("code") == 200 and resp_data.get("data"):
                                    num_str = str(resp_data["data"].get("no_plus_number", "")).replace("+", "")
                                    if not num_str: num_str = str(resp_data["data"].get("national_number", ""))
                                    fetched_nums.append(num_str)
                                    voltx_assigned_numbers[num_str] = chat_id
                                    is_voltx_used = True
                                    global total_assigned_stats
                                    total_assigned_stats += 1
                                    break #  api_key   ,
                            except: continue

                # 🌟 Voltx        StexSMS
                if len(fetched_nums) < req_count and is_stex_allowed:
                    stex_keys = bot_settings.get("stex_keys", [])

                    for _ in range(req_count - len(fetched_nums)):
                        for api_key in stex_keys:
                            try:
                                headers = {"mauthapi": api_key}
                                res = requests.post(f"{STEX_BASE_URL}/getnum", json={"rid": query}, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                                data = res.json()
                                if data.get("meta", {}).get("code") == 200 and data.get("data"):
                                    num_str = str(data["data"].get("no_plus_number", "")).replace("+", "")
                                    if not num_str: num_str = str(data["data"].get("national_number", ""))
                                    fetched_nums.append(num_str)
                                    stex_assigned_numbers[num_str] = chat_id
                                    total_assigned_stats += 1
                                    break
                            except: continue

                if not fetched_nums:
                    if wait_msg_id: delete_message(chat_id, wait_msg_id)
                    send_message(chat_id, render_body_text("❌ Number out of stock!"), reply_markup=main_menu(chat_id))
                    del user_states[chat_id]
                    return
                save_db()
            else:
                random.shuffle(found_indices)
                for b_id, idx in found_indices:
                    if len(fetched_nums) >= bot_settings.get("num_req", 1): break
                    n_obj = number_batches[b_id]["numbers"][idx]
                    num_str = n_obj["num"]

                    fetched_nums.append(num_str)
                    reward_by_num[num_str] = batch_otp_reward(b_id)

                    n_obj["shares"] += 1
                    n_obj["used_by"].append(chat_id)
                    total_assigned_stats += 1

                    if n_obj["shares"] >= bot_settings.get("num_share", 1):
                        n_obj["to_remove"] = True
                        used_numbers_list.append(num_str)

                for b_id in number_batches:
                    number_batches[b_id]["numbers"] = [n for n in number_batches[b_id]["numbers"] if not n.get("to_remove")]
                save_db()

            vtx_ext = "_vtx" if 'is_voltx_used' in locals() and is_voltx_used else ""
            ch_country_cb = "get_number_menu"
            ch_number_cb = f"c_n_s_{query}{vtx_ext}"
            card_service = "NUMBER"
            card_category = "FREE"
            num_text = _number_result_text(card_service, query, card_category, fetched_nums, show_prefix=True)
            markup = _number_result_markup(card_service, query, card_category, fetched_nums, ch_country_cb, ch_number_cb, show_prefix=True)
            active_msg_id = _deliver_number_card(chat_id, wait_msg_id, num_text, markup, card_service, query, card_category, fetched_nums, show_prefix=True)
            if active_msg_id:
                user_active_sessions[chat_id] = _number_session_payload(active_msg_id, fetched_nums, reward_by_num, card_service, query, card_category, ch_country_cb, ch_number_cb, show_prefix=True)
            return

        elif state == "wait_for_withdraw_amount" and text:
            msg_id_to_edit = temp_data[chat_id].get("msg_id")
            try:
                amount = float(text.strip())
                bal = temp_data[chat_id]["balance"]
                min_w = bot_settings['min_withdraw']

                if amount < min_w:
                    if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ Minimum withdrawal is {min_w} $!\n💰 Balance: {bal} $\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return
                if amount > bal:
                    if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text(f"❌ You don't have enough balance!\n💰 Balance: {bal} $\n\n📝 Enter again:"), reply_markup=get_cancel_kb())
                    return

                temp_data[chat_id]["amount"] = amount
                user_states[chat_id] = "wait_for_withdraw_number"
                if msg_id_to_edit:
                    edit_message(chat_id, msg_id_to_edit, render_body_text(f"✅ Amount: {amount} $\n\n📱 Now send your <b>{temp_data[chat_id]['method']}</b> payout details:"), reply_markup=get_cancel_kb())
            except ValueError:
                if msg_id_to_edit: edit_message(chat_id, msg_id_to_edit, render_body_text("❌ Invalid amount!\n\n📝 Please send a valid number:"), reply_markup=get_cancel_kb())
            return

        elif state == "wait_for_2fa_key" and text:
            msg_id_to_edit = temp_data.get(chat_id, {}).get("msg_id")
            delete_message(chat_id, msg.get("message_id")) #

            if not msg_id_to_edit:
                send_message(chat_id, render_body_text("❌ Error: Message not found. Try again."))
                del user_states[chat_id]
                return

            try:
                secret = text.strip().replace(" ", "")
                totp = pyotp.TOTP(secret)
                code = totp.now()
                remaining_time = 30 - (int(time.time()) % 30)

                success_txt = _menu_grid(PEM['lock'] + " <b>2FA CODE</b>", [
                    ("CODE", str(code)),
                    ("EXPIRES IN", f"{remaining_time}s"),
                ])
                kb = [[{"text": f"Click to copy {code}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": code}, "style": "success"}],
                      [{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"ref_2fa_{secret}", "style": "primary"},
                       {"text": "New Code", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "gen_2fa", "style": "danger"}],
                      [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]

                edit_message(chat_id, msg_id_to_edit, render_body_text(success_txt), reply_markup={"inline_keyboard": kb})
                del user_states[chat_id]
                if chat_id in temp_data: del temp_data[chat_id]
            except Exception:
                error_txt = _menu_grid("🔑 ENTER 2FA KEY", [
                    ("ACTION", "SEND YOUR 2FA SECRET KEY"),
                    ("STATUS", "INVALID KEY, TRY AGAIN"),
                ])
                cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_2fa", "style": "danger"}]]}
                edit_message(chat_id, msg_id_to_edit, render_body_text(error_txt), reply_markup=cancel_kb)
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

            if bot_settings["w_group"]:
                admin_msg = f"🎙 <b>NEW WITHDRAWAL REQUEST</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={chat_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amount} USD\n🍏 <b>PAYOUT DETAILS:</b> <code>{number}</code>\n🏦 <b>METHOD:</b> {method}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"
                kb = {"inline_keyboard": [[{"text": "APPROVE", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"wapp_{req_id}", "style": "success"}, {"text": "REJECT", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"wrej_{req_id}", "style": "danger"}]]}
                send_message(bot_settings["w_group"], render_body_text(admin_msg), reply_markup=kb)

            kb = {"inline_keyboard": [[{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]}
            success_text = f"{PEM['ok']} Your withdrawal request has been submitted!\n\n🧾 <b>Req ID:</b> {req_id}\n💰 <b>Amount:</b> {amount} $\n🏦 <b>Method:</b> {method}\n📱 <b>Payout Details:</b> <code>{number}</code>"

            if msg_id_to_edit:
                edit_message(chat_id, msg_id_to_edit, render_body_text(success_text), reply_markup=kb)
            else:
                send_message(chat_id, render_body_text(success_text), reply_markup=kb)

            del user_states[chat_id]
            del temp_data[chat_id]
            return

    # --- Regular Commands ---
    if text.startswith("/start"):
        get_user(chat_id)

        # --- PROCESS PENDING REFERRAL ---
        if db:
            try:
                doc = db.collection('users').document(str(chat_id)).get()
                if doc.exists:
                    u_data = doc.to_dict()
                    if u_data.get("referred_by") and not u_data.get("ref_paid"):
                        inviter = u_data["referred_by"]
                        db.collection('users').document(str(chat_id)).update({"ref_paid": True})
                        reward = bot_settings.get("refer_reward", 0.2)
                        update_balance(inviter, reward)
                        if db:
                            db.collection('users').document(str(inviter)).update({"total_refers": firestore.Increment(1)})
                        _send_referral_reward_board(inviter, reward, str(chat_id))
            except Exception as e:
                print(f"❌ Referral processing skipped: {type(e).__name__}: {e}")
                disable_firestore("Referral processing failed.")

        c_msg = bot_settings["custom_messages"].get("start", {})
        txt = render_custom_menu_body("start", msg)
        kb = []
        for b in safe_custom_buttons(c_msg.get("buttons", [])):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        inline_markup = {"inline_keyboard": kb} if kb else None
        main_markup = main_menu(chat_id)
        media = c_msg.get("media") or {}
        media_type = str(media.get("type") or "").lower()
        media_id = str(media.get("file_id") or "").strip()
        media_sent = False
        if media_id and media_type == "photo" and len(txt) <= 1024:
            result = send_photo(chat_id, media_id, caption=txt, reply_markup=inline_markup or main_markup)
            media_sent = bool(result and result.get("ok"))
        elif media_id and media_type == "document" and len(txt) <= 1024:
            result = api_call("sendDocument", {
                "chat_id": chat_id,
                "document": media_id,
                "caption": txt,
                "parse_mode": "HTML",
                "reply_markup": inline_markup or main_markup,
            })
            media_sent = bool(result and result.get("ok"))
        if media_sent:
            if inline_markup:
                send_message(chat_id, render_body_text(f"{PEM['gear']} Navigation Menu:"), reply_markup=main_markup)
        elif inline_markup:
            # If an old/invalid file_id or an overlong caption prevents media
            # delivery, never lose the body text or stop the bot.
            send_message(chat_id, txt, reply_markup=inline_markup)
            send_message(chat_id, render_body_text(f"{PEM['gear']} Navigation Menu:"), reply_markup=main_markup)
        else:
            send_message(chat_id, txt, reply_markup=main_markup)

    elif text == "TRAFFIC":
        txt, markup = build_traffic_ui()
        send_message(chat_id, txt, reply_markup=markup)

    elif text == "Refer":
        u_data = get_user(chat_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        c_msg = bot_settings["custom_messages"].get("refer", {})

        txt = render_custom_menu_body("refer", msg, {
            "ref_link": ref_link,
            "total_ref": u_data.get('total_refers', 0),
            "ref_reward": bot_settings['refer_reward'],
        })

        kb = [[{"text": "COPY LINK", "icon_custom_emoji_id": "5192739271886282680", "copy_text": {"text": ref_link}, "style": "success"}]]
        for b in safe_custom_buttons(c_msg.get("buttons", [])):
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
        txt = render_custom_menu_body("withdrawal", msg, {
            "bal": bal,
            "total_otp": u_data.get('total_otps', 0),
            "total_ref": u_data.get('total_refers', 0),
            "min_w": bot_settings['min_withdraw'],
        })

        kb = []
        for m in bot_settings["w_methods"]:
            kb.append([{"text": m.strip(), "icon_custom_emoji_id": "5190899075968441286", "callback_data": f"sel_wm_{m.strip()}", "style": "primary"}])

        for b in safe_custom_buttons(c_msg.get("buttons", [])):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        kb.append([{"text": "Cancel", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif text == "Admin Panel" and is_admin(chat_id):
        send_message(chat_id, get_admin_text(), reply_markup=admin_panel_keyboard())

    elif text == "GET NUMBER":
        local_srvs = set([b["service"] for b in number_batches.values() if b["numbers"]])
        stex_srvs = set(bot_settings.get("stex_services", {}).keys())
        voltx_srvs = set(bot_settings.get("voltx_services", {}).keys())
        all_services = local_srvs.union(stex_srvs).union(voltx_srvs)

        if not all_services:
            send_message(chat_id, render_body_text(f"{PEM['no']} No numbers or services available!"))
        else:
            c_msg = bot_settings["custom_messages"].get("get_number", {})
            txt = render_custom_menu_body("get_number", msg)

            apps_db = bot_settings.get("premium_apps", {})
            kb = []
            for s in all_services:
                emoji_id = "5352694861990501856" # Default icon
                for app_key, app_data in apps_db.items():
                    if s.upper() == app_key or s.upper() in app_key or app_key in s.upper():
                        if "id" in app_data:
                            emoji_id = app_data["id"]
                            break
                kb.append([{"text": f"{s}", "icon_custom_emoji_id": emoji_id, "callback_data": f"g_s_{s}", "style": "primary"}])

            for b in safe_custom_buttons(c_msg.get("buttons", [])):
                b_copy = b.copy()
                if "style" not in b_copy: b_copy["style"] = "primary"
                kb.append([b_copy])
            kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])

            send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif text == "Search Number":
        user_states[chat_id] = "wait_for_search"
        c_msg = bot_settings["custom_messages"].get("search_number", {})
        txt = render_custom_menu_body("search_number", msg)
        kb = [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_state", "style": "danger"}]]
        for b in safe_custom_buttons(c_msg.get("buttons", [])):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb})

    elif text == "2FA ONLINE" or text == "🔐 2FA ONLINE":
        txt = _menu_grid(PEM['lock'] + " <b>2FA ONLINE</b>", [
            ("SERVICE", "2FA CODE GENERATOR"),
            ("INPUT", "YOUR SECRET KEY"),
            ("SPEED", "INSTANT GENERATION"),
        ])
        kb = [[{"text": "Generate 2fa code", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "gen_2fa", "style": "success"}],
              [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
        send_message(chat_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif text == "SUPPORT":
        c_msg = bot_settings["custom_messages"].get("support", {})
        txt = render_custom_menu_body("support", msg)
        if not txt.strip(): txt = render_body_text(f"{PEM['msg']} Support")
        kb = []
        for b in safe_custom_buttons(c_msg.get("buttons", [])):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])

        sup_link = bot_settings.get("support_link", "")
        sup_url = valid_button_url(sup_link)
        if sup_url:
            kb.insert(0, [{"text": "Contact Support", "icon_custom_emoji_id": "5337302974806922068", "url": sup_url, "style": "success"}])

        kb.append([{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}])
        send_message(chat_id, txt, reply_markup={"inline_keyboard": kb} if kb else None)

#==============================================================================
#  [36]  NUMBER EXPIRY HELPER
#==============================================================================
def expire_previous_number(chat_id):
    if chat_id in user_active_sessions:
        prev_data = user_active_sessions[chat_id]
        prev_msg_id = prev_data["msg_id"]
        nums = prev_data["nums"]

        # StexSMS
        for num in nums:
            if num in stex_assigned_numbers:
                del stex_assigned_numbers[num]
        save_db()

        # Regular numbers are marked expired when a new request starts.
        # Facebook Tools numbers remain inbox-active for 24 hours, so do not
        # replace the visible card with an expired notice.
        if not prev_data.get("fb_tools_mode"):
            kb = [[{"text": "Number Expired", "icon_custom_emoji_id": "5336997731481193790", "callback_data": "ignore", "style": "danger"}]]
            try:
                edit_message(chat_id, prev_msg_id, "ㅤ\n", reply_markup={"inline_keyboard": kb})
            except:
                pass
        del user_active_sessions[chat_id]
    try:
        with api_session_lock:
            api_number_sessions.pop(chat_id, None)
    except Exception:
        pass

# ==========================================
# Callback Query Handler
# ==========================================
#==============================================================================
#  [37]  CORE HANDLER — handle_callback (V1, wrapped by patch layer)
#==============================================================================
def handle_callback(call):
    global total_assigned_stats
    chat_id = call["message"]["chat"]["id"]
    chat_type = call["message"]["chat"].get("type", "private")
    data = call.get("data", "")

    # 🌟 Button Loading Fix:      Response  ,     !
    if not data.startswith("test_p_conn_") and not data.startswith("c_n_") and not data.startswith("g_c_"):
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
                        _send_referral_reward_board(inviter, reward, str(chat_id))
        else:
            answer_callback(call["id"], "❌ You haven't joined all channels yet!", show_alert=True)
        return

    if data == "close_msg":
        delete_message(chat_id, msg_id)

    elif data == "get_number_menu":
        show_service_menu(chat_id, msg_id, "FREE NUMBER")
        answer_callback(call["id"])

    elif data == "cancel_state":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        delete_message(chat_id, msg_id)

    elif data == "cancel_2fa":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        txt = _menu_grid(PEM['lock'] + " <b>2FA ONLINE</b>", [
            ("SERVICE", "2FA CODE GENERATOR"),
            ("INPUT", "YOUR SECRET KEY"),
            ("SPEED", "INSTANT GENERATION"),
        ])
        kb = [[{"text": "Generate 2fa code", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "gen_2fa", "style": "success"}],
              [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

    elif data == "gen_2fa":
        user_states[chat_id] = "wait_for_2fa_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        txt = _menu_grid("🔑 ENTER 2FA KEY", [
            ("ACTION", "SEND YOUR 2FA SECRET KEY"),
        ])
        kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_2fa", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
        answer_callback(call["id"])

    elif data.startswith("ref_2fa_"):
        secret = data.replace("ref_2fa_", "")
        try:
            totp = pyotp.TOTP(secret)
            code = totp.now()
            remaining_time = 30 - (int(time.time()) % 30)

            success_txt = _menu_grid(PEM['lock'] + " <b>2FA CODE</b>", [
                ("CODE", str(code)),
                ("EXPIRES IN", f"{remaining_time}s"),
            ])
            kb = [[{"text": f"Click to copy {code}", "icon_custom_emoji_id": "5353022963132174959", "copy_text": {"text": code}, "style": "success"}],
                  [{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": f"ref_2fa_{secret}", "style": "primary"},
                   {"text": "New Code", "icon_custom_emoji_id": "5352552689983067014", "callback_data": "gen_2fa", "style": "danger"}],
                  [{"text": "Close", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "close_msg", "style": "danger"}]]

            edit_message(chat_id, msg_id, render_body_text(success_txt), reply_markup={"inline_keyboard": kb})
        except:
            answer_callback(call["id"], "❌ Error refreshing code!", show_alert=True)

    elif data == "cancel_dxa_edit":
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())

    elif data == "dummy_alert":
        answer_callback(call["id"], "This feature will be added later!", show_alert=True)

    elif data == "refresh_traffic":
        txt, markup = build_traffic_ui()
        edit_message(chat_id, msg_id, txt, reply_markup=markup)
        answer_callback(call["id"], "✅ Traffic Refreshed!", show_alert=False)

    elif data == "traffic_main_menu":
        edit_message(chat_id, msg_id, render_body_text("🏠 <b>MAIN MENU</b>"))
        send_message(chat_id, render_body_text("✅ Main menu restored."), reply_markup=main_menu(chat_id))
        answer_callback(call["id"])

    elif data.startswith("exp_rng_"):
        srv_query = data.replace("exp_rng_", "")

        country_stats = {}
        current_time = time.time()
        for t in recent_traffic:
            if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS:
                if t.get("service", "").startswith(srv_query):
                    iso = t.get("iso", "XX")
                    flag = t.get("flag", "🌍")
                    if iso not in country_stats:
                        country_stats[iso] = {"count": 0, "flag": flag}
                    country_stats[iso]["count"] += 1

        if not country_stats:
            answer_callback(call["id"], "❌ No recent traffic found for this service!", show_alert=True)
            return

        kb = []
        for iso, c_data in sorted(country_stats.items(), key=lambda x: x[1]["count"], reverse=True):
            count = c_data["count"]
            c_name = iso
            emoji_id = "5780471598922337683"
            for code, fdata in bot_settings.get("premium_flags", {}).items():
                if fdata.get("iso") == iso:
                    c_name = fdata.get("name", iso)
                    if "id" in fdata: emoji_id = fdata["id"]
                    break

            btn_text = f"{c_name} ({iso}) - {count} OTP"
            kb.append([{"text": btn_text, "icon_custom_emoji_id": emoji_id, "callback_data": f"exp_c_{srv_query}_{iso}", "style": "primary"}])

        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "refresh_traffic", "style": "danger"}])

        app_full_name, prem_app_html = get_service_info_html(srv_query)
        edit_message(chat_id, msg_id, render_body_text(f"📊 <b>Explore Service: {prem_app_html} {app_full_name}</b>\n\nSelect a country to view available ranges:"), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

    elif data.startswith("exp_c_"):
        parts = data.split("_")
        srv_query = parts[2]
        iso_query = parts[3]

        nums = []
        current_time = time.time()
        for t in recent_traffic:
            if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS:
                if t.get("service", "").startswith(srv_query) and t.get("iso") == iso_query:
                    num = t.get("number", "").replace("+", "").strip()
                    if num: nums.append(num)

        if not nums:
            answer_callback(call["id"], "❌ No recent numbers found for this country!", show_alert=True)
            return

        #  StexSMS Services    (Search Countries  ,      )
        known_ranges = set()
        for s_name, c_dict in bot_settings.get("stex_services", {}).items():
            for c_name, r_list in c_dict.items():
                for r in r_list:
                    known_ranges.add(r)

        sorted_known = sorted(list(known_ranges), key=len, reverse=True)

        r_counts = Counter()
        for num in nums:
            matched = False
            for r in sorted_known:
                if num.startswith(r):
                    r_counts[r] += 1
                    matched = True
                    break
            if not matched:
                if len(num) >= 7:
                    r_counts[num[:7]] += 1
                else:
                    r_counts[num] += 1

        r_list = r_counts.most_common(12)

        kb = []
        for r, count in r_list:
            #
            kb.append([{"text": f"{r} ({count})", "icon_custom_emoji_id": "5352862640592949843", "copy_text": {"text": r}, "style": "primary"}])

        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"exp_rng_{srv_query}", "style": "danger"}])

        app_full_name, prem_app_html = get_service_info_html(srv_query)
        prem_flag_html = get_flag_info_html(iso_query)

        edit_message(chat_id, msg_id, render_body_text(f"📊 <b>Ranges for {prem_app_html} {app_full_name} - {prem_flag_html} {iso_query}</b>\n\nClick on any range to copy it."), reply_markup={"inline_keyboard": kb})
        answer_callback(call["id"])

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
        edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Menu Design Editor — Full Control</b>\n\nEvery user-facing menu is editable: body text, inline buttons, card titles, rows and full card bodies. Buttons are validated automatically, so a button that has no function in the bot can never be saved."), reply_markup=menu_design_list_keyboard())

    elif data == "md_reset_defaults":
        # Deep copy: a shallow copy let later edits corrupt the module defaults,
        # which silently broke every "Reset Defaults" after the first one.
        bot_settings["custom_messages"] = json.loads(json.dumps(DEFAULT_CUSTOM_MESSAGES))
        bot_settings["card_templates"] = json.loads(json.dumps(DEFAULT_CARD_TEMPLATES))
        save_db()
        answer_callback(call["id"], "✅ Resetted to Premium Defaults!", show_alert=True)

    elif data == "md_fix_dead_buttons":
        problems = sanitize_design_data(persist=False)
        if problems:
            save_db()
            report = "\n".join(f"• {html.escape(p)}" for p in problems)
            report_text = f"🛠 <b>Dead Button Scanner</b>\n\n{report}\n\n✅ All menu designs are now safe."
        else:
            report_text = "🛠 <b>Dead Button Scanner</b>\n\n✅ No dead or broken buttons found. Every Menu Design button works inside the bot."
        answer_callback(call["id"])
        edit_message(chat_id, msg_id, render_body_text(report_text), reply_markup=menu_design_list_keyboard())

    elif data == "md_remove_start_media":
        bot_settings["custom_messages"].setdefault("start", {}).pop("media", None)
        save_db()
        answer_callback(call["id"], "Start image removed", show_alert=True)
        edit_message(chat_id, msg_id, render_body_text("✅ <b>/start image removed.</b>"), reply_markup=menu_edit_options_keyboard("start"))

    elif data == "md_user_menu":
        answer_callback(call["id"])
        edit_message(chat_id, msg_id, render_body_text("<b>User Menu Editor</b>\n\nChange User Menu button text, button emoji, and User Menu body emoji mappings here."), reply_markup=user_menu_editor_keyboard())

    elif data in {"md_edit_access_type", "md_edit_service_menu", "md_edit_fb_tools_menu", "md_edit_fb_service_menu"}:
        answer_callback(call["id"])
        key = {"md_edit_access_type": "access_type", "md_edit_service_menu": "service_menu", "md_edit_fb_tools_menu": "fb_tools_menu", "md_edit_fb_service_menu": "fb_service_menu"}[data]
        cm_text = render_body_text(bot_settings["custom_messages"].get(key, {}).get("text", "..."))
        edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Editing: {key.upper()}</b>\n\nPreview of current Text:\n{cm_text}"), reply_markup=menu_edit_options_keyboard(key))

    elif data.startswith("md_edit_"):
        answer_callback(call["id"])
        if chat_id in user_states: del user_states[chat_id]
        if chat_id in temp_data: del temp_data[chat_id]
        key = data.replace("md_edit_", "")
        if key in _MD_CARD_ONLY_KEYS:
            # Card-backed screens (Profile, Balance, Number Result, Admin Panel)
            # are edited through the full Card Template editor.
            return _show_card_editor(chat_id, key, msg_id)
        cm_text = render_body_text(bot_settings["custom_messages"].get(key, {}).get("text", "..."))
        try:
            edit_message(chat_id, msg_id, render_body_text(f"🎨 <b>Editing: {key.upper()}</b>\n\nPreview of current Text:\n{cm_text}"), reply_markup=menu_edit_options_keyboard(key))
        except: pass

    elif data.startswith("md_text_"):
        key = data.replace("md_text_", "")
        user_states[chat_id] = "wait_for_menu_text"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        placeholder_help = ""
        media_help = ""
        if key == "start":
            media_help = "\n\nFor /start, send either text or a photo with a caption. The photo will be sent above the body text."

        if key in {"number_broadcast", "otp_inbox", "otp_group"}:
            placeholder_help = (
                "\n\nPlaceholders: <code>{country}</code> = flag, "
                "<code>{country1}</code> = country name, "
                "<code>{service}</code> = service icon/name, "
                "<code>{service1}</code> = service name, "
                "<code>{number}</code> = full number, "
                "<code>{number1}</code> = masked number, "
                "<code>{otp}</code>, <code>{prefix}</code>, <code>{lang}</code>, "
                "<code>{sms}</code>, <code>{reward}</code>, <code>{category}</code>, "
                "<code>{total}</code>, <code>{batch_id}</code>."
            )
        elif _md_uses_card(key):
            extra_help = _md_placeholder_help(key)
            if extra_help:
                placeholder_help = "\n\nPlaceholders: " + extra_help
        edit_message(chat_id, msg_id, render_body_text(f"📝 <b>Edit Body: {key.upper()}</b>\n\nSend the new text. You can use Premium Emojis directly here.{media_help}{placeholder_help}\n(Use standard HTML like <b>bold</b>, <i>italic</i> for formatting)"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_edit_{key}", "style": "danger"}]]})

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
        edit_message(chat_id, msg_id, render_body_text(f"➕ <b>Add Button: {key.upper()}</b>\n\nSend one of these formats:\n<code>Continue - https://example.com</code>\n<code>Continue &lt;6170209141953403618&gt; - https://example.com</code>\n<code>Continue - https://example.com | emoji:success</code>\n<code>Continue &lt;6170209141953403618&gt; - https://example.com</code>\n\nUse one angle-bracket ID or a saved dynamic name. A directly sent Premium Emoji is also accepted."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_btns_{key}", "style": "danger"}]]})

    elif data.startswith("md_seticon_"):
        rest = data[len("md_seticon_"):]
        try:
            key, b_idx_raw = rest.rsplit("_", 1)
            b_idx = int(b_idx_raw)
        except (ValueError, TypeError):
            answer_callback(call["id"], "Invalid button", show_alert=True)
            return
        user_states[chat_id] = "wait_for_menu_icon"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key, "button_index": b_idx}
        current = _md_buttons_store(key)
        action = "Change Icon" if 0 <= b_idx < len(current) and current[b_idx].get("icon_custom_emoji_id") else "Set Icon"
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['star']} <b>{action}</b>\n\nSend one numeric ID, a saved dynamic name such as <code>success</code>, or directly send one Premium Emoji."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"md_btns_{key}", "style": "danger"}]]})

    elif data.startswith("md_delbtn_"):
        rest = data[len("md_delbtn_"):]
        try:
            key, b_idx_raw = rest.rsplit("_", 1)
            b_idx = int(b_idx_raw)
        except (ValueError, TypeError):
            answer_callback(call["id"], "Invalid button", show_alert=True)
            return
        btns_store = _md_buttons_store(key)
        if b_idx < len(btns_store):
            del btns_store[b_idx]
            save_db()
            answer_callback(call["id"], "✅ Button Deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text(f"⚙️ <b>Edit Inline Buttons: {key.upper()}</b>"), reply_markup=menu_buttons_list_keyboard(key))

    elif data.startswith("sel_wm_"):
        method = data.replace("sel_wm_", "")
        bal = get_user(chat_id).get('balance', 0.0)
        min_w = bot_settings['min_withdraw']

        if bal < min_w:
            answer_callback(call["id"], f"❌ Insufficient balance. Minimum {min_w} USD is required.", show_alert=True)
            return

        temp_data[chat_id] = {"method": method, "balance": bal, "msg_id": msg_id}
        user_states[chat_id] = "wait_for_withdraw_amount"
        edit_message(chat_id, msg_id, _menu_grid(
            PEM['money'] + " <b>WITHDRAW</b>", [
                ("METHOD", str(method)),
                ("BALANCE", "{} $".format(bal)),
                ("ENTER AMOUNT", "MIN {} $".format(min_w)),
            ],
            footer="📝 SEND THE AMOUNT IN YOUR NEXT MESSAGE",
        ), reply_markup=get_cancel_kb())
        answer_callback(call["id"])

    elif data == "test_message_flow":
        user_states[chat_id] = "wait_for_test_service"
        temp_data[chat_id] = {}
        edit_message(chat_id, msg_id, render_body_text("🧪 <b>Test Mode</b>\n\n📝 Send the Service Name (e.g., WhatsApp):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]]})

    elif data == "manage_emojis":
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['star']} <b>Premium Emoji Management</b>\n\nUpload your TXT files or manually add them below:"), reply_markup=emoji_settings_keyboard())

    elif data == "clear_emoji_id":
        user_states[chat_id] = "wait_for_clear_emoji_id"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                "🗑 <b>Clear Specific Emoji ID</b>\n\n"
                "Send one numeric Premium Emoji ID. The bot will remove it from the matching service or country record and save the change."
            ),
            reply_markup=get_cancel_kb(),
        )

    elif data == "preview_emoji_ids":
        user_states[chat_id] = "wait_for_emoji_id_preview"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['star']} <b>Preview Emoji IDs</b>\n\nSend up to 200 plain IDs separated by comma, space or newline."), reply_markup=get_cancel_kb())

    elif data == "extract_emoji_ids":
        user_states[chat_id] = "wait_for_emoji_id_extract"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['star']} <b>Extract Emoji IDs</b>\n\nForward or send one or more Premium Custom Emoji messages or custom emoji stickers."), reply_markup=get_cancel_kb())

    elif data == "extract_pack_emoji_ids":
        user_states[chat_id] = "wait_for_emoji_pack_link"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['link']} <b>Extract Pack IDs</b>\n\nSend a public Telegram Emoji Pack link, for example:\n<code>https://t.me/addemoji/PackName</code>"), reply_markup=get_cancel_kb())

    elif data == "up_flags_txt":
        user_states[chat_id] = "wait_for_flag_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the <b>Flag Emojis</b> <code>.txt</code> file."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "up_apps_txt":
        user_states[chat_id] = "wait_for_app_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the <b>Service Apps</b> <code>.txt</code> file."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "add_single_emoji":
        user_states[chat_id] = "wait_for_emoji_extract"
        edit_message(chat_id, msg_id, render_body_text("📝 Send any premium emoji, e.g. a flag or an app icon:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_emojis", "style": "danger"}]]})

    elif data == "user_menu_editor":
        edit_message(chat_id, msg_id, render_body_text("<b>User Menu Text and Emoji Editor</b>\n\nEvery User Menu label and icon can be changed. Body Emoji Editor controls the message-body icons used across the bot."), reply_markup=user_menu_editor_keyboard())

    elif data == "body_emoji_editor":
        edit_message(chat_id, msg_id, render_body_text("<b>Body Emoji Editor</b>\n\nChoose a body emoji to replace its Custom Emoji ID. Changes apply to all user-facing message bodies."), reply_markup=body_emoji_editor_keyboard())

    elif data.startswith("bme_set_"):
        item = _body_emoji_by_index(data[len("bme_set_"):])
        if not item:
            answer_callback(call["id"], "Invalid body emoji", show_alert=True)
            return
        body_char, current_id = item
        user_states[chat_id] = "wait_for_body_emoji"
        temp_data[chat_id] = {"msg_id": msg_id, "body_char": body_char}
        edit_message(chat_id, msg_id, render_body_text(f"Send one valid Premium Emoji ID or one Premium Emoji for <code>{html.escape(body_char)}</code>.\n\nCurrent ID: <code>{html.escape(str(current_id))}</code>"), reply_markup=get_cancel_kb())

    elif data.startswith("ume_icon_"):
        key = data[len("ume_icon_"):]
        if key not in USER_MENU_LABEL_DEFAULTS:
            answer_callback(call["id"], "Invalid menu item", show_alert=True)
            return
        user_states[chat_id] = "wait_for_user_menu_emoji"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"Send one valid Premium Emoji ID or one Premium Emoji for the <b>{html.escape(menu_label(key))}</b> button."), reply_markup=get_cancel_kb())

    elif data.startswith("ume_text_"):
        key = data[len("ume_text_"):]
        if key not in USER_MENU_LABEL_DEFAULTS:
            answer_callback(call["id"], "Invalid menu item", show_alert=True)
            return
        user_states[chat_id] = "wait_for_user_menu_text"
        temp_data[chat_id] = {"msg_id": msg_id, "menu_key": key}
        edit_message(chat_id, msg_id, render_body_text(f"Send the new button text for <b>{html.escape(menu_label(key))}</b>."), reply_markup=get_cancel_kb())

    elif data == "button_emoji_editor":
        user_states[chat_id] = "wait_for_button_emoji_edit"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>Button Emoji Editor</b>\n\nSend the exact button name followed by one ID in angle brackets:\n<code>GET NUMBER &lt;586555&gt;</code>\n\nThe button name must match the visible Telegram button text. The new icon will apply everywhere that button appears."), reply_markup=get_cancel_kb())

    elif data == "dl_flags_txt":
        content = generate_emoji_txt("flags")
        if content:
            send_document(chat_id, "Flag_Emojis.txt", content)
            answer_callback(call["id"], "✅ Downloaded!")
        else:
            answer_callback(call["id"], "❌ No Flag Emojis found!", show_alert=True)

    elif data == "dl_apps_txt":
        content = generate_emoji_txt("apps")
        if content:
            send_document(chat_id, "Service_Apps.txt", content)
            answer_callback(call["id"], "✅ Downloaded!")
        else:
            answer_callback(call["id"], "❌ No App Emojis found!", show_alert=True)

    elif data == "del_all_flags":
        bot_settings["premium_flags"] = {}
        save_db()
        answer_callback(call["id"], "✅ All Premium Flags Deleted Successfully!", show_alert=True)

    elif data == "broadcast_msg":
        user_states[chat_id] = "wait_for_broadcast"
        edit_message(chat_id, msg_id, render_body_text("📢 <b>Broadcast Mode</b>\n\nSend the message you want to broadcast (Text, Photo, Video, File etc)."), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]})

    elif data == "upload_num":
        user_states[chat_id] = "wait_for_txt"
        edit_message(chat_id, msg_id, render_body_text("📂 Please upload the numbers in a <b>.txt</b> file."), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]})

    elif data == "delete_files":
        kb = []
        for b_id, b_data in number_batches.items():
            kb.append([{"text": f"{b_data['filename']} ({len(b_data['numbers'])})", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"del_b_{b_id}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "primary"}])
        txt = "🗑 Select a file to delete:" if len(kb) > 1 else f"{PEM['no']} No files found."
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_b_"):
        b_id = data.split("del_b_")[1]
        if b_id in number_batches:
            del number_batches[b_id]
            save_db()
            answer_callback(call["id"], "✅ File deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "delete_files", "id": call["id"]})

    elif data == "show_used":
        kb = {"inline_keyboard": [[{"text": "Download TXT", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_used", "style": "primary"}], [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} <b>Total Used Numbers:</b> {len(used_numbers_list)}"), reply_markup=kb)

    elif data == "show_unused":
        unused_count = sum(len(b["numbers"]) for b in number_batches.values())
        kb = {"inline_keyboard": [[{"text": "Download TXT", "icon_custom_emoji_id": "5257969839313526622", "callback_data": "dl_unused", "style": "primary"}], [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "back_to_admin", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['rocket']} <b>Total Unused Numbers:</b> {unused_count}"), reply_markup=kb)

    elif data == "dl_used":
        if not used_numbers_list:
            answer_callback(call["id"], "❌ No used numbers found!", show_alert=True)
            return
        content = "\n".join(used_numbers_list).encode('utf-8')
        send_document(chat_id, "used_numbers.txt", content)
        answer_callback(call["id"])

    elif data == "dl_unused":
        unused_list = [n["num"] for b in number_batches.values() for n in b["numbers"]]
        if not unused_list:
            answer_callback(call["id"], "❌ No unused numbers found!", show_alert=True)
            return
        content = "\n".join(unused_list).encode('utf-8')
        send_document(chat_id, "unused_numbers.txt", content)
        answer_callback(call["id"])

    elif data == "lb_main":
        txt = _menu_grid(PEM['admin'] + " <b>LEADER BOARD</b>", [
            ("VIEW", "TOP PERFORMERS & HISTORY"),
            ("ACTION", "SELECT A CATEGORY BELOW"),
        ])
        kb = [
            [{"text": "Top Referrers", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "lb_top_refs", "style": "primary"}],
            [{"text": "Top OTP Receivers", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "lb_top_otps", "style": "primary"}],
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
                        p = "•"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "• <i>No data found.</i>\n"

            elif sub == "top_otps":
                title, field, limit, icon = "TOP 5 OTP RECEIVERS", "total_otps", 5, PEM.get('msg', '📩')
                users = db.collection('users').order_by(field, direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for u in users:
                    d = u.to_dict()
                    if d.get(field, 0) > 0:
                        p = "•"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "• <i>No data found.</i>\n"

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
                    p = "•"
                    res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={uid}'>{uid}</a> ➔ <b>${d.get('amount',0)} USD</b> {stat_icon}\n"
                    count += 1
                if not res_txt: res_txt = "• <i>No history found.</i>\n"

            final_msg = f"\n{icon} <b>{title}</b>\n\n{res_txt}"
            kb = [[{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": data, "style": "success"}, {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]
            edit_message(chat_id, msg_id, render_body_text(final_msg), reply_markup={"inline_keyboard": kb})

        except Exception as e:
            edit_message(chat_id, msg_id, render_body_text(f"❌ Error: {e}"), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]})

    elif data == "lb_main":
        txt = _menu_grid(PEM['admin'] + " <b>LEADER BOARD</b>", [
            ("VIEW", "TOP PERFORMERS & HISTORY"),
            ("ACTION", "SELECT A CATEGORY BELOW"),
        ])
        kb = [
            [{"text": "Top Referrers", "icon_custom_emoji_id": "5420145051336485498", "callback_data": "lb_top_refs", "style": "primary"}],
            [{"text": "Top OTP Receivers", "icon_custom_emoji_id": "5353001161878182134", "callback_data": "lb_top_otps", "style": "primary"}],
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
                        p = "•"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "• <i>No data found.</i>\n"

            elif sub == "top_otps":
                title, field, limit, icon = "TOP 5 OTP RECEIVERS", "total_otps", 5, PEM.get('msg', '📩')
                users = db.collection('users').order_by(field, direction="DESCENDING").limit(limit).stream()
                res_txt = ""
                count = 1
                for u in users:
                    d = u.to_dict()
                    if d.get(field, 0) > 0:
                        p = "•"
                        res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={u.id}'>{u.id}</a> ➔ <b>{d.get(field,0)}</b>\n"
                        count += 1
                if not res_txt: res_txt = "• <i>No data found.</i>\n"

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
                    p = "•"
                    res_txt += f"{p} {get_p_num(count)} <a href='tg://user?id={uid}'>{uid}</a> ➔ <b>${d.get('amount',0)} USD</b> {stat_icon}\n"
                    count += 1
                if not res_txt: res_txt = "• <i>No history found.</i>\n"

            final_msg = f"\n{icon} <b>{title}</b>\n\n{res_txt}"
            kb = [[{"text": "Refresh", "icon_custom_emoji_id": "5420155432272438703", "callback_data": data, "style": "success"}, {"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]
            edit_message(chat_id, msg_id, render_body_text(final_msg), reply_markup={"inline_keyboard": kb})

        except Exception as e:
            edit_message(chat_id, msg_id, render_body_text(f"❌ Error: {e}"), reply_markup={"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "lb_main", "style": "danger"}]]})

    elif data == "back_to_admin":
        if chat_id in user_states: del user_states[chat_id]
        edit_message(chat_id, msg_id, get_admin_text(), reply_markup=admin_panel_keyboard())

    elif data == "system_settings":
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>System Settings</b>\nManage advanced bot configurations below:"), reply_markup=system_settings_keyboard())

    elif data == "stex_control":
        edit_message(chat_id, msg_id, render_body_text(f"🌐 <b>StexSMS Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('stex_keys', []))}\nManage your StexSMS API Keys below:"), reply_markup=stex_control_keyboard())

    elif data == "add_stex_key":
        user_states[chat_id] = "wait_for_add_stex_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new StexSMS API Key (e.g. nxa_...):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "danger"}]]})

    elif data == "view_stex_keys":
        kb = []
        for idx, key in enumerate(bot_settings.get("stex_keys", [])):
            safe_name = key[:10] + "..." if len(key)>10 else key
            kb.append([{"text": f"Delete {safe_name}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_nxa_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🗑 <b>Select StexSMS Key to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_nxa_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("stex_keys", [])):
            del bot_settings["stex_keys"][idx]
            save_db()
            answer_callback(call["id"], "✅ StexSMS Key Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "view_stex_keys", "id": call["id"]})

    elif data == "stex_search_country":
        kb = []
        for idx, c in enumerate(bot_settings.get("search_countries", [])):
            kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_sc_{idx}", "style": "danger"}])
        kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_search_country", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🌍 <b>Allowed Search Countries:</b>\nOnly these country codes will be allowed in Search Number."), reply_markup={"inline_keyboard": kb})

    elif data == "add_search_country":
        user_states[chat_id] = "wait_for_add_sc"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Country Code (e.g. 880 or 92):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_search_country", "style": "danger"}]]})

    elif data.startswith("del_sc_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("search_countries", [])):
            del bot_settings["search_countries"][idx]
            save_db()
            answer_callback(call["id"], "✅ Country Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "stex_search_country", "id": call["id"]})

    elif data == "manage_stex_srv":
        kb = []
        srvs = bot_settings.get("stex_services", {})
        apps_db = bot_settings.get("premium_apps", {})
        for srv in srvs:
            emoji_id = "5257969839313526622"
            for app_key, app_data in apps_db.items():
                if srv.upper() == app_key or srv.upper() in app_key or app_key in srv.upper():
                    if "id" in app_data:
                        emoji_id = app_data["id"]
                        break
            kb.append([{"text": f"{srv}", "icon_custom_emoji_id": emoji_id, "callback_data": f"nx_srv_{srv}", "style": "primary"}])
        kb.append([{"text": "Add New Service", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "nx_add_srv", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "stex_control", "style": "danger"}])
        edit_message(chat_id, msg_id, render_body_text("📦 <b>StexSMS Services Manager</b>\nManage your API-based dynamic services below:"), reply_markup={"inline_keyboard": kb})

    elif data == "nx_add_srv":
        user_states[chat_id] = "wait_nx_srv_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Enter Service Name (e.g. TELEGRAM):"), reply_markup=get_cancel_kb())

    elif data.startswith("nx_srv_"):
        srv = data.replace("nx_srv_", "")
        kb = []
        countries = bot_settings["stex_services"].get(srv, {})
        for c in countries:
            emoji_id = _country_icon_id(c)
            kb.append([{"text": f"{c} ({len(countries[c])} Ranges)", "icon_custom_emoji_id": emoji_id, "callback_data": f"nx_cnt_{srv}_{c}", "style": "primary"}])
        kb.append([{"text": "Add Country", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"nx_add_cnt_{srv}", "style": "success"}])
        kb.append([{"text": "Delete Service", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"nx_del_srv_{srv}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_stex_srv", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📂 <b>Service: {srv}</b>\nManage countries for this service:"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("nx_add_cnt_"):
        srv = data.replace("nx_add_cnt_", "")
        user_states[chat_id] = "wait_nx_cnt_name"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv}
        edit_message(chat_id, msg_id, render_body_text(f"🌍 Enter Country Name for <b>{srv}</b> (e.g. BD, INDIA):"), reply_markup=get_cancel_kb())

    elif data.startswith("nx_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        ranges = bot_settings["stex_services"][srv].get(cnt, [])

        kb = []
        row = []
        for r in ranges:
            row.append({"text": f"Delete {r}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"nx_dr_{srv}_{cnt}_{r}", "style": "danger"})
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)

        kb.append([{"text": "Add Range", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"nx_addr_{srv}_{cnt}", "style": "success"}])
        kb.append([{"text": "Delete Entire Country", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"nx_del_cnt_{srv}_{cnt}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"nx_srv_{srv}", "style": "primary"}])

        txt = f"📍 <b>Service: {srv} | Country: {cnt}</b>\n\n<b>Total Ranges:</b> {len(ranges)}\n<i>Click on a range below to delete it, or add a new one.</i>"
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("nx_addr_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        user_states[chat_id] = "wait_nx_addr"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv, "cnt": cnt}
        edit_message(chat_id, msg_id, render_body_text(f"📝 Send the new Range for <b>{cnt}</b> (e.g. 88017):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"nx_cnt_{srv}_{cnt}", "style": "danger"}]]})

    elif data.startswith("nx_dr_"):
        parts = data.split("_")
        srv, cnt, rng = parts[2], parts[3], parts[4]
        if rng in bot_settings["stex_services"].get(srv, {}).get(cnt, []):
            bot_settings["stex_services"][srv][cnt].remove(rng)
            save_db()
            answer_callback(call["id"], f"✅ Range {rng} deleted!", show_alert=True)
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"nx_cnt_{srv}_{cnt}", "id": call["id"]})

    elif data.startswith("nx_del_srv_"):
        srv = data.replace("nx_del_srv_", "")
        if srv in bot_settings["stex_services"]: del bot_settings["stex_services"][srv]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_stex_srv", "id": call["id"]})

    elif data.startswith("nx_del_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[3], parts[4]
        if cnt in bot_settings["stex_services"].get(srv, {}): del bot_settings["stex_services"][srv][cnt]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"nx_srv_{srv}", "id": call["id"]})

    elif data == "voltx_control":
        edit_message(chat_id, msg_id, render_body_text(f"⚡ <b>Voltx Control Panel</b>\n\nTotal API Keys: {len(bot_settings.get('voltx_keys', []))}\nManage your Voltx API Keys below:"), reply_markup=voltx_control_keyboard())

    elif data == "add_voltx_key":
        user_states[chat_id] = "wait_for_add_voltx_key"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new Voltx API Key:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "danger"}]]})

    elif data == "view_voltx_keys":
        kb = []
        for idx, key in enumerate(bot_settings.get("voltx_keys", [])):
            safe_name = key[:10] + "..." if len(key)>10 else key
            kb.append([{"text": f"Delete {safe_name}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_vtx_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🗑 <b>Select Voltx Key to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("del_vtx_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("voltx_keys", [])):
            del bot_settings["voltx_keys"][idx]
            save_db()
            answer_callback(call["id"], "✅ Voltx Key Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "view_voltx_keys", "id": call["id"]})

    elif data == "voltx_search_country":
        kb = []
        for idx, c in enumerate(bot_settings.get("voltx_search_countries", [])):
            kb.append([{"text": f"Delete {c}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"del_vsc_{idx}", "style": "danger"}])
        kb.append([{"text": "Add Country Code", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "add_voltx_search_country", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text("🌍 <b>Voltx Allowed Ranges:</b>\nOnly these ranges/codes will be allowed in Voltx Search Number."), reply_markup={"inline_keyboard": kb})

    elif data == "add_voltx_search_country":
        user_states[chat_id] = "wait_for_add_vsc"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Voltx Range Code (e.g. 26134):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_search_country", "style": "danger"}]]})

    elif data.startswith("del_vsc_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings.get("voltx_search_countries", [])):
            del bot_settings["voltx_search_countries"][idx]
            save_db()
            answer_callback(call["id"], "✅ Voltx Range Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "voltx_search_country", "id": call["id"]})

    elif data == "manage_voltx_srv":
        kb = []
        srvs = bot_settings.get("voltx_services", {})
        apps_db = bot_settings.get("premium_apps", {})
        for srv in srvs:
            emoji_id = "5257969839313526622"
            for app_key, app_data in apps_db.items():
                if srv.upper() == app_key or srv.upper() in app_key or app_key in srv.upper():
                    if "id" in app_data: emoji_id = app_data["id"]; break
            kb.append([{"text": f"{srv}", "icon_custom_emoji_id": emoji_id, "callback_data": f"vx_srv_{srv}", "style": "primary"}])
        kb.append([{"text": "Add New Service", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "vx_add_srv", "style": "success"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "voltx_control", "style": "danger"}])
        edit_message(chat_id, msg_id, render_body_text("⚡ <b>Voltx Services Manager</b>\nManage your API-based dynamic services below:"), reply_markup={"inline_keyboard": kb})

    elif data == "vx_add_srv":
        user_states[chat_id] = "wait_vx_srv_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Enter Service Name (e.g. TELEGRAM):"), reply_markup=get_cancel_kb())

    elif data.startswith("vx_srv_"):
        srv = data.replace("vx_srv_", "")
        kb = []
        countries = bot_settings["voltx_services"].get(srv, {})
        for c in countries:
            emoji_id = _country_icon_id(c)
            kb.append([{"text": f"{c} ({len(countries[c])} Ranges)", "icon_custom_emoji_id": emoji_id, "callback_data": f"vx_cnt_{srv}_{c}", "style": "primary"}])
        kb.append([{"text": "Add Country", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"vx_add_cnt_{srv}", "style": "success"}])
        kb.append([{"text": "Delete Service", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"vx_del_srv_{srv}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_voltx_srv", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"📂 <b>Service: {srv}</b>\nManage countries for this service:"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("vx_add_cnt_"):
        srv = data.replace("vx_add_cnt_", "")
        user_states[chat_id] = "wait_vx_cnt_name"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv}
        edit_message(chat_id, msg_id, render_body_text(f"🌍 Enter Country Name for <b>{srv}</b> (e.g. BD, INDIA):"), reply_markup=get_cancel_kb())

    elif data.startswith("vx_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        ranges = bot_settings["voltx_services"][srv].get(cnt, [])
        kb = []
        row = []
        for r in ranges:
            row.append({"text": f"Delete {r}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"vx_dr_{srv}_{cnt}_{r}", "style": "danger"})
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)
        kb.append([{"text": "Add Range", "icon_custom_emoji_id": "5420323438508155202", "callback_data": f"vx_addr_{srv}_{cnt}", "style": "success"}])
        kb.append([{"text": "Delete Entire Country", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"vx_del_cnt_{srv}_{cnt}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"vx_srv_{srv}", "style": "primary"}])
        txt = f"📍 <b>Service: {srv} | Country: {cnt}</b>\n\n<b>Total Ranges:</b> {len(ranges)}\n<i>Click on a range below to delete it, or add a new one.</i>"
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup={"inline_keyboard": kb})

    elif data.startswith("vx_addr_"):
        parts = data.split("_")
        srv, cnt = parts[2], parts[3]
        user_states[chat_id] = "wait_vx_addr"
        temp_data[chat_id] = {"msg_id": msg_id, "srv": srv, "cnt": cnt}
        edit_message(chat_id, msg_id, render_body_text(f"📝 Send the new Range for <b>{cnt}</b> (e.g. 26134):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"vx_cnt_{srv}_{cnt}", "style": "danger"}]]})

    elif data.startswith("vx_dr_"):
        parts = data.split("_")
        srv, cnt, rng = parts[2], parts[3], parts[4]
        if rng in bot_settings["voltx_services"].get(srv, {}).get(cnt, []):
            bot_settings["voltx_services"][srv][cnt].remove(rng)
            save_db()
            answer_callback(call["id"], f"✅ Range {rng} deleted!", show_alert=True)
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"vx_cnt_{srv}_{cnt}", "id": call["id"]})

    elif data.startswith("vx_del_srv_"):
        srv = data.replace("vx_del_srv_", "")
        if srv in bot_settings["voltx_services"]: del bot_settings["voltx_services"][srv]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": "manage_voltx_srv", "id": call["id"]})

    elif data.startswith("vx_del_cnt_"):
        parts = data.split("_")
        srv, cnt = parts[3], parts[4]
        if cnt in bot_settings["voltx_services"].get(srv, {}): del bot_settings["voltx_services"][srv][cnt]
        save_db()
        handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"vx_srv_{srv}", "id": call["id"]})

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

    elif data == "manage_otp_groups":
        edit_message(chat_id, msg_id, render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())

    elif data == "add_fw":
        user_states[chat_id] = "wait_for_add_fw_id"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Group ID/Username to forward messages to:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "danger"}]]})

    elif data.startswith("manage_fw_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            grp_id = bot_settings["fw_groups"][idx]["chat_id"]
            edit_message(chat_id, msg_id, render_body_text(f"🛡 <b>Manage Group:</b> {grp_id}"), reply_markup=specific_fw_group_keyboard(idx))

    elif data.startswith("add_fwbtn_"):
        idx = int(data.split("_")[2])
        user_states[chat_id] = "wait_for_add_fw_btn"
        temp_data[chat_id] = {"msg_id": msg_id, "fw_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send Custom Inline Button format:\n<code>Button Text &lt;586555&gt; - https://link.com</code>"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_fw_{idx}", "style": "danger"}]]})

    elif data.startswith("del_fwbtn_"):
        parts = data.split("_")
        idx, b_idx = int(parts[2]), int(parts[3])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            if 0 <= b_idx < len(bot_settings["fw_groups"][idx]["buttons"]):
                del bot_settings["fw_groups"][idx]["buttons"][b_idx]
                save_db()
                answer_callback(call["id"], "✅ Button deleted!", show_alert=True)
                edit_message(chat_id, msg_id, render_body_text(f"🛡 <b>Manage Group:</b> {bot_settings['fw_groups'][idx]['chat_id']}"), reply_markup=specific_fw_group_keyboard(idx))

    elif data.startswith("del_fw_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["fw_groups"]):
            del bot_settings["fw_groups"][idx]
            save_db()
            answer_callback(call["id"], "✅ Group deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text("🛡 <b>OTP GROUP MANAGEMENT</b>\nManage settings below:"), reply_markup=otp_groups_list_keyboard())

    elif data == "edit_otp_link":
        user_states[chat_id] = "wait_for_otp_link"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the new OTP Group Link:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "manage_otp_groups", "style": "danger"}]]})

    elif data == "manage_panels":
        api_count = len([p for p in bot_settings["panels"] if p.get("type") == "API Panel"])
        cpt_count = len([p for p in bot_settings["panels"] if p.get("type", "API Panel") == "Auto Captcha Panel"])
        text = f"{PEM['gear']} <b>Panel Management</b>\n\nSelect which type of panel system you want to manage:"
        kb = {"inline_keyboard": [
            [{"text": f"Manage API Panels ({api_count})", "icon_custom_emoji_id": "5336972142066047577", "callback_data": "manage_api_panels", "style": "primary"}],
            [{"text": f"Manage Auto Captcha Panels ({cpt_count})", "icon_custom_emoji_id": "5353022963132174959", "callback_data": "manage_cpt_panels", "style": "success"}],
            [{"text": "Back to System", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]
        ]}
        edit_message(chat_id, msg_id, render_body_text(text), reply_markup=kb)

    elif data in ["manage_api_panels", "manage_cpt_panels"]:
        p_type = "API Panel" if data == "manage_api_panels" else "Auto Captcha Panel"
        p_list = [p for p in bot_settings["panels"] if p.get("type", "API Panel") == p_type]
        icon = f"{PEM['world']} API" if p_type == 'API Panel' else f"{PEM['lock']} Auto Captcha"

        text = f"{icon} <b>{p_type}s Management</b>\n\n👀 <b>Active Monitors:</b> {len(p_list)}\n\n🟢 <b>Available Providers:</b>\n"
        for p in p_list:
            status = "Monitoring" if p['status'] == 'ON' else "Stopped"
            login_state = p.get('login_status', '')
            if p['type'] == 'Auto Captcha Panel':
                conf = f" {login_state}" if login_state else f"{PEM['ok']} Configured"
            else:
                conf = f"{PEM['ok']} Configured" if p.get('api_url') else f"{PEM['no']} Not Configured"
            text += f"• {p['name']}: {PEM['ok'] if p['status']=='ON' else PEM['no']} {status} | {conf}\n"
        edit_message(chat_id, msg_id, render_body_text(text), reply_markup=typed_panels_list_keyboard(p_type))

    elif data in ["add_api_panel", "add_cpt_panel"]:
        user_states[chat_id] = "wait_for_panel_name"
        p_type = "api" if data == "add_api_panel" else "logc"
        temp_data[chat_id] = {"msg_id": msg_id, "add_type": p_type}
        edit_message(chat_id, msg_id, render_body_text("📝 Please send the name of the New Provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_{'api' if p_type=='api' else 'cpt'}_panels", "style": "danger"}]]})

    elif data.startswith("add_ptype_"):
        pass

    elif data in ["list_del_api", "list_del_cpt"]:
        p_type = "API Panel" if data == "list_del_api" else "Auto Captcha Panel"
        kb = []
        for idx, p in enumerate(bot_settings["panels"]):
            if p.get("type", "API Panel") == p_type:
                kb.append([{"text": f"Delete {p['name']}", "icon_custom_emoji_id": "5420130255174145507", "callback_data": f"do_del_pnl_{idx}", "style": "danger"}])
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"manage_{'api' if p_type=='API Panel' else 'cpt'}_panels", "style": "primary"}])
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['trash']} <b>Select a Provider to Delete:</b>"), reply_markup={"inline_keyboard": kb})

    elif data.startswith("do_del_pnl_"):
        idx = int(data.split("_")[3])
        if 0 <= idx < len(bot_settings["panels"]):
            p_type = bot_settings["panels"][idx].get("type", "API Panel")
            del bot_settings["panels"][idx]
            save_db()
            answer_callback(call["id"], "✅ Provider Deleted!", show_alert=True)
            handle_callback({"message": {"chat": {"id": chat_id}, "message_id": msg_id}, "data": f"manage_{'api' if p_type=='API Panel' else 'cpt'}_panels", "id": "internal"})

    elif data.startswith("tog_pnl_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["panels"]):
            p = bot_settings["panels"][idx]

            p["status"] = "ON" if p["status"] == "OFF" else "OFF"
            save_db()

            if p["type"] == "Auto Captcha Panel":
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>Login Status:</b> {p.get('login_status', 'Unknown')}\n<b>Login URL:</b> <code>{p.get('login_url', 'None')}</code>\n<b>User:</b> <code>{p.get('username', 'None')}</code>"
            else:
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>"
            edit_message(chat_id, msg_id, render_body_text(text), reply_markup=panel_config_keyboard(idx))

    elif data.startswith("conf_pnl_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(bot_settings["panels"]):
            p = bot_settings["panels"][idx]
            if p["type"] == "Auto Captcha Panel":
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>Login Status:</b> {p.get('login_status', 'Unknown')}\n<b>Login URL:</b> <code>{p.get('login_url', 'None')}</code>\n<b>User:</b> <code>{p.get('username', 'None')}</code>\n<b>Num Col:</b> {p.get('num_col_name')} (Idx: {p.get('num_col_idx')})\n<b>Msg Col:</b> {p.get('msg_col_name')} (Idx: {p.get('msg_col_idx')})"
            else:
                text = f"⚙️ <b>Configure {p['name']}</b>\n\n<b>Type:</b> {p['type']}\n<b>Status:</b> {'🟢 Monitoring' if p['status'] == 'ON' else '🔴 Stopped'}\n<b>API URL:</b> <code>{p.get('api_url', 'None')}</code>\n<b>Token:</b> <code>{p.get('token', 'None')}</code>\n<b>Full API URL:</b> <code>{p.get('full_api_url', 'None')}</code>"
            edit_message(chat_id, msg_id, render_body_text(text), reply_markup=panel_config_keyboard(idx))

    elif data.startswith("set_p_api_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_api"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the API URL for this provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_tok_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_tok"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the Token for this provider:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_fapi_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_fapi"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the FULL API URL (Example: http://api.com/get?key=YOUR_TOKEN&start=0):"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("set_p_rec_"):
        idx = int(data.split("_")[3])
        user_states[chat_id] = "wait_for_p_rec"
        temp_data[chat_id] = {"msg_id": msg_id, "p_idx": idx}
        edit_message(chat_id, msg_id, render_body_text("📝 Send the number of records to fetch (e.g. 10).\nType <code>0</code> for Unlimited:"), reply_markup={"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": f"conf_pnl_{idx}", "style": "danger"}]]})

    elif data.startswith("test_p_conn_"):
        idx = int(data.split("_")[3])
        p = bot_settings["panels"][idx]
        wait_msg = send_message(chat_id, render_body_text("⏳ Testing connection. Please wait..."))
        wait_msg_id = wait_msg.get("result", {}).get("message_id") if wait_msg else None
        answer_callback(call["id"])

        try:
            parsed = []
            raw_text = ""

            if p["type"] == "Auto Captcha Panel":
                sess = panel_sessions.get(idx)
                if not sess:
                    success = attempt_auto_login(p, idx)
                    if not success:
                        if wait_msg_id: delete_message(chat_id, wait_msg_id)
                        send_message(chat_id, render_body_text(f"❌ <b>Auto Login Failed!</b>\nReason: {html.escape(str(p.get('login_status', 'Unknown')))}"))
                        return
                    sess = panel_sessions.get(idx)

                login_url = p.get("login_url", "").strip()
                if not login_url.startswith("http"): login_url = "http://" + login_url
                msg_link = p.get("msg_link", "").strip()
                if not msg_link.startswith("http") and msg_link != "": msg_link = "http://" + msg_link
                check_url = msg_link if msg_link else f"{login_url.split('/login')[0]}/client/SMSCDRStats"

                # 🌟 test connection supports sAjaxSource & HTML table parser
                parsed, raw_text = fetch_cpt_panel_cdrs(p, sess, check_url)

            else:
                full_url = p.get("full_api_url", "").strip()
                url = p.get("api_url", "").strip()
                token = p.get("token", "").strip()
                if not full_url and not url:
                    if wait_msg_id: delete_message(chat_id, wait_msg_id)
                    send_message(chat_id, render_body_text("❌ Please Set API URL or Full API URL first!"))
                    return

                urls_to_try = []
                if full_url:
                    urls_to_try.append(full_url)
                else:
                    if "{token}" in url or "{key}" in url:
                        urls_to_try.append(url.replace("{token}", token).replace("{key}", token))
                    elif "token=" in url or "key=" in url:
                        urls_to_try.append(url)
                    else:
                        sep = '&' if '?' in url else '?'
                        urls_to_try.append(f"{url}{sep}token={token}")
                        urls_to_try.append(f"{url}{sep}key={token}&start=0")
                        urls_to_try.append(f"{url}{sep}key={token}")

                parsed = []
                raw_text = ""
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                for try_url in urls_to_try:
                    try:
                        res = requests.get(try_url, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                        raw_text = res.text
                        parsed = parse_panel_response(raw_text, p)
                        if parsed:
                            if not full_url and try_url != url and token:
                                p["api_url"] = try_url.replace(token, "{token}")
                                save_db()
                            break
                    except: pass

            if wait_msg_id: delete_message(chat_id, wait_msg_id)

            if parsed:
                txt = f"✅ <b>Connection Successful!</b>\n\n🎯 <b>Parsed Data Sample (Max 3):</b>\n\n"

                for i, sample in enumerate(parsed[:3]):
                    num = sample['number']
                    msg = sample['message']
                    otp = sample['otp']

                    detected_app = detect_service(msg)
                    app_name = detected_app if detected_app else p.get("name", "Unknown")
                    app_full_name, prem_app_html = get_service_info_html(app_name, msg)

                    txt += f"<b>{i+1}.</b> {prem_app_html} <b>{app_full_name}</b>\n"
                    txt += f"📱 Number: <code>{num}</code>\n"
                    txt += f"📝 Full Msg: <code>{html.escape(msg)}</code>\n"
                    txt += f"🔐 OTP: <code>{otp}</code>\n"
                    txt += "➖" * 12 + "\n"

                send_message(chat_id, render_body_text(txt))
            else:
                if p["type"] == "Auto Captcha Panel":
                    try:
                        soup = BeautifulSoup(raw_text, 'html.parser')
                        tables = soup.find_all('table')
                        if tables:
                            full_table_data = "🔍 FULL TABLE DATA (A-Z)\n" + "="*50 + "\n\n"
                            for t_idx, table in enumerate(tables):
                                full_table_data += f"--- Table {t_idx+1} ---\n"
                                rows = table.find_all('tr')
                                for r_idx, row in enumerate(rows):
                                    cols = row.find_all(['th', 'td'])
                                    col_texts = [f"[{c_idx+1}] {c.get_text(separator=' ', strip=True)}" for c_idx, c in enumerate(cols)]
                                    full_table_data += f"Row {r_idx+1}: {' | '.join(col_texts)}\n"
                                full_table_data += "\n" + "="*50 + "\n"

                            send_document(chat_id, f"Full_Panel_Data_{idx}.txt", full_table_data.encode('utf-8'))
                            fail_txt = f"⚠️ <b>Connected, but could not parse OTP data.</b>\n\n<i>The complete data has been sent as a text file. Open it, check the correct column numbers such as [1] or [3], and update the panel settings.</i>"
                            send_message(chat_id, render_body_text(fail_txt))
                        else:
                            send_message(chat_id, render_body_text(f"⚠️ <b>Connected, but no HTML Table found!</b>\nMake sure the message link is correct."))
                    except Exception as e:
                        send_message(chat_id, render_body_text(f"❌ <b>Error parsing HTML:</b> {html.escape(str(e))}"))
                else:
                    safe_html = html.escape(str(raw_text)[:300])
                    send_message(chat_id, render_body_text(f"⚠️ <b>Connected, but couldn't find/parse OTP data.</b>\n\n<i>Make sure your API config is correct.</i>\n\nRaw HTML/Data (excerpt):\n<code>{safe_html}...</code>"))
        except Exception as e:
            if wait_msg_id: delete_message(chat_id, wait_msg_id)
            send_message(chat_id, render_body_text(f"❌ <b>Connection Failed!</b>\nError: {html.escape(str(e))}"))

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
            sanitize_withdrawal_methods_for_usd()
            save_db()
            answer_callback(call["id"], "✅ Method deleted!", show_alert=True)
            edit_message(chat_id, msg_id, render_body_text("💳 <b>WITHDRAWAL METHODS</b>\n\nManage your USD withdrawal methods below:"), reply_markup=w_methods_keyboard())

    elif data == "traffic_interval_menu":
        current = _traffic_forward_interval_seconds()
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                f"<b>OTP Group Live Traffic Interval</b>\n\n"
                f"Current interval: <b>{html.escape(_format_duration(current))}</b>\n"
                "Choose how often the last five minutes of live traffic should be forwarded to OTP Groups."
            ),
            reply_markup=traffic_interval_keyboard(),
        )

    elif data.startswith("traffic_interval:"):
        try:
            interval = int(data.split(":", 1)[1])
        except (TypeError, ValueError):
            answer_callback(call["id"], "Invalid interval", show_alert=True)
            return
        bot_settings["traffic_forward_interval"] = max(60, min(172800, interval))
        save_db()
        answer_callback(call["id"], f"Traffic interval: {_format_duration(bot_settings['traffic_forward_interval'])}", show_alert=True)
        edit_message(chat_id, msg_id, render_body_text("🕹 <b>DXA CONTROL PANEL</b>"), reply_markup=dxa_control_keyboard())

    elif data == "traffic_interval_custom":
        user_states[chat_id] = "wait_traffic_interval"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                "Send a traffic interval such as <code>60</code>, <code>5m</code>, "
                "<code>1h</code>, or <code>2h</code>. Minimum is 60 seconds."
            ),
            reply_markup=get_cancel_kb(),
        )

    elif data.startswith("dxa_"):
        key = data.replace("dxa_", "")
        key_map = {"min_w": "min_withdraw", "otp_r": "otp_reward", "ref_r": "refer_reward", "cool": "cooldown", "num_req": "num_req", "num_share": "num_share", "sup_link": "support_link", "w_group": "w_group", "brand": "brand_name"}
        if key in key_map:
            temp_data[chat_id] = {"msg_id": msg_id, "key": key_map[key]}
            user_states[chat_id] = "set_dxa"
            cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_dxa_edit", "style": "danger"}]]}

            if key_map[key] == "brand_name":
                prompt = "📝 Send the new dynamic name/brand. Example: <b>Versia SMS 🔥</b>\n\nPremium emoji will be saved too."
            else:
                prompt = f"📝 Please send the new value for <code>{key_map[key]}</code>:"
            edit_message(chat_id, msg_id, render_body_text(prompt), reply_markup=cancel_kb)
            answer_callback(call["id"])

    elif data.startswith("gsc:"):
        try:
            _, category_filter, service = data.split(":", 2)
        except ValueError:
            answer_callback(call["id"], "Invalid request", show_alert=True)
            return
        category_filter = _normalize_stock_category(category_filter)
        local_cnts = {b["country"] for b in number_batches.values() if b.get("service") == service and b.get("numbers") and _batch_category(b) == category_filter}
        route_cnts = {route.get("country") for _, route in _panel_routes(category_filter, service=service) if route.get("country")}
        stex_cnts = set()
        voltx_cnts = set()
        if category_filter == "FREE":
            stex_cnts = set(bot_settings.get("stex_services", {}).get(service, {}).keys())
            voltx_cnts = set(bot_settings.get("voltx_services", {}).get(service, {}).keys())
        all_countries = sorted(local_cnts.union(route_cnts).union(stex_cnts).union(voltx_cnts), key=lambda x: str(x).upper())
        txt = render_card_template(
            "country_menu",
            values={"service1": service, "country_count": len(all_countries)},
            trusted_html={"service": f"<b>{html.escape(str(service).upper())}</b>"},
            fallback_title=f"{str(service).upper()} COUNTRIES",
        )
        kb = []
        for c in all_countries:
            kb.append([{"text": f"{c}", "icon_custom_emoji_id": _country_icon_id(c), "callback_data": f"gcc:{category_filter}:{service}:{c}", "style": "success"}])
        if not kb:
            if category_filter == "PREMIUM":
                return show_premium_unavailable(chat_id, msg_id, back_cb="ux_premium_number")
            kb.append([{"text": "No stock available", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "ignore", "style": "danger"}])
        back_cb = "ux_premium_number" if category_filter == "PREMIUM" else "ux_free_number"
        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": back_cb, "style": "danger"}])
        edit_message(chat_id, msg_id, txt, reply_markup={"inline_keyboard": kb})

    elif data.startswith("g_s_"):
        service = data.split("g_s_")[1]
        local_cnts = set([b["country"] for b in number_batches.values() if b["service"] == service and b["numbers"]])
        stex_cnts = set(bot_settings.get("stex_services", {}).get(service, {}).keys())
        voltx_cnts = set(bot_settings.get("voltx_services", {}).get(service, {}).keys())
        all_countries = local_cnts.union(stex_cnts).union(voltx_cnts)

        c_msg = bot_settings["custom_messages"].get("select_country", {})
        txt = render_card_template(
            "country_menu",
            values={"service1": service, "country_count": len(all_countries)},
            trusted_html={"service": f"<b>{html.escape(str(service).upper())}</b>"},
            fallback_title=f"{str(service).upper()} COUNTRIES",
        )

        flags_db = bot_settings.get("premium_flags", {})
        kb = []
        for c in all_countries:
            emoji_id = "5780471598922337683" # Default flag
            for flag_code, flag_data in flags_db.items():
                iso = flag_data.get("iso", "").upper()
                name = flag_data.get("name", "").upper()
                if c.upper() == iso or c.upper() == name or c.upper() in name or name in c.upper():
                    if "id" in flag_data:
                        emoji_id = flag_data["id"]
                        break
            kb.append([{"text": f"{c}", "icon_custom_emoji_id": emoji_id, "callback_data": f"g_c_{service}_{c}", "style": "success"}])

        for b in safe_custom_buttons(c_msg.get("buttons", [])):
            b_copy = b.copy()
            if "style" not in b_copy: b_copy["style"] = "primary"
            kb.append([b_copy])

        kb.append([{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "ux_free_number", "style": "danger"}])
        edit_message(chat_id, msg_id, txt, reply_markup={"inline_keyboard": kb})

    elif data.startswith("g_c_") or data.startswith("c_n_") or data.startswith("gcc:") or data.startswith("cnc:"):
        # Provider-backed number allocation can involve one or more external
        # APIs. A callback must be acknowledged immediately; otherwise Telegram
        # keeps the button spinner visible while a provider is slow. Show a
        # progress card now and finish the allocation in a worker thread.
        if not call.get("_number_worker"):
            try:
                edit_message(chat_id, msg_id, render_body_text("⌛ <i>Processing... Finding Number...</i>"))
            except Exception:
                pass
            worker_call = dict(call)
            worker_call["_number_worker"] = True
            threading.Thread(target=_safe_handle_update, args=(handle_callback, worker_call, "number_allocation"), daemon=True).start()
            return

        # Cooldown check for number requests.
        now = time.time()
        if now - user_cooldowns.get(chat_id, 0) < bot_settings["cooldown"]:
            answer_callback(call["id"], f"⌛ Please wait {int(bot_settings['cooldown'] - (now - user_cooldowns.get(chat_id, 0)))}s.", show_alert=True)
            return

        #
        user_cooldowns[chat_id] = now

        #
        expire_previous_number(chat_id)

        category_filter = None
        if data.startswith("c_n_s_"):
            is_voltx_req = data.endswith("_vtx")
            clean_data = data[:-4] if is_voltx_req else data
            parts_s = clean_data.split("_", 4)

            query = parts_s[3] if len(parts_s) > 3 else ""
            service_from_cb = parts_s[4] if len(parts_s) > 4 else None

            allowed_countries = bot_settings.get("search_countries", [])
            voltx_allowed = bot_settings.get("voltx_search_countries", [])

            is_stex_allowed = any(query.startswith(c) for c in allowed_countries) if allowed_countries else False
            is_voltx_allowed = any(query.startswith(c) for c in voltx_allowed) if voltx_allowed else False

            if not is_voltx_req and not is_stex_allowed and not is_voltx_allowed:
                answer_callback(call["id"], "❌ This country code is not allowed for search!", show_alert=True)
                return

            edit_message(chat_id, msg_id, render_body_text("⌛ <i>Processing... Finding Number...</i>"))
            wait_msg_id = msg_id

            found_indices = []
            for b_id, b_data in number_batches.items():
                for idx, n_obj in enumerate(b_data["numbers"]):
                    if n_obj["num"].replace("+", "").startswith(query) and chat_id not in n_obj.get("used_by", []):
                        found_indices.append((b_id, idx))

            fetched_nums = []
            reward_by_num = {}
            if not found_indices:
                api_found = False
                if is_voltx_req:
                    voltx_keys = bot_settings.get("voltx_keys", [])
                    for _ in range(bot_settings.get("num_req", 1)):
                        for api_key in voltx_keys:
                            try:
                                headers = {"mauthapi": api_key}
                                payload = {"rid": query}
                                res = requests.post(f"{VOLTX_BASE_URL}/getnum", json=payload, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                                resp_data = res.json()
                                if resp_data.get("meta", {}).get("code") == 200 and resp_data.get("data"):
                                    num_str = str(resp_data["data"].get("no_plus_number", "")).replace("+", "")
                                    if not num_str: num_str = str(resp_data["data"].get("national_number", ""))
                                    fetched_nums.append(num_str)
                                    voltx_assigned_numbers[num_str] = chat_id
                                    api_found = True
                                    global total_assigned_stats
                                    total_assigned_stats += 1
                                    break
                            except: continue
                else:
                    stex_keys = bot_settings.get("stex_keys", [])
                    for _ in range(bot_settings.get("num_req", 1)):
                        for api_key in stex_keys:
                            try:
                                headers = {"mauthapi": api_key}
                                res = requests.post(f"{STEX_BASE_URL}/getnum", json={"rid": query}, headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                                resp_data = res.json()
                                if resp_data.get("meta", {}).get("code") == 200 and resp_data.get("data"):
                                    num_str = str(resp_data["data"].get("no_plus_number", "")).replace("+", "")
                                    if not num_str: num_str = str(resp_data["data"].get("national_number", ""))
                                    fetched_nums.append(num_str)
                                    stex_assigned_numbers[num_str] = chat_id
                                    api_found = True
                                    total_assigned_stats += 1
                                    break
                            except: continue

                if not api_found:
                    answer_callback(call["id"], "❌ Number out of stock!", show_alert=True)
                    delete_message(chat_id, wait_msg_id)
                    return
                save_db()
            else:
                random.shuffle(found_indices)
                for b_id, idx in found_indices:
                    if len(fetched_nums) >= bot_settings.get("num_req", 1): break
                    n_obj = number_batches[b_id]["numbers"][idx]
                    num_str = n_obj["num"]
                    fetched_nums.append(num_str)
                    reward_by_num[num_str] = batch_otp_reward(b_id)
                    n_obj["shares"] += 1
                    n_obj["used_by"].append(chat_id)
                    total_assigned_stats += 1
                    if n_obj["shares"] >= bot_settings.get("num_share", 1):
                        n_obj["to_remove"] = True
                        used_numbers_list.append(num_str)
                for b_id in number_batches:
                    number_batches[b_id]["numbers"] = [n for n in number_batches[b_id]["numbers"] if not n.get("to_remove")]
                save_db()

            vtx_ext = "_vtx" if is_voltx_req else ""
            srv_ext = f"_{service_from_cb}" if service_from_cb else ""
            ch_cntry_cb = f"g_s_{service_from_cb}" if service_from_cb else "get_number_menu"
            ch_number_cb = f"c_n_s_{query}{srv_ext}{vtx_ext}"
            card_service = service_from_cb or "NUMBER"
            card_category = "FREE"
            num_text = _number_result_text(card_service, query, card_category, fetched_nums, show_prefix=True)
            markup = _number_result_markup(card_service, query, card_category, fetched_nums, ch_cntry_cb, ch_number_cb, show_prefix=True)
            active_msg_id = _deliver_number_card(chat_id, wait_msg_id, num_text, markup, card_service, query, card_category, fetched_nums, show_prefix=True)
            if active_msg_id:
                user_active_sessions[chat_id] = _number_session_payload(active_msg_id, fetched_nums, reward_by_num, card_service, query, card_category, ch_cntry_cb, ch_number_cb, show_prefix=True)
            return

        if data.startswith("gcc:") or data.startswith("cnc:"):
            try:
                _, category_filter, service, country = data.split(":", 3)
                category_filter = _normalize_stock_category(category_filter)
            except ValueError:
                answer_callback(call["id"], "Invalid request", show_alert=True)
                return
        else:
            parts = data.split("_")
            service = parts[2]
            country = parts[3]

        effective_category = _normalize_stock_category(category_filter or "FREE")
        available_indices = []
        # Check uploaded local stock first.
        for b_id, b_data in number_batches.items():
            if b_data["service"] == service and b_data["country"] == country and _batch_category(b_data) == effective_category:
                for idx, n_obj in enumerate(b_data["numbers"]):
                    if chat_id not in n_obj.get("used_by", []):
                        available_indices.append((b_id, idx))

        panel_route_nums, panel_route_rewards, panel_route_assignments = [], {}, []
        if not available_indices:
            panel_route_nums, panel_route_rewards, panel_route_assignments = _fetch_panel_route_numbers(
                service, country, effective_category, chat_id, bot_settings.get("num_req", 1)
            )

        # If no uploaded/panel route stock, dynamic legacy API fallback is available only for FREE stock.
        if not available_indices and not panel_route_nums and effective_category == "FREE":
            stex_srv_data = bot_settings.get("stex_services", {}).get(service, {}).get(country)
            voltx_srv_data = bot_settings.get("voltx_services", {}).get(service, {}).get(country)

            target_range = None
            is_voltx = False

            if stex_srv_data and len(stex_srv_data) > 0:
                target_range = random.choice(stex_srv_data)
            elif voltx_srv_data and len(voltx_srv_data) > 0:
                target_range = random.choice(voltx_srv_data)
                is_voltx = True

            if target_range:
                user_cooldowns[chat_id] = 0
                vtx_flag = "_vtx" if is_voltx else ""
                handle_callback({"message": call["message"], "data": f"c_n_s_{target_range}_{service}{vtx_flag}", "id": call["id"]})
                return
            else:
                answer_callback(call["id"], "❌ Number out of stock or range missing!", show_alert=True)
                if data.startswith("c_n_") or data.startswith("cnc:"): delete_message(chat_id, msg_id)
                return
        elif not available_indices and not panel_route_nums:
            if effective_category == "PREMIUM":
                answer_callback(call["id"], "Premium number is not available", show_alert=True)
                return show_premium_unavailable(chat_id, msg_id, back_cb=f"gsc:PREMIUM:{service}")
            answer_callback(call["id"], "Number out of stock!", show_alert=True)
            if data.startswith("c_n_") or data.startswith("cnc:"):
                delete_message(chat_id, msg_id)
            return

        fetched_nums = []
        reward_by_num = {}
        if panel_route_nums and not available_indices:
            fetched_nums = panel_route_nums
            reward_by_num.update(panel_route_rewards)
        else:
            random.shuffle(available_indices)
        for b_id, idx in ([] if fetched_nums else available_indices):
            if len(fetched_nums) >= bot_settings["num_req"]: break
            n_obj = number_batches[b_id]["numbers"][idx]
            assigned_num = n_obj["num"]
            fetched_nums.append(assigned_num)
            reward_by_num[assigned_num] = batch_otp_reward(b_id)
            n_obj["shares"] += 1
            n_obj["used_by"].append(chat_id)
            total_assigned_stats += 1

            if n_obj["shares"] >= bot_settings.get("num_share", 1):
                n_obj["to_remove"] = True
                used_numbers_list.append(n_obj["num"])

        for b_id in number_batches:
            number_batches[b_id]["numbers"] = [n for n in number_batches[b_id]["numbers"] if not n.get("to_remove")]
        save_db()

        if not fetched_nums:
            if effective_category == "PREMIUM":
                answer_callback(call["id"], "Premium number is not available", show_alert=True)
                return show_premium_unavailable(chat_id, msg_id, back_cb=f"gsc:PREMIUM:{service}")
            answer_callback(call["id"], "You have already taken all numbers or stock is empty!", show_alert=True)
            if data.startswith("c_n_"): delete_message(chat_id, msg_id)
            return

        app_full_name, prem_app_html_loc = get_service_info_html(service)
        emoji_id = "5337302974806922068"
        apps_db = bot_settings.get("premium_apps", {})
        for app_key, app_data in apps_db.items():
            if service.upper() == app_key or service.upper() in app_key or app_key in service.upper():
                if "id" in app_data:
                    emoji_id = app_data["id"]
                    break

        ch_country_cb = f"gsc:{effective_category}:{service}" if effective_category else f"g_s_{service}"
        ch_number_cb = f"cnc:{effective_category}:{service}:{country}" if effective_category else f"c_n_{service}_{country}"
        text_numbers = _number_result_text(service, country, effective_category, fetched_nums, show_prefix=True)
        markup = _number_result_markup(service, country, effective_category, fetched_nums, ch_country_cb, ch_number_cb, show_prefix=True)
        active_msg_id = _deliver_number_card(chat_id, msg_id, text_numbers, markup, service, country, effective_category, fetched_nums, show_prefix=True)
        if active_msg_id:
            user_active_sessions[chat_id] = _number_session_payload(active_msg_id, fetched_nums, reward_by_num, service, country, effective_category, ch_country_cb, ch_number_cb, show_prefix=True)

    elif data.startswith("wapp_") or data.startswith("wrej_"):
        #   (User ID   )
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
            new_text = f"🎙 <b>WITHDRAWAL {status_text}</b>\n\n👤 <b>USER:</b> <a href='tg://user?id={u_id}'>{full_name}</a>\n💳 <b>WITHDRAWAL:</b> {amt} USD\n🍏 <b>PAYOUT DETAILS:</b> <code>{masked_num}</code>\n🏦 <b>METHOD:</b> {req_data['method']}\n\n🧾 <b>REQ ID:</b> {req_id}\n👨‍⚖️ <b>PROCESSED BY ADMIN</b>"

            kb = {"inline_keyboard": [[{"text": status_text, "icon_custom_emoji_id": emoji_icon_id, "callback_data": "ignore", "style": "success" if action == "APPROVE" else "danger"}]]}
            edit_message(chat_id, msg_id, render_body_text(new_text), reply_markup=kb)

            if action == "REJECT":
                update_balance(u_id, amt)
                send_message(u_id, render_body_text(f"❌ Your {amt} USD withdrawal request was rejected. Balance refunded."))
            else:
                send_message(u_id, render_body_text(f"{PEM['ok']} Your {amt} USD withdrawal request has been paid successfully!"))

            if db:
                try: db.collection('withdrawals').document(req_id).update({"status": "approved" if action == "APPROVE" else "rejected"})
                except: pass

            del pending_withdrawals[req_id]
        else:
            answer_callback(call["id"], "❌ Request already processed!", show_alert=True)

# ==========================================
# Polling Loop
# ==========================================
#==============================================================================
#  [38]  OTP POLLING & PROVIDER SMS LISTENERS
#==============================================================================
def poll_otp_with_status(number_id, num_str, owner_id, api_key):
    headers = {"X-API-Key": api_key}
    for _ in range(150): # 150 * 4 seconds = 10 Minutes Polling
        try:
            res = requests.get(f"{STEX_BASE_URL}/api/v1/numbers/{number_id}/sms", headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
            data = res.json()
            if data.get("success") and data.get("otp"):
                otp = str(data["otp"])
                msg_text = data.get("message", f"Your code is {otp}")

                # 🌟       OTP
                extracted_otp = extract_otp_code(msg_text)
                if extracted_otp and len(extracted_otp) > len(otp):
                    otp = extracted_otp

                # 🌟    /
                app_name = data.get("service", "StexSMS Service")
                detected_app = detect_service(msg_text)
                if detected_app:
                    app_name = detected_app

                unique_id = f"POLL_{number_id}_{otp}"
                if unique_id not in processed_otps:
                    processed_otps.add(unique_id)

                    char, iso = get_flag_and_code(num_str)
                    app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)

                    global recent_traffic
                    current_time = time.time()
                    if _number_has_get_number_owner(num_str):
                        recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS]
                        recent_traffic.append({"source": "GET NUMBER", "service": app_full_name, "iso": iso, "flag": char, "number": num_str, "time": current_time})
                        save_local_db()

                    display_num = f"+{num_str}" if not str(num_str).startswith("+") else str(num_str)
                    masked = mask_number(display_num)
                    lang = detect_language(msg_text)

                    _forward_otp_to_groups(app_name, display_num, otp, lang, msg_text)

                    inbox_kb = _otp_copy_markup(display_num, otp)

                    reward = reward_for_session_number(owner_id, display_num)
                    if reward > 0:
                        update_balance(owner_id, reward)
                        inbox_kb.append([{"text": f"Added {reward} USD", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                    _send_otp_inbox(
                        owner_id, display_num, otp, lang, msg_text,
                        reward=f"{float(reward or 0):g} USD",
                        markup={"inline_keyboard": inbox_kb},
                    )

                    if db:
                        try: db.collection('users').document(str(owner_id)).update({"total_otps": firestore.Increment(1)})
                        except: pass
                break
        except: pass
        time.sleep(4)

def voltx_sms_listener():
    global processed_otps, recent_traffic, voltx_assigned_numbers
    while True:
        try:
            voltx_keys = bot_settings.get("voltx_keys", [])
            for api_key in voltx_keys:
                try:
                    headers = {"mauthapi": api_key}
                    res = requests.get(f"{VOLTX_BASE_URL}/success-otp", headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                    resp_data = res.json()

                    if resp_data.get("meta", {}).get("code") == 200 and "data" in resp_data and "otps" in resp_data["data"]:
                        for item in resp_data["data"]["otps"]:
                            num = str(item.get("number", "")).replace("+", "")
                            msg_text = str(item.get("message", ""))
                            otp = extract_otp_code(msg_text) or "CODE"
                            otp_id = str(item.get("otp_id", otp))

                            app_name = "Voltx Service"
                            detected_app = detect_service(msg_text)
                            if detected_app: app_name = detected_app

                            unique_id = f"VOLTX_{num}_{otp_id}"

                            if unique_id not in processed_otps and num:
                                processed_otps.add(unique_id)
                                if len(processed_otps) > 5000: processed_otps.clear()

                                char, iso = get_flag_and_code(num)
                                app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                                current_time = time.time()

                                if _number_has_get_number_owner(num):
                                    recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS]
                                    recent_traffic.append({"source": "GET NUMBER", "service": app_full_name, "iso": iso, "flag": char, "number": num, "time": current_time})
                                    save_local_db()

                                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                                masked = mask_number(display_num)
                                lang = detect_language(msg_text)

                                _forward_otp_to_groups(app_name, display_num, otp, lang, msg_text)

                                owner_id = None
                                clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()

                                for uid, session_data in user_active_sessions.items():
                                    for act_num in session_data.get("nums", []):
                                        act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                            owner_id = uid
                                            break
                                    if owner_id: break

                                if not owner_id:
                                    for vtx_n, n_owner in voltx_assigned_numbers.items():
                                        clean_vtx = str(vtx_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if clean_vtx == clean_api_num or (len(clean_vtx) >= 8 and clean_vtx.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_vtx[-8:])):
                                            owner_id = n_owner
                                            break
                                if not owner_id:
                                    fb_owners = _find_fb_tool_owners(clean_api_num)
                                    if fb_owners:
                                        owner_id = fb_owners[0]

                                if owner_id:
                                    inbox_kb = _otp_copy_markup(display_num, otp)

                                    reward = reward_for_session_number(owner_id, display_num)
                                    if reward > 0:
                                        update_balance(owner_id, reward)
                                        inbox_kb.append([{"text": f"Added {reward} USD", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                        _send_otp_inbox(
                                        owner_id, display_num, otp, lang, msg_text,
                                        reward=f"{float(reward or 0):g} USD",
                                        markup={"inline_keyboard": inbox_kb},
                                    )

                                    if db:
                                        try: db.collection('users').document(str(owner_id)).update({"total_otps": firestore.Increment(1)})
                                        except: pass
                except: pass
        except: pass
        time.sleep(OTP_POLL_INTERVAL)

def global_sms_listener():
    global processed_otps, recent_traffic, stex_assigned_numbers
    while True:
        try:
            stex_keys = bot_settings.get("stex_keys", [])
            for api_key in stex_keys:
                try:
                    headers = {"mauthapi": api_key}
                    res = requests.get(f"{STEX_BASE_URL}/success-otp", headers=headers, timeout=FAST_PROVIDER_TIMEOUT)
                    resp_data = res.json()

                    if resp_data.get("meta", {}).get("code") == 200 and "data" in resp_data and "otps" in resp_data["data"]:
                        for item in resp_data["data"]["otps"]:
                            num = str(item.get("number", "")).replace("+", "")
                            msg_text = str(item.get("message", ""))
                            otp = extract_otp_code(msg_text) or "CODE"
                            otp_id = str(item.get("otp_id", otp))

                            app_name = "Stex Service"
                            detected_app = detect_service(msg_text)
                            if detected_app: app_name = detected_app

                            unique_id = f"STEX_{num}_{otp_id}"

                            if unique_id not in processed_otps and num:
                                processed_otps.add(unique_id)
                                if len(processed_otps) > 5000: processed_otps.clear()

                                char, iso = get_flag_and_code(num)
                                app_full_name, prem_app_html = get_service_info_html(app_name, msg_text)
                                current_time = time.time()

                                if _number_has_get_number_owner(num):
                                    recent_traffic = [t for t in recent_traffic if current_time - t.get("time", 0) <= TRAFFIC_WINDOW_SECONDS]
                                    recent_traffic.append({"source": "GET NUMBER", "service": app_full_name, "iso": iso, "flag": char, "number": num, "time": current_time})
                                    save_local_db()

                                display_num = f"+{num}" if not str(num).startswith("+") else str(num)
                                masked = mask_number(display_num)
                                lang = detect_language(msg_text)

                                _forward_otp_to_groups(app_name, display_num, otp, lang, msg_text)

                                owner_id = None
                                clean_api_num = str(num).replace("+", "").replace(" ", "").replace("-", "").strip()

                                for uid, session_data in user_active_sessions.items():
                                    for act_num in session_data.get("nums", []):
                                        act_clean = str(act_num).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if act_clean == clean_api_num or (len(act_clean) >= 8 and act_clean.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(act_clean[-8:])):
                                            owner_id = uid
                                            break
                                    if owner_id: break

                                if not owner_id:
                                    for stex_n, n_owner in stex_assigned_numbers.items():
                                        clean_stex = str(stex_n).replace("+", "").replace(" ", "").replace("-", "").strip()
                                        if clean_stex == clean_api_num or (len(clean_stex) >= 8 and clean_stex.endswith(clean_api_num[-8:])) or (len(clean_api_num) >= 8 and clean_api_num.endswith(clean_stex[-8:])):
                                            owner_id = n_owner
                                            break
                                if not owner_id:
                                    fb_owners = _find_fb_tool_owners(clean_api_num)
                                    if fb_owners:
                                        owner_id = fb_owners[0]

                                if owner_id:
                                    inbox_kb = _otp_copy_markup(display_num, otp)

                                    reward = reward_for_session_number(owner_id, display_num)
                                    if reward > 0:
                                        update_balance(owner_id, reward)
                                        inbox_kb.append([{"text": f"Added {reward} USD", "icon_custom_emoji_id": "5420396762189831222", "callback_data": "ignore", "style": "primary"}])
                                    _send_otp_inbox(
                                        owner_id, app_name, display_num, otp, lang, msg_text,
                                        reward=f"{float(reward or 0):g} USD",
                                        markup={"inline_keyboard": inbox_kb},
                                    )

                                    if db:
                                        try: db.collection('users').document(str(owner_id)).update({"total_otps": firestore.Increment(1)})
                                        except: pass
                except: pass
        except: pass
        time.sleep(OTP_POLL_INTERVAL)


# ==========================================
# API NUMBER + MK ONLINE SMS CONTROL
# ==========================================
# The existing DXnumbers flow remains unchanged. The old "Search Number"
# button is replaced in the menu by "API Number". API Number uses only
# authorized providers configured by the owner and the provider contract:
#   GET  {base_url}/api/liveaccess
#   POST {base_url}/api/getnum
#   GET  {base_url}/api/success-otp-info

API_RANGE_FILE = "api_ranges.json"
MK_PANEL_FILE = "mk_api_panels.json"
API_SESSION_TIMEOUT = 3600
api_range_lock = threading.RLock()
api_session_lock = threading.RLock()
api_number_sessions = {}
api_range_cache = {}
api_seen_otps = set()
mk_panel_http = requests.Session()


#==============================================================================
#  [39]  MK / NP API PROVIDER LAYER (V1)
#==============================================================================
def _safe_panel_id(value):
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip()).strip("-")
    return (clean[:30] or "mk-panel")


def _normalise_mk_panel(raw, index=0):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or f"API Panel {index + 1}").strip()[:60]
    base_url = str(raw.get("base_url") or raw.get("url") or "").strip().rstrip("/")
    api_key = str(raw.get("api_key") or raw.get("token") or "").strip()
    if not base_url:
        return None
    protocol = str(raw.get("protocol") or raw.get("type") or "").strip().lower()
    if protocol not in {"mk", "npnetwork"}:
        protocol = "npnetwork" if ("npsmsnetwork" in base_url.lower() or "route=user" in base_url.lower()) else "mk"
    routes = []
    raw_routes = raw.get("routes", []) if isinstance(raw.get("routes", []), list) else []
    for route in raw_routes:
        if not isinstance(route, dict):
            continue
        service = str(route.get("service") or "").strip().upper()
        country = str(route.get("country") or "").strip().upper()
        ranges = _route_ranges(route)
        category = _normalize_stock_category(route.get("category", "FREE"))
        try:
            otp_reward = float(route.get("otp_reward", bot_settings.get("otp_reward", 0.0)))
            if otp_reward < 0:
                otp_reward = float(bot_settings.get("otp_reward", 0.0) or 0.0)
        except Exception:
            otp_reward = float(bot_settings.get("otp_reward", 0.0) or 0.0)
        if service and country and ranges:
            routes.append({
                "service": service,
                "country": country,
                "ranges": list(dict.fromkeys(ranges)),
                "category": category,
                "otp_reward": otp_reward,
            })
    return {
        "id": _safe_panel_id(raw.get("id") or name),
        "name": name,
        "base_url": base_url,
        "api_key": api_key,
        "protocol": protocol,
        "enabled": bool(raw.get("enabled", True)),
        "routes": routes,
        "created_at": raw.get("created_at") or datetime.now().isoformat(),
    }


def _save_mk_panels(panels):
    cleaned, seen = [], set()
    for i, raw in enumerate(panels or []):
        p = _normalise_mk_panel(raw, i)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            cleaned.append(p)
    temp = MK_PANEL_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    os.replace(temp, MK_PANEL_FILE)
    try:
        os.chmod(MK_PANEL_FILE, 0o600)
    except OSError:
        pass


def _load_mk_panels():
    if not os.path.exists(MK_PANEL_FILE):
        # Optional migration from environment variables. No credentials are
        # included in source code.
        panels = []
        env_base = os.environ.get("MK_API_BASE_URL", "").strip().rstrip("/")
        env_key = os.environ.get("MK_API_KEY", "").strip()
        if env_base:
            panels.append({"id": "mk-primary", "name": "MK Primary", "base_url": env_base, "api_key": env_key, "protocol": "mk", "enabled": True})
        np_base = os.environ.get("NP_API_BASE_URL", "").strip().rstrip("/")
        np_key = os.environ.get("NP_API_KEY", "").strip()
        if np_base:
            panels.append({"id": "np-primary", "name": "NP Primary", "base_url": np_base, "api_key": np_key, "protocol": "npnetwork", "enabled": True})
        _save_mk_panels(panels)
        return panels
    try:
        with open(MK_PANEL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [_normalise_mk_panel(x, i) for i, x in enumerate(data or []) if _normalise_mk_panel(x, i)]
    except Exception as e:
        print(f"[MK panels] load error: {e}")
        return []


def _mk_panels(enabled_only=False):
    panels = _load_mk_panels()
    return [p for p in panels if p["enabled"]] if enabled_only else panels


def _mk_panel(panel_id):
    return next((p for p in _mk_panels() if p["id"] == str(panel_id)), None)


def _mk_headers(panel):
    headers = {"Accept": "application/json"}
    if panel.get("api_key"):
        if panel.get("protocol") == "npnetwork":
            headers["mauthapi"] = panel["api_key"]
        else:
            headers["X-API-Key"] = panel["api_key"]
    return headers


def _mk_endpoint(panel, path):
    base = panel["base_url"].rstrip("/")
    clean_path = "/" + path.lstrip("/")
    # Accept either a site root or a base URL that already ends in /api.
    if base.lower().endswith("/api") and clean_path.lower().startswith("/api/"):
        clean_path = clean_path[4:]
    return f"{base}{clean_path}"


def _np_user_endpoint(panel, action=None):
    """Build the NP Network user API URL from root, /api, or route=user input."""
    base = str(panel.get("base_url", "")).strip().rstrip("/")
    lower = base.lower()
    if "route=user" in lower:
        endpoint = base
        separator = "&" if "?" in endpoint else "?"
    elif re.search(r"/api/(?:index\.php|user)$", lower):
        endpoint = base
        separator = "&" if "?" in endpoint else "?"
    elif lower.endswith("/api"):
        endpoint = f"{base}/index.php?route=user"
        separator = "&"
    else:
        endpoint = f"{base}/api/index.php?route=user"
        separator = "&"
    if action:
        return f"{endpoint}{separator}action={action}"
    return endpoint


def _api_liveaccess_services(payload):
    """Accept MK and NP Network liveaccess response shapes."""
    if not isinstance(payload, dict):
        return []
    candidates = []
    if isinstance(payload.get("services"), list):
        candidates.append(payload["services"])
    if isinstance(payload.get("result"), dict) and isinstance(payload["result"].get("services"), list):
        candidates.append(payload["result"]["services"])
    if isinstance(payload.get("liveaccess"), list):
        candidates.append(payload["liveaccess"])
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("services"), list):
        candidates.append(data["services"])
    if isinstance(data, dict) and isinstance(data.get("liveaccess"), list):
        candidates.append(data["liveaccess"])
    if isinstance(data, list):
        candidates.append(data)
    for services in candidates:
        result = []
        for service in services:
            if not isinstance(service, dict):
                continue
            ranges = service.get("ranges")
            if ranges is None and service.get("range") is not None:
                ranges = [service.get("range")]
            result.append({**service, "ranges": [str(x) for x in (ranges or []) if str(x).strip()]})
        if result:
            return result
    return []


_PANEL_NUMBER_KEYS = (
    "full_number", "number", "phone", "phone_number", "msisdn", "mobile",
    "no_plus_number", "national_number", "num", "no", "receiver", "to"
)


def _number_from_text(value):
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    patterns = [
        r"(?:number|phone|msisdn|mobile|num|no)\D{0,12}(\+?\d[\d\s().-]{7,20}\d)",
        r"(\+?\d[\d\s().-]{7,20}\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if 8 <= len(digits) <= 18:
                return digits
    digits = re.sub(r"\D", "", raw)
    if 8 <= len(digits) <= 18 and (raw.startswith("+") or raw.replace(".", "").isdigit()):
        return digits
    return ""


def _extract_panel_number(payload):
    """Extract a phone number from common MK/NP response envelopes."""
    if isinstance(payload, dict):
        for key in _PANEL_NUMBER_KEYS:
            found = _number_from_text(payload.get(key))
            if found:
                return found
        for value in payload.values():
            found = _extract_panel_number(value)
            if found:
                return found
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found = _extract_panel_number(value)
            if found:
                return found
    elif isinstance(payload, (str, int, float)):
        return _number_from_text(payload)
    return ""


def _numbers_match(first, second):
    left = re.sub(r"\D", "", str(first or ""))
    right = re.sub(r"\D", "", str(second or ""))
    if left.startswith("00"):
        left = left[2:]
    if right.startswith("00"):
        right = right[2:]
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 8 and longer.endswith(shorter)


def _api_otp_items(payload):
    """Accept common MK/NP OTP response envelopes."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    if any(payload.get(key) is not None for key in _PANEL_NUMBER_KEYS) and any(payload.get(key) is not None for key in ("message", "otp", "sms", "code", "text")):
        return [payload]
    for key in ("otps", "sms", "messages", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    for key in ("data", "result", "response"):
        found = _api_otp_items(payload.get(key))
        if found:
            return found
    return []


def _mk_json_get(panel, path):
    try:
        if panel.get("protocol") == "npnetwork":
            action = {
                "liveaccess": "liveaccess",
                "success-otp-info": "otp",
                "otp": "otp",
                "console": "console",
            }.get(str(path).strip("/").split("/")[-1].lower())
            endpoint = _np_user_endpoint(panel, action)
        else:
            endpoint = _mk_endpoint(panel, path)
        res = mk_panel_http.get(endpoint, headers=_mk_headers(panel), timeout=FAST_PROVIDER_TIMEOUT)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[{panel.get('protocol', 'mk').upper()}:{panel.get('name')}] GET error: {type(e).__name__}")
        return None


def _mk_json_post(panel, path, payload):
    try:
        request_payload = dict(payload or {})
        if panel.get("protocol") == "npnetwork":
            endpoint = _np_user_endpoint(panel)
            request_payload = {"action": "getnum", "range": str(request_payload.get("range", ""))}
        else:
            endpoint = _mk_endpoint(panel, path)
        res = mk_panel_http.post(endpoint, headers=_mk_headers(panel), json=request_payload, timeout=FAST_PROVIDER_TIMEOUT)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[{panel.get('protocol', 'mk').upper()}:{panel.get('name')}] POST error: {type(e).__name__}")
        return None


def _load_api_ranges():
    if not os.path.exists(API_RANGE_FILE):
        return {}
    try:
        with open(API_RANGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[API ranges] load error: {e}")
        return {}


def _save_api_ranges(data):
    temp = API_RANGE_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp, API_RANGE_FILE)
    try:
        os.chmod(API_RANGE_FILE, 0o600)
    except OSError:
        pass


def _get_user_api_ranges(user_id):
    """Return only the user's latest saved range.

    Firestore is the primary store; the local file remains a fallback for
    deployments that are intentionally running without Firebase.
    """
    with api_range_lock:
        if db:
            try:
                doc = db.collection("users").document(str(user_id)).get()
                latest = doc.to_dict().get("api_last_range") if doc.exists else None
                if isinstance(latest, dict) and latest.get("range"):
                    return [latest]
            except Exception as e:
                print(f"[API ranges] Firestore read error: {type(e).__name__}")
        data = _load_api_ranges()
        values = data.get(str(user_id), [])
        if isinstance(values, list) and values:
            return [values[-1]]
        return []


def _add_user_api_range(user_id, range_text, panel):
    with api_range_lock:
        data = _load_api_ranges()
        key = str(user_id)
        existing = data.get(key, [])
        if not isinstance(existing, list):
            existing = []
        if not any(str(x.get("range", "")).upper() == str(range_text).upper() and x.get("panel_id") == panel["id"] for x in existing if isinstance(x, dict)):
            existing.append({
                "range": str(range_text).upper(),
                "panel_id": panel["id"],
                "panel_name": panel["name"],
                "saved_at": datetime.now().isoformat(),
            })
        data[key] = existing
        _save_api_ranges(data)
        return existing


def _range_is_listed(panel, range_text):
    """Validate a range without allocating/consuming a phone number."""
    wanted = re.sub(r"\s+", "", str(range_text).upper())
    for route in panel.get("routes", []) or []:
        if any(re.sub(r"\s+", "", str(candidate).upper()) == wanted for candidate in _route_ranges(route)):
            return True
    data = _mk_json_get(panel, "/api/liveaccess") or {}
    services = _api_liveaccess_services(data)
    for service in services:
        for candidate in service.get("ranges", []) or []:
            if re.sub(r"\s+", "", str(candidate).upper()) == wanted:
                return True
    return False


def _find_panel_for_range(range_text):
    for panel in _mk_panels(enabled_only=True):
        if _range_is_listed(panel, range_text):
            return panel
    return None


def _mk_get_number(panel, range_text):
    data = _mk_json_post(panel, "/api/getnum", {"range": str(range_text), "is_national": False}) or {}
    number = _extract_panel_number(data)
    if not number:
        return None
    body = data.get("data", {}) if isinstance(data, dict) else {}
    if not isinstance(body, dict):
        body = data if isinstance(data, dict) else {}
    return {
        "number": number,
        "otp_now": bool(body.get("otp_now", False)) if isinstance(body, dict) else False,
        "otp": body.get("otp") if isinstance(body, dict) else None,
        "sms": body.get("sms") if isinstance(body, dict) else None,
        "panel_id": panel["id"],
        "panel_name": panel["name"],
        "range": str(range_text),
    }


def _api_number_keyboard():
    """Persistent API reply keyboard; it changes only when MAIN MENU is pressed."""
    return {"keyboard": [
        [{"text": "SAVE RANGE", "icon_custom_emoji_id": "5192739271886282680"}, {"text": "API NUMBER", "icon_custom_emoji_id": "5337132498965010628"}],
        [{"text": "MAIN MENU", "icon_custom_emoji_id": "5353027129250453493"}],
    ], "resize_keyboard": True, "one_time_keyboard": False}


def _api_cancel_keyboard():
    return {"keyboard": [[{"text": "CANCEL", "icon_custom_emoji_id": "5420130255174145507"}]], "resize_keyboard": True, "one_time_keyboard": False}


def _api_cancel_inline_keyboard():
    return {"inline_keyboard": [[
        {"text": "CANCEL", "icon_custom_emoji_id": "5420130255174145507", "callback_data": "api_cancel_range", "style": "danger"}
    ]]}


def _api_result_inline_keyboard(link=""):
    """Attach exactly two result buttons; configured OTP link opens directly."""
    link = str(link or "").strip()
    # A Telegram URL button opens the configured group immediately. There is
    # no callback/message hop when the admin has configured OTP_GROUP_LINK or
    # the Admin Panel OTP Group link.
    otp_button = {"text": "OTP GROUP", "icon_custom_emoji_id": "5190447043545438788", "callback_data": "api_open_group", "style": "primary"}
    if link:
        otp_button = {"text": "OTP GROUP", "icon_custom_emoji_id": "5190447043545438788", "url": link, "style": "primary"}
    return {"inline_keyboard": [[
        otp_button,
        {"text": "CHANGE NUMBER", "icon_custom_emoji_id": "5465368548702446780", "callback_data": "api_change_number", "style": "danger"},
    ]]}


def _show_api_number_menu(chat_id, message_id=None):
    saved = _get_user_api_ranges(chat_id)
    latest = saved[-1].get("range", "") if saved and isinstance(saved[-1], dict) else ""
    text = (
        "📞 <b>API NUMBER</b>\n\n"
        "💾 SAVE RANGE — save your latest authorized range.\n"
        "📞 API NUMBER — choose a matched provider for your saved range.\n\n"
        f"📋 LAST SAVED RANGE: <code>{html.escape(latest or 'Not saved')}</code>"
    )
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text))
    send_message(chat_id, render_body_text(text), reply_markup=_api_number_keyboard())


def _show_api_provider_menu(chat_id, message_id=None):
    """Show matching providers with a bottom reply keyboard."""
    saved = _get_user_api_ranges(chat_id)
    latest = saved[-1] if saved and isinstance(saved[-1], dict) else None
    range_text = str(latest.get("range", "")).upper() if latest else ""
    if not range_text:
        user_states.pop(chat_id, None)
        text = "⚠️ Save a valid range first from SAVE RANGE."
        markup = _api_number_keyboard()
    else:
        matches = _find_matching_mk_panels(range_text)
        if matches:
            user_states[chat_id] = "api_choose_provider"
            text = (
                "🔹 <b>PLEASE SELECT PROVIDER</b>\n\n"
                f"📋 RANGE: <code>{html.escape(range_text)}</code>\n"
                "Click a provider button below; two numbers will be fetched from the selected provider."
            )
            rows = [[{
                "text": f"🛰 {panel['name']}",
                "callback_data": f"api_provider:{panel['id']}",
                "style": "primary",
            }] for panel in matches]
            markup = {"inline_keyboard": rows}
        else:
            user_states.pop(chat_id, None)
            text = (
                "❌ No enabled API provider live range matches the saved range.\n\n"
                f"RANGE: <code>{html.escape(range_text)}</code>"
            )
            markup = None
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=markup)
    else:
        send_message(chat_id, render_body_text(text), reply_markup=markup)


def _api_number_result_text(items):
    lines = []
    for item in items:
        flag_html = get_flag_info_html(item["number"])
        lines.append(f"{flag_html} <code>+{item['number']}</code>")
    return (
        f"{brand_header()}📞 <b>API NUMBERS</b>\n\n"
        "🛰 <b>MK ONLINE SMS</b>\n" + "\n".join(lines) +
        f"\n\n✅ {len(items)} number(s) fetched from your saved range."
    )


def _api_number_action(chat_id, message_id=None, preferred=None):
    saved = _get_user_api_ranges(chat_id)
    if not saved:
        _show_api_number_menu(chat_id, message_id)
        send_message(chat_id, render_body_text("⚠️ Save at least one valid range from SAVE API RANGE first."))
        return
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(x for x in saved if x not in candidates)
    fetched = []
    chosen = None
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        panel = _mk_panel(entry.get("panel_id"))
        if not panel or not panel["enabled"]:
            continue
        chosen = (entry, panel)
        for _ in range(2 - len(fetched)):
            item = _mk_get_number(panel, entry.get("range", ""))
            if item and item["number"] not in {x["number"] for x in fetched}:
                fetched.append(item)
        if len(fetched) >= 2:
            break
    if not fetched:
        msg = "❌ No number is currently available for the saved range."
        if message_id:
            edit_message(chat_id, message_id, render_body_text(msg), reply_markup=_api_number_keyboard())
        else:
            send_message(chat_id, render_body_text(msg), reply_markup=_api_number_keyboard())
        return
    if chosen:
        entry, panel = chosen
        session = {
            "user_id": chat_id,
            "range": entry.get("range", ""),
            "panel_id": panel["id"],
            "panel_name": panel["name"],
            "numbers": [x["number"] for x in fetched],
            "created": time.time(),
        }
        with api_session_lock:
            api_number_sessions[chat_id] = session
    text = _api_number_result_text(fetched)
    result_markup = _api_result_inline_keyboard(bot_settings.get("otp_link", ""))
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=result_markup)
    else:
        send_message(chat_id, render_body_text(text), reply_markup=result_markup)


def _api_monitor_thread():
    while True:
        try:
            now = time.time()
            with api_session_lock:
                for uid in list(api_number_sessions):
                    session_expiry = float(api_number_sessions[uid].get("expires_at") or (api_number_sessions[uid].get("created", now) + API_SESSION_TIMEOUT))
                    if now > session_expiry:
                        del api_number_sessions[uid]
                sessions = list(api_number_sessions.values()) + _fb_api_sessions()
            for panel in _mk_panels(enabled_only=True):
                owners = [s for s in sessions if s.get("panel_id") == panel["id"]]
                if not owners:
                    continue
                data = _mk_json_get(panel, "/api/success-otp-info") or {}
                items = data.get("data", {}).get("otps", []) if isinstance(data, dict) else []
                for item in items:
                    number = re.sub(r"\D", "", str(item.get("number", "")))
                    owner_session = next((s for s in owners if number in s.get("numbers", [])), None)
                    if not owner_session:
                        continue
                    sms = item.get("message") or item.get("otp") or item.get("sms") or "No Content"
                    code = extract_otp_code(str(sms)) or "N/A"
                    otp_id = str(item.get("otp_id") or f"{number}_{code}")
                    unique = f"{panel['id']}::{number}::{otp_id}"
                    if unique in api_seen_otps:
                        continue
                    api_seen_otps.add(unique)
                    if len(api_seen_otps) > 10000:
                        api_seen_otps.clear()
                    reward = float(bot_settings.get("otp_reward", 0.0))
                    if reward > 0:
                        update_balance(owner_session["user_id"], reward)
                    send_message(owner_session["user_id"], render_body_text(
                        f"{brand_header()}✅ <b>API OTP RECEIVED</b>\n\n🛰 PANEL: {html.escape(panel['name'])}\n"
                        f"📞 <code>+{number}</code>\n🔑 <code>{html.escape(str(code))}</code>\n\n"
                        f"<blockquote>📩 {html.escape(str(sms))}</blockquote>\n\n"
                        f"💵 ADDED: {reward:.2f} USD"
                    ), reply_markup=main_menu(owner_session["user_id"]))
        except Exception as e:
            print(f"[API Number] monitor error: {e}")
        time.sleep(max(3, int(os.environ.get("MK_CHECK_INTERVAL", "5"))))


# Final user reply keyboard: Versia-style menu, premium/custom emoji icons only.
#==============================================================================
#  [40]  PATCH LAYER — V2 WRAPPERS (intentionally override earlier defs)
#==============================================================================
_original_dx_main_menu = main_menu

def main_menu(user_id):
    return user_main_menu(user_id)


# Add an MK provider-management shortcut to the existing System Settings menu.
_original_system_settings_keyboard = system_settings_keyboard

def system_settings_keyboard():
    markup = _original_system_settings_keyboard()
    rows = markup.get("inline_keyboard", [])
    rows.insert(0, [{"text": "API PANEL CONTROL (MK / NP)", "icon_custom_emoji_id": "5336879280578138635", "callback_data": "mk_manage_panels", "style": "primary"}])
    rows.insert(1, [{"text": "PREMIUM USER CONTROL", "icon_custom_emoji_id": "5418291565864647309", "callback_data": "premium_manage", "style": "primary"}])
    rows.insert(2, [{"text": "FACEBOOK TOOLS CONTROL", "icon_custom_emoji_id": "5334807341109908955", "callback_data": "fb_admin", "style": "success"}])
    return markup


def _premium_admin_keyboard():
    rows = [
        [{"text": "ADD PREMIUM USER", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "premium_add", "style": "success"}],
        [{"text": "SET PREMIUM SUPPORT", "icon_custom_emoji_id": "5337302974806922068", "callback_data": "premium_support", "style": "primary"}],
        [{"text": "PREMIUM NUMBER REQUESTS", "icon_custom_emoji_id": "5352838545826420397", "callback_data": "premium_number_requests", "style": "success"}],
    ]
    for uid, rec in sorted(_premium_users_store().items(), key=lambda x: str(x[0])):
        days_left = premium_days_left(uid)
        rows.append([{
            "text": f"REMOVE {uid} ({days_left}d)",
            "icon_custom_emoji_id": "5422557736330106570",
            "callback_data": f"premium_remove:{uid}",
            "style": "danger",
        }])
    rows.append([{"text": "BACK TO SYSTEM", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "mks_back", "style": "primary"}])
    return {"inline_keyboard": rows}


def _show_premium_admin(chat_id, message_id=None):
    cleanup_expired_premium_users()
    active_count = len(_premium_users_store())
    support_link = str(bot_settings.get("premium_support_link") or bot_settings.get("support_link") or "Not set")
    text = render_body_text(
        "🔐 <b>PREMIUM USER CONTROL</b>\n\n"
        f"Active premium users: <b>{active_count}</b>\n"
        f"Support link: <code>{html.escape(support_link)}</code>\n\n"
        "Add users with a fixed number of days. Expired users are removed automatically and notified in English."
    )
    if message_id:
        edit_message(chat_id, message_id, text, reply_markup=_premium_admin_keyboard())
    else:
        send_message(chat_id, text, reply_markup=_premium_admin_keyboard())


def _batch_result_markup(service, country, category, batch_id, fetched_nums, show_prefix=True):
    return _number_result_markup(
        service,
        country,
        category,
        fetched_nums,
        f"gsc:{category}:{service}",
        f"batch_get:{batch_id}",
        show_prefix=show_prefix,
    )


def _allocate_from_uploaded_batch(chat_id, msg_id, batch_id, call_id=None):
    global total_assigned_stats
    batch = number_batches.get(str(batch_id))
    if not batch or not batch.get("numbers"):
        if batch and _batch_category(batch) == "PREMIUM":
            if call_id:
                answer_callback(call_id, "Premium number is not available", show_alert=True)
            return show_premium_unavailable(chat_id, msg_id, back_cb="ux_premium_number")
        if call_id:
            answer_callback(call_id, "Number out of stock", show_alert=True)
        return send_message(chat_id, render_body_text("Number out of stock."), reply_markup=main_menu(chat_id))
    category = _batch_category(batch)
    if category == "PREMIUM" and not is_premium_user(chat_id):
        if call_id:
            answer_callback(call_id, "Premium access required", show_alert=True)
        return show_premium_required(chat_id, msg_id)
    expire_previous_number(chat_id)
    available = []
    for idx, n_obj in enumerate(batch.get("numbers", [])):
        if chat_id not in n_obj.get("used_by", []):
            available.append(idx)
    if not available:
        if call_id:
            answer_callback(call_id, "You already used all numbers in this batch", show_alert=True)
        return send_message(chat_id, render_body_text("You already used all available numbers in this batch."), reply_markup=main_menu(chat_id))
    random.shuffle(available)
    limit = max(1, int(bot_settings.get("num_req", 1) or 1))
    fetched_nums = []
    reward_by_num = {}
    reward = batch_otp_reward(str(batch_id))
    for idx in available:
        if len(fetched_nums) >= limit:
            break
        n_obj = batch["numbers"][idx]
        num = str(n_obj.get("num", "")).strip()
        if not num:
            continue
        fetched_nums.append(num)
        reward_by_num[num] = reward
        clean_num = re.sub(r"\D", "", num)
        if clean_num:
            reward_by_num[clean_num] = reward
            reward_by_num[f"+{clean_num}"] = reward
        n_obj["shares"] = int(n_obj.get("shares", 0)) + 1
        n_obj.setdefault("used_by", []).append(chat_id)
        total_assigned_stats += 1
        if n_obj["shares"] >= bot_settings.get("num_share", 1):
            n_obj["to_remove"] = True
            used_numbers_list.append(num)
    batch["numbers"] = [x for x in batch.get("numbers", []) if not x.get("to_remove")]
    save_db()
    if not fetched_nums:
        if category == "PREMIUM":
            if call_id:
                answer_callback(call_id, "Premium number is not available", show_alert=True)
            return show_premium_unavailable(chat_id, msg_id, back_cb="ux_premium_number")
        if call_id:
            answer_callback(call_id, "Number out of stock", show_alert=True)
        return send_message(chat_id, render_body_text("Number out of stock."), reply_markup=main_menu(chat_id))
    service = str(batch.get("service", "UNKNOWN"))
    country = str(batch.get("country", "UNKNOWN"))
    text = _number_result_text(service, country, category, fetched_nums, show_prefix=True, reward=reward)
    markup = _batch_result_markup(service, country, category, str(batch_id), fetched_nums, show_prefix=True)
    active_msg_id = _deliver_number_card(chat_id, msg_id, text, markup, service, country, category, fetched_nums, show_prefix=True, reward=reward) or msg_id
    user_active_sessions[chat_id] = _number_session_payload(
        active_msg_id,
        fetched_nums,
        reward_by_num,
        service,
        country,
        category,
        f"gsc:{category}:{service}",
        f"batch_get:{batch_id}",
        show_prefix=True,
    )
    return True


def _mk_admin_keyboard():
    rows = []
    for p in _mk_panels():
        state = "ON" if p["enabled"] else "OFF"
        provider_tag = "NP" if p.get("protocol") == "npnetwork" else "MK"
        rows.append([
            {"text": f"[{provider_tag}] {p['name']} [{state}]", "icon_custom_emoji_id": "5192812028632274956" if p["enabled"] else "5420130255174145507", "callback_data": f"mks_toggle:{p['id']}", "style": "primary"},
            {"text": "TEST", "icon_custom_emoji_id": "5352694861990501856", "callback_data": f"mks_test:{p['id']}", "style": "success"},
        ])
        rows.append([
            {"text": f"ROUTES ({len(p.get('routes', []) or [])})", "icon_custom_emoji_id": "5352862640592949843", "callback_data": f"mks_routes:{p['id']}", "style": "primary"},
            {"text": "DELETE", "icon_custom_emoji_id": "5422557736330106570", "callback_data": f"mks_delete:{p['id']}", "style": "danger"},
        ])
    rows.append([{ "text": "ADD NP PANEL", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "nps_add", "style": "success" }])
    rows.append([{ "text": "ADD MK PANEL", "icon_custom_emoji_id": "5420323438508155202", "callback_data": "mks_add", "style": "primary" }])
    rows.append([{ "text": "BACK TO SYSTEM", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "mks_back", "style": "primary" }])
    return {"inline_keyboard": rows}


def _mk_routes_keyboard(panel):
    pid = str(panel.get("id", ""))
    rows = []
    for index, route in enumerate(panel.get("routes", []) or []):
        label = _route_label(route)
        rows.append([{
            "text": f"DELETE {label[:48]}",
            "icon_custom_emoji_id": "5422557736330106570",
            "callback_data": f"mks_route_delete:{pid}:{index}",
            "style": "danger",
        }])
    rows.append([{
        "text": "ADD ROUTE",
        "icon_custom_emoji_id": "5420323438508155202",
        "callback_data": f"mks_route_add:{pid}",
        "style": "success",
    }])
    rows.append([{
        "text": "BACK TO PANELS",
        "icon_custom_emoji_id": "5267490665117275176",
        "callback_data": "mk_manage_panels",
        "style": "primary",
    }])
    return {"inline_keyboard": rows}


def _show_mk_routes(chat_id, panel_id, message_id=None):
    panel = _mk_panel(panel_id)
    if not panel:
        return
    routes = panel.get("routes", []) or []
    if routes:
        route_lines = "\n".join(
            f"• <b>{html.escape(str(route.get('service', '')))}</b> / "
            f"<b>{html.escape(str(route.get('country', '')))}</b> / "
            f"<b>{_route_category(route)}</b> / "
            f"<b>{_route_reward(route):g} USD</b> → "
            f"<code>{html.escape(', '.join(_route_ranges(route)))}</code>"
            for route in routes
        )
    else:
        route_lines = "<i>No custom route is set. Only liveaccess ranges will be used.</i>"
    text = (
        f"🧭 <b>{html.escape(panel['name'])} ROUTES</b>\n\n"
        "Set exactly which service, country, range, stock type, and OTP reward this panel should provide.\n\n"
        f"{route_lines}\n\n"
        "Format:\n"
        "<code>SERVICE | COUNTRY | RANGE1,RANGE2 | FREE/PREMIUM | OTP_REWARD</code>\n\n"
        "Example:\n"
        "<code>WHATSAPP | YEMEN | 9677,96773 | PREMIUM | 0.02</code>"
    )
    markup = _mk_routes_keyboard(panel)
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=markup)
    else:
        send_message(chat_id, render_body_text(text), reply_markup=markup)


def _show_mk_admin(chat_id, message_id=None):
    text = (
        "🛰 <b>API PANEL CONTROL</b>\n\n"
        "Add only your authorized MK or NP Network API providers here.\n"
        "Use ROUTES to set service, country, range, Free/Premium stock, and per-OTP reward."
    )
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=_mk_admin_keyboard())
    else:
        send_message(chat_id, render_body_text(text), reply_markup=_mk_admin_keyboard())


_original_dx_handle_message = handle_message

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    admin = is_admin(chat_id)
    is_start_action = text.casefold() == "start" or text.casefold().startswith("/start")

    # START acknowledges the notice when the user uses the command directly.
    # The notice is informational only; it never blocks the user's existing
    # menu or resets the stored account.
    if is_start_action:
        acknowledge_user_update(chat_id)

    if user_states.get(chat_id) in ("fb_wait_payment_screenshot", "fb_wait_payment_txid"):
        if _handle_fb_payment_message(msg):
            return
    if _handle_premium_number_payment_message(msg):
        return

    if handle_temp_mail_text(msg):
        return

    if handle_user_menu_text(msg):
        return

    # API Number flow uses a bottom Reply Keyboard, replacing the main menu.
    if text == "API Number":
        if not _dual_api_allowed(chat_id):
            return
        user_states.pop(chat_id, None)
        _show_api_number_menu(chat_id)
        return
    if text in ("🏠 MAIN MENU", "MAIN MENU"):
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        send_message(chat_id, render_body_text("✅ Main menu restored."), reply_markup=main_menu(chat_id))
        return
    if text in ("📞 API NUMBER", "API NUMBER"):
        if not _dual_api_allowed(chat_id):
            return
        _show_api_provider_menu(chat_id)
        return
    if text in ("🛡 OTP GROUP", "OTP GROUP"):
        link = bot_settings.get("otp_link", "")
        if link:
            send_message(chat_id, render_body_text("🛡 <b>OTP GROUP</b>"), reply_markup={
                "inline_keyboard": [[{"text": "OPEN OTP GROUP", "icon_custom_emoji_id": "5190447043545438788", "url": link, "style": "primary"}]]
            })
        else:
            send_message(chat_id, render_body_text("⚠️ Admin has not configured an OTP group."))
        return
    if text in ("🔄 CHANGE NUMBER", "CHANGE NUMBER"):
        if not _dual_api_allowed(chat_id):
            return
        with api_session_lock:
            current_session = dict(api_number_sessions.get(chat_id, {}))
        if current_session.get("panel_id") and current_session.get("range"):
            preferred = {
                "range": current_session.get("range"),
                "panel_id": current_session.get("panel_id"),
                "panel_name": current_session.get("panel_name", ""),
            }
            # Change Number stays on the provider selected by the user.
            _api_number_action(
                chat_id,
                preferred=preferred,
                provider_id=current_session.get("panel_id"),
            )
        else:
            send_message(chat_id, render_body_text("⚠️ Select a provider from API NUMBER first."), reply_markup=_api_number_keyboard())
        return
    if text in ("🔄 CHANGE PROVIDER", "CHANGE PROVIDER"):
        if not _dual_api_allowed(chat_id):
            return
        # Provider changes only through API NUMBER → provider selection.
        _show_api_provider_menu(chat_id)
        return
    if text in ("💾 SAVE RANGE", "SAVE RANGE", "SAVE API RANGE"):
        if not _dual_api_allowed(chat_id):
            return
        user_states[chat_id] = "api_wait_range"
        send_message(chat_id, render_body_text("💾 <b>SAVE RANGE</b>\n\nSend your authorized range. Example: <code>234XXX</code>"), reply_markup=_api_cancel_inline_keyboard())
        return

    if user_states.get(chat_id) == "api_choose_provider" and text.startswith("🛰 "):
        saved = _get_user_api_ranges(chat_id)
        latest = saved[-1] if saved and isinstance(saved[-1], dict) else None
        provider_name = text.removeprefix("🛰 ").strip()
        matches = _find_matching_mk_panels(str(latest.get("range", ""))) if latest else []
        panel = next((p for p in matches if p.get("name") == provider_name), None)
        if not panel:
            send_message(chat_id, render_body_text("❌ Provider is no longer available. Press API NUMBER again."), reply_markup=_api_number_keyboard())
            return
        user_states.pop(chat_id, None)
        _api_number_action(chat_id, preferred=latest, provider_id=panel["id"])
        return

    if user_states.get(chat_id) == "api_wait_range":
        if text in ("Cancel", "❌ CANCEL"):
            user_states.pop(chat_id, None)
            send_message(chat_id, render_body_text("❌ Range save cancelled."), reply_markup=_api_number_keyboard())
            return
        if not re.match(r"^[0-9]+[0-9Xx]*$", text) or not re.search(r"\d", text):
            send_message(chat_id, render_body_text("❌ Invalid range. Example: <code>234XXX</code>"), reply_markup=_api_cancel_inline_keyboard())
            return
        range_text = text.upper().replace(" ", "")
        user_states.pop(chat_id, None)
        send_message(chat_id, render_body_text("⌛ Checking the range in MK Online SMS panel..."))
        panel = _find_panel_for_range(range_text)
        if panel:
            saved = _add_user_api_range(chat_id, range_text, panel)
            send_message(chat_id, render_body_text(
                f"✅ <b>RANGE SAVED</b>\n\n📶 RANGE: <code>{html.escape(range_text)}</code>\n"
                f"🛰 MATCHED PROVIDERS: <b>{html.escape(panel['name'])}</b>\n"
                "📋 Only the latest range has been saved in the database."
            ), reply_markup=_api_number_keyboard())
        else:
            send_message(chat_id, render_body_text(
                "❌ This range is not in the MK Online SMS liveaccess list.\n"
                "Use the provider official live range."
            ), reply_markup=_api_number_keyboard())
        return

    if user_states.get(chat_id) == "fb_wait_quantity":
        if _handle_fb_quantity_text(chat_id, text):
            return

    admin_mode = user_states.get(chat_id)
    if admin and admin_mode == "wait_premium_add":
        if text in ("Cancel", "CANCEL", "❌ CANCEL"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_premium_admin(chat_id)
            return
        parts = [x.strip() for x in re.split(r"[|,\s]+", text) if x.strip()]
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            send_message(chat_id, render_body_text("Invalid format. Send: <code>USER_ID | DAYS</code>"), reply_markup=get_cancel_kb())
            return
        user_id = int(parts[0])
        days = int(parts[1])
        expires_at = grant_premium_user(user_id, days, chat_id)
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        send_message(
            chat_id,
            render_body_text(
                f"✅ Premium user added.\n\nUser ID: <code>{user_id}</code>\n"
                f"Days: <b>{days}</b>\n"
                f"Expires: <code>{datetime.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')}</code>"
            ),
        )
        _show_premium_admin(chat_id)
        return

    if admin and admin_mode == "wait_premium_support":
        if text in ("Cancel", "CANCEL", "❌ CANCEL"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_premium_admin(chat_id)
            return
        link = text.strip()
        if link and not re.match(r"^https?://[^\s]+$", link, re.I):
            send_message(chat_id, render_body_text("Send a valid public URL, for example <code>https://t.me/support</code>"), reply_markup=get_cancel_kb())
            return
        bot_settings["premium_support_link"] = link
        save_db()
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        send_message(chat_id, render_body_text("✅ Premium support link saved."))
        _show_premium_admin(chat_id)
        return

    if admin and str(user_states.get(chat_id, "")).startswith("fb_wait_"):
        if _handle_fb_admin_text(chat_id, text):
            return

    # Prefix search input flow. The active number session fixes the
    # service, country, and stock category; the user supplies only the prefix.
    admin_mode = user_states.get(chat_id)
    if admin_mode == "wait_for_prefix_search" and text:
        prefix = text.strip().replace("+", "")
        if not prefix.isdigit() or len(prefix) < 3 or len(prefix) > 9:
            send_message(chat_id, render_body_text("Please send a valid 3 to 9 digit Prefix."), reply_markup=get_cancel_kb())
            return
        session = user_active_sessions.get(chat_id) or {}
        if not session.get("nums"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            send_message(chat_id, render_body_text("The active number session has expired."), reply_markup=main_menu(chat_id))
            return
        prompt_id = temp_data.get(chat_id, {}).get("msg_id")
        if prompt_id:
            edit_message(chat_id, prompt_id, render_body_text("Searching numbers for the requested Prefix..."))
        fetched_nums, reward_by_num = _search_local_numbers_by_prefix(chat_id, session, prefix)
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        if not fetched_nums:
            if prompt_id:
                delete_message(chat_id, prompt_id)
            send_message(
                chat_id,
                render_body_text(
                    f"No available number found for Prefix <code>{html.escape(prefix)}</code> "
                    f"in {html.escape(str(session.get('service', '')))} / {html.escape(str(session.get('country', '')))}."
                ),
                reply_markup=main_menu(chat_id),
            )
            return
        service = session.get("service", "NUMBER")
        country = session.get("country", "AUTO")
        category = session.get("category", "FREE")
        result_text = _number_result_text(service, country, category, fetched_nums, show_prefix=True)
        result_markup = _number_result_markup(
            service,
            country,
            category,
            fetched_nums,
            session.get("change_country_cb", "ux_get_number"),
            session.get("change_number_cb", "ux_get_number"),
            show_prefix=True,
        )
        active_msg_id = _deliver_number_card(
            chat_id,
            prompt_id,
            result_text,
            result_markup,
            service,
            country,
            category,
            fetched_nums,
            show_prefix=True,
        )
        if active_msg_id:
            user_active_sessions[chat_id] = _number_session_payload(
                active_msg_id,
                fetched_nums,
                reward_by_num,
                service,
                country,
                category,
                session.get("change_country_cb", "ux_get_number"),
                session.get("change_number_cb", "ux_get_number"),
                show_prefix=True,
            )
        return

    # Card template editor input flow.
    if admin and admin_mode == "card_wait_body" and text:
        data = temp_data.get(chat_id, {})
        card_key = data.get("card_key")
        if text.casefold() in {"cancel", "❌ cancel"}:
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_editor(chat_id, card_key)
            return
        if card_key:
            if text.strip().upper() == "RESET":
                _card_template(card_key).pop("body_text", None)
            else:
                _card_template(card_key)["body_text"] = compile_admin_premium_input(msg)
            save_db()
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_editor(chat_id, card_key)
        return

    if admin and admin_mode == "card_wait_title" and text:
        card_key = temp_data.get(chat_id, {}).get("card_key")
        if text.casefold() in {"cancel", "❌ cancel"}:
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_editor(chat_id, card_key)
            return
        if card_key:
            _card_template(card_key)["title"] = text[:120]
            save_db()
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_editor(chat_id, card_key)
        return

    if admin and admin_mode == "card_wait_row" and text:
        data = temp_data.get(chat_id, {})
        if text.casefold() in {"cancel", "❌ cancel"}:
            card_key = data.get("card_key")
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_editor(chat_id, card_key)
            return
        card_key, field, index = data.get("card_key"), data.get("field"), data.get("row_index")
        try:
            row = _card_template(card_key)["rows"][int(index)]
            row[field] = text[:500]
            save_db()
        except Exception:
            send_message(chat_id, render_body_text("Invalid card row."), reply_markup=get_cancel_kb())
            return
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        _show_card_editor(chat_id, card_key)
        return

    if admin and admin_mode == "card_wait_button" and text:
        data = temp_data.get(chat_id, {})
        card_key = data.get("card_key")
        if text.casefold() in {"cancel", "❌ cancel"}:
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_buttons(chat_id, card_key)
            return
        parts = [part.strip() for part in text.split("|", 2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            send_message(chat_id, render_body_text("Send: <code>Button Text | callback_data</code> or <code>Button Text | https://example.com</code>"), reply_markup=get_cancel_kb())
            return
        action_check = validate_button_action(parts[1])
        if not action_check.get("ok"):
            send_message(chat_id, render_body_text(f"❌ Button was not saved. {html.escape(action_check.get('error', ''))}"), reply_markup=get_cancel_kb())
            return
        button = {"text": parts[0][:64], "style": "primary"}
        if action_check.get("url"):
            button["url"] = action_check["url"]
        else:
            button["callback_data"] = action_check["callback"]
        if len(parts) == 3 and parts[2].strip().isdigit():
            button["icon_custom_emoji_id"] = parts[2].strip()
        _card_template(card_key).setdefault("buttons", []).append(button)
        save_db()
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        _show_card_buttons(chat_id, card_key)
        return

    if admin and admin_mode in {"card_wait_button_text", "card_wait_button_action", "card_wait_button_icon"} and text:
        data = temp_data.get(chat_id, {})
        card_key, index = data.get("card_key"), int(data.get("button_index", -1))
        buttons = _card_template(card_key).setdefault("buttons", [])
        if text.casefold() in {"cancel", "❌ cancel"}:
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_buttons(chat_id, card_key)
            return
        if index < 0 or index >= len(buttons):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            _show_card_buttons(chat_id, card_key)
            return
        if admin_mode == "card_wait_button_text":
            buttons[index]["text"] = text[:80]
        elif admin_mode == "card_wait_button_action":
            action_check = validate_button_action(text)
            if not action_check.get("ok"):
                send_message(chat_id, render_body_text(f"❌ Action was not saved. {html.escape(action_check.get('error', ''))}"), reply_markup=get_cancel_kb())
                return
            buttons[index].pop("url", None)
            buttons[index].pop("callback_data", None)
            if action_check.get("url"):
                buttons[index]["url"] = action_check["url"]
            else:
                buttons[index]["callback_data"] = action_check["callback"]
        else:
            ids = list(dict.fromkeys(plain_custom_emoji_ids(text) + [item["id"] for item in custom_emoji_entities(msg)]))
            result = validate_premium_ids(ids)
            if len(ids) != 1 or not result.get("ok"):
                send_message(chat_id, render_body_text("Send exactly one valid custom emoji ID or Premium Emoji."), reply_markup=get_cancel_kb())
                return
            buttons[index]["icon_custom_emoji_id"] = ids[0]
        save_db()
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        _show_card_buttons(chat_id, card_key)
        return

    # Admin panel route input flow.
    if admin and admin_mode == "mks_route":
        panel_id = temp_data.get(chat_id, {}).get("panel_id")
        if text in ("Cancel", "CANCEL", "❌ CANCEL"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            if panel_id:
                _show_mk_routes(chat_id, panel_id)
            else:
                send_message(chat_id, render_body_text("Route setup cancelled."), reply_markup=main_menu(chat_id))
            return
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 5 or not all(parts):
            send_message(
                chat_id,
                render_body_text(
                    "Invalid format. Send exactly like this:\n"
                    "<code>SERVICE | COUNTRY | RANGE1,RANGE2 | FREE/PREMIUM | OTP_REWARD</code>"
                ),
                reply_markup=get_cancel_kb(),
            )
            return
        service, country, raw_ranges, raw_category, raw_reward = parts
        ranges = [value.strip().upper() for value in re.split(r"[,;\s]+", raw_ranges) if value.strip()]
        category = _normalize_stock_category(raw_category)
        if category == "FB":
            category = "FREE"
        try:
            otp_reward = float(raw_reward)
            if otp_reward < 0:
                raise ValueError
        except Exception:
            send_message(chat_id, render_body_text("Invalid OTP reward. Example: <code>0.02</code>"), reply_markup=get_cancel_kb())
            return
        if (
            not re.match(r"^[A-Za-z0-9][A-Za-z0-9 _./-]{0,59}$", service)
            or not re.match(r"^[A-Za-z0-9][A-Za-z0-9 _./+-]{0,39}$", country)
            or not ranges
            or any(not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.*+#/-]{0,39}$", value) for value in ranges)
        ):
            send_message(
                chat_id,
                render_body_text("Invalid service, country, or range. Example: <code>WHATSAPP | IN | 9198 | PREMIUM | 0.02</code>"),
                reply_markup=get_cancel_kb(),
            )
            return
        panel = _mk_panel(panel_id)
        if not panel:
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            send_message(chat_id, render_body_text("Panel not found."))
            return
        new_route = {
            "service": service.upper(),
            "country": country.upper(),
            "ranges": list(dict.fromkeys(ranges)),
            "category": category,
            "otp_reward": otp_reward,
        }
        routes = [
            route for route in (panel.get("routes", []) or [])
            if not (
                _route_key(route.get("service")) == _route_key(new_route["service"])
                and _route_key(route.get("country")) == _route_key(new_route["country"])
                and _route_category(route) == category
            )
        ]
        routes.append(new_route)
        panel["routes"] = routes
        _save_mk_panels([panel if item.get("id") == panel["id"] else item for item in _mk_panels()])
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        send_message(
            chat_id,
            render_body_text(
                f"✅ Route saved: <b>{html.escape(new_route['service'])}</b> / "
                f"<b>{html.escape(new_route['country'])}</b> / <b>{category}</b> → "
                f"<code>{html.escape(', '.join(new_route['ranges']))}</code>\n"
                f"Per OTP reward: <b>{otp_reward:g} USD</b>"
            ),
        )
        _show_mk_routes(chat_id, panel["id"])
        return

    # Admin panel-management input flow
    if admin and admin_mode in ("mks_name", "mks_url", "mks_key", "nps_name", "nps_url", "nps_key"):
        if text in ("Cancel", "CANCEL", "❌ CANCEL"):
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            send_message(chat_id, render_body_text("Panel setup cancelled."), reply_markup=main_menu(chat_id))
            return
        if admin_mode in ("mks_name", "nps_name"):
            temp_data[chat_id] = {"name": text[:60]}
            next_state = "nps_url" if admin_mode == "nps_name" else "mks_url"
            user_states[chat_id] = next_state
            example = "https://npsmsnetwork.com/api/index.php?route=user" if next_state == "nps_url" else "https://provider.example/api"
            send_message(chat_id, render_body_text(f"🌐 Send the panel base URL:\n<code>{example}</code>"), reply_markup=get_cancel_kb())
            return
        if admin_mode in ("mks_url", "nps_url"):
            url = text.rstrip("/")
            if not re.match(r"^https://[^\s]+$", url, re.I) or any(x in url.lower() for x in ["localhost", "127.0.0.1", "0.0.0.0"]):
                send_message(chat_id, render_body_text("❌ Send a public HTTPS URL."), reply_markup=get_cancel_kb())
                return
            temp_data[chat_id]["base_url"] = url
            user_states[chat_id] = "nps_key" if admin_mode == "nps_url" else "mks_key"
            send_message(chat_id, render_body_text("🔐 Send the API key. The message will be deleted if possible."), reply_markup=get_cancel_kb())
            return
        if admin_mode in ("mks_key", "nps_key"):
            key = text.strip()
            try:
                delete_message(chat_id, msg.get("message_id"))
            except Exception:
                pass
            if len(key) < 4:
                send_message(chat_id, "❌ API key invalid.", reply_markup=get_cancel_kb())
                return
            data = temp_data.get(chat_id, {})
            protocol = "npnetwork" if admin_mode == "nps_key" else "mk"
            name = data.get("name", "NP Panel" if protocol == "npnetwork" else "MK Panel")
            panels = _mk_panels()
            pid_base = _safe_panel_id(name)
            pid = pid_base
            i = 2
            while any(p["id"] == pid for p in panels):
                pid = f"{pid_base}-{i}"; i += 1
            panels.append({
                "id": pid,
                "name": name,
                "base_url": data["base_url"],
                "api_key": key,
                "protocol": protocol,
                "enabled": True,
            })
            _save_mk_panels(panels)
            user_states.pop(chat_id, None)
            temp_data.pop(chat_id, None)
            title = "NP Network" if protocol == "npnetwork" else "MK"
            send_message(chat_id, render_body_text(f"✅ {title} API panel added. Press TEST now."), reply_markup=main_menu(chat_id))
            return


    # Existing DXnumbers behavior
    _original_dx_handle_message(msg)


_original_dx_handle_callback = handle_callback

def handle_callback(call):
    chat_id = call["message"]["chat"]["id"]
    data = call.get("data", "")
    if data == "send_update_notify":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Admin access required", show_alert=True)
            return
        answer_callback(call["id"], "Sending update notification")
        announce_user_update("The bot has been updated by Admin")
        edit_message(
            chat_id,
            call.get("message", {}).get("message_id"),
            render_body_text("✅ <b>Update notification sent.</b>\n\nUsers received one notification with the START button. No automatic update notification will be sent until you press this button again."),
            reply_markup=admin_panel_keyboard(),
        )
        return
    if data == "update_start":
        answer_callback(call["id"], "Loading the latest bot version")
        acknowledge_user_update(chat_id)
        try:
            delete_message(chat_id, call.get("message", {}).get("message_id"))
        except Exception:
            pass
        source_message = call.get("message", {}) or {}
        start_message = {
            "chat": source_message.get("chat", {"id": chat_id, "type": "private"}),
            "from": call.get("from") or source_message.get("from", {}),
            "text": "/start",
        }
        # Re-enter the normal /start flow. This only refreshes the UI; the
        # existing user, balance, referrals, batches, and OTP history remain.
        return _original_dx_handle_message(start_message)
    if data.startswith("traffic_get:"):
        try:
            _, encoded_service, _iso = data.split(":", 2)
            service = unquote(encoded_service)
        except ValueError:
            answer_callback(call["id"], "Invalid traffic entry", show_alert=True)
            return
        answer_callback(call["id"])
        return show_service_menu(
            chat_id,
            call.get("message", {}).get("message_id"),
            "FREE NUMBER",
            service_filter=service,
        )
    if data == "ignore":
        answer_callback(call["id"], "Not available", show_alert=False)
        return
    if is_user_menu_callback(data):
        if is_user_banned(chat_id):
            answer_callback(call["id"], "You are banned from using this bot.", show_alert=True)
            return
        if not check_force_join(chat_id):
            answer_callback(call["id"])
            send_force_join_msg(chat_id)
            return
        answer_callback(call["id"])
        return handle_user_menu_callback(call)
    if data.startswith("card_"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Admin access required", show_alert=True)
            return
        return handle_card_editor_callback(call)
    if data.startswith("otpgrp:"):
        parts = data.split(":")
        session_key = parts[1] if len(parts) > 1 else ""
        expanded = len(parts) > 2 and parts[2] == "1"
        session = group_card_sessions.get(session_key)
        answer_callback(call["id"])
        if not session:
            return
        markup = _otp_group_markup(session.get("number", ""), session.get("otp", ""), safe_custom_buttons(session.get("buttons", [])), session_key=session_key, expanded=expanded)
        # Board cards are photos — the expand/collapse swap deletes and
        # re-renders the board instead of editing text into a photo.
        return _send_otp_group_card(
            chat_id,
            session,
            markup=markup,
            replace_message_id=call["message"]["message_id"],
            collapsed=not expanded,
        )
    if not (data.startswith("mks_") or data.startswith("nps_") or data.startswith("api_") or data.startswith("premium_") or data.startswith("pn") or data.startswith("fb") or data.startswith("batch_get:") or data in {"prefix_toggle", "prefix_search"} or data == "bc_start" or data == "mk_manage_panels"):
        if callback_requires_premium(data) and not is_premium_user(chat_id):
            answer_callback(call["id"], "Premium access required", show_alert=True)
            return show_premium_required(chat_id, call["message"].get("message_id"))
        return _original_dx_handle_callback(call)
    if not is_admin(chat_id) and not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return
    msg_id = call["message"]["message_id"]
    if callback_requires_premium(data) and not is_premium_user(chat_id):
        answer_callback(call["id"], "Premium access required", show_alert=True)
        show_premium_required(chat_id, msg_id)
        return
    answer_callback(call["id"])

    if data.startswith("fb"):
        if handle_fb_tools_callback(call):
            return

    if data == "bc_start":
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        cleanup_expired_premium_users()
        send_message(chat_id, render_body_text(f"{PEM['ok']} Bot refreshed. Use the menu below."), reply_markup=main_menu(chat_id))
        return

    if data == "prefix_search":
        session = user_active_sessions.get(chat_id) or {}
        if not session.get("nums"):
            answer_callback(call["id"], "No active number session", show_alert=True)
            return
        service = str(session.get("service", "NUMBER"))
        country = str(session.get("country", "AUTO"))
        category = _normalize_stock_category(session.get("category", "FREE"))
        prompt = render_body_text(
            f"<b>Find by Prefix</b>\n\n"
            f"Service: <b>{html.escape(service)}</b>\n"
            f"Country: <b>{html.escape(country)}</b>\n"
            f"Category: <b>{html.escape(category)}</b>\n\n"
            "Send a 3 to 9 digit Prefix to search only this Service and Country."
        )
        prompt_res = send_message(chat_id, prompt, reply_markup=get_cancel_kb())
        prompt_id = (prompt_res or {}).get("result", {}).get("message_id")
        user_states[chat_id] = "wait_for_prefix_search"
        temp_data[chat_id] = {
            "msg_id": prompt_id,
            "source_msg_id": msg_id,
            "service": service,
            "country": country,
            "category": category,
        }
        answer_callback(call["id"], "Send the Prefix", show_alert=False)
        return

    if data == "prefix_toggle":
        session = user_active_sessions.get(chat_id)
        if not session:
            answer_callback(call["id"], "No active number session", show_alert=True)
            return
        session["show_prefix"] = not bool(session.get("show_prefix", True))
        user_active_sessions[chat_id] = session
        _refresh_number_card(chat_id, msg_id)
        answer_callback(call["id"], "Prefix display updated", show_alert=False)
        return

    if data.startswith("batch_get:"):
        batch_id = data.split(":", 1)[1]
        _allocate_from_uploaded_batch(chat_id, msg_id, batch_id, call_id=call.get("id"))
        return

    if data == "premium_manage":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin can manage premium users", show_alert=True)
            return
        _show_premium_admin(chat_id, msg_id)
        return
    if data == "premium_add":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return
        user_states[chat_id] = "wait_premium_add"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("➕ <b>ADD PREMIUM USER</b>\n\nSend: <code>USER_ID | DAYS</code>\nExample: <code>123456789 | 30</code>"), reply_markup=get_cancel_kb())
        return
    if data == "premium_number_requests":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return
        show_premium_number_requests(chat_id, msg_id)
        return
    if data.startswith("pnapprove:") or data.startswith("pnreject:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return
        request_id = data.split(":", 1)[1]
        record = _premium_number_requests_store().get(request_id)
        if not record or record.get("status") != "PENDING":
            answer_callback(call["id"], "Request is no longer pending", show_alert=True)
            return
        if data.startswith("pnapprove:"):
            days = int(record.get("plan", {}).get("days", 1) or 1)
            grant_premium_user(int(record["user_id"]), days, chat_id)
            record["status"] = "APPROVED"
            record["approved_by"] = chat_id
            save_db()
            send_message(record["user_id"], render_body_text(f"✅ Premium Number payment approved. Your {days}-day Premium Number access is active."))
            edit_message(chat_id, msg_id, render_body_text(f"✅ Premium Number request <code>{html.escape(request_id)}</code> approved."))
        else:
            record["status"] = "REJECTED"
            record["rejected_by"] = chat_id
            save_db()
            send_message(record["user_id"], render_body_text("❌ Premium Number payment request was rejected. Please contact support."))
            edit_message(chat_id, msg_id, render_body_text(f"❌ Premium Number request <code>{html.escape(request_id)}</code> rejected."))
        return
    if data == "premium_support":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return
        user_states[chat_id] = "wait_premium_support"
        temp_data[chat_id] = {"msg_id": msg_id}
        edit_message(chat_id, msg_id, render_body_text("🔗 <b>SET PREMIUM SUPPORT LINK</b>\n\nSend a public support URL, for example: <code>https://t.me/support</code>"), reply_markup=get_cancel_kb())
        return
    if data.startswith("premium_remove:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True)
            return
        uid = data.split(":", 1)[1]
        revoke_premium_user(uid, notify=True, reason="removed")
        _show_premium_admin(chat_id, msg_id)
        return

    if data == "mk_manage_panels":
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin can manage panels", show_alert=True)
            return
        _show_mk_admin(chat_id, msg_id)
        return
    if data == "mks_back":
        edit_message(chat_id, msg_id, render_body_text("⚙️ <b>SYSTEM SETTINGS</b>"), reply_markup=system_settings_keyboard())
        return
    if data in {"mks_add", "nps_add"}:
        user_states[chat_id] = "nps_name" if data == "nps_add" else "mks_name"
        temp_data[chat_id] = {"msg_id": msg_id}
        title = "NP NETWORK" if data == "nps_add" else "MK / FAST SMS"
        edit_message(chat_id, msg_id, render_body_text(f"➕ <b>ADD API PANEL ({title})</b>\n\nSend the panel name:"), reply_markup=get_cancel_kb())
        return
    if data.startswith("mks_toggle:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True); return
        pid = data.split(":", 1)[1]
        panels = _mk_panels()
        for p in panels:
            if p["id"] == pid:
                p["enabled"] = not p["enabled"]
        _save_mk_panels(panels)
        _show_mk_admin(chat_id, msg_id)
        return
    if data.startswith("mks_delete:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True); return
        pid = data.split(":", 1)[1]
        _save_mk_panels([p for p in _mk_panels() if p["id"] != pid])
        _show_mk_admin(chat_id, msg_id)
        return
    if data.startswith("mks_test:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin", show_alert=True); return
        pid = data.split(":", 1)[1]
        panel = _mk_panel(pid)
        result = _mk_json_get(panel, "/api/liveaccess") if panel else None
        services = _api_liveaccess_services(result or {})
        provider_tag = "NP" if panel and panel.get("protocol") == "npnetwork" else "MK"
        send_message(chat_id, render_body_text(
            f"🧪 <b>{provider_tag} - {html.escape(panel['name'] if panel else pid)}</b>\n"
            + (f"✅ {len(services)} service(s) available" if services else "❌ Test failed or no service returned")
        ))
        return
    if data.startswith("mks_routes:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin can manage routes", show_alert=True)
            return
        panel_id = data.split(":", 1)[1]
        if not _mk_panel(panel_id):
            answer_callback(call["id"], "Panel not found", show_alert=True)
            return
        user_states.pop(chat_id, None)
        temp_data.pop(chat_id, None)
        _show_mk_routes(chat_id, panel_id, msg_id)
        return
    if data.startswith("mks_route_add:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin can manage routes", show_alert=True)
            return
        panel_id = data.split(":", 1)[1]
        if not _mk_panel(panel_id):
            answer_callback(call["id"], "Panel not found", show_alert=True)
            return
        user_states[chat_id] = "mks_route"
        temp_data[chat_id] = {"msg_id": msg_id, "panel_id": panel_id}
        edit_message(
            chat_id,
            msg_id,
            render_body_text(
                "🧭 <b>ADD PANEL ROUTE</b>\n\n"
                "Send one line:\n"
                "<code>SERVICE | COUNTRY | RANGE1,RANGE2 | FREE/PREMIUM | OTP_REWARD</code>\n\n"
                "Examples:\n"
                "<code>FACEBOOK | BD | 88017,88018 | FREE | 0.01</code>\n"
                "<code>WHATSAPP | IN | 9198 | PREMIUM | 0.02</code>"
            ),
            reply_markup=get_cancel_kb(),
        )
        return
    if data.startswith("mks_route_delete:"):
        if not is_admin(chat_id):
            answer_callback(call["id"], "Only admin can manage routes", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) != 3:
            answer_callback(call["id"], "Invalid route", show_alert=True)
            return
        panel_id, raw_index = parts[1], parts[2]
        try:
            route_index = int(raw_index)
        except ValueError:
            answer_callback(call["id"], "Invalid route", show_alert=True)
            return
        panel = _mk_panel(panel_id)
        routes = panel.get("routes", []) if panel else []
        if not panel or not 0 <= route_index < len(routes):
            answer_callback(call["id"], "Route not found", show_alert=True)
            return
        routes.pop(route_index)
        panel["routes"] = routes
        _save_mk_panels([panel if item.get("id") == panel_id else item for item in _mk_panels()])
        answer_callback(call["id"], "Route deleted", show_alert=True)
        _show_mk_routes(chat_id, panel_id, msg_id)
        return

    if data == "api_cancel_range":
        user_states.pop(chat_id, None)
        edit_message(chat_id, msg_id, render_body_text("❌ Range save cancelled."), reply_markup=_api_number_keyboard())
        return
    if data == "api_save_range":
        user_states[chat_id] = "api_wait_range"
        edit_message(chat_id, msg_id, render_body_text("💾 <b>SAVE API RANGE</b>\n\nSend a range. Example: <code>234XXX</code>"), reply_markup=_api_cancel_inline_keyboard())
        return
    if data == "api_main_menu":
        edit_message(chat_id, msg_id, render_body_text("🏠 <b>MAIN MENU</b>"))
        send_message(chat_id, render_body_text("✅ Main menu restored."), reply_markup=main_menu(chat_id))
        return
    if data == "api_get_numbers":
        _show_api_provider_menu(chat_id, msg_id)
        return
    if data.startswith("api_provider:"):
        provider_id = data.split(":", 1)[1]
        saved = _get_user_api_ranges(chat_id)
        preferred = saved[-1] if saved else None
        _api_number_action(chat_id, msg_id, preferred=preferred, provider_id=provider_id)
        return
    if data == "api_change_number":
        with api_session_lock:
            current_session = dict(api_number_sessions.get(chat_id, {}))
        if not current_session.get("panel_id") or not current_session.get("range"):
            answer_callback(call["id"], "API number session expired. Press API NUMBER again.", show_alert=True)
            send_message(chat_id, render_body_text("⚠️ API session expired. Press API NUMBER again to choose a new provider."), reply_markup=_api_number_keyboard())
            return
        preferred = {
            "range": current_session.get("range"),
            "panel_id": current_session.get("panel_id"),
            "panel_name": current_session.get("panel_name", ""),
        }
        _api_number_action(
            chat_id,
            message_id=msg_id,
            preferred=preferred,
            provider_id=current_session.get("panel_id"),
        )
        return
    if data in ("api_no_group", "api_open_group"):
        answer_callback(call["id"], "Admin has not configured an OTP group", show_alert=True)
        return


def _dual_api_allowed(chat_id):
    if is_admin(chat_id):
        return True
    if is_user_banned(chat_id):
        send_message(chat_id, render_body_text("🚫 <b>You are banned from using this bot!</b>"))
        return False
    if not check_force_join(chat_id):
        send_force_join_msg(chat_id)
        return False
    return True


# ==========================================
# API NUMBER V2: MULTI-PROVIDER + DX FORWARD GROUPS
# ==========================================
# API Number checks all enabled API providers against the user's last saved
# range, shows the matching providers, and takes two numbers from the provider
# selected by the user. OTPs are sent to the user and to the same groups/buttons
# configured in the DX admin panel.


def _find_matching_mk_panels(range_text):
    matches = []
    wanted = re.sub(r"\s+", "", str(range_text).upper())
    for panel in _mk_panels(enabled_only=True):
        route_ranges = [value for route in (panel.get("routes", []) or []) for value in _route_ranges(route)]
        if any(re.sub(r"\s+", "", str(r).upper()) == wanted for r in route_ranges):
            matches.append(panel)
            continue
        data = _mk_json_get(panel, "/api/liveaccess") or {}
        services = _api_liveaccess_services(data)
        if any(re.sub(r"\s+", "", str(r).upper()) == wanted
               for service in services for r in (service.get("ranges") or [])):
            matches.append(panel)
    return matches


def _find_panel_for_range(range_text):
    matches = _find_matching_mk_panels(range_text)
    if not matches:
        return None
    return {
        "id": "multi-match", "name": ", ".join(p["name"] for p in matches)[:120],
        "base_url": "", "api_key": "", "enabled": True,
        "matched_panel_ids": [p["id"] for p in matches],
    }


def _add_user_api_range(user_id, range_text, panel=None):
    """Save exactly one latest range in both Firestore and local fallback."""
    matches = _find_matching_mk_panels(range_text)
    if not matches and panel and panel.get("id") != "multi-match":
        matches = [panel]
    if not matches:
        return []
    ids = [p["id"] for p in matches]
    names = [p["name"] for p in matches]
    record = {
        "range": str(range_text).upper(),
        "panel_ids": ids,
        "panel_names": names,
        "saved_at": datetime.now().isoformat(),
    }
    with api_range_lock:
        data = _load_api_ranges()
        # User requirement: only the newest range is retained.
        data[str(user_id)] = [record]
        _save_api_ranges(data)
        if db:
            try:
                db.collection("users").document(str(user_id)).set(
                    {"api_last_range": record}, merge=True
                )
            except Exception as e:
                print(f"[API ranges] Firestore write error: {type(e).__name__}")
    return [record]


def _api_sources_for_user(chat_id, preferred_range=None, provider_id=None):
    saved = _get_user_api_ranges(chat_id)
    if not saved:
        return []
    entry = saved[-1]
    range_text = str(preferred_range or entry.get("range", "")).upper()
    sources = []
    for panel in _mk_panels(enabled_only=True):
        if provider_id and panel["id"] != str(provider_id):
            continue
        sources.append((panel, range_text))
    return sources


def _fetch_two_api_numbers(chat_id, preferred_range=None, provider_id=None):
    sources = _api_sources_for_user(chat_id, preferred_range, provider_id)
    fetched, successful = [], []
    # A selected provider supplies both numbers. Provider/range validity is
    # checked before this function is called by the inline-button flow.
    for panel, range_text in sources:
        for _ in range(2):
            item = _mk_get_number(panel, range_text)
            if item and item["number"] not in {x["number"] for x in fetched}:
                fetched.append(item)
        if fetched:
            successful.append((panel, range_text))
        if len(fetched) >= 2:
            break
    return fetched[:2], successful


def _api_number_result_text(items):
    lines = []
    for item in items:
        lines.append(
            f"🌍 <code>+{item['number']}</code> "
            f"<i>({html.escape(str(item.get('panel_name', 'Fast OTP')))})</i>"
        )
    return (
        "📞 <b>API NUMBERS</b>\n\n"
        "🛰 <b>AVAILABLE API PANELS</b>\n\n"
        + "\n".join(lines) +
        f"\n\n✅ {len(items)} number(s) fetched from available panels."
    )


def _format_api_group_message(panel, number, sms, otp, range_text=""):
    """Backward-compatible alias for the API OTP group formatter."""
    return _format_api_dx_group_message(panel, number, sms, otp, range_text)


def _format_api_user_otp_message(panel, number, sms, otp, range_text, reward):
    """Build the editable detailed card for the API-number owner's inbox."""
    service = detect_service(str(sms)) or panel.get("name", "API Service")
    return _render_otp_template(
        "otp_inbox",
        service=service,
        number=number,
        otp=otp,
        sms_text=str(sms),
        reward=f"{float(reward or 0):.2f}",
        provider=panel.get("name", "API Panel"),
        range_text=range_text,
    )


def _format_api_dx_group_message(panel, number, sms, otp, range_text=""):
    """Build the same screenshot-style OTP card used by the Test forward flow."""
    service = detect_service(str(sms)) or panel.get("name", "API Service")
    lang = detect_language(str(sms))
    return _otp_group_message(service, number, otp, lang, str(sms))


def _forward_api_otp_to_dx_groups(panel, number, sms, otp, range_text=""):
    # Uses the exact screenshot-style card and fw_groups maintained by DX Admin Panel.
    service = detect_service(str(sms)) or panel.get("name", "API Service")
    _forward_otp_to_groups(service, number, otp, detect_language(str(sms)), str(sms))

def _api_number_action(chat_id, message_id=None, preferred=None, provider_id=None):
    preferred_range = preferred.get("range") if isinstance(preferred, dict) else None
    items, successful = _fetch_two_api_numbers(chat_id, preferred_range, provider_id)
    if not items:
        text = "❌ Two numbers are not currently available for this range on the selected provider."
        if message_id:
            edit_message(chat_id, message_id, render_body_text(text), reply_markup=_api_number_keyboard())
        else:
            send_message(chat_id, render_body_text(text), reply_markup=_api_number_keyboard())
        return
    user_states.pop(chat_id, None)
    default_range = items[0].get("range", preferred_range or "")
    assignments = [{"number": x["number"], "panel_id": x["panel_id"],
                    "panel_name": x["panel_name"], "range": x.get("range", default_range)} for x in items]
    selected_panel_id = items[0].get("panel_id", provider_id or "")
    with api_session_lock:
        api_number_sessions[chat_id] = {
            "user_id": chat_id, "range": default_range,
            "panel_id": selected_panel_id, "panel_name": items[0].get("panel_name", "API Panel"),
            "assignments": assignments, "numbers": [x["number"] for x in items], "created": time.time()
        }
    text = _api_number_result_text(items)
    result_markup = _api_result_inline_keyboard(bot_settings.get("otp_link", ""))
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=result_markup)
    else:
        send_message(chat_id, render_body_text(text), reply_markup=result_markup)


def _api_monitor_thread():
    while True:
        try:
            now = time.time()
            with api_session_lock:
                for uid in list(api_number_sessions):
                    session_expiry = float(api_number_sessions[uid].get("expires_at") or (api_number_sessions[uid].get("created", now) + API_SESSION_TIMEOUT))
                    if now > session_expiry:
                        del api_number_sessions[uid]
                sessions = list(api_number_sessions.values()) + _fb_api_sessions()
            for panel in _mk_panels(enabled_only=True):
                panel_sessions = [s for s in sessions if any(
                    a.get("panel_id") == panel["id"] for a in s.get("assignments", []))]
                if not panel_sessions:
                    continue
                data = _mk_json_get(panel, "/api/success-otp-info") or {}
                items = _api_otp_items(data)
                for item in items:
                    number = _extract_panel_number(item) or re.sub(r"\D", "", str(item.get("number", "")))
                    if not number:
                        continue
                    session = None
                    assignment = {}
                    for candidate_session in panel_sessions:
                        for candidate_assignment in candidate_session.get("assignments", []):
                            if candidate_assignment.get("panel_id") == panel["id"] and _numbers_match(candidate_assignment.get("number"), number):
                                session = candidate_session
                                assignment = candidate_assignment
                                break
                        if session:
                            break
                    if not session:
                        continue
                    sms = item.get("message") or item.get("text") or item.get("sms") or item.get("otp") or item.get("code") or "No Content"
                    code = extract_otp_code(str(sms)) or str(item.get("code") or item.get("otp") or "N/A")
                    oid = str(item.get("otp_id") or item.get("id") or f"{number}_{code}")
                    unique = f"{panel['id']}::{number}::{oid}"
                    if unique in api_seen_otps:
                        continue
                    api_seen_otps.add(unique)
                    if len(api_seen_otps) > 10000: api_seen_otps.clear()
                    owner_id = session["user_id"]
                    try:
                        reward = float(assignment.get("reward", session.get("reward_by_num", {}).get(number, bot_settings.get("otp_reward", 0.0))))
                    except Exception:
                        reward = float(bot_settings.get("otp_reward", 0.0) or 0.0)
                    range_text = assignment.get("range", session.get("range", ""))
                    route_category = _normalize_stock_category(assignment.get("category", session.get("category", "FREE")))
                    if reward > 0:
                        update_balance(owner_id, reward)

                    # Keep API OTPs included in the same user statistics and
                    # five-minute traffic view as the existing DX listeners.
                    char, iso = get_flag_and_code(number)
                    detected_service = detect_service(str(sms)) or assignment.get("service") or panel.get("name", "API Service")
                    service_name, _ = get_service_info_html(detected_service, str(sms))
                    recent_traffic.append({
                        "source": "API Number",
                        "service": service_name,
                        "iso": iso,
                        "flag": char,
                        "number": number,
                        "range": range_text,
                        "category": route_category,
                        "time": time.time(),
                    })
                    category_total_field = "total_premium_otps" if route_category == "PREMIUM" else "total_free_otps"
                    category_today_field = "today_premium_otps" if route_category == "PREMIUM" else "today_free_otps"
                    if owner_id in user_cache:
                        user_cache[owner_id]["total_otps"] = int(user_cache[owner_id].get("total_otps", 0)) + 1
                        user_cache[owner_id][category_total_field] = int(user_cache[owner_id].get(category_total_field, 0)) + 1
                        user_cache[owner_id][category_today_field] = int(user_cache[owner_id].get(category_today_field, 0)) + 1
                    if db:
                        try:
                            db.collection("users").document(str(owner_id)).update({
                                "total_otps": firestore.Increment(1),
                                category_total_field: firestore.Increment(1),
                                category_today_field: firestore.Increment(1),
                                "verified": True,
                            })
                        except Exception as e:
                            print(f"[API Number] stats update error: {e}")
                    save_local_db()

                    send_message(
                        owner_id,
                        _format_api_user_otp_message(
                            panel, number, str(sms), code,
                            range_text, reward
                        ),
                        reply_markup=main_menu(owner_id)
                    )
                    # Group message remains in the existing DX forward-group style.
                    _forward_api_otp_to_dx_groups(panel, number, str(sms), code, range_text)
        except Exception as e:
            print(f"[API Number] multi-panel monitor error: {e}")
        time.sleep(max(3, int(os.environ.get("MK_CHECK_INTERVAL", "5"))))


def _show_mk_admin(chat_id, message_id=None):
    text = (
        "🛰 <b>API PANEL CONTROL</b>\n\n"
        "Add authorized MK, Fast SMS, or NP Network API providers.\n"
        "ROUTES can set service, country, range, Free/Premium stock, and per-OTP reward."
    )
    if message_id:
        edit_message(chat_id, message_id, render_body_text(text), reply_markup=_mk_admin_keyboard())
    else:
        send_message(chat_id, render_body_text(text), reply_markup=_mk_admin_keyboard())

#==============================================================================
#  [41]  SAFE UPDATE WRAPPER & UPDATE NOTICES
#==============================================================================
def _safe_handle_update(handler, payload, label="update"):
    try:
        handler(payload)
    except Exception as e:
        print(f"❌ Handler error ({label}): {type(e).__name__}: {e}")


_DYNAMIC_SETTING_KEYS = {"brand_name", "button_emojis", "body_emojis", "user_menu_emojis", "user_menu_labels", "custom_messages", "card_templates", "traffic_forward_interval", "premium_apps", "premium_flags"}
_dynamic_settings_mtime = 0.0
_dynamic_settings_lock = threading.RLock()
_UPDATE_NOTICE_INTERVAL = 3600
_update_notice_lock = threading.RLock()
_update_notice_version = 0
_update_notice_text = ""
_update_notice_ack = {}
_update_notice_last_sent = {}


def _update_start_keyboard():
    # Keep the user's existing Reply Keyboard. The update notice behaves like
    # a stock broadcast and uses one inline action underneath it.
    return {"inline_keyboard": [[
        {"text": "START", "icon_custom_emoji_id": "5337132498965010628", "callback_data": "update_start", "style": "success"},
    ]]}


def _send_update_notice(user_id, force=False):
    with _update_notice_lock:
        version = _update_notice_version
        text = _update_notice_text
        last_sent = float(_update_notice_last_sent.get(str(user_id), 0) or 0)
    if not version or (not force and time.time() - last_sent < _UPDATE_NOTICE_INTERVAL):
        return False
    result = send_message(
        user_id,
        render_body_text(
            "<b>Bot Update Available</b>\n\n"
            f"{html.escape(text or 'The bot has been updated.')}\n\n"
            "Press <b>START</b> below to load the latest bot version. Your account data will be preserved."
        ),
        reply_markup=_update_start_keyboard(),
    )
    if result and result.get("ok"):
        with _update_notice_lock:
            if version == _update_notice_version:
                _update_notice_last_sent[str(user_id)] = time.time()
        return True
    return False


def _update_notice_broadcast_worker(version, users):
    for user_id in users:
        with _update_notice_lock:
            if version != _update_notice_version:
                return
        _send_update_notice(user_id, force=True)
        time.sleep(0.04)


def announce_user_update(reason="Bot updated"):
    global _update_notice_version, _update_notice_text
    with _update_notice_lock:
        _update_notice_version = int(time.time() * 1000)
        _update_notice_text = str(reason or "Bot updated")
        _update_notice_last_sent.clear()
        version = _update_notice_version
    users = list(all_known_users) if "all_known_users" in globals() else []
    if users:
        threading.Thread(target=_update_notice_broadcast_worker, args=(version, users), daemon=True).start()


def acknowledge_user_update(user_id):
    with _update_notice_lock:
        if _update_notice_version:
            _update_notice_ack[str(user_id)] = _update_notice_version
            _update_notice_last_sent.pop(str(user_id), None)


#==============================================================================
#  [42]  DYNAMIC SETTINGS MONITOR
#==============================================================================
def _apply_dynamic_settings(saved_settings):
    if not isinstance(saved_settings, dict):
        return False
    changed = False
    with _dynamic_settings_lock:
        for key in _DYNAMIC_SETTING_KEYS:
            if key not in saved_settings:
                continue
            value = saved_settings[key]
            if key == "custom_messages" and isinstance(value, dict):
                current = bot_settings.setdefault("custom_messages", {})
                for menu_key, menu_value in value.items():
                    normalized = menu_value if isinstance(menu_value, dict) else {"text": str(menu_value), "buttons": []}
                    if current.get(menu_key) != normalized:
                        current[menu_key] = normalized
                        changed = True
            elif key == "card_templates" and isinstance(value, dict):
                current = bot_settings.setdefault("card_templates", {})
                for card_key, card_value in value.items():
                    if isinstance(card_value, dict) and current.get(card_key) != card_value:
                        current[card_key] = card_value
                        changed = True
                for card_key, card_value in DEFAULT_CARD_TEMPLATES.items():
                    if card_key not in current:
                        current[card_key] = json.loads(json.dumps(card_value))
                        changed = True
            elif key != "custom_messages" and bot_settings.get(key) != value:
                bot_settings[key] = value
                changed = True
        if changed:
            sanitize_premium_assets()
    return changed


def refresh_dynamic_settings():
    """Reload editable names, emoji maps and custom messages without restart."""
    global _dynamic_settings_mtime
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_FILE)
    try:
        if os.path.exists(local_path):
            mtime = os.path.getmtime(local_path)
            if mtime <= _dynamic_settings_mtime:
                return False
            with open(local_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            changed = _apply_dynamic_settings(data.get("bot_settings", {}))
            _dynamic_settings_mtime = mtime
            return changed
        if db:
            doc = db.collection("settings").document("bot_config").get()
            if doc.exists:
                return _apply_dynamic_settings(doc.to_dict())
    except Exception as exc:
        print(f"⚠️ Dynamic settings refresh skipped: {type(exc).__name__}")
    return False


def dynamic_settings_monitor():
    while True:
        try:
            refresh_dynamic_settings()
        except Exception as exc:
            print(f"⚠️ Dynamic settings monitor error: {type(exc).__name__}")
        time.sleep(10)


#==============================================================================
#  [43]  ENTRY POINT — main()
#==============================================================================
def main():
    global BOT_USERNAME
    res = api_call("getMe")
    if res.get("ok"):
        BOT_USERNAME = res["result"].get("username", "")
    else:
        print(f"❌ getMe failed: {res}")
    # Keep the original Telegram profile name unchanged; dynamic name is message-only.
    # Polling cannot receive updates while a webhook is active.
    wh = api_call("deleteWebhook", {"drop_pending_updates": False})
    if wh and not wh.get("ok"):
        print(f"⚠️ deleteWebhook failed: {wh}")
    print(f"🤖 Bot is starting... @{BOT_USERNAME}")

    threading.Thread(target=panel_monitor_thread, daemon=True).start()
    threading.Thread(target=global_sms_listener, daemon=True).start()
    threading.Thread(target=voltx_sms_listener, daemon=True).start()
    threading.Thread(target=traffic_group_forwarder, daemon=True).start()
    threading.Thread(target=_api_monitor_thread, daemon=True).start()
    threading.Thread(target=premium_expiry_monitor, daemon=True).start()
    threading.Thread(target=dynamic_settings_monitor, daemon=True).start()
    all_known_users_ready.wait(timeout=2)
    print("📡 Background APIs, Global SMS Listener, API Number Monitor, Premium Monitor & Dynamic Settings Monitor Started!")

    # A bounded pool is faster and more stable than hundreds of competing sockets.
    worker_count = max(16, min(128, int(os.environ.get("BOT_WORKERS", "64"))))
    executor = ThreadPoolExecutor(max_workers=worker_count)

    offset = None
    while True:
        try:
            method = "getUpdates?timeout=50"
            if offset is not None:
                method += f"&offset={offset}"
            updates = api_call(method)
            if not updates or not updates.get("ok"):
                print(f"⚠️ getUpdates failed: {updates}")
                time.sleep(2)
                continue
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    executor.submit(_safe_handle_update, handle_message, update["message"], "message")
                elif "callback_query" in update:
                    executor.submit(_safe_handle_update, handle_callback, update["callback_query"], "callback_query")
        except Exception as e:
            print(f"❌ Polling loop error: {type(e).__name__}: {e}")
            time.sleep(2)

def _railway_health_server():
    """Tiny HTTP health endpoint for platforms that expect a listening port
    (e.g. Railway web services). Runs only when PORT is set."""
    port = os.environ.get("PORT")
    if not port:
        return
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"bot running")

            def log_message(self, *args):
                pass

        HTTPServer(("0.0.0.0", int(port)), _HealthHandler).serve_forever()
    except Exception as e:
        print(f"⚠️ Health server not started: {type(e).__name__}: {e}")


# Warm up Pillow in the background so the first board render is instant.
threading.Thread(target=lambda: _pil_ready(), daemon=True).start()
threading.Thread(target=_railway_health_server, daemon=True).start()


if __name__ == "__main__":
    main()

