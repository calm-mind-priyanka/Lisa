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
        "protect": False, "auto_delete": False, "del_time": 60,
        "shortner": "OFF ❌", "short_url": None,
        "fsub": "OFF ❌", "channels": [], 
        "token_verify": "OFF ❌", "caption": "✨ **{filename}**"
    },
    "files": {}, 
    "states": {} 
}

# --- [ 3. UI GENERATORS ] ---

def get_settings_btns():
    c = DB["config"]
    # Grouping buttons to look "Smooth" and "Small" just like your SS
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

# --- [ 4. HANDLERS ] ---

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id
    args = event.text.split()
    
    if len(args) > 1:
        fid = args[1]
        if fid in DB["files"]:
            file = DB["files"][fid]
            return await client.send_file(uid, file['media'], noscript=DB["config"]["protect"])

    user = await event.get_sender()
    name = user.first_name.upper() if user.first_name else "USER"
    
    text = (
        f"**HEY {name}** 👋,\n\n"
        "**I AM A PERMENANT FILE STORE BOT WITH CLONE AND MANY AMAZING ADVANCE FEATURE AND USERS CAN ACCESS STORED MESSAGES BY USING A SHAREABLE LINK GIVEN BY ME**\n\n"
        "**TO KNOW MORE CLICK HELP BUTTON.**"
    )
    
    # Put HELP and ABOUT on the same row to make it "Smooth"
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

    if data == b"home":
        await start(event)
    
    elif data == b"settings" and uid == ADMIN_ID:
        await event.edit("**HERE IS THE SETTINGS MENU**\n\n**CUSTOMIZE YOUR SETTINGS AS PER YOUR NEED**", buttons=get_settings_btns())

    elif data == b"short_menu":
        # FIXED: Removed the backslash from the f-string curly braces
        url_text = f"URL: `{c['short_url']}`" if c['short_url'] else "YOU DIDN'T ADD ANY SHORTLINK"
        text = (
            "**HERE YOU CAN MANAGE YOUR SHORTNER, THE GENERATED LINK WILL CONVERT INTO YOUR SHORTLINK**\n\n"
            f"**SHORTLINK - {c['shortner']}**\n\n"
            f"**{url_text}**"
        )
        btns = [
            [Button.inline("SET SHORTLINK", b"set_sl"), Button.inline("DELETE SHORTLINK", b"del_sl")],
            [Button.inline(f"{'OFF' if 'ON' in c['shortner'] else 'ON'} SHORTLINK", b"toggle_sl")],
            [Button.inline("⬅️ BACK", b"settings")]
        ]
        await event.edit(text, buttons=btns)

    elif data == b"set_sl":
        DB["states"][uid] = "waiting_url"
        await event.edit("**SEND ME A SHORTLINK URL...**\n\n**FORMAT :**\n\n`https://vjlink.online` - ❌\n`vjlink.online` - ✅\n\n**/cancel - CANCEL THIS PROCESS.**")

    elif data == b"toggle_sl":
        c['shortner'] = "ON ✅" if "OFF" in c['shortner'] else "OFF ❌"
        await cb_handler(event)

    elif data == b"toggle_prot":
        c['protect'] = not c['protect']
        await event.edit(buttons=get_settings_btns())

    elif data in [b"help", b"about"]:
        await event.answer("Help/About section is coming soon!", alert=True)

# --- [ 5. MESSAGE MANAGER ] ---

@client.on(events.NewMessage)
async def manager(event):
    uid = event.chat_id
    if event.text == "/cancel" and uid in DB["states"]:
        del DB["states"][uid]
        return await event.respond("**CANCELLED THIS PROCESS...**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

    if uid in DB["states"] and DB["states"][uid] == "waiting_url":
        DB["config"]["short_url"] = event.text
        del DB["states"][uid]
        await event.respond(f"✅ **SHORTLINK URL UPDATED!**", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])
        return

    if uid == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        bot = await client.get_me()
        await event.reply(f"**✅ FILE STORED!**\n\nLink: `t.me/{bot.username}?start={fid}`")

print("Bot deployed successfully and running smoothly!")
client.run_until_disconnected()
