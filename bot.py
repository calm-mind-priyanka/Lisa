from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError
import os, asyncio, json, threading, time
from fastapi import FastAPI
import uvicorn
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, filename="error.log", filemode="a",
                    format="%(asctime)s - %(levelname)s - %(message)s")

# FastAPI setup for keeping bot alive (Koyeb)
app = FastAPI()
@app.get("/")
async def root():
    return {"status": "Bot is alive!"}

threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080), daemon=True).start()

# Your bot credentials
API_ID = 22669886
API_HASH = "dfb10d8414a29df060d23605d648bfa4"
SESSION = "1BVtsOJwBu4wNrPD6KNn4n9vUKb59mrbwXxOc0XyCK06r4AHRlOLzADtTs3dVzefdgiJh8CSgyApvrL5EGO96BK9eFJWF3rHrwDw1KmJXTuxq2dm71bZJzd1QSa8AZTI42mVIJp6sdf06uQNMQKX1TYJ0xHmxwbglawZieV9YQdzINtLn9w7F2ONHDELRG3H6mtnn8z7EI3I2iaeN7-vlUsYG1s7lRw03KwHWnsZVJVKVghJfQAoENKTtg4HrPNhQ33F0AA280Iv38Gw0hnXP0RHYOzth1r81MQb1hi5eM6aY48KDASAakkHBoqd3I6Su_vDhxNGRE7EmxEvuoG69C3NWIV2U6Fk="
ADMIN = 2056329003

# Files
GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"

# Load/save functions
def load_data(groups_file, settings_file, default_msg):
    try:
        groups = set(json.load(open(groups_file)))
    except:
        groups = set()
    try:
        d = json.load(open(settings_file))
        return (
            groups,
            d.get("reply_msg", default_msg),
            d.get("delete_delay", 15),
            d.get("reply_gap", 30),
            d.get("pm_msg", None)
        )
    except:
        return groups, default_msg, 15, 30, None

def save_groups(path, groups):
    json.dump(list(groups), open(path, "w"))

def save_settings(path, msg, d, g, pm_msg):
    json.dump({"reply_msg": msg, "delete_delay": d, "reply_gap": g, "pm_msg": pm_msg}, open(path, "w"))

# Initial data
groups, msg, delay, gap, pm_msg = load_data(GROUPS_FILE, SETTINGS_FILE, "🤖 Bot is active!")
last_reply = {}

# Create client
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

# Message handler
@client.on(events.NewMessage)
async def handler(event):
    try:
        if event.is_private and pm_msg:
            m = await event.reply(pm_msg)
            await asyncio.sleep(60)
            await m.delete()
        elif event.chat_id in groups and not event.sender.bot:
            now = time.time()
            if now - last_reply.get(event.chat_id, 0) < gap:
                return
            last_reply[event.chat_id] = now
            m = await event.reply(msg)
            if delay > 0:
                await asyncio.sleep(delay)
                await m.delete()
    except ChatWriteForbiddenError:
        pass
    except Exception as e:
        logging.error(f"[Bot] {e}")

# Admin commands
@client.on(events.NewMessage)
async def admin_handler(e):
    global msg, delay, gap, pm_msg
    if e.sender_id != ADMIN:
        return
    txt = e.raw_text.strip()

    if e.is_private:
        if txt.startswith("/addgroup"):
            try:
                gid = int(txt.split(" ", 1)[1])
            except:
                return await e.reply("❌ Usage: /addgroup -100xxxx")
            groups.add(gid)
            save_groups(GROUPS_FILE, groups)
            return await e.reply(f"✅ Added {gid}")

        elif txt.startswith("/removegroup"):
            try:
                gid = int(txt.split(" ", 1)[1])
            except:
                return await e.reply("❌ Usage: /removegroup -100xxxx")
            groups.discard(gid)
            save_groups(GROUPS_FILE, groups)
            return await e.reply(f"❌ Removed {gid}")

        elif txt.startswith("/setmsgpm "):
            pm_msg = txt.split(" ", 1)[1]
            save_settings(SETTINGS_FILE, msg, delay, gap, pm_msg)
            return await e.reply("✅ PM auto-reply set.")

        elif txt == "/setmsgpmoff":
            pm_msg = None
            save_settings(SETTINGS_FILE, msg, delay, gap, pm_msg)
            return await e.reply("❌ PM auto-reply turned off.")

    if txt == "/add":
        groups.add(e.chat_id)
        save_groups(GROUPS_FILE, groups)
        return await e.reply("✅ Group added.")

    elif txt == "/remove":
        groups.discard(e.chat_id)
        save_groups(GROUPS_FILE, groups)
        return await e.reply("❌ Group removed.")

    elif txt.startswith("/setmsg "):
        msg = txt.split(" ", 1)[1]
        save_settings(SETTINGS_FILE, msg, delay, gap, pm_msg)
        await e.reply("✅ Message set")

    elif txt.startswith("/setdel "):
        delay = int(txt.split(" ", 1)[1])
        save_settings(SETTINGS_FILE, msg, delay, gap, pm_msg)
        await e.reply("✅ Delete delay set")

    elif txt.startswith("/setgap "):
        gap = int(txt.split(" ", 1)[1])
        save_settings(SETTINGS_FILE, msg, delay, gap, pm_msg)
        await e.reply("✅ Gap set")

    elif txt == "/status":
        await e.reply(f"Groups: {len(groups)}\nMsg: {msg}\nPM msg: {pm_msg or '❌ Off'}\nDel: {delay}s\nGap: {gap}s")

    elif txt == "/ping":
        await e.reply("🏓 Bot is alive!")

# Start bot
async def start_bot():
    try:
        await client.start()
        print("✅ Bot running...")
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"[Startup Error] {e}")

asyncio.get_event_loop().run_until_complete(start_bot())
