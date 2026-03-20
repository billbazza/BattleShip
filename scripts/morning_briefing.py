#!/usr/bin/env python3
"""
Battleship Reset — Morning Briefing
=====================================
Runs at 07:00 daily via cron.
  - Aggregates data from all agents/state files
  - Picks photo candidates (iCloud drop folder + brand library)
  - Sends styled HTML email to will@battleship.me
  - Sends Telegram summary with photo review buttons
  - Writes clients/morning_briefing.json for dashboard

CRON:
  0 7 * * * /usr/bin/python3 /Users/will/Obsidian-Vaults/BattleShip-Vault/scripts/morning_briefing.py >> /Users/will/Obsidian-Vaults/BattleShip-Vault/logs/morning_briefing.log 2>&1
"""

import json
import os
import re
import smtplib
import sys
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

VAULT_ROOT         = Path(__file__).parent.parent
CLIENTS_DIR        = VAULT_ROOT / "clients"
STATE_FILE         = CLIENTS_DIR / "state.json"
SOCIAL_FILE        = CLIENTS_DIR / "social_metrics.json"
MARKETING_FILE     = CLIENTS_DIR / "marketing_strategy.json"
SEO_FILE           = VAULT_ROOT / "brand" / "Marketing" / "SEO" / "seo_state.json"
TECH_FILE          = VAULT_ROOT / "brand" / "Marketing" / "tech_backlog.json"
REMINDERS_FILE     = VAULT_ROOT / "brand" / "Marketing" / "reminders.json"
FINANCES_FILE      = VAULT_ROOT / "finances.md"
BRIEFING_FILE      = CLIENTS_DIR / "morning_briefing.json"
PHOTO_REVIEW_FILE  = CLIENTS_DIR / "photo_review_state.json"

# Drop folder — drag photos here from anywhere (Finder, iPhone AirDrop, etc.) to queue for review
ICLOUD_DROP = VAULT_ROOT / "brand" / "random-snaps"

# Existing brand photo library
BRAND_OUTPUT = VAULT_ROOT / "brand" / "output"
BRAND_PHOTOS = VAULT_ROOT / "brand" / "photos"

WILL_EMAIL   = "will@battleship.me"
COACH_EMAIL  = "coach@battleship.me"
SMTP_PORT    = 587


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env = {}
    env_path = Path.home() / ".battleship.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _load_json(path: Path, default=None):
    if path and path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default if default is not None else {}


def _calc_mrr(state: dict) -> float:
    mrr = 0.0
    for cs in state.get("clients", {}).values():
        if cs.get("status") == "active":
            mrr += 89.0 if cs.get("complimentary") is False else 0.0
            if not cs.get("complimentary"):
                mrr += 89.0
    # Use paid count × £89 as MRR proxy
    paid = [cs for cs in state.get("clients", {}).values()
            if cs.get("status") in ("active",) and not cs.get("complimentary")]
    return round(len(paid) * 89.0, 2)


def _parse_spend(finances_text: str) -> float:
    total = 0.0
    for m in re.finditer(r'£\s*([\d,]+(?:\.\d+)?)', finances_text):
        try:
            total += float(m.group(1).replace(",", ""))
        except Exception:
            pass
    return round(total, 2) if total else 0.0


def _traffic_light(value: float, warn: float, ok: float) -> str:
    if value >= ok:
        return "🟢"
    if value >= warn:
        return "🟡"
    return "🔴"


def _days_ago(date_str: str) -> int:
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (datetime.now() - d).days
    except Exception:
        return 999


# ── Photo Candidate Selection ─────────────────────────────────────────────────

IMAGE_EXTS     = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
CATALOGUE_FILE = VAULT_ROOT / "brand" / "catalogue.json"

# Quality ranking for sorting
QUALITY_RANK = {"best": 0, "good": 1, "usable": 2}


