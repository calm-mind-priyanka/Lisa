import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN
from suno_client import generate_song
from audio_utils import convert_to_mp3, create_preview, save_temp_file
from hook_generator import generate_hooks

user_state = {}
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# -------------------- Keyboards --------------------
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎵 Create Song", callback_data="create_song"),
         InlineKeyboardButton("🔁 Hook Generator", callback_data="hook_gen")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard():
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back")]]
    return InlineKeyboardMarkup(keyboard)

# -------------------- Handlers --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state[update.effective_user.id] = {"step": 0, "lyrics": "", "track": None, "style": "pop"}
    await update.message.reply_text(
        "Welcome to 🎵 Ultimate Music Bot!\nStep by step, create your own songs.",
        reply_markup=main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    state = user_state.get(user_id, {"step":0})

    if data == "create_song":
        state["step"] = 1
        await query.message.reply_text(
            "Step 1: Upload your instrumental track (mp3/wav) or type /skip.",
            reply_markup=back_keyboard()
        )

    elif data == "hook_gen":
        keyboard = [
            [InlineKeyboardButton("Pop 10000 hooks", callback_data="hooks_pop"),
             InlineKeyboardButton("Romantic 10000 hooks", callback_data="hooks_romantic")],
            [InlineKeyboardButton("EDM 10000 hooks", callback_data="hooks_edm")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ]
        await query.message.reply_text("Select style and amount of hooks:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("hooks_"):
        style = data.replace("hooks_", "")
        hooks = generate_hooks(style=style, count=10000)
        preview_hooks = "\n".join(hooks[:20])
        await query.message.reply_text(
            f"Top hooks for {style} (first 20 of 10000):\n{preview_hooks}\nUse these in your lyrics!",
            reply_markup=back_keyboard()
        )

    elif data == "settings":
        await query.message.reply_text("Settings not implemented yet.", reply_markup=back_keyboard())

    elif data.startswith("style_"):
        style = data.replace("style_", "")
        state["style"] = style
        state["step"] = 4
        user_state[user_id] = state
        await query.message.reply_text(f"Selected style: {style}\nGenerating your song...", reply_markup=back_keyboard())
        await generate_and_send_song(update, context, user_id)

    elif data == "back":
        await start(update, context)

# -------------------- Generate Song --------------------
async def generate_and_send_song(update, context, user_id):
    state = user_state[user_id]
    lyrics = state.get("lyrics", "")
    track = state.get("track")

    try:
        song_bytes = generate_song(lyrics, style=state["style"], track_file_path=track)
        file_path = save_temp_file(f"{user_id}_song.mp3")
        with open(file_path, "wb") as f:
            f.write(song_bytes)

        # Preview clip
        preview_path = save_temp_file(f"{user_id}_preview.mp3")
        create_preview(file_path, preview_path)

        await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(preview_path, "rb"), caption="🎧 Preview (30s)")
        await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(file_path, "rb"), caption="🎵 Full Song Ready!")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Use /start to create another song.")

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Error generating song: {e}")

# -------------------- Message Handler --------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    state = user_state.get(user_id, {"step":0})

    # Skip optional track
    if update.message.text and update.message.text.lower() == "/skip" and state["step"] == 1:
        state["track"] = None
        state["step"] = 2
        user_state[user_id] = state
        await update.message.reply_text("Step 2: Paste your lyrics.", reply_markup=back_keyboard())
        return

    # Upload track
    if state["step"] == 1 and update.message.audio:
        file = await update.message.audio.get_file()
        file_path = save_temp_file(f"{user_id}_track.mp3")
        await file.download_to_drive(file_path)
        state["track"] = file_path
        state["step"] = 2
        user_state[user_id] = state
        await update.message.reply_text("Track uploaded! Step 2: Paste your lyrics.", reply_markup=back_keyboard())
        return

    # Lyrics input
    if state["step"] == 2 and update.message.text:
        state["lyrics"] = update.message.text
        state["step"] = 3
        user_state[user_id] = state
        await update.message.reply_text(
            "Step 3: Choose singing style",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Arijit Style", callback_data="style_arijit"),
                 InlineKeyboardButton("Atif Style", callback_data="style_atif")],
                [InlineKeyboardButton("Pop", callback_data="style_pop"),
                 InlineKeyboardButton("EDM", callback_data="style_edm")],
                [InlineKeyboardButton("Romantic", callback_data="style_romantic")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ])
        )
        return

# -------------------- Main --------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.AUDIO, message_handler))
    print("Ultimate Music Bot is running...")
    app.run_polling()
