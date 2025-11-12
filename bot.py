# bot.py
import os
import re
import time
import sqlite3
import logging
import threading
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient, events, Button
from fastapi import FastAPI
import uvicorn

# -------------------------
# CONFIG - set env vars or replace literal values
# -------------------------
API_ID = int(os.getenv("API_ID", "24222039"))       # from my.telegram.org
API_HASH = os.getenv("API_HASH", "6dd2dc70434b2f577f76a2e993135662")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE")
BOT_USERNAME = os.getenv("Victoroorrrbot", None)     # optional: your bot username without @

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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            code TEXT PRIMARY KEY,
            owner_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            caption TEXT,
            file_type TEXT,
            created_at INTEGER,
            delete_at INTEGER
        )
    """)
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

def add_file_record(code, owner_id, file_id, file_name, caption, file_type, created_at=None, delete_at=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO files (code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, owner_id, file_id, file_name, caption, file_type, int(created_at or time.time()), int(delete_at) if delete_at else None))
    conn.commit(); conn.close()

def get_file_record(code):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at FROM files WHERE code = ?", (code,))
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

_url_re = re.compile(r'https?://\S+|www\.\S+')
_mention_re = re.compile(r'@[\w_]+')
_channel_link_re = re.compile(r'tg://joinchat/\S+|telegram.me/\S+|t.me/\S+')

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

async def schedule_delete(code: str, when_ts: int):
    now = int(time.time())
    delay = max(0, when_ts - now)
    # cancel existing
    if code in scheduled_tasks:
        try:
            scheduled_tasks[code].cancel()
        except Exception:
            pass
    async def _job():
        try:
            await asyncio.sleep(delay)
            # delete DB record
            delete_file_record(code)
            log.info("Auto-deleted file record %s", code)
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

    if arg.startswith("file_"):
        code = arg.split("file_", 1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ File not found or expired.")
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at = rec
        s = get_settings()
        protect = s["protect_content"]
        try:
            # send stored file_id - will not show forwarded tag because it's a new send
            await client.send_file(event.sender_id, file=file_id, caption=caption or file_name, force_document=False, allow_cache=True, supports_streaming=True, protect_content=bool(protect))
        except Exception:
            log.exception("Failed to send file for code %s", code)
            await event.respond("⚠️ Failed to send file. Try again later.")
        return

    await event.respond("Unknown start parameter. Send a file to generate a link.")

# -------------------------
# Admin commands
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
        set_setting(delete_seconds=0)
        set_setting(auto_delete=False)
        await event.reply("✅ Auto-delete disabled.")
        return
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("❌ Invalid duration. Use like `30s`, `2m`, `1h`, `1d`.")
        return
    set_setting(delete_seconds=sec)
    set_setting(auto_delete=True)
    await event.reply(f"✅ Auto-delete enabled. Files will be removed after {human_seconds(sec)}.")

@client.on(events.NewMessage(pattern=r"^/setforward\s+(\w+)$"))
async def cmd_setforward(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ Only admin can change forward protection.")
        return
    arg = event.pattern_match.group(1).lower()
    if arg not in ("on","off"):
        await event.reply("Usage: /setforward <on|off>")
        return
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
        f"• Protect content: {'ON' if s['protect_content'] else 'OFF'}\n"
        f"• Admin: {ADMIN_ID}\n\n"
        "Use /setautodelete and /setforward to change. Or use Admin Panel below."
    )
    buttons = [
        [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn")],
        [Button.inline("Toggle Protect", b"toggle_protect_btn")]
    ]
    await event.reply(text, buttons=buttons)

# -------------------------
# My files listing
# -------------------------
@client.on(events.NewMessage(pattern=r"^/myfiles$"))
async def cmd_myfiles(event):
    sender = await event.get_sender()
    rows = list_user_files(sender.id, limit=50)
    if not rows:
        await event.reply("📂 You have no saved files.")
        return
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
    msg = event.message
    if not msg:
        return
    if not getattr(msg, "file", None):
        return

    sender = await event.get_sender()
    if not sender:
        return

    original_caption = (msg.message or "") if getattr(msg, "message", None) else (msg.text or "")
    sanitized_caption = sanitize_caption(original_caption)

    file_obj = msg.file
    # file_id - store as string
    file_id = getattr(file_obj, "id", None)
    # For some media, id property can be bytes-like or large; cast to str
    file_id = str(file_id)
    file_name = getattr(file_obj, "name", None) or ""
    file_type = getattr(file_obj, "mime_type", None) or ""

    code = gen_code()
    created_at = int(time.time())
    s = get_settings()
    delete_at = None
    if s["auto_delete_enabled"] and s["delete_seconds"] > 0:
        delete_at = created_at + s["delete_seconds"]

    add_file_record(code=code, owner_id=sender.id, file_id=file_id, file_name=file_name, caption=sanitized_caption, file_type=file_type, created_at=created_at, delete_at=delete_at)

    if delete_at:
        try:
            await schedule_delete(code, delete_at)
        except Exception:
            log.exception("Failed scheduling delete for %s", code)

    await ensure_username()
    share_link = f"https://t.me/{BOT_USERNAME}?start=file_{code}"

    delete_msg = f"\n\n⏳ This file will auto-delete in {human_seconds(s['delete_seconds'])}." if delete_at else ""

    btns = [
        [Button.url("📎 Get / Share Link", share_link)],
        [Button.inline("📁 My Files", b"my_files"), Button.inline("🗑 Delete", f"del_{code}".encode())]
    ]
    reply_text = (
        f"✅ **File Saved Successfully!**\n\n"
        f"📄 **Name:** `{file_name or 'Unnamed'}`\n"
        f"💬 **Caption:** {sanitized_caption or '—'}\n"
        f"🔗 **Share Link:** {share_link}"
        f"{delete_msg}"
    )
    try:
        await event.reply(reply_text, buttons=btns, link_preview=False)
    except Exception:
        await event.reply("✅ File saved. Use /myfiles to view.")
    log.info("Saved file code=%s owner=%s file_id=%s", code, sender.id, file_id)

# -------------------------
# Callback query handler (buttons)
# -------------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode() if event.data else ""
    sender = await event.get_sender()

    if data == "my_files":
        rows = list_user_files(sender.id, limit=30)
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

    if data.startswith("del_"):
        code = data.split("_", 1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found.", alert=True)
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at = rec
        if sender.id != owner_id and not is_admin(sender.id):
            await event.answer("Only owner or admin can delete this file.", alert=True)
            return
        delete_file_record(code)
        if code in scheduled_tasks:
            try:
                scheduled_tasks[code].cancel()
            except Exception:
                pass
            scheduled_tasks.pop(code, None)
        await event.edit(f"✅ Deleted file: {file_name or code}")
        return

    if data == "admin_panel":
        if not is_admin(sender.id):
            await event.answer("Admin only.", alert=True)
            return
        s = get_settings()
        text = (
            f"⚙️ Admin Panel\n\n"
            f"Auto-delete: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
            f"Delete after: {human_seconds(s['delete_seconds'])}\n"
            f"Protect content: {'ON' if s['protect_content'] else 'OFF'}\n\n"
            "Use /setautodelete <2m|1h|30s|off> or buttons below."
        )
        buttons = [
            [Button.inline("Toggle Auto-delete", b"toggle_autodel_btn")],
            [Button.inline("Toggle Protect", b"toggle_protect_btn")]
        ]
        await event.edit(text, buttons=buttons)
        return

    if data == "toggle_autodel_btn":
        if not is_admin(sender.id):
            await event.answer("Admin only.", alert=True)
            return
        s = get_settings()
        new = not s["auto_delete_enabled"]
        set_setting(auto_delete=new)
        await event.edit(f"Auto-delete is now {'ON' if new else 'OFF'}.")
        return

    if data == "toggle_protect_btn":
        if not is_admin(sender.id):
            await event.answer("Admin only.", alert=True)
            return
        s = get_settings()
        new = not s["protect_content"]
        set_setting(protect_content=new)
        await event.edit(f"Protect content is now {'ON' if new else 'OFF'}.")
        return

    if data == "back":
        await event.edit("👋 Back to menu. Send a file to create a link.", buttons=[[Button.inline("📁 My Files", b"my_files")]])
        return

    await event.answer("Unknown action", alert=True)

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
