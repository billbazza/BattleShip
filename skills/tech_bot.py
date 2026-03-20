"""
Battleship Reset — Tech Bot
============================
Identifies technology gaps across all bots, costs them, revenue-gates them,
and reports recommendations to the orchestrator.

Core principle: Tech investment only happens when the business can afford it.
Every gap gets a "unlock at £X MRR" threshold. Current free alternatives are
always documented so the bot never blocks on missing paid tools.

Standalone:
    python3 skills/tech_bot.py --backlog          # show all gaps
    python3 skills/tech_bot.py --report           # generate report email
    python3 skills/tech_bot.py --flag "description" --cost 25  # flag a new gap

Called from any bot:
    from skills.tech_bot import flag_gap
    flag_gap("seo_bot", "GBP API for automated posts", monthly_cost=0, free_alternative="Manual paste")

Called from orchestrator:
    from skills.tech_bot import run as run_tech
    run_tech(secrets, pnl)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT     = Path(__file__).parent.parent
BACKLOG_FILE   = VAULT_ROOT / "brand" / "Marketing" / "tech_backlog.json"

# ── Pre-seeded gap library ─────────────────────────────────────────────────────
# Known gaps identified during build. Others added dynamically.

INITIAL_GAPS = [
    {
        "id": "gap_001",
        "reported_by": "seo_bot",
        "title": "GBP Automated Posting",
        "description": "Google Business Profile has no free public API for posts. Bot drafts posts; Will pastes manually.",
        "estimated_monthly_cost_gbp": 0,
        "paid_solution": "Semrush Local (£35/mo) or BrightLocal (£29/mo) can post to GBP automatically.",
        "free_alternative": "Bot drafts post → Will copies from outputs/ into GBP dashboard. 2 minutes/week.",
        "revenue_unlock_gbp": 1000,
        "status": "workaround_active",
        "impact": "low",  # manual paste is easy enough
        "category": "SEO",
    },
    {
        "id": "gap_002",
        "reported_by": "seo_bot",
        "title": "GBP Review Monitoring",
        "description": "No automated way to detect new GBP reviews without paid tools. Will must check manually.",
        "estimated_monthly_cost_gbp": 29,
        "paid_solution": "BrightLocal (£29/mo) monitors reviews and alerts via email.",
        "free_alternative": "Set up Google Alerts for 'battleshipreset.com' + manual weekly check in GBP dashboard.",
        "revenue_unlock_gbp": 500,
        "status": "workaround_active",
        "impact": "medium",
        "category": "SEO",
    },
    {
        "id": "gap_003",
        "reported_by": "facebook_bot",
        "title": "Instagram Scheduling",
        "description": "Meta API allows posting but not scheduling. All posts are immediate.",
        "estimated_monthly_cost_gbp": 0,
        "paid_solution": "Buffer (£15/mo) or Later (£16/mo) enable scheduling.",
        "free_alternative": "Post immediately at optimal time (7-9am or 7-9pm UK). Bot calculates best window.",
        "revenue_unlock_gbp": 750,
        "status": "workaround_active",
        "impact": "low",
        "category": "Social",
    },
    {
        "id": "gap_004",
        "reported_by": "marketing_bot",
        "title": "Landing Page A/B Testing",
        "description": "battleshipreset.com (Carrd) has no built-in A/B testing. Can't test headline variants automatically.",
        "estimated_monthly_cost_gbp": 35,
        "paid_solution": "Google Optimize (free but deprecated) or VWO (£35/mo) or Unbounce (£55/mo).",
        "free_alternative": "Manual variant testing: alternate headlines weekly, track CTR from UTM params.",
        "revenue_unlock_gbp": 1500,
        "status": "workaround_active",
        "impact": "medium",
        "category": "Conversion",
    },
    {
        "id": "gap_005",
        "reported_by": "orchestrator",
        "title": "CRM / Pipeline Management",
        "description": "Client tracking is in a JSON file. No visual pipeline, no automated follow-up sequences beyond email.",
        "estimated_monthly_cost_gbp": 15,
        "paid_solution": "HubSpot Free (genuinely free) or Pipedrive (£15/mo).",
        "free_alternative": "Current clients/ JSON + Flask dashboard. Sufficient below 20 clients.",
        "revenue_unlock_gbp": 1000,
        "status": "workaround_active",
        "impact": "low",
        "category": "CRM",
    },
    {
        "id": "gap_006",
        "reported_by": "marketing_bot",
        "title": "Broadcast Email / Mailing List",
        "description": "No broadcast list for leads. Not needed until a lead magnet exists and list > 50 people. Mailchimp is NOT free (14-day trial only).",
        "estimated_monthly_cost_gbp": 0,
        "paid_solution": "Brevo (brevo.com) — genuinely free forever, 300 emails/day, unlimited contacts, UK-compatible, has API.",
        "free_alternative": "Not needed yet. Tally + pipeline handles all current flows. Set up Brevo when lead magnet is built and list > 50 contacts.",
        "revenue_unlock_gbp": 0,
        "status": "not_yet_needed",
        "impact": "medium",
        "category": "Email",
    },
    {
        "id": "gap_007",
        "reported_by": "accounts_bot",
        "title": "Accounting Software",
        "description": "Expenses tracked in finances.md via accounts_bot. No manual data entry — will API-migrate to Zoho Books when revenue justifies it.",
        "estimated_monthly_cost_gbp": 10,
        "paid_solution": "Zoho Books UK (books.zoho.eu) — £10/mo, HMRC Making Tax Digital compliant, API available for automated import from accounts_bot. No manual copying needed.",
        "free_alternative": "finances.md + accounts_bot is the source of truth. API-migrate everything in one automated batch when ready. Do NOT copy data manually.",
        "revenue_unlock_gbp": 300,
        "status": "workaround_active",
        "impact": "medium",
        "category": "Finance",
    },
    {
        "id": "gap_008",
        "reported_by": "seo_bot",
        "title": "Keyword Rank Tracking",
        "description": "No way to track where battleshipreset.com ranks for target keywords automatically.",
        "estimated_monthly_cost_gbp": 0,
        "paid_solution": "Semrush (£90/mo), Ahrefs (£79/mo), Ubersuggest (£12/mo).",
        "free_alternative": "Google Search Console (free) — once site gets traffic. Manual search checks weekly.",
        "revenue_unlock_gbp": 500,
        "status": "workaround_active",
        "impact": "low",
        "category": "SEO",
    },
]


# ── State management ──────────────────────────────────────────────────────────

def _load_backlog() -> dict:
    if BACKLOG_FILE.exists():
        return json.loads(BACKLOG_FILE.read_text())
    # Seed with initial gaps
    backlog = {"gaps": INITIAL_GAPS, "created": datetime.now(timezone.utc).isoformat()}
    _save_backlog(backlog)
    return backlog


def _save_backlog(b: dict):
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKLOG_FILE.write_text(json.dumps(b, indent=2))


# ── Public API ────────────────────────────────────────────────────────────────

def flag_gap(
    reported_by: str,
    title: str,
    description: str,
    estimated_monthly_cost_gbp: float = 0,
    free_alternative: str = "Unknown",
    revenue_unlock_gbp: float = 500,
    impact: str = "medium",
    category: str = "Other",
):
    """
    Any bot can call this to flag a technology gap.
    Gap is added to backlog if not already present.
    """
    backlog = _load_backlog()
    existing_titles = [g["title"].lower() for g in backlog["gaps"]]
    if title.lower() in existing_titles:
        return  # already tracked

    gap_id = f"gap_{len(backlog['gaps']) + 1:03d}"
    backlog["gaps"].append({
        "id":                         gap_id,
        "reported_by":                reported_by,
        "title":                      title,
        "description":                description,
        "estimated_monthly_cost_gbp": estimated_monthly_cost_gbp,
        "paid_solution":              "",
        "free_alternative":           free_alternative,
        "revenue_unlock_gbp":         revenue_unlock_gbp,
        "status":                     "identified",
        "impact":                     impact,
        "category":                   category,
        "flagged_date":               datetime.now(timezone.utc).isoformat(),
    })
    _save_backlog(backlog)
    print(f"  🔧 Tech gap flagged: {title}")


def get_unlocked_recommendations(current_mrr: float) -> list[dict]:
    """Return gaps whose revenue threshold is met by current MRR."""
    backlog = _load_backlog()
    return [
        g for g in backlog["gaps"]
        if g.get("revenue_unlock_gbp", 9999) <= current_mrr
        and g.get("status") not in ("implemented", "dismissed")
        and g.get("estimated_monthly_cost_gbp", 0) > 0
    ]


def get_free_recommendations() -> list[dict]:
    """Return gaps with free solutions available right now."""
    backlog = _load_backlog()
    return [
        g for g in backlog["gaps"]
        if g.get("status") == "recommended_free"
    ]


def get_summary(pnl: dict | None = None) -> dict:
    """Return a summary for the orchestrator/brand PM."""
    backlog   = _load_backlog()
    gaps      = backlog["gaps"]
    mrr       = (pnl or {}).get("mrr_estimate", 0)

    total_gaps        = len(gaps)
    free_available    = len(get_free_recommendations())
    unlocked          = len(get_unlocked_recommendations(mrr))
    total_monthly_cost = sum(g.get("estimated_monthly_cost_gbp", 0) for g in gaps
                             if g.get("status") not in ("implemented", "dismissed"))
    high_impact       = [g for g in gaps if g.get("impact") == "high" and g.get("status") != "implemented"]

    return {
        "total_gaps":            total_gaps,
        "free_available":        free_available,
        "unlocked_at_mrr":       unlocked,
        "current_mrr":           mrr,
        "total_monthly_if_all":  total_monthly_cost,
        "high_impact_gaps":      [g["title"] for g in high_impact],
    }


def generate_report(pnl: dict | None = None) -> str:
    """Generate a markdown tech report for inclusion in digest or email."""
    backlog  = _load_backlog()
    gaps     = backlog["gaps"]
    mrr      = (pnl or {}).get("mrr_estimate", 0)
    summary  = get_summary(pnl)

    lines = [
        "## Tech Backlog Report",
        f"*MRR: £{mrr:.0f} · Gaps tracked: {summary['total_gaps']}*\n",
    ]

    # Free wins available now
    free = get_free_recommendations()
    if free:
        lines.append("### ✅ Free Wins — Available Now")
        for g in free:
            lines.append(f"- **{g['title']}** ({g['category']}): {g['free_alternative']}")
        lines.append("")

    # Unlocked by current MRR
    unlocked = get_unlocked_recommendations(mrr)
    if unlocked:
        lines.append(f"### 🔓 Unlocked at Current MRR (£{mrr:.0f})")
        for g in unlocked:
            lines.append(f"- **{g['title']}** — £{g['estimated_monthly_cost_gbp']:.0f}/mo: {g['paid_solution']}")
        lines.append("")

    # Locked gaps with thresholds
    locked = [
        g for g in gaps
        if g.get("revenue_unlock_gbp", 0) > mrr
        and g.get("status") not in ("implemented", "dismissed")
        and g.get("estimated_monthly_cost_gbp", 0) > 0
    ]
    if locked:
        lines.append("### 🔒 Locked — Revenue Threshold Not Met")
        for g in sorted(locked, key=lambda x: x.get("revenue_unlock_gbp", 0)):
            lines.append(
                f"- **{g['title']}** — £{g['estimated_monthly_cost_gbp']:.0f}/mo "
                f"(unlock at £{g['revenue_unlock_gbp']:.0f} MRR): {g['description'][:80]}"
            )
        lines.append("")

    # Active workarounds summary
    workarounds = [g for g in gaps if g.get("status") == "workaround_active"]
    if workarounds:
        lines.append(f"### 🔄 Active Workarounds ({len(workarounds)})")
        for g in workarounds:
            lines.append(f"- {g['title']}: {g['free_alternative']}")

    return "\n".join(lines)


FREE_WIN_GUIDES = {
}


def send_tech_guide_email(secrets: dict):
    """
    Send a step-by-step guide email to Will for the free tech wins.
    Sent once — tracked in orchestrator state so it doesn't repeat.
    """
    free_wins = get_free_recommendations()
    if not free_wins:
        return

    guide_sections_html = []
    guide_sections_plain = []

    for gap in free_wins:
        guide = FREE_WIN_GUIDES.get(gap["title"])
        if not guide:
            continue

        steps_html = "".join(
            f'<li style="margin-bottom:8px;font-size:13px;color:#333;">{s}</li>'
            for s in guide["steps"]
        )
        section_html = (
            f'<h3 style="margin:0 0 4px;font-size:15px;color:#0a0a0a;">{guide["title"]}</h3>'
            f'<p style="font-size:11px;color:#aaa;margin:0 0 8px;">⏱ {guide["time"]}</p>'
            f'<p style="font-size:13px;color:#555;margin:0 0 10px;"><strong>Why:</strong> {guide["why"]}</p>'
            f'<ol style="margin:0 0 10px;padding-left:20px;">{steps_html}</ol>'
            f'<p style="font-size:12px;color:#888;font-style:italic;margin:0;">{guide["reply_prompt"]}</p>'
        )
        guide_sections_html.append({"body": section_html})

        steps_plain = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(guide["steps"]))
        guide_sections_plain.append(
            f"{guide['title']} ({guide['time']})\n"
            f"Why: {guide['why']}\n\n{steps_plain}\n\n{guide['reply_prompt']}"
        )

    if not guide_sections_html:
        return

    plain = (
        "FREE TECH WINS — Set These Up Now\n\n"
        + "\n\n---\n\n".join(guide_sections_plain)
        + "\n\nReply to this email with any question and I'll walk you through it."
    )

    try:
        import sys
        sys.path.insert(0, str(VAULT_ROOT))
        from scripts.battleship_pipeline import render_internal_email, send_email

        intro = {
            "body": (
                '<p style="font-size:14px;color:#333;margin:0 0 8px;">'
                f'You have <strong>{len(free_wins)} free tech wins</strong> available right now — '
                'no cost, just 15-20 minutes each. These will save you time and keep you HMRC-compliant.</p>'
                '<p style="font-size:13px;color:#777;margin:0;">'
                'Reply to this email with any question and I\'ll walk you through it step by step.</p>'
            )
        }
        sections = [intro] + guide_sections_html

        html = render_internal_email(
            title="Free Tech Wins — Do These Now",
            subtitle="Tech Bot · Action Required",
            sections=sections,
        )
        send_email(
            secrets,
            to="will@battleship.me",
            subject=f"[TECH] Tech backlog — {len(free_wins)} action(s) available now (reply if stuck)",
            plain_body=plain,
            html_body=html,
        )
        print("  ✅ Tech guide email sent → will@battleship.me")
    except Exception as e:
        print(f"  ⚠️  Tech guide email failed: {e}")


# ── Entry point ────────────────────────────────────────────────────────────────

def run(secrets: dict, pnl: dict | None = None):
    """Called from orchestrator. Ensures backlog is seeded and returns summary."""
    try:
        backlog = _load_backlog()  # seeds if first run
        summary = get_summary(pnl)
        print(f"  🔧 Tech backlog: {summary['total_gaps']} gaps, "
              f"{summary['free_available']} free wins available, "
              f"{summary['unlocked_at_mrr']} unlocked at current MRR")
        return summary
    except Exception as e:
        print(f"  ⚠️  Tech bot error: {e}")
        return {}


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Battleship Tech Bot")
    parser.add_argument("--backlog", action="store_true", help="Show full tech backlog")
    parser.add_argument("--report",  action="store_true", help="Generate tech report")
    parser.add_argument("--flag",    type=str,            help="Flag a new gap (description)")
    parser.add_argument("--cost",    type=float, default=0, help="Monthly cost in GBP for --flag")
    parser.add_argument("--unlock",  type=float, default=500, help="MRR threshold to unlock for --flag")
    args = parser.parse_args()

    if args.backlog:
        backlog = _load_backlog()
        for g in backlog["gaps"]:
            status_icon = {"implemented": "✅", "workaround_active": "🔄",
                           "recommended_free": "🆓", "identified": "🔍"}.get(g.get("status", ""), "❓")
            print(f"  {status_icon} [{g['category']}] {g['title']}")
            print(f"     Cost: £{g.get('estimated_monthly_cost_gbp', 0):.0f}/mo | "
                  f"Unlock at: £{g.get('revenue_unlock_gbp', 0):.0f} MRR")
            print(f"     Workaround: {g.get('free_alternative', 'None')[:80]}")
            print()

    elif args.report:
        print(generate_report())

    elif args.flag:
        flag_gap(
            reported_by="manual",
            title=args.flag,
            description=args.flag,
            estimated_monthly_cost_gbp=args.cost,
            revenue_unlock_gbp=args.unlock,
        )

    else:
        parser.print_help()
