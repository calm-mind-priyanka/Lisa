from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError, FloodWaitError
from telethon.tl import types as tltypes
from telethon.tl.types import (
    MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention,
    UserStatusOnline, UserStatusOffline
)
import os, asyncio, json, time, random, sys, logging
from fastapi import FastAPI
import uvicorn
from datetime import datetime, timedelta, timezone

# =========================
# Logging Configuration
# =========================
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("error.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ],
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bot")

# =========================
# Keep-alive API (Koyeb / Render)
# =========================
app = FastAPI()

# =========================
# Load Credentials & Config
# =========================
CONFIG_FILE = "bot_transfer.json"

# Secrets must be supplied through Koyeb environment variables. A legacy
# bot_transfer.json is still supported for existing deployments, but secrets
# are never embedded in source code.
try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        _config = json.load(f)
except (OSError, json.JSONDecodeError):
    _config = {}
API_ID = int(os.getenv("API_ID", _config.get("API_ID") or 0))
API_HASH = os.getenv("API_HASH", _config.get("API_HASH") or "")
SESSION = os.getenv("SESSION", _config.get("SESSION") or "")
PRIMARY_ADMIN = int(os.getenv("PRIMARY_ADMIN", _config.get("PRIMARY_ADMIN") or 0))
SECONDARY_ADMIN = int(os.getenv("SECONDARY_ADMIN", PRIMARY_ADMIN or 0))

# =========================
# Files & State Management
# =========================
GROUPS_FILE = "groups.json"
SETTINGS_FILE = "settings.json"

def load_data():
    groups = set()
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                raw_groups = json.load(f)
            # Normalize persisted IDs: JSON string IDs and integer IDs must compare
            # equally with Telethon's integer event.chat_id.
            groups = set()
            invalid_group_ids = []
            for raw_gid in raw_groups:
                try:
                    groups.add(int(raw_gid))
                except (TypeError, ValueError):
                    invalid_group_ids.append(str(raw_gid))
            log.info(
                "GROUPS_LOADED file=%s count=%d ids=%s invalid_count=%d",
                GROUPS_FILE, len(groups), sorted(groups), len(invalid_group_ids)
            )
            if invalid_group_ids:
                log.warning("GROUPS_INVALID_IDS values=%s", invalid_group_ids[:20])
        except Exception as e:
            log.exception("GROUPS_LOAD_FAILED file=%s error=%s", GROUPS_FILE, e)
    else:
        log.warning("GROUPS_FILE_MISSING file=%s; group auto-replies need /addgroup", GROUPS_FILE)

    defaults = {
        "reply_msg": "🤖 Bot is active!",
        "delete_delay": 15,
        "reply_gap": 30,
        "pm_msg": None,
        "admin_autodel": 20,
        "rate_send_interval": 1.6,
        "rate_edit_interval": 1.2,
        "rate_delete_interval": 1.4,
    }
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception as e:
            log.error(f"Error loading settings: {e}")

    return (
        groups,
        defaults["reply_msg"],
        defaults["delete_delay"],
        defaults["reply_gap"],
        defaults["pm_msg"],
        defaults["admin_autodel"],
        defaults["rate_send_interval"],
        defaults["rate_edit_interval"],
        defaults["rate_delete_interval"]
    )

def save_groups():
    try:
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(groups), f, indent=2)
    except Exception as e:
        log.error(f"Error saving groups: {e}")

def save_settings():
    try:
        data = {
            "reply_msg": msg,
            "delete_delay": delay,
            "reply_gap": gap,
            "pm_msg": pm_msg,
            "admin_autodel": admin_autodel,
            "rate_send_interval": rate_send_interval,
            "rate_edit_interval": rate_edit_interval,
            "rate_delete_interval": rate_delete_interval,
        }
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Error saving settings: {e}")

(
    groups, msg, delay, gap, pm_msg, 
    admin_autodel, rate_send_interval, 
    rate_edit_interval, rate_delete_interval
) = load_data()

# Runtime trackers
last_reply = {}
last_sent_messages = {}
bot_active = True
emergency_stop = False
flood_pause_until = 0
WATCHED_ADMIN_ID = None
WATCH_GRACE_SEC = 5
start_time_global = time.time()

