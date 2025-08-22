from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError
import os, asyncio, json, threading, time
from fastapi import FastAPI
import uvicorn
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, filename="error.log", filemode="a",
                    format="%(asctime)s - %(levelname)s - %(message)s")

# =====================
# FastAPI server
# =====================
app = FastAPI()
@app.get("/")
async def root():
    return {"status": "Bot is alive!"}

threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080), daemon=True).start()

# =====================
# Bot configs
# =====================
# Bot 1
API_ID1 = 16899138
API_HASH1 = "a42e17e6861c4a7693e236d4dc12fef6"
SESSION1 = "1AZWarzgBu4nJ_W6KLYr10cf1sF4eBi70miM9P4Q2ar2zPUSICuQS8KLyj-Qww-8NjJOmXlsi7RBzMgu9OKp7e62WGRvcRns54oXbor6fp9cE9NVo7NZ8e7OG8KojJ4bB1trc9dCzzCbQx78flQ57ze5N1RxglckzS8aSFYO4nkpTXSfgHxgBZxONJrdFtGzd4v8LT1VUCf8C3_49GG7bg1tztJ-fBkWv1B_g7FJoYLZnnSvay5Jp2_-z_bwITA0I8f3NKRCeRSVUPgtPENKVkZ_mwDcgjZgnPb5qh2af2RLPFzAbElEn_iDYpRZQr3MsB4bynJQOYisKNRZBvKpM4IcBmW6_kNY="
ADMIN1 = 8223402637

# Bot 2
API_ID2 = 23857015
API_HASH2 = "820a54e11cfd089d89de40be5fa26dba"
SESSION2 = "1AZWarzgBuxS5cIYTXRT5uqunH4ELNOMTRFKbjelfsGfHKDiJqZum3vjFqVfuloNodPHoLfaC55fO07GORmTm3WqQ8mg4e_RNd6EC7a7Q4kJLCdKKl2BT9v6tgGtEvdtQN3e_J5i2RFIxloLInDtJzES59JtMt_62tLLBnUnP_r1f2w3GTzUq6mgr1XdiNDnbs6Fv_b0g4aM1BuAgdGyTqQdiTIh_qn2vebUUSL562PPb_7rW1VpafL2FYNaQMs8CzibYSmQLrpJUPDRGiOWhgBnk3IBNf_0T2_NjsXW68sMxVmHZPoCpJhvpU0DnjBhyYqSY7acwAxO5cGeCWN72JJroVOG-y1k="
ADMIN2 = 8352331412

GROUPS_FILE1 = "groups1.json"
SETTINGS_FILE1 = "settings1.json"
GROUPS_FILE2 = "groups2.json"
SETTINGS_FILE2 = "settings2.json"

# =====================
# Load/save helpers
# =====================
def load_data(groups_file, settings_file, default_msg):
    try: groups = set(json.load(open(groups_file)))
    except: groups = set()
    try:
        d = json.load(open(settings_file))
        return (
            groups,
            d.get("reply_msg", default_msg),
            d.get("delete_delay", 15),
            d.get("reply_gap", 30),
            d.get("pm_msg", None)
        )
    except: return groups, default_msg, 15, 30, None

def save_groups(path, groups): json.dump(list(groups), open(path, "w"))
def save_settings(path, msg, d, g, pm_msg): json.dump({"reply_msg": msg, "delete_delay": d, "reply_gap": g, "pm_msg": pm_msg}, open(path, "w"))

# =====================
# Load data
# =====================
groups1, msg1, delay1, gap1, pm_msg1 = load_data(GROUPS_FILE1, SETTINGS_FILE1, "🤖 Bot1 here!")
groups2, msg2, delay2, gap2, pm_msg2 = load_data(GROUPS_FILE2, SETTINGS_FILE2, "👥 Bot2 here!")

last_reply1, last_reply2 = {}, {}
msg_count1, msg_count2 = defaultdict(int), defaultdict(int)
FLOOD_LIMIT = 3     # max replies in short window
FLOOD_RESET = 10    # seconds to reset counter

