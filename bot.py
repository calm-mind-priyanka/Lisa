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
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# -----------------------
# CONFIG - Put your details here or use environment variables
# -----------------------
# It's safe to put them directly here if you want:
API_ID = int(os.getenv("API_ID", "YOUR_API_ID"))           # e.g. 1234567
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")         # e.g. "abcd1234..."
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")      # e.g. "123:ABC..."
# -----------------------

# Storage paths
BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "files.db"
STORAGE_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# FastAPI for health-check
app = FastAPI()


# -----------------------
# DATABASE helpers (SQLite)
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
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
        """
    )
    conn.commit()
    conn.close()


def add_file_record(code, owner_id, original_name, stored_path, mime, size):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (code, owner_id, original_name, stored_path, mime, size) VALUES (?, ?, ?, ?, ?, ?)",
        (code, owner_id, original_name, str(stored_path), mime, size),
    )
    conn.commit()
    conn.close()


def get_file_record(code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, owner_id, original_name, stored_path, mime, size FROM files WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return row  # None or tuple


# -----------------------
# Small utilities
# -----------------------
def gen_code():
    # short unique code - you can change length
    return uuid.uuid4().hex[:12]


_filename_clean_re = re.compile(r"[^A-Za-z0-9._\- ]")


def sanitize_filename(name: str) -> str:
    name = name or "file"
    name = _filename_clean_re.sub("", name)
    return name[:200]


# -----------------------
# Telethon client setup
# -----------------------
# Create client session name 'bot_session'
client = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


async def get_bot_username():
    me = await client.get_me()
    return getattr(me, "username", None)


# -----------------------
# Event: Any incoming message that contains media -> save and reply link
# -----------------------
@client.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    # Only process messages that contain media (photo, document, video, audio, sticker, voice, animation, etc.)
    if not event.message or not event.message.media:
        return

    # Protect against channels / service messages without sender
    sender = await event.get_sender()
    if not sender:
        return

    user_id = sender.id

    # Generate unique code and storage path
    code = gen_code()

    # infer original filename if available
    orig_name = None
    mime = None
    size = None

    # Telethon message.media can be a document or photo etc.
    media = event.message.media
    # Try to extract filename and size when it's a document
    if hasattr(media, "document") and media.document is not None:
        doc = media.document
        # file name might be in attributes; try the 'attributes' list for a filename attribute
        orig_name = getattr(doc, "file_name", None)
        size = getattr(doc, "size", None)
        mime = getattr(doc, "mime_type", None)
    elif isinstance(media, MessageMediaPhoto) or isinstance(media, MessageMediaDocument):
        # fallback
        orig_name = getattr(media, "caption", None) or "photo.jpg"
    else:
        orig_name = getattr(event.message, "file", None) or "file"

    safe_name = sanitize_filename(orig_name)
    stored_filename = f"{code}_{safe_name}"
    stored_path = STORAGE_DIR / stored_filename

    try:
        # Download the media to local storage path
        # This will download from Telegram servers; for large files it may take time
        await client.download_media(message=event.message, file=stored_path)
        # If download successful, get file size on disk
        try:
            size = stored_path.stat().st_size
        except Exception:
            size = size or 0

        # Add DB record
        add_file_record(code, user_id, orig_name or safe_name, stored_path, mime or "", size or 0)

        # Compose share link - note: bot username may be None temporarily, but Telegram requires username in t.me link
        bot_username = await get_bot_username()
        if bot_username:
            share_link = f"https://t.me/{bot_username}?start=file_{code}"
        else:
            # fallback: use deep-start param only (this still works as /start param but t.me link without username can't be built)
            share_link = f"/start file_{code}"

        # Reply with link (inline URL button + plain link text)
        buttons = [
            [Button.url("📎 Open link / Share", share_link)],
            [Button.inline("📁 My Files (Your Uploads)", b"my_files"), Button.inline("🗑️ Delete (owner only)", f"del_{code}".encode())]
        ]
        reply_text = (
            f"✅ File saved!\n\n"
            f"📄 Name: {orig_name or safe_name}\n"
            f"🔗 Share link: {share_link}\n\n"
            f"Anyone who clicks the link will get this file directly (not forwarded)."
        )
        await event.reply(reply_text, buttons=buttons)
        log.info(f"Saved file {stored_path} as code {code} (owner {user_id})")
    except Exception as e:
        log.exception("Failed to download / store file")
        await event.reply("⚠️ Failed to save file. Try again or check bot logs.")


# -----------------------
# Handler for deep-link /start file_xxx
# -----------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.+))?$"))
async def on_start(event):
    arg = None
    if event.message.message:
        parts = event.message.message.split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()

    if not arg:
        # plain start
        text = (
            "👋 Welcome to FileStore Bot.\n\n"
            "Send any file and I'll instantly create a permanent share link for it."
        )
        buttons = [[Button.inline("📤 Upload a file (send any file) ", b"dummy")]]
        await event.respond(text, buttons=buttons)
        return

    # Expecting form file_<code>
    if arg.startswith("file_"):
        code = arg[len("file_"):]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ File not found or link invalid.")
            return

        # rec: (code, owner_id, original_name, stored_path, mime, size)
        _, owner_id, original_name, stored_path, mime, size = rec
        stored_path = Path(stored_path)
        if not stored_path.exists():
            await event.respond("❌ File record found but file missing on server.")
            return

        # Send file to the user directly (not forwarded) with original filename as caption
        try:
            await client.send_file(event.sender_id, file=str(stored_path), caption=f"{original_name}")
        except Exception as e:
            log.exception("Failed to send file on /start link")
            await event.respond("⚠️ Failed to send file. Owner might have removed it or file is corrupted.")
        return

    # If start param is something else
    await event.respond("Hi — send any file and I'll create a share link for it.")


# -----------------------
# Optional: handler for inline buttons like My Files or Delete
# -----------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data  # bytes or None
    if not data:
        return

    text = data.decode(errors="ignore")

    # Dummy button (does nothing)
    if text == "dummy":
        await event.answer("Just send any file directly to create a link.", alert=True)
        return

    if text == "my_files":
        # Show a simple list of the user's uploaded files from DB
        user_id = event.sender_id
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT code, original_name FROM files WHERE owner_id = ? ORDER BY id DESC LIMIT 50", (user_id,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await event.edit("📂 You have no saved files yet.", buttons=[[Button.inline("⬅️ Back", b"dummy")]])
            return

        btns = []
        for code, name in rows:
            url = f"/start file_{code}"
            # Use URL button so user can click or copy
            btns.append([Button.url(name[:30], url)])
        btns.append([Button.inline("⬅️ Back", b"dummy")])
        await event.edit("📁 Your files (latest 50):", buttons=btns)
        return

    if text.startswith("del_"):
        # Delete a file (only owner can)
        code = text[len("del_"):]
        rec = get_file_record(code)
        if not rec:
            await event.answer("File not found.", alert=True)
            return
        _, owner_id, original_name, stored_path, mime, size = rec
        if event.sender_id != owner_id:
            await event.answer("Only the owner can delete this file.", alert=True)
            return
        # Delete DB record and file
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM files WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            # Delete stored file if exists
            p = Path(stored_path)
            if p.exists():
                p.unlink()
            await event.edit(f"✅ Deleted file: {original_name}")
        except Exception:
            await event.edit("⚠️ Failed to delete file (check bot logs).")
        return

    # fallback
    await event.answer("Unknown action", alert=True)


# -----------------------
# FastAPI health-check endpoint
# -----------------------
@app.get("/")
async def root():
    return {"status": "running"}


def run_fastapi():
    # run uvicorn inside thread
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


# -----------------------
# Start-up
# -----------------------
def main():
    init_db()
    # start FastAPI in background thread (so both run)
    t = threading.Thread(target=run_fastapi, daemon=True)
    t.start()
    log.info("FastAPI thread started on port 8080")

    # Start Telethon client (blocking)
    log.info("Starting Telegram client...")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
