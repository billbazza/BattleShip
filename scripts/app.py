"""
Battleship — Local Dashboard
Run: python3 scripts/app.py
Open: http://localhost:5100
"""
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for, jsonify

VAULT_ROOT   = Path(__file__).parent.parent
CLIENTS_DIR  = VAULT_ROOT / "clients"
STATE_FILE   = CLIENTS_DIR / "state.json"
TALLY_QUEUE  = CLIENTS_DIR / "tally-queue"
PIPELINE     = VAULT_ROOT / "scripts" / "battleship_pipeline.py"
PYTHON       = sys.executable

app = Flask(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"clients": {}}

def read_file(folder: str, filename: str) -> str:
    p = CLIENTS_DIR / folder / filename
    return p.read_text() if p.exists() else ""

def run_pipeline(*args) -> str:
    result = subprocess.run(
        [PYTHON, str(PIPELINE)] + list(args),
        capture_output=True, text=True, cwd=str(VAULT_ROOT)
    )
    return (result.stdout + result.stderr).strip()

STATUS_COLOUR = {
    "diagnosed": "#e8a020",
    "active":    "#2a9d4e",
}

ENV_FILE  = Path.home() / ".battleship.env"
LOG_FILE  = VAULT_ROOT / "logs" / "pipeline.log"
CRON_TAG  = "battleship_pipeline"

def _read_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out

def _ok(msg=""):   return {"status": "ok",   "label": msg or "OK"}
def _warn(msg=""):  return {"status": "warn", "label": msg or "—"}
def _err(msg=""):   return {"status": "err",  "label": msg or "Error"}

def get_system_status() -> dict:
    env  = _read_env()
    stat = {}

    # Flask — always up if we're serving this page
    stat["flask"] = _ok("Running on :5100")

    # Cloudflare tunnel process
    try:
        r = subprocess.run(["pgrep", "-f", "cloudflared tunnel run"],
                           capture_output=True)
        stat["tunnel"] = _ok("Connected") if r.returncode == 0 else _err("Not running")
    except Exception:
        stat["tunnel"] = _warn("Unknown")

    # Webhook DNS
    try:
        socket.getaddrinfo("webhook.battleshipreset.com", 443, timeout=3)
        stat["dns"] = _ok("webhook.battleshipreset.com")
    except Exception:
        stat["dns"] = _warn("Propagating…")

    # Cron job
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if "battleship_pipeline" in cron.stdout or "battleship" in cron.stdout:
            # Extract schedule
            line = next((l for l in cron.stdout.splitlines() if "battleship" in l), "")
            parts = line.split()
            schedule = " ".join(parts[:5]) if len(parts) >= 5 else "set"
            stat["cron"] = _ok(schedule)
        else:
            stat["cron"] = _warn("Not scheduled")
    except Exception:
        stat["cron"] = _warn("Not scheduled")

    # Claude API
    stat["claude"] = _ok("Key set") if env.get("ANTHROPIC_KEY") else _err("No key")

    # Stripe
    stat["stripe"] = _ok("Live key") if (env.get("STRIPE_KEY") or "").startswith("sk_live") else \
                     _warn("Test/missing")

    # SMTP
    stat["smtp"] = _ok(env.get("SMTP_USER", "")) if env.get("SMTP_PASS") else _err("No credentials")

    # IMAP (inbound email)
    stat["imap"] = _ok("Configured") if env.get("IMAP_PASS") else _warn("Not set")

    # Google Sheets
    creds_path = Path(env.get("GSHEETS_CREDS", "~/.battleship-gsheets.json")).expanduser()
    stat["gsheets"] = _ok("Creds found") if creds_path.exists() else _warn("No creds")

    # Pipeline last run
    if LOG_FILE.exists():
        mtime    = LOG_FILE.stat().st_mtime
        age_secs = (datetime.now(timezone.utc).timestamp() - mtime)
        if age_secs < 3600:
            label = f"{int(age_secs // 60)}m ago"
        elif age_secs < 86400:
            label = f"{int(age_secs // 3600)}h ago"
        else:
            label = f"{int(age_secs // 86400)}d ago"
        stat["pipeline"] = _ok(label)
    else:
        stat["pipeline"] = _warn("Never run")

    # Queued Tally submissions
    queued = len(list(TALLY_QUEUE.glob("submission-*.json"))) if TALLY_QUEUE.exists() else 0
    stat["queue"] = _ok(f"{queued} queued") if queued == 0 else _warn(f"{queued} waiting")

    return stat

