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
# NOTE: All verification button logic (verify1/verify2/shortener/etc.)
# has been removed from this file as requested. No verify handlers,
# verify maps or verify-related DB usage remain.
# -------------------------

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
            "👋 **Welcome to Pro FileStore Bot**\n\n"
            "📦 Send any file (or forward) and I'll generate a permanent share link.\n"
            f"🔒 Auto-delete: **{'ON' if s['auto_delete_enabled'] else 'OFF'}**\n"
            f"⏳ Delete after: **{human_seconds(s['delete_seconds'])}**\n"
            f"🚫 Forward protection: **{'ON' if s['protect_content'] else 'OFF'}**\n\n"
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

        # Directly send file (no verification step)
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
# Callbacks: admin and other buttons (verify-related buttons removed)
# -------------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode() if event.data else ""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id

    # Back button (return to main menu)
    if data == "back":
        await ensure_username()
        text = (
            "👋 **Welcome back!**\n\n"
            "Send a file or use the menu below."
        )
        btns = [[Button.inline("📁 My Files", b"my_files")], [Button.inline("⚙️ Settings", b"admin_panel")]]
        await event.edit(text, buttons=btns)
        return

    # Admin panel (verify buttons removed)
    if data == "admin_panel":
        if not is_admin(uid):
            await event.answer("Admin only", alert=True)
            return
        s = get_settings()
        text = (
            "⚙️ Admin Panel\n\n"
            f"Auto-delete: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
            f"Delete after: {human_seconds(s['delete_seconds'])}\n"
            f"Protect content: {'ON' if s['protect_content'] else 'OFF'}\n\n"
            "Use the buttons below to manage settings."
        )
        buttons = [
            [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn"), Button.inline("Toggle Protect", b"toggle_protect_btn")],
            [Button.inline("⬅ Back", b"back")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Toggle auto-delete / protect
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
# uid -> pending action name like 'set_verify1_short' (kept for potential other uses)
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
    # currently no specific pending actions implemented; keep placeholder responses
    await event.reply("Received. (No verify-related settings are used in this bot.)")

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
    # No verify2 in this bot; acknowledge but do not store
    await event.reply("✅ Note received — verification features have been removed from this bot.")

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
    s = get_settings()
    text = (
        f"⚙️ Settings\n\n"
        f"• Auto-delete: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
        f"• Delete after: {human_seconds(s['delete_seconds'])}\n"
        f"• Protect content: {'ON' if s['protect_content'] else 'OFF'}\n\n"
        "Use inline buttons below to manage settings."
    )
    buttons = [
        [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn"), Button.inline("Toggle Protect", b"toggle_protect_btn")],
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
