import asyncio
import logging
import os
import sys
import time
import threading
import tempfile
import shutil
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, ChatWriteForbiddenError

from ai_engine import AnanyaAI
from memory import ConversationMemory

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("ananya-bot")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_ID = int(required_env("API_ID"))
API_HASH = required_env("API_HASH")
SESSION = required_env("SESSION")
GEMINI_API_KEY = required_env("GEMINI_API_KEY")
SANDY_USER_ID = int(required_env("SANDY_USER_ID"))
PRIMARY_ADMIN = int(os.getenv("PRIMARY_ADMIN", str(SANDY_USER_ID)))

MODEL_NAME = os.getenv("GEMINI_MODEL", "").strip()
VOICE_REPLIES = os.getenv("VOICE_REPLIES", "false").lower() in {"1", "true", "yes", "on"}
VOICE_NAME = os.getenv("VOICE_NAME", "hi-IN-SwaraNeural")
MAX_HISTORY_TURNS = max(2, min(int(os.getenv("MAX_HISTORY_TURNS", "12")), 30))
MAX_MEDIA_MB = max(1, min(int(os.getenv("MAX_MEDIA_MB", "15")), 20))
PORT = int(os.getenv("PORT", "8080"))

def parse_ids(name: str) -> set[int]:
    values = os.getenv(name, "")
    result = set()
    for value in values.split(","):
        value = value.strip()
        if value and value.lstrip("-").isdigit():
            result.add(int(value))
    return result

AI_GROUP_IDS = parse_ids("AI_GROUP_IDS")
IGNORED_USER_IDS = parse_ids("IGNORED_USER_IDS")
IGNORED_USER_IDS.discard(SANDY_USER_ID)

bot_active = True
start_time = time.time()
memory = ConversationMemory(max_turns=MAX_HISTORY_TURNS)
ai = AnanyaAI(api_key=GEMINI_API_KEY, model_name=MODEL_NAME)
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

app = FastAPI(title="Ananya AI Userbot", docs_url=None, redoc_url=None)

@app.get("/")
async def root():
    return {"status": "Ananya AI userbot is alive and running"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ananya-ai-userbot"}


def run_web():
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


async def make_voice_note(text: str) -> str | None:
    if not VOICE_REPLIES:
        return None
    temp_dir = tempfile.mkdtemp(prefix="ananya_voice_")
    mp3_path = os.path.join(temp_dir, "reply.mp3")
    ogg_path = os.path.join(temp_dir, "reply.ogg")
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text[:2500], VOICE_NAME)
        await communicate.save(mp3_path)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "32k",
            "-vbr", "on", "-application", "voip", ogg_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(ogg_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        return ogg_path
    except Exception:
        log.exception("Voice generation failed; text response will still be sent")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


async def handle_incoming(event):
    global bot_active
    if event.out or not bot_active:
        return

    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False):
        return
    sender_id = int(sender.id)
    if sender_id in IGNORED_USER_IDS:
        return

    # Private chats work by default. Group chats are only enabled for IDs listed in
    # AI_GROUP_IDS and the bot only replies when mentioned or directly replied to.
    if event.is_private:
        pass
    else:
        if event.chat_id not in AI_GROUP_IDS:
            return
        me = await client.get_me()
        text_for_trigger = event.raw_text or ""
        is_reply_to_me = False
        if event.message and event.message.reply_to:
            try:
                replied = await event.get_reply_message()
                is_reply_to_me = bool(replied and replied.sender_id == me.id)
            except Exception:
                is_reply_to_me = False
        mentioned = bool(me.username and ("@" + me.username.lower()) in text_for_trigger.lower())
        if not mentioned and not is_reply_to_me:
            return

    text = (event.raw_text or "").strip()
    media = None
    mime_type = None
    is_voice_or_audio = bool(event.message and (event.message.voice or event.message.audio))
    is_photo = bool(event.message and event.message.photo)
    if not text and not (is_voice_or_audio or is_photo):
        return

    downloaded_path = None
    voice_path = None
    try:
        async with client.action(event.chat_id, "typing"):
            if is_voice_or_audio or is_photo:
                downloaded_path = await event.download_media()
                if downloaded_path:
                    size = os.path.getsize(downloaded_path)
                    if size > MAX_MEDIA_MB * 1024 * 1024:
                        await event.reply(f"That file is too large for me to process. Please send something under {MAX_MEDIA_MB} MB. 🙂")
                        return
                    suffix = Path(downloaded_path).suffix.lower()
                    if is_photo:
                        mime_type = {
                            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".png": "image/png", ".webp": "image/webp",
                        }.get(suffix, "image/jpeg")
                        text = text or "Look at this image and respond naturally about what you can actually see."
                    else:
                        mime_type = {
                            ".ogg": "audio/ogg", ".oga": "audio/ogg",
                            ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
                            ".wav": "audio/wav", ".webm": "audio/webm",
                        }.get(suffix, "audio/ogg" if event.message.voice else "audio/mpeg")
                        text = text or "Listen to this audio/voice message and respond naturally. If you cannot understand it, ask the sender to repeat it."
                    media = Path(downloaded_path).read_bytes()

            reply_text = await ai.reply(
                user_id=sender_id,
                user_text=text,
                history=memory.get(sender_id),
                is_sandy=(sender_id == SANDY_USER_ID),
                attachment=media,
                mime_type=mime_type,
            )
            reply_text = (reply_text or "").strip()
            if not reply_text:
                reply_text = "Sorry yaar, my thoughts got a little tangled 😅 Can you say that again?"

            memory.add(sender_id, text or "[media message]", reply_text)

            # Telegram messages are limited to 4096 characters.
            for offset in range(0, len(reply_text), 4000):
                await event.reply(reply_text[offset:offset + 4000])

            voice_path = await make_voice_note(reply_text)
            if voice_path:
                await client.send_file(event.chat_id, voice_path, voice_note=True, reply_to=event.id)
    finally:
        if downloaded_path:
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
        if voice_path:
            try:
                shutil.rmtree(os.path.dirname(voice_path), ignore_errors=True)
            except Exception:
                pass


