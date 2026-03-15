"""
Battleship Reset — Orchestrator
================================
The top-level growth coordinator. Sits above all bots, runs daily,
ensures every piece of the machine is aligned toward the same goal:
£3,000/month MRR within 90 days.

Hierarchy:
  orchestrator.py          ← you are here
      ├── brand_manager.py (PM) — sets weekly targets, measures actuals
      │       ├── marketing_bot.py  — content arc, ad copy
      │       └── seo_bot.py        — GBP progression
      ├── accounts_bot.py   — P&L (informs all decisions)
      └── tech_bot.py       — gaps, costs, revenue-gated recommendations

The orchestrator:
  1. Loads P&L (accounts_bot)
  2. Generates the brand PM brief (brand_manager in PM mode)
  3. Runs SEO task for the week
  4. Runs marketing daily review
  5. Runs tech bot gap check
  6. Sends a single "Command Report" digest to Will

Standalone:
    python3 skills/orchestrator.py --run           # full daily run
    python3 skills/orchestrator.py --brief         # print brand PM brief only
    python3 skills/orchestrator.py --status        # print all bot statuses

Called from cron / battleship_pipeline:
    from skills.orchestrator import run as run_orchestrator
    run_orchestrator(secrets, client_state)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT = Path(__file__).parent.parent

# ── Business constants ────────────────────────────────────────────────────────

TARGET_MRR       = 3000   # £3,000/month by Week 12
LAUNCH_DATE_ISO  = "2026-03-11"  # when the business officially started


def _weeks_since_launch() -> int:
    launch = datetime.fromisoformat(LAUNCH_DATE_ISO).replace(tzinfo=timezone.utc)
    return max(1, (datetime.now(timezone.utc) - launch).days // 7)


# ── Brand PM function ─────────────────────────────────────────────────────────

def generate_pm_brief(pnl: dict, seo_status: dict, tech_summary: dict,
                      arc_guidance: dict | None, client_state: dict) -> dict:
    """
    The brand manager's PM function. Takes real data from all bots and
    produces a weekly brief with measurable targets for each channel.

    Returns a dict used by the digest email and stored for reference.
    """
    week_num     = _weeks_since_launch()
    mrr          = pnl.get("mrr_estimate", 0)
    gap_to_target = max(0, TARGET_MRR - mrr)
    active_clients = pnl.get("active_clients", 0)
    total_spend  = pnl.get("total_spend", 0)
    net          = pnl.get("net", 0)
    seo_pct      = seo_status.get("completion_pct", 0)
    arc_phase    = (arc_guidance or {}).get("phase", "Problem Agitation")

    # Revenue trajectory
    clients_needed_route_a = max(0, int((gap_to_target / 89) + 0.99))  # ongoing @ £89/mo
    clients_needed_route_b = max(0, int((gap_to_target / 199) + 0.99)) # programme @ £199

    # Weekly targets — calibrated to week number
    if week_num <= 2:
        content_target = 5
        lead_target    = 0
        client_target  = 0
        focus          = "Foundation: GBP setup, brand identity, first content posts"
    elif week_num <= 4:
        content_target = 7
        lead_target    = 3
        client_target  = 0
        focus          = "Visibility: SEO completion, organic content volume, first leads"
    elif week_num <= 8:
        content_target = 7
        lead_target    = 5
        client_target  = 1
        focus          = "Conversion: first paying clients, review collection, referral ask"
    else:
        content_target = 5
        lead_target    = 10
        client_target  = 2
        focus          = "Scale: paid ads + organic compound + retention"

    # SEO priority this week
    seo_priority = "Complete GBP setup tasks" if seo_pct < 100 else "Weekly GBP post + review monitoring"

    # Marketing priority aligned to arc
    arc_priorities = {
        "Problem Agitation":    "Post content that names the pain. Before/after. 'I tried everything.'",
        "Why You've Failed":    "Explain the system failure, not willpower failure. Science angle.",
        "Science & System":     "Walking + cortisol + VO2 max. Data posts. Apple Watch stats.",
        "System + Proof":       "Client results (or Will's own). Specific numbers. Testimonials.",
        "Objection Crushing":   "Address price, time, age, doubt. Direct responses to objections.",
        "Direct CTA":           "Urgency, scarcity, direct offer. Founding member pricing.",
    }
    marketing_priority = arc_priorities.get(arc_phase, "Post consistently and engage.")

    return {
        "week":               week_num,
        "date":               datetime.now().strftime("%d %b %Y"),
        "focus":              focus,
        "mrr":                mrr,
        "gap_to_target":      gap_to_target,
        "active_clients":     active_clients,
        "total_spend":        total_spend,
        "net":                net,
        "clients_needed_a":   clients_needed_route_a,
        "clients_needed_b":   clients_needed_route_b,
        "content_target":     content_target,
        "lead_target":        lead_target,
        "client_target":      client_target,
        "arc_phase":          arc_phase,
        "seo_pct":            seo_pct,
        "seo_priority":       seo_priority,
        "marketing_priority": marketing_priority,
        "tech_free_wins":     tech_summary.get("free_available", 0),
        "tech_unlocked":      tech_summary.get("unlocked_at_mrr", 0),
    }


def _render_pm_brief_text(brief: dict) -> str:
    """Render PM brief as plain text for console output."""
    return f"""
