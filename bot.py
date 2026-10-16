from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import ChatWriteForbiddenError, FloodWaitError
from telethon.tl import types as tltypes
from telethon.tl.types import (
    MessageEntityUrl, MessageEntityTextUrl, MessageEntityMention,
    UserStatusOnline, UserStatusOffline
)
import os, asyncio, json, threading, time, random, sys, logging
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


@app.get("/")
async def root():
    return {"status": "Bot is alive and running!"}


def run_web():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


threading.Thread(target=run_web, daemon=True).start()

# =========================
# Load Credentials from Environment Variables
# =========================
# Configure these in Koyeb Environment Variables.
# Never commit credentials or session strings to GitHub.

try:
    API_ID = int(os.environ["API_ID"])
    API_HASH = os.environ["API_HASH"]
    SESSION = os.environ["SESSION"]
    PRIMARY_ADMIN = int(os.environ["PRIMARY_ADMIN"])

    SECONDARY_ADMIN = int(
        os.getenv("SECONDARY_ADMIN", str(PRIMARY_ADMIN))
    )

except KeyError as exc:
    raise RuntimeError(
        f"Missing required environment variable: {exc.args[0]}. "
        "Set API_ID, API_HASH, SESSION, and PRIMARY_ADMIN in Koyeb."
    ) from exc

except ValueError as exc:
    raise RuntimeError(
        "API_ID, PRIMARY_ADMIN, and SECONDARY_ADMIN must be numeric."
    ) from exc


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
                groups = set(json.load(f))
        except Exception as e:
            log.error(f"Error loading groups: {e}")

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
    groups,
    msg,
    delay,
    gap,
    pm_msg,
    admin_autodel,
    rate_send_interval,
    rate_edit_interval,
    rate_delete_interval
) = load_data()


# =========================
# Runtime Trackers
# =========================
last_reply = {}
last_sent_messages = {}

bot_active = True
emergency_stop = False
flood_pause_until = 0

WATCHED_ADMIN_ID = None
WATCH_GRACE_SEC = 5

start_time_global = time.time()


# =========================
# Time Helpers
# =========================
IST = timezone(timedelta(hours=5, minutes=30))


def now_utc():
    return datetime.now(timezone.utc)


def fmt_ist(dt_utc: datetime):
    return dt_utc.astimezone(IST).strftime(
        "%Y-%m-%d %I:%M:%S %p IST"
    )


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

            self._next_allowed = (
                time.time()
                + self.min_interval
                + random.uniform(0, self.jitter)
            )


send_rl = RateLimiter(rate_send_interval, jitter=0.5)
edit_rl = RateLimiter(rate_edit_interval, jitter=0.4)
delete_rl = RateLimiter(rate_delete_interval, jitter=0.6)


# =========================
# Telegram Client Initialization
# =========================
client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH
)

admin_dm_pending = {}


async def _schedule_delete_after_read(msg, seconds: int):
    admin_dm_pending[msg.id] = (msg, time.time() + 120)


@client.on(events.Raw)
async def on_raw_update(update):
    try:
        if isinstance(
            update,
            (
                tltypes.UpdateReadHistoryOutbox,
                tltypes.UpdateReadHistoryInbox
            )
        ):
            peer = update.peer
            target_uid = None

            if isinstance(peer, tltypes.PeerUser):
                target_uid = peer.user_id

            if (
                target_uid in (PRIMARY_ADMIN, SECONDARY_ADMIN)
                or hasattr(update, "max_id")
            ):
                max_id = getattr(update, "max_id", 0)

                if max_id > 0:
                    to_delete = [
                        mid
                        for mid in list(admin_dm_pending.keys())
                        if mid <= max_id
                    ]

                    for mid in to_delete:
                        msg_obj, expire_at = admin_dm_pending.pop(
                            mid, (None, 0)
                        )

                        if msg_obj:
                            asyncio.create_task(
                                safe_delete(msg_obj, 1.0)
                            )

    except Exception as e:
        log.debug(f"on_raw_update error: {e}")


async def dm_cleanup_watcher():
    while True:
        await asyncio.sleep(10)
        now = time.time()

        for mid, (msg_obj, expire_at) in list(
            admin_dm_pending.items()
        ):
            if now >= expire_at:
                admin_dm_pending.pop(mid, None)

                if msg_obj:
                    asyncio.create_task(
                        safe_delete(msg_obj, 0.5)
                    )


async def safe_delete(message, after_sec: float):
    await asyncio.sleep(
        after_sec + random.uniform(0.5, 2.0)
    )

    try:
        await delete_rl.wait()
        await message.delete()

    except Exception as e:
        log.warning(f"Delete failed: {e}")


