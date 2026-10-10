# Integrated Telegram Campaign Tracker

This tracker runs inside the existing FastAPI app and Telethon userbot in the same Koyeb service and asyncio event loop. It does not require a separate web deployment. Uvicorn and Telethon share one asyncio event loop so campaign actions can call Telegram safely.

## Required Koyeb environment variables

Set these in the service settings (never commit them to source):

- `API_ID` — Telegram API ID
- `API_HASH` — Telegram API hash
- `SESSION` — Telethon StringSession
- `PRIMARY_ADMIN` — your Telegram numeric user ID
- `TRACKER_ADMIN_PASSWORD` — a strong, unique dashboard password
- `TRACKER_SECRET_KEY` — a long random secret used to sign the admin cookie
- `PUBLIC_BASE_URL` — optional; if omitted, the app tries Koyeb’s `KOYEB_PUBLIC_DOMAIN` automatically
- `TRACKER_DB_PATH` — optional; defaults to `tracker.sqlite3`

**Free Koyeb storage warning:** the free instance filesystem is ephemeral, and Koyeb volumes cannot be attached to a free instance. SQLite is fine for testing, but campaigns and history can be lost during rescheduling/redeploys. For reliable long-term data, use an external persistent database or a Koyeb plan/region that supports volumes. Do not treat free-instance local SQLite as durable storage.

## How to use

1. Deploy this folder as the same Koyeb service, using the included Dockerfile.
2. Visit `/login` once and sign in with `TRACKER_ADMIN_PASSWORD`. After authentication, the main URL `/` opens your dashboard. An unauthenticated visitor opening `/` sees a blank page. `/dashboard` requires authentication too.
3. In the dashboard, enter a campaign name, Telegram destination (`@username` or a Telegram link your userbot can resolve), and unique-join target. The userbot account must be able to access the destination and create invite links there (usually administrator permission is required).
4. Copy the generated public tracker URL `/r/<campaign-id>` from the dashboard and put it in your bio. It redirects to that campaign's unique Telegram invite link.

## Attribution behavior

- Each request to the public tracking URL increments the link-hit counter; it is **not** counted as a join. Automated preview/scanner requests may also increment this counter, so it is not a guaranteed count of unique human clicks.
- Existing members who click the campaign URL but do not newly join are not counted.
- Only a Telegram membership-join event that includes the campaign's unique invite link is credited to that campaign. Telegram update visibility and permissions affect what can be observed; test with a real new member before relying on a campaign.
- A user ID is counted once per campaign in the lifetime unique-attributed-user total. Rejoins are logged separately and do not create another unique user.
- The target is based on the number of currently tracked campaign-attributed members (`is_member=1`), not lifetime joins. Leaves/kicks of known campaign members reduce the current-member count. The dashboard reports whether the target is met right now and calculates remaining target from current members.
- When the current-member count reaches the target, the campaign is marked closed and its campaign invite is revoked on a best-effort basis. The short `/r/<id>` route then displays “Campaign Completed / Access Closed.” If members leave after closure, the dashboard shows that the target is no longer currently met, but the campaign remains closed and must be recreated to resume acquisition. Other campaigns remain independent.
- Tracking link hits are HTTP requests, not guaranteed unique human clicks; automated previews/scanners may contribute.
- Dashboard tracking URLs use `PUBLIC_BASE_URL` if set, otherwise `KOYEB_PUBLIC_DOMAIN`, otherwise the incoming request host.
- Telegram may not expose invite attribution for every type of join (for example, joins via a different link or some request-approval flows); such joins are not falsely credited.

## Security note

The original archive contained Telegram session/API credentials embedded in `bot.py`. They have been removed from the source and must be supplied as environment variables or a private `bot_transfer.json`. Because the old session string was included in the archive shared here, revoke that Telegram session and generate a fresh session before deploying. Never share or commit session strings.


## Join attribution troubleshooting notes

The tracker reads invite-link joins from Telethon's `events.ChatAction` service
message. For a `MessageActionChatJoinedByLink`, the exported invite is exposed
as `action.invite_link`; it is not named `action.invite`. The tracker now reads
the documented field, keeps compatibility fallbacks, normalizes equivalent
Telegram invite URL host/trailing-slash forms, and matches only within the
destination chat.

The dashboard's lifetime unique count is based on users recorded in `members`.
Current members counts only rows currently marked as members. Clicks are never
counted as joins. Duplicate join updates for a user already marked as a member
do not create extra join/rejoin events.

Telegram's MTProto API includes `messages.getChatInviteImporters`, which can
return users who joined using a specific invite link when the logged-in user
has the required admin access. The tracker does not automatically import
historical importers: doing so safely requires reconciling historical dates
and users while not guessing whether each person is still a member. The
dashboard's existing database cannot reconstruct past leaves/kicks or current
membership solely from Telegram's aggregate “joined” count. Historical
reconciliation should only be performed from importer records returned by
Telegram, never by copying an aggregate count into member rows.

The `requirements.txt` currently leaves Telethon unpinned, so the exact
Telethon version installed in a deployed Koyeb image cannot be inferred from
the repository alone. Check the build logs or run `python -c "import telethon;
print(telethon.__version__)"` in the deployed image when diagnosing version-
specific behavior.
