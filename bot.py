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
# Load credentials
# =========================
if os.path.exists("bot_transfer.json"):
    data = json.load(open("bot_transfer.json"))
    API_ID = data.get("API_ID")
    API_HASH = data.get("API_HASH")
    SESSION = data.get("SESSION")
    PRIMARY_ADMIN = data.get("PRIMARY_ADMIN")
else:
    API_ID = 38560260
    API_HASH = "b263984d9c87a6ba37f72100eca60570"
    SESSION = "1BVtsOKEBu3JxsuDz8yYoiSGN_dycPFkcMgr8eivzqlE3O2QK3XC16_5iMRy5FQH73iol2_px3C5uCKGf43wJpLHzyOL5Sle-AUJev3EdngrEk4X4hSf0Co9P6dqt938yf2K_xS7V-eDKDJkTfNIp1Xq9yYijPVB0tli6FsxGJrXzMNF6yguSvSUkJZVccQ5Sw3sobE8u_FZ3xJc61B-ei9DtpNCAQuaB-ZO9VsHnBga19f6TBZDR0UMEfWPe2q1BaW1JOVMvbpxc9o3jxddMP263_UzD2Eh4c_gUlamD9DDepbJh1xfg6c0NodDVjG4kg4XDDPAYONTDfEvWY3QPEQy8sKiUxGM="
    PRIMARY_ADMIN = 8223551195
SECONDARY_ADMIN = 8223551195  # real secondary admin ID

# =========================
# Files
# =========================
GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"

# =========================
# Load state/settings
# =========================
def load_data():
    try:
        groups = set(json.load(open(GROUPS_FILE)))
    except:
        groups = set()
    try:
        d = json.load(open(SETTINGS_FILE))
        return (
            groups,
            d.get("reply_msg", "🤖 Bot is active!"),
            d.get("delete_delay", 15),
            d.get("reply_gap", 30),
            d.get("pm_msg", None),
            d.get("admin_autodel", 20),
            d.get("rate_send_interval", 1.6),
            d.get("rate_edit_interval", 1.2),
            d.get("rate_delete_interval", 1.4),
        )
    except:
        return groups, "🤖 Bot is active!", 15, 30, None, 20, 1.6, 1.2, 1.4

def save_groups(groups):
    json.dump(list(groups), open(GROUPS_FILE, "w"))

def save_settings(msg, d, g, pm_msg, admin_autodel, r_send, r_edit, r_del):
    json.dump(
        {
            "reply_msg": msg,
            "delete_delay": d,
            "reply_gap": g,
            "pm_msg": pm_msg,
            "admin_autodel": admin_autodel,
            "rate_send_interval": r_send,
            "rate_edit_interval": r_edit,
            "rate_delete_interval": r_del,
        },
        open(SETTINGS_FILE, "w")
    )

groups, msg, delay, gap, pm_msg, admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval = load_data()

# =========================
# Last reply & sent messages
# =========================
last_reply = {}
last_sent_messages = {}

# =========================
# Bot control
# =========================
bot_active = True  # new flag to stop/resume bot

# =========================
# Emergency stop & flood wait
# =========================
WATCHED_ADMIN_ID = None
WATCH_GRACE_SEC = 5
emergency_stop = False
flood_pause_until = 0

