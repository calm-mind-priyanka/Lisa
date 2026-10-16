Lisa auto-reply bot - privacy-focused build

The bot writes only these configuration files locally:
- groups.json: group IDs configured by the admin
- settings.json: reply text and bot configuration values

The bot does not save incoming message history or log incoming message text.
Logs are sent to stdout (Koyeb runtime logs), not to a local error.log file.
The /debugauto command keeps limited diagnostic counters and the latest chat ID
in memory while the process runs; this diagnostic state is not written to disk.

Telethon still processes incoming updates in order to reply. Temporary in-memory
message references are used by existing auto-delete/emergency-cleanup features.
This does not mean the bot has a persistent message-history database. Koyeb may
retain its own runtime logs according to its platform settings.

Required Koyeb environment variables remain: API_ID, API_HASH, SESSION,
PRIMARY_ADMIN. SECONDARY_ADMIN is optional.