# ── Templates ─────────────────────────────────────────────────────────────────

BASE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Battleship — {{ title }}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
           background: #f2efe8; color: #1a1a1a; font-size: 15px; }
    a { color: #c41e3a; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .topbar { background: #0a0a0a; padding: 14px 32px; display: flex;
              align-items: center; justify-content: space-between; }
    .topbar-brand { font-family: Georgia, serif; font-size: 20px;
                    letter-spacing: 3px; text-transform: uppercase; color: #fff; }
    .topbar-brand span { color: #c41e3a; }
    .topbar-nav a { color: #888; font-size: 13px; margin-left: 20px; }
    .topbar-nav a:hover { color: #fff; text-decoration: none; }

    .container { max-width: 1000px; margin: 0 auto; padding: 32px 24px; }
    h1 { font-family: Georgia, serif; font-weight: normal; font-size: 26px;
         margin-bottom: 24px; color: #0a0a0a; }
    h2 { font-family: Georgia, serif; font-weight: normal; font-size: 19px;
         margin: 28px 0 12px; color: #0a0a0a; }

    .card { background: #fff; border-radius: 4px; padding: 24px;
            margin-bottom: 20px; border: 1px solid #e0dbd2; }

    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 11px; text-transform: uppercase;
         letter-spacing: 1.5px; color: #999; padding: 0 12px 10px 0;
         border-bottom: 2px solid #e0dbd2; }
    td { padding: 12px 12px 12px 0; border-bottom: 1px solid #f0ece4;
         vertical-align: top; }
    tr:last-child td { border-bottom: none; }

    .badge { display: inline-block; padding: 3px 10px; border-radius: 20px;
             font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }
    .badge-diagnosed { background: #fdf0d5; color: #b87000; }
    .badge-active    { background: #d4f0de; color: #1a7a3a; }
    .badge-complete  { background: #d0e8ff; color: #1a4a7a; }
    .badge-silent    { background: #eeeeee; color: #666666; }
    .badge-refunded  { background: #fde8e8; color: #a02020; }
    .badge-archived  { background: #e8e8e8; color: #888888; }
    .badge-unknown   { background: #eee;    color: #666; }
    .danger-zone { border-top: 1px solid #f0ece4; margin-top: 20px; padding-top: 20px; }
    .danger-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
                    color: #ccc; margin-bottom: 10px; }
    .btn-danger  { background: transparent; color: #c41e3a;
                   border: 1px solid #e0c0c0; }
    .btn-danger:hover { background: #c41e3a; color: #fff; border-color: #c41e3a; }

    .btn { display: inline-block; padding: 9px 20px; border-radius: 3px;
           font-size: 13px; font-weight: 600; cursor: pointer; border: none;
           letter-spacing: 0.3px; }
    .btn-primary  { background: #c41e3a; color: #fff; }
    .btn-secondary{ background: #0a0a0a; color: #fff; }
    .btn-ghost    { background: transparent; color: #c41e3a;
                    border: 1px solid #c41e3a; }
    .btn:hover { opacity: 0.85; }
    form { display: inline; }

    .pre { font-family: 'SF Mono', 'Menlo', monospace; font-size: 13px;
           background: #f8f6f1; padding: 16px; border-radius: 3px;
           white-space: pre-wrap; word-break: break-word;
           border: 1px solid #e8e3da; line-height: 1.6; }
    .output-box { background: #0a0a0a; color: #a8e6a8; font-family: monospace;
                  font-size: 13px; padding: 18px; border-radius: 4px;
                  white-space: pre-wrap; line-height: 1.5; }

    .meta-row { display: flex; gap: 32px; flex-wrap: wrap; margin-bottom: 16px; }
    .meta-item label { font-size: 11px; text-transform: uppercase;
                       letter-spacing: 1.5px; color: #999; display: block;
                       margin-bottom: 4px; }
    .meta-item value { font-size: 15px; color: #1a1a1a; }

    .action-bar { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }

    .note-form input[type=text] { width: 340px; padding: 9px 12px;
      border: 1px solid #ccc; border-radius: 3px; font-size: 14px; }
    .week-num { font-size: 28px; font-weight: 700; color: #c41e3a; }
    .alert { padding: 12px 16px; border-radius: 3px; margin-bottom: 20px;
             background: #d4f0de; color: #1a5c2a; font-size: 14px; }

    /* ── Status Panel ── */
    .status-panel { background: #0f0f0f; border-radius: 4px; padding: 24px 28px;
                    margin-bottom: 32px; border: 1px solid #222; }
    .status-panel-header { display: flex; align-items: center;
                           justify-content: space-between; margin-bottom: 20px; }
    .status-panel-title { font-family: Georgia, serif; font-size: 11px;
                          text-transform: uppercase; letter-spacing: 3px; color: #555; }
    .status-refresh { font-size: 11px; color: #444; cursor: pointer; }
    .status-refresh:hover { color: #888; }
    .status-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
    .status-item { background: #1a1a1a; border-radius: 3px; padding: 12px 14px;
                   border: 1px solid #2a2a2a; }
    .status-item-name { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
                        color: #555; margin-bottom: 6px; }
    .status-item-val { display: flex; align-items: center; gap: 7px; }
    .status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .dot-ok   { background: #2a9d4e; box-shadow: 0 0 5px #2a9d4e88; }
    .dot-warn { background: #e8a020; box-shadow: 0 0 5px #e8a02088; }
    .dot-err  { background: #c41e3a; box-shadow: 0 0 5px #c41e3a88; }
    .status-item-label { font-size: 12px; color: #aaa; white-space: nowrap;
                         overflow: hidden; text-overflow: ellipsis; }
    .status-divider { border: none; border-top: 1px solid #1e1e1e; margin: 18px 0; }
    .status-meta { display: flex; gap: 32px; }
    .status-meta-item { font-size: 11px; color: #444; }
    .status-meta-item strong { color: #777; font-weight: 600; }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-brand">Battle<span>ship</span></div>
    <nav class="topbar-nav">
      <a href="/">Dashboard</a>
      <a href="/run">Run Pipeline</a>
    </nav>
  </div>
  <div class="container">
    {% if flash %}<div class="alert">{{ flash }}</div>{% endif %}
    {% block content %}{% endblock %}
  </div>
</body>
</html>"""

DASHBOARD = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}

<div class="status-panel">
  <div class="status-panel-header">
    <span class="status-panel-title">System Status</span>
    <span class="status-refresh" onclick="location.reload()">↻ Refresh</span>
  </div>
  <div class="status-grid">
    {% for key, item in status.items() %}
    <div class="status-item">
      <div class="status-item-name">{{ key }}</div>
      <div class="status-item-val">
        <span class="status-dot dot-{{ item.status }}"></span>
        <span class="status-item-label" title="{{ item.label }}">{{ item.label }}</span>
      </div>
    </div>
    {% endfor %}
  </div>
  <hr class="status-divider">
  <div class="status-meta">
    <span class="status-meta-item">Active clients: <strong>{{ active_count }}</strong></span>
    <span class="status-meta-item">Diagnosed: <strong>{{ diagnosed_count }}</strong></span>
    <span class="status-meta-item">Pipeline: <strong>{{ status.pipeline.label }}</strong></span>
    <span class="status-meta-item">Queued: <strong>{{ status.queue.label }}</strong></span>
    <span class="status-meta-item" style="margin-left:auto;color:#333">
      <a href="https://battleshipreset.com" target="_blank" style="color:#444;font-size:11px">battleshipreset.com ↗</a>
    </span>
  </div>
</div>

<h1>Clients</h1>

{% if clients %}
<div class="card">
  <table>
    <thead>
      <tr>
        <th>Account</th>
        <th>Name</th>
        <th>Email</th>
        <th>Status</th>
        <th>Week</th>
        <th>Enrolled</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for acct, cs in clients %}
      <tr>
        <td><code>{{ acct }}</code></td>
        <td><strong>{{ cs.name }}</strong>{% if cs.get('complimentary') %} <span style="font-size:11px;color:#888">(comp)</span>{% endif %}{% if cs.get('phase2_requested') %} <span style="font-size:11px;color:#c41e3a;font-weight:700">★ P2</span>{% endif %}</td>
        <td style="color:#666">{{ cs.email }}</td>
        <td>
          <span class="badge badge-{{ cs.status }}">{{ cs.status }}</span>
        </td>
        <td><span class="week-num" style="font-size:18px">{{ cs.get('current_week', 0) }}</span></td>
        <td style="color:#999;font-size:13px">{{ cs.get('enrolled_date') or '—' }}</td>
        <td><a href="/client/{{ acct }}" class="btn btn-ghost" style="padding:5px 14px;font-size:12px">View →</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% else %}
<div class="card" style="color:#888;text-align:center;padding:48px">
  No clients yet. Run the pipeline to process new intakes.
</div>
{% endif %}

<div style="margin-top:24px">
  <a href="/run" class="btn btn-secondary">Run Pipeline Now</a>
</div>
{% endblock %}""")

CLIENT_PAGE = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<p style="margin-bottom:20px"><a href="/">← Dashboard</a></p>

<h1>{{ cs.name }}</h1>

<div class="card">
  <div class="meta-row">
    <div class="meta-item"><label>Account</label><value><code>{{ acct }}</code></value></div>
    <div class="meta-item"><label>Status</label><value><span class="badge badge-{{ cs.status }}">{{ cs.status }}</span></value></div>
    <div class="meta-item"><label>Week</label><value><span class="week-num">{{ cs.get('current_week', 0) }}</span></value></div>
    <div class="meta-item"><label>Email</label><value>{{ cs.email }}</value></div>
    <div class="meta-item"><label>Enrolled</label><value>{{ cs.get('enrolled_date') or 'not yet' }}</value></div>
    {% if cs.get('complimentary') %}<div class="meta-item"><label>Plan</label><value>Complimentary</value></div>{% endif %}
    {% if cs.get('phase2_requested') %}<div class="meta-item"><label>Phase 2</label><value style="color:#c41e3a;font-weight:700">Requested ★</value></div>{% endif %}
  </div>
  {% if cs.get('challenge_goal') %}
  <div style="margin-bottom:12px;padding:12px;background:#f8f6f1;border-radius:3px;border-left:3px solid #c41e3a">
    <span style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#999">Challenge Goal</span><br>
    <span style="font-size:14px;color:#1a1a1a">{{ cs.challenge_goal }}</span>
  </div>
  {% endif %}
  <div style="font-size:13px;color:#999">Emails sent: {{ ', '.join(cs.get('emails_sent', [])) or 'none' }}</div>
</div>

<h2>Actions</h2>
<div class="card">
  <div class="action-bar">
    {% if cs.status == 'diagnosed' %}
    <form method="post" action="/action/{{ acct }}/enrol">
      <button class="btn btn-primary">Enrol (paid)</button>
    </form>
    <form method="post" action="/action/{{ acct }}/enrol_free">
      <button class="btn btn-secondary">Enrol (complimentary)</button>
    </form>
    {% endif %}
    {% if cs.status == 'active' %}
    <form method="post" action="/action/{{ acct }}/advance">
      <button class="btn btn-ghost">Advance Week →</button>
    </form>
    {% endif %}
  </div>

  <div style="margin-top:20px">
    <form method="post" action="/action/{{ acct }}/note" class="note-form" style="display:flex;gap:8px;align-items:center">
      <input type="text" name="note" placeholder="Add a coach note…" required>
      <button class="btn btn-secondary" style="white-space:nowrap">Save Note</button>
    </form>
  </div>

  <div class="danger-zone">
    <div class="danger-label">Move to</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      {% if cs.status != 'silent' %}
      <form method="post" action="/action/{{ acct }}/setstatus">
        <input type="hidden" name="new_status" value="silent">
        <button class="btn btn-ghost" style="font-size:12px;padding:6px 14px">Went silent</button>
      </form>
      {% endif %}
      {% if cs.status != 'refunded' %}
      <form method="post" action="/action/{{ acct }}/setstatus">
        <input type="hidden" name="new_status" value="refunded">
        <button class="btn btn-ghost" style="font-size:12px;padding:6px 14px">Refunded</button>
      </form>
      {% endif %}
      {% if cs.status != 'archived' %}
      <form method="post" action="/action/{{ acct }}/setstatus">
        <input type="hidden" name="new_status" value="archived">
        <button class="btn btn-ghost" style="font-size:12px;padding:6px 14px">Archive</button>
      </form>
      {% endif %}
      {% if cs.status in ('diagnosed', 'silent', 'refunded', 'archived') %}
      <span style="flex:1"></span>
      <form method="post" action="/action/{{ acct }}/delete"
            onsubmit="return confirm('Permanently remove {{ cs.name }} from state? Their files will be kept on disk.')">
        <button class="btn btn-danger" style="font-size:12px;padding:6px 14px">Delete record</button>
      </form>
      {% endif %}
    </div>
  </div>
</div>

{% if tracker %}
<h2>Progress Tracker</h2>
<div class="card">
  <div class="pre">{{ tracker }}</div>
</div>
{% else %}
<h2>Progress Tracker</h2>
<div class="card" style="color:#999">No check-ins received yet.</div>
{% endif %}

{% if plan %}
<h2>Plan</h2>
<div class="card">
  <div class="pre">{{ plan }}</div>
</div>
{% endif %}

{% if diagnosis %}
<h2>Diagnosis</h2>
<div class="card">
  <div class="pre">{{ diagnosis }}</div>
</div>
{% endif %}

{% if event_log %}
<h2>Event Log</h2>
<div class="card">
  <div class="pre">{{ event_log }}</div>
</div>
{% endif %}

{% endblock %}""")

RUN_PAGE = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<h1>Run Pipeline</h1>
<div class="card">
  <p style="margin-bottom:20px;color:#555">
    Polls Typeform for new intakes, checks Stripe for payments, sends education drips.
    This is the same as the cron job — safe to run any time.
  </p>
  <form method="post" action="/run">
    <button class="btn btn-primary">Run Now</button>
  </form>
</div>
{% if output %}
<h2>Output</h2>
<div class="output-box">{{ output }}</div>
{% endif %}
{% endblock %}""")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    state          = load_state()
    clients        = sorted(state["clients"].items(), key=lambda x: x[0])
    flash          = request.args.get("flash", "")
    active_count   = sum(1 for _, cs in clients if cs.get("status") == "active")
    diagnosed_count= sum(1 for _, cs in clients if cs.get("status") == "diagnosed")
    sys_status     = get_system_status()
    return render_template_string(DASHBOARD, title="Dashboard",
                                  clients=clients, flash=flash,
                                  status=sys_status,
                                  active_count=active_count,
                                  diagnosed_count=diagnosed_count)

@app.route("/client/<acct>")
def client_detail(acct):
    state = load_state()
    cs    = state["clients"].get(acct)
    if not cs:
        return redirect(url_for("dashboard", flash=f"Client {acct} not found"))
    flash   = request.args.get("flash", "")
    folder  = cs.get("folder", "")
    return render_template_string(
        CLIENT_PAGE,
        title=cs["name"], acct=acct, cs=cs, flash=flash,
        tracker   = read_file(folder, "progress-tracker.md"),
        plan      = read_file(folder, "plan.md"),
        diagnosis = read_file(folder, "diagnosis.md"),
        event_log = read_file(folder, "event-log.md"),
    )

@app.route("/action/<acct>/enrol", methods=["POST"])
def action_enrol(acct):
    out = run_pipeline(f"--enrol={acct}")
    return redirect(url_for("client_detail", acct=acct,
                            flash="Enrolment triggered — check email."))

@app.route("/action/<acct>/enrol_free", methods=["POST"])
def action_enrol_free(acct):
    out = run_pipeline(f"--enrol={acct}", "--free")
    return redirect(url_for("client_detail", acct=acct,
                            flash="Complimentary enrolment triggered."))

@app.route("/action/<acct>/advance", methods=["POST"])
def action_advance(acct):
    out = run_pipeline(f"--advance={acct}")
    return redirect(url_for("client_detail", acct=acct,
                            flash=f"Week advanced. {out.splitlines()[-1] if out else ''}"))

@app.route("/action/<acct>/note", methods=["POST"])
def action_note(acct):
    note = request.form.get("note", "").strip()
    if note:
        run_pipeline(f"--note={acct}", note)
    return redirect(url_for("client_detail", acct=acct,
                            flash="Note saved." if note else ""))

@app.route("/action/<acct>/setstatus", methods=["POST"])
def action_setstatus(acct):
    allowed = {"silent", "refunded", "archived", "active", "diagnosed"}
    new_status = request.form.get("new_status", "").strip()
    if new_status not in allowed:
        return redirect(url_for("client_detail", acct=acct, flash="Invalid status."))
    state = load_state()
    cs = state["clients"].get(acct)
    if not cs:
        return redirect(url_for("dashboard", flash=f"Client {acct} not found."))
    old = cs["status"]
    cs["status"] = new_status
    if cs.get("folder"):
        import json as _json
        folder_path = CLIENTS_DIR / cs["folder"]
        log_path = folder_path / "event-log.md"
        entry = f"\n**{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC** — Status changed: {old} → {new_status}\n"
        if log_path.exists():
            log_path.write_text(log_path.read_text() + entry)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    return redirect(url_for("client_detail", acct=acct,
                            flash=f"Status updated to '{new_status}'."))

@app.route("/action/<acct>/delete", methods=["POST"])
def action_delete(acct):
    state = load_state()
    cs = state["clients"].get(acct)
    if not cs:
        return redirect(url_for("dashboard", flash=f"Client {acct} not found."))
    name = cs.get("name", acct)
    # Safety: block deletion of active paying clients
    if cs.get("status") == "active" and not cs.get("complimentary"):
        return redirect(url_for("client_detail", acct=acct,
                                flash="Cannot delete an active paying client. Archive or refund first."))
    del state["clients"][acct]
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    return redirect(url_for("dashboard", flash=f"{name} removed. Files kept in clients/{cs.get('folder', acct)}/."))

def _verify_tally_signature(raw_body: bytes, header: str, secret: str) -> bool:
    """Verify Tally webhook signature: sha256=<hmac> against raw body."""
    if not secret:
        return True  # no secret configured — skip verification
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header or "")

@app.route("/tally-webhook", methods=["POST"])
def tally_webhook():
    """Receive Tally form submissions and queue them for pipeline processing."""
    try:
        raw_body = request.get_data()
        sig      = request.headers.get("tally-signature", "")
        secret   = os.environ.get("TALLY_WEBHOOK_SECRET", "")

        if secret and not _verify_tally_signature(raw_body, sig, secret):
            print("  ⛔ Tally webhook: invalid signature — rejected")
            return jsonify({"error": "invalid signature"}), 401

        payload = json.loads(raw_body) if raw_body else None
        if not payload:
            return jsonify({"error": "empty payload"}), 400

        TALLY_QUEUE.mkdir(parents=True, exist_ok=True)
        ts          = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        response_id = payload.get("data", {}).get("responseId", ts)
        filename    = TALLY_QUEUE / f"submission-{ts}-{response_id}.json"
        filename.write_text(json.dumps(payload, indent=2))
        print(f"  📥 Tally submission queued: {filename.name}")

        # Trigger pipeline immediately in background
        subprocess.Popen([PYTHON, str(PIPELINE)], cwd=str(VAULT_ROOT))
        return jsonify({"status": "queued"}), 200
    except Exception as e:
        print(f"  ❌ Tally webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def api_status():
    return jsonify(get_system_status())

@app.route("/run", methods=["GET", "POST"])
def run_pipeline_page():
    output = None
    if request.method == "POST":
        output = run_pipeline()
    return render_template_string(RUN_PAGE, title="Run Pipeline", output=output)

# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Battleship Dashboard → http://localhost:5100\n")
    app.run(host="127.0.0.1", port=5100, debug=False)