# =========================
# Time helpers
# =========================
IST = timezone(timedelta(hours=5, minutes=30))
def now_utc(): return datetime.now(timezone.utc)
def fmt_ist(dt_utc: datetime): return dt_utc.astimezone(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")

# =========================
# Rate Limiter
# =========================
class RateLimiter:
    def __init__(self, min_interval: float, jitter: float = 0.4):
        self.min_interval = float(min_interval)
        self.jitter = float(jitter)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
    async def wait(self):
        async with self._lock:
            now = time.time()
            if now < self._next_allowed:
                await asyncio.sleep(self._next_allowed - now)
            self._next_allowed = time.time() + self.min_interval + random.uniform(0, self.jitter)

send_rl = RateLimiter(rate_send_interval, jitter=0.5)
edit_rl = RateLimiter(rate_edit_interval, jitter=0.4)
delete_rl = RateLimiter(rate_delete_interval, jitter=0.6)

# =========================
# Client
# =========================
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

# =========================
# Admin DM auto-delete after read
# =========================
admin_dm_pending = {}  # message_id -> (message, delay)

async def _schedule_delete_after_read(msg, seconds: int):
    admin_dm_pending[msg.id] = (msg, seconds)

@client.on(events.Raw)
async def on_raw_update(update):
    try:
        if isinstance(update, tltypes.UpdateReadHistoryOutbox):
            peer = update.peer
            if isinstance(peer, tltypes.PeerUser) and peer.user_id in (PRIMARY_ADMIN, SECONDARY_ADMIN):
                max_id = update.max_id
                to_delete = [mid for mid in list(admin_dm_pending.keys()) if mid <= max_id]
                for mid in to_delete:
                    msg, sec = admin_dm_pending.pop(mid, (None, None))
                    if msg:
                        asyncio.create_task(safe_delete(msg, sec))
        elif isinstance(update, tltypes.UpdateReadHistoryInbox):
            peer = update.peer
            if isinstance(peer, tltypes.PeerUser) and peer.user_id in (PRIMARY_ADMIN, SECONDARY_ADMIN):
                max_id = update.max_id
                to_delete = [mid for mid in list(admin_dm_pending.keys()) if mid <= max_id]
                for mid in to_delete:
                    msg, sec = admin_dm_pending.pop(mid, (None, None))
                    if msg:
                        asyncio.create_task(safe_delete(msg, sec))
    except Exception as e:
        log.debug(f"on_raw_update error: {e}")

async def safe_delete(message, after_sec: float):
    await asyncio.sleep(after_sec + random.uniform(0.5, 2.0))
    try:
        await delete_rl.wait()
        await message.delete()
    except Exception as e:
        log.warning(f"Delete failed: {e}")

async def notify_admin(text: str, autodel_on_read=True, autodel_sec=None):
    try:
        await send_rl.wait()
        m = await client.send_message(PRIMARY_ADMIN, text)
        if autodel_on_read:
            sec = autodel_sec if autodel_sec is not None else admin_autodel
            asyncio.create_task(_schedule_delete_after_read(m, sec))
        return m
    except Exception as e:
        log.error(f"Failed to notify admin: {e}")

async def send_reply(event, text: str):
    await send_rl.wait()
    return await event.reply(text)

# =========================
# Emergency watch
# =========================
@client.on(events.UserUpdate)
async def watch_admin(event):
    global emergency_stop
    if WATCHED_ADMIN_ID and event.user_id == WATCHED_ADMIN_ID:
        if isinstance(event.status, UserStatusOnline):
            await asyncio.sleep(WATCH_GRACE_SEC)
            emergency_stop = True
            await notify_admin(f"🚨 Emergency stop activated (watched admin online at {fmt_ist(now_utc())}).")
            for chat_id, msg_obj in list(last_sent_messages.items()):
                try: await delete_rl.wait(); await msg_obj.delete()
                except: pass
            last_sent_messages.clear()
        elif isinstance(event.status, UserStatusOffline):
            emergency_stop = False
            await notify_admin(f"✅ Emergency stop lifted (watched admin offline at {fmt_ist(now_utc())}).")

# =========================
# Admin commands
# =========================
@client.on(events.NewMessage(outgoing=True))
async def primary_admin_handler(e):
    global msg, delay, gap, pm_msg
    global admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval
    global send_rl, edit_rl, delete_rl, API_ID, API_HASH, SESSION, PRIMARY_ADMIN
    global bot_active  # new

    txt = (e.raw_text or "").strip()

    if txt.startswith("/ping"):
        start_time = time.time()
        m = await e.reply("Pinging...")
        end_time = time.time()
        latency = round((end_time - start_time)*1000)
        await m.edit(f"Pong! 🏓 {latency}ms")
        return

    if txt.startswith("/status"):
        status = "Active ✅" if bot_active else "Stopped ⛔"
        info = f"Bot Status: {status}\nChat count: {len(groups)}\nLast reply per chat: {len(last_reply)}\nEmergency stop: {emergency_stop}"
        await e.reply(info)
        return

    if txt.startswith("/setmsg "):
        msg = txt[len("/setmsg "):].strip()
        save_settings(msg, delay, gap, pm_msg, admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval)
        await e.reply(f"✅ Reply message set to:\n{msg}")
        return

    if txt.startswith("/setdel "):
        try:
            delay = int(txt[len("/setdel "):].strip())
            save_settings(msg, delay, gap, pm_msg, admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval)
            await e.reply(f"✅ Delete delay set to {delay} seconds")
        except:
            await e.reply("❌ Invalid number for /setdel")
        return

    if txt.startswith("/setgap "):
        try:
            gap = int(txt[len("/setgap "):].strip())
            save_settings(msg, delay, gap, pm_msg, admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval)
            await e.reply(f"✅ Reply gap set to {gap} seconds")
        except:
            await e.reply("❌ Invalid number for /setgap")
        return

    if txt.startswith("/setpm "):
        pm_msg = txt[len("/setpm "):].strip()
        save_settings(msg, delay, gap, pm_msg, admin_autodel, rate_send_interval, rate_edit_interval, rate_delete_interval)
        await e.reply(f"✅ Private message set:\n{pm_msg}")
        return

    if txt.startswith("/addgroup "):
        try:
            gid = int(txt[len("/addgroup "):].strip())
            groups.add(gid)
            save_groups(groups)
            await e.reply(f"✅ Added group {gid}")
        except:
            await e.reply("❌ Invalid group ID")
        return

    if txt.startswith("/delgroup "):
        try:
            gid = int(txt[len("/delgroup "):].strip())
            groups.discard(gid)
            save_groups(groups)
            await e.reply(f"✅ Removed group {gid}")
        except:
            await e.reply("❌ Invalid group ID")
        return

    # --------- New Stop/Resume Commands ----------
    if txt.startswith("/stopbot"):
        if bot_active:
            bot_active = False
            await e.reply("⛔ Bot stopped. It will not auto-reply until resumed.")
        else:
            await e.reply("⚠ Bot is already stopped.")
        return

    if txt.startswith("/resumebot"):
        if not bot_active:
            bot_active = True
            await e.reply("✅ Bot resumed. Auto-reply is active again.")
        else:
            await e.reply("⚠ Bot is already active.")
        return

# ---- Secondary admin (/transfer) ----
@client.on(events.NewMessage(from_users=SECONDARY_ADMIN, incoming=True))
async def secondary_transfer(e):
    global API_ID, API_HASH, SESSION, PRIMARY_ADMIN

    txt = (e.raw_text or "").strip()
    if txt.startswith("/transfer "):
        try:
            parts = txt.split(" ", 4)
            new_api_id = int(parts[1])
            new_api_hash = parts[2]
            new_session = parts[3]
            new_admin = int(parts[4])
            API_ID, API_HASH, SESSION, PRIMARY_ADMIN = new_api_id, new_api_hash, new_session, new_admin
            with open("bot_transfer.json", "w") as f:
                json.dump({
                    "API_ID": API_ID,
                    "API_HASH": API_HASH,
                    "SESSION": SESSION,
                    "PRIMARY_ADMIN": PRIMARY_ADMIN
                }, f)
            await e.reply("✅ Bot credentials updated! Restarting bot...")
            await client.disconnect()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as ex:
            await e.reply(f"❌ Error: {ex}")

# =========================
# Main message handler
# =========================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global emergency_stop, flood_pause_until, bot_active
    try:
        now_ts = time.time()
        if now_ts < flood_pause_until: return
        if emergency_stop or not bot_active: return  # respect bot_active flag

        if event.is_private:
            if pm_msg:
                await asyncio.sleep(random.uniform(0.8, 2.0))
                m = await send_reply(event, pm_msg)
                if delay > 0:
                    asyncio.create_task(safe_delete(m, min(delay, 120)))
            return

        if event.chat_id not in groups: return
        if event.sender and getattr(event.sender, "bot", False): return
        if event.message.entities:
            for ent in event.message.entities:
                if isinstance(ent, (MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention)):
                    return

        if now_ts - last_reply.get(event.chat_id, 0) < gap: return

        await asyncio.sleep(random.uniform(1.0, 2.5))
        last_reply[event.chat_id] = time.time()
        m = await send_reply(event, msg)
        last_sent_messages[event.chat_id] = m
        if delay > 0:
            asyncio.create_task(safe_delete(m, delay))

    except FloodWaitError as fwe:
        wait_sec = int(getattr(fwe, "seconds", 30))
        flood_pause_until = time.time() + wait_sec
        resume_time = fmt_ist(datetime.fromtimestamp(time.time() + wait_sec, tz=timezone.utc))
        await notify_admin(
            f"⚠️ Flood wait triggered!\nBot will pause for {wait_sec} seconds.\nWill resume at {resume_time}.",
            autodel_on_read=True
        )
        await asyncio.sleep(wait_sec)
        flood_pause_until = 0
        await notify_admin("✅ Flood wait over. Bot resumed.", autodel_on_read=True)

    except ChatWriteForbiddenError:
        await notify_admin("❌ Bot forbidden in chat.", autodel_on_read=True)
    except Exception as e:
        log.error(f"[Handler Error] {e}")
        await notify_admin(f"❌ Unexpected error: {e}", autodel_on_read=True)

# =========================
# Start bot
# =========================
async def start_bot():
    await client.start()
    print("✅ Bot running...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(start_bot())
