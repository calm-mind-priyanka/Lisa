# bot.py
import os
import sqlite3
import logging
import threading
import uuid
from pathlib import Path
from telethon import TelegramClient, events, Button
from fastapi import FastAPI
import uvicorn

# =============================
# CONFIGURATION
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE")

# Storage setup
BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "files.db"
STORAGE_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("filestore")

# FastAPI app for Koyeb health check
app = FastAPI()


# =============================
# DATABASE
# =============================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            code TEXT PRIMARY KEY,
            owner_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            file_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def add_file(code, owner_id, file_id, file_name, file_type):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (code, owner_id, file_id, file_name, file_type) VALUES (?, ?, ?, ?, ?)",
        (code, owner_id, file_id, file_name, file_type),
    )
    conn.commit()
    conn.close()


def get_file(code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, owner_id, file_id, file_name, file_type FROM files WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return row


# =============================
# TELETHON CLIENT
# =============================
client = TelegramClient("bot", 0, 0).start(bot_token=BOT_TOKEN)


async def get_username():
    me = await client.get_me()
    return me.username


def generate_code():
    return uuid.uuid4().hex[:10]


# =============================
# EVENT: /start command
# =============================
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
async def start_handler(event):
    arg = event.pattern_match.group(1)

    if not arg:
        text = (
            "👋 **Welcome to FileStore Bot!**\n\n"
            "📦 Send me **any file** (video, photo, document, audio, etc.) and I’ll give you a **permanent link**.\n\n"
            "✅ Works for **forwarded** files too!\n"
            "🔗 You can share the generated link with anyone — they’ll get the file directly from me.\n\n"
            "✨ *Built for creators, movie sharers & file lovers.*"
        )
        buttons = [
            [Button.inline("📁 My Files", b"my_files")],
            [Button.url("💡 Developer", "https://t.me/yourusername")],
        ]
        await event.respond(text, buttons=buttons, link_preview=False)
        return

    # Handle deep link
    if arg.startswith("file_"):
        code = arg.replace("file_", "")
        data = get_file(code)
        if not data:
            await event.respond("❌ File not found or expired.")
            return
        _, owner_id, file_id, file_name, file_type = data
        try:
            await client.send_file(event.sender_id, file=file_id, caption=file_name)
        except Exception as e:
            log.error(e)
            await event.respond("⚠️ Could not send file, please try later.")


# =============================
# EVENT: On any file received
# =============================
@client.on(events.NewMessage(incoming=True))
async def save_file(event):
    if not event.file:
        return

    try:
        user_id = event.sender_id
        file = event.message
        code = generate_code()
        file_id = file.file.id
        file_name = file.file.name or "Unnamed"
        file_type = file.file.mime_type or "Unknown"

        add_file(code, user_id, file_id, file_name, file_type)
        username = await get_username()
        share_link = f"https://t.me/{username}?start=file_{code}"

        buttons = [
            [Button.url("📎 Get / Share Link", share_link)],
            [Button.inline("📁 My Files", b"my_files"), Button.inline("🗑 Delete", f"del_{code}".encode())],
        ]

        reply = (
            f"✅ **File Saved!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"💾 **Type:** `{file_type}`\n\n"
            f"🔗 **Share Link:** {share_link}\n\n"
            f"Anyone with this link can download your file directly (no forward tag)."
        )
        await event.reply(reply, buttons=buttons, link_preview=False)

    except Exception as e:
        log.exception(e)
        await event.reply("⚠️ Error while saving file. Try again.")


# =============================
# CALLBACK HANDLERS
# =============================
@client.on(events.CallbackQuery)
async def callback(event):
    data = event.data.decode()

    if data == "my_files":
        user_id = event.sender_id
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT code, file_name FROM files WHERE owner_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,))
        files = cur.fetchall()
        conn.close()

        if not files:
            await event.edit("📁 You don’t have any saved files yet.", buttons=[[Button.inline("⬅ Back", b"back")]])
            return

        buttons = []
        for code, name in files:
            buttons.append([Button.url(name[:30], f"/start file_{code}")])
        buttons.append([Button.inline("⬅ Back", b"back")])
        await event.edit("📁 **Your Files:**", buttons=buttons)

    elif data.startswith("del_"):
        code = data.split("_", 1)[1]
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM files WHERE code = ?", (code,))
        conn.commit()
        conn.close()
        await event.edit("✅ File deleted successfully.")

    elif data == "back":
        await event.edit(
            "👋 **Welcome back!**\nSend me any file to generate a link instantly.",
            buttons=[[Button.inline("📁 My Files", b"my_files")]],
        )


# =============================
# FASTAPI HEALTH CHECK
# =============================
@app.get("/")
async def root():
    return {"status": "ok"}


def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080)


# =============================
# MAIN
# =============================
def main():
    init_db()
    threading.Thread(target=run_fastapi, daemon=True).start()
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