@client.on(events.NewMessage(incoming=True))
async def incoming_message_handler(event):
    try:
        await handle_incoming(event)
    except FloodWaitError as exc:
        wait_seconds = min(int(getattr(exc, "seconds", 30)), 120)
        log.warning("Telegram FloodWait: sleeping for %s seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)
    except ChatWriteForbiddenError:
        log.warning("Cannot write to chat %s", event.chat_id)
    except Exception:
        log.exception("Incoming message handler failed")
        if event.is_private:
            try:
                await event.reply("Oops, something went wrong on my side. Please try again in a little while. 💛")
            except Exception:
                pass


@client.on(events.NewMessage(outgoing=True, from_users=PRIMARY_ADMIN))
async def admin_commands(event):
    global bot_active
    text = (event.raw_text or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""

    if command == "/ping":
        started = time.time()
        message = await event.reply("Pinging…")
        await message.edit(f"Pong! 🏓 `{round((time.time() - started) * 1000)} ms`")
    elif command == "/status":
        uptime = str(timedelta(seconds=int(time.time() - start_time)))
        me = await client.get_me()
        await event.reply(
            "🤖 **Ananya AI Status**\n"
            f"• State: `{'Active ✅' if bot_active else 'Paused ⛔'}`\n"
            f"• Uptime: `{uptime}`\n"
            f"• Telegram account ID: `{me.id}`\n"
            f"• AI-enabled groups: `{len(AI_GROUP_IDS)}`\n"
            f"• Memory: `temporary / in-memory`\n"
            f"• Voice replies: `{'on' if VOICE_REPLIES else 'off'}`"
        )
    elif command == "/stopbot":
        bot_active = False
        await event.reply("⛔ Ananya's automatic replies are paused. Use `/resumebot` to resume.")
    elif command == "/resumebot":
        bot_active = True
        await event.reply("✅ Ananya's automatic replies are active again.")
    elif command == "/clearallmemory":
        memory.clear_all()
        await event.reply("🧹 Temporary conversation memory has been cleared.")


async def main():
    threading.Thread(target=run_web, daemon=True, name="health-server").start()
    await client.start()
    me = await client.get_me()
    log.info("TELEGRAM_CONNECTED user_id=%s username=%s", me.id, me.username)
    log.info("Ananya AI userbot started; AI_GROUP_IDS=%s", sorted(AI_GROUP_IDS))
    if not AI_GROUP_IDS:
        log.info("Group replies are disabled. Set AI_GROUP_IDS to enable selected groups.")
    try:
        await client.run_until_disconnected()
    finally:
        await ai.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
