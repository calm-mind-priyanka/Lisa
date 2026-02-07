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
client.run_until_disconnected()
