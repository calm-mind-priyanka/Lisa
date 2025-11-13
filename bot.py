# bot.py
import os
import re
import time
import json
import sqlite3
import logging
import threading
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional
from telethon import TelegramClient, events, Button
from fastapi import FastAPI
import uvicorn
import aiohttp

# -------------------------
# CONFIG - set env vars or replace literal values
# -------------------------
API_ID = int(os.getenv("API_ID", "24222039"))       # from my.telegram.org
API_HASH = os.getenv("API_HASH", "6dd2dc70434b2f577f76a2e993135662")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE")
BOT_USERNAME = os.getenv("BOT_USERNAME", None)     # optional: your bot username without @
ADMIN_ID = int(os.getenv("ADMIN_ID", "6046055058"))

# DB path
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "files.db"

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pro_filestore")

# FastAPI health check
app = FastAPI()

# -------------------------
# DATABASE helpers
# -------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn(); cur = conn.cursor()
    # files table (keeps reply ids too)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            code TEXT PRIMARY KEY,
            owner_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            caption TEXT,
            file_type TEXT,
            created_at INTEGER,
            delete_at INTEGER,
            reply_chat_id INTEGER,
            reply_msg_id INTEGER
        )
    """)
    # settings table (global)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            auto_delete_enabled INTEGER DEFAULT 0,
            delete_seconds INTEGER DEFAULT 0,
            protect_content INTEGER DEFAULT 0
        )
    """)
    cur.execute("INSERT OR IGNORE INTO settings (id, auto_delete_enabled, delete_seconds, protect_content) VALUES (1,0,0,0)")
    # global verify defaults (kept but users can override)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verify_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            verify1_enabled INTEGER DEFAULT 0,
            verify1_shortener_template TEXT DEFAULT '',
            verify1_api_key TEXT DEFAULT '',
            verify2_enabled INTEGER DEFAULT 0,
            verify2_shortener_template TEXT DEFAULT '',
            verify2_api_key TEXT DEFAULT '',
            verify2_delay_seconds INTEGER DEFAULT 60
        )
    """)
    cur.execute("INSERT OR IGNORE INTO verify_settings (id) VALUES (1)")
    # per-user verify settings (each user can set their own shortener/template/key and enable flags)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_verify_settings (
            user_id INTEGER PRIMARY KEY,
            verify1_enabled INTEGER DEFAULT 0,
            verify1_shortener_template TEXT DEFAULT '',
            verify1_api_key TEXT DEFAULT '',
            verify2_enabled INTEGER DEFAULT 0,
            verify2_shortener_template TEXT DEFAULT '',
            verify2_api_key TEXT DEFAULT '',
            verify2_delay_seconds INTEGER DEFAULT 60
        )
    """)
    conn.commit(); conn.close()

# file helpers
def add_file_record(code, owner_id, file_id, file_name, caption, file_type, created_at=None, delete_at=None, reply_chat_id=None, reply_msg_id=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO files (code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, owner_id, file_id, file_name, caption, file_type, int(created_at or time.time()), int(delete_at) if delete_at else None, reply_chat_id, reply_msg_id))
    conn.commit(); conn.close()

def get_file_record(code):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id FROM files WHERE code = ?", (code,))
    row = cur.fetchone(); conn.close()
    return row

def delete_file_record(code):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE code = ?", (code,))
    conn.commit(); conn.close()

def list_user_files(user_id, limit=50):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, file_name, caption, created_at, delete_at FROM files WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    rows = cur.fetchall(); conn.close()
    return rows

def list_scheduled_deletes_future():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, delete_at FROM files WHERE delete_at IS NOT NULL")
    rows = cur.fetchall(); conn.close()
    return rows

# settings getters/setters
def get_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT auto_delete_enabled, delete_seconds, protect_content FROM settings WHERE id = 1")
    row = cur.fetchone(); conn.close()
    return {"auto_delete_enabled": bool(row[0]), "delete_seconds": int(row[1]), "protect_content": bool(row[2])}

def set_setting(auto_delete=None, delete_seconds=None, protect_content=None):
    conn = get_conn(); cur = conn.cursor()
    if auto_delete is not None:
        cur.execute("UPDATE settings SET auto_delete_enabled = ? WHERE id = 1", (1 if auto_delete else 0,))
    if delete_seconds is not None:
        cur.execute("UPDATE settings SET delete_seconds = ? WHERE id = 1", (int(delete_seconds),))
    if protect_content is not None:
        cur.execute("UPDATE settings SET protect_content = ? WHERE id = 1", (1 if protect_content else 0,))
    conn.commit(); conn.close()