# Time helpers
IST = timezone(timedelta(hours=5, minutes=30))
def now_utc(): return datetime.now(timezone.utc)
def fmt_ist(dt_utc: datetime): return dt_utc.astimezone(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")

# =========================
# Advanced Rate Limiter
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
# Telegram Client Initialization
# =========================
if not (API_ID and API_HASH and SESSION and PRIMARY_ADMIN):
    log.warning("Telegram credentials are missing. Set API_ID, API_HASH, SESSION, and PRIMARY_ADMIN in Koyeb environment variables.")

client = TelegramClient(StringSession(SESSION), API_ID or 1, API_HASH or "missing-api-hash")

# Campaign tracker routes and join/leave event handler share this same FastAPI
# app and Telethon client; no second web service is created.
from tracker import install_tracker
start_tracker_reconciler = install_tracker(app, client, lambda: PRIMARY_ADMIN)

admin_dm_pending = {}

async def _schedule_delete_after_read(msg, seconds: int):
    admin_dm_pending[msg.id] = (msg, time.time() + 120)

@client.on(events.Raw)
async def on_raw_update(update):
    try:
        if isinstance(update, (tltypes.UpdateReadHistoryOutbox, tltypes.UpdateReadHistoryInbox)):
            peer = update.peer
            target_uid = None
            if isinstance(peer, tltypes.PeerUser):
                target_uid = peer.user_id
            
            if target_uid in (PRIMARY_ADMIN, SECONDARY_ADMIN) or hasattr(update, 'max_id'):
                max_id = getattr(update, 'max_id', 0)
                if max_id > 0:
                    to_delete = [mid for mid in list(admin_dm_pending.keys()) if mid <= max_id]
                    for mid in to_delete:
                        msg_obj, expire_at = admin_dm_pending.pop(mid, (None, 0))
                        if msg_obj:
                            asyncio.create_task(safe_delete(msg_obj, 1.0))
    except Exception as e:
        log.debug(f"on_raw_update error: {e}")

async def dm_cleanup_watcher():
    while True:
        await asyncio.sleep(10)
        now = time.time()
        for mid, (msg_obj, expire_at) in list(admin_dm_pending.items()):
            if now >= expire_at:
                admin_dm_pending.pop(mid, None)
                if msg_obj:
                    asyncio.create_task(safe_delete(msg_obj, 0.5))

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
                try: 
                    await delete_rl.wait()
                    await msg_obj.delete()
                except: 
                    pass
            last_sent_messages.clear()
        elif isinstance(event.status, UserStatusOffline):
            emergency_stop = False
            await notify_admin(f"✅ Emergency stop lifted (watched admin offline at {fmt_ist(now_utc())}).")

# =========================
# Admin Commands Handler
# =========================
@client.on(events.NewMessage(outgoing=True, from_users=PRIMARY_ADMIN))
async def primary_admin_handler(e):
    global msg, delay, gap, pm_msg, admin_autodel, bot_active

    txt = (e.raw_text or "").strip()

    if txt.startswith("/ping"):
        t1 = time.time()
        m = await e.reply("Pinging...")
        latency = round((time.time() - t1) * 1000)
        await m.edit(f"Pong! 🏓 `{latency}ms`")
        return

    if txt.startswith("/status"):
        uptime_sec = int(time.time() - start_time_global)
        uptime_str = str(timedelta(seconds=uptime_sec))
        status_text = (
            f"🤖 **Bot Status Report**\n"
            f"• State: `{'Active ✅' if bot_active else 'Stopped ⛔'}`\n"
            f"• Uptime: `{uptime_str}`\n"
            f"• Monitored Groups: `{len(groups)}`\n"
            f"• Emergency Stop: `{emergency_stop}`\n"
            f"• Delay / Gap: `{delay}s / {gap}s`"
        )
        await e.reply(status_text)
        return

    if txt.startswith("/listgroups"):
        if not groups:
            await e.reply("📂 No groups added to the tracking list yet.")
            return
        
        group_list_text = "📋 **Monitored Groups List:**\n\n"
        for gid in groups:
            try:
                chat = await client.get_entity(gid)
                title = getattr(chat, "title", "Unknown Title")
                group_list_text += f"• **{title}**\n  `{gid}`\n\n"
            except Exception:
                group_list_text += f"• **[Could not fetch name]**\n  `{gid}`\n\n"
        
        if len(group_list_text) > 4000:
            for chunk in [group_list_text[i:i+4000] for i in range(0, len(group_list_text), 4000)]:
                await e.reply(chunk)
        else:
            await e.reply(group_list_text)
        return

    if txt.startswith("/update"):
        m = await e.reply("🔄 Pulling latest code updates from GitHub...")
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "pull",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                output = stdout.decode().strip()
                await m.edit(f"✅ **Update Successful!**\n```{output}```\n\n🔄 Restarting bot application...")
                await client.disconnect()
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                err = stderr.decode().strip()
                await m.edit(f"❌ **Git Pull Failed:**\n```{err}```")
        except Exception as ex:
            await m.edit(f"❌ **Error executing update:** `{ex}`")
        return

    if txt.startswith("/setmsg "):
        msg = txt[len("/setmsg "):].strip()
        save_settings()
        await e.reply("✅ Reply message updated successfully.")
        return

    if txt.startswith("/setdel "):
        try:
            delay = int(txt[len("/setdel "):].strip())
            save_settings()
            await e.reply(f"✅ Delete delay set to `{delay}` seconds.")
        except ValueError:
            await e.reply("❌ Invalid number provided for delete delay.")
        return

    if txt.startswith("/setgap "):
        try:
            gap = int(txt[len("/setgap "):].strip())
            save_settings()
            await e.reply(f"✅ Reply gap set to `{gap}` seconds.")
        except ValueError:
            await e.reply("❌ Invalid number provided for reply gap.")
        return

    if txt.startswith("/setpm "):
        pm_msg = txt[len("/setpm "):].strip()
        save_settings()
        await e.reply("✅ Private message auto-reply updated.")
        return

    if txt.startswith("/addgroup "):
        try:
            gid = int(txt[len("/addgroup "):].strip())
            groups.add(gid)
            save_groups()
            await e.reply(f"✅ Group `{gid}` added to watchlist.")
        except ValueError:
            await e.reply("❌ Invalid Group ID format.")
        return

    if txt.startswith("/delgroup "):
        try:
            gid = int(txt[len("/delgroup "):].strip())
            groups.discard(gid)
            save_groups()
            await e.reply(f"✅ Group `{gid}` removed from watchlist.")
        except ValueError:
            await e.reply("❌ Invalid Group ID format.")
        return

    if txt.startswith("/stopbot"):
        if bot_active:
            bot_active = False
            await e.reply("⛔ Bot auto-replies paused.")
        else:
            await e.reply("⚠️ Bot is already stopped.")
        return

    if txt.startswith("/resumebot"):
        if not bot_active:
            bot_active = True
            await e.reply("✅ Bot auto-replies resumed.")
        else:
            await e.reply("⚠️ Bot is already active.")
        return

# =========================
# Secondary Admin (/transfer)
# =========================
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "API_ID": API_ID,
                    "API_HASH": API_HASH,
                    "SESSION": SESSION,
                    "PRIMARY_ADMIN": PRIMARY_ADMIN
                }, f, indent=2)
            await e.reply("✅ Bot credentials updated! Restarting bot...")
            await client.disconnect()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as ex:
            await e.reply(f"❌ Error during transfer: {ex}")

