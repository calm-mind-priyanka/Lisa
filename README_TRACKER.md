# Integrated Telegram Campaign Tracker

This tracker runs inside the existing FastAPI app and Telethon userbot in the same Koyeb service. It does not require a separate web deployment.

## Required Koyeb environment variables

Set these in the service settings (never commit them to source):

- `API_ID` — Telegram API ID
- `API_HASH` — Telegram API hash
- `SESSION` — Telethon StringSession
- `PRIMARY_ADMIN` — your Telegram numeric user ID
- `TRACKER_ADMIN_PASSWORD` — a strong, unique dashboard password
- `TRACKER_SECRET_KEY` — a long random secret used to sign the admin cookie
- `PUBLIC_BASE_URL` — optional, e.g. `https://your-service.koyeb.app` (used to display full campaign URLs)
- `TRACKER_DB_PATH` — optional; defaults to `tracker.sqlite3`

**Persistence:** attach a persistent volume and set `TRACKER_DB_PATH` to a path on it if campaigns and history must survive redeploys/restarts. Without persistent storage, local SQLite data may be lost on redeploy.

## How to use

1. Deploy this folder as the same Koyeb service, using the included Dockerfile.
2. Visit `/login` once and sign in with `TRACKER_ADMIN_PASSWORD`. After authentication, the main URL `/` opens your dashboard. An unauthenticated visitor opening `/` sees a blank page. `/dashboard` requires authentication too.
3. In the dashboard, enter a campaign name, Telegram destination (`@username` or a Telegram link your userbot can resolve), and unique-join target. The userbot account must be able to access the destination and create invite links there (usually administrator permission is required).
4. Put the generated public tracker URL `/r/<campaign-id>` in your bio. It redirects to that campaign's unique Telegram invite link.

## Attribution behavior

- A click is recorded as a click only; it is **not** counted as a join.
- Existing members who click the campaign URL but do not newly join are not counted.
- Only a Telegram membership-join event that includes the campaign's unique invite link is credited to that campaign. Telegram update visibility and permissions affect what can be observed; test with a real new member before relying on a campaign.
- A user ID is counted once per campaign toward the target. Rejoins are logged as events but do not increase the unique-join total. Leaves/kicks of known campaign members are logged and update the currently-known-member count.
- At the unique target, the campaign is marked completed and the campaign invite is revoked on a best-effort basis. The public `/r/<id>` route then displays “Campaign Completed / Access Closed.” Other campaigns remain active.
- Telegram may not expose invite attribution for every type of join (for example, joins via a different link or some request-approval flows); such joins are not falsely credited.

## Security note

The original archive contained Telegram session/API credentials embedded in `bot.py`. They have been removed from the source and must be supplied as environment variables or a private `bot_transfer.json`. Because the old session string was included in the archive shared here, revoke that Telegram session and generate a fresh session before deploying. Never share or commit session strings.