# verify settings getters/setters (global defaults)
def get_verify_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT verify1_enabled, verify1_shortener_template, verify1_api_key, verify2_enabled, verify2_shortener_template, verify2_api_key, verify2_delay_seconds FROM verify_settings WHERE id = 1")
    row = cur.fetchone(); conn.close()
    return {
        "verify1_enabled": bool(row[0]),
        "verify1_shortener_template": row[1] or "",
        "verify1_api_key": row[2] or "",
        "verify2_enabled": bool(row[3]),
        "verify2_shortener_template": row[4] or "",
        "verify2_api_key": row[5] or "",
        "verify2_delay_seconds": int(row[6] or 60)
    }

def set_verify_settings(**kwargs):
    conn = get_conn(); cur = conn.cursor()
    allowed = ["verify1_enabled","verify1_shortener_template","verify1_api_key","verify2_enabled","verify2_shortener_template","verify2_api_key","verify2_delay_seconds"]
    for k,v in kwargs.items():
        if k in allowed:
            cur.execute(f"UPDATE verify_settings SET {k} = ? WHERE id = 1", (1 if (k.endswith("_enabled") and v) else v,))
    conn.commit(); conn.close()

# per-user verify settings
def get_user_verify_settings(user_id: int):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT verify1_enabled, verify1_shortener_template, verify1_api_key, verify2_enabled, verify2_shortener_template, verify2_api_key, verify2_delay_seconds FROM user_verify_settings WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        # return global defaults if user does not have settings
        conn.close()
        global_defaults = get_verify_settings()
        return global_defaults
    conn.close()
    return {
        "verify1_enabled": bool(row[0]),
        "verify1_shortener_template": row[1] or "",
        "verify1_api_key": row[2] or "",
        "verify2_enabled": bool(row[3]),
        "verify2_shortener_template": row[4] or "",
        "verify2_api_key": row[5] or "",
        "verify2_delay_seconds": int(row[6] or 60)
    }

def set_user_verify_settings(user_id: int, **kwargs):
    # Upsert: create if not exists, then update fields
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO user_verify_settings (user_id) VALUES (?)", (user_id,))
    allowed = ["verify1_enabled","verify1_shortener_template","verify1_api_key","verify2_enabled","verify2_shortener_template","verify2_api_key","verify2_delay_seconds"]
    for k,v in kwargs.items():
        if k in allowed:
            cur.execute(f"UPDATE user_verify_settings SET {k} = ? WHERE user_id = ?", (1 if (k.endswith("_enabled") and v) else v, user_id))
    conn.commit(); conn.close()

# -------------------------
# Utilities
# -------------------------
def gen_code():
    return uuid.uuid4().hex[:12]

# improved URL + mention regex (removes http(s), www, t.me, telegram.me, and @user)
_url_re = re.compile(r'(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)', flags=re.IGNORECASE)
_mention_re = re.compile(r'@[\w_]+')
_channel_link_re = re.compile(r'tg://joinchat/\S+', flags=re.IGNORECASE)

def sanitize_caption(text: str):
    if not text:
        return ""
    t = _url_re.sub("", text)
    t = _mention_re.sub("", t)
    t = _channel_link_re.sub("", t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def parse_duration(s: str):
    s = s.strip().lower()
    if s == "off":
        return 0
    m = re.match(r'^(\d+)\s*([smhd])$', s)
    if not m:
        return None
    val = int(m.group(1)); unit = m.group(2)
    if unit == 's': return val
    if unit == 'm': return val * 60
    if unit == 'h': return val * 3600
    if unit == 'd': return val * 86400
    return None

def human_seconds(sec: int):
    if not sec or sec <= 0: return "N/A"
    parts = []
    d, r = divmod(sec, 86400)
    if d: parts.append(f"{d}d")
    h, r = divmod(r, 3600)
    if h: parts.append(f"{h}h")
    m, r = divmod(r, 60)
    if m: parts.append(f"{m}m")
    if r: parts.append(f"{r}s")
    return " ".join(parts)

def is_admin(uid: int):
    return uid == ADMIN_ID

# -------------------------
# Telethon client
# -------------------------
client = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

async def ensure_username():
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await client.get_me()
        BOT_USERNAME = getattr(me, "username", None)

# -------------------------
# Auto-delete scheduler (async tasks)
# -------------------------
scheduled_tasks = {}  # code -> asyncio.Task

async def _delete_messages_safe(pairs: List[Tuple[int,int]]):
    """Delete given messages (chat_id, msg_id) safely."""
    for chat_id, msg_id in pairs:
        try:
            await client.delete_messages(chat_id, [msg_id])
        except Exception:
            log.warning("Could not delete message %s in chat %s", msg_id, chat_id)

async def schedule_delete(code: str, when_ts: int, extra_messages: Optional[List[Tuple[int,int]]] = None):
    """Schedule deletion of DB record and optionally messages at when_ts.
       extra_messages: list of (chat_id, msg_id) to delete at that time (e.g. per-download file+notice)
    """
    now = int(time.time())
    delay = max(0, when_ts - now)
    if code in scheduled_tasks:
        try:
            scheduled_tasks[code].cancel()
        except Exception:
            pass

    async def _job():
        try:
            await asyncio.sleep(delay)
            # attempt to delete any DB-stored reply message first
            rec = get_file_record(code)
            msgs_to_delete = []
            if rec:
                _, _, _, _, _, _, _, _, reply_chat_id, reply_msg_id = rec
                if reply_chat_id and reply_msg_id:
                    msgs_to_delete.append((reply_chat_id, reply_msg_id))
            # include extra messages passed when scheduling (per-download)
            if extra_messages:
                msgs_to_delete.extend(extra_messages)
            if msgs_to_delete:
                await _delete_messages_safe(msgs_to_delete)
            # delete DB record
            delete_file_record(code)
            log.info("Auto-deleted file %s and cleaned messages", code)
            scheduled_tasks.pop(code, None)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Error in scheduled delete for %s", code)

    task = asyncio.create_task(_job())
    scheduled_tasks[code] = task

async def reschedule_all():
    rows = list_scheduled_deletes_future()
    now = int(time.time())
    for code, delete_at in rows:
        if delete_at and delete_at > now:
            await schedule_delete(code, delete_at)
        elif delete_at and delete_at <= now:
            # expired - remove now
            delete_file_record(code)
            log.info("Removed expired file at startup %s", code)

# -------------------------
# Verification: in-memory user+code verified map (short-lived)
# -------------------------
# key: (user_id, code) -> timestamp
verified_stage1 = {}   # (user_id, code) -> ts
verified_stage2 = {}   # (user_id, code) -> ts

# helper to call shortener API (expects JSON with {"short":"..."} by default or raw http in response)
async def call_shortener(template: str, api_key: str, target_url: str) -> Optional[str]:
    if not template:
        return None
    try:
        url = template.format(api_key=api_key, url=target_url)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=12) as resp:
                text = await resp.text()
                # try parse JSON
                try:
                    j = json.loads(text)
                    for k in ("short","short_url","url","result"):
                        if k in j and isinstance(j[k], str) and j[k].startswith("http"):
                            return j[k]
                except Exception:
                    # fallback: if raw text looks like http...
                    m = re.search(r'https?://\S+', text)
                    if m:
                        return m.group(0)
    except Exception:
        log.exception("Shortener call failed")
    return None