# =========================
# Incoming Message Handler (Guaranteed Exact User Reply)
# =========================
@client.on(events.NewMessage(incoming=True))
async def message_handler(event):
    global emergency_stop, flood_pause_until, bot_active
    chat_id = event.chat_id
    sender_id = event.sender_id
    # Do not log message text; IDs and decision reasons are enough to diagnose.
    try:
        log.info(
            "INCOMING_MESSAGE chat_id=%s sender_id=%s private=%s text_len=%s",
            chat_id, sender_id, event.is_private, len(event.raw_text or "")
        )
        now_ts = time.time()
        if now_ts < flood_pause_until:
            log.info("AUTO_REPLY_SKIPPED reason=flood_pause chat_id=%s seconds_left=%d",
                     chat_id, int(flood_pause_until - now_ts))
            return
        if emergency_stop:
            log.info("AUTO_REPLY_SKIPPED reason=emergency_stop chat_id=%s", chat_id)
            return
        if not bot_active:
            log.info("AUTO_REPLY_SKIPPED reason=bot_inactive chat_id=%s", chat_id)
            return

        if event.is_private:
            if pm_msg:
                log.info("PM_AUTO_REPLY_ATTEMPT chat_id=%s sender_id=%s", chat_id, sender_id)
                await asyncio.sleep(random.uniform(0.5, 1.2))
                await send_rl.wait()
                m = await event.reply(pm_msg)
                log.info("PM_AUTO_REPLY_SUCCESS chat_id=%s reply_message_id=%s", chat_id, m.id)
                if delay > 0:
                    asyncio.create_task(safe_delete(m, min(delay, 120)))
            else:
                log.info("PM_AUTO_REPLY_SKIPPED reason=no_pm_message chat_id=%s", chat_id)
            return

        if chat_id not in groups:
            log.info("AUTO_REPLY_SKIPPED reason=group_not_watched chat_id=%s watched=%s",
                     chat_id, chat_id in groups)
            return

        # Block messages sent by admin IDs or the userbot itself.
        if sender_id in (PRIMARY_ADMIN, SECONDARY_ADMIN, client.uid):
            log.info("AUTO_REPLY_SKIPPED reason=excluded_sender chat_id=%s sender_id=%s", chat_id, sender_id)
            return

        sender = event.sender
        if sender and getattr(sender, "bot", False):
            log.info("AUTO_REPLY_SKIPPED reason=sender_is_bot chat_id=%s sender_id=%s", chat_id, sender_id)
            return

        if event.is_channel and event.out:
            log.info("AUTO_REPLY_SKIPPED reason=outgoing_channel_message chat_id=%s", chat_id)
            return

        if event.message.entities:
            for ent in event.message.entities:
                if isinstance(ent, (MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention)):
                    log.info("AUTO_REPLY_SKIPPED reason=url_or_mention_entity chat_id=%s entity=%s",
                             chat_id, type(ent).__name__)
                    return

        elapsed = now_ts - last_reply.get(chat_id, 0)
        if elapsed < gap:
            log.info("AUTO_REPLY_SKIPPED reason=reply_gap chat_id=%s seconds_left=%d",
                     chat_id, int(gap - elapsed))
            return

        log.info("AUTO_REPLY_ATTEMPT chat_id=%s sender_id=%s", chat_id, sender_id)
        await asyncio.sleep(random.uniform(0.8, 1.8))
        last_reply[chat_id] = time.time()
        await send_rl.wait()
        m = await event.reply(msg)
        last_sent_messages[chat_id] = m
        log.info("AUTO_REPLY_SUCCESS chat_id=%s reply_message_id=%s", chat_id, m.id)
        if delay > 0:
            asyncio.create_task(safe_delete(m, delay))

    except FloodWaitError as fwe:
        wait_sec = int(getattr(fwe, "seconds", 30))
        flood_pause_until = time.time() + wait_sec
        resume_time = fmt_ist(datetime.fromtimestamp(time.time() + wait_sec, tz=timezone.utc))
        log.warning("AUTO_REPLY_FLOOD_WAIT chat_id=%s seconds=%s", chat_id, wait_sec)
        await notify_admin(f"⚠️ Flood wait triggered! Pausing for {wait_sec}s until {resume_time}.")
        await asyncio.sleep(wait_sec)
        flood_pause_until = 0
        await notify_admin("✅ Flood wait over. Bot resumed.")

    except ChatWriteForbiddenError:
        log.exception("AUTO_REPLY_FAILED reason=chat_write_forbidden chat_id=%s sender_id=%s", chat_id, sender_id)
    except Exception as e:
        log.exception("AUTO_REPLY_FAILED chat_id=%s sender_id=%s error=%s", chat_id, sender_id, e)

