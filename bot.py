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
        "fsub": "OFF ❌", "channels": [], # Store as [{"id": -100..., "link": "https://t.me/..."}]
        "token_verify": "OFF ❌", "caption": "✨ **{filename}**"
    },
    "files": {}, 
    "states": {} 
}

# --- [ 3. UI GENERATORS ] ---

def settings_panel():
    """Generates the full Settings Menu as seen in screenshot"""
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

async def check_fsub(user_id):
    """Checks if user joined all required channels."""
    c = DB["config"]
    if c["fsub"] == "OFF ❌" or not c["channels"]: return []
    unjoined = []
    for ch in c["channels"]:
        try:
            await client(functions.channels.GetParticipantRequest(int(ch['id']), user_id))
        except: unjoined.append(ch)
    return unjoined

# --- [ 4. MAIN HANDLERS ] ---

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id
    args = event.text.split()
    
    # User retrieving a file
    if len(args) > 1:
        unjoined = await check_fsub(uid)
        if unjoined:
            btns = [[Button.url("📢 JOIN CHANNEL", ch['link'])] for ch in unjoined]
            btns.append([Button.url("🔄 TRY AGAIN", f"https://t.me/bot?start={args[1]}")])
            return await event.respond("❌ **JOIN ALL CHANNELS TO ACCESS FILE!**", buttons=btns)
        
        fid = args[1]
        if fid in DB["files"]:
            file = DB["files"][fid]
            return await client.send_file(uid, file['media'], noscript=DB["config"]["protect"])
        return await event.respond("❌ File not found.")

    # Home Welcome Message
    user = await event.get_sender()
    name = user.first_name.upper() if user.first_name else "USER"
    text = (
        f"**HEY {name}** 👋,\n\n"
        "**I AM A PERMENANT FILE STORE BOT WITH CLONE AND MANY AMAZING ADVANCE FEATURE AND USERS CAN ACCESS STORED MESSAGES BY USING A SHAREABLE LINK GIVEN BY ME**\n\n"
        "**TO KNOW MORE CLICK HELP BUTTON.**"
    )
    btns = [[Button.inline("🤠 HELP", b"help"), Button.inline("📜 ABOUT", b"about")]]
    if uid == ADMIN_ID: btns.insert(0, [Button.inline("⚙️ SETTINGS", b"settings")])
    await event.respond(text, buttons=btns)

@client.on(events.CallbackQuery)
async def cb_handler(event):
    data = event.data
    uid = event.sender_id
    c = DB["config"]

    if data == b"home": await start(event)
    
    # 1. Main Settings Menu
    elif data == b"settings":
        if uid != ADMIN_ID: return
        await event.edit("**HERE IS THE SETTINGS MENU**", buttons=settings_panel())

    # 2. Shortener Sub-Menu
    elif data == b"short_menu":
        text = f"**SHORTLINK - {c['shortner']}**\n\nURL: `{c['short_url'] or 'Not Set'}`"
        btns = [[Button.inline("SET SHORTLINK", b"set_sl"), Button.inline("DELETE", b"del_sl")],
                [Button.inline(f"{'OFF' if 'ON' in c['shortner'] else 'ON'} SHORTLINK", b"toggle_sl")],
                [Button.inline("⬅️ BACK", b"settings")]]
        await event.edit(text, buttons=btns)

    elif data == b"set_sl":
        DB["states"][uid] = "waiting_url" #
        await event.edit("**SEND ME A SHORTLINK URL...**\n\nExample: `vjlink.online`\n\n**/cancel**")

    # 3. Multi-FSub Menu
    elif data == b"fsub_menu":
        text = f"**MULTI FSUB SETTINGS**\n\nChannels: {len(c['channels'])}\nStatus: {c['fsub']}"
        btns = [[Button.inline("➕ ADD CHANNEL", b"add_fsub"), Button.inline("🗑️ CLEAR", b"clear_fsub")],
                [Button.inline(f"{'OFF' if 'ON' in c['fsub'] else 'ON'} FSUB", b"toggle_fsub")],
                [Button.inline("⬅️ BACK", b"settings")]]
        await event.edit(text, buttons=btns)

    elif data == b"add_fsub":
        DB["states"][uid] = "waiting_fsub"
        await event.edit("**SEND ID & LINK SEPARATED BY ':'**\nExample: `-100123:https://t.me/link`")

    elif data == b"toggle_fsub":
        c['fsub'] = "ON ✅" if "OFF" in c['fsub'] else "OFF ❌"
        await cb_handler(event)

    elif data == b"toggle_prot":
        c['protect'] = not c['protect']
        await event.edit(buttons=settings_panel())

# --- [ 5. MESSAGE MANAGER ] ---

@client.on(events.NewMessage)
async def manager(event):
    uid = event.chat_id
    text = event.text

    # Handle /cancel
    if text == "/cancel" and uid in DB["states"]:
        del DB["states"][uid]
        return await event.respond("**CANCELLED THIS PROCESS...**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

    # Handle Input States
    if uid in DB["states"]:
        state = DB["states"][uid]
        if state == "waiting_url":
            DB["config"]["short_url"] = text
            del DB["states"][uid]
            await event.respond("✅ URL UPDATED!", buttons=[[Button.inline("⬅️ BACK", b"short_menu")]])
        
        elif state == "waiting_fsub":
            try:
                cid, clink = text.split(':')
                DB["config"]["channels"].append({"id": cid, "link": clink})
                del DB["states"][uid]
                await event.respond(f"✅ Channel Added!", buttons=[[Button.inline("⬅️ BACK", b"fsub_menu")]])
            except: await event.respond("❌ Use Format `ID:LINK`")
        return

    # Admin File Storage Logic
    if uid == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        me = await client.get_me()
        await event.reply(f"**✅ FILE STORED!**\n\nLink: `t.me/{me.username}?start={fid}`")

client.run_until_disconnected()
