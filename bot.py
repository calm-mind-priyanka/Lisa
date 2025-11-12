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

# Admin user id (yours)
ADMIN_ID = 6046055058

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
    # settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            auto_delete_enabled INTEGER DEFAULT 0,
            delete_seconds INTEGER DEFAULT 0,
            protect_content INTEGER DEFAULT 0
        )
    """)
    cur.execute("INSERT OR IGNORE INTO settings (id, auto_delete_enabled, delete_seconds, protect_content) VALUES (1,0,0,0)")
    # verify settings table
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

# verify settings getters/setters
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
# key: (user_id, code) -> timestamp of verify1 success
verified_stage1 = {}   # (user_id, code) -> ts
verified_stage2 = {}   # (user_id, code) -> ts

# helper to call shortener API (expects JSON with {"short":"..."} by default)
async def call_shortener(template: str, api_key: str, target_url: str) -> Optional[str]:
    if not template:
        return None
    try:
        url = template.format(api_key=api_key, url=target_url)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=10) as resp:
                text = await resp.text()
                # try parse JSON
                try:
                    j = json.loads(text)
                    # common fields: "short", "short_url", "result"
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
# Handlers: /start, deep link, settings
# -------------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
async def start_handler(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await ensure_username()
        s = get_settings()
        v = get_verify_settings()
        text = (
            "👋 **Welcome to Pro FileStore Bot**\n\n"
            "📦 Send any file (or forward) and I'll generate a permanent share link.\n"
            f"🔒 Auto-delete: **{'ON' if s['auto_delete_enabled'] else 'OFF'}**\n"
            f"⏳ Delete after: **{human_seconds(s['delete_seconds'])}**\n"
            f"🚫 Forward protection: **{'ON' if s['protect_content'] else 'OFF'}**\n\n"
            f"🔐 Verify1: {'ON' if v['verify1_enabled'] else 'OFF'}  |  Verify2: {'ON' if v['verify2_enabled'] else 'OFF'}\n\n"
            "Admin commands: /setautodelete, /setforward, /settings"
        )
        buttons = [
            [Button.inline("📁 My Files", b"my_files")],
            [Button.inline("⚙️ Settings", b"admin_panel")],
        ]
        await event.respond(text, buttons=buttons, link_preview=False)
        return

    # deep link expected to be file_<code>
    if arg.startswith("file_"):
        code = arg.split("file_", 1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ File not found or expired.")
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        v = get_verify_settings()

        # If verify1 enabled and user hasn't completed stage1 for this code -> show verify menu
        user = await event.get_sender()
        uid = user.id if user else event.sender_id
        key1 = (uid, code)
        if v["verify1_enabled"] and key1 not in verified_stage1:
            # prepare shortener button (if template set)
            await ensure_username()
            deep_verify_payload = f"verify1|{code}"
            btns = []
            # inline verify button (internal)
            btns.append([Button.inline("✅ Verify (bot)", f"verify1|{code}")])
            # if shortener template exists, create short link to this bot's deep verify callback URL (t.me link)
            if v["verify1_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start={deep_verify_payload}"
                    short = await call_shortener(v["verify1_shortener_template"], v["verify1_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 Verify via short link", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ Back", b"back")])
            text = (
                "🔐 **Verify 1 required**\n\n"
                "You must complete the verification step before getting the file.\n"
                "You can either press **Verify (bot)** or use the external shortener link if provided by admin."
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # If verify1 passed and verify2 enabled and not yet verified stage2 -> ask for verify2
        key2 = (uid, code)
        if v["verify2_enabled"] and key1 in verified_stage1 and key2 not in verified_stage2:
            # show verify2 menu
            await ensure_username()
            btns = [[Button.inline("✅ Complete Verify 2 (bot)", f"verify2|{code}")]]
            if v["verify2_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start=verify2|{code}"
                    short = await call_shortener(v["verify2_shortener_template"], v["verify2_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 Verify2 via short link", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ Back", b"back")])
            text = (
                "🔐 **Verify 2 required**\n\n"
                f"Second verification step is enabled. You must complete it to receive the file.\n"
                f"Verify2 wait time: {human_seconds(v['verify2_delay_seconds'])} (admin-set)\n"
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # Passed verification (or verification not required) -> send file
        try:
            file_msg = await client.send_file(event.sender_id, file=file_id, caption=caption or file_name, force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file for code %s", code)
            await event.respond("⚠️ Failed to send file. Try again later.")
            return

        # if auto-delete configured for this file, compute remaining seconds and schedule deletion
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ This file will auto-delete in {human_seconds(remaining)}. Please forward/save now if you need it."
                try:
                    notice_msg = await client.send_message(event.sender_id, notice_text, reply_to=file_msg.id)
                    extra = [(event.sender_id, file_msg.id), (event.sender_id, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed to send notice or schedule per-download delete for %s", code)
        return

    await event.respond("Unknown start parameter. Send a file to generate a link.")

# -------------------------
# Callbacks: verify buttons & menus & admin verify config pages
# -------------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode() if event.data else ""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id

    # Back button (return to main menu)
    if data == "back":
        s = get_settings()
        await ensure_username()
        text = (
            "👋 **Welcome back!**\n\n"
            "Send a file or use the menu below."
        )
        btns = [[Button.inline("📁 My Files", b"my_files")], [Button.inline("⚙️ Settings", b"admin_panel")]]
        await event.edit(text, buttons=btns)
        return

    # Verify1 internal button: "verify1|<code>"
    if data.startswith("verify1|"):
        _, code = data.split("|",1)
        # mark verified for this user+code
        verified_stage1[(uid, code)] = int(time.time())
        await event.answer("✅ Verify1 completed. Sending file...", alert=True)
        # emulate /start file_code flow for same user by calling send handler logic
        # craft a fake event to call send logic, but easier: send a message to user telling them to click the original link again
        # Simpler: directly send file here if code exists
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found.", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=caption or file_name, force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file in verify1 callback for %s", code)
            await event.answer("Failed to send file. Try again later.", alert=True)
            return
        # schedule per-download deletion if needed
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ This file will auto-delete in {human_seconds(remaining)}. Please forward/save now if you need it."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed to send notice or schedule per-download delete for %s", code)
        return

    # Verify2 internal button: "verify2|<code>"
    if data.startswith("verify2|"):
        _, code = data.split("|",1)
        verified_stage2[(uid, code)] = int(time.time())
        await event.answer("✅ Verify2 completed. Sending file...", alert=True)
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found.", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=caption or file_name, force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file in verify2 callback for %s", code)
            await event.answer("Failed to send file. Try again later.", alert=True)
            return
        # schedule per-download deletion if needed
        if delete_at:
            now = int(time.time())
            remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ This file will auto-delete in {human_seconds(remaining)}. Please forward/save now if you need it."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed to send notice or schedule per-download delete for %s", code)
        return

    # Admin panel and verify management pages
    if data == "admin_panel":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        s = get_settings(); v = get_verify_settings()
        text = (
            "⚙️ Admin Panel\n\n"
            f"Auto-delete: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
            f"Delete after: {human_seconds(s['delete_seconds'])}\n"
            f"Protect content: {'ON' if s['protect_content'] else 'OFF'}\n\n"
            f"Verify1: {'ON' if v['verify1_enabled'] else 'OFF'}\n"
            f"Verify2: {'ON' if v['verify2_enabled'] else 'OFF'}\n\n"
            "Use the buttons below to manage verify settings and shorteners."
        )
        buttons = [
            [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn"), Button.inline("Toggle Protect", b"toggle_protect_btn")],
            [Button.inline("Verify Settings", b"verify_panel")],
            [Button.inline("⬅ Back", b"back")]
        ]
        await event.edit(text, buttons=buttons)
        return

    if data == "verify_panel":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        v = get_verify_settings()
        text = (
            "**ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴘʀᴏᴄᴇꜱꜱ, ᴍᴇᴀɴꜱ ʏᴏᴜ ᴄᴀɴ ᴅᴏ ᴛᴜʀɴ ᴏɴ/ᴏꜰꜰ & ꜱᴇᴛ ᴛɪᴍᴇ ꜰᴏʀ 2ɴᴅ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴀɴᴅ ᴀʟsᴏ sʜᴏʀᴛɴᴇʀs ꜰᴏʀ ᴠᴇʀɪꜰʏ.**"
        )
        buttons = [
            [Button.inline("Verify 1", b"verify1_page"), Button.inline("Verify 2", b"verify2_page")],
            [Button.inline("Set Verify 2 Time", b"set_verify2_time")],
            [Button.inline("⬅ Back", b"admin_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Verify1 page
    if data == "verify1_page":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        v = get_verify_settings()
        text = (
            "**ᴠᴇʀɪꜰʏ 𝟷 ꜱᴇᴛᴛɪɴɢꜱ: ɢᴇɴᴇʀᴀʟ**\n\n"
            f"Shortener: {'SET' if v['verify1_shortener_template'] else 'NOT SET'}\n"
            f"API Key: {'SET' if v['verify1_api_key'] else 'NOT SET'}\n"
            f"Status: {'ON' if v['verify1_enabled'] else 'OFF'}\n\n"
            "Use buttons below to toggle or set shortener/template."
        )
        buttons = [
            [Button.inline("Turn Verify1 ON/OFF", b"toggle_verify1_btn")],
            [Button.inline("Set Verify1 Shortener Template", b"set_verify1_short"), Button.inline("Set Verify1 API Key", b"set_verify1_key")],
            [Button.inline("⬅ Back", b"verify_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Verify2 page
    if data == "verify2_page":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        v = get_verify_settings()
        text = (
            "**ᴠᴇʀɪꜰʏ 𝟸 ꜱᴇᴛᴛɪɴɢꜱ:**\n\n"
            f"Shortener: {'SET' if v['verify2_shortener_template'] else 'NOT SET'}\n"
            f"API Key: {'SET' if v['verify2_api_key'] else 'NOT SET'}\n"
            f"Status: {'ON' if v['verify2_enabled'] else 'OFF'}\n"
            f"Verify2 delay: {human_seconds(v['verify2_delay_seconds'])}\n\n"
            "Use buttons below to toggle or set shortener/template or set delay."
        )
        buttons = [
            [Button.inline("Turn Verify2 ON/OFF", b"toggle_verify2_btn")],
            [Button.inline("Set Verify2 Shortener Template", b"set_verify2_short"), Button.inline("Set Verify2 API Key", b"set_verify2_key")],
            [Button.inline("⬅ Back", b"verify_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Set verify2 time page
    if data == "set_verify2_time":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        text = (
            "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ɢʀᴏᴜᴘ 2ɴᴅ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴛɪᴍᴇ\n\n"
            "Set Verify2 time (example: `60s`, `2m`, `1h`)\n\n"
            "Use command: /setverify2time <duration>\n\n"
            "⬅ Back"
        )
        buttons = [[Button.inline("⬅ Back", b"verify_panel")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Toggle verify1
    if data == "toggle_verify1_btn":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        v = get_verify_settings()
        new = not v["verify1_enabled"]
        set_verify_settings(verify1_enabled=1 if new else 0)
        await event.edit(f"Verify1 is now {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ Back", b"verify1_page")]])
        return

    # Toggle verify2
    if data == "toggle_verify2_btn":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        v = get_verify_settings()
        new = not v["verify2_enabled"]
        set_verify_settings(verify2_enabled=1 if new else 0)
        await event.edit(f"Verify2 is now {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ Back", b"verify2_page")]])
        return

    # Buttons to set shortener templates / keys - these will ask the admin to send the template/key as a message next
    if data in ("set_verify1_short","set_verify1_key","set_verify2_short","set_verify2_key"):
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        await event.edit("✅ Now send the template (or key) as a plain message in this chat. Use `{api_key}` and `{url}` placeholders in the template. Example:\n`https://api.short.example/create?api_key={api_key}&url={url}`\n\nSend `cancel` to abort.", buttons=[[Button.inline("⬅ Back", b"verify_panel")]])
        # store a small marker in-memory to know next message is template/key
        pending_setter[uid] = data  # will be handled in message handler
        return

    # inline toggle auto-delete / protect buttons
    if data == "toggle_autodel_btn":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        s = get_settings(); new = not s["auto_delete_enabled"]; set_setting(auto_delete=new)
        await event.edit(f"Auto-delete is now {'ON' if new else 'OFF'}.")
        return

    if data == "toggle_protect_btn":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        s = get_settings(); new = not s["protect_content"]; set_setting(protect_content=new)
        await event.edit(f"Protect content is now {'ON' if new else 'OFF'}.")
        return

    # my_files handling via callback
    if data == "my_files":
        rows = list_user_files(uid, limit=30)
        if not rows:
            await event.edit("📂 You don't have any saved files.", buttons=[[Button.inline("⬅ Back", b"back")]])
            return
        await ensure_username()
        btns = []
        for code, name, caption, created_at, delete_at in rows:
            label = (name or caption or "file")[:28]
            btns.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
        btns.append([Button.inline("⬅ Back", b"back")])
        await event.edit("📁 Your files:", buttons=btns)
        return

    # Delete button pressed (del_<code>)
    if data.startswith("del_"):
        code = data.split("_",1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        if uid != owner_id and not is_admin(uid):
            await event.answer("Only owner or admin can delete", alert=True)
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
        await event.edit(f"✅ Deleted file: {file_name or code}")
        return

    await event.answer("Unknown action", alert=True)

# -------------------------
# Pending setter dict (admin sending templates/keys)
# -------------------------
# uid -> pending action name like 'set_verify1_short'
pending_setter = {}

# handle admin sending the template or api key after pressing set button
@client.on(events.NewMessage(incoming=True))
async def handle_pending_setters(event):
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id
    if uid not in pending_setter:
        return  # not in setter flow
    action = pending_setter.pop(uid)
    text = (event.raw_text or "").strip()
    if text.lower() == "cancel":
        await event.reply("Cancelled.")
        return
    if action == "set_verify1_short":
        set_verify_settings(verify1_shortener_template=text)
        await event.reply("✅ Verify1 shortener template saved.")
        return
    if action == "set_verify1_key":
        set_verify_settings(verify1_api_key=text)
        await event.reply("✅ Verify1 API key saved.")
        return
    if action == "set_verify2_short":
        set_verify_settings(verify2_shortener_template=text)
        await event.reply("✅ Verify2 shortener template saved.")
        return
    if action == "set_verify2_key":
        set_verify_settings(verify2_api_key=text)
        await event.reply("✅ Verify2 API key saved.")
        return

# -------------------------
# Admin commands (text) for verify time and basic settings
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setverify2time\s+(.+)$"))
async def cmd_setverify2time(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ Only admin can set verify2 time.")
        return
    arg = event.pattern_match.group(1)
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("Invalid duration. Use like `30s`, `2m`, `1h`, `1d`.")
        return
    set_verify_settings(verify2_delay_seconds=sec)
    await event.reply(f"✅ Verify2 delay set to {human_seconds(sec)}.")

# -------------------------
# Admin commands: setautodelete, setforward, settings, myfiles (text versions)
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setautodelete(?:\s+(.+))?$"))
async def cmd_setautodelete(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ Only admin can set auto-delete.")
        return
    arg = event.pattern_match.group(1)
    if not arg:
        await event.reply("Usage: /setautodelete <30s|2m|1h|1d|off>")
        return
    if arg.strip().lower() == "off":
        set_setting(delete_seconds=0); set_setting(auto_delete=False)
        await event.reply("✅ Auto-delete disabled."); return
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("❌ Invalid duration. Use like `30s`, `2m`, `1h`, `1d`.")
        return
    set_setting(delete_seconds=sec); set_setting(auto_delete=True)
    await event.reply(f"✅ Auto-delete enabled. Files will be removed after {human_seconds(sec)}.")

@client.on(events.NewMessage(pattern=r"^/setforward\s+(\w+)$"))
async def cmd_setforward(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ Only admin can change forward protection.")
        return
    arg = event.pattern_match.group(1).lower()
    if arg not in ("on","off"):
        await event.reply("Usage: /setforward <on|off>"); return
    set_setting(protect_content=(arg=="on"))
    await event.reply(f"✅ Protect content set to {'ON' if arg=='on' else 'OFF'}.")

@client.on(events.NewMessage(pattern=r"^/settings$"))
async def cmd_settings(event):
    sender = await event.get_sender()
    s = get_settings(); v = get_verify_settings()
    text = (
        f"⚙️ Settings\n\n"
        f"• Auto-delete: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
        f"• Delete after: {human_seconds(s['delete_seconds'])}\n"
        f"• Protect content: {'ON' if s['protect_content'] else 'OFF'}\n\n"
        f"🔐 Verify1: {'ON' if v['verify1_enabled'] else 'OFF'}  Short: {'SET' if v['verify1_shortener_template'] else 'NOT SET'}\n"
        f"🔐 Verify2: {'ON' if v['verify2_enabled'] else 'OFF'}  Short: {'SET' if v['verify2_shortener_template'] else 'NOT SET'}  Delay: {human_seconds(v['verify2_delay_seconds'])}\n\n"
        "Use inline buttons below to manage settings."
    )
    buttons = [
        [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn"), Button.inline("Toggle Protect", b"toggle_protect_btn")],
        [Button.inline("Verify Settings", b"verify_panel")],
        [Button.inline("⬅ Back", b"back")]
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
        await event.reply("📂 You have no saved files."); return
    await ensure_username()
    buttons = []
    for code, name, caption, created_at, delete_at in rows:
        label = (name or caption or "file")[:30]
        buttons.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
    await event.reply("📁 Your files:", buttons=buttons)

# -------------------------
# File save handler (accept direct and forwarded)
# -------------------------
@client.on(events.NewMessage(incoming=True))
async def handle_incoming(event):
    # first handle pending_setter messages (admin shortener templates) - this is done in separate handler above
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
        [Button.url("📎 Get / Share Link", share_link)],
        [Button.inline("📁 My Files", b"my_files"), Button.inline("🗑 Delete", f"del_{code}".encode())]
    ]
    delete_msg_text = f"\n\n⏳ This file will auto-delete in {human_seconds(s['delete_seconds'])}." if delete_at else ""
    reply_text = (
        f"✅ **File Saved Successfully!**\n\n"
        f"📄 **Name:** `{file_name or 'Unnamed'}`\n"
        f"💬 **Caption:** {sanitized_caption or '—'}\n"
        f"🔗 **Share Link:** {share_link}"
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
            log.exception("Failed scheduling delete for %s", code)

    log.info("Saved file code=%s owner=%s file_id=%s", code, sender.id, file_id)

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
    log.info("Starting Telegram client...")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
