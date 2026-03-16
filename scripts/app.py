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
import requests as _requests
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for, jsonify, Response

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills.tracker_generator import generate_tracker_for_client  # noqa: E402

VAULT_ROOT          = Path(__file__).parent.parent
CLIENTS_DIR         = VAULT_ROOT / "clients"
STATE_FILE          = CLIENTS_DIR / "state.json"
TALLY_QUEUE         = CLIENTS_DIR / "tally-queue"
PIPELINE            = VAULT_ROOT / "scripts" / "battleship_pipeline.py"
PYTHON              = sys.executable

# Business manager data paths
MARKETING_STRATEGY_FILE  = CLIENTS_DIR / "marketing_strategy.json"
SOCIAL_METRICS_FILE      = CLIENTS_DIR / "social_metrics.json"
SEO_STATE_FILE           = VAULT_ROOT / "brand" / "Marketing" / "SEO" / "seo_state.json"
TECH_BACKLOG_FILE        = VAULT_ROOT / "brand" / "Marketing" / "tech_backlog.json"
REMINDERS_FILE           = VAULT_ROOT / "brand" / "Marketing" / "reminders.json"
ROADMAP_FILE             = VAULT_ROOT / "roadmap.md"
FINANCES_FILE            = VAULT_ROOT / "finances.md"
BIZ_HISTORY_FILE         = CLIENTS_DIR / "business_metrics_history.json"
MORNING_BRIEFING_FILE    = CLIENTS_DIR / "morning_briefing.json"
PHOTO_REVIEW_FILE        = CLIENTS_DIR / "photo_review_state.json"
PHOTO_DROP_DIR           = Path("/Users/will/Desktop/Battleship-review-pics")
CONTENT_REVIEW_FILE      = CLIENTS_DIR / "content_review.json"
IDEAS_BANK_FILE          = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"

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

# ── Business Manager Helpers ──────────────────────────────────────────────────

def _load_json_safe(path: Path, default=None):
    """Load a JSON file, returning default if missing or malformed."""
    if default is None:
        default = {}
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _parse_finances_spend() -> float:
    """Parse finances.md expense table and return total spend as float (£).

    Reads only the '**Total Spend to date' line to avoid double-counting
    pricing tables and target figures elsewhere in the file.
    """
    if not FINANCES_FILE.exists():
        return 0.0
    import re
    text = FINANCES_FILE.read_text()
    # Prefer the explicit total line: **Total Spend to date: £119.47**
    m = re.search(r'\*\*Total Spend to date[^£]*£\s*([\d,]+\.?\d*)', text)
    if m:
        try:
            return round(float(m.group(1).replace(",", "")), 2)
        except ValueError:
            pass
    # Fallback: sum only the expense log table rows (| date | item | cost |)
    # Look for the section between ## Expense Log and the next ## heading
    section = re.search(r'## Expense Log(.+?)^##', text, re.S | re.M)
    if not section:
        return 0.0
    total = 0.0
    for row in section.group(1).splitlines():
        if not row.startswith('|') or row.startswith('| Date') or set(row.strip('|').strip()) <= {'-', ' '}:
            continue
        # Cost column is 3rd pipe-delimited cell
        cells = [c.strip() for c in row.split('|')]
        if len(cells) >= 4:
            cost_cell = cells[3]
            m2 = re.search(r'£\s*([\d,]+\.?\d*)', cost_cell)
            if m2:
                try:
                    total += float(m2.group(1).replace(",", ""))
                except ValueError:
                    pass
    return round(total, 2)


def _calc_mrr(state: dict) -> float:
    """Sum payment_amount for active + complete clients."""
    total = 0.0
    for cs in state.get("clients", {}).values():
        if cs.get("status") in ("active", "complete"):
            try:
                total += float(cs.get("payment_amount", 0) or 0)
            except (ValueError, TypeError):
                pass
    return round(total, 2)