client1 = TelegramClient(StringSession(SESSION1), API_ID1, API_HASH1)
client2 = TelegramClient(StringSession(SESSION2), API_ID2, API_HASH2)

# =====================
# Anti-flood reset function
# =====================
async def reset_counter(counter_dict, chat_id):
    await asyncio.sleep(FLOOD_RESET)
    counter_dict[chat_id] = 0

# =====================
# Bot1 handler
# =====================
@client1.on(events.NewMessage)
async def bot1_handler(event):
    try:
        if event.is_private and pm_msg1:
            m = await event.reply(pm_msg1)
            await asyncio.sleep(60)
            await m.delete()
        elif event.chat_id in groups1 and not event.sender.bot:
            now = time.time()
            last_time = last_reply1.get(event.chat_id, 0)
            if now - last_time < gap1:
                return

            # Flood control
            msg_count1[event.chat_id] += 1
            if msg_count1[event.chat_id] > FLOOD_LIMIT:
                return
            last_reply1[event.chat_id] = now

            m = await event.reply(msg1)
            if delay1 > 0: await asyncio.sleep(delay1)
            if delay1 > 0: await m.delete()

            asyncio.create_task(reset_counter(msg_count1, event.chat_id))
    except ChatWriteForbiddenError: pass
    except Exception as e: logging.error(f"[Bot1] {e}")

# =====================
# Bot2 handler
# =====================
@client2.on(events.NewMessage)
async def bot2_handler(event):
    try:
        if event.is_private and pm_msg2:
            m = await event.reply(pm_msg2)
            await asyncio.sleep(60)
            await m.delete()
        elif event.chat_id in groups2 and not event.sender.bot:
            now = time.time()
            last_time = last_reply2.get(event.chat_id, 0)
            if now - last_time < gap2:
                return

            # Flood control
            msg_count2[event.chat_id] += 1
            if msg_count2[event.chat_id] > FLOOD_LIMIT:
                return
            last_reply2[event.chat_id] = now

            m = await event.reply(msg2)
            if delay2 > 0: await asyncio.sleep(delay2)
            if delay2 > 0: await m.delete()

            asyncio.create_task(reset_counter(msg_count2, event.chat_id))
    except ChatWriteForbiddenError: pass
    except Exception as e: logging.error(f"[Bot2] {e}")

# =====================
# Admin commands
# =====================
# Bot1 Admin
@client1.on(events.NewMessage)
async def bot1_admin(e):
    global msg1, delay1, gap1, pm_msg1
    if e.sender_id != ADMIN1: return
    txt = e.raw_text.strip()
    if e.is_private:
        if txt.startswith("/addgroup"):
            try: gid = int(txt.split(" ",1)[1])
            except: return await e.reply("❌ Usage: /addgroup -100xxxx")
            groups1.add(gid); save_groups(GROUPS_FILE1, groups1); return await e.reply(f"✅ Added {gid}")
        elif txt.startswith("/removegroup"):
            try: gid = int(txt.split(" ",1)[1])
            except: return await e.reply("❌ Usage: /removegroup -100xxxx")
            groups1.discard(gid); save_groups(GROUPS_FILE1, groups1); return await e.reply(f"❌ Removed {gid}")
        elif txt.startswith("/setmsgpm "):
            pm_msg1 = txt.split(" ", 1)[1]; save_settings(SETTINGS_FILE1, msg1, delay1, gap1, pm_msg1)
            return await e.reply("✅ PM auto-reply set.")
        elif txt == "/setmsgpmoff":
            pm_msg1 = None; save_settings(SETTINGS_FILE1, msg1, delay1, gap1, pm_msg1)
            return await e.reply("❌ PM auto-reply turned off.")
    if txt == "/add": groups1.add(e.chat_id); save_groups(GROUPS_FILE1, groups1); return await e.reply("✅ Group added.")
    elif txt == "/remove": groups1.discard(e.chat_id); save_groups(GROUPS_FILE1, groups1); return await e.reply("❌ Group removed.")
    elif txt.startswith("/setmsg "): msg1 = txt.split(" ",1)[1]; save_settings(SETTINGS_FILE1, msg1, delay1, gap1, pm_msg1); await e.reply("✅ Message set")
    elif txt.startswith("/setdel "): delay1 = int(txt.split(" ",1)[1]); save_settings(SETTINGS_FILE1, msg1, delay1, gap1, pm_msg1); await e.reply("✅ Delete delay set")
    elif txt.startswith("/setgap "): gap1 = int(txt.split(" ",1)[1]); save_settings(SETTINGS_FILE1, msg1, delay1, gap1, pm_msg1); await e.reply("✅ Gap set")
    elif txt == "/status":
        await e.reply(f"Groups: {len(groups1)}\nMsg: {msg1}\nPM msg: {pm_msg1 or '❌ Off'}\nDel: {delay1}s\nGap: {gap1}s")
    elif txt == "/ping": await e.reply("🏓 Bot1 alive!")

