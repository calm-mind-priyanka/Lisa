from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError, FloodWaitError
import os, asyncio, json, threading, time
from fastapi import FastAPI
import uvicorn
import logging
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    filename="error.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =====================
# FastAPI server (healthcheck)
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
# Bot configs
# =====================
API_ID1 = 16899138
API_HASH1 = "a42e17e6861c4a7693e236d4dc12fef6"
SESSION1 = "1AZWarzgBu4nJ_W6KLYr10cf1sF4eBi70miM9P4Q2ar2zPUSICuQS8KLyj-Qww-8NjJOmXlsi7RBzMgu9OKp7e62WGRvcRns54oXbor6fp9cE9NVo7NZ8e7OG8KojJ4bB1trc9dCzzCbQx78flQ57ze5N1RxglckzS8aSFYO4nkpTXSfgHxgBZxONJrdFtGzd4v8LT1VUCf8C3_49GG7bg1tztJ-fBkWv1B_g7FJoYLZnnSvay5Jp2_-z_bwITA0I8f3NKRCeRSVUPgtPENKVkZ_mwDcgjZgnPb5qh2af2RLPFzAbElEn_iDYpRZQr3MsB4bynJQOYisKNRZBvKpM4IcBmW6_kNY="
ADMIN1 = 8223402637

API_ID2 = 23857015
API_HASH2 = "820a54e11cfd089d89de40be5fa26dba"
SESSION2 = "1AZWarzgBuxS5cIYTXRT5uqunH4ELNOMTRFKbjelfsGfHKDiJqZum3vjFqVfuloNodPHoLfaC55fO07GORmTm3WqQ8mg4e_RNd6EC7a7Q4kJLCdKKl2BT9v6tgGtEvdtQN3e_J5i2RFIxloLInDtJzES59JtMt_62tLLBnUnP_r1f2w3GTzUq6mgr1XdiNDnbs6Fv_b0g4aM1BuAgdGyTqQdiTIh_qn2vebUUSL562PPb_7rW1VpafL2FYNaQMs8CzibYSmQLrpJUPDRGiOWhgBnk3IBNf_0T2_NjsXW68sMxVmHZPoCpJhvpU0DnjBhyYqSY7acwAxO5cGeCWN72JJroVOG-y1k="
ADMIN2 = 8352331412

GROUPS_FILE1 = "groups1.json"
SETTINGS_FILE1 = "settings1.json"
GROUPS_FILE2 = "groups2.json"
SETTINGS_FILE2 = "settings2.json"

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
groups1, msg1, delay1, gap1, pm_msg1 = load_data(GROUPS_FILE1, SETTINGS_FILE1, "🤖 Bot1 here!")
groups2, msg2, delay2, gap2, pm_msg2 = load_data(GROUPS_FILE2, SETTINGS_FILE2, "👥 Bot2 here!")

# =====================
# Memory containers
# =====================
last_reply1, last_reply2 = {}, {}
last_msg_time1, last_msg_time2 = {}, {}
msg_count1, msg_count2 = defaultdict(int), defaultdict(int)
FLOOD_LIMIT = 3
FLOOD_RESET = 10
FLOOD_CLEAN_INTERVAL = 3600

# =====================
# Clients
# =====================
client1 = TelegramClient(StringSession(SESSION1), API_ID1, API_HASH1)
client2 = TelegramClient(StringSession(SESSION2), API_ID2, API_HASH2)

# =====================
# Anti-flood reset
# =====================
async def reset_counter(counter_dict, chat_id):
    await asyncio.sleep(FLOOD_RESET)
    counter_dict[chat_id] = 0

async def flood_memory_cleaner():
    while True:
        await asyncio.sleep(FLOOD_CLEAN_INTERVAL)
        last_reply1.clear(); last_reply2.clear()
        last_msg_time1.clear(); last_msg_time2.clear()
        msg_count1.clear(); msg_count2.clear()
        logging.info("✅ Flood memory cleaned.")