def record_daily_snapshot(state: dict, strategy: dict, social_metrics: dict, pnl: dict):
    """Append today's business snapshot to business_metrics_history.json."""
    today = datetime.now().strftime("%Y-%m-%d")
    history_data = _load_json_safe(BIZ_HISTORY_FILE, {"history": []})

    # Build snapshot
    page_data = social_metrics.get("page", {})
    ig_data   = social_metrics.get("ig", {})
    ads_data  = social_metrics.get("ads", {})

    # Get most recent page/ig followers
    fb_followers = 0
    if page_data:
        latest_day = max(page_data.keys()) if page_data else None
        if latest_day:
            fb_followers = page_data[latest_day].get("followers", 0) or page_data[latest_day].get("fans", 0)
    ig_followers = 0
    if ig_data:
        latest_ig = max(ig_data.keys()) if ig_data else None
        if latest_ig:
            ig_followers = ig_data[latest_ig].get("followers_count", 0)

    ad_impressions = 0
    ad_spend = 0.0
    last_ad = strategy.get("last_ad_metrics", {})
    if last_ad:
        ad_impressions = last_ad.get("impressions", 0)
        ad_spend = float(last_ad.get("spend", 0) or 0)

    snapshot = {
        "date":           today,
        "mrr":            pnl["mrr"],
        "spend":          pnl["spend"],
        "net":            pnl["net"],
        "active_clients": pnl["active_clients"],
        "fb_followers":   fb_followers,
        "ig_followers":   ig_followers,
        "ad_impressions": ad_impressions,
        "ad_spend":       ad_spend,
    }

    # Remove any existing entry for today before appending
    history_data["history"] = [h for h in history_data.get("history", []) if h.get("date") != today]
    history_data["history"].append(snapshot)
    # Keep last 90 days
    history_data["history"] = sorted(history_data["history"], key=lambda h: h.get("date", ""))[-90:]

    try:
        BIZ_HISTORY_FILE.write_text(json.dumps(history_data, indent=2))
    except Exception:
        pass


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
    .topbar-nav a.active { color: #c41e3a; }

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
      <a href="/business">&#128202; Business Manager</a>
      <a href="/simulate">Simulator</a>
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
    <span class="status-meta-item" style="margin-left:auto;display:flex;gap:14px;align-items:center">
      <a href="https://battleshipreset.com" target="_blank" style="color:#888;font-size:11px">🌐 Website ↗</a>
      <a href="https://tally.so/r/rjK752" target="_blank" style="color:#888;font-size:11px">📋 Quiz ↗</a>
      <a href="https://www.facebook.com/people/Battleship-Reset/61574337936271/" target="_blank" style="color:#888;font-size:11px">📘 Facebook ↗</a>
      <a href="https://www.instagram.com/battleshipreset/" target="_blank" style="color:#888;font-size:11px">📸 Instagram ↗</a>
      <a href="https://buy.stripe.com/3cI6oG79qefgb1CdhwejK00" target="_blank" style="color:#888;font-size:11px">💳 Stripe ↗</a>
      <a href="https://business.google.com" target="_blank" style="color:#888;font-size:11px">📍 GBP ↗</a>
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

# ── Pipeline Simulator ────────────────────────────────────────────────────────

# Mirrors EDUCATION_DRIPS in battleship_pipeline.py + day_offset within the week
# (day 0 = Monday, day 3 = Thursday) — matches the idx==1 stagger logic in the pipeline
_SIM_DRIPS = {
    # One lesson per week. Day offset: 0=Monday. Week 8 keeps challenge (AI email, separate trigger).
    1:  [("edu_sleep",       "Week 1 bonus: sleep — the easiest win in the programme",          "education-lessons/sleep/sleep-for-fat-loss.md",                          0)],
    2:  [("edu_zone2",       "Why slow walking beats hard running — the science",               "education-lessons/exercises/zone2-walking.md",                           0)],
    3:  [("edu_8020",        "The 80/20 rule of nutrition",                                     "education-lessons/nutrition/80-20-rule.md",                              0)],
    4:  [("edu_fatloss_1",   "How to actually lose fat: getting started",                       "education-lessons/fat-loss/getting-started.md",                          0)],
    5:  [("edu_fatloss_2",   "How to actually lose fat: awareness",                             "education-lessons/fat-loss/awareness.md",                                0),
         ("edu_mfp",        "Your calorie tracking tool: MyFitnessPal — simple setup guide",   "education-lessons/Myfitnesspal/myfitnesspal-guide.md",                   3)],
    6:  [("edu_training_1",  "Time to add weights — here's what your training looks like",      "education-lessons/training/workout-overview.md",                         0)],
    7:  [("edu_gymtim",      "Gymtimidation — and why it ends at session three",                "education-lessons/training/gymtimidation.md",                            0)],
    8:  [("edu_warmup",      "The warm-up you should never skip (especially over 40)",          "education-lessons/training/warm-ups.md",                                 0),
         ("edu_challenge",   "Week 8: What's your challenge?",                                  "education-lessons/training/confirmation-challenge.md",                   0)],
    9:  [("edu_fasting",     "Why fasting is the fastest way to burn dangerous belly fat",      "education-lessons/fasting/jamnadas-fasting-visceral-fat.md",             0)],
    10: [("edu_fatloss_t",   "Why lifting beats cardio for body composition",                   "education-lessons/training/training-for-fat-loss.md",                   0)],
    11: [("edu_bws",         "The Battleship training method — and why boring works",           "education-lessons/training/bws-method.md",                              0)],
    12: [("edu_arms",        "What about arms? Why the basics come first",                      "education-lessons/training/arms-and-basics.md",                         0)],
}

# ── Programme track constants + parser (mirrors battleship_pipeline.py) ───────

_PROGRAMS_DIR = VAULT_ROOT / "11-week-programs"

_PROGRAM_FILES = {
    "beginner_bodyweight": "11-week-beginner-bodyweight-strength-training-program.md",
    "bodyweight_full":     "11-week-bodyweight-full-body-program.md",
    "bodyweight_hiit":     "11-week bodyweight HIIT (high-intensity-interval-training)-program.md",
    "resistance_bands":    "11-week-resistance-bands-full-body.md",
    "dumbbell_full_body":  "11-week-dumbbell-full-body-program.md",
    "home_complete":       "11-week-home-complete-program.md",
    "gym_beginner":        "11-week-gym-beginner-machines.md",
    "gym_intermediate":    "11-week-gym-intermediate-ppl.md",
}

_PROGRAM_LABELS = {
    "beginner_bodyweight": "Beginner Bodyweight Strength",
    "bodyweight_full":     "Bodyweight Full-Body",
    "bodyweight_hiit":     "Bodyweight HIIT",
    "resistance_bands":    "Resistance Bands Full-Body",
    "dumbbell_full_body":  "Dumbbell Full-Body",
    "home_complete":       "Home Complete (Dumbbells + Bands + Pull-Up Bar)",
    "gym_beginner":        "Gym Beginner (Machines)",
    "gym_intermediate":    "Gym Intermediate (Push / Pull / Legs)",
}

_UPGRADE_NUDGES = {
    "beginner_bodyweight": {
        4: "💡 Upgrade nudge: A resistance band (£8–15 online) unlocks pulling movements bodyweight can't do. Mention it in your next check-in and your programme switches tracks automatically.",
        7: "💡 Upgrade nudge: You're ready for more resistance. Bands or light dumbbells would unlock the next stage.",
    },
    "bodyweight_full": {
        4: "💡 Upgrade nudge: A pair of fixed dumbbells — even 10kg + 15kg from Decathlon (£25–35) — would let us load these movements and accelerate fat loss. Get them before next check-in.",
        6: "💡 Upgrade nudge: If a gym is at all accessible, now is the time. You've built the base. Most gyms are £20–35/month.",
    },
    "bodyweight_hiit": {
        4: "💡 Upgrade nudge: HIIT conditions your engine well. A pair of dumbbells is the next step for building muscle alongside fat loss.",
    },
    "resistance_bands": {
        4: "💡 Upgrade nudge: The bands are working. Dumbbells (£25–35 fixed set) would let us load squats, rows, and presses with real weight.",
    },
    "dumbbell_full_body": {
        6: "💡 Upgrade nudge: If a gym is viable (£20–25/month), joining before Week 7 unlocks a barbell, cables, and machines — Push/Pull/Legs split from here.",
    },
    "home_complete": {
        6: "💡 Upgrade nudge: Your home programme has been solid. A gym from Week 7 moves you to Push/Pull/Legs — the format that builds the most muscle per session.",
    },
}

_GYM_TRACKS = {"gym_beginner", "gym_intermediate"}
_META_COLS_SIM = {
    "Week", "Sets × Reps", "Sets × Goal", "Sets", "Frequency",
    "Circuit Structure (per round)", "Work / Rest per Exercise",
    "Rounds per Session", "Total Time (approx.)",
    "Notes / Weight Used", "Notes / How It Felt", "Notes / Modifications",
    "Notes / Variation Used", "Notes / Weight", "Notes",
    "Key Progression / Focus",
}


def _sim_parse_table_lines(lines: list) -> tuple:
    if len(lines) < 3:
        return [], []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= len(headers):
            rows.append(dict(zip(headers, cells[:len(headers)])))
    return headers, rows


def _sim_parse_md_tables(text: str) -> list:
    results = []
    lines = text.splitlines()
    label = "Programme"
    buf = []
    in_tbl = False
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            if in_tbl and buf:
                hdrs, rows = _sim_parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
                buf, in_tbl = [], False
            label = s.lstrip("#").strip()
        elif s.startswith("**") and any(w in s for w in ("Tracker", "Day", "Session", "Programme")):
            if in_tbl and buf:
                hdrs, rows = _sim_parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
                buf, in_tbl = [], False
            label = s.strip("*").strip()
        if s.startswith("|"):
            in_tbl = True
            buf.append(s)
        elif in_tbl:
            if buf:
                hdrs, rows = _sim_parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
            buf, in_tbl = [], False
    if in_tbl and buf:
        hdrs, rows = _sim_parse_table_lines(buf)
        if hdrs and rows:
            results.append((label, hdrs, rows))
    return results


def _sim_week_row(rows: list, week: int) -> dict:
    for row in rows:
        val = row.get("Week", row.get(list(row.keys())[0], ""))
        try:
            if int(str(val).strip()) == week:
                return row
        except (ValueError, TypeError):
            continue
    return {}


def _sim_format_row(label: str, headers: list, row: dict, multi: bool) -> str:
    lines = []
    if multi:
        lines.append(f"{label}:")
    for k in ("Sets × Reps", "Sets × Goal", "Sets"):
        if row.get(k):
            lines.append(f"  Volume: {row[k]}")
            break
    for k in ("Circuit Structure (per round)", "Work / Rest per Exercise",
              "Rounds per Session", "Total Time (approx.)"):
        if row.get(k) and row[k] not in ("", "—"):
            lines.append(f"  {k}: {row[k]}")
    for k, v in row.items():
        if k not in _META_COLS_SIM and v and v.strip() not in ("", "—", "-"):
            lines.append(f"  • {k}: {v}")
    for k in ("Key Progression / Focus", "Notes / Weight Used", "Notes / How It Felt",
              "Notes / Modifications", "Notes / Variation Used", "Notes"):
        if row.get(k) and row[k].strip() not in ("", "—"):
            lines.append(f"  → {row[k]}")
            break
    return "\n".join(lines)


def _sim_extract_program_week(track: str, week: int) -> str:
    filename = _PROGRAM_FILES.get(track, "")
    if not filename:
        return ""
    filepath = _PROGRAMS_DIR / filename
    if not filepath.exists():
        return ""
    week = max(1, min(week, 11))
    tables = _sim_parse_md_tables(filepath.read_text())
    if not tables:
        return ""
    multi = len(tables) > 1
    parts = []
    for label, headers, rows in tables:
        row = _sim_week_row(rows, week)
        if row:
            parts.append(_sim_format_row(label, headers, row, multi))
    return "\n\n".join(parts)


def _sim_week_events(week: int, track: str = "dumbbell_full_body") -> list:
    """Return ordered list of pipeline events for a given week (read-only, no state changes)."""
    events = []
    track_label = _PROGRAM_LABELS.get(track, track)
    is_gym_track = track in _GYM_TRACKS

    if week == 0:
        events.append({
            "type": "intake", "day": 0,
            "subject": "Intake form submitted",
            "preview": "Client fills in Tally form → webhook fires to webhook.battleshipreset.com → submission queued.",
            "content": "Tally → POST /tally-webhook → submission-*.json saved\nTrigger: immediate, then cron picks up within 15min\n\nfunction: process_tally_queue()",
            "function": "process_tally_queue()",
        })
        events.append({
            "type": "ai_email", "day": 0,
            "subject": "Your Battleship Diagnosis, [Name]",
            "preview": "Claude generates a personalised diagnosis from intake data — risk flags, calorie target, injuries, programme overview.",
            "content": "Claude-generated from intake answers.\n\nIncludes:\n• Weight/height analysis\n• Sleep & stress risk flags\n• Injury notes (modified movement suggestions)\n• Calorie target = TDEE × 0.8 (individual calc)\n• 12-week programme overview\n• Link to book a call (optional)\n\nfunction: generate_diagnosis() → email_diagnosis()",
            "function": "process_new_intake() → email_diagnosis()",
        })
        return events

    if week == 1:
        events.append({
            "type": "email", "day": 0,
            "subject": "Welcome to Battleship, [Name] — here's your plan",
            "preview": "Onboarding email sent when client pays via Stripe (or manually enrolled). Week 1 is walking only — no strength work yet.",
            "content": "Triggered by: Stripe webhook payment OR manual --enrol flag\n\nIncludes:\n• Link to personalised Notion plan page\n• Workout tracker URL (webhook.battleshipreset.com/tracker/BSR-XXXX)\n  → Client saves to phone home screen as PWA\n  → Shows exercises, per-set logging, how-to videos, history\n• Week 1 instructions: walk every day (Zone 2, 30 min min)\n• Check-in form link — they submit at end of week\n\nfunction: enrol_client() → email_onboarding()",
            "function": "enrol_client() → email_onboarding()",
        })
        events.append({
            "type": "checkin", "day": 6,
            "subject": "Week 1 check-in — how did it go, [Name]?",
            "preview": f"Client submits Week 1 data. Pipeline selects programme track from equipment tags → assigns: {track_label}. Adaptive walking/habit plan built from actual step count.",
            "content": f"Client submits Google Form check-in.\n\nOn receipt (_process_single_checkin, week==1):\n  1. _generate_adaptive_plan() called:\n     • select_program_track() → assigns track: {track} ({track_label})\n     • Sets starting walk target from ACTUAL steps (not ideal)\n     • Push-up challenge begins Week 2\n     • Walking: simple +20% per week progression\n     • gym_track flagged: {'yes — gym gate active from Week 3' if is_gym_track else 'no'}\n  2. Saves new plan.md (replaces intake plan)\n  3. Sends Week 1 coach message with Week 2 targets\n\nfunction: _process_single_checkin() → _generate_adaptive_plan() → select_program_track()",
            "function": "_generate_adaptive_plan() → select_program_track()",
        })
        # Track assignment card
        events.append({
            "type": "track", "day": 6,
            "subject": f"Programme track assigned: {track_label}",
            "preview": f"Track selected from equipment tags at Week 1 check-in. Programme file loaded: {_PROGRAM_FILES.get(track, 'N/A')}",
            "content": f"Track: {track}\nLabel: {track_label}\nFile: {_PROGRAM_FILES.get(track, 'N/A')}\n\nThe programme file is the source of truth for all strength sessions Weeks 2–11.\nClaude wraps each week's session block in a coach message — it does NOT generate the exercises.\n\nUpgrades: detected automatically from check-in text (equipment keywords + acquisition verbs)\nAuto-graduation: {'gym_beginner → gym_intermediate at Week 8' if track == 'gym_beginner' else 'N/A for this track'}\n\nfunction: select_program_track() → state[program_track]",
            "function": "select_program_track()",
        })

    # Education drips for this week
    for (key, subject, filepath, day_offset) in _SIM_DRIPS.get(week, []):
        content_path = VAULT_ROOT / filepath
        if content_path.exists():
            raw = content_path.read_text()
            preview = " ".join(raw.split())[:300] + ("…" if len(raw) > 300 else "")
            content = raw
        else:
            preview = f"[Content file not found: {filepath}]"
            content = preview
        events.append({
            "type": "education", "day": day_offset,
            "subject": subject,
            "preview": preview,
            "content": content,
            "function": "send_education_drips()",
            "key": key,
        })

    # Weekly check-in request (every week 2+; week 1 check-in is built in the week 1 block above)
    if week >= 2:
        gym_note = ""
        if week == 3 and is_gym_track:
            gym_note = f"\n\nGYM GATE (active — track: {track}):\n  On receipt, _infer_gym_attendance() scans check-in text for gym signals.\n  If NOT found → _send_gym_pivot() fires instead of normal coach message.\n  Pivot: warm email + home bodyweight session this week + 'join anytime, just reply'"
        elif week == 3:
            gym_note = "\n\n(No gym gate — client is on home/bodyweight track)"
        events.append({
            "type": "checkin", "day": 0,
            "subject": f"Week {week} check-in — how's it going, [Name]?",
            "preview": f"Client submits check-in. Session block for Week {week} ({track_label}) appended to coach message.{' ⚠️ Gym gate active this week.' if week == 3 and is_gym_track else ''}",
            "content": f"Sent by: send_weekly_checkin_requests()\nCondition: last_checkin_request null OR >6 days ago\n\nOn receipt:\n  1. detect_equipment_upgrade() scans check-in for new equipment signals\n  2. Extract Week {min(week, 11)} session from programme file → appended to email\n  3. Claude generates tracker update + coach message (150–250 words)\n  4. Coach message ALWAYS closes with Week {week + 1} specific targets\n  5. Email sent to client, Notion page updated\n  current_week: {week} → {week + 1}{gym_note}",
            "function": "send_weekly_checkin_requests() → _process_single_checkin()",
        })

    # Session block for weeks 2–12 (from programme file)
    if week >= 2 and track:
        session_content = _sim_extract_program_week(track, week)
        if session_content:
            events.append({
                "type": "session", "day": 0,
                "subject": f"Week {min(week, 11)} sessions — {track_label}",
                "preview": session_content[:200] + ("…" if len(session_content) > 200 else ""),
                "content": f"Appended to coach message after check-in response.\n\nTrack: {track}\nSource file: {_PROGRAM_FILES.get(track, 'N/A')}\n\n---\n{session_content}",
                "function": "extract_program_week()",
            })

    # Upgrade nudge (appended to email at specific weeks)
    nudge = _UPGRADE_NUDGES.get(track, {}).get(week, "")
    if nudge:
        events.append({
            "type": "upgrade", "day": 0,
            "subject": f"Upgrade nudge — Week {week}",
            "preview": nudge[:180] + ("…" if len(nudge) > 180 else ""),
            "content": f"Appended to coach email at end of Week {week} check-in response.\n\nTrack: {track} ({track_label})\n\n---\n{nudge}",
            "function": "get_upgrade_nudge()",
        })

    # Auto-graduation gym_beginner → gym_intermediate at Week 8
    if week == 8 and track == "gym_beginner":
        events.append({
            "type": "upgrade", "day": 6,
            "subject": "Auto-graduation: Gym Beginner → Gym Intermediate (PPL)",
            "preview": "Week 8 check-in triggers automatic track upgrade from machine-based programme to Push/Pull/Legs split.",
            "content": "Trigger: week >= 8 AND track == 'gym_beginner'\n\nPipeline:\n  1. send_track_upgrade_email() called\n  2. Claude generates transition email:\n     • Celebrates machines foundation built\n     • Explains PPL split (Push/Pull/Legs)\n     • Sets expectations: heavier, 3 focused days\n  3. state[program_track] updated to 'gym_intermediate'\n  4. Week 8+ check-ins now load gym_intermediate programme file\n\nNew file: 11-week-gym-intermediate-ppl.md\n\nfunction: send_track_upgrade_email() → detect_equipment_upgrade() auto-path",
            "function": "send_track_upgrade_email()",
        })

    # Week 8: challenge email is AI-generated
    if week == 8:
        for ev in events:
            if ev.get("key") == "edu_challenge":
                ev["type"] = "ai_email"
                ev["preview"] = "Claude writes a personalised challenge prompt based on client's goals and Week 8 progress. Asks them to name one ambitious target."
                ev["content"] = "Claude-generated using:\n• Client intake tags (goal, constraints, risk flags)\n• Progress tracker entries\n• Current week plan content\n\nPrompts client to name a specific challenge (event, goal, milestone).\nTheir reply is stored as challenge_goal in state.\n\nfunction: send_education_drips() → CHALLENGE_PROMPT → Claude API"

    # Week 12: personalised close + Phase 2 pitch
    if week == 12:
        events.append({
            "type": "ai_email", "day": 0,
            "subject": "12 weeks. What comes next, [Name]?",
            "preview": "Claude writes a personalised end-of-programme letter reviewing their journey, acknowledging wins, and making the Phase 2 offer.",
            "content": "Claude-generated using full client history:\n• Original intake data\n• All check-in responses\n• Challenge goal (if set)\n• Progress tracker\n\nCovers:\n• Journey reflection — what changed\n• Acknowledgement of specific wins\n• Phase 2 offer: £79/month, no minimum term\n  – Weekly check-ins continue\n  – Strength progression tracked\n  – Plan adjusted monthly\n  – Event/race prep + debrief\n• Direct reply CTA: 'Just reply I'm in'\n\nfunction: send_week12_close()",
            "function": "send_week12_close()",
        })

    if week == 13:
        events.append({
            "type": "checkin", "day": 0,
            "subject": "Phase 2 — client replied 'I'm in'",
            "preview": "Client replies to Week 12 close. Pipeline detects Phase 2 keywords and flags for manual action.",
            "content": "Trigger: inbound email reply to Week 12 close\nDetection: phase2_keywords match in process_inbound_emails()\n\nPipeline sets: cs['phase2_requested'] = True\nDashboard shows ★ P2 badge on client\n\nManual steps (Will):\n• Set up Stripe subscription (£79/month)\n• Continue weekly check-ins\n• Create new Notion plan page (Phase 2)\n• Reply to confirm start date\n\nfunction: process_inbound_emails()",
            "function": "process_inbound_emails() → phase2 flag",
        })

    return sorted(events, key=lambda e: (e["day"], e["type"]))


SIMULATOR_PAGE = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<h1>Pipeline Simulator</h1>
<p style="color:#666;margin-bottom:28px;font-size:14px;line-height:1.6">
  Preview every email, trigger, and timing in the 12-week client journey.<br>
  <strong style="color:#0a0a0a">Nothing is sent. No state is changed.</strong> Virtual client only.
</p>

<div class="card" style="padding:18px 20px;margin-bottom:12px">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#999;margin-bottom:10px">Programme track</div>
  <div style="display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#bbb;width:90px;flex-shrink:0">Bodyweight</span>
      <button onclick="selectTrack('beginner_bodyweight')" id="track-beginner_bodyweight" class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Beginner</button>
      <button onclick="selectTrack('bodyweight_full')"     id="track-bodyweight_full"     class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Full-Body</button>
      <button onclick="selectTrack('bodyweight_hiit')"     id="track-bodyweight_hiit"     class="btn btn-ghost" style="padding:5px 12px;font-size:11px">HIIT</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#bbb;width:90px;flex-shrink:0">Home kit</span>
      <button onclick="selectTrack('resistance_bands')"   id="track-resistance_bands"   class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Bands</button>
      <button onclick="selectTrack('dumbbell_full_body')" id="track-dumbbell_full_body" class="btn btn-primary" style="padding:5px 12px;font-size:11px">Dumbbells</button>
      <button onclick="selectTrack('home_complete')"      id="track-home_complete"      class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Complete (DB+Bands+Bar)</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#bbb;width:90px;flex-shrink:0">Gym</span>
      <button onclick="selectTrack('gym_beginner')"      id="track-gym_beginner"      class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Beginner (Machines)</button>
      <button onclick="selectTrack('gym_intermediate')"  id="track-gym_intermediate"  class="btn btn-ghost" style="padding:5px 12px;font-size:11px">Intermediate (PPL)</button>
    </div>
  </div>
  <div id="track-label" style="margin-top:10px;font-size:12px;color:#888">Track: <strong style="color:#333">Dumbbell Full-Body</strong></div>
</div>

<div class="card" style="padding:18px 20px;margin-bottom:20px">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#999;margin-bottom:12px">Select stage</div>
  <div id="week-pills" style="display:flex;flex-wrap:wrap;gap:7px">
    <button onclick="selectWeek(0)"  id="pill-0"  class="btn btn-ghost" style="padding:7px 14px;font-size:12px;font-weight:700">Intake</button>
    {% for w in range(1, 13) %}
    <button onclick="selectWeek({{ w }})" id="pill-{{ w }}" class="btn btn-ghost" style="padding:7px 14px;font-size:12px;font-weight:700">Wk {{ w }}</button>
    {% endfor %}
    <button onclick="selectWeek(13)" id="pill-13" class="btn btn-ghost" style="padding:7px 14px;font-size:12px;font-weight:700;opacity:0.6">Phase 2 ↗</button>
  </div>
</div>

<div id="sim-timeline" style="display:none;margin-bottom:20px">
  <div class="card" style="padding:14px 20px;background:#0f0f0f;border-color:#222">
    <div style="display:flex;align-items:center;gap:16px;overflow-x:auto;padding-bottom:4px">
      <span id="tl-label" style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#555;white-space:nowrap">Journey</span>
      <div style="display:flex;align-items:center;gap:0;flex:1;min-width:400px">
        {% for w in range(14) %}
        <div style="flex:1;height:3px;background:{% if loop.index0 == 0 %}#c41e3a{% else %}#2a2a2a{% endif %}" id="tl-seg-{{ loop.index0 }}"></div>
        {% if loop.index0 < 13 %}
        <div style="width:10px;height:10px;border-radius:50%;background:#2a2a2a;flex-shrink:0;cursor:pointer;border:2px solid #1a1a1a" id="tl-dot-{{ loop.index0 }}" onclick="selectWeek({{ loop.index0 }})"></div>
        {% endif %}
        {% endfor %}
      </div>
      <span id="tl-week-label" style="font-size:11px;color:#555;white-space:nowrap">Wk 0</span>
    </div>
  </div>
</div>

<div id="sim-output">
  <div style="color:#999;text-align:center;padding:60px;background:#fff;border-radius:4px;border:1px solid #e0dbd2">
    Select a week above to preview the pipeline events
  </div>
</div>

<style>
  .ev-card { background:#fff; border-radius:4px; border:1px solid #e0dbd2; margin-bottom:10px; overflow:hidden; }
  .ev-header { padding:16px 18px; display:flex; align-items:flex-start; gap:14px; cursor:pointer; }
  .ev-header:hover { background:#faf9f6; }
  .ev-icon { width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:16px; flex-shrink:0; }
  .ev-meta { flex:1; min-width:0; }
  .ev-type-badge { font-size:10px; font-weight:700; letter-spacing:1px; text-transform:uppercase; margin-bottom:3px; }
  .ev-subject { font-size:14px; font-weight:600; color:#0a0a0a; margin-bottom:3px; }
  .ev-preview { font-size:12px; color:#888; line-height:1.5; }
  .ev-fn { font-size:11px; color:#bbb; font-family:'SF Mono',Menlo,monospace; background:#f5f3ee; padding:2px 7px; border-radius:2px; white-space:nowrap; }
  .ev-toggle { flex-shrink:0; background:transparent; border:1px solid #e0dbd2; border-radius:3px; padding:5px 12px; font-size:11px; cursor:pointer; color:#888; align-self:flex-start; }
  .ev-toggle:hover { border-color:#999; color:#333; }
  .ev-content { display:none; border-top:1px solid #f0ece4; padding:16px 18px; background:#f8f6f1; }
  .ev-content pre { font-family:'SF Mono',Menlo,monospace; font-size:12px; color:#333; white-space:pre-wrap; line-height:1.7; margin:0; }
  .day-header { font-size:10px; text-transform:uppercase; letter-spacing:1.5px; color:#aaa; margin:18px 0 8px 2px; }
  .day-header:first-child { margin-top:0; }
</style>

<script>
const TYPE_CONFIG = {
  intake:    { bg:'#ddeeff', color:'#1a3a6a', icon:'📥', label:'Trigger' },
  email:     { bg:'#fdf0d5', color:'#7a3a00', icon:'✉️',  label:'Email' },
  ai_email:  { bg:'#f5e6ff', color:'#5a1a7a', icon:'✨', label:'AI Email' },
  education: { bg:'#d4f0de', color:'#1a5c2a', icon:'📚', label:'Education' },
  checkin:   { bg:'#fff0d4', color:'#6a3a00', icon:'📋', label:'Check-in' },
  session:   { bg:'#d0f0e0', color:'#0a4a22', icon:'🏋️', label:'Session' },
  track:     { bg:'#e8f4ff', color:'#0a2a5a', icon:'🗂️', label:'Track Assigned' },
  upgrade:   { bg:'#fff3cc', color:'#5a3a00', icon:'⬆️', label:'Upgrade' },
};

const TRACK_LABELS = {
  beginner_bodyweight: 'Beginner Bodyweight Strength',
  bodyweight_full:     'Bodyweight Full-Body',
  bodyweight_hiit:     'Bodyweight HIIT',
  resistance_bands:    'Resistance Bands Full-Body',
  dumbbell_full_body:  'Dumbbell Full-Body',
  home_complete:       'Home Complete (DB+Bands+Bar)',
  gym_beginner:        'Gym Beginner (Machines)',
  gym_intermediate:    'Gym Intermediate (PPL)',
};

const DAY_NAMES = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

let currentWeek = null;
let currentTrack = 'dumbbell_full_body';

function selectTrack(t) {
  currentTrack = t;
  // Update track buttons
  Object.keys(TRACK_LABELS).forEach(k => {
    const btn = document.getElementById('track-' + k);
    if (btn) btn.className = 'btn ' + (k === t ? 'btn-primary' : 'btn-ghost');
    if (btn) btn.style.cssText = 'padding:5px 12px;font-size:11px';
  });
  // Update label
  const lbl = document.getElementById('track-label');
  if (lbl) lbl.innerHTML = 'Track: <strong style="color:#333">' + (TRACK_LABELS[t] || t) + '</strong>';
  // Reload current week if one is selected
  if (currentWeek !== null) loadWeek(currentWeek);
}

function selectWeek(w) {
  // Update pills
  for (let i = 0; i <= 13; i++) {
    const p = document.getElementById('pill-' + i);
    if (p) p.className = 'btn ' + (i === w ? 'btn-primary' : 'btn-ghost');
    if (p) p.style.cssText = 'padding:7px 14px;font-size:12px;font-weight:700' + (i === 13 ? ';opacity:' + (w===13?'1':'0.6') : '');
  }
  // Update timeline
  document.getElementById('sim-timeline').style.display = 'block';
  for (let i = 0; i < 14; i++) {
    const seg = document.getElementById('tl-seg-' + i);
    const dot = document.getElementById('tl-dot-' + i);
    if (seg) seg.style.background = i <= w ? '#c41e3a' : '#2a2a2a';
    if (dot) dot.style.background = i < w ? '#c41e3a' : (i === w ? '#fff' : '#2a2a2a');
  }
  document.getElementById('tl-week-label').textContent = w === 0 ? 'Intake' : w === 13 ? 'Phase 2' : 'Wk ' + w;
  currentWeek = w;
  loadWeek(w);
}

function loadWeek(w) {
  document.getElementById('sim-output').innerHTML = '<div style="color:#999;text-align:center;padding:40px;background:#fff;border-radius:4px;border:1px solid #e0dbd2">Loading…</div>';
  fetch('/api/sim/' + w + '?track=' + currentTrack)
    .then(r => r.json())
    .then(data => renderWeek(data));
}

function renderWeek(data) {
  const events = data.events;
  const w = data.week;
  const wLabel = w === 0 ? 'Intake' : w === 13 ? 'Phase 2' : 'Week ' + w;

  if (!events.length) {
    document.getElementById('sim-output').innerHTML =
      '<div class="ev-card" style="padding:40px;text-align:center;color:#999">No events scheduled for this week.</div>';
    return;
  }

  // Group by day
  const byDay = {};
  events.forEach(e => {
    const d = String(e.day || 0);
    if (!byDay[d]) byDay[d] = [];
    byDay[d].push(e);
  });

  let html = `<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:16px">
    <span style="font-family:Georgia,serif;font-size:22px;color:#0a0a0a">${wLabel}</span>
    <span style="color:#999;font-size:12px">${events.length} event${events.length!==1?'s':''}</span>
  </div>`;

  const days = Object.keys(byDay).sort((a,b) => +a - +b);
  days.forEach(day => {
    const dayInt = parseInt(day);
    const dayStr = dayInt === 0 ? 'Day 1 — Monday' : `Day ${dayInt+1} — ${DAY_NAMES[dayInt % 7]}`;
    if (days.length > 1 || byDay[day].length > 1) {
      html += `<div class="day-header">${dayStr}</div>`;
    }
    byDay[day].forEach((ev, idx) => {
      const cfg = TYPE_CONFIG[ev.type] || TYPE_CONFIG.email;
      const id = 'ev_' + day + '_' + idx;
      const escaped_content = ev.content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const escaped_preview = ev.preview.replace(/</g,'&lt;').replace(/>/g,'&gt;');
      html += `
      <div class="ev-card">
        <div class="ev-header" onclick="toggleEv('${id}', event)">
          <div class="ev-icon" style="background:${cfg.bg}">${cfg.icon}</div>
          <div class="ev-meta">
            <div class="ev-type-badge" style="color:${cfg.color}">${cfg.label}</div>
            <div class="ev-subject">${ev.subject}</div>
            <div class="ev-preview">${escaped_preview}</div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0">
            <code class="ev-fn">${ev.function || ''}</code>
            <button class="ev-toggle" id="btn_${id}">Preview ↓</button>
          </div>
        </div>
        <div class="ev-content" id="${id}">
          <pre>${escaped_content}</pre>
        </div>
      </div>`;
    });
  });

  document.getElementById('sim-output').innerHTML = html;
}

function toggleEv(id, e) {
  // Don't toggle if click was on a button or link
  if (e && e.target && (e.target.tagName === 'BUTTON' || e.target.tagName === 'A')) return;
  const el = document.getElementById(id);
  const btn = document.getElementById('btn_' + id);
  if (!el) return;
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? 'Preview ↓' : 'Hide ↑';
}

// Auto-load intake on page load
selectWeek(0);
</script>
{% endblock %}""")


BUSINESS_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Battleship — Business Manager</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
           background: #0f0f0f; color: #ccc; font-size: 15px; }
    a { color: #c41e3a; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* ── Snapshot banner ── */
    .snapshot-banner { background: #222; border-bottom: 1px solid #333; padding: 10px 32px;
                       font-size: 12px; color: #666; display: flex; align-items: center; gap: 8px; }

    /* ── Topbar ── */
    .topbar { background: #0a0a0a; padding: 14px 32px; display: flex;
              align-items: center; justify-content: space-between;
              border-bottom: 1px solid #1a1a1a; }
    .topbar-brand { font-family: Georgia, serif; font-size: 20px;
                    letter-spacing: 3px; text-transform: uppercase; color: #fff; }
    .topbar-brand span { color: #c41e3a; }
    .topbar-nav { display: flex; align-items: center; gap: 20px; }
    .topbar-nav a { color: #555; font-size: 13px; }
    .topbar-nav a:hover { color: #fff; text-decoration: none; }
    .topbar-nav a.alert-link { color: #e8a020; }

    /* ── Reminders ── */
    .rem-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                padding: 22px; margin-bottom: 32px; }
    .rem-item { padding: 14px 0; border-bottom: 1px solid #1e1e1e;
                display: flex; align-items: flex-start; gap: 16px; }
    .rem-item:last-child { border-bottom: none; }
    .rem-badge { font-size: 10px; padding: 2px 9px; border-radius: 20px; font-weight: 700;
                 white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
    .rb-photo  { background: #3a2000; color: #e8a020; }
    .rb-tech   { background: #002233; color: #4a9fd4; }
    .rb-review { background: #1a0a2a; color: #aa66cc; }
    .rb-other  { background: #1e1e1e; color: #888; }
    .rem-body  { flex: 1; }
    .rem-title { font-size: 14px; color: #ddd; font-weight: 600; margin-bottom: 4px; }
    .rem-desc  { font-size: 12px; color: #555; line-height: 1.5; }
    .rem-meta  { font-size: 11px; color: #444; margin-top: 4px; }
    .rem-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .rem-btn { padding: 4px 14px; border-radius: 3px; font-size: 12px; cursor: pointer;
               border: 1px solid #333; background: transparent; color: #666; }
    .rem-btn:hover { border-color: #666; color: #ccc; }
    .rem-btn.done { border-color: #2a6a3a; color: #2a9d4e; }
    .rem-pivot-area { display: none; margin-top: 10px; }
    .rem-pivot-area textarea { width: 100%; background: #111; border: 1px solid #333;
      color: #ccc; padding: 8px 10px; border-radius: 3px; font-size: 13px;
      font-family: inherit; resize: vertical; min-height: 80px; }
    .rem-pivot-submit { margin-top: 6px; padding: 5px 16px; border-radius: 3px;
      background: #c41e3a; color: #fff; border: none; font-size: 12px; cursor: pointer; }

    /* ── Roadmap ── */
    .roadmap-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                    padding: 22px; margin-bottom: 32px; }
    .roadmap-item { display: flex; align-items: flex-start; gap: 14px; padding: 12px 0;
                    border-bottom: 1px solid #1e1e1e; }
    .roadmap-item:last-child { border-bottom: none; }
    .roadmap-num { font-size: 18px; font-weight: 700; color: #333; width: 28px;
                   flex-shrink: 0; text-align: right; }
    .roadmap-body { flex: 1; }
    .roadmap-title { font-size: 13px; color: #ccc; font-weight: 600; margin-bottom: 3px; }
    .roadmap-meta  { font-size: 11px; color: #444; }

    .container { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }

    /* ── Section headers ── */
    .section-label { font-size: 10px; text-transform: uppercase; letter-spacing: 2.5px;
                     color: #444; margin: 36px 0 14px; }
    .section-label:first-child { margin-top: 0; }

    /* ── Page header ── */
    .page-header { display: flex; align-items: baseline; justify-content: space-between;
                   margin-bottom: 32px; flex-wrap: wrap; gap: 12px; }
    .page-title { font-family: Georgia, serif; font-size: 26px; font-weight: normal; color: #fff; }
    .page-meta { display: flex; align-items: center; gap: 16px; }
    .page-date { font-size: 13px; color: #555; }
    .week-badge { background: #c41e3a; color: #fff; font-size: 11px; font-weight: 700;
                  letter-spacing: 1px; padding: 4px 12px; border-radius: 20px; text-transform: uppercase; }
    .back-link { font-size: 13px; color: #555; }
    .back-link:hover { color: #aaa; text-decoration: none; }

    /* ── KPI cards ── */
    .kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 32px; }
    @media (max-width: 900px) { .kpi-row { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 560px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
    .kpi-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                padding: 18px 16px; }
    .kpi-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
                 color: #444; margin-bottom: 8px; }
    .kpi-value { font-size: 22px; font-weight: 700; color: #e0e0e0; }
    .kpi-value.red  { color: #c41e3a; }
    .kpi-value.green { color: #2a9d4e; }

    /* ── Charts ── */
    .charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; }
    @media (max-width: 700px) { .charts-row { grid-template-columns: 1fr; } }
    .chart-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px; padding: 22px; }
    .chart-title { font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px;
                   color: #555; margin-bottom: 18px; }
    .chart-wrap { position: relative; height: 220px; }

    /* ── Marketing arc ── */
    .arc-row { display: flex; gap: 0; margin-bottom: 32px; }
    .arc-phase { flex: 1; text-align: center; padding: 12px 6px; background: #1a1a1a;
                 border: 1px solid #252525; font-size: 11px; color: #444; position: relative;
                 cursor: default; transition: background 0.15s; }
    .arc-phase:not(:last-child)::after { content: '▶'; position: absolute; right: -8px; top: 50%;
      transform: translateY(-50%); color: #333; font-size: 10px; z-index: 1; }
    .arc-phase.active { background: #2a0810; border-color: #c41e3a; color: #fff; }
    .arc-phase.active .arc-num { color: #c41e3a; }
    .arc-num { font-size: 9px; letter-spacing: 1px; display: block; margin-bottom: 4px; color: #333; }

    /* ── Social & Ads row ── */
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; }
    @media (max-width: 700px) { .two-col { grid-template-columns: 1fr; } }
    .dark-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px; padding: 22px; }
    .dark-card-title { font-size: 10px; text-transform: uppercase; letter-spacing: 2px;
                       color: #444; margin-bottom: 18px; }
    .stat-row { display: flex; justify-content: space-between; align-items: baseline;
                padding: 10px 0; border-bottom: 1px solid #222; }
    .stat-row:last-child { border-bottom: none; }
    .stat-name { font-size: 13px; color: #666; }
    .stat-val  { font-size: 15px; font-weight: 600; color: #ddd; }
    .stat-delta { font-size: 11px; color: #2a9d4e; margin-left: 6px; }
    .stat-delta.neg { color: #c41e3a; }
    .no-data { font-size: 13px; color: #444; font-style: italic; line-height: 1.6; }

    /* ── SEO progress ── */
    .seo-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                padding: 22px; margin-bottom: 32px; }
    .progress-bar-wrap { background: #111; border-radius: 20px; height: 8px;
                         overflow: hidden; margin-bottom: 20px; }
    .progress-bar-fill { height: 100%; background: #c41e3a; border-radius: 20px;
                         transition: width 0.4s; }
    .seo-task-list { list-style: none; }
    .seo-task { padding: 9px 0; border-bottom: 1px solid #1e1e1e; display: flex;
                align-items: center; gap: 10px; font-size: 13px; }
    .seo-task:last-child { border-bottom: none; }
    .seo-task-icon { font-size: 14px; width: 20px; text-align: center; flex-shrink: 0; }
    .seo-task-name { color: #888; }
    .seo-task-name.complete { color: #2a9d4e; }
    .seo-task-name.current  { color: #fff; }
    .seo-task-name.pending  { color: #e8a020; }

    /* ── Tech backlog table ── */
    .table-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                  padding: 22px; margin-bottom: 32px; overflow-x: auto; }
    .biz-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .biz-table th { text-align: left; font-size: 10px; text-transform: uppercase;
                    letter-spacing: 1.5px; color: #444; padding: 0 12px 10px 0;
                    border-bottom: 1px solid #252525; white-space: nowrap; }
    .biz-table td { padding: 11px 12px 11px 0; border-bottom: 1px solid #1e1e1e;
                    vertical-align: top; color: #888; }
    .biz-table tr:last-child td { border-bottom: none; }
    .biz-table td:first-child { color: #ccc; font-weight: 500; }
    .status-badge { display: inline-block; padding: 2px 9px; border-radius: 20px;
                    font-size: 11px; font-weight: 600; white-space: nowrap; }
    .sb-workaround_active         { background: #2a2a2a; color: #888; }
    .sb-blocked_manual_workaround { background: #3a1f00; color: #e8a020; }
    .sb-not_yet_needed            { background: #001a2a; color: #4a9fd4; }
    .sb-identified                { background: #2a2000; color: #e8c020; }
    .sb-implemented               { background: #001a0a; color: #2a9d4e; }
    .impact-critical { color: #c41e3a; font-weight: 700; }
    .impact-high     { color: #e8a020; }
    .impact-medium   { color: #888; }
    .impact-low      { color: #555; }

    /* ── Bot sections ── */
    .bot-section { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                   margin-bottom: 10px; overflow: hidden; }
    .bot-header  { display: flex; align-items: center; justify-content: space-between;
                   padding: 14px 18px; cursor: pointer; user-select: none; gap: 12px; }
    .bot-header:hover { background: #1f1f1f; }
    .bot-title   { display: flex; align-items: center; gap: 10px; }
    .bot-icon    { font-size: 16px; width: 24px; text-align: center; }
    .bot-name    { font-size: 13px; font-weight: 600; color: #ddd; letter-spacing: 0.5px; }
    .bot-last-run{ font-size: 11px; color: #444; }
    .bot-badges  { display: flex; gap: 6px; align-items: center; }
    .bot-badge   { font-size: 10px; padding: 2px 8px; border-radius: 20px; font-weight: 700; }
    .bb-alert    { background: #2a0810; color: #c41e3a; }
    .bb-warn     { background: #2a1800; color: #e8a020; }
    .bb-ok       { background: #001a0a; color: #2a9d4e; }
    .bb-info     { background: #1a1a2a; color: #7777cc; }
    .bot-chevron { font-size: 10px; color: #444; transition: transform 0.2s; }
    .bot-body    { border-top: 1px solid #222; padding: 18px; display: none; }
    .bot-body.open { display: block; }

    /* ── Post cards (expandable) ── */
    .post-card   { background: #111; border-radius: 4px; margin-bottom: 10px;
                   border: 1px solid #1e1e1e; overflow: hidden; }
    .post-card-header { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px;
                        cursor: pointer; }
    .post-card-header:hover { background: #161616; }
    .post-thumb  { width: 56px; height: 56px; object-fit: cover; border-radius: 3px;
                   flex-shrink: 0; background: #222; }
    .post-thumb-placeholder { width: 56px; height: 56px; border-radius: 3px; flex-shrink: 0;
                               background: #1e1e1e; display: flex; align-items: center;
                               justify-content: center; font-size: 20px; color: #333; }
    .post-meta   { flex: 1; min-width: 0; }
    .post-theme  { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px;
                   color: #555; margin-bottom: 4px; }
    .post-preview{ font-size: 13px; color: #ccc; white-space: nowrap; overflow: hidden;
                   text-overflow: ellipsis; }
    .post-status { font-size: 10px; padding: 2px 8px; border-radius: 20px; font-weight: 700;
                   white-space: nowrap; flex-shrink: 0; align-self: center; }
    .ps-pending_review { background: #2a1800; color: #e8a020; }
    .ps-approved       { background: #001a0a; color: #2a9d4e; }
    .ps-posted         { background: #001a2a; color: #4a9fd4; }
    .ps-rejected       { background: #1e1e1e; color: #444; }
    .post-scheduled    { background: #1a0a20; color: #9b59b6; }
    .post-body { padding: 0 14px 14px; border-top: 1px solid #1e1e1e; display: none; }
    .post-body.open { display: block; }
    .post-full-text { font-size: 13px; color: #aaa; line-height: 1.7; white-space: pre-wrap;
                      margin: 12px 0; }
    .post-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .post-edit-area { display: none; width: 100%; margin-top: 10px; }
    .post-edit-area textarea { width: 100%; background: #0a0a0a; border: 1px solid #c41e3a;
      color: #ccc; padding: 10px; border-radius: 3px; font-size: 13px;
      font-family: inherit; resize: vertical; min-height: 140px; box-sizing: border-box; }

    /* ── Post schedule calendar ── */
    .schedule-row { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
    .schedule-slot { flex: 1; min-width: 160px; background: #111; border-radius: 4px;
                     padding: 10px 12px; border-left: 3px solid #333; }
    .schedule-slot.has-post { border-left-color: #c41e3a; }
    .schedule-slot.posted   { border-left-color: #4a9fd4; }
    .schedule-day  { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
                     color: #555; margin-bottom: 4px; }
    .schedule-date { font-size: 13px; color: #888; margin-bottom: 6px; }
    .schedule-theme{ font-size: 12px; color: #ccc; }

    /* ── Weekly targets ── */
    .targets-card { background: #1a1a1a; border: 1px solid #252525; border-radius: 4px;
                    padding: 22px; margin-bottom: 32px; }
    .target-item { margin-bottom: 18px; }
    .target-item:last-child { margin-bottom: 0; }
    .target-header { display: flex; justify-content: space-between; margin-bottom: 7px;
                     font-size: 13px; }
    .target-label { color: #777; }
    .target-frac  { color: #555; }
  </style>
</head>
<body>

{% if is_snapshot %}
<div class="snapshot-banner">
  &#128248; Read-only snapshot &middot; Generated {{ snapshot_ts }} &middot; battleshipreset.com
</div>
{% endif %}

<div class="topbar">
  <div class="topbar-brand">Battle<span>ship</span></div>
  {% if not is_snapshot %}
  <nav class="topbar-nav">
    <a href="/" class="back-link">&#8592; Dashboard</a>
  </nav>
  {% endif %}
</div>

<div class="container">

  <!-- A. Page header -->
  <div class="page-header">
    <span class="page-title">Business Manager</span>
    <div class="page-meta">
      <span class="page-date">{{ today }}</span>
      <span class="week-badge">Week {{ campaign_week }} / 12</span>
    </div>
  </div>

  <!-- B. KPI cards -->
  <div class="section-label">Key Metrics</div>
  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-label">MRR</div>
      <div class="kpi-value">&#163;{{ "%.0f"|format(mrr) }}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Gap to &#163;3k</div>
      <div class="kpi-value{% if gap > 0 %} red{% endif %}">&#163;{{ "%.0f"|format(gap) }}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Spend</div>
      <div class="kpi-value">&#163;{{ "%.2f"|format(spend) }}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Net P&amp;L</div>
      <div class="kpi-value{% if net >= 0 %} green{% else %} red{% endif %}">
        {% if net >= 0 %}+{% endif %}&#163;{{ "%.2f"|format(net) }}
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Active Clients</div>
      <div class="kpi-value">{{ active_clients }}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Week</div>
      <div class="kpi-value">{{ campaign_week }} <span style="font-size:14px;color:#444;font-weight:400">/ 12</span></div>
    </div>
  </div>

  <!-- B2. Morning Briefing -->
  {% if briefing %}
  <div class="section-label" id="briefing-section">
    Morning Briefing
    <span style="font-size:10px;color:#444;font-weight:400;margin-left:8px;text-transform:none;letter-spacing:0">{{ briefing.get('today','') }}</span>
    <button onclick="toggleBriefing()" id="briefing-toggle" style="float:right;background:none;border:1px solid #333;color:#666;font-size:10px;padding:2px 10px;border-radius:3px;cursor:pointer;text-transform:uppercase;letter-spacing:1px">Collapse</button>
  </div>
  <div id="briefing-body" style="display:block">
    <!-- Pulse row -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px">
      {% set pulse = briefing.get('pulse',{}) %}
      <div style="background:#111;border-radius:4px;padding:14px;text-align:center">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">MRR</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-top:4px">£{{ pulse.get('mrr',0)|int }}</div>
        <div style="font-size:11px;color:#555">/ £3,000</div>
      </div>
      <div style="background:#111;border-radius:4px;padding:14px;text-align:center">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Leads 7d</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-top:4px">{{ pulse.get('leads_week',0) }}</div>
        <div style="font-size:11px;color:#555">this week</div>
      </div>
      <div style="background:#111;border-radius:4px;padding:14px;text-align:center">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Ad Spend</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-top:4px">£{{ "%.2f"|format(pulse.get('ad_spend_7d',0)) }}</div>
        <div style="font-size:11px;color:#555">7 days</div>
      </div>
    </div>
    <!-- Agent briefs -->
    {% set agents = briefing.get('agents',{}) %}
    {% for key, icon, label in [('clients','👥','Clients'),('ads','📣','Ads'),('brand','📊','Brand'),('seo','🔍','SEO'),('tech','⚙️','Tech')] %}
    {% if key in agents %}
    <div style="background:#111;border-radius:4px;padding:10px 14px;margin-bottom:6px;display:flex;gap:12px;align-items:flex-start">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;min-width:70px;padding-top:2px">{{ icon }} {{ label }}</span>
      <div>
        <span style="color:#ccc;font-size:13px">{{ agents[key].get('summary','') }}</span>
        <span style="color:#666;font-size:12px;font-style:italic"> → {{ agents[key].get('next_action','') }}</span>
      </div>
    </div>
    {% endif %}
    {% endfor %}
    <!-- Horizon -->
    {% set horizon = briefing.get('horizon',{}) %}
    <div style="border-left:3px solid #c41e3a;padding:10px 14px;background:#1a0a04;border-radius:0 4px 4px 0;margin-top:10px">
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#c41e3a">Today</div>
      <div style="color:#e8d5b0;font-size:14px;font-weight:600;margin-top:4px">{{ horizon.get('today','') }}</div>
    </div>
    <div style="background:#111;border-radius:4px;padding:10px 14px;margin-top:6px">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">5 Days: </span>
      <span style="color:#ccc;font-size:13px">{{ horizon.get('five_days','') }}</span>
    </div>
    <div style="background:#111;border-radius:4px;padding:10px 14px;margin-top:6px;margin-bottom:4px">
      <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">30 Days: </span>
      <span style="color:#ccc;font-size:13px">{{ horizon.get('thirty_days','') }}</span>
    </div>
    <div style="font-size:11px;color:#333;padding:6px 0">Generated {{ briefing.get('generated_at','')[:16] }}</div>
  </div>
  {% endif %}

  <!-- B3. Content Review -->
  <div class="section-label" id="content-review-section">
    Content Review
    {% if pending_content %}<span style="background:#c41e3a;color:#fff;font-size:10px;padding:2px 8px;border-radius:20px;margin-left:8px;font-weight:700">{{ pending_content | length }}</span>{% endif %}
    {% if ideas_drafts %}<span style="background:#3a2000;color:#e8a020;font-size:10px;padding:2px 8px;border-radius:20px;margin-left:6px;font-weight:700">{{ ideas_drafts | length }} idea{{ 's' if ideas_drafts | length != 1 }} to green light</span>{% endif %}
  </div>

  <!-- Ideas bank -->
  {% if ideas_drafts %}
  <div style="background:#111;border-radius:4px;padding:12px 16px;margin-bottom:8px;border-left:3px solid #e8a020">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#e8a020;margin-bottom:10px">💡 Ideas Bank — Awaiting Green Light</div>
    {% for idea in ideas_drafts %}
    <div style="padding:8px 0;border-bottom:1px solid #1e1e1e;display:flex;justify-content:space-between;align-items:flex-start;gap:12px" id="idea-{{ idea.id }}">
      <div style="flex:1">
        <div style="color:#fff;font-size:13px;font-weight:600">{{ idea.title }}</div>
        <div style="color:#777;font-size:12px;margin-top:3px">{{ idea.angle[:120] }}{% if idea.angle | length > 120 %}…{% endif %}</div>
      </div>
      <div style="display:flex;gap:6px;flex-shrink:0">
        <button onclick="greenLightIdea('{{ idea.id }}')" style="background:#2a9d4e;color:#fff;border:none;padding:5px 12px;border-radius:3px;font-size:11px;cursor:pointer">✅ Green light</button>
        <button onclick="archiveIdea('{{ idea.id }}')" style="background:none;border:1px solid #333;color:#555;padding:5px 10px;border-radius:3px;font-size:11px;cursor:pointer">Archive</button>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Pending post drafts -->
  <div class="rem-card">
    {% if pending_content %}
    {% for post in pending_content %}
    <div class="rem-item" id="cr-{{ post.id }}" style="align-items:flex-start;flex-direction:column">
      <div style="display:flex;gap:10px;align-items:center;width:100%;margin-bottom:8px">
        <span class="rem-badge" style="background:#1a0a20;color:#9b59b6">{{ post.source }}</span>
        <span style="color:#555;font-size:11px">{{ post.theme }} · {{ post.created[:10] }}</span>
      </div>
      <div id="cr-text-{{ post.id }}" style="color:#ccc;font-size:13px;line-height:1.6;white-space:pre-wrap;background:#111;padding:12px;border-radius:4px;width:100%;box-sizing:border-box">{{ post.content }}</div>
      <textarea id="cr-edit-{{ post.id }}" style="display:none;color:#ccc;font-size:13px;line-height:1.6;background:#111;padding:12px;border-radius:4px;width:100%;box-sizing:border-box;border:1px solid #c41e3a;min-height:160px;font-family:inherit">{{ post.content }}</textarea>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <button onclick="approveContent('{{ post.id }}')" class="rem-btn done">✅ Approve &amp; queue</button>
        <button onclick="toggleEditContent('{{ post.id }}')" id="edit-btn-{{ post.id }}" class="rem-btn" style="border-color:#9b59b6;color:#9b59b6">✏️ Edit</button>
        <button onclick="saveEditContent('{{ post.id }}')" id="save-btn-{{ post.id }}" class="rem-btn" style="display:none;border-color:#2a9d4e;color:#2a9d4e">Save edit</button>
        <button onclick="rejectContent('{{ post.id }}')" class="rem-btn" style="border-color:#c41e3a;color:#c41e3a">❌ Reject</button>
      </div>
    </div>
    {% endfor %}
    {% else %}
    <div style="color:#444;font-size:13px;font-style:italic;padding:12px 0">No content pending review. Posts are drafted Mon/Wed/Fri by Facebook Bot.</div>
    {% endif %}
  </div>

  <!-- B4. Bot Activity -->
  <div class="section-label" style="margin-top:32px">Bot Activity</div>

  <!-- Facebook Bot -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('fb')">
      <div class="bot-title">
        <span class="bot-icon">📘</span>
        <div>
          <div class="bot-name">Facebook Bot</div>
          <div class="bot-last-run">Posts: Mon · Wed · Fri</div>
        </div>
      </div>
      <div class="bot-badges">
        {% set fb_pending = all_content | selectattr('status','equalto','pending_review') | list %}
        {% set fb_posted  = all_content | selectattr('status','equalto','posted') | list %}
        {% if fb_pending %}<span class="bot-badge bb-warn">{{ fb_pending|length }} pending</span>{% endif %}
        {% if fb_posted  %}<span class="bot-badge bb-ok">{{ fb_posted|length }} posted</span>{% endif %}
        {% if not fb_pending and not fb_posted %}<span class="bot-badge bb-info">No drafts yet</span>{% endif %}
      </div>
      <span class="bot-chevron" id="chev-fb">&#9660;</span>
    </div>
    <div class="bot-body" id="body-fb">
      <!-- Post schedule calendar -->
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;margin-bottom:10px">Upcoming Schedule</div>
      <div class="schedule-row">
        {% for slot in fb_schedule %}
        {% set day_posts = posted_by_date.get(slot.date, []) %}
        <div class="schedule-slot {% if day_posts %}has-post{% endif %}">
          <div class="schedule-day">{{ slot.day }}</div>
          <div class="schedule-date">{{ slot.date }}</div>
          {% if day_posts %}
          <div class="schedule-theme">{{ day_posts[0].get('theme','—') }}</div>
          {% else %}
          <div class="schedule-theme" style="color:#333;font-style:italic">No post assigned</div>
          {% endif %}
        </div>
        {% endfor %}
      </div>
      <!-- Content queue -->
      {% if all_content %}
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;margin-bottom:10px;margin-top:6px">Content Queue</div>
      {% for post in all_content | sort(attribute='created', reverse=True) | list %}
      <div class="post-card" id="pc-{{ post.id }}">
        <div class="post-card-header" onclick="togglePost('{{ post.id }}')">
          <div class="post-thumb-placeholder">&#128444;</div>
          <div class="post-meta">
            <div class="post-theme">{{ post.get('theme','—') }} · {{ post.get('created','')[:10] }}</div>
            <div class="post-preview">{{ post.get('content','')[:100] }}</div>
          </div>
          <span class="post-status ps-{{ post.get('status','pending_review') }}">{{ post.get('status','—').replace('_',' ') }}</span>
        </div>
        <div class="post-body" id="pb-{{ post.id }}">
          <div class="post-full-text">{{ post.get('content','') }}</div>
          {% if post.get('status') == 'pending_review' %}
          <div class="post-actions">
            <button onclick="approveContent('{{ post.id }}')" class="rem-btn done">&#10003; Approve &amp; queue</button>
            <button onclick="toggleEditContent('{{ post.id }}')" id="edit-btn-{{ post.id }}" class="rem-btn" style="border-color:#9b59b6;color:#9b59b6">&#9998; Edit</button>
            <button onclick="saveEditContent('{{ post.id }}')" id="save-btn-{{ post.id }}" class="rem-btn" style="display:none;border-color:#2a9d4e;color:#2a9d4e">Save</button>
            <button onclick="rejectContent('{{ post.id }}')" class="rem-btn" style="border-color:#c41e3a;color:#c41e3a">&#10005; Reject</button>
          </div>
          <div class="post-edit-area" id="cr-edit-wrap-{{ post.id }}">
            <textarea id="cr-edit-{{ post.id }}">{{ post.get('content','') }}</textarea>
          </div>
          {% endif %}
          <div style="font-size:11px;color:#333;margin-top:8px">Source: {{ post.get('source','—') }} · ID: {{ post.id }}</div>
        </div>
      </div>
      {% endfor %}
      {% else %}
      <div style="color:#444;font-size:13px;font-style:italic">No content in queue. Facebook Bot drafts posts Mon/Wed/Fri.</div>
      {% endif %}
    </div>
  </div>

  <!-- Marketing Bot -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('mkt')">
      <div class="bot-title">
        <span class="bot-icon">📣</span>
        <div>
          <div class="bot-name">Marketing Bot</div>
          <div class="bot-last-run">Ideas bank · content arc · direction check</div>
        </div>
      </div>
      <div class="bot-badges">
        {% set green_lit = all_ideas | selectattr('status','equalto','green_lit') | list %}
        {% set developed = all_ideas | selectattr('status','equalto','developed') | list %}
        {% set drafts    = all_ideas | selectattr('status','equalto','draft') | list %}
        {% if green_lit %}<span class="bot-badge bb-ok">{{ green_lit|length }} green lit</span>{% endif %}
        {% if drafts    %}<span class="bot-badge bb-warn">{{ drafts|length }} draft{% if drafts|length != 1 %}s{% endif %}</span>{% endif %}
        {% if developed %}<span class="bot-badge bb-info">{{ developed|length }} developed</span>{% endif %}
      </div>
      <span class="bot-chevron" id="chev-mkt">&#9660;</span>
    </div>
    <div class="bot-body" id="body-mkt">
      <!-- Arc position -->
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;margin-bottom:8px">Content Arc</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px">
        {% for phase in arc_phases %}
        <div style="padding:6px 12px;border-radius:20px;font-size:11px;{% if loop.index0 == arc_phase_index %}background:#c41e3a;color:#fff;font-weight:700{% else %}background:#1e1e1e;color:#555{% endif %}">{{ phase }}</div>
        {% endfor %}
      </div>
      <!-- Ideas bank -->
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;margin-bottom:8px">Ideas Bank</div>
      {% if all_ideas %}
      {% for idea in all_ideas %}
      <div style="background:#111;border-radius:4px;padding:12px 14px;margin-bottom:8px;border-left:3px solid {% if idea.status == 'green_lit' %}#2a9d4e{% elif idea.status == 'developed' %}#4a9fd4{% elif idea.status == 'archived' %}#333{% else %}#e8a020{% endif %}" id="idea-mkt-{{ idea.id }}">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
          <div style="flex:1">
            <div style="color:#fff;font-size:13px;font-weight:600">{{ idea.title }}
              <span style="font-size:10px;padding:2px 8px;border-radius:20px;margin-left:8px;font-weight:700;{% if idea.status == 'green_lit' %}background:#001a0a;color:#2a9d4e{% elif idea.status == 'developed' %}background:#001a2a;color:#4a9fd4{% elif idea.status == 'archived' %}background:#1e1e1e;color:#444{% else %}background:#2a1800;color:#e8a020{% endif %}">{{ idea.status.replace('_',' ') }}</span>
            </div>
            <div style="color:#777;font-size:12px;margin-top:4px;line-height:1.5">{{ idea.angle }}</div>
            {% if idea.green_lit %}<div style="color:#333;font-size:11px;margin-top:4px">Green lit: {{ idea.green_lit[:10] }}</div>{% endif %}
          </div>
          {% if idea.status == 'draft' %}
          <div style="display:flex;gap:6px;flex-shrink:0">
            <button onclick="greenLightIdea('{{ idea.id }}')" style="background:#2a9d4e;color:#fff;border:none;padding:5px 12px;border-radius:3px;font-size:11px;cursor:pointer">Green light</button>
            <button onclick="archiveIdea('{{ idea.id }}')" style="background:none;border:1px solid #333;color:#555;padding:5px 10px;border-radius:3px;font-size:11px;cursor:pointer">Archive</button>
          </div>
          {% endif %}
        </div>
      </div>
      {% endfor %}
      {% else %}
      <div style="color:#444;font-size:13px;font-style:italic">No ideas yet. Add ideas via Telegram evening check-in.</div>
      {% endif %}
    </div>
  </div>

  <!-- Brand Manager -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('brand')">
      <div class="bot-title">
        <span class="bot-icon">🖼</span>
        <div>
          <div class="bot-name">Brand Manager</div>
          <div class="bot-last-run">Photo catalogue · review queue</div>
        </div>
      </div>
      <div class="bot-badges">
        {% if catalogue_stats.pending_review_photos > 0 %}<span class="bot-badge bb-warn">{{ catalogue_stats.pending_review_photos }} to review</span>{% endif %}
        <span class="bot-badge bb-info">{{ catalogue_stats.total }} in catalogue</span>
      </div>
      <span class="bot-chevron" id="chev-brand">&#9660;</span>
    </div>
    <div class="bot-body" id="body-brand">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px">
        <div style="background:#111;border-radius:4px;padding:12px;text-align:center">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Total Photos</div>
          <div style="font-size:24px;font-weight:700;color:#fff;margin-top:4px">{{ catalogue_stats.total }}</div>
        </div>
        <div style="background:#111;border-radius:4px;padding:12px;text-align:center">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Best Quality</div>
          <div style="font-size:24px;font-weight:700;color:#2a9d4e;margin-top:4px">{{ catalogue_stats.best }}</div>
        </div>
        <div style="background:#111;border-radius:4px;padding:12px;text-align:center">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Good</div>
          <div style="font-size:24px;font-weight:700;color:#e8a020;margin-top:4px">{{ catalogue_stats.good }}</div>
        </div>
      </div>
      {% if pending_photos %}
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555;margin-bottom:8px">Pending Photo Review</div>
      {% for photo in pending_photos %}
      <div style="display:flex;gap:12px;align-items:center;background:#111;border-radius:4px;padding:10px 14px;margin-bottom:8px" id="photo-{{ photo.id }}">
        <div style="font-size:20px">🖼</div>
        <div style="flex:1">
          <div style="color:#ccc;font-size:13px">{{ photo.path | replace('/Users/will/','~/') }}</div>
          <div style="color:#555;font-size:11px;margin-top:2px">{{ photo.get('notes','') }}</div>
        </div>
        <div style="display:flex;gap:6px">
          <button onclick="approvePhoto('{{ photo.id }}')" style="background:#2a9d4e;color:#fff;border:none;padding:5px 12px;border-radius:3px;font-size:11px;cursor:pointer">&#10003; Use</button>
          <button onclick="rejectPhoto('{{ photo.id }}')" style="background:none;border:1px solid #444;color:#666;padding:5px 10px;border-radius:3px;font-size:11px;cursor:pointer">Skip</button>
        </div>
      </div>
      {% endfor %}
      {% else %}
      <div style="color:#444;font-size:13px;font-style:italic">No photos pending review. Drop images into ~/Desktop/Battleship-review-pics to queue them.</div>
      {% endif %}
      <div style="color:#333;font-size:11px;margin-top:12px">Drop folder: ~/Desktop/Battleship-review-pics</div>
    </div>
  </div>

  <!-- SEO Bot -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('seo')">
      <div class="bot-title">
        <span class="bot-icon">🔍</span>
        <div>
          <div class="bot-name">SEO Bot</div>
          <div class="bot-last-run">Google Business Profile · local search</div>
        </div>
      </div>
      <div class="bot-badges">
        <span class="bot-badge bb-info">{{ seo_complete }}/{{ seo_tasks|length }} tasks</span>
        {% set seo_pending_will = seo_tasks | selectattr('cls','equalto','pending') | list %}
        {% if seo_pending_will %}<span class="bot-badge bb-warn">{{ seo_pending_will|length }} waiting on you</span>{% endif %}
      </div>
      <span class="bot-chevron" id="chev-seo">&#9660;</span>
    </div>
    <div class="bot-body" id="body-seo">
      {% for task in seo_tasks %}
      <div style="display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid #1a1a1a">
        <span style="font-size:14px;width:20px;text-align:center">{{ task.icon }}</span>
        <span style="font-size:13px;color:{% if task.cls == 'complete' %}#2a9d4e{% elif task.cls == 'pending' %}#e8a020{% elif task.cls == 'current' %}#4a9fd4{% else %}#444{% endif %}">{{ task.name }}</span>
        {% if task.cls == 'pending' %}<span style="font-size:10px;color:#e8a020;margin-left:auto">Action needed</span>{% endif %}
        {% if task.cls == 'current' %}<span style="font-size:10px;color:#4a9fd4;margin-left:auto">In progress</span>{% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Tech Bot -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('tech')">
      <div class="bot-title">
        <span class="bot-icon">⚙️</span>
        <div>
          <div class="bot-name">Tech Bot</div>
          <div class="bot-last-run">Infrastructure · integrations · automation</div>
        </div>
      </div>
      <div class="bot-badges">
        {% set tech_high = tech_gaps | selectattr('priority','equalto','high') | list if tech_gaps and tech_gaps[0] is mapping else [] %}
        {% if tech_high %}<span class="bot-badge bb-alert">{{ tech_high|length }} high priority</span>{% endif %}
        <span class="bot-badge bb-info">{{ tech_gaps|length }} items</span>
      </div>
      <span class="bot-chevron" id="chev-tech">&#9660;</span>
    </div>
    <div class="bot-body" id="body-tech">
      {% if tech_gaps %}
      {% for gap in tech_gaps %}
      {% if gap is mapping %}
      <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid #1a1a1a">
        <span style="font-size:10px;padding:2px 8px;border-radius:20px;font-weight:700;flex-shrink:0;margin-top:2px;{% if gap.get('priority') == 'high' %}background:#2a0810;color:#c41e3a{% elif gap.get('priority') == 'medium' %}background:#2a1800;color:#e8a020{% else %}background:#1a1a2a;color:#555{% endif %}">{{ gap.get('priority','—') }}</span>
        <div>
          <div style="color:#ccc;font-size:13px">{{ gap.get('description', gap.get('gap', gap)) }}</div>
          {% if gap.get('impact') %}<div style="color:#555;font-size:11px;margin-top:2px">Impact: {{ gap.impact }}</div>{% endif %}
        </div>
      </div>
      {% else %}
      <div style="color:#ccc;font-size:13px;padding:6px 0;border-bottom:1px solid #1a1a1a">{{ gap }}</div>
      {% endif %}
      {% endfor %}
      {% else %}
      <div style="color:#444;font-size:13px;font-style:italic">No tech backlog items.</div>
      {% endif %}
    </div>
  </div>

  <!-- Accounts Bot -->
  <div class="bot-section">
    <div class="bot-header" onclick="toggleBot('accounts')">
      <div class="bot-title">
        <span class="bot-icon">💳</span>
        <div>
          <div class="bot-name">Accounts Bot</div>
          <div class="bot-last-run">P&amp;L · client billing · cash flow</div>
        </div>
      </div>
      <div class="bot-badges">
        <span class="bot-badge {% if net >= 0 %}bb-ok{% else %}bb-alert{% endif %}">Net £{{ "%.0f"|format(net) }}</span>
        <span class="bot-badge bb-info">{{ active_clients }} client{{ 's' if active_clients != 1 }}</span>
      </div>
      <span class="bot-chevron" id="chev-accounts">&#9660;</span>
    </div>
    <div class="bot-body" id="body-accounts">
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">
        <div style="background:#111;border-radius:4px;padding:14px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">MRR</div>
          <div style="font-size:22px;font-weight:700;color:#fff;margin-top:4px">£{{ "%.0f"|format(mrr) }}</div>
          <div style="font-size:11px;color:#555">Target: £3,000</div>
          <div style="background:#1a1a1a;border-radius:3px;height:4px;margin-top:8px;overflow:hidden">
            <div style="height:100%;background:#c41e3a;width:{{ [mrr/3000*100,100]|min|int }}%"></div>
          </div>
        </div>
        <div style="background:#111;border-radius:4px;padding:14px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Monthly Spend</div>
          <div style="font-size:22px;font-weight:700;color:#e8a020;margin-top:4px">£{{ "%.2f"|format(spend) }}</div>
          <div style="font-size:11px;color:#555;margin-top:4px">Net: <span style="color:{% if net >= 0 %}#2a9d4e{% else %}#c41e3a{% endif %}">£{{ "%.2f"|format(net) }}</span></div>
        </div>
      </div>
      <div style="font-size:11px;color:#333;margin-top:12px">Active clients: {{ active_clients }} · Gap to £3k: £{{ "%.0f"|format(gap) }}</div>
    </div>
  </div>

  <!-- C. Charts -->
  <div class="section-label">Trends</div>
  <div class="charts-row">
    <div class="chart-card">
      <div class="chart-title">Revenue vs Spend</div>
      <div class="chart-wrap">
        <canvas id="chartRevSpend"></canvas>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Funnel</div>
      <div class="chart-wrap">
        <canvas id="chartFunnel"></canvas>
      </div>
    </div>
  </div>

  <!-- D. Marketing arc -->
  <div class="section-label">Marketing Arc — Phase {{ arc_phase_index + 1 }} / 6</div>
  <div class="arc-row">
    {% for phase in arc_phases %}
    <div class="arc-phase{% if loop.index0 == arc_phase_index %} active{% endif %}">
      <span class="arc-num">{{ loop.index }}</span>
      {{ phase }}
    </div>
    {% endfor %}
  </div>

  <!-- E. Social & Ads -->
  <div class="section-label">Social &amp; Ads</div>
  <div class="two-col">
    <div class="dark-card">
      <div class="dark-card-title">Social</div>
      <div class="stat-row">
        <span class="stat-name">FB Followers</span>
        <span class="stat-val">{{ fb_followers }}
          {% if fb_delta != 0 %}<span class="stat-delta{% if fb_delta < 0 %} neg{% endif %}">
            {{ '+' if fb_delta > 0 else '' }}{{ fb_delta }}</span>{% endif %}
        </span>
      </div>
      <div class="stat-row">
        <span class="stat-name">IG Followers</span>
        <span class="stat-val">{{ ig_followers }}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Organic Reach (week)</span>
        <span class="stat-val">{{ organic_reach_week }}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Link Clicks (week)</span>
        <span class="stat-val">{{ link_clicks_week }}</span>
      </div>
    </div>
    <div class="dark-card">
      <div class="dark-card-title">Ads</div>
      {% if has_ad_data %}
      <div class="stat-row">
        <span class="stat-name">Impressions</span>
        <span class="stat-val">{{ ad_impressions }}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Ad Spend</span>
        <span class="stat-val">&#163;{{ "%.2f"|format(ad_spend) }}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Results</span>
        <span class="stat-val">{{ ad_results }}</span>
      </div>
      {% else %}
      <div class="no-data">Add <code>FB_USER_TOKEN</code> to <code>~/.battleship.env</code> to enable ad tracking.</div>
      {% endif %}
    </div>
  </div>

  <!-- F. SEO Progress -->
  <div class="section-label">SEO — Google Business Profile</div>
  <div class="seo-card">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
      <span style="font-size:12px;color:#555">{{ seo_complete }} / 9 tasks complete</span>
      <span style="font-size:12px;color:#555">{{ seo_pct }}%</span>
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar-fill" style="width:{{ seo_pct }}%"></div>
    </div>
    <ul class="seo-task-list">
      {% for task in seo_tasks %}
      <li class="seo-task">
        <span class="seo-task-icon">{{ task.icon }}</span>
        <span class="seo-task-name {{ task.cls }}">{{ task.name }}</span>
      </li>
      {% endfor %}
    </ul>
  </div>

  <!-- G. Tech backlog -->
  <div class="section-label">Tech Backlog</div>
  <div class="table-card">
    <table class="biz-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Category</th>
          <th>Impact</th>
          <th>Status</th>
          <th>Monthly Cost</th>
          <th>Revenue Unlock</th>
        </tr>
      </thead>
      <tbody>
        {% for gap in tech_gaps %}
        <tr>
          <td>{{ gap.title }}</td>
          <td style="color:#666">{{ gap.category }}</td>
          <td><span class="impact-{{ gap.impact }}">{{ gap.impact }}</span></td>
          <td><span class="status-badge sb-{{ gap.status }}">{{ gap.status | replace('_', ' ') }}</span></td>
          <td style="color:#666">{% if gap.estimated_monthly_cost_gbp %}&#163;{{ gap.estimated_monthly_cost_gbp }}{% else %}free{% endif %}</td>
          <td style="color:#666">{% if gap.revenue_unlock_gbp %}&#163;{{ gap.revenue_unlock_gbp }}{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- H. Reminders -->
  <div class="section-label" id="reminders-section">
    Action Items
    {% if pending_reminders %}<span style="background:#c41e3a;color:#fff;font-size:10px;padding:2px 8px;border-radius:20px;margin-left:8px;font-weight:700">{{ pending_reminders | length }}</span>{% endif %}
  </div>
  <div class="rem-card">
    {% if pending_reminders %}
    {% for r in pending_reminders %}
    <div class="rem-item" id="rem-{{ r.id }}">
      <span class="rem-badge rb-{{ r.type }}">{{ r.type }}</span>
      <div class="rem-body">
        <div class="rem-title">{{ r.title }}</div>
        <div class="rem-desc">{{ r.description }}</div>
        <div class="rem-meta">Added by {{ r.added_by }} · {{ r.created_at }}{% if r.priority == 'high' %} · <span style="color:#e8a020">⚠ high priority</span>{% endif %}</div>
        <div class="rem-actions">
          {% if r.get('content_url') %}
          <a href="{{ r.content_url }}" target="_blank" class="rem-btn" style="border-color:#c41e3a;color:#c41e3a;text-decoration:none">📋 Open content ↗</a>
          {% endif %}
          <button class="rem-btn done" onclick="dismissReminder('{{ r.id }}')">✓ Done</button>
          <button class="rem-btn" onclick="togglePivot('{{ r.id }}')">↩ Pivot / push back</button>
        </div>
        <div class="rem-pivot-area" id="pivot-{{ r.id }}">
          <textarea id="pivot-text-{{ r.id }}" placeholder="Describe the pivot or why you're pushing back (saved and emailed to bot)…"></textarea>
          <button class="rem-pivot-submit" onclick="submitPivot('{{ r.id }}')">Save feedback</button>
        </div>
      </div>
    </div>
    {% endfor %}
    {% else %}
    <div style="color:#444;font-size:13px;font-style:italic;padding:12px 0">No pending action items.</div>
    {% endif %}
    {% if pivot_notes %}
    <div style="margin-top:18px;border-top:1px solid #222;padding-top:14px">
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#333;margin-bottom:10px">Recent Pivots / Feedback</div>
      {% for p in pivot_notes[-5:] %}
      <div style="padding:8px 0;border-bottom:1px solid #1a1a1a;font-size:12px;color:#555">
        <span style="color:#444">{{ p.created_at }} · rem {{ p.reminder_id }}:</span> {{ p.note }}
      </div>
      {% endfor %}
    </div>
    {% endif %}
  </div>

  <!-- H2. Photo Review -->
  <div class="section-label" id="photo-review-section">
    Photo Review
    {% if pending_photos %}<span style="background:#e8a020;color:#000;font-size:10px;padding:2px 8px;border-radius:20px;margin-left:8px;font-weight:700">{{ pending_photos | length }}</span>{% endif %}
  </div>
  <div class="rem-card">
    {% if pending_photos %}
    {% for photo in pending_photos %}
    <div class="rem-item" id="photo-{{ photo.id }}" style="align-items:flex-start">
      <span class="rem-badge" style="background:#3a2000;color:#e8a020">📸</span>
      <div class="rem-body" style="flex:1">
        <div class="rem-title">{{ photo.filename }}</div>
        <div class="rem-desc">{{ photo.caption_hint }}</div>
        <div class="rem-meta">Source: {{ photo.source }} · Added {{ photo.created_at[:10] }}</div>
        <div class="rem-actions" style="margin-top:8px">
          <button class="rem-btn done" onclick="approvePhoto('{{ photo.id }}')">✅ Post it</button>
          <button class="rem-btn" style="border-color:#c41e3a;color:#c41e3a" onclick="rejectPhoto('{{ photo.id }}')">❌ Skip</button>
        </div>
      </div>
    </div>
    {% endfor %}
    {% else %}
    <div style="color:#444;font-size:13px;font-style:italic;padding:12px 0">
      No photos pending review. Drop images into <code style="color:#666">/Users/will/Desktop/Battleship-review-pics/</code> to queue them.
    </div>
    {% endif %}
  </div>

  <!-- I. Roadmap -->
  <div class="section-label">Feature Roadmap</div>
  <div class="roadmap-card">
    {% if roadmap_items %}
    {% for item in roadmap_items %}
    <div class="roadmap-item">
      <div class="roadmap-num">{{ loop.index }}</div>
      <div class="roadmap-body">
        <div class="roadmap-title">{{ item.title }}</div>
        <div class="roadmap-meta">Impact: {{ item.impact }} &middot; Effort: {{ item.effort }}</div>
      </div>
    </div>
    {% endfor %}
    {% else %}
    <div style="color:#444;font-size:13px;font-style:italic">roadmap.md not found.</div>
    {% endif %}
  </div>

  <!-- J. Weekly targets -->
  <!-- TODO: wire up actual content/lead counts when tracking is implemented -->
  <div class="section-label">Weekly Targets</div>
  <div class="targets-card">
    {% for t in weekly_targets %}
    <div class="target-item">
      <div class="target-header">
        <span class="target-label">{{ t.label }}</span>
        <span class="target-frac">{{ t.current }} / {{ t.target }}</span>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-bar-fill" style="width:{{ [((t.current / t.target * 100) if t.target else 0), 100] | min }}%"></div>
      </div>
    </div>
    {% endfor %}
  </div>

</div><!-- /container -->

<script>
// ── Revenue vs Spend chart ─────────────────────────────────────────────────
(function() {
  const historyDates  = {{ history_dates | tojson }};
  const historyMrr    = {{ history_mrr   | tojson }};
  const historySpend  = {{ history_spend | tojson }};

  const ctx = document.getElementById('chartRevSpend');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: historyDates,
      datasets: [
        {
          label: 'MRR',
          data: historyMrr,
          borderColor: '#2a9d4e',
          backgroundColor: 'rgba(42,157,78,0.08)',
          tension: 0.3,
          pointRadius: 3,
          pointBackgroundColor: '#2a9d4e',
        },
        {
          label: 'Spend',
          data: historySpend,
          borderColor: '#c41e3a',
          backgroundColor: 'rgba(196,30,58,0.08)',
          tension: 0.3,
          pointRadius: 3,
          pointBackgroundColor: '#c41e3a',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#666', font: { size: 11 } } }
      },
      scales: {
        x: { ticks: { color: '#444', font: { size: 10 } }, grid: { color: '#1e1e1e' } },
        y: { ticks: { color: '#444', font: { size: 10 }, callback: v => '\\u00A3' + v },
             grid: { color: '#1e1e1e' } }
      }
    }
  });
})();

// ── Funnel chart ──────────────────────────────────────────────────────────
(function() {
  const funnel = {{ funnel | tojson }};
  const labels = ['Impressions', 'Clicks', 'Quiz Starts', 'Diagnosed', 'Paid'];
  const values = [
    funnel.impressions   || 0,
    funnel.clicks        || 0,
    funnel.quiz_starts   || 0,
    funnel.diagnosed     || 0,
    funnel.paid          || 0,
  ];

  const ctx = document.getElementById('chartFunnel');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Count',
        data: values,
        backgroundColor: [
          'rgba(196,30,58,0.25)',
          'rgba(196,30,58,0.35)',
          'rgba(196,30,58,0.50)',
          'rgba(196,30,58,0.70)',
          'rgba(196,30,58,0.90)',
        ],
        borderColor: '#c41e3a',
        borderWidth: 1,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: { ticks: { color: '#444', font: { size: 10 } }, grid: { color: '#1e1e1e' } },
        y: { ticks: { color: '#aaa', font: { size: 11 } }, grid: { color: '#1e1e1e' } }
      }
    }
  });
})();
</script>

<script>
function dismissReminder(id) {
  fetch('/api/reminders/' + id + '/dismiss', {method:'POST'})
    .then(r => r.json())
    .then(() => {
      const el = document.getElementById('rem-' + id);
      if (el) { el.style.opacity='0.3'; el.style.pointerEvents='none'; }
    });
}
function togglePivot(id) {
  const el = document.getElementById('pivot-' + id);
  if (el) el.style.display = el.style.display === 'block' ? 'none' : 'block';
}
function submitPivot(id) {
  const note = document.getElementById('pivot-text-' + id)?.value?.trim();
  if (!note) return;
  fetch('/api/reminders/' + id + '/pivot', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note: note})
  }).then(r => r.json()).then(() => {
    const el = document.getElementById('rem-' + id);
    if (el) { el.style.opacity='0.3'; el.style.pointerEvents='none'; }
  });
}
function approveContent(id) {
  fetch('/api/content-review/' + id + '/approve', {method:'POST'})
    .then(r => r.json()).then(() => {
      const el = document.getElementById('cr-' + id);
      if (el) el.innerHTML = '<span style="color:#2a9d4e;padding:8px 0;display:block">✅ Approved and queued for posting.</span>';
    });
}
function rejectContent(id) {
  fetch('/api/content-review/' + id + '/reject', {method:'POST'})
    .then(r => r.json()).then(() => {
      const el = document.getElementById('cr-' + id);
      if (el) { el.style.opacity='0.3'; el.style.pointerEvents='none'; }
    });
}
function toggleEditContent(id) {
  const view = document.getElementById('cr-text-' + id);
  const edit = document.getElementById('cr-edit-' + id);
  const editBtn = document.getElementById('edit-btn-' + id);
  const saveBtn = document.getElementById('save-btn-' + id);
  const editing = edit.style.display !== 'none';
  view.style.display = editing ? 'block' : 'none';
  edit.style.display = editing ? 'none' : 'block';
  editBtn.style.display = editing ? 'inline-block' : 'none';
  saveBtn.style.display = editing ? 'none' : 'inline-block';
}
function saveEditContent(id) {
  const text = document.getElementById('cr-edit-' + id)?.value?.trim();
  if (!text) return;
  fetch('/api/content-review/' + id + '/edit', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content: text})
  }).then(r => r.json()).then(() => {
    document.getElementById('cr-text-' + id).textContent = text;
    toggleEditContent(id);
  });
}
function greenLightIdea(id) {
  fetch('/api/ideas-bank/' + id + '/green-light', {method:'POST'})
    .then(r => r.json()).then(() => {
      const el = document.getElementById('idea-' + id);
      if (el) el.innerHTML = '<span style="color:#2a9d4e;padding:8px 0;display:block">✅ Green lit — post draft being generated...</span>';
    });
}
function archiveIdea(id) {
  fetch('/api/ideas-bank/' + id + '/archive', {method:'POST'})
    .then(r => r.json()).then(() => {
      const el = document.getElementById('idea-' + id);
      if (el) { el.style.opacity='0.3'; el.style.pointerEvents='none'; }
    });
}
function approvePhoto(id) {
  fetch('/api/photo-review/' + id + '/approve', {method:'POST'})
    .then(r => r.json())
    .then(() => {
      const el = document.getElementById('photo-' + id);
      if (el) { el.innerHTML = '<span style="color:#2a9d4e;padding:8px 0;display:block">✅ Approved — queued for posting</span>'; }
    });
}
function rejectPhoto(id) {
  fetch('/api/photo-review/' + id + '/reject', {method:'POST'})
    .then(r => r.json())
    .then(() => {
      const el = document.getElementById('photo-' + id);
      if (el) { el.style.opacity='0.3'; el.style.pointerEvents='none'; }
    });
}
function toggleBriefing() {
  const body = document.getElementById('briefing-body');
  const btn  = document.getElementById('briefing-toggle');
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? 'Expand' : 'Collapse';
}
function toggleBot(id) {
  const body  = document.getElementById('body-' + id);
  const chev  = document.getElementById('chev-' + id);
  if (!body) return;
  const open = body.classList.contains('open');
  body.classList.toggle('open', !open);
  if (chev) chev.style.transform = open ? '' : 'rotate(180deg)';
}
function togglePost(id) {
  const body = document.getElementById('pb-' + id);
  if (!body) return;
  body.classList.toggle('open');
}
</script>

</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

_CONTENT_VIEWER = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title }} — Battleship</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
           background: #f2efe8; color: #1a1a1a; font-size: 15px; line-height: 1.7; }
    .topbar { background: #0a0a0a; padding: 14px 32px; display: flex;
              align-items: center; justify-content: space-between; }
    .topbar-brand { font-family: Georgia, serif; font-size: 18px;
                    letter-spacing: 3px; text-transform: uppercase; color: #fff; }
    .topbar-brand span { color: #c41e3a; }
    .topbar-back { color: #555; font-size: 13px; text-decoration: none; }
    .topbar-back:hover { color: #fff; }
    .container { max-width: 720px; margin: 0 auto; padding: 40px 24px 80px; }
    .copy-bar { background: #fff; border: 1px solid #e0dbd2; border-radius: 4px;
                padding: 14px 18px; margin-bottom: 28px; display: flex;
                align-items: center; justify-content: space-between; gap: 16px; }
    .copy-hint { font-size: 13px; color: #888; }
    .copy-btn { background: #c41e3a; color: #fff; border: none; padding: 8px 20px;
                border-radius: 3px; font-size: 13px; font-weight: 600; cursor: pointer; }
    .copy-btn:hover { opacity: 0.85; }
    .content { background: #fff; border: 1px solid #e0dbd2; border-radius: 4px;
               padding: 32px 36px; }
    .content h1 { font-family: Georgia, serif; font-weight: normal; font-size: 22px;
                  color: #0a0a0a; margin: 0 0 20px; padding-bottom: 14px;
                  border-bottom: 1px solid #e0dbd2; }
    .content h2 { font-family: Georgia, serif; font-weight: normal; font-size: 17px;
                  color: #0a0a0a; margin: 28px 0 10px; }
    .content h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px;
                  color: #999; margin: 24px 0 8px; font-weight: 600; }
    .content p { margin-bottom: 14px; color: #333; }
    .content ul, .content ol { margin: 0 0 14px 20px; color: #333; }
    .content li { margin-bottom: 6px; }
    .content hr { border: none; border-top: 2px solid #e0dbd2; margin: 24px 0; }
    .content table { width: 100%; border-collapse: collapse; margin-bottom: 16px;
                     font-size: 13px; }
    .content th { text-align: left; font-size: 10px; text-transform: uppercase;
                  letter-spacing: 1px; color: #999; padding: 0 12px 8px 0;
                  border-bottom: 2px solid #e0dbd2; }
    .content td { padding: 9px 12px 9px 0; border-bottom: 1px solid #f0ece4;
                  vertical-align: top; color: #555; }
    .content code { background: #f5f3ee; padding: 2px 6px; border-radius: 3px;
                    font-family: monospace; font-size: 13px; color: #c41e3a; }
    .content pre { background: #f5f3ee; padding: 16px; border-radius: 4px;
                   white-space: pre-wrap; font-size: 13px; border: 1px solid #e8e3da;
                   margin-bottom: 14px; }
    .content strong { color: #0a0a0a; font-weight: 600; }
    .paste-block { background: #f0fdf4; border: 2px solid #2a9d4e; border-radius: 4px;
                   padding: 20px 22px; margin: 16px 0; position: relative; }
    .paste-block-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
                         color: #2a9d4e; font-weight: 700; margin-bottom: 10px; }
    .paste-block pre { background: transparent; border: none; padding: 0;
                       font-family: -apple-system, Arial, sans-serif; font-size: 14px;
                       line-height: 1.7; color: #1a1a1a; white-space: pre-wrap; }
    .paste-copy { position: absolute; top: 12px; right: 12px; background: #2a9d4e;
                  color: #fff; border: none; padding: 4px 12px; border-radius: 3px;
                  font-size: 11px; cursor: pointer; }
  </style>
</head>
<body>
<div class="topbar">
  <div class="topbar-brand">Battle<span>ship</span></div>
  <a href="{{ back_url }}" class="topbar-back">&#8592; Back</a>
</div>
<div class="container">
  <div class="copy-bar">
    <span class="copy-hint">Content file: <code>{{ filepath }}</code></span>
    <button class="copy-btn" onclick="copyAll()">Copy all text</button>
  </div>
  <div class="content" id="main-content">{{ rendered | safe }}</div>
</div>
<script>
function copyAll() {
  const el = document.getElementById('main-content');
  const text = el.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy all text', 2000);
  });
}
function copyBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.innerText).then(() => {
    const btn = el.parentElement.querySelector('.paste-copy');
    if (btn) { btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 2000); }
  });
}
</script>
</body>
</html>"""


@app.route("/content/<path:filepath>")
def content_viewer(filepath: str):
    """Render any vault markdown file as a clean readable page. Works on snapshot URL."""
    import re as _re
    # Security: only allow files within the vault, no path traversal
    target = (VAULT_ROOT / filepath).resolve()
    if not str(target).startswith(str(VAULT_ROOT.resolve())):
        return Response("Forbidden", status=403)
    if not target.exists():
        return Response("File not found", status=404)
    if target.suffix not in (".md", ".txt"):
        return Response("Only .md and .txt files supported", status=400)

    raw = target.read_text()

    # Simple markdown → HTML (no external deps)
    def md_to_html(text: str) -> str:
        lines = text.splitlines()
        html_parts = []
        in_pre = False
        in_paste = False
        paste_buf = []
        paste_id = 0

        for line in lines:
            # Fenced paste blocks: lines between "---" are paste-ready content
            if line.strip() == "---" and not in_pre:
                if not in_paste:
                    in_paste = True
                    paste_id += 1
                    paste_buf = []
                else:
                    in_paste = False
                    pid = f"paste_{paste_id}"
                    content = "\n".join(paste_buf)
                    html_parts.append(
                        f'<div class="paste-block">'
                        f'<div class="paste-block-label">📋 Paste-ready</div>'
                        f'<button class="paste-copy" onclick="copyBlock(\'{pid}\')">Copy</button>'
                        f'<pre id="{pid}">{content}</pre></div>'
                    )
                continue

            if in_paste:
                paste_buf.append(line)
                continue

            # Code blocks
            if line.startswith("```"):
                if not in_pre:
                    html_parts.append("<pre>")
                    in_pre = True
                else:
                    html_parts.append("</pre>")
                    in_pre = False
                continue
            if in_pre:
                html_parts.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                continue

            # Headings
            m = _re.match(r'^(#{1,3})\s+(.+)', line)
            if m:
                lvl = len(m.group(1))
                text_content = m.group(2)
                html_parts.append(f"<h{lvl}>{text_content}</h{lvl}>")
                continue

            # HR
            if _re.match(r'^[-*]{3,}$', line.strip()):
                html_parts.append("<hr>")
                continue

            # Table rows
            if line.startswith("|"):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if all(set(c) <= set("-: ") for c in cells):
                    continue  # separator row
                is_header = html_parts and html_parts[-1].strip().startswith("<table")
                tag = "th" if not any("<tr>" in p for p in html_parts[-3:]) else "td"
                if not any("<table>" in p for p in html_parts[-10:]):
                    html_parts.append("<table>")
                row_html = "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
                html_parts.append(row_html)
                continue
            else:
                if html_parts and html_parts[-1].strip() not in ("</table>", "") and \
                   html_parts[-1].strip().startswith("<tr>"):
                    html_parts.append("</table>")

            # List items
            m = _re.match(r'^[\-\*]\s+(.+)', line)
            if m:
                html_parts.append(f"<ul><li>{m.group(1)}</li></ul>")
                continue

            # Bold/italic inline
            line = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
            line = _re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2" target="_blank">\1</a>', line)
            line = _re.sub(r'`([^`]+)`', r'<code>\1</code>', line)

            # Paragraph
            if line.strip():
                html_parts.append(f"<p>{line}</p>")
            else:
                html_parts.append("")

        if in_pre:
            html_parts.append("</pre>")

        return "\n".join(html_parts)

    rendered = md_to_html(raw)
    title = target.stem.replace("-", " ").replace("_", " ").title()
    back_url = request.referrer or "/business"

    return render_template_string(
        _CONTENT_VIEWER,
        title=title,
        filepath=str(target.relative_to(VAULT_ROOT)),
        rendered=rendered,
        back_url=back_url,
    )


@app.route("/brand/<path:filename>")
def brand_asset(filename):
    """Serve brand images publicly (used by Instagram API which needs a public URL)."""
    from flask import send_from_directory
    brand_dir = VAULT_ROOT / "brand"
    return send_from_directory(brand_dir, filename)


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

@app.route("/tracker/<acct>")
def client_tracker(acct: str):
    """Serve the PWA workout tracker for a client."""
    state = load_state()
    cs = state.get("clients", {}).get(acct)
    if not cs:
        return Response("Client not found", status=404)
    html = generate_tracker_for_client(cs)
    return Response(html, mimetype="text/html")


@app.route("/simulate")
def simulator():
    return render_template_string(SIMULATOR_PAGE, title="Pipeline Simulator")

@app.route("/api/sim/<int:week>")
def api_sim_week(week):
    week  = max(0, min(week, 13))
    track = request.args.get("track", "dumbbell_full_body")
    if track not in _PROGRAM_FILES:
        track = "dumbbell_full_body"
    return jsonify({"week": week, "track": track, "events": _sim_week_events(week, track)})

@app.route("/run", methods=["GET", "POST"])
def run_pipeline_page():
    output = None
    if request.method == "POST":
        output = run_pipeline()
    return render_template_string(RUN_PAGE, title="Run Pipeline", output=output)

def _build_business_context():
    """Gather all data needed to render the /business page."""
    import re

    state    = load_state()
    strategy = _load_json_safe(MARKETING_STRATEGY_FILE, {})
    social   = _load_json_safe(SOCIAL_METRICS_FILE, {})
    seo      = _load_json_safe(SEO_STATE_FILE, {})
    backlog  = _load_json_safe(TECH_BACKLOG_FILE, {"gaps": []})
    history  = _load_json_safe(BIZ_HISTORY_FILE, {"history": []})

    today = datetime.now().strftime("%Y-%m-%d")

    # ── P&L ──────────────────────────────────────────────────────────────────
    mrr            = _calc_mrr(state)
    spend          = _parse_finances_spend()
    net            = round(mrr - spend, 2)
    gap            = max(0.0, round(3000.0 - mrr, 2))
    active_clients = sum(1 for cs in state.get("clients", {}).values()
                         if cs.get("status") == "active")

    pnl = {"mrr": mrr, "spend": spend, "net": net, "active_clients": active_clients}

    # ── Snapshot (write today's) ──────────────────────────────────────────────
    record_daily_snapshot(state, strategy, social, pnl)
    # Reload after write
    history = _load_json_safe(BIZ_HISTORY_FILE, {"history": []})

    # ── History arrays for chart ──────────────────────────────────────────────
    hist_items    = history.get("history", [])
    history_dates = [h["date"] for h in hist_items]
    history_mrr   = [h.get("mrr", 0) for h in hist_items]
    history_spend = [h.get("spend", 0) for h in hist_items]

    # ── Social ────────────────────────────────────────────────────────────────
    page_data = social.get("page", {})
    ig_data   = social.get("ig", {})
    ads_data  = social.get("ads", {})

    fb_followers = 0
    fb_delta     = 0
    if page_data:
        sorted_days = sorted(page_data.keys())
        if sorted_days:
            latest = sorted_days[-1]
            fb_followers = page_data[latest].get("followers", 0) or page_data[latest].get("fans", 0)
            if len(sorted_days) >= 2:
                prev = sorted_days[-2]
                prev_val = page_data[prev].get("followers", 0) or page_data[prev].get("fans", 0)
                fb_delta = fb_followers - prev_val

    ig_followers = 0
    if ig_data:
        latest_ig = max(ig_data.keys()) if ig_data else None
        if latest_ig:
            ig_followers = ig_data[latest_ig].get("followers_count", 0)

    # Organic reach + link clicks for the week: sum post reach from social.posts
    posts_data = social.get("posts", {})
    organic_reach_week = 0
    link_clicks_week   = 0
    for post_id, post in posts_data.items():
        insights = post.get("insights", {})
        organic_reach_week += int(insights.get("reach", 0) or 0)
        link_clicks_week   += int(insights.get("link_clicks", 0) or 0)

    # Ads
    last_ad    = strategy.get("last_ad_metrics", {})
    has_ad_data = bool(last_ad)
    ad_impressions = last_ad.get("impressions", 0) if has_ad_data else 0
    ad_spend       = float(last_ad.get("spend", 0) or 0) if has_ad_data else 0.0
    ad_results     = last_ad.get("results", "—") if has_ad_data else "—"

    # ── Marketing arc ─────────────────────────────────────────────────────────
    arc_phases = [
        "Problem Agitation",
        "Why You've Failed",
        "Science & System",
        "System + Proof",
        "Objection Crushing",
        "Direct CTA",
    ]
    arc_phase_index = int(strategy.get("arc_phase_index", 0))
    campaign_week   = int(strategy.get("campaign_week", 1))

    # ── Funnel ────────────────────────────────────────────────────────────────
    funnel = strategy.get("funnel", {
        "impressions": 0, "clicks": 0, "quiz_starts": 0, "diagnosed": 0, "paid": 0
    })

    # ── SEO ───────────────────────────────────────────────────────────────────
    SEO_TASK_NAMES = [
        "GBP Setup",
        "Category Audit",
        "Attributes Audit",
        "Competitor Teardown",
        "Review Strategy",
        "Posts Strategy",
        "Services",
        "Description",
        "Photo Plan",
    ]
    tasks_complete      = set(seo.get("tasks_complete", []))
    tasks_pending_will  = set(seo.get("tasks_pending_will", []))
    current_task        = seo.get("current_task", 0)
    seo_complete        = len(tasks_complete)
    seo_pct             = round(seo_complete / len(SEO_TASK_NAMES) * 100)

    seo_tasks = []
    for i, name in enumerate(SEO_TASK_NAMES):
        if i in tasks_complete:
            seo_tasks.append({"icon": "\u2705", "name": name, "cls": "complete"})
        elif i in tasks_pending_will:
            seo_tasks.append({"icon": "\u23f3", "name": name, "cls": "pending"})
        elif i == current_task:
            seo_tasks.append({"icon": "\U0001f535", "name": name, "cls": "current"})
        else:
            seo_tasks.append({"icon": "\u2b1c", "name": name, "cls": ""})

    # ── Tech backlog ──────────────────────────────────────────────────────────
    tech_gaps = backlog.get("gaps", [])

    # ── Reminders ─────────────────────────────────────────────────────────────
    rem_data         = _load_json_safe(REMINDERS_FILE, {"reminders": [], "pivot_notes": []})
    pending_reminders = [r for r in rem_data.get("reminders", []) if r.get("status") == "pending"]
    pivot_notes       = rem_data.get("pivot_notes", [])

    # ── Morning briefing ──────────────────────────────────────────────────────
    briefing      = _load_json_safe(MORNING_BRIEFING_FILE, {})
    photo_review  = _load_json_safe(PHOTO_REVIEW_FILE, {"candidates": []})
    pending_photos = [c for c in photo_review.get("candidates", []) if c.get("status") == "pending"]

    # ── Content review ────────────────────────────────────────────────────────
    content_review  = _load_json_safe(CONTENT_REVIEW_FILE, {"posts": []})
    pending_content = [p for p in content_review.get("posts", []) if p.get("status") == "pending_review"]
    ideas_data      = _load_json_safe(IDEAS_BANK_FILE, {"ideas": []})
    ideas_drafts    = [i for i in ideas_data.get("ideas", []) if i.get("status") == "draft"]

    # ── Roadmap ───────────────────────────────────────────────────────────────
    roadmap_items = []
    if ROADMAP_FILE.exists():
        import re as _re
        rm_text = ROADMAP_FILE.read_text()
        # Parse the build order table at the bottom
        for row in _re.finditer(
            r'\|\s*\d+\s*\|\s*#\d+\s+([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|', rm_text
        ):
            roadmap_items.append({
                "title": row.group(1).strip(),
                "effort": row.group(2).strip(),
                "impact": row.group(3).strip(),
            })

    # ── Ad results label ──────────────────────────────────────────────────────
    # Show link_clicks rather than generic "results"
    if has_ad_data:
        ad_results = f"{last_ad.get('link_clicks', last_ad.get('clicks', '—'))} link clicks"

    # ── Weekly targets (actuals TODO when tracking is implemented) ────────────
    weekly_targets = [
        {"label": "Content pieces",  "current": 0, "target": 5},
        {"label": "Leads generated", "current": 0, "target": 5},
        {"label": "New clients",     "current": 0, "target": 1},
    ]

    # ── Bot Activity: all content + all ideas ─────────────────────────────────
    all_content  = content_review.get("posts", [])
    all_ideas    = ideas_data.get("ideas", [])

    # Next 3 Mon/Wed/Fri posting dates from today
    from datetime import timedelta
    POST_DAYS = {0, 2, 4}  # Mon=0, Wed=2, Fri=4
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fb_schedule = []
    d = datetime.now().date()
    while len(fb_schedule) < 3:
        if d.weekday() in POST_DAYS:
            fb_schedule.append({"date": d.strftime("%Y-%m-%d"), "day": DAY_NAMES[d.weekday()]})
        d += timedelta(days=1)

    # Match scheduled content to those dates
    posted_by_date = {}
    for p in all_content:
        sched = p.get("scheduled_for") or p.get("created", "")[:10]
        for slot in fb_schedule:
            if sched == slot["date"]:
                posted_by_date.setdefault(slot["date"], []).append(p)

    # Catalogue stats
    catalogue_file = VAULT_ROOT / "brand" / "catalogue.json"
    catalogue_stats = {"total": 0, "best": 0, "good": 0, "usable": 0, "pending_review_photos": len(pending_photos)}
    if catalogue_file.exists():
        cat = json.loads(catalogue_file.read_text())
        catalogue_stats["total"] = len(cat)
        for v in cat.values():
            q = v.get("quality", "usable")
            if q in catalogue_stats:
                catalogue_stats[q] += 1

    # Orchestrator last-run times
    orch = _load_json_safe(VAULT_ROOT / "brand" / "Marketing" / "orchestrator_state.json", {})

    return dict(
        today=today,
        mrr=mrr, gap=gap, spend=spend, net=net, active_clients=active_clients,
        campaign_week=campaign_week,
        arc_phases=arc_phases, arc_phase_index=arc_phase_index,
        funnel=funnel,
        fb_followers=fb_followers, fb_delta=fb_delta,
        ig_followers=ig_followers,
        organic_reach_week=organic_reach_week, link_clicks_week=link_clicks_week,
        has_ad_data=has_ad_data, ad_impressions=ad_impressions,
        ad_spend=ad_spend, ad_results=ad_results,
        seo_complete=seo_complete, seo_pct=seo_pct, seo_tasks=seo_tasks,
        tech_gaps=tech_gaps,
        pending_reminders=pending_reminders,
        pivot_notes=pivot_notes,
        roadmap_items=roadmap_items,
        weekly_targets=weekly_targets,
        history_dates=history_dates, history_mrr=history_mrr, history_spend=history_spend,
        briefing=briefing,
        pending_photos=pending_photos,
        pending_content=pending_content,
        ideas_drafts=ideas_drafts,
        all_content=all_content,
        all_ideas=all_ideas,
        fb_schedule=fb_schedule,
        posted_by_date=posted_by_date,
        catalogue_stats=catalogue_stats,
        orch=orch,
    )


@app.route("/api/reminders", methods=["GET", "POST"])
def api_reminders():
    """GET: list pending. POST: add a new reminder (for bots)."""
    data = _load_json_safe(REMINDERS_FILE, {"reminders": [], "pivot_notes": []})
    if request.method == "GET":
        return jsonify({"reminders": [r for r in data.get("reminders", []) if r.get("status") == "pending"]})
    body = request.get_json(silent=True) or {}
    # Deduplicate by title
    existing_titles = {r.get("title", "") for r in data.get("reminders", [])}
    if body.get("title") in existing_titles:
        return jsonify({"status": "duplicate", "message": "Reminder already exists"}), 200
    import uuid as _uuid
    new_rem = {
        "id": "rem_" + _uuid.uuid4().hex[:8],
        "added_by": body.get("added_by", "bot"),
        "type": body.get("type", "other"),
        "title": body.get("title", "Untitled"),
        "description": body.get("description", ""),
        "priority": body.get("priority", "medium"),
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "status": "pending",
    }
    data.setdefault("reminders", []).append(new_rem)
    REMINDERS_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "added", "id": new_rem["id"]}), 201


@app.route("/api/reminders/<rem_id>/dismiss", methods=["POST"])
def api_reminder_dismiss(rem_id):
    data = _load_json_safe(REMINDERS_FILE, {"reminders": [], "pivot_notes": []})
    for r in data.get("reminders", []):
        if r["id"] == rem_id:
            r["status"] = "done"
            r["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    REMINDERS_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "ok"})


@app.route("/api/reminders/<rem_id>/pivot", methods=["POST"])
def api_reminder_pivot(rem_id):
    body = request.get_json(silent=True) or {}
    note = body.get("note", "").strip()
    data = _load_json_safe(REMINDERS_FILE, {"reminders": [], "pivot_notes": []})
    for r in data.get("reminders", []):
        if r["id"] == rem_id:
            r["status"] = "pivoted"
            r["pivoted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    pivot = {
        "reminder_id": rem_id,
        "note": note,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data.setdefault("pivot_notes", []).append(pivot)
    REMINDERS_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "ok"})


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    """Real-time Telegram webhook — handles button presses and messages instantly."""
    import importlib.util as _ilu
    update = request.get_json(silent=True) or {}

    def _tg_reply(text: str):
        try:
            env   = _read_env()
            token = env.get("TELEGRAM_BOT_TOKEN", "")
            cid   = env.get("TELEGRAM_CHAT_ID", "")
            if token and cid:
                _requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                    timeout=10
                )
        except Exception as e:
            print(f"  ⚠️  TG reply failed: {e}")

    # ── Inline button press ───────────────────────────────────────────────────
    cq = update.get("callback_query")
    if cq:
        cb_id   = cq["id"]
        data_str = cq.get("data", "")
        # Acknowledge immediately
        try:
            env = _read_env()
            _requests.post(
                f"https://api.telegram.org/bot{env.get('TELEGRAM_BOT_TOKEN','')}/answerCallbackQuery",
                json={"callback_query_id": cb_id, "text": "Got it"},
                timeout=5
            )
        except Exception:
            pass

        pr_data = _load_json_safe(PHOTO_REVIEW_FILE, {"candidates": []})

        if data_str.startswith("photo_approve_"):
            photo_id = data_str[len("photo_approve_"):]
            filename = photo_id
            for c in pr_data.get("candidates", []):
                if c["id"] == photo_id and c.get("status") == "pending":
                    c["status"]        = "approved"
                    c["reviewed_at"]   = datetime.now().isoformat()
                    c["review_source"] = "telegram"
                    filename           = c.get("filename", photo_id)
                    # Queue for Facebook posting
                    if c.get("path") and Path(c["path"]).exists():
                        import uuid as _uuid
                        queue_dir = VAULT_ROOT / "clients" / "facebook_queue"
                        queue_dir.mkdir(parents=True, exist_ok=True)
                        q = {"id": "fq_" + _uuid.uuid4().hex[:8], "image_path": c["path"],
                             "caption": c.get("caption_hint", ""), "source": "telegram_review",
                             "queued_at": datetime.now().isoformat(), "status": "pending"}
                        (queue_dir / f"photo_{photo_id}.json").write_text(json.dumps(q, indent=2))
            PHOTO_REVIEW_FILE.write_text(json.dumps(pr_data, indent=2))
            _tg_reply(f"✅ <b>{filename}</b> approved and queued for posting.")

        elif data_str.startswith("photo_reject_"):
            photo_id = data_str[len("photo_reject_"):]
            filename = photo_id
            for c in pr_data.get("candidates", []):
                if c["id"] == photo_id and c.get("status") == "pending":
                    c["status"]        = "rejected"
                    c["reviewed_at"]   = datetime.now().isoformat()
                    c["review_source"] = "telegram"
                    filename           = c.get("filename", photo_id)
            PHOTO_REVIEW_FILE.write_text(json.dumps(pr_data, indent=2))
            _tg_reply(f"❌ <b>{filename}</b> skipped.")

        return jsonify({"ok": True})

    # ── Text message → Claude (async so Telegram gets 200 instantly) ──────────
    msg  = update.get("message", {})
    text = msg.get("text", "").strip()
    if text:
        import threading as _threading
        def _handle_in_background(text=text):
          try:
            import anthropic as _anthropic
            env    = _read_env()
            state  = load_state()
            pr     = _load_json_safe(PHOTO_REVIEW_FILE, {"candidates": []})
            rems   = _load_json_safe(REMINDERS_FILE, {"reminders": []})
            brief  = _load_json_safe(MORNING_BRIEFING_FILE, {})
            social = _load_json_safe(SOCIAL_METRICS_FILE, {})

            clients   = state.get("clients", {})
            active    = [cs for cs in clients.values() if cs.get("status") == "active"]
            diagnosed = [cs for cs in clients.values() if cs.get("status") == "diagnosed"]
            pend_photos = [c for c in pr.get("candidates", []) if c.get("status") == "pending"]
            pend_rems   = [r for r in rems.get("reminders", []) if r.get("status") == "pending"]

            page_data    = social.get("page", {})
            fb_followers = 0
            if page_data:
                latest = max(page_data.keys()) if page_data else None
                if latest:
                    fb_followers = page_data[latest].get("fans", 0) or page_data[latest].get("followers", 0)

            pulse = brief.get("pulse", {})

            ideas_bank = ""
            ideas_file = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.md"
            if ideas_file.exists():
                ideas_bank = ideas_file.read_text()

            context = f"""You are the Battleship Reset AI assistant — Will Barratt's autonomous business partner.
Will runs an online fitness coaching business targeting men 40+ who've tried and failed to get fit.
You have full visibility of the business. Be direct, conversational, and useful. No filler.

TODAY: {datetime.now().strftime('%A %d %B %Y, %H:%M')}

BUSINESS STATE:
- MRR: £{pulse.get('mrr', 0):.0f} / £3,000 target (gap: £{pulse.get('gap', 0):.0f})
- Active clients: {len(active)}
- Leads (diagnosed, not paid): {len(diagnosed)}
- Leads this week: {pulse.get('leads_week', 0)}
- Ad spend (7d): £{pulse.get('ad_spend_7d', 0):.2f}
- FB followers: {fb_followers}

PENDING ACTIONS:
- Photos awaiting review: {len(pend_photos)} ({', '.join(c.get('filename','?') for c in pend_photos)})
- Reminders: {len(pend_rems)} pending ({'; '.join(r.get('title','') for r in pend_rems[:3])})

ACTIVE CLIENTS:
{chr(10).join(f"- {cs['name']}: week {cs.get('current_week',0)}, enrolled {cs.get('enrolled_date','?')}" for cs in active) or '- None yet'}

MARKETING IDEAS BANK:
{ideas_bank[:1500] if ideas_bank else 'No ideas bank yet.'}

Respond conversationally and directly. Keep replies concise (Telegram format).
If Will asks you to do something (approve a photo, add a reminder, etc.) say you've done it and confirm.
Don't use markdown headers. Use plain text with occasional bold using HTML <b>tags</b>.
Never say you can't do something — figure out the best response with the data you have."""

            ai = _anthropic.Anthropic(api_key=env.get("ANTHROPIC_KEY", ""))
            resp = ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=context,
                messages=[{"role": "user", "content": text}]
            )
            reply = resp.content[0].text.strip()

            # Execute simple actions Claude might decide on
            tl = text.lower()
            if any(w in tl for w in ("approve", "post it", "yes", "queue")) and pend_photos:
                c = pend_photos[0]
                c["status"] = "approved"; c["reviewed_at"] = datetime.now().isoformat(); c["review_source"] = "claude_tg"
                if c.get("path") and Path(c["path"]).exists():
                    import uuid as _uuid
                    qd = VAULT_ROOT / "clients" / "facebook_queue"; qd.mkdir(parents=True, exist_ok=True)
                    q  = {"id": "fq_" + _uuid.uuid4().hex[:8], "image_path": c["path"], "caption": c.get("caption_hint",""), "source":"claude_tg", "queued_at": datetime.now().isoformat(), "status":"pending"}
                    (qd / f"photo_{c['id']}.json").write_text(json.dumps(q, indent=2))
                PHOTO_REVIEW_FILE.write_text(json.dumps(pr, indent=2))

            _tg_reply(reply)

          except Exception as e:
            print(f"  ⚠️  Claude Telegram handler failed: {e}")
            _tg_reply(f"⚠️ Error: {str(e)[:120]}")

        _threading.Thread(target=_handle_in_background, daemon=True).start()

    return jsonify({"ok": True})


@app.route("/api/photo-review/<photo_id>/approve", methods=["POST"])
def api_photo_approve(photo_id):
    data = _load_json_safe(PHOTO_REVIEW_FILE, {"candidates": []})
    approved_path = None
    for c in data.get("candidates", []):
        if c["id"] == photo_id:
            c["status"] = "approved"
            c["reviewed_at"] = datetime.now().isoformat()
            c["review_source"] = "dashboard"
            approved_path = c.get("path")
    PHOTO_REVIEW_FILE.write_text(json.dumps(data, indent=2))
    # Queue approved photo for Facebook posting
    if approved_path and Path(approved_path).exists():
        queue_dir = VAULT_ROOT / "clients" / "facebook_queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        import uuid as _uuid
        queue_item = {
            "id": "fq_" + _uuid.uuid4().hex[:8],
            "image_path": approved_path,
            "caption": "",
            "source": "photo_review",
            "queued_at": datetime.now().isoformat(),
            "status": "pending",
        }
        (queue_dir / f"photo_{photo_id}.json").write_text(json.dumps(queue_item, indent=2))
    return jsonify({"status": "approved"})


@app.route("/api/photo-review/<photo_id>/reject", methods=["POST"])
def api_photo_reject(photo_id):
    data = _load_json_safe(PHOTO_REVIEW_FILE, {"candidates": []})
    for c in data.get("candidates", []):
        if c["id"] == photo_id:
            c["status"] = "rejected"
            c["reviewed_at"] = datetime.now().isoformat()
            c["review_source"] = "dashboard"
    PHOTO_REVIEW_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "rejected"})


@app.route("/api/content-review/<cr_id>/approve", methods=["POST"])
def api_content_approve(cr_id):
    data = _load_json_safe(CONTENT_REVIEW_FILE, {"posts": []})
    for p in data.get("posts", []):
        if p["id"] == cr_id:
            p["status"] = "approved"
            p["reviewed_at"] = datetime.now().isoformat()
            # Move to facebook_queue for posting
            queue_dir = VAULT_ROOT / "clients" / "facebook_queue"
            queue_dir.mkdir(parents=True, exist_ok=True)
            import uuid as _uuid
            (queue_dir / f"cr_{cr_id}.json").write_text(json.dumps({
                "id": "fq_" + _uuid.uuid4().hex[:8],
                "content": p.get("content", ""),
                "theme": p.get("theme", ""),
                "source": "content_review",
                "queued_at": datetime.now().isoformat(),
                "status": "pending",
            }, indent=2))
    CONTENT_REVIEW_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "approved"})


@app.route("/api/content-review/<cr_id>/reject", methods=["POST"])
def api_content_reject(cr_id):
    data = _load_json_safe(CONTENT_REVIEW_FILE, {"posts": []})
    for p in data.get("posts", []):
        if p["id"] == cr_id:
            p["status"] = "rejected"
            p["reviewed_at"] = datetime.now().isoformat()
    CONTENT_REVIEW_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "rejected"})


@app.route("/api/content-review/<cr_id>/edit", methods=["POST"])
def api_content_edit(cr_id):
    body = request.get_json(silent=True) or {}
    data = _load_json_safe(CONTENT_REVIEW_FILE, {"posts": []})
    for p in data.get("posts", []):
        if p["id"] == cr_id:
            p["content"] = body.get("content", p["content"])
            p["edited"]  = True
    CONTENT_REVIEW_FILE.write_text(json.dumps(data, indent=2))
    return jsonify({"status": "saved"})


@app.route("/api/ideas-bank/<idea_id>/green-light", methods=["POST"])
def api_idea_green_light(idea_id):
    data = _load_json_safe(IDEAS_BANK_FILE, {"ideas": []})
    for idea in data.get("ideas", []):
        if idea["id"] == idea_id:
            idea["status"] = "green_lit"
            idea["green_lit"] = datetime.now().strftime("%Y-%m-%d")
    IDEAS_BANK_FILE.write_text(json.dumps(data, indent=2))
    # Also update the markdown version
    _sync_ideas_bank_md(data)
    return jsonify({"status": "green_lit"})


@app.route("/api/ideas-bank/<idea_id>/archive", methods=["POST"])
def api_idea_archive(idea_id):
    data = _load_json_safe(IDEAS_BANK_FILE, {"ideas": []})
    for idea in data.get("ideas", []):
        if idea["id"] == idea_id:
            idea["status"] = "archived"
    IDEAS_BANK_FILE.write_text(json.dumps(data, indent=2))
    _sync_ideas_bank_md(data)
    return jsonify({"status": "archived"})


def _sync_ideas_bank_md(data: dict):
    """Keep ideas-bank.md in sync with the JSON."""
    STATUS_EMOJI = {"draft": "🟡 Draft", "green_lit": "🟢 Green lit", "archived": "⬛ Archived", "developed": "✅ Developed"}
    lines = ["# Marketing Ideas Bank\n"]
    for idea in data.get("ideas", []):
        status = STATUS_EMOJI.get(idea.get("status", "draft"), idea.get("status", ""))
        lines.append(f"## {idea['title']}")
        lines.append(f"**Angle:** {idea['angle']}")
        lines.append(f"**Status:** {status}")
        lines.append(f"**Added:** {idea.get('added', '')}\n")
    md_file = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.md"
    md_file.write_text("\n".join(lines))


@app.route("/business")
def business():
    ctx = _build_business_context()
    ctx["is_snapshot"]   = False
    ctx["snapshot_ts"]   = ""
    return render_template_string(BUSINESS_PAGE, **ctx)


@app.route("/snapshot")
def snapshot():
    token = request.args.get("token", "")
    if token != "bsr2026":
        return Response("403 Forbidden", status=403, mimetype="text/plain")
    ctx = _build_business_context()
    ctx["is_snapshot"]  = True
    ctx["snapshot_ts"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    return render_template_string(BUSINESS_PAGE, **ctx)


# ── Entry ─────────────────────────────────────────────────────────────────────

_LEGAL_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title }} — Battleship Reset</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
           background: #fff; color: #333; font-size: 15px; line-height: 1.8;
           max-width: 720px; margin: 0 auto; padding: 48px 24px 80px; }
    h1 { font-family: Georgia, serif; font-weight: normal; font-size: 28px;
         color: #0a0a0a; margin-bottom: 8px; }
    h2 { font-size: 16px; font-weight: 700; color: #0a0a0a; margin: 32px 0 8px; }
    p, li { color: #444; margin-bottom: 12px; }
    ul { margin-left: 20px; }
    .meta { font-size: 13px; color: #999; margin-bottom: 40px; }
    a { color: #c41e3a; }
    .brand { font-family: Georgia, serif; letter-spacing: 2px; font-size: 13px;
             text-transform: uppercase; color: #0a0a0a; border-bottom: 2px solid #c41e3a;
             padding-bottom: 16px; margin-bottom: 32px; display: block; }
  </style>
</head>
<body>
<span class="brand">Battleship Reset</span>
<h1>{{ title }}</h1>
<p class="meta">Last updated: 15 March 2026 &middot; Battleship Reset &middot; battleshipreset.com</p>
{{ body | safe }}
</body></html>"""

_PRIVACY_BODY = """
<h2>1. Who we are</h2>
<p>Battleship Reset is an online fitness coaching service for men aged 40–60, operated by Will Barratt, United Kingdom. Website: <a href="https://battleshipreset.com">battleshipreset.com</a>. Contact: <a href="mailto:coach@battleship.me">coach@battleship.me</a></p>

<h2>2. What data we collect</h2>
<ul>
  <li><strong>Intake form data</strong> — name, email, age, weight, height, fitness goals, health notes — collected when you complete our quiz at battleshipreset.com.</li>
  <li><strong>Payment data</strong> — processed by Stripe. We do not store card details.</li>
  <li><strong>Check-in data</strong> — weekly progress submissions you send via our Google Form.</li>
  <li><strong>Email correspondence</strong> — messages you send to coach@battleship.me or support@battleship.me.</li>
  <li><strong>Social media interactions</strong> — comments and messages you send to our Facebook Page or Instagram account (@battleshipreset).</li>
</ul>

<h2>3. How we use your data</h2>
<ul>
  <li>To deliver your personalised 12-week coaching programme.</li>
  <li>To send weekly check-in requests, education content, and coaching feedback by email.</li>
  <li>To respond to comments and messages on our social media pages.</li>
  <li>To process payments via Stripe.</li>
  <li>To improve our service based on aggregated, anonymised feedback.</li>
</ul>

<h2>4. Legal basis (GDPR)</h2>
<p>We process your data under <strong>contract</strong> (to deliver the coaching service you purchased), <strong>legitimate interests</strong> (to respond to enquiries and manage our social media), and <strong>consent</strong> (for marketing communications, which you can withdraw at any time).</p>

<h2>5. Data retention</h2>
<p>Client coaching data is retained for 2 years after your programme ends, then deleted. Enquiry data is retained for 12 months. You can request deletion at any time (see section 7).</p>

<h2>6. Third parties</h2>
<ul>
  <li><strong>Stripe</strong> — payment processing (stripe.com/privacy)</li>
  <li><strong>Google</strong> — check-in forms and workspace (policies.google.com/privacy)</li>
  <li><strong>Anthropic / Claude API</strong> — used to generate personalised coaching content from your intake data (anthropic.com/privacy)</li>
  <li><strong>Meta (Facebook/Instagram)</strong> — social media management (facebook.com/policy)</li>
</ul>
<p>We do not sell your data to any third party.</p>

<h2>7. Your rights</h2>
<p>Under GDPR you have the right to access, correct, or delete your personal data. To exercise any of these rights, email <a href="mailto:coach@battleship.me">coach@battleship.me</a> with the subject line "Data Request". We will respond within 30 days.</p>
<p>You can also request data deletion directly at: <a href="https://webhook.battleshipreset.com/data-deletion">webhook.battleshipreset.com/data-deletion</a></p>

<h2>8. Cookies</h2>
<p>Our website (battleshipreset.com) does not use tracking cookies. Our coaching dashboard (webhook.battleshipreset.com) uses session cookies only for operational purposes.</p>

<h2>9. Contact</h2>
<p>Data controller: Will Barratt, Battleship Reset, United Kingdom.<br>
Email: <a href="mailto:coach@battleship.me">coach@battleship.me</a></p>
"""

_DATA_DELETION_BODY = """
<h2>How to request deletion of your data</h2>
<p>To request deletion of your personal data held by Battleship Reset, please send an email to <a href="mailto:coach@battleship.me">coach@battleship.me</a> with the subject line <strong>"Data Deletion Request"</strong>.</p>
<p>Include your name and the email address associated with your account. We will confirm deletion within 30 days.</p>

<h2>What gets deleted</h2>
<ul>
  <li>Your intake form responses</li>
  <li>Your weekly check-in data</li>
  <li>Your email correspondence</li>
  <li>Your coaching plan and progress tracker</li>
</ul>
<p>Payment records are retained for legal/tax purposes as required by UK law (7 years), but are not used for any other purpose after deletion.</p>

<h2>Facebook / Instagram data</h2>
<p>If you connected with us via Facebook or Instagram, you can also manage your data directly through Meta's tools at <a href="https://www.facebook.com/help/contact/540977946302970" target="_blank">facebook.com/help/contact/540977946302970</a>.</p>

<h2>Contact</h2>
<p>Email: <a href="mailto:coach@battleship.me">coach@battleship.me</a><br>
Subject: Data Deletion Request</p>
"""

@app.route("/privacy")
def privacy_policy():
    return render_template_string(_LEGAL_PAGE, title="Privacy Policy", body=_PRIVACY_BODY)

@app.route("/data-deletion")
def data_deletion():
    return render_template_string(_LEGAL_PAGE, title="Data Deletion", body=_DATA_DELETION_BODY)


if __name__ == "__main__":
    print("\n  Battleship Dashboard → http://localhost:5100\n")
    app.run(host="127.0.0.1", port=5100, debug=False)
