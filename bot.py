# ================================
# 🚀 ULTRA ADVANCED TELETHON BOT
# ================================

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

# =========================
# 🔐 CREDENTIALS
# =========================
API_ID = 39184173
API_HASH = "0f7069e1b143a358b409053f558e564c"
SESSION = "1BVtsOMYBu7aKafSKRq8q7ZnjG9VNfJE6aPd0q9gl-MeskoYFbFrUDN_jSy80k8Ofh1Lesw1DrZN3cH0chH97ltSRnjsDT_rAvUwU98yjhTBDh_y3X0WKDy7ll60mTfPbhfoD2uoXjoiHR_wJH27p9om8IjuXkZItClPVcbHEEvLr7DiNtCj6AE_AtN1Oz4iTeH7Qi270FlAs_v_n6PbeKJOdS5_rjoUoDb1v3zfW5fOD3NvCNpu6ihOHOD2cg7GYbJF6i0tzPZl8qEF9sRUCPW5R_2rM6K1RVoKjKxr9EayNrIYnKijCViXg7L3hoSzF2dfEWudgDlNeRP57IhWs9dwcyOu1zJA="
PRIMARY_ADMIN = 6189096205
SECONDARY_ADMIN = 6189096205

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
admin_autodel = settings.get("admin_autodel", 20)

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
        "pm_once": pm_once,
        "admin_autodel": admin_autodel
    })

# =========================
# 🧠 STATE
# =========================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

last_reply = {}
pm_replied_users = {}
bot_active = True
emergency_stop = False
flood_pause_until = 0

# =========================
# 👑 ADMIN COMMANDS
# =========================
@client.on(events.NewMessage(outgoing=True))
async def admin_cmd(e):
    global msg, delay, gap
    global pm_msg, pm_enabled, pm_delete, pm_once
    global bot_active, admin_autodel

    if e.sender_id not in [PRIMARY_ADMIN, SECONDARY_ADMIN]:
        return

    text = e.raw_text.strip()

    # ===== BASIC =====
    if text == "/stopbot":
        bot_active = False
        await e.reply("⛔ Bot Stopped")

    elif text == "/resumebot":
        bot_active = True
        await e.reply("✅ Bot Resumed")

    elif text == "/status":
        await e.reply(f"""
📊 STATUS

Bot Active: {bot_active}
Emergency Stop: {emergency_stop}
Groups: {len(groups)}
PM Enabled: {pm_enabled}
PM Once Mode: {pm_once}
Blacklist Users: {len(blacklist)}
""")

    elif text == "/ping":
        start = time.time()
        m = await e.reply("🏓 Pinging...")
        ms = round((time.time() - start) * 1000)
        await m.edit(f"🏓 Pong: {ms} ms")

    elif text == "/help":
        await e.reply("""
🛠 COMMAND LIST

/stopbot
/resumebot
/status
/ping
/help
/addgroup
/delgroup
/listgroups
/cleargroups
/setmsg
/setdel
/setgap
/setpm
/pmon
/pmoff
/setpmdel
/pmonce
/pmrepeat
/blacklist
/unblacklist
/leavegroup
/restart
/setadminautodel
""")

    # ===== GROUP =====
    elif text.startswith("/addgroup"):
        gid = int(text.split()[1])
        groups.add(gid)
        save_all()
        await e.reply("✅ Group added")

    elif text.startswith("/delgroup"):
        gid = int(text.split()[1])
        groups.discard(gid)
        save_all()
        await e.reply("✅ Group removed")

    elif text == "/listgroups":
        await e.reply(f"📂 Groups:\n{list(groups)}")

    elif text == "/cleargroups":
        groups.clear()
        save_all()
        await e.reply("✅ All groups cleared")

    elif text.startswith("/leavegroup"):
        gid = int(text.split()[1])
        await client.delete_dialog(gid)
        groups.discard(gid)
        save_all()
        await e.reply("👋 Left group")

    # ===== SETTINGS =====
    elif text.startswith("/setmsg"):
        msg = text.replace("/setmsg", "").strip()
        save_all()
        await e.reply("✅ Group reply updated")

    elif text.startswith("/setdel"):
        delay = int(text.split()[1])
        save_all()
        await e.reply("✅ Group delete delay updated")

    elif text.startswith("/setgap"):
        gap = int(text.split()[1])
        save_all()
        await e.reply("✅ Gap updated")

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

    elif text.startswith("/setpmdel"):
        pm_delete = int(text.split()[1])
        save_all()
        await e.reply("✅ PM delete delay updated")

    elif text == "/pmonce":
        pm_once = True
        save_all()
        await e.reply("✅ PM Once Mode Enabled")

    elif text == "/pmrepeat":
        pm_once = False
        pm_replied_users.clear()
        save_all()
        await e.reply("✅ PM Repeat Mode Enabled")

    elif text.startswith("/setadminautodel"):
        admin_autodel = int(text.split()[1])
        save_all()
        await e.reply("✅ Admin auto delete updated")

    # ===== BLACKLIST =====
    elif text.startswith("/blacklist"):
        uid = int(text.split()[1])
        blacklist.add(uid)
        save_all()
        await e.reply("🚫 User blacklisted")

    elif text.startswith("/unblacklist"):
        uid = int(text.split()[1])
        blacklist.discard(uid)
        save_all()
        await e.reply("✅ User removed from blacklist")

    # ===== SYSTEM =====
    elif text == "/restart":
        await e.reply("♻ Restarting...")
        save_all()
        os.execv(sys.executable, ['python'] + sys.argv)

