from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
import os, asyncio, json, sys
from collections import defaultdict, deque
import threading
from fastapi import FastAPI
import uvicorn

# ================= CONFIG =================
API_ID = 38960072
API_HASH = "8fc5f21e81ac3f1a123eee3efa78902d"
SESSION = "1BVtsOMYBu11a3Y14XLOAFn-9HYbml8HWiGCd3Q9oDyPAyYvvWI40uzyhQ0X1rHGjOPiLVYaaROOju6k89_CWyMVTy64vpKA-gUHFfd0jDoqDO8qViNEr2w787pZvGHkfaXiBl7hS69A7_Mq9MDFGis8a3yViR5Wp4FRHuYbz5b1QSGbzrLxCjEhJom39hccvFTmI5fNcoDOdZZMu3VKVl3cIjny54Y_46q8UWazk8Q_CpQGOvt94eRWlRqSx11ZOv35pAKNtaNScsjHR1Feg9Ku891BpWDQsqMxw4SpirkX3Xn3-r_TWQIbPTGBM-bskbJuTz2rhrzK1NvSNCDdD8gRCWWv1Pk="

PRIMARY_ADMIN = 6250064764
SECONDARY_ADMIN = 6250064764

GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"
BLACKLIST_FILE = "blacklist.json"

# ================= FILE LOAD =================
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

reply_msg = settings.get("reply_msg", "Bot Active")
delete_delay = settings.get("delete_delay", 10)
reply_gap = settings.get("reply_gap", 5)

pm_msg = settings.get("pm_msg", None)
pm_enabled = settings.get("pm_enabled", True)
pm_delete = settings.get("pm_delete", 10)
pm_once = settings.get("pm_once", False)

bot_active = True
pm_replied_users = {}

group_queues = defaultdict(deque)
group_processing = {}

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

# ================= SAVE =================
def save_all():
    save_json(GROUPS_FILE, list(groups))
    save_json(BLACKLIST_FILE, list(blacklist))
    save_json(SETTINGS_FILE, {
        "reply_msg": reply_msg,
        "delete_delay": delete_delay,
        "reply_gap": reply_gap,
        "pm_msg": pm_msg,
        "pm_enabled": pm_enabled,
        "pm_delete": pm_delete,
        "pm_once": pm_once
    })

# ================= AUTO DELETE =================
async def auto_delete(msg, seconds):
    await asyncio.sleep(seconds)
    try:
        await msg.delete()
    except:
        pass

# ================= ADMIN AUTO CLEAN =================
async def admin_reply(event, text):
    sent = await event.reply(text)
    await asyncio.sleep(0.5)
    try:
        await event.delete()
        await sent.delete()
    except:
        pass

# ================= QUEUE SYSTEM =================
async def process_queue(chat_id):
    if group_processing.get(chat_id):
        return

    group_processing[chat_id] = True

    while group_queues[chat_id]:
        event = group_queues[chat_id].popleft()

        try:
            sent = await event.reply(reply_msg)

            if delete_delay > 0:
                asyncio.create_task(auto_delete(sent, delete_delay))

            await asyncio.sleep(reply_gap)

        except FloodWaitError as f:
            await asyncio.sleep(f.seconds)
        except:
            pass

    group_processing[chat_id] = False

