from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError, FloodWaitError
from telethon.tl import types as tltypes
from telethon.tl.types import (
    MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention,
    UserStatusOnline, UserStatusOffline
)

import os, asyncio, json, threading, time, random, sys
from fastapi import FastAPI
import uvicorn
import logging
from datetime import datetime, timedelta, timezone

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    filename="error.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bot")

# =========================
# Keep-alive API (Koyeb)
# =========================
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Bot is alive!"}

threading.Thread(
    target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080),
    daemon=True
).start()

# =========================
# Credentials
# =========================
API_ID = 123456
API_HASH = "YOUR_API_HASH"
SESSION = "YOUR_STRING_SESSION"
PRIMARY_ADMIN = 123456789
SECONDARY_ADMIN = 123456789

# =========================
# Files
# =========================
GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"

# =========================
# Load Data
# =========================
def load_data():
    try:
        groups = set(json.load(open(GROUPS_FILE)))
    except:
        groups = set()

    try:
        d = json.load(open(SETTINGS_FILE))
    except:
        d = {}

    return (
        groups,
        d.get("reply_msg", "🤖 Bot is active!"),
        d.get("delete_delay", 15),
        d.get("reply_gap", 30),
        d.get("pm_msg", None),
        d.get("pm_enabled", True),
        d.get("pm_delete", 15),
        d.get("pm_once", False),
        d.get("admin_autodel", 20)
    )

def save_data():
    json.dump(list(groups), open(GROUPS_FILE, "w"))
    json.dump({
        "reply_msg": msg,
        "delete_delay": delay,
        "reply_gap": gap,
        "pm_msg": pm_msg,
        "pm_enabled": pm_enabled,
        "pm_delete": pm_delete,
        "pm_once": pm_once,
        "admin_autodel": admin_autodel
    }, open(SETTINGS_FILE, "w"))

groups, msg, delay, gap, pm_msg, pm_enabled, pm_delete, pm_once, admin_autodel = load_data()

# =========================
# State
# =========================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
last_reply = {}
last_sent_messages = {}
pm_replied_users = set()
bot_active = True
emergency_stop = False
flood_pause_until = 0

# =========================
# Helpers
# =========================
async def safe_delete(message, after):
    await asyncio.sleep(after)
    try:
        await message.delete()
    except:
        pass

async def notify_admin(text):
    try:
        m = await client.send_message(PRIMARY_ADMIN, text)
        await asyncio.sleep(admin_autodel)
        await m.delete()
    except:
        pass

# =========================
# HELP TEXT
# =========================
HELP_TEXT = """
🤖 ADVANCED BOT COMMANDS

⚙ CONTROL
/status
/stopbot
/resumebot

👥 GROUP
/addgroup <id>
/delgroup <id>
/listgroups
/cleargroups
/setmsg <text>
/setdel <sec>
/setgap <sec>

💬 PM
/setpm <text>
/pmon
/pmoff
/setpmdel <sec>
/pmonce
/pmrepeat
"""

# =========================
# Admin Commands
# =========================
@client.on(events.NewMessage(outgoing=True))
async def admin_cmd(e):
    global msg, delay, gap
    global pm_msg, pm_enabled, pm_delete, pm_once
    global bot_active

    if e.sender_id != PRIMARY_ADMIN:
        return

    text = e.raw_text.strip()

    if text == "/help":
        await e.reply(HELP_TEXT)

    elif text == "/status":
        await e.reply(
            f"Bot: {'Active' if bot_active else 'Stopped'}\n"
            f"Groups: {len(groups)}\n"
            f"PM Enabled: {pm_enabled}\n"
            f"PM Once: {pm_once}\n"
            f"Emergency: {emergency_stop}"
        )

    elif text == "/stopbot":
        bot_active = False
        await e.reply("⛔ Bot Stopped")

    elif text == "/resumebot":
        bot_active = True
        await e.reply("✅ Bot Resumed")

    elif text.startswith("/addgroup"):
        gid = int(text.split()[1])
        groups.add(gid)
        save_data()
        await e.reply("✅ Group added")

    elif text.startswith("/delgroup"):
        gid = int(text.split()[1])
        groups.discard(gid)
        save_data()
        await e.reply("✅ Group removed")

    elif text == "/listgroups":
        await e.reply(str(groups))

    elif text == "/cleargroups":
        groups.clear()
        save_data()
        await e.reply("✅ All groups cleared")

    elif text.startswith("/setmsg"):
        msg = text.replace("/setmsg", "").strip()
        save_data()
        await e.reply("✅ Group reply updated")

    elif text.startswith("/setdel"):
        delay = int(text.split()[1])
        save_data()
        await e.reply("✅ Group delete delay updated")

    elif text.startswith("/setgap"):
        gap = int(text.split()[1])
        save_data()
        await e.reply("✅ Gap updated")

    elif text.startswith("/setpm"):
        pm_msg = text.replace("/setpm", "").strip()
        save_data()
        await e.reply("✅ PM message set")

    elif text == "/pmon":
        pm_enabled = True
        save_data()
        await e.reply("✅ PM Enabled")

    elif text == "/pmoff":
        pm_enabled = False
        save_data()
        await e.reply("⛔ PM Disabled")

    elif text.startswith("/setpmdel"):
        pm_delete = int(text.split()[1])
        save_data()
        await e.reply("✅ PM delete delay updated")

    elif text == "/pmonce":
        pm_once = True
        save_data()
        await e.reply("✅ PM Once Mode Enabled")

    elif text == "/pmrepeat":
        pm_once = False
        pm_replied_users.clear()
        save_data()
        await e.reply("✅ PM Repeat Mode Enabled")

# =========================
# Emergency Watch
# =========================
@client.on(events.UserUpdate)
async def watch_admin(event):
    global emergency_stop
    if isinstance(event.status, UserStatusOnline):
        emergency_stop = True
    elif isinstance(event.status, UserStatusOffline):
        emergency_stop = False

# =========================
# Main Handler
# =========================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global last_reply

    if not bot_active or emergency_stop:
        return

    try:
        # ===== PM =====
        if event.is_private:
            if not pm_enabled or not pm_msg:
                return

            if pm_once and event.sender_id in pm_replied_users:
                return

            reply = await event.reply(pm_msg)

            if pm_delete > 0:
                asyncio.create_task(safe_delete(reply, pm_delete))

            pm_replied_users.add(event.sender_id)
            return

        # ===== GROUP =====
        if event.chat_id not in groups:
            return

        if event.sender and getattr(event.sender, "bot", False):
            return

        if event.message.entities:
            for ent in event.message.entities:
                if isinstance(ent, (MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention)):
                    return

        now = time.time()
        if now - last_reply.get(event.chat_id, 0) < gap:
            return

        last_reply[event.chat_id] = now

        reply = await event.reply(msg)

        if delay > 0:
            asyncio.create_task(safe_delete(reply, delay))

    except FloodWaitError as f:
        flood_pause_until = time.time() + f.seconds
        await asyncio.sleep(f.seconds)

    except ChatWriteForbiddenError:
        await notify_admin("❌ Bot cannot write in a group.")

    except Exception as e:
        log.error(str(e))

# =========================
# Start
# =========================
async def main():
    await client.start()
    print("✅ FULL ADVANCED BOT RUNNING...")
    await client.run_until_disconnected()

asyncio.run(main())
