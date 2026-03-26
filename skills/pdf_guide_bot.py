"""
SOVEREIGN — PDF Guide Bot (Stream A)
======================================
Generates and sells PDF guides about Claude Code, AI automation,
and building autonomous systems. Will's lived expertise, packaged.

Responsibilities:
  1. Generate guide content via Claude API (one per run to control cost)
  2. Render to styled PDF via scripts/pdf_gen.py
  3. Track in SQLite (guides + guide_sales tables)
  4. Sync sales data from Stripe (phase 1) / Lemon Squeezy (phase 2)
  5. Store buy URLs in bot_state for cross-promotion by other bots

Called from pipeline:
    from skills.pdf_guide_bot import run as run_guides
    run_guides(secrets, state, VAULT_ROOT)

Standalone:
    python3 skills/pdf_guide_bot.py --dry-run     # generate PDFs locally, no upload
    python3 skills/pdf_guide_bot.py --generate     # force generate next guide
    python3 skills/pdf_guide_bot.py --status        # print guide status + sales
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

VAULT_ROOT = Path(__file__).parent.parent
STATE_FILE = VAULT_ROOT / "clients" / "pdf_guide_state.json"
GUIDES_DIR = VAULT_ROOT / "SOVEREIGN" / "products" / "live"


# ── Guide Specifications ──────────────────────────────────────────────────────

GUIDE_SPECS = [
    {
        "id": "guide_claude_agent",
        "title": "Build Your First AI Agent with Claude Code",
        "subtitle": "A step-by-step guide for non-developers",
        "slug": "claude-code-ai-agent",
        "price_pence": 799,
        "sections": [
            {
                "heading": "What Is Claude Code (And Why It Matters)",
                "prompt": (
                    "Explain what Claude Code is in plain English. Not the marketing version — "
                    "the real version. What it actually does on your machine, how it differs from "
                    "ChatGPT, why it's a step change for non-developers. Mention OpenClaw (the open-source "
                    "release). Keep it practical — no hype, no jargon. 400-500 words."
                ),
            },
            {
                "heading": "Setting Up Your First Project",
                "prompt": (
                    "Walk through setting up a Claude Code project from scratch. Cover: installing "
                    "Claude Code, creating a project folder, writing your first CLAUDE.md file "
                    "(explain what it is and why it matters), and running your first command. "
                    "Include example CLAUDE.md content. Assume the reader has a Mac and basic "
                    "terminal comfort but is NOT a developer. 500-600 words."
                ),
            },
            {
                "heading": "Building a Simple Automation",
                "prompt": (
                    "Guide the reader through building their first real automation: a script that "
                    "monitors a folder for new files and processes them automatically. Use Python "
                    "as the language (Claude Code will write it). Show the conversation flow — "
                    "what to ask Claude, how to iterate, how to test. The reader should have "
                    "a working automation by the end of this section. 600-700 words."
                ),
            },
            {
                "heading": "Running It on a Schedule",
                "prompt": (
                    "Explain how to make the automation run automatically using cron (Mac/Linux) "
                    "or launchd (Mac). Cover: writing a cron entry, basic launchd plist, "
                    "environment variables, and checking logs. Include a real working example. "
                    "400-500 words."
                ),
            },
            {
                "heading": "Common Mistakes and How to Avoid Them",
                "prompt": (
                    "List the 7 most common mistakes people make when starting with Claude Code. "
                    "For each: what they do wrong, why it fails, and the fix. Draw from real "
                    "experience (not theory). Include: context window limits, CLAUDE.md neglect, "
                    "over-prompting, not testing incrementally, ignoring error messages, "
                    "trying to do too much at once, not using git. 500-600 words."
                ),
            },
            {
                "heading": "What to Build Next",
                "prompt": (
                    "Give 5 concrete project ideas the reader can build next, ordered by complexity. "
                    "For each: a one-paragraph description, estimated time, and what they'll learn. "
                    "Include: email auto-responder, content scheduler, expense tracker, "
                    "simple web dashboard, and a multi-step pipeline. End with encouragement — "
                    "the reader now has a real skill. 400-500 words."
                ),
            },
        ],
    },
    {
        "id": "guide_autonomous_biz",
        "title": "The Autonomous Business Playbook",
        "subtitle": "How I built a self-running coaching business with AI",
        "slug": "autonomous-business-playbook",
        "price_pence": 1299,
        "sections": [
            {
                "heading": "The Starting Point",
                "prompt": (
                    "Tell Will's real story. 47, desk job, transformed himself — lost 3 stone, "
                    "fitness age 55 to 17. Decided to turn the system into a coaching business "
                    "(Battleship Reset). But didn't want to spend all day on admin, marketing, "
                    "and client management. Decided to build an AI system to run it. "
                    "Be honest about the motivation: not 'passive income' fantasy, but genuine "
                    "need to keep the business sustainable without burning out. 400-500 words."
                ),
            },
            {
                "heading": "The Architecture",
                "prompt": (
                    "Describe the full Battleship Reset autonomous system. The pipeline: "
                    "Tally intake form → Claude auto-diagnosis → personalised 12-week plan → "
                    "Stripe payment → onboarding email sequence → weekly check-ins via Google Sheets → "
                    "education drips → week 8 challenge → week 12 close + phase 2 pitch. "
                    "All running on a Mac Mini via launchd. Flask dashboard for oversight. "
                    "Cloudflare tunnel for webhooks. This is real — show the full flow. 600-700 words."
                ),
            },
            {
                "heading": "The Content Engine",
                "prompt": (
                    "Explain the content pipeline: marketing_bot generates strategy reviews, "
                    "facebook_bot creates and queues posts (3x/week), ideas bank with approval flow, "
                    "newsletter bot (The Operator) for broader audience. Arc phases that rotate "
                    "messaging. All coordinated, all autonomous. What works, what doesn't. "
                    "Be honest: the content is running but hasn't generated customers yet — "
                    "all sales came from word of mouth. That's a real lesson. 500-600 words."
                ),
            },
            {
                "heading": "The Tools and What They Cost",
                "prompt": (
                    "List every tool in the stack with real costs. Anthropic API (~£40/mo), "
                    "Stripe (% per transaction), Cloudflare (free), Beehiiv (free tier), "
                    "Google Workspace, domain costs. Total monthly burn. Be transparent about "
                    "what's free, what's cheap, what's expensive. Include the cost of the "
                    "Mac Mini itself. 400-500 words."
                ),
            },
            {
                "heading": "What Actually Worked (And What Didn't)",
                "prompt": (
                    "Honest retrospective. What worked: the intake-to-plan pipeline is flawless, "
                    "quiz-to-paid conversion is 100% (when people reach it), the education drip "
                    "sequence keeps clients engaged. What didn't work: organic content has zero "
                    "tracked impressions, Facebook posts aren't driving traffic, the newsletter "
                    "has zero subscribers, arc phase advancement was buggy. "
                    "The system works mechanically but has no audience. That's the lesson. 500-600 words."
                ),
            },
            {
                "heading": "How to Build Your Own Version",
                "prompt": (
                    "Practical steps for the reader to build a similar system for their own business. "
                    "Start with: what's your one offer? Build the intake form first. Then the "
                    "auto-response. Then the payment link. Then the follow-up sequence. "
                    "Each step is one Claude Code session. Don't build the marketing engine "
                    "until you have paying customers. That was the mistake. 500-600 words."
                ),
            },
        ],
    },
    {
        "id": "guide_mac_mini",
        "title": "The Mac Mini Income Machine",
        "subtitle": "Setting up always-on AI automation for under £500",
        "slug": "mac-mini-income-machine",
        "price_pence": 999,
        "sections": [
            {
                "heading": "Why a Mac Mini",
                "prompt": (
                    "Explain why a Mac Mini is the ideal always-on automation machine. "
                    "Low power consumption (~15W idle), silent, reliable, macOS has launchd "
                    "(better than cron), ARM chips are efficient. Compare to: VPS (monthly cost "
                    "adds up), Raspberry Pi (underpowered for AI API calls + PDF generation), "
                    "old laptop (unreliable, battery issues). A refurbished M1 Mac Mini is "
                    "under £400. It pays for itself in month 2. 400-500 words."
                ),
            },
            {
                "heading": "Initial Setup",
                "prompt": (
                    "Walk through the setup: unbox, connect to power + ethernet (not WiFi — "
                    "reliability matters), enable auto-login, disable sleep, enable SSH. "
                    "Install Homebrew, Python 3.11+, git. Set up a dedicated user account "
                    "for the automation (not your personal account). Create the project "
                    "directory structure. 400-500 words."
                ),
            },
            {
                "heading": "Environment and Secrets",
                "prompt": (
                    "How to manage API keys and secrets safely. Options: macOS Keychain "
                    "(most secure), .env file with restricted permissions (simplest), "
                    "1Password CLI (enterprise). Show a working .env pattern with "
                    "sourcing in scripts. Explain why secrets must NEVER go in git. "
                    "Include a real example of loading secrets in Python. 400-500 words."
                ),
            },
            {
                "heading": "Launchd: The Always-On Engine",
                "prompt": (
                    "Explain launchd (macOS's process supervisor) and why it's better than cron "
                    "for this use case. Walk through writing a .plist file, loading it, "
                    "checking status, reading logs. Cover: StartInterval vs StartCalendarInterval, "
                    "KeepAlive, StandardOutPath/StandardErrorPath. Include 2 real working "
                    "plist examples (one for a periodic script, one for an always-on service). "
                    "500-600 words."
                ),
            },
            {
                "heading": "Cloudflare Tunnel: Webhooks Without Port Forwarding",
                "prompt": (
                    "Explain the problem: external services (Stripe, Tally, etc.) need to "
                    "send webhooks to your machine. You don't want to open ports on your router. "
                    "Solution: Cloudflare Tunnel. Walk through: install cloudflared, "
                    "create a tunnel, point a subdomain at localhost:5100, run as a launchd service. "
                    "Include real working config. Explain why this is free and secure. 500-600 words."
                ),
            },
            {
                "heading": "Monitoring and Self-Healing",
                "prompt": (
                    "How to make sure the machine keeps running without you checking it. "
                    "Cover: heartbeat files, a simple watchdog script, email alerts via Resend "
                    "(free tier), disk space monitoring, log rotation. Show a working Python "
                    "watchdog that checks if your main process is alive and restarts it if not. "
                    "End with: the goal is to forget the machine exists. 400-500 words."
                ),
            },
        ],
    },
]


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "guides": {},
        "last_generation_date": None,
        "total_revenue_pence": 0,
    }


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Content generation ────────────────────────────────────────────────────────

def _generate_guide_content(spec: dict, secrets: dict) -> list[dict]:
    """
    Generate all sections for a guide via Claude API.
    Returns list of {"heading": ..., "body": ...} dicts.
    """
    api_key = (secrets.get("ANTHROPIC_API_KEY") or
               secrets.get("ANTHROPIC_KEY") or
               secrets.get("anthropic"))
    client = anthropic.Anthropic(api_key=api_key)

    sections = []
    for sec in spec["sections"]:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": (
                f"You are writing a section for a paid PDF guide titled "
                f"\"{spec['title']}\" by Will Barratt.\n\n"
                f"Section heading: {sec['heading']}\n\n"
                f"Instructions: {sec['prompt']}\n\n"
                f"Rules:\n"
                f"- Write in Will's voice: direct, honest, no bullshit, first person where natural\n"
                f"- Use short paragraphs (2-4 sentences max)\n"
                f"- Include specific details and real examples — no hand-waving\n"
                f"- Use **bold** for key terms or emphasis (markdown bold)\n"
                f"- Use bullet points (- ) where a list is genuinely clearer\n"
                f"- No emojis, no exclamation marks, no 'let's go!' energy\n"
                f"- This is a paid guide — the reader expects depth, not fluff\n"
                f"- Write ONLY the section body text. No heading, no intro sentence restating the heading."
            )}]
        )
        body = msg.content[0].text.strip()
        sections.append({"heading": sec["heading"], "body": body})
        print(f"    Generated: {sec['heading']}")

    return sections


# ── PDF rendering ─────────────────────────────────────────────────────────────

def _render_pdf(spec: dict, sections: list[dict]) -> Path:
    """Render a guide to PDF using scripts/pdf_gen.py."""
    sys.path.insert(0, str(VAULT_ROOT))
    from scripts.pdf_gen import generate_guide_pdf

    output_path = GUIDES_DIR / f"{spec['slug']}.pdf"

    # Build cross-promo URLs for back page
    other_guides = [
        {"title": s["title"], "url": "battleshipreset.com"}
        for s in GUIDE_SPECS if s["id"] != spec["id"]
    ]

    generate_guide_pdf(
        title=spec["title"],
        subtitle=spec["subtitle"],
        author="Will Barratt",
        sections=sections,
        output_path=output_path,
        guide_urls=other_guides,
    )
    return output_path


# ── DB sync ───────────────────────────────────────────────────────────────────

def _sync_guide_to_db(spec: dict, pdf_path: Path, status: str = "draft"):
    """Upsert guide record into SQLite."""
    sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as db

    db.upsert_guide({
        "id": spec["id"],
        "title": spec["title"],
        "slug": spec["slug"],
        "price_pence": spec["price_pence"],
        "status": status,
        "pdf_path": str(pdf_path),
    })


def _sync_buy_urls_to_bot_state():
    """Write guide buy URLs to bot_state so other bots can read them for promos."""
    sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as db

    guides = db.get_guides(status="published")
    promos = [
        {"id": g["id"], "title": g["title"], "buy_url": g.get("buy_url", ""),
         "price": f"£{g['price_pence'] / 100:.2f}"}
        for g in guides if g.get("buy_url")
    ]
    db.set_bot_state("guide_promos", json.dumps(promos))


# ── Main entry ────────────────────────────────────────────────────────────────

def run(secrets: dict, state: dict = None, vault_root: Path = VAULT_ROOT,
        dry_run: bool = False, force: bool = False) -> None:
    """
    Called from battleship_pipeline.py.
    Generates one missing guide per run (to control API cost).
    """
    guide_state = _load_state()
    generated = guide_state.get("guides", {})

    # Find the first guide that hasn't been generated yet
    pending = [s for s in GUIDE_SPECS if s["id"] not in generated]

    if not pending:
        # All guides generated — just sync promos
        _sync_buy_urls_to_bot_state()
        return

    if not force:
        # Limit: one guide per day max
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if guide_state.get("last_generation_date") == today:
            print("  ℹ️  Guide already generated today — skipping")
            return

    spec = pending[0]
    print(f"  📚 Generating guide: {spec['title']}")

    try:
        # Generate content
        sections = _generate_guide_content(spec, secrets)

        # Render PDF
        pdf_path = _render_pdf(spec, sections)
        print(f"  ✅ PDF generated: {pdf_path}")

        # Update state
        generated[spec["id"]] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pdf_path": str(pdf_path),
            "sections": len(sections),
        }
        guide_state["guides"] = generated
        guide_state["last_generation_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _save_state(guide_state)

        # Sync to DB
        _sync_guide_to_db(spec, pdf_path, status="draft")
        print(f"  ✅ Guide synced to DB: {spec['id']}")

    except Exception as e:
        print(f"  ⚠️  Guide generation failed: {e}")


def print_status():
    """Print current guide status and sales."""
    sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as db

    guides = db.get_guides()
    total_rev = db.get_guide_revenue_total()

    print(f"\n📚 PDF Guides — {len(guides)} total, £{total_rev / 100:.2f} revenue\n")
    for g in guides:
        status_badge = {"draft": "📝", "published": "🟢", "archived": "⬜"}.get(g["status"], "?")
        print(f"  {status_badge} {g['title']}")
        print(f"     Price: £{g['price_pence'] / 100:.2f}  |  Sales: {g['total_sales']}  |  "
              f"Revenue: £{g['total_revenue'] / 100:.2f}")
        if g.get("buy_url"):
            print(f"     Buy: {g['buy_url']}")
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()

    parser = argparse.ArgumentParser(description="SOVEREIGN PDF Guide Bot")
    parser.add_argument("--dry-run", action="store_true", help="Generate PDFs locally, no upload")
    parser.add_argument("--generate", action="store_true", help="Force generate next guide")
    parser.add_argument("--status", action="store_true", help="Print guide status + sales")
    parser.add_argument("--all", action="store_true", help="Generate ALL missing guides (not just one)")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.generate or args.dry_run:
        if args.all:
            # Generate all missing guides in one go
            guide_state = _load_state()
            generated = guide_state.get("guides", {})
            pending = [s for s in GUIDE_SPECS if s["id"] not in generated]
            for spec in pending:
                run(secrets, dry_run=args.dry_run, force=True)
        else:
            run(secrets, dry_run=args.dry_run, force=True)
    else:
        run(secrets)