# =========================
# 📩 MESSAGE HANDLER
# =========================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global flood_pause_until

    if not bot_active:
        return

    if event.sender_id in blacklist:
        return

    try:
        sender = await event.get_sender()

        # ===== NEW FEATURE: IGNORE BOT ACCOUNTS AND GROUP ADMINS =====
        if sender:
            # Ignore all bots
            if getattr(sender, "bot", False):
                return
            # Ignore all admins of this group (Telegram accounts)
            if event.is_group:
                try:
                    admins = await event.client.get_participants(event.chat_id, filter=tltypes.ChannelParticipantsAdmins)
                    if any(admin.id == event.sender_id for admin in admins):
                        return
                except:
                    pass

        # ----- PM -----
        if event.is_private:
            if not pm_enabled or not pm_msg:
                return

            if pm_once and event.sender_id in pm_replied_users:
                return

            reply = await event.reply(pm_msg)

            if pm_delete > 0:
                await asyncio.sleep(pm_delete)
                await reply.delete()

            pm_replied_users[event.sender_id] = True
            return

        # ----- GROUP -----
        if event.chat_id not in groups:
            return

        if time.time() - last_reply.get(event.chat_id, 0) < gap:
            return

        last_reply[event.chat_id] = time.time()
        reply = await event.reply(msg)

        if delay > 0:
            await asyncio.sleep(delay)
            await reply.delete()

    except FloodWaitError as f:
        flood_pause_until = time.time() + f.seconds
        await asyncio.sleep(f.seconds)

    except Exception as e:
        log.error(str(e))

# =========================
# 🚀 START
# =========================
async def main():
    await client.start()
    print("🔥 ULTRA ADVANCED BOT RUNNING...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())).start()

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
admin_autodel = settings.get("admin_autodel", 20)

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
        "pm_once": pm_once,
        "admin_autodel": admin_autodel
    })

# =========================
# 🧠 STATE
# =========================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

last_reply = {}
pm_replied_users = {}
bot_active = True
emergency_stop = False
flood_pause_until = 0

