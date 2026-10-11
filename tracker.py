"""Private campaign dashboard integrated into the existing FastAPI/Telethon service."""
import asyncio
import hashlib
import hmac
import html
import os
import sqlite3
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
        CREATE TABLE IF NOT EXISTS tracker_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        """)
        # Additive migration only: keep existing campaign, member, and event history intact.
        campaign_columns = {row["name"] for row in c.execute("PRAGMA table_info(campaigns)").fetchall()}
        for column in ("start_intro_sent", "success_outro_sent"):
            if column not in campaign_columns:
                c.execute(f"ALTER TABLE campaigns ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
        c.execute("INSERT OR IGNORE INTO tracker_settings(key,value) VALUES(?,?)", ("start_intro_template", "🎬 ═══ MISSION INITIATED ═══ 🎬\n\n🚀 CAMPAIGN STARTED!\n\n📌 Campaign: {campaign_name}\n🎯 Mission Target: {target}\n👥 Current Joins: {current_joins}\n🕒 Started At: {started_at}\n\n🔥 The mission has officially begun!"))
        c.execute("INSERT OR IGNORE INTO tracker_settings(key,value) VALUES(?,?)", ("success_outro_template", "🏆 ═══ MISSION SUCCESSFUL ═══ 🏆\n\n🎯 Campaign: {campaign_name}\n✅ Target Achieved: {target}\n👥 Final Joins: {current_joins}\n🕒 Completed At: {completed_at}\n\n🎉 MISSION ACCOMPLISHED!\n\nThank you to everyone who participated!"))


def _public_base_url(request=None):
    configured = (os.getenv('PUBLIC_BASE_URL', '') or os.getenv('KOYEB_PUBLIC_DOMAIN', '')).strip().rstrip('/')
    if configured:
        if not configured.startswith(('http://', 'https://')):
            configured = 'https://' + configured
        return configured
    # Useful for local deployments too. On Koyeb, PUBLIC_BASE_URL is still the
    # most reliable setting if a reverse proxy does not forward host headers.
    if request is not None:
        return str(request.base_url).rstrip('/')
    return ''


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_ist(value):
    """Format stored ISO timestamps as Indian Standard Time for dashboard display."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        day = dt.day
        suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suffix} {dt.strftime('%B %Y, %-I:%M:%S %p')} IST"
    except (ValueError, TypeError, OverflowError):
        return str(value)


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
    :root{{color-scheme:dark;--bg:#080d1b;--panel:#111a2e;--panel2:#17233c;--line:#293957;--text:#f2f6ff;--muted:#a7b5cf;--mint:#5eead4;--blue:#60a5fa;--violet:#a78bfa;--pink:#f472b6;--amber:#fbbf24;--red:#fda4af;--shadow:0 18px 50px rgba(0,0,0,.24)}}
    *{{box-sizing:border-box}}html{{min-height:100%;background:var(--bg)}}body{{margin:0;min-height:100vh;color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(ellipse at 10% 0%,rgba(96,165,250,.16),transparent 35%),radial-gradient(ellipse at 92% 8%,rgba(167,139,250,.15),transparent 32%),var(--bg)}}
    main{{max-width:1180px;margin:0 auto;padding:34px 22px 64px}}header{{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;margin:0 0 26px;padding:22px 24px;border:1px solid rgba(148,163,184,.2);border-radius:22px;background:linear-gradient(120deg,rgba(17,26,46,.96),rgba(23,35,60,.88));box-shadow:var(--shadow)}}header h1{{margin:0;font-size:clamp(25px,4vw,34px);line-height:1.15;letter-spacing:-.04em}}h1{{font-size:clamp(24px,4vw,32px);line-height:1.2;letter-spacing:-.035em}}h2{{margin:0 0 6px;font-size:18px;letter-spacing:-.015em}}h3{{font-size:15px;margin:20px 0 8px}}p{{margin:8px 0;color:var(--muted)}}.muted,small{{color:var(--muted)}}.eyebrow{{font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--mint);margin:0 0 7px}}.brand-mark{{display:inline-grid;place-items:center;width:40px;height:40px;margin-right:12px;border-radius:13px;color:#071526;background:linear-gradient(135deg,var(--mint),var(--blue),var(--violet));font-weight:900;box-shadow:0 8px 25px rgba(96,165,250,.2);vertical-align:middle}}.card{{position:relative;overflow:hidden;background:linear-gradient(145deg,rgba(17,26,46,.96),rgba(14,22,40,.96));border:1px solid rgba(148,163,184,.18);border-radius:20px;padding:23px;margin:18px 0;box-shadow:var(--shadow)}}.card:before{{content:"";position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(90deg,var(--mint),var(--blue),var(--violet),var(--pink));opacity:.9}}.section-intro{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap;margin-bottom:15px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:20px 0}}.grid>div{{min-width:0;padding:15px;border:1px solid rgba(148,163,184,.16);border-radius:15px;background:linear-gradient(145deg,rgba(23,35,60,.9),rgba(14,22,40,.8))}}.grid small{{display:block;line-height:1.4;min-height:30px;font-size:11px;letter-spacing:.02em}}.stat{{font-size:clamp(23px,3vw,29px);font-weight:800;letter-spacing:-.04em;margin-top:6px;overflow-wrap:anywhere}}.bar{{height:8px;background:#25324b;border-radius:99px;overflow:hidden;margin-top:11px}}.bar span{{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--mint),var(--blue),var(--violet));box-shadow:0 0 15px rgba(94,234,212,.2)}}label{{display:block;color:#dbe6fa;font-size:13px;font-weight:650;margin:15px 0 7px}}input,button{{font:inherit;border-radius:11px;padding:12px 14px;border:1px solid var(--line)}}input{{width:100%;color:var(--text);background:#0a1224;outline:none;transition:border-color .2s,box-shadow .2s}}input:focus{{border-color:var(--blue);box-shadow:0 0 0 3px rgba(96,165,250,.15)}}button,.btn{{background:linear-gradient(100deg,var(--mint),#7dd3fc);color:#071827;font-weight:800;border:0;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 17px;border-radius:11px;transition:transform .15s,filter .15s;box-shadow:0 8px 20px rgba(94,234,212,.12)}}button:hover,.btn:hover{{filter:brightness(1.07);transform:translateY(-1px)}}.secondary{{background:#1d2b45;color:#e6efff;border:1px solid #354766;box-shadow:none}}.danger{{color:var(--red)}}.pill{{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(94,234,212,.28);background:rgba(94,234,212,.09);color:#99f6e4;border-radius:99px;padding:4px 10px;font-size:11px;font-weight:800;letter-spacing:.04em}}.pill:before{{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}}.pill.completed{{color:#c4b5fd;background:rgba(167,139,250,.1);border-color:rgba(167,139,250,.28)}}.tablewrap{{overflow:auto;border:1px solid rgba(148,163,184,.15);border-radius:12px}}table{{width:100%;border-collapse:collapse;min-width:560px;background:rgba(8,13,27,.35)}}th,td{{text-align:left;padding:12px 13px;border-bottom:1px solid rgba(148,163,184,.12);font-size:12px;vertical-align:top}}th{{color:#b9c9e4;background:rgba(96,165,250,.07);font-weight:750;white-space:nowrap}}tr:last-child td{{border-bottom:0}}code{{display:inline-block;max-width:100%;overflow-wrap:anywhere;color:#99f6e4;background:rgba(94,234,212,.06);border:1px solid rgba(94,234,212,.12);border-radius:8px;padding:5px 8px;font-size:12px}}.linkbox{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}.linkbox code{{flex:1;min-width:190px}}.form-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}}.form-grid .full{{grid-column:1/-1}}.empty-state{{text-align:center;padding:34px 18px;border:1px dashed #34435e;border-radius:14px;background:rgba(96,165,250,.035)}}.empty-icon{{font-size:28px;margin-bottom:6px}}.notice{{border:1px solid rgba(251,191,36,.25);background:rgba(251,191,36,.07);border-radius:12px;padding:12px 14px;font-size:12px}}.login-card{{max-width:460px;margin:10vh auto 0}}.login-card form{{margin-top:20px}}.login-card button{{width:100%;margin-top:10px}}.footer-note{{text-align:center;font-size:11px;color:#72829f;margin-top:24px}}.hero-copy{{max-width:650px}}.campaign-top{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}.campaign-top>div{{min-width:0}}.target-note{{font-size:12px;color:#9eb0cc}}
    @media(max-width:640px){{main{{padding:18px 12px 42px}}header{{padding:18px;border-radius:17px}}.card{{padding:17px;border-radius:16px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}.grid>div{{padding:12px}}.stat{{font-size:24px}}.form-grid{{grid-template-columns:1fr}}.form-grid .full{{grid-column:auto}}.login-card{{margin-top:7vh}}.linkbox code{{min-width:100%}}}}
    @media(prefers-reduced-motion:reduce){{*,*:before,*:after{{scroll-behavior:auto!important;transition:none!important}}}}
    </style></head><body><main>{body}</main></body></html>"""


def install_tracker(app, client, admin_getter):
    init_db()

    async def send_campaign_caption(campaign_id, kind):
        flag = "start_intro_sent" if kind == "start" else "success_outro_sent"
        template_key = "start_intro_template" if kind == "start" else "success_outro_template"
        if client is None or not getattr(client, "is_connected", lambda: False)():
            print(f"Cannot send {kind} campaign caption {campaign_id}: Telegram is not connected")
            return
        with db() as c:
            camp = c.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not camp or camp["status"] == "archived" or camp[flag]:
                return
            row = c.execute("SELECT value FROM tracker_settings WHERE key=?", (template_key,)).fetchone()
            template = row["value"] if row else ""
            if not template.strip():
                return
            # Claim once so duplicate events/restarts cannot send the same caption twice.
            c.execute(f"UPDATE campaigns SET {flag}=1 WHERE id=? AND {flag}=0", (campaign_id,))
            if c.execute("SELECT changes()").fetchone()[0] != 1:
                return
            active = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=? AND is_member=1", (campaign_id,)).fetchone()["n"]
            values = {
                "campaign_name": camp["name"], "target": camp["target"],
                "current_joins": active, "started_at": format_ist(camp["created_at"]),
                "completed_at": format_ist(camp["completed_at"] or utcnow()),
            }
            try:
                caption = template.format_map(values)
            except (KeyError, ValueError):
                caption = template
            destination_id = camp["destination_id"]
        try:
            entity = await client.get_entity(int(destination_id))
            await client.send_message(entity, caption)
        except Exception as exc:
            # Permit a later attempt if Telegram rejected the send.
            with db() as c:
                c.execute(f"UPDATE campaigns SET {flag}=0 WHERE id=?", (campaign_id,))
            print(f"Could not send {kind} campaign caption {campaign_id}: {type(exc).__name__}")

    async def close_campaign_and_send_outro(campaign_id):
        # Preserve original behavior: attempt to revoke the invite, then send the separate outro.
        await revoke_campaign(campaign_id)
        await send_campaign_caption(campaign_id, "success")

    @app.get("/", response_class=HTMLResponse)
    async def tracker_root(request: Request):
        # Admin sees dashboard at the main Koyeb URL after login; everyone else sees blank.
        if _authed(request):
            return await dashboard_html(request)
        return HTMLResponse("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body></body></html>")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if _authed(request):
            return RedirectResponse("/", status_code=303)
        if not TRACKER_PASSWORD or not COOKIE_SECRET:
            return HTMLResponse(_page("Tracker setup required", "<section class='card'><h1>Tracker setup required</h1><p>Set TRACKER_ADMIN_PASSWORD and TRACKER_SECRET_KEY in your Koyeb environment variables.</p></section>"), status_code=503)
        body = "<section class='card login-card'><p class='eyebrow'>Private workspace</p><h1><span class='brand-mark'>CT</span>Welcome back</h1><p>Sign in to manage your Telegram campaigns, links and verified joins.</p><form method='post' action='/login'><label for='password'>Dashboard password</label><input id='password' name='password' type='password' required autocomplete='current-password' placeholder='Enter your admin password'><button type='submit'>Sign in <span aria-hidden='true'>→</span></button></form><p class='footer-note'>Private admin access · Protected session</p></section>"
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
        return await dashboard_html(request)

    async def dashboard_html(request):
        with db() as c:
            campaigns = c.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        cards = []
        public_base = _public_base_url(request)
        for camp in campaigns:
            with db() as c:
                unique = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=?", (camp['id'],)).fetchone()['n']
                active = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=? AND is_member=1", (camp['id'],)).fetchone()['n']
                leaves = c.execute("SELECT COUNT(*) n FROM events WHERE campaign_id=? AND event_type IN ('left','kicked')", (camp['id'],)).fetchone()['n']
                rejoins = c.execute("SELECT COUNT(*) n FROM events WHERE campaign_id=? AND event_type='rejoined'", (camp['id'],)).fetchone()['n']
                evs = c.execute("SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT 12", (camp['id'],)).fetchall()
            # The target is the current number of tracked campaign members, not
            # the lifetime number of different people who ever joined.
            pct = min(100, int(active * 100 / camp['target']))
            state = "MISSION SUCCESSFUL" if camp['status'] == 'completed' else ("Archived" if camp['status'] == 'archived' else "Active")
            state_class = 'completed' if camp['status'] in ('completed', 'archived') else ''
            target_label = "TARGET MET NOW" if active >= camp['target'] else "TARGET NOT MET"
            tracking_url = (public_base + '/r/' + str(camp['id'])) if public_base else ('/r/' + str(camp['id']))
            event_rows = "".join(f"<tr><td>{html.escape(format_ist(e['occurred_at']))}</td><td>{html.escape(e['event_type'])}</td><td>{html.escape(str(e['user_id'] or '—'))}</td><td>{html.escape('@'+e['username'] if e['username'] else '—')}</td></tr>" for e in evs) or "<tr><td colspan='4'>No confirmed member events yet.</td></tr>"
            cards.append(f"""<section class='card'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap'><div><h2>#{camp['id']} — {html.escape(camp['name'])}</h2><p>{html.escape(camp['destination_title'])} · <span class='pill {state_class}'>{state}</span> · <strong>{target_label}</strong></p></div><div><small>Campaign tracking URL</small><br><div class='linkbox'><code>{html.escape(tracking_url)}</code><button type='button' class='secondary' onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent).then(()=>{{this.textContent='Copied!'}})">Copy link</button></div></div></div>
            <div class='grid'><div><small>Unique attributed users (lifetime)</small><div class='stat'>{unique}</div></div><div><small>Current members / target</small><div class='stat'>{active} / {camp['target']}</div><div class='bar'><span style='width:{pct}%'></span></div></div><div><small>Leaves / kicks recorded</small><div class='stat'>{leaves}</div></div><div><small>Rejoin events</small><div class='stat'>{rejoins}</div></div><div><small>Tracking link hits</small><div class='stat'>{camp['clicks']}</div></div><div><small>Target remaining (current members)</small><div class='stat'>{max(0,camp['target']-active)}</div></div></div>
            <p class='muted'>Created: {html.escape(format_ist(camp['created_at']))} {(' · Completed: '+html.escape(format_ist(camp['completed_at']))) if camp['completed_at'] else ''}</p><p><small>Telegram invite:</small> <code>{html.escape(camp['invite_link'])}</code></p><h3>Recent join/leave history</h3><div class='tablewrap'><table><thead><tr><th>Time (IST)</th><th>Event</th><th>User ID</th><th>Username</th></tr></thead><tbody>{event_rows}</tbody></table></div><form method="post" action="/campaigns/{camp['id']}/delete" onsubmit="return confirm('Archive campaign: {html.escape(camp['name'], quote=True)}? Tracking will stop; records/history are preserved.');" style="margin-top:14px"><button class="secondary danger" type="submit">Delete / Archive Campaign</button></form></section>""")
        create_form = """<section class='card'><div class='section-intro'><div><p class='eyebrow'>Launch a campaign</p><h2>Create a tracking link</h2><p>Set a destination and target. Your private invite and tracking URL are generated automatically.</p></div><span class='pill'>New campaign</span></div><form method='post' action='/campaigns' class='form-grid'><div><label for='name'>Campaign name</label><input id='name' name='name' required maxlength='100' placeholder='October bio campaign'></div><div><label for='target'>Unique join target</label><input id='target' name='target' type='number' min='1' max='1000000' required value='100'></div><div class='full'><label for='destination'>Telegram group or channel</label><input id='destination' name='destination' required placeholder='@yourgroup or https://t.me/yourgroup'></div><div class='full'><p><button type='submit'>✦ Generate tracking link</button></p><div class='notice'>Important: clicks and existing members are not counted as new joins. Only confirmed join events attributed to this campaign's unique invite count toward membership. Link hits may include automated preview/scanner requests. Your Telegram account needs permission to create invite links.</div></div></form></section>"""
        with db() as c:
            intro_template = c.execute("SELECT value FROM tracker_settings WHERE key='start_intro_template'").fetchone()["value"]
            outro_template = c.execute("SELECT value FROM tracker_settings WHERE key='success_outro_template'").fetchone()["value"]
        template_form = f"""<section class='card'><h2>Separate Intro &amp; Outro Templates</h2><p>These are additional messages sent to the campaign destination. Existing tracker behavior and target closure remain in place.</p><form method='post' action='/campaigns/templates'><label for='start_intro_template'>Campaign Start Intro Template</label><textarea id='start_intro_template' name='start_intro_template' rows='6' style='width:100%;background:#0a1224;color:var(--text);padding:12px;border:1px solid var(--line);border-radius:11px'>{html.escape(intro_template)}</textarea><label for='success_outro_template'>Mission Successful Outro Template</label><textarea id='success_outro_template' name='success_outro_template' rows='6' style='width:100%;background:#0a1224;color:var(--text);padding:12px;border:1px solid var(--line);border-radius:11px'>{html.escape(outro_template)}</textarea><p>Placeholders: {{campaign_name}}, {{target}}, {{current_joins}}, {{started_at}}, {{completed_at}}</p><button type='submit'>Save Caption Templates</button></form></section>"""
        body = "<header><div class='hero-copy'><p class='eyebrow'>Telegram growth workspace</p><h1><span class='brand-mark'>CT</span>Campaign Tracker</h1><p>One dashboard for every bio link, verified join and campaign milestone.</p></div><div><form method='post' action='/logout'><button type='submit' class='secondary'>Sign out ↗</button></form><p class='target-note'>● Dashboard · timestamps shown in Indian Standard Time</p></div></header>" + create_form + template_form + ("".join(cards) if cards else "<section class='card empty-state'><div class='empty-icon'>✦</div><h2>Your first campaign starts here</h2><p>Create a campaign above to generate a unique tracking link and see verified joins in this dashboard.</p></section>")
        return HTMLResponse(_page("Campaign Tracker", body), headers={"Cache-Control":"no-store"})

    @app.post("/campaigns/templates")
    async def save_campaign_templates(request: Request, start_intro_template: str = Form(""), success_outro_template: str = Form("")):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        with db() as c:
            c.execute("INSERT INTO tracker_settings(key,value) VALUES('start_intro_template',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (start_intro_template[:10000],))
            c.execute("INSERT INTO tracker_settings(key,value) VALUES('success_outro_template',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (success_outro_template[:10000],))
        return RedirectResponse("/", status_code=303)

    @app.post("/campaigns/{campaign_id}/delete")
    async def delete_campaign(request: Request, campaign_id: int):
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        with db() as c:
            c.execute("UPDATE campaigns SET status='archived' WHERE id=? AND status!='archived'", (campaign_id,))
            exists = c.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Campaign not found")
        # Preserve records and history; close its invite on a best-effort basis too.
        asyncio.create_task(revoke_campaign(campaign_id))
        return RedirectResponse("/", status_code=303)

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
        asyncio.create_task(send_campaign_caption(campaign_id, "start"))
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
            active = c.execute("SELECT COUNT(*) n FROM members WHERE campaign_id=? AND is_member=1", (campaign_id,)).fetchone()['n']
            if active >= camp['target']:
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
                check_target_ids = set()
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
                            # Check after this transaction: target means CURRENT active members.
                            check_target_ids.add(int(matched['id']))
                        else:
                            # Rejoins/leaves of already-attributed members are logged, but unrelated joins never enter campaign totals.
                            known = c.execute("SELECT campaign_id FROM members WHERE user_id=? AND campaign_id IN (SELECT id FROM campaigns WHERE destination_id=?)", (uid, chat_id)).fetchall()
                            for row in known:
                                c.execute("UPDATE members SET is_member=1,left_at=NULL,last_join_at=?,join_count=join_count+1,username=?,first_name=? WHERE campaign_id=? AND user_id=?", (timestamp, username, first_name, row['campaign_id'], uid))
                                c.execute("INSERT INTO events(campaign_id,user_id,username,event_type,occurred_at,details) VALUES(?,?,?,?,?,?)", (row['campaign_id'], uid, username, 'rejoined', timestamp, 'Rejoin observed; original campaign attribution retained'))
                                check_target_ids.add(int(row['campaign_id']))
                    elif event.user_left or event.user_kicked:
                        known = c.execute("SELECT campaign_id FROM members WHERE user_id=? AND campaign_id IN (SELECT id FROM campaigns WHERE destination_id=?)", (uid, chat_id)).fetchall()
                        for row in known:
                            c.execute("UPDATE members SET is_member=0,left_at=? WHERE campaign_id=? AND user_id=?", (timestamp, row['campaign_id'], uid))
                            c.execute("INSERT INTO events(campaign_id,user_id,username,event_type,occurred_at,details) VALUES(?,?,?,?,?,?)", (row['campaign_id'], uid, username, 'left' if event.user_left else 'kicked', timestamp, None))
                for cid in check_target_ids:
                    if finish_if_target_reached(cid):
                        revoke_ids.append(cid)
                for cid in revoke_ids:
                    asyncio.create_task(close_campaign_and_send_outro(cid))
            except Exception as exc:
                print(f"Tracker membership update error: {type(exc).__name__}: {exc}")