╔══════════════════════════════════════════════════════════════╗
  BATTLESHIP RESET — WEEK {brief['week']} COMMAND BRIEF
  {brief['date']}
╚══════════════════════════════════════════════════════════════╝

GOAL: £{TARGET_MRR:,}/mo MRR   CURRENT: £{brief['mrr']:.0f}   GAP: £{brief['gap_to_target']:.0f}
NET P&L: £{brief['net']:.0f}   ACTIVE CLIENTS: {brief['active_clients']}   SPEND: £{brief['total_spend']:.0f}

WEEK {brief['week']} FOCUS
  {brief['focus']}

TO CLOSE THE GAP:
  Route A (ongoing @ £89/mo):    {brief['clients_needed_a']} more clients
  Route B (programme @ £199):    {brief['clients_needed_b']} more sales

THIS WEEK'S TARGETS
  Content pieces:  {brief['content_target']}
  Leads:           {brief['lead_target']}
  New clients:     {brief['client_target']}

SEO ({brief['seo_pct']}% complete)
  {brief['seo_priority']}

MARKETING (Arc: {brief['arc_phase']})
  {brief['marketing_priority']}

TECH
  Free wins available now: {brief['tech_free_wins']}
  Investments unlocked at current MRR: {brief['tech_unlocked']}