# ================= ADMIN COMMANDS =================
@client.on(events.NewMessage(outgoing=True))
async def admin_commands(e):
    global reply_msg, delete_delay, reply_gap
    global pm_msg, pm_enabled, pm_delete, pm_once
    global bot_active

    if e.sender_id not in [PRIMARY_ADMIN, SECONDARY_ADMIN]:
        return

    text = e.raw_text.strip()

    # STOP / RESUME
    if text == "/stopbot":
        bot_active = False
        await admin_reply(e, "Bot Stopped")
    elif text == "/resumebot":
        bot_active = True
        await admin_reply(e, "Bot Resumed")
    elif text == "/status":
        await admin_reply(e,
            f"Bot Active: {bot_active}\n"
            f"Groups: {len(groups)}\n"
            f"Gap: {reply_gap}s\n"
            f"Delete: {delete_delay}s\n"
            f"PM Enabled: {pm_enabled}"
        )

    # GROUP MANAGEMENT
    elif text == "/addgroup":
        groups.add(e.chat_id)
        save_all()
        await admin_reply(e, "Group Added")
    elif text == "/delgroup":
        groups.discard(e.chat_id)
        save_all()
        await admin_reply(e, "Group Removed")
    elif text == "/listgroups":
        await admin_reply(e, "\n".join(str(g) for g in groups) or "No Groups")
    elif text == "/cleargroups":
        groups.clear()
        save_all()
        await admin_reply(e, "All Groups Cleared")

    # SETTINGS
    elif text.startswith("/setmsg"):
        reply_msg = text.replace("/setmsg", "").strip()
        save_all()
        await admin_reply(e, "Reply Message Updated")
    elif text.startswith("/setdel"):
        delete_delay = int(text.split()[1])
        save_all()
        await admin_reply(e, "Delete Delay Updated")
    elif text.startswith("/setgap"):
        reply_gap = int(text.split()[1])
        save_all()
        await admin_reply(e, "Gap Updated")
    elif text.startswith("/setpm"):
        pm_msg = text.replace("/setpm", "").strip()
        save_all()
        await admin_reply(e, "PM Message Set")
    elif text == "/pmon":
        pm_enabled = True
        save_all()
        await admin_reply(e, "PM Enabled")
    elif text == "/pmoff":
        pm_enabled = False
        save_all()
        await admin_reply(e, "PM Disabled")
    elif text == "/pmonce":
        pm_once = True
        pm_replied_users.clear()
        save_all()
        await admin_reply(e, "PM Once Mode")
    elif text == "/pmrepeat":
        pm_once = False
        pm_replied_users.clear()
        save_all()
        await admin_reply(e, "PM Repeat Mode")
    elif text.startswith("/setpmdel"):
        pm_delete = int(text.split()[1])
        save_all()
        await admin_reply(e, "PM Delete Updated")

    # BLACKLIST
    elif text.startswith("/blacklist"):
        user = int(text.split()[1])
        blacklist.add(user)
        save_all()
        await admin_reply(e, "User Blacklisted")
    elif text.startswith("/unblacklist"):
        user = int(text.split()[1])
        blacklist.discard(user)
        save_all()
        await admin_reply(e, "User Unblacklisted")

    # OTHER
    elif text == "/leavegroup":
        await admin_reply(e, "Leaving Group")
        await client.delete_dialog(e.chat_id)
    elif text == "/restart":
        await admin_reply(e, "Restarting...")
        os.execl(sys.executable, sys.executable, *sys.argv)

# ================= MESSAGE HANDLER =================
@client.on(events.NewMessage(incoming=True))
async def handler(event):

    if not bot_active or event.sender_id in blacklist:
        return

    # PRIVATE MESSAGE
    if event.is_private:
        if not pm_enabled or not pm_msg:
            return
        if pm_once and event.sender_id in pm_replied_users:
            return
        sent = await event.reply(pm_msg)
        if pm_delete > 0:
            asyncio.create_task(auto_delete(sent, pm_delete))
        pm_replied_users[event.sender_id] = True
        return

    # GROUP MESSAGE
    if event.chat_id not in groups:
        return
    sender = await event.get_sender()
    if getattr(sender, "bot", False):
        return

    group_queues[event.chat_id].append(event)
    asyncio.create_task(process_queue(event.chat_id))

# ================= FASTAPI KEEP ALIVE =================
app = FastAPI()

@app.get("/")
async def health():
    return {"status": "healthy"}

def start_api():
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info"
    )

threading.Thread(target=start_api, daemon=True).start()

# ================= START =================
async def main():
    await client.start()
    print("✅ CLEAN BOT RUNNING")
    await client.run_until_disconnected()

asyncio.run(main())
