import os, asyncio, uuid
from telethon import TelegramClient, events, Button

# --- CONFIGURATION ---
API_ID = 1234567  
API_HASH = "your_api_hash"
BOT_TOKEN = "your_bot_token"
ADMIN_ID = 12345678 

client = TelegramClient('VJ_FileStore', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- DATABASE ---
DB = {
    "config": {
        "protect": False, "auto_delete": False, "del_time": 60,
        "shortner": "OFF ❌", "short_url": None, "short_api": None,
        "caption": "✨ **{filename}**", "token_verify": "OFF ❌",
        "fsub": "OFF ❌"
    },
    "files": {}, 
    "states": {} 
}

# --- UI GENERATORS ---
def settings_btns():
    c = DB["config"]
    return [
        [Button.url("🤖 MY CLONE BOT", "https://t.me/botfather")],
        [Button.inline("💸 PREMIUM PLAN", b"premium")],
        [Button.inline("🔗 LINK SHORTNER", b"short_menu")],
        [Button.inline(f"⏰ TOKEN VERIFICATION [{c['token_verify']}]", b"token_menu")],
        [Button.inline("🍿 CUSTOM CAPTION", b"cap_menu")],
        [Button.inline(f"📢 CUSTOM FORCE SUBSCRIBE [{c['fsub']}]", b"fsub_menu")],
        [Button.inline("🔘 CUSTOM BUTTON", b"btn_menu")],
        [Button.inline(f"♻️ AUTO DELETE [{'✅' if c['auto_delete'] else '❌'}]", b"toggle_del")],
        [Button.inline(f"🔒 PROTECT CONTENT [{'✅' if c['protect'] else '❌'}]", b"toggle_prot")],
        [Button.inline("⬅️ BACK", b"home")]
    ]

# --- CALLBACK HANDLER ---
@client.on(events.CallbackQuery)
async def cb_handler(event):
    data = event.data
    uid = event.sender_id
    c = DB["config"]

    if data == b"settings":
        await event.edit("**HERE IS THE SETTINGS MENU**", buttons=settings_btns())

    # --- SHORTENER LOGIC ---
    elif data == b"short_menu":
        text = f"**MANAGE SHORTNER**\n\n**SHORTLINK - {c['shortner']}**\n{'URL: ' + c['short_url'] if c['short_url'] else 'No URL set.'}"
        btns = [[Button.inline("SET SHORTLINK", b"set_sl"), Button.inline("DELETE", b"del_sl")], [Button.inline("⬅️ BACK", b"settings")]]
        await event.edit(text, buttons=btns)

    elif data == b"set_sl":
        DB["states"][uid] = "waiting_url"
        await event.edit("**SEND URL (vjlink.online format)...**\n\n**/cancel TO STOP**")

    # --- CAPTION LOGIC ---
    elif data == b"cap_menu":
        DB["states"][uid] = "waiting_caption"
        await event.edit(f"**CURRENT CAPTION:**\n`{c['caption']}`\n\n**SEND NEW CAPTION TEXT...**")

    # --- TOGGLE LOGIC (ONE-CLICK) ---
    elif data == b"toggle_prot":
        c['protect'] = not c['protect']
        await event.edit(buttons=settings_btns())

    elif data == b"fsub_menu":
        c['fsub'] = "ON ✅" if "OFF" in c['fsub'] else "OFF ❌"
        await event.edit(buttons=settings_btns())

    elif data == b"home":
        user = await event.get_sender()
        await event.edit(f"**HEY {user.first_name}** 👋", buttons=[[Button.inline("⚙️ SETTINGS", b"settings")]])

# --- MESSAGE HANDLER ---
@client.on(events.NewMessage)
async def handle_messages(event):
    uid = event.chat_id
    if uid in DB["states"]:
        if event.text == "/cancel": #
            del DB["states"][uid]
            await event.respond("**PROCESS CANCELLED**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])
            return
        
        # Logic for Shortener URL
        if DB["states"][uid] == "waiting_url":
            DB["config"]["short_url"] = event.text
            del DB["states"][uid]
            await event.respond(f"✅ URL SET: `{event.text}`", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])
        
        # Logic for Custom Caption
        elif DB["states"][uid] == "waiting_caption":
            DB["config"]["caption"] = event.text
            del DB["states"][uid]
            await event.respond("✅ CAPTION UPDATED", buttons=[[Button.inline("⬅️ BACK", b"settings")]])
        return

    # Start command logic
    if event.text.startswith('/start'):
        await event.respond("**WELCOME TO VJ FILE STORE**", buttons=[[Button.inline("⚙️ SETTINGS", b"settings")]])

    # Admin storing file
    if uid == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        bot = await client.get_me()
        await event.reply(f"**FILE STORED!**\n\n`t.me/{bot.username}?start={fid}`")

client.run_until_disconnected()
