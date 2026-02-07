import os, asyncio, uuid
from telethon import TelegramClient, events, Button, functions, errors

# --- [ 1. CONFIGURATION ] ---
API_ID = 24222039  
API_HASH = "6dd2dc70434b2f577f76a2e993135662"
BOT_TOKEN = "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE"
ADMIN_ID = 6046055058 

client = TelegramClient('VJ_FileStore', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- [ 2. DATABASE ] ---
DB = {
    "config": {
        "protect": "OFF ❌", "auto_delete": "OFF ❌", 
        "shortner": "OFF ❌", "short_url": None,
        "fsub": "OFF ❌", "channels": [], 
        "token_verify": "OFF ❌", "caption": "✨ **{filename}**"
    },
    "files": {}, "states": {} 
}

# --- [ 3. UI GENERATOR ] ---

def get_settings_btns():
    """Groups buttons side-by-side for the 'Small/Medium' look"""
    c = DB["config"]
    return [
        [Button.url("🤖 MY CLONE BOT", "https://t.me/botfather")],
        # Grouped side-by-side to stay small
        [Button.inline("💸 PREMIUM PLAN", b"premium"), Button.inline("🔗 LINK SHORTNER", b"short_menu")],
        [Button.inline(f"⏰ TOKEN VERIFICATION [{c['token_verify']}]", b"toggle_token")],
        [Button.inline("🍿 CUSTOM CAPTION", b"cap_menu"), Button.inline("📢 FSUB", b"fsub_menu")],
        [Button.inline("🔘 CUSTOM BUTTON", b"btn_menu")],
        # Grouped side-by-side
        [Button.inline(f"♻️ DEL [{c['auto_delete']}]", b"toggle_del"), Button.inline(f"🔒 PROT [{c['protect']}]", b"toggle_prot")],
        [Button.inline("⬅️ BACK", b"home")]
    ]

# --- [ 4. HANDLERS ] ---

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id
    user = await event.get_sender()
    name = user.first_name.upper() if user.first_name else "USER"
    
    # Matching screenshot text
    text = f"**HEY {name}** 👋,\n\n**I AM A PERMENANT FILE STORE BOT...**"
    
    # SMALL side-by-side buttons
    btns = [
        [Button.inline("🤠 HELP", b"help"), Button.inline("📜 ABOUT", b"about")],
        [Button.url("🤖 CREATE OWN CLONE 🤖", "https://t.me/botfather")]
    ]
    if uid == ADMIN_ID:
        btns.insert(0, [Button.inline("⚙️ SETTINGS", b"settings")])
    await event.respond(text, buttons=btns)

@client.on(events.CallbackQuery)
async def cb_handler(event):
    data = event.data
    uid = event.sender_id
    c = DB["config"]

    # --- REAL CALLBACK FUNCTIONS ---
    if data == b"settings":
        await event.edit("**HERE IS THE SETTINGS MENU**", buttons=get_settings_btns())

    elif data == b"toggle_token":
        c['token_verify'] = "ON ✅" if "OFF" in c['token_verify'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    elif data == b"toggle_del":
        c['auto_delete'] = "ON ✅" if "OFF" in c['auto_delete'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    elif data == b"toggle_prot":
        c['protect'] = "ON ✅" if "OFF" in c['protect'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    elif data == b"home":
        await start(event)

    # State triggers for inputs
    elif data == b"cap_menu":
        DB["states"][uid] = "waiting_cap"
        await event.edit("**SEND YOUR NEW CUSTOM CAPTION...**")

    # Alert for unfinished features
    elif data in [b"premium", b"short_menu", b"fsub_menu", b"btn_menu", b"help", b"about"]:
        await event.answer("Feature is being optimized!", alert=True)

# --- [ 5. FILE STORAGE & STATES ] ---

@client.on(events.NewMessage)
async def manager(event):
    uid = event.sender_id
    
    # Cancel Process
    if event.text == "/cancel":
        DB["states"].pop(uid, None)
        return await event.respond("**CANCELLED.**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

    # Handling Input States
    if uid in DB["states"]:
        if DB["states"][uid] == "waiting_cap":
            DB["config"]["caption"] = event.text
            DB["states"].pop(uid)
            return await event.respond("✅ **CAPTION UPDATED!**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

    # ACTUAL FILE STORE FUNCTION
    if uid == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        bot = await client.get_me()
        await event.reply(f"**✅ FILE STORED!**\n\n`t.me/{bot.username}?start={fid}`")

client.run_until_disconnected()
client.run_until_disconnected()
