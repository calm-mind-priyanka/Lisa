import os
import logging
from fastapi import FastAPI
from telethon import TelegramClient, events, Button

# ----------------------------
# Basic Config
# ----------------------------
logging.basicConfig(level=logging.INFO)

API_ID = int(os.getenv("API_ID", "YOUR_API_ID"))
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
app = FastAPI()

# ----------------------------
# File Store (in-memory demo)
# ----------------------------
file_store = {}  # {user_id: [(file_id, file_name)]}

# ----------------------------
# Helper Functions
# ----------------------------
def main_menu():
    return [
        [Button.inline("📤 Upload File", b"upload")],
        [Button.inline("📁 My Files", b"myfiles")],
        [Button.inline("ℹ️ About", b"about")]
    ]

def back_home():
    return [[Button.inline("⬅️ Back", b"home")]]

# ----------------------------
# Start Command
# ----------------------------
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    await event.respond(
        "👋 **Welcome to File Store Bot!**\n\n"
        "Upload any file and get a shareable link.",
        buttons=main_menu()
    )

# ----------------------------
# Upload File Handler
# ----------------------------
@bot.on(events.NewMessage(func=lambda e: e.document or e.photo))
async def file_upload_handler(event):
    user_id = event.sender_id
    if not event.file:
        return
    file = event.file
    file_name = file.name or "Unnamed"
    file_id = file.id

    file_store.setdefault(user_id, []).append((file_id, file_name))

    await event.reply(
        f"✅ **File Saved!**\n\n**Name:** {file_name}",
        buttons=[[Button.inline("📁 My Files", b"myfiles")]]
    )

# ----------------------------
# Callback Handlers
# ----------------------------
@bot.on(events.CallbackQuery(data=b"home"))
async def home_callback(event):
    await event.edit(
        "👋 **Welcome to File Store Bot!**\n\nUpload any file and get a shareable link.",
        buttons=main_menu()
    )

@bot.on(events.CallbackQuery(data=b"about"))
async def about_callback(event):
    text = (
        "📦 **About This Bot**\n\n"
        "This is an advanced file store bot built with Telethon.\n"
        "• Upload files\n"
        "• Retrieve them anytime\n"
        "• Navigate smoothly with inline buttons"
    )
    await event.edit(text, buttons=back_home())

@bot.on(events.CallbackQuery(data=b"myfiles"))
async def myfiles_callback(event):
    user_id = event.sender_id
    files = file_store.get(user_id, [])
    if not files:
        await event.edit("📂 You have no files yet.", buttons=back_home())
        return

    buttons = [
        [Button.inline(f"📄 {name}", f"view_{file_id}".encode())]
        for file_id, name in files
    ]
    buttons.append([Button.inline("⬅️ Back", b"home")])
    await event.edit("📁 **Your Files:**", buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"view_(.+)"))
async def view_file_callback(event):
    file_id = event.pattern_match.group(1).decode()
    user_id = event.sender_id
    files = file_store.get(user_id, [])
    for f_id, name in files:
        if str(f_id) == file_id:
            text = f"📄 **File Name:** {name}\n\nUse this to access your file anytime."
            buttons = [[Button.inline("⬅️ Back", b"myfiles")]]
            await event.edit(text, buttons=buttons)
            break

# ----------------------------
# FastAPI Health Check
# ----------------------------
@app.get("/")
async def root():
    return {"status": "running"}

# ----------------------------
# Run both FastAPI & Bot
# ----------------------------
import threading
import uvicorn

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    threading.Thread(target=run_fastapi).start()
    bot.run_until_disconnected()
