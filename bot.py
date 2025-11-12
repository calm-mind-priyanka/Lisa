# bot.py
import os
import sqlite3
import logging
import threading
import uuid
import re
from pathlib import Path
from fastapi import FastAPI
import uvicorn
from telethon import TelegramClient, events, Button

# -----------------------
# CONFIG - Your credentials
# -----------------------
API_ID = int(os.getenv("API_ID", "24222039"))
API_HASH = os.getenv("API_HASH", "6dd2dc70434b2f577f76a2e993135662")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE")
# -----------------------

BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "files.db"
STORAGE_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI()

# -----------------------
# DATABASE
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            owner_id INTEGER,
            original_name TEXT,
            stored_path TEXT,
            mime TEXT,
            size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_file_record(code, owner_id, original_name, stored_path, mime, size):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (code, owner_id, original_name, stored_path, mime, size) VALUES (?, ?, ?, ?, ?, ?)",
        (code, owner_id, original_name, str(stored_path), mime, size)
    )
    conn.commit()
    conn.close()

def get_file_record(code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, owner_id, original_name, stored_path, mime, size FROM files WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return row

# -----------------------
# Utilities
# -----------------------
def gen_code():
    return uuid.uuid4().hex[:12]

_filename_clean_re = re.compile(r"[^A-Za-z0-9._\- ]")
def sanitize_filename(name: str) -> str:
    name = name or "file"
    return _filename_clean_re.sub("", name)[:200]

# -----------------------
# Telethon setup
# -----------------------
client = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

async def get_bot_username():
    me = await client.get_me()
    return getattr(me, "username", None)

# -----------------------
# Handle any incoming media (including forwarded)
# -----------------------
@client.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    msg = event.message
    if not msg:
        return

    # Accept both direct and forwarded media
    media = msg.media or getattr(msg.fwd_from, "media", None)
    if not media:
        return

    sender = await event.get_sender()
    if not sender:
        return

    user_id = sender.id
    code = gen_code()

    # Extract filename info
    orig_name = getattr(msg.file, "name", None) or "file"
    mime = getattr(msg.file, "mime_type", "")
    size = getattr(msg.file, "size", 0)
    safe_name = sanitize_filename(orig_name)
    stored_filename = f"{code}_{safe_name}"
    stored_path = STORAGE_DIR / stored_filename

    try:
        await client.download_media(msg, file=stored_path)
        if not stored_path.exists():
            await event.reply("⚠️ Failed to save file. Try again.")
            return

        size = stored_path.stat().st_size
        add_file_record(code, user_id, orig_name, stored_path, mime, size)

        bot_username = await get_bot_username()
        share_link = f"https://t.me/{bot_username}?start=file_{code}" if bot_username else f"/start file_{code}"

        buttons = [
            [Button.url("📎 Open / Share", share_link)],
            [Button.inline("📁 My Files", b"my_files"), Button.inline("🗑️ Delete", f"del_{code}".encode())]
        ]
        text = (
            f"✅ File saved!\n\n"
            f"📄 Name: {orig_name}\n"
            f"🔗 Link: {share_link}\n\n"
            f"Anyone who clicks the link will get this file directly (not forwarded)."
        )
        await event.reply(text, buttons=buttons)
        log.info(f"Saved file {stored_path} (owner {user_id})")
    except Exception as e:
        log.exception("Error saving file")
        await event.reply("⚠️ Error saving file. Check bot logs.")

# -----------------------
# Handle deep-link (/start file_xxx)
# -----------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.+))?$"))
async def on_start(event):
    args = event.pattern_match.group(1)
    if not args:
        await event.respond(
            "👋 Welcome to FileStore Bot!\n\nJust send any file and I'll give you a permanent share link.",
            buttons=[[Button.inline("📤 Send File", b"dummy")]]
        )
        return

    if args.startswith("file_"):
        code = args[len("file_"):]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ File not found or deleted.")
            return

        _, owner_id, orig_name, stored_path, mime, size = rec
        stored_path = Path(stored_path)
        if not stored_path.exists():
            await event.respond("❌ File record found but file missing on server.")
            return

        try:
            await client.send_file(event.sender_id, file=str(stored_path), caption=orig_name)
        except Exception:
            log.exception("Failed to send file")
            await event.respond("⚠️ Failed to send file. Try again later.")
        return

    await event.respond("Unknown parameter. Send any file to create a link.")

# -----------------------
# Callback buttons
# -----------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode("utf-8", errors="ignore")

    if data == "dummy":
        await event.answer("Just send any file directly!", alert=True)
        return

    if data == "my_files":
        user_id = event.sender_id
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT code, original_name FROM files WHERE owner_id = ? ORDER BY id DESC LIMIT 30", (user_id,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await event.edit("📂 You have no saved files.", buttons=[[Button.inline("⬅️ Back", b"dummy")]])
            return

        btns = [[Button.url(name[:30], f"/start file_{code}")] for code, name in rows]
        btns.append([Button.inline("⬅️ Back", b"dummy")])
        await event.edit("📁 Your recent files:", buttons=btns)
        return

    if data.startswith("del_"):
        code = data[4:]
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found.", alert=True)
            return

        _, owner_id, orig_name, stored_path, mime, size = rec
        if event.sender_id != owner_id:
            await event.answer("You can delete only your own files.", alert=True)
            return

        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM files WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            p = Path(stored_path)
            if p.exists():
                p.unlink()
            await event.edit(f"✅ Deleted file: {orig_name}")
        except Exception:
            log.exception("Delete failed")
            await event.edit("⚠️ Failed to delete file.")
        return

    await event.answer("Unknown action", alert=True)

# -----------------------
# FastAPI health check
# -----------------------
@app.get("/")
async def root():
    return {"status": "running"}

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

# -----------------------
# Main
# -----------------------
def main():
    init_db()
    t = threading.Thread(target=run_fastapi, daemon=True)
    t.start()
    log.info("FastAPI running on port 8080")
    log.info("Starting Telegram bot...")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
