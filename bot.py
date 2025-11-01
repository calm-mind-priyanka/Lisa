from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError, FloodWaitError
import os, asyncio, json, threading, time, logging
from fastapi import FastAPI
import uvicorn
from collections import defaultdict

# =====================
# Logging
# =====================
logging.basicConfig(
    level=logging.INFO,
    filename="error.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =====================
# FastAPI (for Koyeb uptime)
# =====================
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Bot is alive!"}

threading.Thread(
    target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080),
    daemon=True
).start()

# =====================
# Bot Config
# =====================
API_ID = 20813384
API_HASH = "e7523a805e3adb211815eb6e689b21ab"
SESSION = "1BVtsOHUBu18w3N88LMIgm-qFXd7m0_devnKmMSN1WiDRJq5--nFFLCf9ulA97cQ4SRN_ryiof3Sovl-PANnsghVtsKLml0e5bakMz9mLRpAYl_Ep5rk0BMWRiKItes5PAGpCG9STsE2aJEqP7GrdPUtkKQY6FslmuT9A8DCtgEzTlINO_TBdtYS6cRmdlowGsh3PNGmpzWAdpte3LvWxaU3wjgtbtYU-38yxIvOde5_DaX5z_EBPRPqdeZ2uz88u7-kfRjovHCJx7q27reLMLVTFW-6ZwJjU6XHQ_B_1w6VIyOZSv2OASRnsSl__ssIlvdZm2V6vhXRPBI2CxEfhAQ3bqECYH9Q="
ADMIN_ID = 8375460468

GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"

IGNORE_IDS = {6462141921}

# =====================
# Load/save helpers
# =====================
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

# =====================
# Load data
# =====================
groups, reply_msg, delete_delay, reply_gap, pm_msg = load_data(GROUPS_FILE, SETTINGS_FILE, "🤖 Auto Reply Activated!")

# =====================
# Memory containers
# =====================
last_reply = {}
last_msg_time = {}
msg_count = defaultdict(int)
FLOOD_LIMIT = 3
FLOOD_RESET = 10
FLOOD_CLEAN_INTERVAL = 3600

# =====================
# Client
# =====================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

# =====================
# Anti-flood reset
# =====================
async def reset_counter(counter_dict, chat_id):
    await asyncio.sleep(FLOOD_RESET)
    counter_dict[chat_id] = 0

async def flood_memory_cleaner():
    while True:
        await asyncio.sleep(FLOOD_CLEAN_INTERVAL)
        last_reply.clear()
        last_msg_time.clear()
        msg_count.clear()
        logging.info("✅ Flood memory cleaned.")