def _select_photo_candidates(photo_review: dict) -> list:
    """
    Pick up to 3 photo candidates:
    1. New drops from brand/random-snaps (highest priority)
    2. Best unposted photos from brand/catalogue.json
    Returns list of candidate dicts.
    """
    reviewed_paths = {c["path"] for c in photo_review.get("candidates", [])}
    candidates = []

    # 1. Desktop drop folder — any new file goes straight to the top of the queue
    if ICLOUD_DROP.exists():
        for f in sorted(ICLOUD_DROP.iterdir()):
            if f.suffix.lower() in IMAGE_EXTS and str(f) not in reviewed_paths:
                candidates.append({
                    "id": "photo_" + uuid.uuid4().hex[:8],
                    "path": str(f),
                    "filename": f.name,
                    "source": "drop_folder",
                    "caption_hint": "New photo from drop folder",
                    "quality": "best",
                    "notes": "Manually dropped for review",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "reviewed_at": None,
                    "review_source": None,
                })
                if len(candidates) >= 3:
                    return candidates

    # 2. Brand catalogue — best unposted photos not yet reviewed
    if CATALOGUE_FILE.exists():
        try:
            catalogue = json.loads(CATALOGUE_FILE.read_text())
        except Exception:
            catalogue = {}

        # Sort by quality, then period (after > mid > before for posts)
        period_rank = {"after": 0, "mid": 1, "before": 2}
        sorted_entries = sorted(
            catalogue.items(),
            key=lambda kv: (
                QUALITY_RANK.get(kv[1].get("quality", "usable"), 2),
                period_rank.get(kv[1].get("period", "after"), 3),
            )
        )

        for rel_path, meta in sorted_entries:
            abs_path = str(VAULT_ROOT / "brand" / rel_path)
            if abs_path in reviewed_paths:
                continue
            if not Path(abs_path).exists():
                continue
            # Skip photos already used in a post
            if meta.get("used_in"):
                continue

            filename = Path(rel_path).name
            notes    = meta.get("notes", "")
            quality  = meta.get("quality", "usable")
            period   = meta.get("period", "after")
            use_cases = meta.get("use_cases", [])

            # Generate a meaningful caption hint
            if "ad" in use_cases and period == "after":
                caption_hint = f"Strong ad candidate ({quality}). {notes[:80]}"
            elif period == "after":
                caption_hint = f"After shot — {notes[:80]}"
            elif period == "before":
                caption_hint = f"Before shot — good for transformation story. {notes[:60]}"
            else:
                caption_hint = notes[:100] or "Lifestyle / progress shot"

            candidates.append({
                "id": "photo_" + uuid.uuid4().hex[:8],
                "path": abs_path,
                "filename": filename,
                "source": "catalogue",
                "caption_hint": caption_hint,
                "quality": quality,
                "notes": notes,
                "use_cases": use_cases,
                "period": period,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "reviewed_at": None,
                "review_source": None,
            })
            if len(candidates) >= 3:
                break

    return candidates


# ── Data Aggregation ──────────────────────────────────────────────────────────

