import os, asyncio, uuid
from telethon import TelegramClient, events, Button

# --- CONFIGURATION ---
API_ID = 1234567  # Your API ID
API_HASH = "your_api_hash"
BOT_TOKEN = "your_bot_token"
ADMIN_ID = 12345678 # Your Telegram ID

client = TelegramClient('VJ_FileStore', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- IN-MEMORY DATABASE (DEMO MODE) ---
DB = {
    "config": {
        "protect": False, "auto_delete": False, "del_time": 60,
        "shortner": "OFF ❌", "short_url": None, "short_api": None,
        "caption": "✨ **{filename}**", "token_verify": "OFF ❌"
    },
    "files": {}, # Stores file_id -> media_obj
    "states": {} # Tracks user input state
}

# --- UI GENERATORS ---
def main_menu_btns():
    return [
        [Button.inline("🤠 HELP", b"help"), Button.inline("📁 ABOUT", b"about")],
        [Button.inline("⚙️ SETTINGS", b"settings")]
    ]

def settings_btns():
    c = DB["config"]
    return [
        [Button.url("🤖 MY CLONE BOT", "https://t.me/botfather")],
        [Button.inline("💸 PREMIUM PLAN", b"premium")],
        [Button.inline("🔗 LINK SHORTNER", b"short_menu")],
        [Button.inline(f"⏰ TOKEN VERIFICATION [{c['token_verify']}]", b"token_menu")],
        [Button.inline("🍿 CUSTOM CAPTION", b"cap_menu")],
        [Button.inline("📢 CUSTOM FORCE SUBSCRIBE", b"fsub_menu")],
        [Button.inline("🔘 CUSTOM BUTTON", b"btn_menu")],
        [Button.inline(f"♻️ AUTO DELETE [{'✅' if c['auto_delete'] else '❌'}]", b"toggle_del")],
        [Button.inline(f"🔒 PROTECT CONTENT [{'✅' if c['protect'] else '❌'}]", b"toggle_prot")],
        [Button.inline("⬅️ BACK", b"home")]
    ]

# --- HANDLERS ---

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    args = event.text.split()
    if len(args) > 1: # File Retrieval Logic
        fid = args[1]
        if fid in DB["files"]:
            file = DB["files"][fid]
            sent = await client.send_file(event.chat_id, file['media'], caption=DB["config"]["caption"].format(filename="File"), noscript=DB["config"]["protect"])
            if DB["config"]["auto_delete"]:
                await asyncio.sleep(DB["config"]["del_time"])
                await sent.delete()
        return

    user = await event.get_sender()
    name = user.first_name.upper() if user.first_name else "USER"
    text = f"**HEY {name}** 👋,\n\n**I AM A PERMENANT FILE STORE BOT WITH CLONE AND MANY AMAZING ADVANCE FEATURE...**"
    await event.respond(text, buttons=main_menu_btns())

@client.on(events.CallbackQuery)
async def cb_handler(event):
    data = event.data
    c = DB["config"]

    if data == b"settings":
        await event.edit("**HERE IS THE SETTINGS MENU\n\nCUSTOMIZE YOUR SETTINGS AS PER YOUR NEED**", buttons=settings_btns())

    elif data == b"short_menu":
        text = (f"**HERE YOU CAN MANAGE YOUR SHORTNER...**\n\n**SHORTLINK - {c['shortner']}**\n\n"
                f"{'YOU DIDN\'T ADDED ANY SHORTLINK' if not c['short_url'] else f'URL: {c['short_url']}'}")
        btns = [[Button.inline("SET SHORTLINK", b"set_sl"), Button.inline("DELETE SHORTLINK", b"del_sl")],
                [Button.inline(f"{'ON' if 'OFF' in c['shortner'] else 'OFF'} SHORTLINK", b"toggle_sl")],
                [Button.inline("⬅️ BACK", b"settings")]]
        await event.edit(text, buttons=btns)

    elif data == b"set_sl":
        DB["states"][event.chat_id] = "waiting_url"
        await event.edit("**SEND ME A SHORTLINK URL...**\n\n**FORMAT :**\nvjlink.online - ✅\n\n**/cancel - CANCEL THIS PROCESS.**")

    elif data == b"toggle_sl":
        if not c['short_url']: return await event.answer("Set URL first!", alert=True)
        c['shortner'] = "ON ✅" if "OFF" in c['shortner'] else "OFF ❌"
        await cb_handler(event)

    elif data == b"toggle_prot":
        c['protect'] = not c['protect']
        await event.edit(buttons=settings_btns())

    elif data == b"home":
        await start(event)

@client.on(events.NewMessage)
async def input_handler(event):
    uid = event.chat_id
    if uid in DB["states"]:
        if event.text == "/cancel":
            del DB["states"][uid]
            await event.respond("**CANCELLED THIS PROCESS...**", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])
            return
        
        if DB["states"][uid] == "waiting_url":
            if "://" in event.text:
                await event.reply("❌ Invalid Format! Send like: `vjlink.online`")
                return
            DB["config"]["short_url"] = event.text
            del DB["states"][uid]
            await event.respond(f"✅ URL Set: `{event.text}`", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])

    # Admin File Storage Logic
    if event.sender_id == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        me = await client.get_me()
        await event.reply(f"**✅ File Stored!**\n\nLink: `t.me/{me.username}?start={fid}`")

print("Bot is Running...")
client.run_until_disconnected()    try:
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