# =========================
# Main Execution
# =========================
async def main():
    if not (API_ID and API_HASH and SESSION and PRIMARY_ADMIN):
        raise RuntimeError("Missing Telegram credentials. Configure API_ID, API_HASH, SESSION, and PRIMARY_ADMIN in Koyeb environment variables.")
    await client.start()
    log.info(
        "TELEGRAM_CONNECTED user_id=%s watched_group_count=%d watched_group_ids=%s bot_active=%s emergency_stop=%s",
        client.uid, len(groups), sorted(groups), bot_active, emergency_stop
    )
    start_tracker_reconciler()
    asyncio.create_task(dm_cleanup_watcher())
    log.info("Telegram userbot started successfully.")
    port = int(os.getenv("PORT", "8080"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    # Keep the HTTP app and Telethon on one asyncio loop. Running Uvicorn in a
    # separate thread breaks async Telegram calls made by dashboard requests.
    server_task = asyncio.create_task(server.serve())
    client_task = asyncio.create_task(client.run_until_disconnected())
    log.info("Campaign dashboard listening on port %s", port)
    done, _ = await asyncio.wait({server_task, client_task}, return_when=asyncio.FIRST_COMPLETED)
    if client_task in done:
        server.should_exit = True
        await server_task
        client_task.result()
    if server_task in done:
        await client.disconnect()
        server_task.result()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