# =====================
# Safe group reply
# =====================
async def safe_group_reply(client, event, groups, last_reply, last_msg_time, msg_count, msg_text, delay, gap):
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
        if now - last_reply.get(event.chat_id, 0) < gap:
            return

        msg_count[event.chat_id] += 1
        if msg_count[event.chat_id] > FLOOD_LIMIT:
            return

        last_reply[event.chat_id] = now
        last_msg_time[event.chat_id] = event.message.date.timestamp()

        m = await event.reply(msg_text)
        if delay > 0:
            await asyncio.sleep(delay)
            try:
                await m.delete()
            except Exception:
                pass

        asyncio.create_task(reset_counter(msg_count, event.chat_id))

    except ChatWriteForbiddenError:
        pass
    except FloodWaitError as e:
        logging.warning(f"[FloodWait] Sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)   # FIX: wait flood time then continue
    except (ConnectionError, OSError, asyncio.TimeoutError) as e:
        logging.warning(f"[Network] {e}.")
    except Exception as e:
        logging.error(f"[SafeGroupReply] {e}")

# =====================
# Event handler
# =====================
async def handle_event(client, event, groups, last_reply, last_msg_time, msg_count, msg_text, delay, gap, pm_msg):
    try:
        if event.sender_id in IGNORE_IDS:
            return
        if event.is_private and pm_msg:
            m = await event.reply(pm_msg)
            await asyncio.sleep(60)
            try:
                await m.delete()
            except Exception:
                pass
        else:
            await safe_group_reply(client, event, groups, last_reply, last_msg_time, msg_count, msg_text, delay, gap)
    except Exception as e:
        logging.error(f"[Handler] {e}")

# =====================
# Admin commands
# =====================
async def bot_admin(client, event, admin_id, groups, groups_file, settings_file,
                    msg_var, delay_var, gap_var, pm_msg_var, last_reply, msg_count):
    txt = (event.raw_text or "").strip()
    if event.sender_id != admin_id:
        return

    if event.is_private:
        if txt.startswith("/addgroup"):
            try:
                gid = int(txt.split(" ", 1)[1])
            except:
                return await event.reply("❌ Usage: /addgroup -100xxxx")
            groups.add(gid); save_groups(groups_file, groups)
            return await event.reply(f"✅ Added {gid}")

        elif txt.startswith("/removegroup"):
            try:
                gid = int(txt.split(" ", 1)[1])
            except:
                return await event.reply("❌ Usage: /removegroup -100xxxx")
            groups.discard(gid); save_groups(groups_file, groups)
            return await event.reply(f"❌ Removed {gid}")

        elif txt.startswith("/setmsgpm "):
            pm_msg_var[0] = txt.split(" ", 1)[1]
            save_settings(settings_file, msg_var[0], delay_var[0], gap_var[0], pm_msg_var[0])
            return await event.reply("✅ PM auto-reply set.")

        elif txt == "/setmsgpmoff":
            pm_msg_var[0] = None
            save_settings(settings_file, msg_var[0], delay_var[0], gap_var[0], pm_msg_var[0])
            return await event.reply("❌ PM auto-reply turned off.")

    if txt.startswith("/add"):
        groups.add(event.chat_id); save_groups(groups_file, groups)
        return await event.reply("✅ Group added.")
    elif txt.startswith("/remove"):
        groups.discard(event.chat_id); save_groups(groups_file, groups)
        return await event.reply("❌ Group removed.")
    elif txt.startswith("/setmsg "):
        msg_var[0] = txt.split(" ", 1)[1]
        save_settings(settings_file, msg_var[0], delay_var[0], gap_var[0], pm_msg_var[0])
        await event.reply("✅ Message set")
    elif txt.startswith("/setdel "):
        delay_var[0] = int(txt.split(" ", 1)[1])
        save_settings(settings_file, msg_var[0], delay_var[0], gap_var[0], pm_msg_var[0])
        await event.reply("✅ Delete delay set")
    elif txt.startswith("/setgap "):
        gap_var[0] = int(txt.split(" ", 1)[1])
        save_settings(settings_file, msg_var[0], delay_var[0], gap_var[0], pm_msg_var[0])
        await event.reply("✅ Gap set")
    elif txt == "/status":
        status_text = f"Groups ({len(groups)}):\n"
        for gid in groups:
            try:
                chat = await client.get_entity(gid)
                status_text += f"- {getattr(chat, 'title', 'Unknown')} ({gid})\n"
            except:
                status_text += f"- Unknown ({gid})\n"
        status_text += (
            f"\nMsg: {msg_var[0]}"
            f"\nPM msg: {pm_msg_var[0] or '❌ Off'}"
            f"\nDel: {delay_var[0]}s"
            f"\nGap: {gap_var[0]}s"
        )
        await event.reply(status_text)
    elif txt == "/ping":
        await event.reply("🏓 Bot alive!")

# =====================
# Prepare variables
# =====================
msg1_var, delay1_var, gap1_var, pm_msg1_var = [msg1], [delay1], [gap1], [pm_msg1]
msg2_var, delay2_var, gap2_var, pm_msg2_var = [msg2], [delay2], [gap2], [pm_msg2]

# =====================
# Event listeners
# =====================
@client1.on(events.NewMessage)
async def client1_handler(event):
    try:
        if event.sender_id in IGNORE_IDS:
            return
        await handle_event(client1, event, groups1, last_reply1, last_msg_time1, msg_count1,
                           msg1_var[0], delay1_var[0], gap1_var[0], pm_msg1_var[0])
        await bot_admin(client1, event, ADMIN1, groups1, GROUPS_FILE1, SETTINGS_FILE1,
                        msg1_var, delay1_var, gap1_var, pm_msg1_var, last_reply1, msg_count1)
    except Exception as e:
        logging.error(f"[Client1Handler] {e}")

@client2.on(events.NewMessage)
async def client2_handler(event):
    try:
        if event.sender_id in IGNORE_IDS:
            return
        await handle_event(client2, event, groups2, last_reply2, last_msg_time2, msg_count2,
                           msg2_var[0], delay2_var[0], gap2_var[0], pm_msg2_var[0])
        await bot_admin(client2, event, ADMIN2, groups2, GROUPS_FILE2, SETTINGS_FILE2,
                        msg2_var, delay2_var, gap2_var, pm_msg2_var, last_reply2, msg_count2)
    except Exception as e:
        logging.error(f"[Client2Handler] {e}")

# =====================
# Keep-alive + Restart loop
# =====================
async def keep_alive(client):
    while True:
        try:
            await client.get_me()
        except Exception as e:
            logging.warning(f"[KeepAlive] {e}")
        await asyncio.sleep(300)

async def run_client(client):
    while True:
        try:
            await client.run_until_disconnected()
        except Exception as e:
            logging.error(f"Client crashed: {e}, restarting in 5s")
            await asyncio.sleep(5)

# =====================
# Main function
# =====================
async def main():
    asyncio.create_task(flood_memory_cleaner())

    await client1.start()
    await client2.start()
    print("Both bots started!")

    asyncio.create_task(keep_alive(client1))
    asyncio.create_task(keep_alive(client2))

    await asyncio.gather(
        run_client(client1),
        run_client(client2)
    )

# =====================
# Start main
# =====================
if __name__ == "__main__":
    import sys
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        sys.exit()