"""


# ── HTML email rendering ──────────────────────────────────────────────────────

def _render_command_report_html(brief: dict, seo_result: dict | None,
                                marketing_result: dict | None,
                                tech_report: str, pending_will: list) -> str:
    """Build the HTML for the orchestrator's daily command report email."""

    def _stat(label, value, color="#0a0a0a"):
        return (
            f'<td style="text-align:center;padding:0 16px 0 0;">'
            f'<p style="margin:0;font-size:22px;font-family:Georgia,serif;color:{color};">{value}</p>'
            f'<p style="margin:4px 0 0;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">{label}</p>'
            f'</td>'
        )

    net_color  = "#2a7a2a" if brief["net"] >= 0 else "#c41e3a"
    gap_color  = "#c41e3a" if brief["gap_to_target"] > 0 else "#2a7a2a"

    stats_html = (
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        + _stat("MRR", f"£{brief['mrr']:.0f}")
        + _stat("Gap to £3k", f"£{brief['gap_to_target']:.0f}", gap_color)
        + _stat("Net P&L", f"£{brief['net']:.0f}", net_color)
        + _stat("Clients", str(brief["active_clients"]))
        + _stat("Week", str(brief["week"]))
        + '</tr></table>'
    )

    # Targets table
    targets_html = f"""
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<tr style="background:#f5f5f5;"><th style="padding:6px 10px;text-align:left;">Target</th><th style="padding:6px 10px;text-align:left;">Goal</th></tr>
<tr><td style="padding:6px 10px;border-bottom:1px solid #eee;">Content pieces</td><td style="padding:6px 10px;border-bottom:1px solid #eee;">{brief['content_target']}/week</td></tr>
<tr><td style="padding:6px 10px;border-bottom:1px solid #eee;">Leads</td><td style="padding:6px 10px;border-bottom:1px solid #eee;">{brief['lead_target']}/week</td></tr>
<tr><td style="padding:6px 10px;">New clients</td><td style="padding:6px 10px;">{brief['client_target']}/week</td></tr>
</table>"""

    # Will's pending actions
    actions_html = ""
    if pending_will:
        items = "".join(f'<li style="margin-bottom:6px;">{a}</li>' for a in pending_will)
        actions_html = f'<ul style="margin:0;padding-left:20px;color:#555;font-size:13px;">{items}</ul>'
    else:
        actions_html = '<p style="color:#555;font-size:13px;margin:0;">No pending actions. All systems running autonomously.</p>'

    # SEO status
    seo_html = ""
    if seo_result:
        if seo_result.get("mode") == "ongoing":
            seo_html = f'<p style="font-size:13px;color:#555;margin:0;">Weekly GBP post drafted → paste into GBP dashboard (2 mins).</p>'
        else:
            seo_html = (
                f'<p style="font-size:13px;color:#555;margin:0;">'
                f'<strong>Task {seo_result.get("task_id")}: {seo_result.get("name")}</strong><br>'
                f'Action needed: {seo_result.get("will_action", "")}</p>'
            )

    # Marketing arc context
    marketing_html = f"""
<p style="font-size:13px;color:#555;margin:0;">
<strong>Arc Phase:</strong> {brief['arc_phase']}<br>
{brief['marketing_priority']}
</p>"""

    # Tech report (markdown → basic HTML)
    tech_html = tech_report.replace("\n### ", "<br><strong>").replace("\n- ", "<br>• ").replace("\n", "<br>")

    sections = [
        {"body": stats_html, "accent": True},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">Week {brief["week"]} Focus</h3><p style="font-size:13px;color:#555;margin:0;">{brief["focus"]}</p>'},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">Weekly Targets</h3>' + targets_html},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">SEO ({brief["seo_pct"]}% complete)</h3>' + (seo_html or '<p style="font-size:13px;color:#aaa;margin:0;">No SEO task this cycle.</p>')},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">Marketing Direction</h3>' + marketing_html},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">Actions Needed From You</h3>' + actions_html},
        {"body": f'<h3 style="margin:0 0 8px;font-size:14px;">Tech Backlog</h3><p style="font-size:12px;color:#777;margin:0;">{tech_html[:600]}</p>'},
    ]

    try:
        import sys
        sys.path.insert(0, str(VAULT_ROOT))
        from scripts.battleship_pipeline import render_internal_email
        return render_internal_email(
            title=f"Command Report — Week {brief['week']}",
            subtitle=f"Orchestrator · {brief['date']}",
            sections=sections,
        )
    except Exception:
        return ""


# ── Main orchestration run ────────────────────────────────────────────────────