# =====================
# Safe reply logic
# =====================
async def safe_group_reply(event):
    try:
        if event.sender_id in IGNORE_IDS:
            return

        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return
        if event.chat_id not in groups:
            return

        now = time.time()
        if event.message.date.timestamp() <= last_msg_time.get(event.chat_id, 0):
            return
        if now - last_reply.get(event.chat_id, 0) < reply_gap:
            return

        msg_count[event.chat_id] += 1
        if msg_count[event.chat_id] > FLOOD_LIMIT:
            return

        last_reply[event.chat_id] = now
        last_msg_time[event.chat_id] = event.message.date.timestamp()

        m = await event.reply(reply_msg)
        if delete_delay > 0:
            await asyncio.sleep(delete_delay)
            try:
                await m.delete()
            except Exception:
                pass

        asyncio.create_task(reset_counter(msg_count, event.chat_id))

    except ChatWriteForbiddenError:
        pass
    except FloodWaitError as e:
        logging.warning(f"[FloodWait] Sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logging.error(f"[SafeGroupReply] {e}")

# =====================
# Event handler
# =====================
@client.on(events.NewMessage)
async def handler(event):
    global reply_msg, delete_delay, reply_gap, pm_msg  # ✅ FIXED: declare globals at top

    try:
        if event.sender_id in IGNORE_IDS:
            return

        # PM auto reply
        if event.is_private and pm_msg and event.sender_id != ADMIN_ID:
            m = await event.reply(pm_msg)
            await asyncio.sleep(60)
            try:
                await m.delete()
            except Exception:
                pass
            return

        # Admin commands
        if event.sender_id == ADMIN_ID:
            txt = (event.raw_text or "").strip()

            if event.is_private:
                if txt.startswith("/addgroup"):
                    try:
                        gid = int(txt.split(" ", 1)[1])
                    except:
                        return await event.reply("❌ Usage: /addgroup -100xxxx")
                    groups.add(gid); save_groups(GROUPS_FILE, groups)
                    return await event.reply(f"✅ Added {gid}")

                elif txt.startswith("/removegroup"):
                    try:
                        gid = int(txt.split(" ", 1)[1])
                    except:
                        return await event.reply("❌ Usage: /removegroup -100xxxx")
                    groups.discard(gid); save_groups(GROUPS_FILE, groups)
                    return await event.reply(f"❌ Removed {gid}")

                elif txt.startswith("/setmsgpm "):
                    pm_msg = txt.split(" ", 1)[1]
                    save_settings(SETTINGS_FILE, reply_msg, delete_delay, reply_gap, pm_msg)
                    return await event.reply("✅ PM auto-reply set.")

                elif txt == "/setmsgpmoff":
                    pm_msg = None
                    save_settings(SETTINGS_FILE, reply_msg, delete_delay, reply_gap, pm_msg)
                    return await event.reply("❌ PM auto-reply turned off.")

            if txt.startswith("/add"):
                groups.add(event.chat_id); save_groups(GROUPS_FILE, groups)
                return await event.reply("✅ Group added.")
            elif txt.startswith("/remove"):
                groups.discard(event.chat_id); save_groups(GROUPS_FILE, groups)
                return await event.reply("❌ Group removed.")
            elif txt.startswith("/setmsg "):
                reply_msg = txt.split(" ", 1)[1]
                save_settings(SETTINGS_FILE, reply_msg, delete_delay, reply_gap, pm_msg)
                return await event.reply("✅ Message updated.")
            elif txt.startswith("/setdel "):
                delete_delay = int(txt.split(" ", 1)[1])
                save_settings(SETTINGS_FILE, reply_msg, delete_delay, reply_gap, pm_msg)
                return await event.reply("✅ Delete delay updated.")
            elif txt.startswith("/setgap "):
                reply_gap = int(txt.split(" ", 1)[1])
                save_settings(SETTINGS_FILE, reply_msg, delete_delay, reply_gap, pm_msg)
                return await event.reply("✅ Reply gap updated.")
            elif txt == "/status":
                status = f"Groups ({len(groups)}):\n"
                for gid in groups:
                    try:
                        chat = await client.get_entity(gid)
                        status += f"- {getattr(chat, 'title', 'Unknown')} ({gid})\n"
                    except:
                        status += f"- Unknown ({gid})\n"
                status += (
                    f"\nMsg: {reply_msg}"
                    f"\nPM msg: {pm_msg or '❌ Off'}"
                    f"\nDel: {delete_delay}s"
                    f"\nGap: {reply_gap}s"
                )
                return await event.reply(status)
            elif txt == "/ping":
                return await event.reply("🏓 Bot alive!")

        # Normal group message reply
        await safe_group_reply(event)

    except Exception as e:
        logging.error(f"[HandlerError] {e}")

# =====================
# Keep Alive + Main
# =====================
async def keep_alive():
    while True:
        try:
            await client.get_me()
        except Exception as e:
            logging.warning(f"[KeepAlive] {e}")
        await asyncio.sleep(300)

async def main():
    asyncio.create_task(flood_memory_cleaner())
    await client.start()
    print("✅ Bot started successfully!")
    asyncio.create_task(keep_alive())
    await client.run_until_disconnected()

if __name__ == "__main__":
    import sys
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        sys.exit()
