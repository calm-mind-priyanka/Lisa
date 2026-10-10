"""Private campaign dashboard integrated into the existing FastAPI/Telethon service."""
import asyncio
import hashlib
import hmac
import html
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from telethon.tl.functions.messages import ExportChatInviteRequest, EditExportedChatInviteRequest

DB_PATH = os.getenv("TRACKER_DB_PATH", "tracker.sqlite3")
TRACKER_PASSWORD = os.getenv("TRACKER_ADMIN_PASSWORD", "")
COOKIE_SECRET = os.getenv("TRACKER_SECRET_KEY", "")


def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            destination TEXT NOT NULL,
            destination_title TEXT NOT NULL,
            destination_id INTEGER NOT NULL,
            target INTEGER NOT NULL CHECK(target > 0),
            invite_link TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            clicks INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS members (
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            joined_at TEXT NOT NULL,
            last_join_at TEXT NOT NULL,
            left_at TEXT,
            is_member INTEGER NOT NULL DEFAULT 1,
            join_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(campaign_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
            user_id INTEGER,
            username TEXT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            details TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_campaign ON events(campaign_id, id DESC);
        """)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token(payload):
    sig = hmac.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig


def _valid_cookie(value):
    if not value or not COOKIE_SECRET:
        return False
    try:
        payload, sig = value.rsplit(".", 1)
        expected = hmac.new(COOKIE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        who, expiry = payload.split(":", 1)
        return hmac.compare_digest(sig, expected) and who == "admin" and int(expiry) > int(time.time())
    except Exception:
        return False


def _authed(request):
    return _valid_cookie(request.cookies.get("tracker_auth"))


def _page(title, body):
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>
    :root{{--bg:#0b1020;--panel:#151d32;--line:#283550;--text:#edf2ff;--muted:#a6b3cb;--accent:#6ee7b7;--red:#fda4af;}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1100px;margin:32px auto;padding:0 16px}}h1{{font-size:26px;margin:0 0 8px}}h2{{font-size:18px}}p,.muted{{color:var(--muted)}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;margin:16px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}.stat{{font-size:26px;font-weight:750}}label{{display:block;color:var(--muted);margin:10px 0 5px}}input,button{{font:inherit;border-radius:9px;padding:11px;border:1px solid var(--line)}}input{{width:100%;background:#0c1427;color:var(--text)}}button,.btn{{background:var(--accent);color:#09251b;font-weight:700;border:0;cursor:pointer;text-decoration:none;display:inline-block;padding:10px 14px;border-radius:9px}}.danger{{color:var(--red)}}table{{width:100%;border-collapse:collapse;min-width:720px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}}.tablewrap{{overflow:auto}}code{{overflow-wrap:anywhere;color:#b7f7dc}}.pill{{border:1px solid var(--line);border-radius:99px;padding:3px 8px}}.bar{{height:8px;background:#29354d;border-radius:99px;overflow:hidden;margin-top:7px}}.bar span{{display:block;height:100%;background:var(--accent)}}a{{color:#8decc8}}small{{color:var(--muted)}}
    </style></head><body><main>{body}</main></body></html>"""


def install_tracker(app, client, admin_getter):
    init_db()

    @app.get("/", response_class=HTMLResponse)
    async def tracker_root(request: Request):
        # Admin sees dashboard at the main Koyeb URL after login; everyone else sees blank.
        if _authed(request):
            return await dashboard_html()
        return HTMLResponse("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body></body></html>")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if _authed(request):
            return RedirectResponse("/", status_code=303)
        if not TRACKER_PASSWORD or not COOKIE_SECRET:
            return HTMLResponse(_page("Tracker setup required", "<section class='card'><h1>Tracker setup required</h1><p>Set TRACKER_ADMIN_PASSWORD and TRACKER_SECRET_KEY in your Koyeb environment variables.</p></section>"), status_code=503)
        body = "<section class='card' style='max-width:430px;margin:10vh auto'><h1>Admin sign in</h1><p>Private campaign dashboard</p><form method='post' action='/login'><label>Dashboard password</label><input name='password' type='password' required autocomplete='current-password'><p><button type='submit'>Sign in</button></p></form></section>"
        return HTMLResponse(_page("Admin sign in", body))

    @app.post("/login")
    async def login_submit(password: str = Form(...)):
        if not TRACKER_PASSWORD or not COOKIE_SECRET:
            raise HTTPException(503, "Dashboard authentication is not configured")
        if not hmac.compare_digest(password, TRACKER_PASSWORD):
            return HTMLResponse(_page("Sign in failed", "<section class='card'><h1>Sign in failed</h1><p>Incorrect password.</p><a href='/login'>Try again</a></section>"), status_code=401)
        payload = "admin:" + str(int(time.time()) + 60 * 60 * 24 * 14)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("tracker_auth", _token(payload), httponly=True, secure=True, samesite="strict", max_age=60 * 60 * 24 * 14, path="/")
        return response

    @app.post("/logout")
    async def logout():
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("tracker_auth", path="/")
        return response

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        return await dashboard_html()

    async def dashboard_html():
        with db() as c:
            campaigns = c.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        cards = []
        for camp in campaigns:
            with db() as c:
                unique = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=?", (camp['id'],)).fetchone()['n']
                active = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=? AND is_member=1", (camp['id'],)).fetchone()['n']
                leaves = c.execute("SELECT COUNT(*) n FROM events WHERE campaign_id=? AND event_type='left'", (camp['id'],)).fetchone()['n']
                evs = c.execute("SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT 12", (camp['id'],)).fetchall()
            pct = min(100, int(unique * 100 / camp['target']))
            state = "Completed" if camp['status'] == 'completed' else "Active"
            event_rows = "".join(f"<tr><td>{html.escape(e['occurred_at'])}</td><td>{html.escape(e['event_type'])}</td><td>{html.escape(str(e['user_id'] or '—'))}</td><td>{html.escape('@'+e['username'] if e['username'] else '—')}</td></tr>" for e in evs) or "<tr><td colspan='4'>No confirmed member events yet.</td></tr>"
            cards.append(f"""<section class='card'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap'><div><h2>#{camp['id']} — {html.escape(camp['name'])}</h2><p>{html.escape(camp['destination_title'])} · <span class='pill'>{state}</span></p></div><div><small>Campaign link</small><br><code>{html.escape(os.getenv('PUBLIC_BASE_URL','').rstrip('/') + '/r/' + str(camp['id']) if os.getenv('PUBLIC_BASE_URL') else '/r/'+str(camp['id']))}</code></div></div>
            <div class='grid'><div><small>Unique confirmed joins / target</small><div class='stat'>{unique} / {camp['target']}</div><div class='bar'><span style='width:{pct}%'></span></div></div><div><small>Currently known members</small><div class='stat'>{active}</div></div><div><small>Leaves recorded</small><div class='stat'>{leaves}</div></div><div><small>Link clicks</small><div class='stat'>{camp['clicks']}</div></div><div><small>Target remaining</small><div class='stat'>{max(0,camp['target']-unique)}</div></div></div>
            <p class='muted'>Created: {html.escape(camp['created_at'])} {(' · Completed: '+html.escape(camp['completed_at'])) if camp['completed_at'] else ''}</p><p><small>Telegram invite:</small> <code>{html.escape(camp['invite_link'])}</code></p><h3>Recent join/leave history</h3><div class='tablewrap'><table><thead><tr><th>Time (UTC)</th><th>Event</th><th>User ID</th><th>Username</th></tr></thead><tbody>{event_rows}</tbody></table></div></section>""")
        create_form = """<section class='card'><h2>Create campaign</h2><p class='muted'>Use a group/channel where your Telegram account can create invite links (usually administrator permission required).</p><form method='post' action='/campaigns'><label>Campaign name</label><input name='name' required maxlength='100' placeholder='June promotion'><label>Telegram group/channel link or @username</label><input name='destination' required placeholder='https://t.me/yourgroup or @yourgroup'><label>Unique confirmed join target</label><input name='target' type='number' min='1' max='1000000' required value='200'><p><button type='submit'>Create campaign link</button></p></form><small>Clicks are not joins. Only confirmed join events attributed to this campaign's unique invite count toward its target.</small></section>"""
        body = "<header><h1>Campaign Tracker</h1><p>Private admin dashboard · updates every 10 seconds</p><form method='post' action='/logout'><button type='submit'>Sign out</button></form></header>" + create_form + ("".join(cards) if cards else "<section class='card'>No campaigns yet. Create your first campaign above.</section>")
        body += "<script>setTimeout(()=>location.reload(),10000)</script>"
        return HTMLResponse(_page("Campaign Tracker", body), headers={"Cache-Control":"no-store"})

    @app.post("/campaigns")
    async def create_campaign(request: Request, name: str = Form(...), destination: str = Form(...), target: int = Form(...)):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        name = name.strip()[:100]
        destination = destination.strip()
        if not name or target < 1 or target > 1_000_000:
            raise HTTPException(400, "Provide a campaign name and a positive target")
        if client is None or not getattr(client, 'is_connected', lambda: False)():
            return HTMLResponse(_page("Tracker temporarily unavailable", "<section class='card'><h1>Tracker temporarily unavailable</h1><p>Telegram connection is not ready. Try again shortly.</p><a href='/'>Back</a></section>"), status_code=503)
        try:
            entity = await client.get_entity(destination)
            # A campaign-specific Telegram invite enables join attribution; a normal URL redirect alone cannot prove a join.
            invite = await client(ExportChatInviteRequest(peer=entity, title=name[:32]))
            invite_url = getattr(invite, 'link', None)
            if not invite_url:
                raise RuntimeError('Telegram did not return an invite link')
            title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or destination
            chat_id = int(getattr(entity, 'id'))
            with db() as c:
                cur = c.execute("INSERT INTO campaigns(name,destination,destination_title,destination_id,target,invite_link,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (name, destination, title, chat_id, target, invite_url, 'active', utcnow()))
                campaign_id = cur.lastrowid
        except Exception as exc:
            # Do not expose Telegram internals or credentials in a public error page.
            log_msg = f"Campaign creation failed: {type(exc).__name__}: {exc}"
            print(log_msg)
            return HTMLResponse(_page("Could not create campaign", "<section class='card'><h1>Could not create campaign</h1><p>Check the destination and ensure the userbot account can create invite links there.</p><a href='/'>Back to dashboard</a></section>"), status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.get("/r/{campaign_id}")
    async def campaign_redirect(campaign_id: int):
        with db() as c:
            camp = c.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not camp:
                return HTMLResponse(_page("Link unavailable", "<section class='card'><h1>Link Unavailable</h1><p>This campaign link does not exist.</p></section>"), status_code=404)
            if camp['status'] != 'active':
                return HTMLResponse(_page("Campaign completed", "<section class='card'><h1>Campaign Completed</h1><p>Access to this campaign link is closed.</p></section>"), status_code=410)
            c.execute("UPDATE campaigns SET clicks=clicks+1 WHERE id=?", (campaign_id,))
            invite_url = camp['invite_link']
        return RedirectResponse(invite_url, status_code=302)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    async def revoke_campaign(campaign_id):
        if client is None or not getattr(client, 'is_connected', lambda: False)():
            return
        with db() as c:
            camp = c.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not camp:
            return
        try:
            entity = await client.get_entity(int(camp['destination_id']))
            await client(EditExportedChatInviteRequest(peer=entity, link=camp['invite_link'], revoked=True))
        except Exception as exc:
            print(f"Could not revoke campaign invite {campaign_id}: {type(exc).__name__}")

    def finish_if_target_reached(campaign_id):
        with db() as c:
            camp = c.execute("SELECT target,status FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not camp or camp['status'] != 'active':
                return False
            unique = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=?", (campaign_id,)).fetchone()['n']
            if unique >= camp['target']:
                c.execute("UPDATE campaigns SET status='completed', completed_at=? WHERE id=?", (utcnow(), campaign_id))
                return True
        return False

    # Telegram membership actions are authoritative; a link click alone is never counted as a join.
    if client is not None:
        from telethon import events

        @client.on(events.ChatAction)
        async def tracker_chat_action(event):
            try:
                chat = await event.get_chat()
                chat_id = int(getattr(chat, 'id', 0) or 0)
                action = getattr(getattr(event, 'action_message', None), 'action', None)
                invite = getattr(action, 'invite', None)
                invite_link = getattr(invite, 'link', None)
                user = await event.get_user()
                if not user or getattr(user, 'bot', False):
                    return
                uid = int(user.id)
                username = getattr(user, 'username', None)
                first_name = getattr(user, 'first_name', None)
                timestamp = utcnow()
                revoke_ids = []
                with db() as c:
                    # Match the unique invite URL to one campaign. Existing members who merely click do not emit a join event.
                    matched = None
                    if invite_link:
                        matched = c.execute("SELECT * FROM campaigns WHERE destination_id=? AND invite_link=? AND status='active'", (chat_id, invite_link)).fetchone()
                    if event.user_joined or event.user_added:
                        if matched:
                            previous = c.execute("SELECT * FROM members WHERE campaign_id=? AND user_id=?", (matched['id'], uid)).fetchone()
                            if previous:
                                c.execute("UPDATE members SET username=?,first_name=?,last_join_at=?,left_at=NULL,is_member=1,join_count=join_count+1 WHERE campaign_id=? AND user_id=?", (username, first_name, timestamp, matched['id'], uid))
                                etype = 'rejoined'
                            else:
                                c.execute("INSERT INTO members(campaign_id,user_id,username,first_name,joined_at,last_join_at,is_member,join_count) VALUES(?,?,?,?,?,?,1,1)", (matched['id'], uid, username, first_name, timestamp, timestamp))
                                etype = 'joined'
                            c.execute("INSERT INTO events(campaign_id,user_id,username,event_type,occurred_at,details) VALUES(?,?,?,?,?,?)", (matched['id'], uid, username, etype, timestamp, 'Attributed to campaign invite'))
                            # Count unique attributed user IDs (not clicks or rejoin events).
                            total_unique = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=?", (matched['id'],)).fetchone()['n']
                            current_campaign = c.execute("SELECT target,status FROM campaigns WHERE id=?", (matched['id'],)).fetchone()
                            if current_campaign and current_campaign['status'] == 'active' and total_unique >= current_campaign['target']:
                                c.execute("UPDATE campaigns SET status='completed', completed_at=? WHERE id=?", (timestamp, matched['id']))
                                revoke_ids.append(matched['id'])
                        else:
                            # Rejoins/leaves of already-attributed members are logged, but unrelated joins never enter campaign totals.
                            known = c.execute("SELECT campaign_id FROM members WHERE user_id=? AND campaign_id IN (SELECT id FROM campaigns WHERE destination_id=?)", (uid, chat_id)).fetchall()
                            for row in known:
                                c.execute("UPDATE members SET is_member=1,left_at=NULL,last_join_at=?,join_count=join_count+1,username=?,first_name=? WHERE campaign_id=? AND user_id=?", (timestamp, username, first_name, row['campaign_id'], uid))
                                c.execute("INSERT INTO events(campaign_id,user_id,username,event_type,occurred_at,details) VALUES(?,?,?,?,?,?)", (row['campaign_id'], uid, username, 'rejoined', timestamp, 'Rejoin observed; original campaign attribution retained'))
                    elif event.user_left or event.user_kicked:
                        known = c.execute("SELECT campaign_id FROM members WHERE user_id=? AND campaign_id IN (SELECT id FROM campaigns WHERE destination_id=?)", (uid, chat_id)).fetchall()
                        for row in known:
                            c.execute("UPDATE members SET is_member=0,left_at=? WHERE campaign_id=? AND user_id=?", (timestamp, row['campaign_id'], uid))
                            c.execute("INSERT INTO events(campaign_id,user_id,username,event_type,occurred_at,details) VALUES(?,?,?,?,?,?)", (row['campaign_id'], uid, username, 'left' if event.user_left else 'kicked', timestamp, None))
                for cid in revoke_ids:
                    asyncio.create_task(revoke_campaign(cid))
            except Exception as exc:
                print(f"Tracker membership update error: {type(exc).__name__}: {exc}")
