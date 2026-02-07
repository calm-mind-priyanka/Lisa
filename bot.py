import os, asyncio, uuid
from telethon import TelegramClient, events, Button, functions, errors

# --- CONFIGURATION ---
API_ID = 24222039  
API_HASH = "6dd2dc70434b2f577f76a2e993135662"
BOT_TOKEN = "8430798122:AAHOcHZn2-w7Wq2OU0pUVRAiN47Y4e7vnLE"
ADMIN_ID = 6046055058 

client = TelegramClient('VJ_FileStore', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- DATABASE ---
DB = {
    "config": {
        "protect": False, "auto_delete": False, "del_time": 60,
        "shortner": "OFF ❌", "short_url": None, 
        "caption": "✨ **{filename}**", 
        "fsub": "OFF ❌",
        "fsub_channels": [] # List of Channel IDs
    },
    "files": {}, 
    "states": {} 
}

# --- HELPERS ---
async def get_unsubscribed_channels(user_id):
    """Returns a list of channel IDs the user hasn't joined yet."""
    c = DB["config"]
    if c["fsub"] == "OFF ❌" or not c["fsub_channels"]: 
        return []
    
    unsubscribed = []
    for channel_id in c["fsub_channels"]:
        try:
            await client(functions.channels.GetParticipantRequest(int(channel_id), user_id))
        except (errors.UserNotParticipantError, ValueError):
            unsubscribed.append(channel_id)
        except Exception:
            continue 
    return unsubscribed

def settings_btns():
    c = DB["config"]
    return [
        [Button.url("🤖 MY CLONE BOT", "https://t.me/botfather")],
        [Button.inline("🔗 LINK SHORTNER", b"short_menu")],
        [Button.inline(f"📢 MULTI FSUB [{c['fsub']}]", b"fsub_config")],
        [Button.inline(f"🔒 PROTECT CONTENT [{'✅' if c['protect'] else '❌'}]", b"toggle_prot")],
        [Button.inline("⬅️ BACK", b"home")]
    ]

# --- HANDLERS ---

@client.on(events.CallbackQuery)
async def cb_handler(event):
    data = event.data
    uid = event.sender_id
    c = DB["config"]

    if uid != ADMIN_ID: return

    if data == b"settings":
        await event.edit("**SETTINGS MENU**", buttons=settings_btns())

    # --- MULTI FSUB CONFIG MENU ---
    elif data == b"fsub_config":
        channels_str = "\n".join([f"• `{id}`" for id in c['fsub_channels']]) if c['fsub_channels'] else "None"
        text = (
            "**📢 MULTI FORCE SUBSCRIBE SETTINGS**\n\n"
            f"**STATUS:** {c['fsub']}\n"
            f"**CHANNELS:**\n{channels_str}\n\n"
            "Bot must be Admin in all these channels!"
        )
        btns = [
            [Button.inline("➕ ADD CHANNEL ID", b"add_fsub"), Button.inline("🗑️ CLEAR ALL", b"clear_fsub")],
            [Button.inline(f"{'ON' if 'OFF' in c['fsub'] else 'OFF'} FSUB", b"toggle_fsub")],
            [Button.inline("⬅️ BACK", b"settings")]
        ]
        await event.edit(text, buttons=btns)

    elif data == b"add_fsub":
        DB["states"][uid] = "waiting_fsub"
        await event.edit("**SEND THE CHANNEL ID TO ADD...**\n\nExample: `-100123456789`\n\n**/cancel - CANCEL**")

    elif data == b"clear_fsub":
        c['fsub_channels'] = []
        c['fsub'] = "OFF ❌"
        await event.answer("All channels removed.", alert=True)
        await cb_handler(event)

    elif data == b"toggle_fsub":
        if not c['fsub_channels']: return await event.answer("❌ Add at least one channel first!", alert=True)
        c['fsub'] = "ON ✅" if "OFF" in c['fsub'] else "OFF ❌"
        await cb_handler(event)

# --- MESSAGE HANDLER ---

@client.on(events.NewMessage)
async def manager(event):
    uid = event.chat_id
    text = event.text

    if uid in DB["states"]:
        if text == "/cancel":
            del DB["states"][uid]
            return await event.respond("**PROCESS CANCELLED**", buttons=[[Button.inline("⬅️ BACK", b"settings")]])

        if DB["states"][uid] == "waiting_fsub":
            DB["config"]["fsub_channels"].append(text)
            del DB["states"][uid]
            await event.respond(f"✅ **Channel added!** Total: {len(DB['config']['fsub_channels'])}", buttons=[[Button.inline("⬅️ BACK", b"fsub_config")]])
        return

    if text.startswith('/start'):
        args = text.split()
        if len(args) > 1:
            # CHECK MULTIPLE CHANNELS
            unsubscribed = await get_unsubscribed_channels(uid)
            if unsubscribed:
                # Create buttons for each channel they haven't joined
                btns = []
                for i, ch_id in enumerate(unsubscribed, 1):
                    # Note: Using a raw link logic; you might need to adjust link format
                    btns.append([Button.url(f"📢 JOIN CHANNEL {i}", f"https://t.me/c/{str(ch_id)[4:]}")])
                btns.append([Button.url("🔄 TRY AGAIN", f"https://t.me/bot?start={args[1]}")])
                
                return await event.respond("❌ **YOU MUST JOIN ALL CHANNELS BELOW:**", buttons=btns)
            
            fid = args[1]
            if fid in DB["files"]:
                file = DB["files"][fid]
                await client.send_file(uid, file['media'], noscript=DB["config"]["protect"])
            return
        await event.respond("**I AM LIVE!**", buttons=settings_btns() if uid == ADMIN_ID else None)

    # Admin Link Generation
    if uid == ADMIN_ID and event.file:
        fid = str(uuid.uuid4())[:8]
        DB["files"][fid] = {"media": event.media}
        me = await client.get_me()
        await event.reply(f"**✅ LINK:** `t.me/{me.username}?start={fid}`")

client.run_until_disconnected()