async def notify_admin(
    text: str,
    autodel_on_read=True,
    autodel_sec=None
):
    try:
        await send_rl.wait()

        m = await client.send_message(
            PRIMARY_ADMIN,
            text
        )

        if autodel_on_read:
            sec = (
                autodel_sec
                if autodel_sec is not None
                else admin_autodel
            )

            asyncio.create_task(
                _schedule_delete_after_read(m, sec)
            )

        return m

    except Exception as e:
        log.error(f"Failed to notify admin: {e}")


# =========================
# Emergency Watch
# =========================
@client.on(events.UserUpdate)
async def watch_admin(event):
    global emergency_stop

    if WATCHED_ADMIN_ID and event.user_id == WATCHED_ADMIN_ID:

        if isinstance(event.status, UserStatusOnline):
            await asyncio.sleep(WATCH_GRACE_SEC)

            emergency_stop = True

            await notify_admin(
                "🚨 Emergency stop activated "
                f"(watched admin online at {fmt_ist(now_utc())})."
            )

            for chat_id, msg_obj in list(
                last_sent_messages.items()
            ):
                try:
                    await delete_rl.wait()
                    await msg_obj.delete()
                except Exception:
                    pass

            last_sent_messages.clear()

        elif isinstance(event.status, UserStatusOffline):
            emergency_stop = False

            await notify_admin(
                "✅ Emergency stop lifted "
                f"(watched admin offline at {fmt_ist(now_utc())})."
            )