def _build_briefing_data() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    state    = _load_json(STATE_FILE, {"clients": {}})
    social   = _load_json(SOCIAL_FILE, {})
    strategy = _load_json(MARKETING_FILE, {})
    seo      = _load_json(SEO_FILE, {})
    backlog  = _load_json(TECH_FILE, {"gaps": []})
    rems     = _load_json(REMINDERS_FILE, {"reminders": []})
    finances = FINANCES_FILE.read_text() if FINANCES_FILE.exists() else ""

    # ── Pulse ────────────────────────────────────────────────────────────────
    clients       = state.get("clients", {})
    active_count  = sum(1 for cs in clients.values() if cs.get("status") == "active")
    diagnosed     = sum(1 for cs in clients.values() if cs.get("status") == "diagnosed")
    total_clients = len(clients)
    mrr           = _calc_mrr(state)
    spend         = _parse_spend(finances)
    gap           = max(0.0, round(3000.0 - mrr, 2))

    # Leads this week = new intakes in last 7 days
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    leads_week = sum(
        1 for cs in clients.values()
        if cs.get("intake_date", "") >= week_ago
    )

    # Ad spend last 7 days
    last_ad  = strategy.get("last_ad_metrics", {})
    ad_spend = float(last_ad.get("spend", 0) or 0)
    ad_impr  = int(last_ad.get("impressions", 0) or 0)
    ad_clicks= int(last_ad.get("link_clicks", last_ad.get("clicks", 0)) or 0)

    # ── Social ───────────────────────────────────────────────────────────────
    page_data = social.get("page", {})
    ig_data   = social.get("ig", {})
    fb_followers = 0
    fb_delta     = 0
    if page_data:
        sorted_days = sorted(page_data.keys())
        if sorted_days:
            latest = sorted_days[-1]
            fb_followers = page_data[latest].get("followers", 0) or page_data[latest].get("fans", 0)
            if len(sorted_days) >= 2:
                prev_val = page_data[sorted_days[-2]].get("followers", 0) or page_data[sorted_days[-2]].get("fans", 0)
                fb_delta = fb_followers - prev_val
    ig_followers = 0
    if ig_data:
        latest_ig = max(ig_data.keys())
        ig_followers = ig_data[latest_ig].get("followers_count", 0)

    # Post engagement
    posts   = social.get("posts", {})
    reach   = sum(int(p.get("insights", {}).get("reach", 0) or 0) for p in posts.values())
    clicks  = sum(int(p.get("insights", {}).get("link_clicks", 0) or 0) for p in posts.values())

    # ── SEO ──────────────────────────────────────────────────────────────────
    seo_tasks_done = len(seo.get("tasks_complete", []))
    seo_total      = 9
    seo_pct        = round(seo_tasks_done / seo_total * 100)
    seo_pending_will = seo.get("tasks_pending_will", [])

    # ── Tech ─────────────────────────────────────────────────────────────────
    gaps = backlog.get("gaps", [])
    active_workarounds = [g for g in gaps if g.get("status") == "workaround_active"]
    blocked_gaps       = [g for g in gaps if g.get("status") in ("open", "blocked")]

    # ── Reminders ────────────────────────────────────────────────────────────
    pending_rems = [r for r in rems.get("reminders", []) if r.get("status") == "pending"]
    high_prio    = [r for r in pending_rems if r.get("priority") == "high"]

    # ── Marketing arc ────────────────────────────────────────────────────────
    arc_names = ["Problem Agitation", "Why You've Failed", "Science & System",
                 "System + Proof", "Objection Crushing", "Direct CTA"]
    arc_idx     = int(strategy.get("arc_phase_index", 0))
    arc_current = arc_names[arc_idx] if arc_idx < len(arc_names) else "Unknown"
    campaign_week = int(strategy.get("campaign_week", 1))

    # ── Horizon targets (rule-based) ─────────────────────────────────────────
    if campaign_week <= 2:
        phase_label  = "Foundation"
        target_content = 5; target_leads = 0; target_clients = 0
    elif campaign_week <= 4:
        phase_label  = "Visibility"
        target_content = 7; target_leads = 3; target_clients = 0
    elif campaign_week <= 8:
        phase_label  = "Conversion"
        target_content = 7; target_leads = 5; target_clients = 1
    else:
        phase_label  = "Scale"
        target_content = 5; target_leads = 10; target_clients = 2

    clients_needed_mrr = max(0, round((3000 - mrr) / 89))

    # ── Agent briefs ─────────────────────────────────────────────────────────
    agents = {
        "brand": {
            "summary": f"{fb_followers} FB followers ({'+' if fb_delta >= 0 else ''}{fb_delta} vs yesterday), {ig_followers} IG. Reach: {reach}, clicks: {clicks}.",
            "next_action": "Post due Mon/Wed/Fri. Next content should be Phase: " + arc_current,
        },
        "seo": {
            "summary": f"{seo_tasks_done}/{seo_total} GBP tasks complete ({seo_pct}%).",
            "next_action": "Claim GBP at business.google.com" if seo_tasks_done == 0 else (
                f"Tasks pending your action: {len(seo_pending_will)}" if seo_pending_will else "On track."
            ),
        },
        "tech": {
            "summary": f"{len(active_workarounds)} active workaround(s), {len(blocked_gaps)} blocked gap(s).",
            "next_action": "Apply for Meta Standard Access" if any("standard" in str(g).lower() for g in blocked_gaps) else (
                "No action needed — monitor at £" + str(min((g.get("unlock_at_mrr", 999) for g in blocked_gaps), default=999)) + " MRR."
            ),
        },
        "ads": {
            "summary": f"7d: {ad_impr:,} impressions, {ad_clicks} clicks, £{ad_spend:.2f} spend.",
            "next_action": "Messages campaign ends 19 Mar — decide whether to renew." if campaign_week <= 2 else "Monitor CPL trend.",
        },
        "clients": {
            "summary": f"{active_count} active, {diagnosed} diagnosed, {total_clients} total. {leads_week} lead(s) this week.",
            "next_action": f"Need {clients_needed_mrr} more paying clients to hit £3k MRR." if gap > 0 else "£3k MRR target reached!",
        },
    }

    # ── Today's priority action ───────────────────────────────────────────────
    if high_prio:
        today_action = high_prio[0]["title"]
    elif seo_tasks_done == 0:
        today_action = "Claim Google Business Profile at business.google.com"
    elif pending_rems:
        today_action = pending_rems[0]["title"]
    else:
        today_action = "Publish a post on Facebook/Instagram"

    horizon = {
        "today": today_action,
        "five_days": f"Publish {target_content} content pieces. Generate {target_leads} leads. Arc: {arc_current}.",
        "thirty_days": f"Target: {target_clients} new client(s)/week. Close gap of £{gap:.0f} → need {clients_needed_mrr} paying clients.",
    }

    # ── Photo review ─────────────────────────────────────────────────────────
    photo_review  = _load_json(PHOTO_REVIEW_FILE, {"candidates": []})
    new_candidates = _select_photo_candidates(photo_review)

    return {
        "generated_at": datetime.now().isoformat(),
        "today": today,
        "pulse": {
            "mrr": mrr, "gap": gap, "spend": spend,
            "leads_week": leads_week, "ad_spend_7d": ad_spend,
        },
        "agents": agents,
        "horizon": horizon,
        "photo_candidates": new_candidates,
        "campaign_week": campaign_week,
        "phase_label": phase_label,
    }


