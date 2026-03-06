from telethon import events

CHANNEL_ID = -1001702618096   # change if needed

def setup_purge(client):

    @client.on(events.NewMessage(outgoing=True, pattern='/purge'))
    async def purge_all(event):

        if event.chat_id != CHANNEL_ID:
            await event.reply("❌ Use this command inside the channel.")
            return

        await event.reply("⚠️ Purging channel messages...")

        ids = []

        async for msg in client.iter_messages(CHANNEL_ID):
            ids.append(msg.id)

            if len(ids) >= 100:
                await client.delete_messages(CHANNEL_ID, ids)
                ids = []

        if ids:
            await client.delete_messages(CHANNEL_ID, ids)

        await event.reply("✅ All channel messages deleted.")