def run(secrets: dict, client_state: dict):
    """
    Full daily orchestration run. Call this once per day.
    Order matters: accounts → PM brief → SEO → marketing → tech → report
    """
    print("\n🎯 ORCHESTRATOR — Daily Growth Run")
    print(f"   {datetime.now().strftime('%A %d %B %Y, %H:%M')}\n")

    import sys
    sys.path.insert(0, str(VAULT_ROOT))

    # ── Step 1: P&L ──────────────────────────────────────────────────────────
    print("  [1/6] Accounts…")
    try:
        from skills.accounts_bot import get_pnl, scan_receipts
        scan_receipts(secrets)
        pnl = get_pnl(client_state)
        print(f"        MRR: £{pnl['mrr_estimate']:.0f} · Net: £{pnl['net']:.0f} · Spend: £{pnl['total_spend']:.0f}")
    except Exception as e:
        print(f"        ⚠️  Accounts error: {e}")
        pnl = {"mrr_estimate": 0, "net": 0, "total_spend": 0, "active_clients": 0,
               "revenue": 0, "ad_spend": 0, "gap_to_target": TARGET_MRR}

    # ── Step 2: Marketing arc guidance ───────────────────────────────────────
    print("  [2/6] Marketing arc…")
    arc_guidance = None
    try:
        from skills.marketing_bot import get_current_arc_guidance
        arc_guidance = get_current_arc_guidance()
        print(f"        Arc: {arc_guidance.get('phase', 'N/A')}")
    except Exception as e:
        print(f"        ⚠️  Marketing arc error: {e}")

    # ── Step 3: SEO task ──────────────────────────────────────────────────────
    print("  [3/6] SEO…")
    seo_result = None
    seo_status = {"completion_pct": 0, "pending_will_actions": []}
    try:
        from skills.seo_bot import run_weekly_task, get_status_report
        seo_result = run_weekly_task(secrets, arc_guidance)
        seo_status = get_status_report()
        print(f"        SEO: {seo_status['completion_pct']}% complete")
    except Exception as e:
        print(f"        ⚠️  SEO error: {e}")

    # ── Step 4: Tech bot ──────────────────────────────────────────────────────
    print("  [4/6] Tech backlog…")
    tech_summary = {}
    tech_report  = ""
    try:
        from skills.tech_bot import run as run_tech, generate_report
        tech_summary = run_tech(secrets, pnl)
        tech_report  = generate_report(pnl)
    except Exception as e:
        print(f"        ⚠️  Tech bot error: {e}")

    # ── Step 5: Brand PM brief ────────────────────────────────────────────────
    print("  [5/6] Brand PM brief…")
    brief = generate_pm_brief(pnl, seo_status, tech_summary, arc_guidance, client_state)
    print(_render_pm_brief_text(brief))

    # ── Step 6: Marketing daily review ───────────────────────────────────────
    print("  [6/6] Marketing daily review…")
    marketing_result = None
    try:
        from skills.marketing_bot import run_daily_review
        marketing_result = run_daily_review(secrets, client_state)
    except Exception as e:
        print(f"        ⚠️  Marketing review error: {e}")

    # ── Command report email ──────────────────────────────────────────────────
    # Collect all pending actions for Will
    pending_will = []
    if seo_status.get("pending_will_actions"):
        pending_will.extend(seo_status["pending_will_actions"])
    if tech_summary.get("free_available", 0) > 0:
        pending_will.append(f"Tech: {tech_summary['free_available']} free tool(s) ready to set up — run: python3 skills/tech_bot.py --backlog")

    try:
        from scripts.battleship_pipeline import send_email
        html = _render_command_report_html(brief, seo_result, marketing_result, tech_report, pending_will)
        if html:
            plain = _render_pm_brief_text(brief)
            send_email(
                secrets,
                to="will@battleship.me",
                subject=f"[COMMAND] Week {brief['week']} · MRR £{pnl['mrr_estimate']:.0f} · Gap £{pnl['gap_to_target']:.0f}",
                plain_body=plain,
                html_body=html,
            )
            print("\n  ✅ Command report sent → will@battleship.me")
    except Exception as e:
        print(f"\n  ⚠️  Command report email failed: {e}")

    print("\n🎯 Orchestrator run complete.\n")
    return brief


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()

    state_file = VAULT_ROOT / "clients" / "state.json"
    client_state = json.loads(state_file.read_text()) if state_file.exists() else {"clients": {}}

    parser = argparse.ArgumentParser(description="Battleship Orchestrator")
    parser.add_argument("--run",    action="store_true", help="Full daily orchestration run")
    parser.add_argument("--brief",  action="store_true", help="Print brand PM brief only")
    parser.add_argument("--status", action="store_true", help="Print all bot statuses")
    args = parser.parse_args()

    if args.run:
        run(secrets, client_state)

    elif args.brief:
        sys.path.insert(0, str(VAULT_ROOT))
        try:
            from skills.accounts_bot import get_pnl
            from skills.seo_bot import get_status_report
            from skills.tech_bot import get_summary
            from skills.marketing_bot import get_current_arc_guidance
            pnl          = get_pnl(client_state)
            seo_status   = get_status_report()
            tech_summary = get_summary(pnl)
            arc_guidance = get_current_arc_guidance()
            brief        = generate_pm_brief(pnl, seo_status, tech_summary, arc_guidance, client_state)
            print(_render_pm_brief_text(brief))
        except Exception as e:
            print(f"Error generating brief: {e}")

    elif args.status:
        sys.path.insert(0, str(VAULT_ROOT))
        print("\n  Bot Status Summary")
        print("  " + "─" * 40)
        try:
            from skills.seo_bot import get_status_report
            s = get_status_report()
            print(f"  SEO:        {s['completion_pct']}% complete · Task: {s['current_task_name']}")
        except Exception as e:
            print(f"  SEO:        ⚠️  {e}")
        try:
            from skills.tech_bot import get_summary
            t = get_summary()
            print(f"  Tech:       {t['total_gaps']} gaps · {t['free_available']} free wins available")
        except Exception as e:
            print(f"  Tech:       ⚠️  {e}")
        try:
            from skills.marketing_bot import get_current_arc_guidance
            a = get_current_arc_guidance()
            print(f"  Marketing:  Arc phase '{a.get('phase', 'N/A')}'")
        except Exception as e:
            print(f"  Marketing:  ⚠️  {e}")
        print()

    else:
        parser.print_help()