# Bot2 Admin
@client2.on(events.NewMessage)
async def bot2_admin(e):
    global msg2, delay2, gap2, pm_msg2
    if e.sender_id != ADMIN2: return
    txt = e.raw_text.strip()
    if e.is_private:
        if txt.startswith("/addgroup"):
            try: gid = int(txt.split(" ",1)[1])
            except: return await e.reply("❌ Usage: /addgroup -100xxxx")
            groups2.add(gid); save_groups(GROUPS_FILE2, groups2); return await e.reply(f"✅ Added {gid}")
        elif txt.startswith("/removegroup"):
            try: gid = int(txt.split(" ",1)[1])
            except: return await e.reply("❌ Usage: /removegroup -100xxxx")
            groups2.discard(gid); save_groups(GROUPS_FILE2, groups2); return await e.reply(f"❌ Removed {gid}")
        elif txt.startswith("/setmsgpm "):
            pm_msg2 = txt.split(" ", 1)[1]; save_settings(SETTINGS_FILE2, msg2, delay2, gap2, pm_msg2)
            return await e.reply("✅ PM auto-reply set.")
        elif txt == "/setmsgpmoff":
            pm_msg2 = None; save_settings(SETTINGS_FILE2, msg2, delay2, gap2, pm_msg2)
            return await e.reply("❌ PM auto-reply turned off.")
    if txt == "/add": groups2.add(e.chat_id); save_groups(GROUPS_FILE2, groups2); return await e.reply("✅ Group added.")
    elif txt == "/remove": groups2.discard(e.chat_id); save_groups(GROUPS_FILE2, groups2); return await e.reply("❌ Group removed.")
    elif txt.startswith("/setmsg "): msg2 = txt.split(" ",1)[1]; save_settings(SETTINGS_FILE2, msg2, delay2, gap2, pm_msg2); await e.reply("✅ Message set")
    elif txt.startswith("/setdel "): delay2 = int(txt.split(" ",1)[1]); save_settings(SETTINGS_FILE2, msg2, delay2, gap2, pm_msg2); await e.reply("✅ Delete delay set")
    elif txt.startswith("/setgap "): gap2 = int(txt.split(" ",1)[1]); save_settings(SETTINGS_FILE2, msg2, delay2, gap2, pm_msg2); await e.reply("✅ Gap set")
    elif txt == "/status":
        await e.reply(f"Groups: {len(groups2)}\nMsg: {msg2}\nPM msg: {pm_msg2 or '❌ Off'}\nDel: {delay2}s\nGap: {gap2}s")
    elif txt == "/ping": await e.reply("🏓 Bot2 alive!")

# =====================
# Start clients
# =====================
async def start_clients():
    try: await client1.start()
    except Exception as e: logging.error(f"[Client1] {e}")
    try: await client2.start()
    except Exception as e: logging.error(f"[Client2] {e}")
    tasks = []
    if client1.is_connected(): tasks.append(client1.run_until_disconnected())
    if client2.is_connected(): tasks.append(client2.run_until_disconnected())
    print("✅ Running bots...")
    if tasks: await asyncio.gather(*tasks)
    else: print("❌ Both clients failed.")

asyncio.get_event_loop().run_until_complete(start_clients())
