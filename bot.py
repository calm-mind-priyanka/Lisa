# bot.py
import os
import re
import time
import json
import sqlite3
import logging
import threading
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional
from telethon import TelegramClient, events, Button
from fastapi import FastAPI
import uvicorn
import aiohttp

# -------------------------
# CONFIG - set env vars or replace literal values
# -------------------------
API_ID = int(os.getenv("API_ID", "24222039"))
API_HASH = os.getenv("API_HASH", "6dd2dc70434b2f577f76a2e993135662")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE")
BOT_USERNAME = os.getenv("BOT_USERNAME", None)

ADMIN_ID = int(os.getenv("ADMIN_ID", "6046055058"))

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "files.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pro_filestore")

app = FastAPI()

# -------------------------
# DATABASE helpers
# -------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn(); cur = conn.cursor()
    # files table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            code TEXT PRIMARY KEY,
            owner_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            caption TEXT,
            file_type TEXT,
            created_at INTEGER,
            delete_at INTEGER,
            reply_chat_id INTEGER,
            reply_msg_id INTEGER
        )
    """)
    # settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            auto_delete_enabled INTEGER DEFAULT 0,
            delete_seconds INTEGER DEFAULT 0,
            protect_content INTEGER DEFAULT 0
        )
    """)
    cur.execute("INSERT OR IGNORE INTO settings (id, auto_delete_enabled, delete_seconds, protect_content) VALUES (1,0,0,0)")
    # verify settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verify_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            verify1_enabled INTEGER DEFAULT 0,
            verify1_shortener_template TEXT DEFAULT '',
            verify1_api_key TEXT DEFAULT '',
            verify2_enabled INTEGER DEFAULT 0,
            verify2_shortener_template TEXT DEFAULT '',
            verify2_api_key TEXT DEFAULT '',
            verify2_delay_seconds INTEGER DEFAULT 60
        )
    """)
    cur.execute("INSERT OR IGNORE INTO verify_settings (id) VALUES (1)")
    conn.commit(); conn.close()

# file helpers
def add_file_record(code, owner_id, file_id, file_name, caption, file_type, created_at=None, delete_at=None, reply_chat_id=None, reply_msg_id=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO files (code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, owner_id, file_id, file_name, caption, file_type, int(created_at or time.time()), int(delete_at) if delete_at else None, reply_chat_id, reply_msg_id))
    conn.commit(); conn.close()

def get_file_record(code):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id FROM files WHERE code = ?", (code,))
    row = cur.fetchone(); conn.close()
    return row

def delete_file_record(code):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE code = ?", (code,))
    conn.commit(); conn.close()

def list_user_files(user_id, limit=50):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, file_name, caption, created_at, delete_at FROM files WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    rows = cur.fetchall(); conn.close()
    return rows

def list_scheduled_deletes_future():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, delete_at FROM files WHERE delete_at IS NOT NULL")
    rows = cur.fetchall(); conn.close()
    return rows

# settings getters/setters
def get_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT auto_delete_enabled, delete_seconds, protect_content FROM settings WHERE id = 1")
    row = cur.fetchone(); conn.close()
    return {"auto_delete_enabled": bool(row[0]), "delete_seconds": int(row[1]), "protect_content": bool(row[2])}

def set_setting(auto_delete=None, delete_seconds=None, protect_content=None):
    conn = get_conn(); cur = conn.cursor()
    if auto_delete is not None:
        cur.execute("UPDATE settings SET auto_delete_enabled = ? WHERE id = 1", (1 if auto_delete else 0,))
    if delete_seconds is not None:
        cur.execute("UPDATE settings SET delete_seconds = ? WHERE id = 1", (int(delete_seconds),))
    if protect_content is not None:
        cur.execute("UPDATE settings SET protect_content = ? WHERE id = 1", (1 if protect_content else 0,))
    conn.commit(); conn.close()

# verify settings getters/setters
def get_verify_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT verify1_enabled, verify1_shortener_template, verify1_api_key, verify2_enabled, verify2_shortener_template, verify2_api_key, verify2_delay_seconds FROM verify_settings WHERE id = 1")
    row = cur.fetchone(); conn.close()
    return {
        "verify1_enabled": bool(row[0]),
        "verify1_shortener_template": row[1] or "",
        "verify1_api_key": row[2] or "",
        "verify2_enabled": bool(row[3]),
        "verify2_shortener_template": row[4] or "",
        "verify2_api_key": row[5] or "",
        "verify2_delay_seconds": int(row[6] or 60)
    }

def set_verify_settings(**kwargs):
    conn = get_conn(); cur = conn.cursor()
    allowed = ["verify1_enabled","verify1_shortener_template","verify1_api_key","verify2_enabled","verify2_shortener_template","verify2_api_key","verify2_delay_seconds"]
    for k,v in kwargs.items():
        if k in allowed:
            cur.execute(f"UPDATE verify_settings SET {k} = ? WHERE id = 1", (1 if (k.endswith("_enabled") and v) else v,))
    conn.commit(); conn.close()

# -------------------------
# Utilities
# -------------------------
def gen_code():
    return uuid.uuid4().hex[:12]

_url_re = re.compile(r'(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)', flags=re.IGNORECASE)
_mention_re = re.compile(r'@[\w_]+')
_channel_link_re = re.compile(r'tg://joinchat/\S+', flags=re.IGNORECASE)

def sanitize_caption(text: str):
    if not text:
        return ""
    t = _url_re.sub("", text)
    t = _mention_re.sub("", t)
    t = _channel_link_re.sub("", t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def parse_duration(s: str):
    s = s.strip().lower()
    if s == "off": return 0
    m = re.match(r'^(\d+)\s*([smhd])$', s)
    if not m: return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {'s':1,'m':60,'h':3600,'d':86400}[unit]

def human_seconds(sec: int):
    if not sec or sec <= 0: return "N/A"
    parts=[]
    d, r = divmod(sec, 86400)
    if d: parts.append(f"{d}d")
    h, r = divmod(r, 3600)
    if h: parts.append(f"{h}h")
    m, r = divmod(r, 60)
    if m: parts.append(f"{m}m")
    if r: parts.append(f"{r}s")
    return " ".join(parts)

def is_admin(uid: int):
    return uid == ADMIN_ID

# -------------------------
# Telethon client
# -------------------------
client = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

async def ensure_username():
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await client.get_me()
        BOT_USERNAME = getattr(me, "username", None)

# -------------------------
# Auto-delete scheduler
# -------------------------
scheduled_tasks = {}

async def _delete_messages_safe(pairs: List[Tuple[int,int]]):
    for chat_id, msg_id in pairs:
        try: await client.delete_messages(chat_id, [msg_id])
        except Exception: log.warning("Could not delete %s in %s", msg_id, chat_id)

async def schedule_delete(code: str, when_ts: int, extra_messages: Optional[List[Tuple[int,int]]] = None):
    now = int(time.time()); delay = max(0, when_ts - now)
    if code in scheduled_tasks:
        try: scheduled_tasks[code].cancel()
        except Exception: pass

    async def _job():
        try:
            await asyncio.sleep(delay)
            rec = get_file_record(code); msgs=[]
            if rec:
                _,_,_,_,_,_,_,_, reply_chat_id, reply_msg_id = rec
                if reply_chat_id and reply_msg_id: msgs.append((reply_chat_id, reply_msg_id))
            if extra_messages: msgs.extend(extra_messages)
            if msgs: await _delete_messages_safe(msgs)
            delete_file_record(code)
            scheduled_tasks.pop(code,None)
            log.info("Auto-deleted %s", code)
        except asyncio.CancelledError: return
        except Exception: log.exception("Error in scheduled delete for %s", code)

    scheduled_tasks[code] = asyncio.create_task(_job())

async def reschedule_all():
    rows = list_scheduled_deletes_future(); now=int(time.time())
    for code, delete_at in rows:
        if delete_at and delete_at > now: await schedule_delete(code, delete_at)
        elif delete_at and delete_at <= now: delete_file_record(code); log.info("Removed expired %s", code)

# -------------------------
# VERIFY in-memory maps (short lived)
# -------------------------
# key: (user_id, code) -> ts of verify1
verified_stage1 = {}   # (user_id, code) -> timestamp
verified_stage2 = {}   # (user_id, code) -> timestamp

# helper to call shortener
async def call_shortener(template: str, api_key: str, target_url: str) -> Optional[str]:
    if not template: return None
    try:
        url = template.format(api_key=api_key, url=target_url)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=10) as resp:
                text = await resp.text()
                try:
                    j = json.loads(text)
                    for k in ("short","short_url","url","result"):
                        if k in j and isinstance(j[k], str) and j[k].startswith("http"):
                            return j[k]
                except Exception:
                    m = re.search(r'https?://\S+', text)
                    if m: return m.group(0)
    except Exception:
        log.exception("Shortener call failed")
    return None

# -------------------------
# Handlers: /start, deep link, settings
# -------------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
async def start_handler(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await ensure_username()
        s = get_settings(); v = get_verify_settings()
        text = (
            "👋 **Welcome to Pro FileStore Bot**\n\n"
            "📦 Send any file (or forward) and I'll generate a permanent share link.\n"
            f"🔒 Auto-delete: **{'ON' if s['auto_delete_enabled'] else 'OFF'}**\n"
            f"⏳ Delete after: **{human_seconds(s['delete_seconds'])}**\n"
            f"🚫 Forward protection: **{'ON' if s['protect_content'] else 'OFF'}**\n\n"
            f"🔐 VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}  |  VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}\n\n"
            "ADMIN COMMANDS: /setautodelete, /setforward, /settings"
        )
        buttons = [
            [Button.inline("📁 MY FILES", b"MY_FILES")],
            [Button.inline("⚙️ SETTINGS", b"ADMIN_PANEL")],
        ]
        await event.respond(text, buttons=buttons, link_preview=False)
        return

    # deep link expected file_<code>
    if arg.startswith("file_"):
        code = arg.split("file_",1)[1]
        rec = get_file_record(code)
        if not rec:
            await event.respond("❌ FILE NOT FOUND OR EXPIRED.")
            return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings(); v = get_verify_settings()

        user = await event.get_sender()
        uid = user.id if user else event.sender_id
        key1 = (uid, code)

        # If VERIFY1 enabled and user hasn't done stage1 -> show verify menu
        if v["verify1_enabled"] and key1 not in verified_stage1:
            await ensure_username()
            btns = []
            btns.append([Button.inline("✅ VERIFY 1", f"VERIFY1|{code}".encode())])
            if v["verify1_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start=VERIFY1|{code}"
                    short = await call_shortener(v["verify1_shortener_template"], v["verify1_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 VERIFY 1 VIA SHORT LINK", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ BACK", b"BACK")])
            text = (
                "🔐 **VERIFY 1 REQUIRED**\n\n"
                "YOU MUST COMPLETE VERIFY 1 BEFORE GETTING THE FILE.\n"
                "PRESS VERIFY 1 OR USE THE SHORT LINK IF PROVIDED."
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # If VERIFY2 enabled and user passed stage1 but not stage2 -> enforce delay and show verify2 menu
        key2 = (uid, code)
        if v["verify2_enabled"] and key1 in verified_stage1 and key2 not in verified_stage2:
            await ensure_username()
            btns = []
            btns.append([Button.inline("✅ VERIFY 2", f"VERIFY2|{code}".encode())])
            if v["verify2_shortener_template"]:
                try:
                    target = f"https://t.me/{BOT_USERNAME}?start=VERIFY2|{code}"
                    short = await call_shortener(v["verify2_shortener_template"], v["verify2_api_key"], target)
                    if short:
                        btns.append([Button.url("🌐 VERIFY 2 VIA SHORT LINK", short)])
                except Exception:
                    pass
            btns.append([Button.inline("⬅ BACK", b"BACK")])
            text = (
                "🔐 **VERIFY 2 REQUIRED**\n\n"
                f"SECOND VERIFICATION IS ENABLED. WAIT TIME: {human_seconds(v['verify2_delay_seconds'])}\n\n"
                "PRESS VERIFY 2 WHEN READY."
            )
            await event.respond(text, buttons=btns, link_preview=False)
            return

        # Passed verification (or no verify required) -> send file
        try:
            file_msg = await client.send_file(event.sender_id, file=file_id, caption=caption or file_name,
                                              force_document=False, allow_cache=True, supports_streaming=True,
                                              protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file for code %s", code)
            await event.respond("⚠️ FAILED TO SEND FILE. TRY AGAIN LATER.")
            return

        # schedule deletion if file has delete_at
        if delete_at:
            now = int(time.time()); remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. SAVE NOW."
                try:
                    notice_msg = await client.send_message(event.sender_id, notice_text, reply_to=file_msg.id)
                    extra = [(event.sender_id, file_msg.id), (event.sender_id, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed scheduling per-download delete for %s", code)
        return

    await event.respond("UNKNOWN START PARAMETER. SEND A FILE TO GENERATE A LINK.")

# -------------------------
# Callbacks: verify & admin & navigation
# -------------------------
@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode() if event.data else ""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id

    # BACK main menu
    if data == "BACK":
        await ensure_username()
        s = get_settings()
        text = (
            "👋 **WELCOME BACK!**\n\n"
            "SEND A FILE OR USE THE MENU BELOW."
        )
        btns = [[Button.inline("📁 MY FILES", b"MY_FILES")], [Button.inline("⚙️ SETTINGS", b"ADMIN_PANEL")]]
        await event.edit(text, buttons=btns)
        return

    # VERIFY1 inline callback -> mark stage1, send file immediately
    if data.startswith("VERIFY1|"):
        _, code = data.split("|",1)
        verified_stage1[(uid, code)] = int(time.time())
        await event.answer("✅ VERIFY 1 COMPLETED. SENDING FILE...", alert=True)
        rec = get_file_record(code)
        if not rec:
            await event.answer("FILE NOT FOUND.", alert=True); return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=caption or file_name,
                                              force_document=False, allow_cache=True, supports_streaming=True,
                                              protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file in VERIFY1 for %s", code)
            await event.answer("FAILED TO SEND FILE.", alert=True); return
        # schedule per-download delete if needed
        if delete_at:
            now = int(time.time()); remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. SAVE NOW."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed scheduling per-download delete for %s", code)
        return

    # VERIFY2 inline callback -> check delay since verify1 then send file
    if data.startswith("VERIFY2|"):
        _, code = data.split("|",1)
        key1 = (uid, code)
        v = get_verify_settings()
        if key1 not in verified_stage1:
            await event.answer("You must complete VERIFY 1 first.", alert=True); return
        ts_verify1 = verified_stage1.get(key1, 0)
        required = v["verify2_delay_seconds"]
        now = int(time.time())
        if now - ts_verify1 < required:
            remaining = required - (now - ts_verify1)
            await event.answer(f"Please wait {human_seconds(remaining)} before VERIFY 2.", alert=True)
            return
        # ok, complete stage2
        verified_stage2[(uid, code)] = int(time.time())
        await event.answer("✅ VERIFY 2 COMPLETED. SENDING FILE...", alert=True)
        rec = get_file_record(code)
        if not rec:
            await event.answer("FILE NOT FOUND.", alert=True); return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        s = get_settings()
        try:
            file_msg = await client.send_file(uid, file=file_id, caption=caption or file_name,
                                              force_document=False, allow_cache=True, supports_streaming=True,
                                              protect_content=bool(s["protect_content"]))
        except Exception:
            log.exception("Failed to send file in VERIFY2 for %s", code)
            await event.answer("FAILED TO SEND FILE.", alert=True); return
        if delete_at:
            now = int(time.time()); remaining = delete_at - now
            if remaining > 0:
                notice_text = f"⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(remaining)}. SAVE NOW."
                try:
                    notice_msg = await client.send_message(uid, notice_text, reply_to=file_msg.id)
                    extra = [(uid, file_msg.id), (uid, notice_msg.id)]
                    await schedule_delete(code, delete_at, extra_messages=extra)
                except Exception:
                    log.exception("Failed scheduling per-download delete for %s", code)
        return

    # Admin panel
    if data == "ADMIN_PANEL":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        s = get_settings(); v = get_verify_settings()
        text = (
            "⚙️ ADMIN PANEL\n\n"
            f"AUTO-DELETE: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
            f"DELETE AFTER: {human_seconds(s['delete_seconds'])}\n"
            f"PROTECT CONTENT: {'ON' if s['protect_content'] else 'OFF'}\n\n"
            f"VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}\n"
            f"VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}\n"
        )
        buttons = [
            [Button.inline("TOGGLE AUTO-DELETE", b"TOGGLE_AUTODEL_BTN"), Button.inline("TOGGLE PROTECT", b"TOGGLE_PROTECT_BTN")],
            [Button.inline("VERIFY SETTINGS", b"VERIFY_PANEL")],
            [Button.inline("⬅ BACK", b"BACK")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # Verify settings page (admin)
    if data == "VERIFY_PANEL":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings()
        text = (
            "🛡️ VERIFY SETTINGS\n\n"
            "HERE YOU CAN MANAGE VERIFY OPTIONS & SHORTENERS."
        )
        buttons = [
            [Button.inline("VERIFY 1", b"VERIFY1_PAGE"), Button.inline("VERIFY 2", b"VERIFY2_PAGE")],
            [Button.inline("SET VERIFY 2 TIME", b"SET_VERIFY2_TIME")],
            [Button.inline("⬅ BACK", b"ADMIN_PANEL")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # VERIFY1 admin page
    if data == "VERIFY1_PAGE":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings()
        text = (
            "VERIFY 1 SETTINGS\n\n"
            f"SHORTENER: {'SET' if v['verify1_shortener_template'] else 'NOT SET'}\n"
            f"API KEY: {'SET' if v['verify1_api_key'] else 'NOT SET'}\n"
            f"STATUS: {'ON' if v['verify1_enabled'] else 'OFF'}\n"
        )
        buttons = [
            [Button.inline("TURN VERIFY1 ON/OFF", b"TOGGLE_VERIFY1_BTN")],
            [Button.inline("SET VERIFY1 SHORTENER", b"SET_VERIFY1_SHORT"), Button.inline("SET VERIFY1 API KEY", b"SET_VERIFY1_KEY")],
            [Button.inline("⬅ BACK", b"VERIFY_PANEL")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # VERIFY2 admin page
    if data == "VERIFY2_PAGE":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings()
        text = (
            "VERIFY 2 SETTINGS\n\n"
            f"SHORTENER: {'SET' if v['verify2_shortener_template'] else 'NOT SET'}\n"
            f"API KEY: {'SET' if v['verify2_api_key'] else 'NOT SET'}\n"
            f"STATUS: {'ON' if v['verify2_enabled'] else 'OFF'}\n"
            f"DELAY: {human_seconds(v['verify2_delay_seconds'])}\n"
        )
        buttons = [
            [Button.inline("TURN VERIFY2 ON/OFF", b"TOGGLE_VERIFY2_BTN")],
            [Button.inline("SET VERIFY2 SHORTENER", b"SET_VERIFY2_SHORT"), Button.inline("SET VERIFY2 API KEY", b"SET_VERIFY2_KEY")],
            [Button.inline("⬅ BACK", b"VERIFY_PANEL")]
        ]
        await event.edit(text, buttons=buttons)
        return

    # SET VERIFY2 TIME page
    if data == "SET_VERIFY2_TIME":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        text = (
            "SET VERIFY 2 TIME\n\n"
            "SEND A DURATION EXAMPLE: `30s`, `2m`, `1h`, `1d`\n\n"
            "USE COMMAND: /setverify2time <duration>\n\n"
            "⬅ BACK"
        )
        await event.edit(text, buttons=[[Button.inline("⬅ BACK", b"VERIFY_PANEL")]])
        return

    # Toggle verify1
    if data == "TOGGLE_VERIFY1_BTN":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings(); new = not v["verify1_enabled"]; set_verify_settings(verify1_enabled=1 if new else 0)
        await event.edit(f"VERIFY1 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"VERIFY1_PAGE")]])
        return

    # Toggle verify2
    if data == "TOGGLE_VERIFY2_BTN":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        v = get_verify_settings(); new = not v["verify2_enabled"]; set_verify_settings(verify2_enabled=1 if new else 0)
        await event.edit(f"VERIFY2 IS NOW {'ON' if new else 'OFF'}.", buttons=[[Button.inline("⬅ BACK", b"VERIFY2_PAGE")]])
        return

    # Buttons to set shortener templates / keys (admin) -> trigger pending setter
    if data in ("SET_VERIFY1_SHORT","SET_VERIFY1_KEY","SET_VERIFY2_SHORT","SET_VERIFY2_KEY"):
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        await event.edit("✅ NOW SEND THE TEMPLATE (OR KEY) AS A PLAIN MESSAGE IN THIS CHAT.\n"
                         "USE `{api_key}` AND `{url}` PLACEHOLDERS.\n\n"
                         "EXAMPLE: `https://api.short.example/create?api_key={api_key}&url={url}`\n\n"
                         "SEND `CANCEL` TO ABORT.", buttons=[[Button.inline("⬅ BACK", b"VERIFY_PANEL")]])
        pending_setter[uid] = data
        return

    # Toggle auto-delete / protect
    if data == "TOGGLE_AUTODEL_BTN":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        s = get_settings(); new = not s["auto_delete_enabled"]; set_setting(auto_delete=new)
        await event.edit(f"AUTO-DELETE IS NOW {'ON' if new else 'OFF'}.")
        return

    if data == "TOGGLE_PROTECT_BTN":
        if not is_admin(uid): await event.answer("ADMIN ONLY", alert=True); return
        s = get_settings(); new = not s["protect_content"]; set_setting(protect_content=new)
        await event.edit(f"PROTECT CONTENT IS NOW {'ON' if new else 'OFF'}.")
        return

    # MY FILES handling
    if data == "MY_FILES":
        rows = list_user_files(uid, limit=30)
        if not rows:
            await event.edit("📂 YOU DON'T HAVE ANY SAVED FILES.", buttons=[[Button.inline("⬅ BACK", b"BACK")]])
            return
        await ensure_username()
        btns=[]
        for code, name, caption, created_at, delete_at in rows:
            label = (name or caption or "file")[:28]
            btns.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
        btns.append([Button.inline("⬅ BACK", b"BACK")])
        await event.edit("📁 YOUR FILES:", buttons=btns)
        return

    # Delete button (del_<code>)
    if data.startswith("del_"):
        code = data.split("_",1)[1]
        rec = get_file_record(code)
        if not rec: await event.answer("FILE NOT FOUND", alert=True); return
        _, owner_id, file_id, file_name, caption, file_type, created_at, delete_at, reply_chat_id, reply_msg_id = rec
        if uid != owner_id and not is_admin(uid): await event.answer("ONLY OWNER OR ADMIN CAN DELETE", alert=True); return
        if reply_chat_id and reply_msg_id:
            try: await client.delete_messages(reply_chat_id, [reply_msg_id])
            except Exception: pass
        delete_file_record(code)
        if code in scheduled_tasks:
            try: scheduled_tasks[code].cancel()
            except Exception: pass
            scheduled_tasks.pop(code, None)
        await event.edit(f"✅ DELETED FILE: {file_name or code}")
        return

    await event.answer("UNKNOWN ACTION", alert=True)

# -------------------------
# Pending setter dict
# -------------------------
pending_setter = {}

@client.on(events.NewMessage(incoming=True))
async def handle_pending_setters(event):
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id
    # handle admin template/key sends
    if uid in pending_setter:
        action = pending_setter.pop(uid)
        text = (event.raw_text or "").strip()
        if text.lower() == "cancel":
            await event.reply("CANCELLED.")
            return
        if action == "SET_VERIFY1_SHORT":
            set_verify_settings(verify1_shortener_template=text)
            await event.reply("✅ VERIFY1 SHORTENER TEMPLATE SAVED.")
            return
        if action == "SET_VERIFY1_KEY":
            set_verify_settings(verify1_api_key=text)
            await event.reply("✅ VERIFY1 API KEY SAVED.")
            return
        if action == "SET_VERIFY2_SHORT":
            set_verify_settings(verify2_shortener_template=text)
            await event.reply("✅ VERIFY2 SHORTENER TEMPLATE SAVED.")
            return
        if action == "SET_VERIFY2_KEY":
            set_verify_settings(verify2_api_key=text)
            await event.reply("✅ VERIFY2 API KEY SAVED.")
            return
    # else continue to file saving flow below

# -------------------------
# Admin command: setverify2time
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setverify2time\s+(.+)$"))
async def cmd_setverify2time(event):
    sender = await event.get_sender()
    if not is_admin(sender.id):
        await event.reply("❌ ONLY ADMIN CAN SET VERIFY2 TIME."); return
    arg = event.pattern_match.group(1)
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("INVALID DURATION. USE: 30s, 2m, 1h, 1d"); return
    set_verify_settings(verify2_delay_seconds=sec)
    await event.reply(f"✅ VERIFY2 DELAY SET TO {human_seconds(sec)}.")

# -------------------------
# Admin commands: setautodelete, setforward, settings, myfiles (text)
# -------------------------
@client.on(events.NewMessage(pattern=r"^/setautodelete(?:\s+(.+))?$"))
async def cmd_setautodelete(event):
    sender = await event.get_sender()
    if not is_admin(sender.id): await event.reply("❌ ONLY ADMIN CAN SET AUTO-DELETE."); return
    arg = event.pattern_match.group(1)
    if not arg:
        await event.reply("USAGE: /setautodelete <30s|2m|1h|1d|off>"); return
    if arg.strip().lower() == "off":
        set_setting(delete_seconds=0); set_setting(auto_delete=False)
        await event.reply("✅ AUTO-DELETE DISABLED."); return
    sec = parse_duration(arg)
    if sec is None:
        await event.reply("INVALID DURATION."); return
    set_setting(delete_seconds=sec); set_setting(auto_delete=True)
    await event.reply(f"✅ AUTO-DELETE ENABLED: {human_seconds(sec)}.")

@client.on(events.NewMessage(pattern=r"^/setforward\s+(\w+)$"))
async def cmd_setforward(event):
    sender = await event.get_sender()
    if not is_admin(sender.id): await event.reply("❌ ONLY ADMIN CAN CHANGE FORWARD PROTECTION."); return
    arg = event.pattern_match.group(1).lower()
    if arg not in ("on","off"):
        await event.reply("USAGE: /setforward <on|off>"); return
    set_setting(protect_content=(arg=="on"))
    await event.reply(f"✅ PROTECT CONTENT SET TO {'ON' if arg=='on' else 'OFF'}.")

@client.on(events.NewMessage(pattern=r"^/settings$"))
async def cmd_settings(event):
    sender = await event.get_sender()
    s = get_settings(); v = get_verify_settings()
    text = (
        f"⚙️ SETTINGS\n\n"
        f"• AUTO-DELETE: {'ON' if s['auto_delete_enabled'] else 'OFF'}\n"
        f"• DELETE AFTER: {human_seconds(s['delete_seconds'])}\n"
        f"• PROTECT CONTENT: {'ON' if s['protect_content'] else 'OFF'}\n\n"
        f"🔐 VERIFY1: {'ON' if v['verify1_enabled'] else 'OFF'}  SHORT: {'SET' if v['verify1_shortener_template'] else 'NOT SET'}\n"
        f"🔐 VERIFY2: {'ON' if v['verify2_enabled'] else 'OFF'}  SHORT: {'SET' if v['verify2_shortener_template'] else 'NOT SET'}  DELAY: {human_seconds(v['verify2_delay_seconds'])}\n\n"
        "USE INLINE BUTTONS BELOW TO MANAGE."
    )
    buttons = [
        [Button.inline("TOGGLE AUTO-DELETE", b"TOGGLE_AUTODEL_BTN"), Button.inline("TOGGLE PROTECT", b"TOGGLE_PROTECT_BTN")],
        [Button.inline("VERIFY SETTINGS", b"VERIFY_PANEL")],
        [Button.inline("⬅ BACK", b"BACK")]
    ]
    await event.reply(text, buttons=buttons)

# -------------------------
# My files listing (text)
# -------------------------
@client.on(events.NewMessage(pattern=r"^/myfiles$"))
async def cmd_myfiles(event):
    sender = await event.get_sender()
    rows = list_user_files(sender.id, limit=50)
    if not rows:
        await event.reply("📂 YOU HAVE NO SAVED FILES."); return
    await ensure_username()
    buttons=[]
    for code, name, caption, created_at, delete_at in rows:
        label = (name or caption or "file")[:30]
        buttons.append([Button.url(label, f"https://t.me/{BOT_USERNAME}?start=file_{code}")])
    await event.reply("📁 YOUR FILES:", buttons=buttons)

# -------------------------
# File save handler (incoming files)
# -------------------------
@client.on(events.NewMessage(incoming=True))
async def handle_incoming(event):
    # if message has file, process saving
    msg = event.message
    if not msg or not getattr(msg, "file", None):
        return

    sender = await event.get_sender()
    if not sender: return

    original_caption = (msg.message or "") if getattr(msg, "message", None) else (msg.text or "")
    sanitized_caption = sanitize_caption(original_caption)

    file_obj = msg.file
    file_id = getattr(file_obj, "id", None)
    file_id = str(file_id)
    file_name = getattr(file_obj, "name", None) or ""
    file_type = getattr(file_obj, "mime_type", None) or ""

    code = gen_code()
    created_at = int(time.time())
    s = get_settings()
    delete_at = None
    if s["auto_delete_enabled"] and s["delete_seconds"] > 0:
        delete_at = created_at + s["delete_seconds"]

    await ensure_username()
    share_link = f"https://t.me/{BOT_USERNAME}?start=file_{code}"
    btns = [
        [Button.url("📎 GET / SHARE LINK", share_link)],
        [Button.inline("📁 MY FILES", b"MY_FILES"), Button.inline("🗑 DELETE", f"del_{code}".encode())]
    ]
    delete_msg_text = f"\n\n⏳ THIS FILE WILL AUTO-DELETE IN {human_seconds(s['delete_seconds'])}." if delete_at else ""
    reply_text = (
        f"✅ FILE SAVED SUCCESSFULLY!\n\n"
        f"📄 NAME: `{file_name or 'Unnamed'}`\n"
        f"💬 CAPTION: {sanitized_caption or '—'}\n"
        f"🔗 SHARE LINK: {share_link}"
        f"{delete_msg_text}"
    )
    try:
        reply_obj = await event.reply(reply_text, buttons=btns, link_preview=False)
        reply_chat_id = reply_obj.chat_id; reply_msg_id = reply_obj.id
    except Exception:
        reply_chat_id = None; reply_msg_id = None

    add_file_record(code=code, owner_id=sender.id, file_id=file_id, file_name=file_name, caption=sanitized_caption, file_type=file_type, created_at=created_at, delete_at=delete_at, reply_chat_id=reply_chat_id, reply_msg_id=reply_msg_id)

    if delete_at:
        try: await schedule_delete(code, delete_at)
        except Exception: log.exception("Failed scheduling delete for %s", code)

    log.info("Saved file code=%s owner=%s file_id=%s", code, sender.id, file_id)

# -------------------------
# Startup tasks & FastAPI
# -------------------------
@app.get("/")
async def health():
    return {"status":"running"}

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

async def startup_tasks():
    await ensure_username()
    await reschedule_all()

# -------------------------
# Main
# -------------------------
def main():
    init_db()
    threading.Thread(target=run_fastapi, daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(startup_tasks())
    log.info("Starting Telegram client...")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
