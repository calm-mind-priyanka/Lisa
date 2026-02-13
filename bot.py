# ================================
# 🚀 ULTRA ADVANCED TELETHON BOT
# ================================

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl import types as tltypes

import os, asyncio, json, threading, time, sys
from fastapi import FastAPI
import uvicorn
import logging
from collections import defaultdict, deque

# =========================
# 🔐 CREDENTIALS
# =========================
API_ID = 38960072
API_HASH = "8fc5f21e81ac3f1a123eee3efa78902d"
SESSION = "1BVtsOMYBu11a3Y14XLOAFn-9HYbml8HWiGCd3Q9oDyPAyYvvWI40uzyhQ0X1rHGjOPiLVYaaROOju6k89_CWyMVTy64vpKA-gUHFfd0jDoqDO8qViNEr2w787pZvGHkfaXiBl7hS69A7_Mq9MDFGis8aZ3yViR5Wp4FRHuYbz5b1QSGbzrLxCjEhJom39hccvFTmI5fNcoDOdZZMu3VKVl3cIjny54Y_46q8UWazk8Q_CpQGOvt94eRWlRqSx11ZOv35pAKNtaNScsjHR1Feg9Ku891BpWDQsqMxw4SpirkX3Xn3-r_TWQIbPTGBM-bskbJuTz2rhrzK1NvSNCDdD8gRCWWv1Pk="
PRIMARY_ADMIN = 6250064764
SECONDARY_ADMIN = 6250064764

# =========================
# 📂 FILES
# =========================
GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"
BLACKLIST_FILE = "blacklist.json"

# =========================
# 📝 LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    filename="error.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bot")

# =========================
# 🌐 KEEP ALIVE
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
# 📦 LOAD / SAVE
# =========================
def load_json(file, default):
    try:
        return json.load(open(file))
    except:
        return default

def save_json(file, data):
    json.dump(data, open(file, "w"))

groups = set(load_json(GROUPS_FILE, []))
blacklist = set(load_json(BLACKLIST_FILE, []))
settings = load_json(SETTINGS_FILE, {})

msg = settings.get("reply_msg", "🤖 Bot Active")
delay = settings.get("delete_delay", 15)
gap = settings.get("reply_gap", 30)
pm_msg = settings.get("pm_msg", None)
pm_enabled = settings.get("pm_enabled", True)
pm_delete = settings.get("pm_delete", 15)
pm_once = settings.get("pm_once", False)

def save_all():
    save_json(GROUPS_FILE, list(groups))
    save_json(BLACKLIST_FILE, list(blacklist))
    save_json(SETTINGS_FILE, {
        "reply_msg": msg,
        "delete_delay": delay,
        "reply_gap": gap,
        "pm_msg": pm_msg,
        "pm_enabled": pm_enabled,
        "pm_delete": pm_delete,
        "pm_once": pm_once
    })

# =========================
# 🧠 STATE
# =========================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

pm_replied_users = {}
bot_active = True

# 🔥 NEW QUEUE SYSTEM
group_queues = defaultdict(deque)
group_processing = {}

# =========================
# 🚀 QUEUE PROCESSOR
# =========================
async def process_group_queue(chat_id):
    if group_processing.get(chat_id):
        return

    group_processing[chat_id] = True

    while group_queues[chat_id]:
        event = group_queues[chat_id].popleft()

        try:
            reply = await event.reply(msg)

            if delay > 0:
                asyncio.create_task(auto_delete(reply, delay))

            await asyncio.sleep(gap)

        except FloodWaitError as f:
            await asyncio.sleep(f.seconds)

        except Exception as e:
            log.error(str(e))

    group_processing[chat_id] = False

async def auto_delete(message, seconds):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except:
        pass

# =========================
# 👑 ADMIN COMMANDS
# =========================
@client.on(events.NewMessage(outgoing=True))
async def admin_cmd(e):
    global msg, delay, gap
    global pm_msg, pm_enabled, pm_delete, pm_once
    global bot_active

    if e.sender_id not in [PRIMARY_ADMIN, SECONDARY_ADMIN]:
        return

    text = e.raw_text.strip()

    if text == "/stopbot":
        bot_active = False
        await e.reply("⛔ Bot Stopped")

    elif text == "/resumebot":
        bot_active = True
        await e.reply("✅ Bot Resumed")

    elif text.startswith("/setgap"):
        gap = int(text.split()[1])
        save_all()
        await e.reply("✅ Gap updated")

    elif text.startswith("/setmsg"):
        msg = text.replace("/setmsg", "").strip()
        save_all()
        await e.reply("✅ Reply message updated")

    elif text.startswith("/setdel"):
        delay = int(text.split()[1])
        save_all()
        await e.reply("✅ Delete delay updated")

    elif text.startswith("/setpm"):
        pm_msg = text.replace("/setpm", "").strip()
        save_all()
        await e.reply("✅ PM message set")

    elif text == "/pmon":
        pm_enabled = True
        save_all()
        await e.reply("✅ PM Enabled")

    elif text == "/pmoff":
        pm_enabled = False
        save_all()
        await e.reply("⛔ PM Disabled")

    elif text == "/pmonce":
        pm_once = True
        pm_replied_users.clear()
        save_all()
        await e.reply("✅ PM Once Mode Enabled")

    elif text == "/pmrepeat":
        pm_once = False
        pm_replied_users.clear()
        save_all()
        await e.reply("✅ PM Repeat Mode Enabled")

# =========================
# 📩 MESSAGE HANDLER
# =========================
@client.on(events.NewMessage(incoming=True))
async def handler(event):

    if not bot_active:
        return

    if event.sender_id in blacklist:
        return

    # ----- PM -----
    if event.is_private:
        if not pm_enabled or not pm_msg:
            return

        if pm_once and event.sender_id in pm_replied_users:
            return

        reply = await event.reply(pm_msg)

        if pm_delete > 0:
            asyncio.create_task(auto_delete(reply, pm_delete))

        pm_replied_users[event.sender_id] = True
        return

    # ----- GROUP QUEUE SYSTEM -----
    if event.chat_id not in groups:
        return

    sender = await event.get_sender()

    # Ignore bots
    if getattr(sender, "bot", False):
        return

    # Ignore admins
    try:
        admins = await event.client.get_participants(
            event.chat_id,
            filter=tltypes.ChannelParticipantsAdmins
        )
        if any(admin.id == event.sender_id for admin in admins):
            return
    except:
        pass

    # Add message to queue
    group_queues[event.chat_id].append(event)

    # Start processor if not running
    asyncio.create_task(process_group_queue(event.chat_id))

# =========================
# 🚀 START
# =========================
async def main():
    await client.start()
    print("🔥 QUEUE BASED BOT RUNNING...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