# ── Email Rendering ───────────────────────────────────────────────────────────

def _render_email(data: dict) -> str:
    pulse    = data["pulse"]
    agents   = data["agents"]
    horizon  = data["horizon"]
    today    = data["today"]
    phase    = data["phase_label"]
    week     = data["campaign_week"]
    n_photos = len(data["photo_candidates"])

    mrr_light = _traffic_light(pulse["mrr"], 500, 3000)
    lead_light= _traffic_light(pulse["leads_week"], 1, 5)
    ad_light  = _traffic_light(pulse["ad_spend_7d"], 5, 20)

    agent_rows = ""
    icons = {"brand": "📊", "seo": "🔍", "tech": "⚙️", "ads": "📣", "clients": "👥"}
    labels = {"brand": "Brand / Social", "seo": "SEO", "tech": "Tech", "ads": "Ads", "clients": "Clients"}
    for key in ["clients", "ads", "brand", "seo", "tech"]:
        ag = agents[key]
        agent_rows += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #2a2a2a;vertical-align:top;width:90px">
            <span style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#888">{icons[key]} {labels[key]}</span>
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #2a2a2a;vertical-align:top">
            <span style="color:#ccc;font-size:13px">{ag['summary']}</span><br>
            <span style="color:#888;font-size:12px;font-style:italic">→ {ag['next_action']}</span>
          </td>
        </tr>"""

    photo_note = (
        f'<p style="color:#e8a020;font-size:13px">📸 {n_photos} photo candidate(s) awaiting review — check Telegram or the Business Manager portal.</p>'
        if n_photos else
        '<p style="color:#555;font-size:13px;font-style:italic">No new photos queued for review.</p>'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Morning Briefing</title></head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:Georgia,serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f0f;padding:32px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:6px;overflow:hidden">

  <!-- Header -->
  <tr><td style="background:#c41e3a;padding:24px 32px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:3px;color:#ffaaaa;margin-bottom:6px">Daily Briefing</div>
    <div style="font-size:22px;font-weight:700;color:#fff;letter-spacing:1px">BATTLESHIP RESET</div>
    <div style="font-size:12px;color:#ffaaaa;margin-top:4px">{today} &nbsp;·&nbsp; Campaign Week {week} &nbsp;·&nbsp; Phase: {phase}</div>
  </td></tr>

  <!-- Pulse -->
  <tr><td style="padding:24px 32px 16px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:2.5px;color:#555;margin-bottom:14px">Pulse</div>
    <table width="100%" cellpadding="0" cellspacing="8">
      <tr>
        <td style="background:#111;border-radius:4px;padding:14px;text-align:center;width:33%">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">MRR {mrr_light}</div>
          <div style="font-size:24px;font-weight:700;color:#fff;margin-top:4px">£{pulse['mrr']:.0f}</div>
          <div style="font-size:11px;color:#555">/ £3,000 target</div>
        </td>
        <td style="background:#111;border-radius:4px;padding:14px;text-align:center;width:33%">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Leads 7d {lead_light}</div>
          <div style="font-size:24px;font-weight:700;color:#fff;margin-top:4px">{pulse['leads_week']}</div>
          <div style="font-size:11px;color:#555">this week</div>
        </td>
        <td style="background:#111;border-radius:4px;padding:14px;text-align:center;width:33%">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Ad Spend {ad_light}</div>
          <div style="font-size:24px;font-weight:700;color:#fff;margin-top:4px">£{pulse['ad_spend_7d']:.2f}</div>
          <div style="font-size:11px;color:#555">last 7 days</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Agent Briefs -->
  <tr><td style="padding:8px 32px 16px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:2.5px;color:#555;margin-bottom:10px">Agent Briefs</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #2a2a2a;border-radius:4px">
      {agent_rows}
    </table>
  </td></tr>

  <!-- Horizon -->
  <tr><td style="padding:8px 32px 16px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:2.5px;color:#555;margin-bottom:12px">Horizon</div>
    <table width="100%" cellpadding="0" cellspacing="8">
      <tr>
        <td style="background:#1f1206;border-left:3px solid #c41e3a;border-radius:0 4px 4px 0;padding:12px 16px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#c41e3a">Today</div>
          <div style="font-size:14px;color:#e8d5b0;margin-top:4px;font-weight:600">{horizon['today']}</div>
        </td>
      </tr>
      <tr><td style="padding:4px 0"></td></tr>
      <tr>
        <td style="background:#111;border-radius:4px;padding:12px 16px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">Next 5 Days</div>
          <div style="font-size:13px;color:#ccc;margin-top:4px">{horizon['five_days']}</div>
        </td>
      </tr>
      <tr><td style="padding:4px 0"></td></tr>
      <tr>
        <td style="background:#111;border-radius:4px;padding:12px 16px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#555">30-Day Target</div>
          <div style="font-size:13px;color:#ccc;margin-top:4px">{horizon['thirty_days']}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Photos -->
  <tr><td style="padding:8px 32px 24px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:2.5px;color:#555;margin-bottom:10px">Photos for Review</div>
    {photo_note}
    <p style="font-size:12px;color:#555">
      Approve or reject via Telegram @BattleshipResetBot, or visit the
      <a href="http://localhost:5100/business" style="color:#c41e3a">Business Manager</a>.
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#111;padding:16px 32px;text-align:center">
    <p style="font-size:11px;color:#333;margin:0">Battleship Reset · Autonomous Pipeline · {today}</p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


# ── Telegram Briefing ─────────────────────────────────────────────────────────

def _send_telegram_briefing(data: dict):
    try:
        sys.path.insert(0, str(VAULT_ROOT))
        from scripts.telegram_notify import send_message, send_photo_with_keyboard

        pulse   = data["pulse"]
        horizon = data["horizon"]
        agents  = data["agents"]
        photos  = data["photo_candidates"]
        week    = data["campaign_week"]

        mrr_l  = _traffic_light(pulse["mrr"], 500, 3000)
        lead_l = _traffic_light(pulse["leads_week"], 1, 5)

        lines = [
            f"☀️ <b>Morning Briefing — {data['today']}</b> · Wk {week}",
            "",
            f"{mrr_l} MRR: <b>£{pulse['mrr']:.0f}</b> / £3,000  ·  Gap: £{pulse['gap']:.0f}",
            f"{lead_l} Leads 7d: <b>{pulse['leads_week']}</b>  ·  Ad spend: £{pulse['ad_spend_7d']:.2f}",
            f"👥 {agents['clients']['summary']}",
            "",
            f"<b>Today:</b> {horizon['today']}",
            f"<b>5 days:</b> {horizon['five_days']}",
            f"<b>30 days:</b> {horizon['thirty_days']}",
        ]
        if photos:
            lines.append(f"\n📸 <b>{len(photos)} photo(s)</b> queued for review — see below")

        send_message("\n".join(lines))

        # Send each photo candidate with inline buttons
        for photo in photos:
            photo_path = photo["path"]
            if not Path(photo_path).exists():
                print(f"  ⚠️  Photo not found: {photo_path}")
                continue
            caption = (
                f"📸 <b>{photo['filename']}</b>\n"
                f"Source: {photo['source']}\n"
                f"{photo['caption_hint']}"
            )
            buttons = [[
                {"text": "✅ Post it", "callback_data": f"photo_approve_{photo['id']}"},
                {"text": "❌ Skip",    "callback_data": f"photo_reject_{photo['id']}"},
            ]]
            send_photo_with_keyboard(photo_path, caption, buttons)
            print(f"  📸 Sent photo candidate: {photo['filename']}")

    except Exception as e:
        print(f"  ⚠️  Telegram briefing failed: {e}")


# ── Email Sending ─────────────────────────────────────────────────────────────

def _send_email(env: dict, subject: str, html_body: str):
    smtp_host = env.get("SMTP_HOST", "")
    smtp_user = env.get("SMTP_USER", "")
    smtp_pass = env.get("SMTP_PASS", "")
    if not smtp_host or not smtp_user:
        print("  ⚠️  SMTP not configured — skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Battleship Reset <{COACH_EMAIL}>"
    msg["To"]      = WILL_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, SMTP_PORT) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, WILL_EMAIL, msg.as_string())
        print(f"  ✅ Email sent to {WILL_EMAIL}")
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")


# ── Photo Review State ────────────────────────────────────────────────────────

def _update_photo_review(existing: dict, new_candidates: list) -> dict:
    """Append new candidates without duplicating by path."""
    existing_paths = {c["path"] for c in existing.get("candidates", [])}
    for c in new_candidates:
        if c["path"] not in existing_paths:
            existing.setdefault("candidates", []).append(c)
    return existing


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print(f"☀️  Morning Briefing — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    env = _load_env()

    print("\n📊 Aggregating data...")
    data = _build_briefing_data()

    # Save briefing JSON for dashboard
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFING_FILE.write_text(json.dumps(data, indent=2, default=str))
    print(f"  ✅ Briefing data saved → {BRIEFING_FILE.name}")

    # Update photo review state
    photo_review = _load_json(PHOTO_REVIEW_FILE, {"candidates": []})
    if data["photo_candidates"]:
        photo_review = _update_photo_review(photo_review, data["photo_candidates"])
        PHOTO_REVIEW_FILE.write_text(json.dumps(photo_review, indent=2, default=str))
        print(f"  ✅ {len(data['photo_candidates'])} new photo candidate(s) queued for review")

    # Send email
    print("\n📧 Sending morning briefing email...")
    html = _render_email(data)
    _send_email(env, f"☀️ Morning Briefing — {data['today']}", html)

    # Send Telegram
    print("\n📱 Sending Telegram briefing...")
    _send_telegram_briefing(data)

    print(f"\n{'='*60}")
    print("✅ Morning briefing complete")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
