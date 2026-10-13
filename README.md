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
- `GEMINI_MODEL` (optional preference; only accepted if it matches one of the explicitly allowlisted model IDs with free-tier API pricing: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, or `gemini-3.1-flash-lite`. Leave blank to prefer them in that order.)
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
- Gemini model discovery is restricted to an explicit allowlist of model IDs that Google currently lists with free-tier API pricing. The bot never calls arbitrary discovered models or `gemini-flash-latest`; it tries only approved IDs, in priority order, and moves to another approved ID after model-unavailable, 503 overload, or 429 quota/rate-limit errors. Invalid-key, permission, billing, and malformed-request errors stop rather than silently changing models. Re-check Google's official pricing page because pricing and model availability can change. IMPORTANT: an API model having a free tier does not itself guarantee zero charges if your Google project is upgraded/configured for paid billing. To avoid API charges, keep the project on the free tier and check Google AI Studio usage/billing settings. The code cannot inspect or enforce the project's billing plan.
- Voice replies use a synthetic TTS service, not a recording of a real person.
- Test in a separate Koyeb service before replacing a working deployment.
- The Telegram session string and API hash previously appeared in pasted source. Revoke the exposed Telegram session in Telegram Settings > Devices, create a fresh session, and store the new value only as a secret environment variable.
