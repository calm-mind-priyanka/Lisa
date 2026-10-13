# Ananya AI Telegram Userbot

A clean replacement for the old static auto-reply bot. It does not include the campaign tracker or dashboard. The FastAPI root and `/health` endpoint are only Koyeb health checks.

## Included
- Telethon userbot.
- Gemini-powered fictional character: Ananya Sharma.
- Sandy is recognized only by the configured numeric `SANDY_USER_ID`.
- Separate temporary conversation history per Telegram user.
- Private-message responses by default.
- Optional group responses for explicitly configured group IDs; Ananya replies in those groups only when mentioned or directly replied to.
- Image and audio/voice message input passed to Gemini.
- Optional TTS voice notes (off by default), generated with Edge TTS and converted using ffmpeg.
- Koyeb Docker health endpoint.

## Required Koyeb environment variables
- `API_ID`
- `API_HASH`
- `SESSION`
- `GEMINI_API_KEY`
- `SANDY_USER_ID`

Optional:
- `PRIMARY_ADMIN` (defaults to `SANDY_USER_ID`)
- `AI_GROUP_IDS` (comma-separated Telegram chat IDs; blank disables group replies)
- `IGNORED_USER_IDS` (comma-separated sender IDs)
- `GEMINI_MODEL` (optional preference; omit it to discover models available to your API key automatically. If a preferred model is unavailable, the bot tries other discovered `generateContent` models.)
- `VOICE_REPLIES` (`true` or `false`; default `false`)
- `VOICE_NAME` (default `hi-IN-SwaraNeural`)
- `MAX_HISTORY_TURNS` (default 12)
- `MAX_MEDIA_MB` (default 15)
- `PORT` (default 8080)

## Admin commands
Send these as outgoing messages from the configured primary admin account:
- `/ping`
- `/status`
- `/stopbot`
- `/resumebot`
- `/clearallmemory`

## Deploy
1. Upload this ZIP to a repository or deploy using its Dockerfile.
2. Add the required variables in Koyeb. Do not add secrets to the repository.
3. Initially set `VOICE_REPLIES=false`.
4. Check the Koyeb health check at `/health`.
5. Send a private message to the Telegram account to test text replies first.
6. Only configure `AI_GROUP_IDS` if you want group support.

## Important limitations
- Memory is in RAM only and is lost on restart. MongoDB persistence is not included yet.
- Gemini model discovery uses the models exposed to your API key and filters for `generateContent`; actual image/audio support and account access can still vary by model. If a model fails with a model-not-found error, the bot tries another discovered candidate. Quota, invalid-key, and permission errors are not automatically fixed by model switching.
- Voice replies use a synthetic TTS service, not a recording of a real person.
- Test in a separate Koyeb service before replacing a working deployment.
- The Telegram session string and API hash previously appeared in pasted source. Revoke the exposed Telegram session in Telegram Settings > Devices, create a fresh session, and store the new value only as a secret environment variable.