# -------------------------
# Pending setter dict (user -> action)
# -------------------------
pending_setter = {}  # user_id -> action like 'SET_VERIFY1_SHORT'

# -------------------------
# Handlers: /start, deep link, settings
# -------------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
async def start_handler(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await ensure_username()
        s = get_settings()
        text = (
            "👋 WELCOME TO PRO FILESTORE BOT\n\n"
            "📦 SEND ANY FILE (OR FORWARD) AND I'LL GENERATE A PERMANENT SHARE LINK.\n"
            f"🔒 AUTO-DELETE: **{'ON' if s['auto_delete_enabled'] else 'OFF'}**\n"
            f"⏳ DELETE AFTER: **{human_seconds(s['delete_seconds'])}**\n"
            f"🚫 FORWARD PROTECTION: **{'ON' if s['protect_content'] else 'OFF'}**\n\n"
            "USE THE MENU BELOW OR SEND A FILE."
        )
        buttons = [
            [Button.inline("📁 MY FILES", b"my_files")],
            [Button.inline("⚙️ SETTINGS", b"admin_panel")],
            [Button.inline("🔐 VERIFY", b"verify_panel")]  # user-level verify manager
        ]
        await event.respond(text, buttons=buttons, link_preview=False)
        return

    # deep link expected to be file_<code>
    if arg.startswith("file_"):
        code = arg.split("file_", 1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ FILE NOT FOUND OR EXPIRED.")
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()

        # Check per-user verify settings first, fallback to global
        user = await event.get_sender()
        uid = user.id if user else event.sender_id
        u_v = get_user_verify_settings(uid)

        key1 = (uid, code)
        # If VERIFY1 is enabled for this user, and the user hasn't completed stage1 -> show VERIFY menu
        if u_v["verify1_enabled"] and key1 not in verified_stage1:
            # prepare verify menu (uppercase text as requested)
            await ensure_username()
            deep_verify_payload = f"VERIFY1|{code}"
            btns = []
            btns.append([Button.inline("✅ VERIFY (BOT)", f"verify1|{code}")])
            # if user has a shortener template, try to build short link
            if u_v["verify1_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start={deep_verify_payload}"
                    short = await call_shortener(u_v["verify1_shortener_template"], u_v["verify1_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 VERIFY VIA SHORT LINK", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ BACK", b"back")])
            text = (
                "🔐 HERE YOU MUST COMPLETE VERIFY 1 BEFORE RECEIVING THE FILE.\n"
                "YOU CAN PRESS VERIFY (BOT) OR USE YOUR SHORTENER LINK IF SET."
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # If VERIFY1 passed and VERIFY2 is enabled but not yet completed -> ask for VERIFY2
        key2 = (uid, code)
        if u_v["verify2_enabled"] and key1 in verified_stage1 and key2 not in verified_stage2:
            await ensure_username()
            btns = [[Button.inline("✅ COMPLETE VERIFY 2 (BOT)", f"verify2|{code}")]]
            if u_v["verify2_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start=VERIFY2|{code}"
                    short = await call_shortener(u_v["verify2_shortener_template"], u_v["verify2_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 VERIFY2 VIA SHORT LINK", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ BACK", b"back")])
            text = (
                "🔐 VERIFY 2 IS REQUIRED. COMPLETE IT TO RECEIVE THE FILE.\n"
                f"VERIFY2 WAIT TIME: {human_seconds(u_v['verify2_delay_seconds'])}"
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # Passed verification (or verification not required) -> send file
        try:
            file_msg = await client.send_file(event.sender_id, file=file_id, caption=(caption or file_name), force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("FAILED TO SEND FILE FOR CODE %s", code)
            await event.respond("⚠️ FAILED TO SEND FILE. TRY AGAIN LATER.")
            return

        # if auto-delete configured for this file, compute remaining seconds and schedule deletion
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. PLEASE SAVE NOW IF NEEDED."
                try:
                    notice_msg = await client.send_message(event.sender_id, notice_text, reply_to=file_msg.id)
                    extra = [(event.sender_id, file_msg.id), (event.sender_id, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("FAILED TO SEND NOTICE OR SCHEDULE PER-DOWNLOAD DELETE FOR %s", code)
        return

    await event.respond("UNKNOWN START PARAMETER. SEND A FILE TO GENERATE A LINK.")

# -------------------------
# Callbacks: verify buttons & menus & admin verify config pages (uppercase text)
# -------------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode() if event.data else ""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id

    # BACK - universal
    if data == "back":
        await ensure_username()
        text = (
            "👋 WELCOME BACK!\n\n"
            "SEND A FILE OR USE THE MENU BELOW."
        )
        btns = [[Button.inline("📁 MY FILES", b"my_files")], [Button.inline("⚙️ SETTINGS", b"admin_panel")], [Button.inline("🔐 VERIFY", b"verify_panel")]]
        try:
            await event.edit(text, buttons=btns)
        except Exception:
            await event.answer("OK")
        return

    # VERIFY PANEL (USER-FACING) - uppercase layout as requested
    if data == "verify_panel":
        # This page is available to all users (they can set their own verify settings)
        u_v = get_user_verify_settings(uid)
        text = (
            "HERE YOU CAN MANAGE YOUR VERIFICATION PROCESS. YOU CAN TURN ON/OFF & SET TIME FOR 2ND VERIFICATION AND ALSO SHORTENERS FOR VERIFY.\n\n"
            "VERIFY 1     VERIFY 2     SET VERIFY 2 TIME    << BACK"
        )
        buttons = [
            [Button.inline("VERIFY 1", b"verify1_page"), Button.inline("VERIFY 2", b"verify2_page")],
            [Button.inline("SET VERIFY 2 TIME", b"set_verify2_time"), Button.inline("⬅ BACK", b"back")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # VERIFY1 PAGE (USER)
    if data == "verify1_page":
        u_v = get_user_verify_settings(uid)
        text = (
            "VERIFY 1 SETTINGS:\n\n"
            f"SHORTENER: {'SET' if u_v['verify1_shortener_template'] else 'NOT SET'}\n"
            f"API KEY: {'SET' if u_v['verify1_api_key'] else 'NOT SET'}\n"
            f"STATUS: {'ON' if u_v['verify1_enabled'] else 'OFF'}\n\n"
            "TURN VERIFY1 ON/OFF - SET SHORTENER - SET API KEY - << BACK"
        )
        buttons = [
            [Button.inline("TURN VERIFY1 ON/OFF", b"toggle_verify1_btn")],
            [Button.inline("SET VERIFY1 SHORTENER", b"set_verify1_short"), Button.inline("SET VERIFY1 API KEY", b"set_verify1_key")],
            [Button.inline("⬅ BACK", b"verify_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # VERIFY2 PAGE (USER)
    if data == "verify2_page":
        u_v = get_user_verify_settings(uid)
        text = (
            "VERIFY 2 SETTINGS:\n\n"
            f"SHORTENER: {'SET' if u_v['verify2_shortener_template'] else 'NOT SET'}\n"
            f"API KEY: {'SET' if u_v['verify2_api_key'] else 'NOT SET'}\n"
            f"STATUS: {'ON' if u_v['verify2_enabled'] else 'OFF'}\n"
            f"VERIFY2 DELAY: {human_seconds(u_v['verify2_delay_seconds'])}\n\n"
            "TURN VERIFY2 ON/OFF - SET SHORTENER - SET API KEY - << BACK"
        )
        buttons = [
            [Button.inline("TURN VERIFY2 ON/OFF", b"toggle_verify2_btn")],
            [Button.inline("SET VERIFY2 SHORTENER", b"set_verify2_short"), Button.inline("SET VERIFY2 API KEY", b"set_verify2_key")],
            [Button.inline("⬅ BACK", b"verify_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # SET VERIFY2 TIME - user flow: instruct to send a time string
    if data == "set_verify2_time":
        await event.edit(
            "HERE YOU CAN MANAGE YOUR GROUP 2ND VERIFICATION TIME.\n\n"
            "SEND ME A TIME LIKE `60s`, `2m`, `1h` OR SEND `CANCEL` TO ABORT.\n\n"
            "⬅ BACK",
            buttons=[[Button.inline("⬅ BACK", b"verify_panel")]]
        )
        # register pending setter for user
        pending_setter[uid] = "SET_VERIFY2_TIME"
        return

    # Toggle verify1 for user
    if data == "toggle_verify1_btn":
        u_v = get_user_verify_settings(uid)
        # If shortener not set and trying to turn on -> complain as requested
        if not u_v["verify1_shortener_template"] and not u_v["verify1_enabled"]:
            # Attempting to turn ON but no shortener set
            await event.answer("SET VERIFY 1 SHORTENER FIRST ❗", alert=True)
            return
        new = not u_v["verify1_enabled"]
        set_user_verify_settings(uid, verify1_enabled=1 if new else 0)
        await event.edit(f"VERIFY1 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"verify1_page")]])
        return

    # Toggle verify2 for user
    if data == "toggle_verify2_btn":
        u_v = get_user_verify_settings(uid)
        new = not u_v["verify2_enabled"]
        set_user_verify_settings(uid, verify2_enabled=1 if new else 0)
        await event.edit(f"VERIFY2 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"verify2_page")]])
        return

    # Set shortener/key actions for user
    if data in ("set_verify1_short", "set_verify1_key", "set_verify2_short", "set_verify2_key"):
        # Prompt the user to send the template/key as a message
        label_map = {
            "set_verify1_short": "SEND VERIFY1 SHORTENER TEMPLATE (USE {api_key} AND {url}). EXAMPLE: https://api.short.example/create?api_key={api_key}&url={url}",
            "set_verify1_key": "SEND VERIFY1 API KEY (OR SEND CANCEL).",
            "set_verify2_short": "SEND VERIFY2 SHORTENER TEMPLATE (USE {api_key} AND {url}).",
            "set_verify2_key": "SEND VERIFY2 API KEY (OR SEND CANCEL)."
        }
        await event.edit("✅ " + label_map[data] + "\n\nSEND 'CANCEL' TO ABORT.", buttons=[[Button.inline("⬅ BACK", b"verify_panel")]])
        pending_setter[uid] = data.upper()  # store in uppercase tag
        return

    # VERIFY (inline) - user clicking verify button on file flow
    if data.startswith("verify1|"):
        _, code = data.split("|",1)
        verified_stage1[(uid, code)] = int(time.time())
        await event.answer("✅ VERIFY1 COMPLETED. SENDING FILE...", alert=True)
        rec = get_file_record(code)
        if not rec:
            await event.answer("FILE NOT FOUND.", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=(caption or file_name), force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("FAILED TO SEND FILE IN VERIFY1 CALLBACK FOR %s", code)
            await event.answer("FAILED TO SEND FILE. TRY AGAIN LATER.", alert=True)
            return
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. PLEASE SAVE NOW IF NEEDED."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("FAILED SCHEDULE PER-DOWNLOAD DELETE FOR %s", code)
        return

    if data.startswith("verify2|"):
        _, code = data.split("|",1)
        verified_stage2[(uid, code)] = int(time.time())
        await event.answer("✅ VERIFY2 COMPLETED. SENDING FILE...", alert=True)
        rec = get_file_record(code)
        if not rec:
            await event.answer("FILE NOT FOUND.", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=(caption or file_name), force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("FAILED TO SEND FILE IN VERIFY2 CALLBACK FOR %s", code)
            await event.answer("FAILED TO SEND FILE. TRY AGAIN LATER.", alert=True)
            return
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. PLEASE SAVE NOW IF NEEDED."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("FAILED SCHEDULE PER-DOWNLOAD DELETE FOR %s", code)
        return

    # ADMIN PANEL (keeps original admin functionality + BACK nav)
    if data == "admin_panel":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True)
            return
        s = get_settings(); v = get_verify_settings()
        text = (
            "⚙️ ADMIN PANEL\n\n"
            f"AUTO-DELETE: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
            f"DELETE AFTER: {human_seconds(s['delete_seconds'])}\n"
            f"PROTECT CONTENT: {'ON' if s['protect_content'] else 'OFF'}\n\n"
            f"GLOBAL VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}\n"
            f"GLOBAL VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}\n\n"
            "USE BUTTONS BELOW TO MANAGE GLOBAL SETTINGS."
        )
        buttons = [
            [Button.inline("TOGGLE AUTO-DELETE", b"toggle_autodel_btn"), Button.inline("TOGGLE PROTECT", b"toggle_protect_btn")],
            [Button.inline("VERIFY SETTINGS (GLOBAL)", b"verify_panel_global")],
            [Button.inline("⬅ BACK", b"back")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # GLOBAL VERIFY PANEL (ADMIN)
    if data == "verify_panel_global":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True)
            return
        v = get_verify_settings()
        text = (
            "GLOBAL VERIFY SETTINGS (ADMIN):\n\n"
            f"VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}\n"
            f"VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}\n\n"
            "USE BUTTONS BELOW TO TOGGLE OR SET GLOBAL SHORTENERS/KEYS."
        )
        buttons = [
            [Button.inline("TOGGLE VERIFY1", b"toggle_verify1_global"), Button.inline("TOGGLE VERIFY2", b"toggle_verify2_global")],
            [Button.inline("SET VERIFY1 SHORTENER (GLOBAL)", b"set_verify1_short_global"), Button.inline("SET VERIFY1 API KEY (GLOBAL)", b"set_verify1_key_global")],
            [Button.inline("SET VERIFY2 SHORTENER (GLOBAL)", b"set_verify2_short_global"), Button.inline("SET VERIFY2 API KEY (GLOBAL)", b"set_verify2_key_global")],
            [Button.inline("⬅ BACK", b"admin_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Toggle global verify1/verify2 (ADMIN)
    if data == "toggle_verify1_global":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings(); new = not v["verify1_enabled"]; set_verify_settings(verify1_enabled=1 if new else 0)
        await event.edit(f"GLOBAL VERIFY1 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"verify_panel_global")]])
        return
    if data == "toggle_verify2_global":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings(); new = not v["verify2_enabled"]; set_verify_settings(verify2_enabled=1 if new else 0)
        await event.edit(f"GLOBAL VERIFY2 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"verify_panel_global")]])
        return

    # Global shortener/key setters (ADMIN) - prompt then pending_setter
    admin_set_map = {
        "set_verify1_short_global": "SET_VERIFY1_SHORT_GLOBAL",
        "set_verify1_key_global": "SET_VERIFY1_KEY_GLOBAL",
        "set_verify2_short_global": "SET_VERIFY2_SHORT_GLOBAL",
        "set_verify2_key_global": "SET_VERIFY2_KEY_GLOBAL"
    }
    if data in admin_set_map:
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True); return
        await event.edit("✅ SEND THE TEMPLATE/KEY AS PLAIN MESSAGE (USE {api_key} AND {url}). SEND 'CANCEL' TO ABORT.", buttons=[[Button.inline("⬅ BACK", b"verify_panel_global")]])
        pending_setter[uid] = admin_set_map[data]
        return

    # Inline toggle auto-delete / protect buttons (admin)
    if data == "toggle_autodel_btn":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True); return
        s = get_settings(); new = not s["auto_delete_enabled"]; set_setting(auto_delete=new)
        await event.edit(f"AUTO-DELETE IS NOW {'ON' if new else 'OFF'}.")
        return

    if data == "toggle_protect_btn":
        if not is_admin(uid):
            await event.answer("ADMIN ONLY", alert=True); return
        s = get_settings(); new = not s["protect_content"]; set_setting(protect_content=new)
        await event.edit(f"PROTECT CONTENT IS NOW {'ON' if new else 'OFF'}.")
        return

    # MY FILES handling via callback
    if data == "my_files":
        rows = list_user_files(uid, limit=30)
        if not rows:
            await event.edit("📂 YOU DON'T HAVE ANY SAVED FILES.", buttons=[[Button.inline("⬅ BACK", b"back")]])
            return
        await ensure_username()
        btns = []
        for code, name, caption, created_at, delete_at in rows:
            label = (name or caption or "file")[:28]
            btns.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
        btns.append([Button.inline("⬅ BACK", b"back")])
        await event.edit("📁 YOUR FILES:", buttons=btns)
        return

    # Delete button pressed (del_<code>)
    if data.startswith("del_"):
        code = data.split("_",1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.answer("FILE NOT FOUND", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        if uid != owner_id and not is_admin(uid):
            await event.answer("ONLY OWNER OR ADMIN CAN DELETE", alert=True)
            return
        # delete saved reply if exists
        if reply_chat_id and reply_msg_id:
            try:
                await client.delete_messages(reply_chat_id, [reply_msg_id])
            except Exception:
                pass
        delete_file_record(code)
        if code in scheduled_tasks:
            try:
                scheduled_tasks[code].cancel()
            except Exception:
                pass
            scheduled_tasks.pop(code, None)
        await event.edit(f"✅ DELETED FILE: {file_name or code}")
        return

    await event.answer("UNKNOWN ACTION", alert=True)

# -------------------------
# Pending setter message handler (user/admin sends actual templates/keys or times)
# -------------------------
@client.on(events.NewMessage(incoming=True))
async def handle_pending_setters(event):
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id
    if uid not in pending_setter:
        return  # not in setter flow
    action = pending_setter.pop(uid)
    text = (event.raw_text or "").strip()
    if text.lower() == "cancel":
        await event.reply("CANCELLED.")
        return

    # USER actions (uppercase markers set earlier)
    if action == "SET_VERIFY1_SHORT":
        set_user_verify_settings(uid, verify1_shortener_template=text)
        await event.reply("✅ VERIFY1 SHORTENER TEMPLATE SAVED.")
        return
    if action == "SET_VERIFY1_KEY":
        set_user_verify_settings(uid, verify1_api_key=text)
        await event.reply("✅ VERIFY1 API KEY SAVED.")
        return
    if action == "SET_VERIFY2_SHORT":
        set_user_verify_settings(uid, verify2_shortener_template=text)
        await event.reply("✅ VERIFY2 SHORTENER TEMPLATE SAVED.")
        return
    if action == "SET_VERIFY2_KEY":
        set_user_verify_settings(uid, verify2_api_key=text)
        await event.reply("✅ VERIFY2 API KEY SAVED.")
        return
    if action == "SET_VERIFY2_TIME":
        sec = parse_duration(text)
        if sec is None:
            await event.reply("INVALID DURATION. USE LIKE `30s`, `2m`, `1h`, `1d` OR SEND CANCEL.")
            return
        set_user_verify_settings(uid, verify2_delay_seconds=sec)
        await event.reply(f"✅ VERIFY2 DELAY SET TO {human_seconds(sec)}.")
        return

    # ADMIN actions (global)
    if action == "SET_VERIFY1_SHORT_GLOBAL" and is_admin(uid):
        set_verify_settings(verify1_shortener_template=text)
        await event.reply("✅ GLOBAL VERIFY1 SHORTENER TEMPLATE SAVED.")
        return
    if action == "SET_VERIFY1_KEY_GLOBAL" and is_admin(uid):
        set_verify_settings(verify1_api_key=text)
        await event.reply("✅ GLOBAL VERIFY1 API KEY SAVED.")
        return
    if action == "SET_VERIFY2_SHORT_GLOBAL" and is_admin(uid):
        set_verify_settings(verify2_shortener_template=text)
        await event.reply("✅ GLOBAL VERIFY2 SHORTENER TEMPLATE SAVED.")
        return
    if action == "SET_VERIFY2_KEY_GLOBAL" and is_admin(uid):
        set_verify_settings(verify2_api_key=text)
        await event.reply("✅ GLOBAL VERIFY2 API KEY SAVED.")
        return

    # fallback
    await event.reply("RECEIVED. (NO ACTION APPLIED)")

# -------------------------
# Admin commands (text) for verify time and basic settings
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setverify2time\s+(.+)$"))
async def cmd_setverify2time(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ ONLY ADMIN CAN SET GLOBAL VERIFY2 TIME.")
        return
    arg = event.pattern_match.group(1)
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("INVALID DURATION. USE LIKE `30s`, `2m`, `1h`, `1d`.")
        return
    set_verify_settings(verify2_delay_seconds=sec)
    await event.reply(f"✅ GLOBAL VERIFY2 DELAY SET TO {human_seconds(sec)}.")

# -------------------------
# Admin commands: setautodelete, setforward, settings, myfiles (text versions)
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setautodelete(?:\s+(.+))?$"))
async def cmd_setautodelete(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ ONLY ADMIN CAN SET AUTO-DELETE.")
        return
    arg = event.pattern_match.group(1)
    if not arg:
        await event.reply("USAGE: /setautodelete <30s|2m|1h|1d|off>")
        return
    if arg.strip().lower() == "off":
        set_setting(delete_seconds=0); set_setting(auto_delete=False)
        await event.reply("✅ AUTO-DELETE DISABLED."); return
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("❌ INVALID DURATION. USE LIKE `30s`,`2m`,`1h`,`1d`.")
        return
    set_setting(delete_seconds=sec); set_setting(auto_delete=True)
    await event.reply(f"✅ AUTO-DELETE ENABLED. FILES WILL BE REMOVED AFTER {human_seconds(sec)}.")

@client.on(events.NewMessage(pattern=r"^/setforward\s+(\w+)$"))
async def cmd_setforward(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ ONLY ADMIN CAN CHANGE FORWARD PROTECTION.")
        return
    arg = event.pattern_match.group(1).lower()
    if arg not in ("on","off"):
        await event.reply("USAGE: /setforward <on|off>"); return
    set_setting(protect_content=(arg=="on"))
    await event.reply(f"✅ PROTECT CONTENT SET TO {'ON' if arg=='on' else 'OFF'}.")

@client.on(events.NewMessage(pattern=r"^/settings$"))
async def cmd_settings(event):
    sender = await event.get_sender()
    s = get_settings(); v = get_verify_settings()
    text = (
        f"⚙️ SETTINGS\n\n"
        f"• AUTO-DELETE: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
        f"• DELETE AFTER: {human_seconds(s['delete_seconds'])}\n"
        f"• PROTECT CONTENT: {'ON' if s['protect_content'] else 'OFF'}\n\n"
        f"🔐 GLOBAL VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}  SHORT: {'SET' if v['verify1_shortener_template'] else 'NOT SET'}\n"
        f"🔐 GLOBAL VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}  SHORT: {'SET' if v['verify2_shortener_template'] else 'NOT SET'}  DELAY: {human_seconds(v['verify2_delay_seconds'])}\n\n"
        "USE INLINE BUTTONS BELOW TO MANAGE SETTINGS."
    )
    buttons = [
        [Button.inline("TOGGLE AUTO-DELETE", b"toggle_autodel_btn"), Button.inline("TOGGLE PROTECT", b"toggle_protect_btn")],
        [Button.inline("VERIFY (USER PANEL)", b"verify_panel")],
        [Button.inline("⬅ BACK", b"back")]
    ]
    await event.reply(text, buttons=buttons)

# -------------------------
# My files listing (text)
# -------------------------
@client.on(events.NewMessage(pattern=r"^/myfiles$"))
async def cmd_myfiles(event):
    sender = await event.get_sender()
    rows = list_user_files(sender.id, limit=50)
    if not rows:
        await event.reply("📂 YOU HAVE NO SAVED FILES."); return
    await ensure_username()
    buttons = []
    for code, name, caption, created_at, delete_at in rows:
        label = (name or caption or "FILE")[:30]
        buttons.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
    await event.reply("📁 YOUR FILES:", buttons=buttons)

# -------------------------
# File save handler (accept direct and forwarded)
# -------------------------
@client.on(events.NewMessage(incoming=True))
async def handle_incoming(event):
    # if message has file, process saving
    msg = event.message
    if not msg or not getattr(msg, "file", None):
        return

    sender = await event.get_sender()
    if not sender:
        return

    original_caption = (msg.message or "") if getattr(msg, "message", None) else (msg.text or "")
    sanitized_caption = sanitize_caption(original_caption)

    file_obj = msg.file
    file_id = getattr(file_obj, "id", None)
    file_id = str(file_id)
    file_name = getattr(file_obj, "name", None) or ""
    file_type = getattr(file_obj, "mime_type", None) or ""

    code = gen_code()
    created_at = int(time.time())
    s = get_settings()
    delete_at = None
    if s["auto_delete_enabled"] and s["delete_seconds"] > 0:
        delete_at = created_at + s["delete_seconds"]

    # reply so user sees link; capture reply message id so we can delete it later
    await ensure_username()
    share_link = f"https://t.me/{BOT_USERNAME}?start=file_{code}"
    btns = [
        [Button.url("📎 GET / SHARE LINK", share_link)],
        [Button.inline("📁 MY FILES", b"my_files"), Button.inline("🗑 DELETE", f"del_{code}".encode())]
    ]
    delete_msg_text = f"\n\n⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(s['delete_seconds'])}." if delete_at else ""
    reply_text = (
        f"✅ FILE SAVED SUCCESSFULLY!\n\n"
        f"📄 NAME: `{file_name or 'UNNAMED'}`\n"
        f"💬 CAPTION: {sanitized_caption or '—'}\n"
        f"🔗 SHARE LINK: {share_link}"
        f"{delete_msg_text}"
    )
    try:
        reply_obj = await event.reply(reply_text, buttons=btns, link_preview=False)
        reply_chat_id = reply_obj.chat_id
        reply_msg_id = reply_obj.id
    except Exception:
        reply_chat_id = None
        reply_msg_id = None

    # store record (store reply ids so the saved message can be deleted when auto-delete fires)
    add_file_record(code=code, owner_id=sender.id, file_id=file_id, file_name=file_name, caption=sanitized_caption, file_type=file_type, created_at=created_at, delete_at=delete_at, reply_chat_id=reply_chat_id, reply_msg_id=reply_msg_id)

    # schedule DB delete + attempt to delete saved reply message when time arrives
    if delete_at:
        try:
            await schedule_delete(code, delete_at)
        except Exception:
            log.exception("FAILED SCHEDULING DELETE FOR %s", code)

    log.info("SAVED FILE CODE=%s OWNER=%s FILE_ID=%s", code, sender.id, file_id)

# -------------------------
# Startup tasks & FastAPI
# -------------------------
@app.get("/")
async def health():
    return {"status": "running"}

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

async def startup_tasks():
    await ensure_username()
    await reschedule_all()

# -------------------------
# Main
# -------------------------
def main():
    init_db()
    # start fastapi thread
    threading.Thread(target=run_fastapi, daemon=True).start()
    # start telethon with startup scheduling
    loop = asyncio.get_event_loop()
    loop.create_task(startup_tasks())
    log.info("STARTING TELEGRAM CLIENT...")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