# =========================
# 👑 ADMIN COMMANDS
# =========================
@client.on(events.NewMessage(outgoing=True))
async def admin_cmd(e):
    global msg, delay, gap
    global pm_msg, pm_enabled, pm_delete, pm_once
    global bot_active, admin_autodel

    if e.sender_id not in [PRIMARY_ADMIN, SECONDARY_ADMIN]:
        return

    text = e.raw_text.strip()

    # ===== BASIC =====
    if text == "/stopbot":
        bot_active = False
        await e.reply("⛔ Bot Stopped")

    elif text == "/resumebot":
        bot_active = True
        await e.reply("✅ Bot Resumed")

    elif text == "/status":
        await e.reply(f"""
📊 STATUS

Bot Active: {bot_active}
Emergency Stop: {emergency_stop}
Groups: {len(groups)}
PM Enabled: {pm_enabled}
PM Once Mode: {pm_once}
Blacklist Users: {len(blacklist)}
""")

    elif text == "/ping":
        start = time.time()
        m = await e.reply("🏓 Pinging...")
        ms = round((time.time() - start) * 1000)
        await m.edit(f"🏓 Pong: {ms} ms")

    elif text == "/help":
        await e.reply("""
🛠 COMMAND LIST

/stopbot
/resumebot
/status
/ping
/help
/addgroup
/delgroup
/listgroups
/cleargroups
/setmsg
/setdel
/setgap
/setpm
/pmon
/pmoff
/setpmdel
/pmonce
/pmrepeat
/blacklist
/unblacklist
/leavegroup
/restart
/setadminautodel
""")

    # ===== GROUP =====
    elif text.startswith("/addgroup"):
        gid = int(text.split()[1])
        groups.add(gid)
        save_all()
        await e.reply("✅ Group added")

    elif text.startswith("/delgroup"):
        gid = int(text.split()[1])
        groups.discard(gid)
        save_all()
        await e.reply("✅ Group removed")

    elif text == "/listgroups":
        await e.reply(f"📂 Groups:\n{list(groups)}")

    elif text == "/cleargroups":
        groups.clear()
        save_all()
        await e.reply("✅ All groups cleared")

    elif text.startswith("/leavegroup"):
        gid = int(text.split()[1])
        await client.delete_dialog(gid)
        groups.discard(gid)
        save_all()
        await e.reply("👋 Left group")

    # ===== SETTINGS =====
    elif text.startswith("/setmsg"):
        msg = text.replace("/setmsg", "").strip()
        save_all()
        await e.reply("✅ Group reply updated")

    elif text.startswith("/setdel"):
        delay = int(text.split()[1])
        save_all()
        await e.reply("✅ Group delete delay updated")

    elif text.startswith("/setgap"):
        gap = int(text.split()[1])
        save_all()
        await e.reply("✅ Gap updated")

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

    elif text.startswith("/setpmdel"):
        pm_delete = int(text.split()[1])
        save_all()
        await e.reply("✅ PM delete delay updated")

    elif text == "/pmonce":
        pm_once = True
        save_all()
        await e.reply("✅ PM Once Mode Enabled")

    elif text == "/pmrepeat":
        pm_once = False
        pm_replied_users.clear()
        save_all()
        await e.reply("✅ PM Repeat Mode Enabled")

    elif text.startswith("/setadminautodel"):
        admin_autodel = int(text.split()[1])
        save_all()
        await e.reply("✅ Admin auto delete updated")

    # ===== BLACKLIST =====
    elif text.startswith("/blacklist"):
        uid = int(text.split()[1])
        blacklist.add(uid)
        save_all()
        await e.reply("🚫 User blacklisted")

    elif text.startswith("/unblacklist"):
        uid = int(text.split()[1])
        blacklist.discard(uid)
        save_all()
        await e.reply("✅ User removed from blacklist")

    # ===== SYSTEM =====
    elif text == "/restart":
        await e.reply("♻ Restarting...")
        save_all()
        os.execv(sys.executable, ['python'] + sys.argv)

# =========================
# 📩 MESSAGE HANDLER
# =========================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global flood_pause_until

    if not bot_active:
        return

    if event.sender_id in blacklist:
        return

    try:
        # ----- PM -----
        if event.is_private:
            if not pm_enabled or not pm_msg:
                return

            if pm_once and event.sender_id in pm_replied_users:
                return

            reply = await event.reply(pm_msg)

            if pm_delete > 0:
                await asyncio.sleep(pm_delete)
                await reply.delete()

            pm_replied_users[event.sender_id] = True
            return

        # ----- GROUP -----
        if event.chat_id not in groups:
            return

        if time.time() - last_reply.get(event.chat_id, 0) < gap:
            return

        last_reply[event.chat_id] = time.time()
        reply = await event.reply(msg)

        if delay > 0:
            await asyncio.sleep(delay)
            await reply.delete()

    except FloodWaitError as f:
        flood_pause_until = time.time() + f.seconds
        await asyncio.sleep(f.seconds)

    except Exception as e:
        log.error(str(e))

# =========================
# 🚀 START
# =========================
async def main():
    await client.start()
    print("🔥 ULTRA ADVANCED BOT RUNNING...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