# =========================
# Primary Admin Commands
# =========================
@client.on(
    events.NewMessage(
        outgoing=True,
        from_users=PRIMARY_ADMIN
    )
)
async def primary_admin_handler(e):
    global msg, delay, gap, pm_msg, admin_autodel, bot_active

    txt = (e.raw_text or "").strip()

    # Ping
    if txt.startswith("/ping"):
        t1 = time.time()

        m = await e.reply("Pinging...")

        latency = round((time.time() - t1) * 1000)

        await m.edit(f"Pong! 🏓 `{latency}ms`")
        return

    # Status
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

    # List groups
    if txt.startswith("/listgroups"):
        if not groups:
            await e.reply(
                "📂 No groups added to the tracking list yet."
            )
            return

        group_list_text = "📋 **Monitored Groups List:**\n\n"

        for gid in groups:
            try:
                chat = await client.get_entity(gid)
                title = getattr(
                    chat,
                    "title",
                    "Unknown Title"
                )

                group_list_text += (
                    f"• **{title}**\n  `{gid}`\n\n"
                )

            except Exception:
                group_list_text += (
                    "• **[Could not fetch name]**\n"
                    f"  `{gid}`\n\n"
                )

        if len(group_list_text) > 4000:
            for chunk in [
                group_list_text[i:i + 4000]
                for i in range(0, len(group_list_text), 4000)
            ]:
                await e.reply(chunk)
        else:
            await e.reply(group_list_text)

        return

    # Update command
    if txt.startswith("/update"):
        m = await e.reply(
            "🔄 Pulling latest code updates from GitHub..."
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "pull",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                output = stdout.decode().strip()

                await m.edit(
                    f"✅ **Update Successful!**\n"
                    f"```{output}```\n\n"
                    f"🔄 Restarting bot application..."
                )

                await client.disconnect()

                os.execv(
                    sys.executable,
                    [sys.executable] + sys.argv
                )

            else:
                err = stderr.decode().strip()

                await m.edit(
                    f"❌ **Git Pull Failed:**\n```{err}```"
                )

        except Exception as ex:
            await m.edit(
                f"❌ **Error executing update:** `{ex}`"
            )

        return

    # Set reply message
    if txt.startswith("/setmsg "):
        msg = txt[len("/setmsg "):].strip()

        save_settings()

        await e.reply(
            "✅ Reply message updated successfully."
        )
        return

    # Set delete delay
    if txt.startswith("/setdel "):
        try:
            delay = int(txt[len("/setdel "):].strip())

            save_settings()

            await e.reply(
                f"✅ Delete delay set to `{delay}` seconds."
            )

        except ValueError:
            await e.reply(
                "❌ Invalid number provided for delete delay."
            )

        return

    # Set reply gap
    if txt.startswith("/setgap "):
        try:
            gap = int(txt[len("/setgap "):].strip())

            save_settings()

            await e.reply(
                f"✅ Reply gap set to `{gap}` seconds."
            )

        except ValueError:
            await e.reply(
                "❌ Invalid number provided for reply gap."
            )

        return

    # Set private-message reply
    if txt.startswith("/setpm "):
        pm_msg = txt[len("/setpm "):].strip()

        save_settings()

        await e.reply(
            "✅ Private message auto-reply updated."
        )
        return

    # Add group
    if txt.startswith("/addgroup "):
        try:
            gid = int(txt[len("/addgroup "):].strip())

            groups.add(gid)
            save_groups()

            await e.reply(
                f"✅ Group `{gid}` added to watchlist."
            )

        except ValueError:
            await e.reply(
                "❌ Invalid Group ID format."
            )

        return

    # Remove group
    if txt.startswith("/delgroup "):
        try:
            gid = int(txt[len("/delgroup "):].strip())

            groups.discard(gid)
            save_groups()

            await e.reply(
                f"✅ Group `{gid}` removed from watchlist."
            )

        except ValueError:
            await e.reply(
                "❌ Invalid Group ID format."
            )

        return

    # Stop bot
    if txt.startswith("/stopbot"):
        if bot_active:
            bot_active = False

            await e.reply(
                "⛔ Bot auto-replies paused."
            )
        else:
            await e.reply(
                "⚠️ Bot is already stopped."
            )

        return

    # Resume bot
    if txt.startswith("/resumebot"):
        if not bot_active:
            bot_active = True

            await e.reply(
                "✅ Bot auto-replies resumed."
            )
        else:
            await e.reply(
                "⚠️ Bot is already active."
            )

        return


# =========================
# Secondary Admin
# =========================
@client.on(
    events.NewMessage(
        from_users=SECONDARY_ADMIN,
        incoming=True
    )
)
async def secondary_transfer(e):
    # Credentials must be updated through Koyeb environment variables.
    # The transfer command is disabled to avoid exposing secrets.
    txt = (e.raw_text or "").strip()

    if txt.startswith("/transfer"):
        await e.reply(
            "🔒 Credential transfer is disabled. Update API_ID, "
            "API_HASH, SESSION, and PRIMARY_ADMIN in your "
            "Koyeb environment variables, then redeploy."
        )


# =========================
# Incoming Message Handler
# =========================
@client.on(events.NewMessage(incoming=True))
async def message_handler(event):
    global emergency_stop, flood_pause_until, bot_active

    try:
        now_ts = time.time()

        if (
            now_ts < flood_pause_until
            or emergency_stop
            or not bot_active
        ):
            return

        # Private messages
        if event.is_private:
            if pm_msg:
                await asyncio.sleep(
                    random.uniform(0.5, 1.2)
                )

                await send_rl.wait()

                m = await event.reply(pm_msg)

                if delay > 0:
                    asyncio.create_task(
                        safe_delete(m, min(delay, 120))
                    )

            return

        # Only process configured groups
        if event.chat_id not in groups:
            return

        # Ignore configured admins and this account
        if event.sender_id in (
            PRIMARY_ADMIN,
            SECONDARY_ADMIN,
            client.uid
        ):
            return

        # Ignore bot accounts
        if (
            event.sender
            and getattr(event.sender, "bot", False)
        ):
            return

        # Ignore channel-originated outgoing messages
        if event.is_channel and event.out:
            return

        # Ignore messages containing links or mentions
        if event.message.entities:
            for ent in event.message.entities:
                if isinstance(
                    ent,
                    (
                        MessageEntityUrl,
                        MessageEntityTextUrl,
                        MessageEntityMention
                    )
                ):
                    return

        # Respect reply gap
        if now_ts - last_reply.get(event.chat_id, 0) < gap:
            return

        await asyncio.sleep(
            random.uniform(0.8, 1.8)
        )

        last_reply[event.chat_id] = time.time()

        # Reply to the triggering message
        await send_rl.wait()

        m = await event.reply(msg)

        last_sent_messages[event.chat_id] = m

        if delay > 0:
            asyncio.create_task(
                safe_delete(m, delay)
            )

    except FloodWaitError as fwe:
        wait_sec = int(
            getattr(fwe, "seconds", 30)
        )

        flood_pause_until = time.time() + wait_sec

        resume_time = fmt_ist(
            datetime.fromtimestamp(
                time.time() + wait_sec,
                tz=timezone.utc
            )
        )

        log.warning(
            f"Flood wait triggered: sleeping for {wait_sec}s"
        )

        await notify_admin(
            f"⚠️ Flood wait triggered! "
            f"Pausing for {wait_sec}s until {resume_time}."
        )

        await asyncio.sleep(wait_sec)

        flood_pause_until = 0

        await notify_admin(
            "✅ Flood wait over. Bot resumed."
        )

    except ChatWriteForbiddenError:
        log.warning(
            f"Chat write forbidden in chat {event.chat_id}"
        )

    except Exception as e:
        log.error(
            f"[Handler Error] {e}"
        )


# =========================
# Main Execution
# =========================
async def main():
    await client.start()

    asyncio.create_task(
        dm_cleanup_watcher()
    )

    log.info(
        "✅ Telegram userbot started successfully."
    )

    print("✅ Bot running...")

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Bot stopped by user.")
