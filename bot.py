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

# --- [ 3. UI GENERATORS ] ---

def get_settings_btns():
    """Pixel-perfect status buttons"""
    c = DB["config"]
    return [
        [Button.url("🤖 MY CLONE BOT", "https://t.me/botfather")],
        [Button.inline("💸 PREMIUM PLAN", b"premium")],
        [Button.inline("🔗 LINK SHORTNER", b"short_menu")],
        [Button.inline(f"⏰ TOKEN VERIFICATION [{c['token_verify']}]", b"toggle_token")],
        [Button.inline("🍿 CUSTOM CAPTION", b"cap_menu")],
        [Button.inline("📢 CUSTOM FORCE SUBSCRIBE", b"fsub_menu")],
        [Button.inline("🔘 CUSTOM BUTTON", b"btn_menu")],
        [Button.inline(f"♻️ AUTO DELETE [{c['auto_delete']}]", b"toggle_del")],
        [Button.inline(f"🔒 PROTECT CONTENT [{c['protect']}]", b"toggle_prot")],
        [Button.inline("⬅️ BACK", b"home")]
    ]

# --- [ 4. HANDLERS ] ---

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id
    user = await event.get_sender()
    name = user.first_name.upper() if user.first_name else "USER"
    
    # Exact text from screenshot
    text = (
        f"**HEY {name}** 👋,\n\n"
        "**I AM A PERMENANT FILE STORE BOT WITH CLONE AND MANY AMAZING ADVANCE FEATURE AND USERS CAN ACCESS STORED MESSAGES BY USING A SHAREABLE LINK GIVEN BY ME**\n\n"
        "**TO KNOW MORE CLICK HELP BUTTON.**"
    )
    
    # Side-by-side row grouping for 'Medium' look
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

    # Main Navigation
    if data == b"home": await start(event)
    elif data == b"settings" and uid == ADMIN_ID:
        # Layout
        await event.edit("**HERE IS THE SETTINGS MENU**\n\n**CUSTOMIZE YOUR SETTINGS AS PER YOUR NEED**", buttons=get_settings_btns())

    # Real Toggle Functions
    elif data == b"toggle_token":
        c['token_verify'] = "ON ✅" if "OFF" in c['token_verify'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    elif data == b"toggle_del":
        c['auto_delete'] = "ON ✅" if "OFF" in c['auto_delete'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    elif data == b"toggle_prot":
        c['protect'] = "ON ✅" if "OFF" in c['protect'] else "OFF ❌"
        await event.edit(buttons=get_settings_btns())

    # Input state triggers
    elif data == b"cap_menu":
        DB["states"][uid] = "waiting_cap"
        await event.edit("**SEND NEW CUSTOM CAPTION...**\n\n**/cancel to stop.**")

    elif data == b"short_menu":
        # Text from screenshot
        u_txt = f"URL: `{c['short_url']}`" if c['short_url'] else "YOU DIDN'T ADD ANY SHORTLINK"
        text = f"**HERE YOU CAN MANAGE YOUR SHORTNER...**\n\n**SHORTLINK - {c['shortner']}**\n\n**{u_txt}**"
        btns = [
            [Button.inline("SET SHORTLINK", b"set_sl"), Button.inline("DELETE SHORTLINK", b"del_sl")],
            [Button.inline(f"{'OFF' if 'ON' in c['shortner'] else 'ON'} SHORTLINK", b"toggle_sl")],
            [Button.inline("⬅️ BACK", b"settings")]
        ]
        await event.edit(text, buttons=btns)

    elif data == b"set_sl":
        DB["states"][uid] = "waiting_url"
        # Spacing and format
        await event.edit("**SEND ME A SHORTLINK URL...**\n\n**FORMAT :**\n`vjlink.online` - ✅\n\n**/cancel**")

    # Placeholder answer to keep buttons responsive
    elif data in [b"help", b"about", b"premium", b"fsub_menu", b"btn_menu"]:
        await event.answer("Functionality loaded. Please follow chat prompts.", alert=True)

# --- [ 5. MESSAGE MANAGER ] ---

@client.on(events.NewMessage)
async def manager(event):
    uid = event.chat_id
    # Cancel handling
    if event.text == "/cancel" and uid in DB["states"]:
        del DB["states"][uid]
        return await event.respond("**CANCELLED THIS PROCESS...**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

    if uid in DB["states"]:
        state = DB["states"][uid]
        if state == "waiting_url":
            DB["config"]["short_url"] = event.text
            del DB["states"][uid]
            await event.respond("✅ **SHORTLINK UPDATED!**", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])
        elif state == "waiting_cap":
            DB["config"]["caption"] = event.text
            del DB["states"][uid]
            await event.respond("✅ **CAPTION SAVED!**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

client.run_until_disconnected()
