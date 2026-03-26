"""
SOVEREIGN — Newsletter Bot (Stream C)
======================================
Publishes "The Operator" — a weekly digest for people building income systems,
running side projects, and compounding their way out of employment dependency.

Not fitness-specific. Adjacent to Battleship Reset but a broader audience:
anyone building something autonomous, lean, and compounding.

Responsibilities:
  1. Assemble weekly issue via Claude (insight + picks + build log + CTA)
  2. Send via Beehiiv API (or dry-run to file)
  3. Track subscriber count and open rates week-over-week
  4. Rotate affiliate link slots based on click performance
  5. Feed top-performing subject lines back into future issues

Called from pipeline:
    from skills.newsletter_bot import run as run_newsletter
    run_newsletter(secrets, state, VAULT_ROOT)

Standalone:
    python3 skills/newsletter_bot.py --dry-run     # generate + save, no send
    python3 skills/newsletter_bot.py --send        # force send (ignores schedule)
    python3 skills/newsletter_bot.py --stats       # print latest issue stats
    python3 skills/newsletter_bot.py --status      # print current state

Beehiiv secrets required (add to ~/.battleship.env):
    BEEHIIV_API_KEY=...
    BEEHIIV_PUBLICATION_ID=...
"""

import json
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import anthropic

VAULT_ROOT = Path(__file__).parent.parent
STATE_FILE  = VAULT_ROOT / "clients" / "newsletter_state.json"

BEEHIIV_BASE = "https://api.beehiiv.com/v2"

# ── Affiliate slots ────────────────────────────────────────────────────────────
# Each slot has an id, label, url, and click_count (tracked from Beehiiv stats).
# Lowest-performing slot gets rotated monthly.
DEFAULT_AFFILIATE_SLOTS = [
    {
        "id":          "aff_lemon",
        "label":       "Lemon Squeezy — sell digital products without the tax headache",
        "url":         "https://www.lemonsqueezy.com",
        "click_count": 0,
    },
    {
        "id":          "aff_beehiiv",
        "label":       "Beehiiv — the newsletter platform actually built for growth",
        "url":         "https://www.beehiiv.com",
        "click_count": 0,
    },
    {
        "id":          "aff_anthropic",
        "label":       "Claude — the AI that writes, reasons, and builds with you",
        "url":         "https://claude.ai",
        "click_count": 0,
    },
]

# ── Rotating insight themes ────────────────────────────────────────────────────
INSIGHT_THEMES = [
    "automation and leverage — how to multiply output without multiplying hours",
    "compounding income — why small streams beat one big bet",
    "building in public — the trust flywheel that makes selling feel natural",
    "systems over willpower — designing the machine, not becoming it",
    "pricing and positioning — how operators underprice and what to do instead",
    "the one-person business — what's actually possible with a Mac and an API key",
    "time arbitrage — finding the gaps incumbents ignore",
    "distribution before product — building the audience before the thing",
]


# ── State ──────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "last_send_date":    None,
        "issue_number":      0,
        "subscriber_count":  0,
        "issues":            [],
        "affiliate_slots":   DEFAULT_AFFILIATE_SLOTS,
        "theme_index":       0,
    }


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Beehiiv API ───────────────────────────────────────────────────────────────

def _beehiiv_headers(secrets: dict) -> dict:
    key = secrets.get("BEEHIIV_API_KEY", "")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _get_subscriber_count(secrets: dict) -> int:
    """Return total active subscriber count from Beehiiv."""
    import httpx
    pub_id = secrets.get("BEEHIIV_PUBLICATION_ID", "")
    if not pub_id:
        return 0
    try:
        r = httpx.get(
            f"{BEEHIIV_BASE}/publications/{pub_id}/subscriptions",
            headers=_beehiiv_headers(secrets),
            params={"status": "active", "limit": 1},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("total_results", 0)
    except Exception as e:
        print(f"  ⚠️  Beehiiv subscriber count failed: {e}")
        return 0


def subscribe_email(email: str, name: str, secrets: dict) -> bool:
    """Add an email to the Beehiiv subscriber list. Returns True on success."""
    import httpx
    pub_id = secrets.get("BEEHIIV_PUBLICATION_ID", "")
    if not pub_id or not email:
        return False
    try:
        r = httpx.post(
            f"{BEEHIIV_BASE}/publications/{pub_id}/subscriptions",
            headers=_beehiiv_headers(secrets),
            json={
                "email": email,
                "reactivate_existing": True,
                "send_welcome_email": False,
                "custom_fields": [{"name": "first_name", "value": name}] if name else [],
            },
            timeout=15,
        )
        r.raise_for_status()
        print(f"  📰 Subscribed {email} to The Operator")
        return True
    except Exception as e:
        print(f"  ⚠️  Beehiiv subscribe failed for {email}: {e}")
        return False


def _create_and_send_post(subject: str, body_text: str, secrets: dict,
                           dry_run: bool = False) -> Optional[str]:
    """
    Stage newsletter for dashboard approval, or save to file in dry-run mode.
    Returns a queue ID on success, None on failure.
    """
    if dry_run:
        out = VAULT_ROOT / "logs" / "newsletter_dry_run.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"SUBJECT: {subject}\n\n{body_text}", encoding="utf-8")
        print(f"  📄 Dry-run — issue saved to {out}")
        return "dry_run_post_id"

    try:
        sys.path.insert(0, str(VAULT_ROOT))
        import scripts.db as db
        eq_id = db.insert_email({
            "to_addr":   "beehiiv",
            "subject":   subject,
            "body":      body_text,
            "html_body": "",
            "source":    "newsletter",
            "reason":    "Copy text → paste into Beehiiv blank draft → publish → Mark as sent",
        })
        print(f"  📋 Newsletter staged for review in dashboard (id: {eq_id})")
        return eq_id
    except Exception as e:
        print(f"  ⚠️  Failed to stage newsletter: {e}")
        return None


def send_to_beehiiv(subject: str, html_body: str, secrets: dict) -> Optional[str]:
    """Actually publish a newsletter issue to Beehiiv. Called from dashboard on approve."""
    import httpx
    pub_id = secrets.get("BEEHIIV_PUBLICATION_ID", "")
    if not pub_id:
        print("  ⚠️  BEEHIIV_PUBLICATION_ID not set — cannot send")
        return None

    try:
        r = httpx.post(
            f"{BEEHIIV_BASE}/publications/{pub_id}/posts",
            headers=_beehiiv_headers(secrets),
            json={
                "title":          subject,
                "subtitle":       subject,
                "subject":        subject,
                "content":        {"free": {"web": html_body, "email": html_body}},
                "status":         "confirmed",
                "send_at":        int(datetime.now(timezone.utc).timestamp()),
                "audience":       "free",
                "content_tags":   ["operator", "autonomous", "income"],
            },
            timeout=30,
        )
        r.raise_for_status()
        post_id = r.json().get("data", {}).get("id", "")
        print(f"  ✅ Beehiiv issue sent — post_id: {post_id}")
        return post_id
    except Exception as e:
        print(f"  ⚠️  Beehiiv send failed: {e}")
        return None


def _get_post_stats(post_id: str, secrets: dict) -> dict:
    """Fetch open rate and click data for a sent post."""
    import httpx
    pub_id = secrets.get("BEEHIIV_PUBLICATION_ID", "")
    if not pub_id or post_id.startswith("dry_run"):
        return {}
    try:
        r = httpx.get(
            f"{BEEHIIV_BASE}/publications/{pub_id}/posts/{post_id}",
            headers=_beehiiv_headers(secrets),
            timeout=15,
        )
        r.raise_for_status()
        stats = r.json().get("data", {}).get("stats", {})
        return {
            "open_rate":    stats.get("open_rate", 0),
            "click_rate":   stats.get("click_rate", 0),
            "sends":        stats.get("recipients", 0),
        }
    except Exception as e:
        print(f"  ⚠️  Beehiiv stats fetch failed: {e}")
        return {}


# ── Build notes from daily logs ────────────────────────────────────────────────

def _gather_build_notes() -> str:
    """Pull key insights and pipeline status from recent daily logs (last 7 days)."""
    notes = []
    for i in range(7):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        for log_dir in [VAULT_ROOT / "logs", VAULT_ROOT / "archive"]:
            log_file = log_dir / f"daily-log-{day}.md"
            if log_file.exists():
                text = log_file.read_text(encoding="utf-8")
                # Extract Key Insights and Pipeline Status sections
                for section in ["Key Insights", "Pipeline Status", "Actions Taken"]:
                    match = re.search(
                        rf"^## {section}\s*\n(.*?)(?=\n## |\Z)",
                        text, re.MULTILINE | re.DOTALL
                    )
                    if match:
                        notes.append(f"[{day}] {match.group(1).strip()}")
    return "\n".join(notes[:500]) if notes else "No daily logs found for this week."


# ── Content generation ─────────────────────────────────────────────────────────

def _generate_issue(issue_number: int, theme: str, affiliate_slots: list,
                    secrets: dict) -> tuple[str, str, str, str]:
    """
    Generate subject line, preview, and plain text body for the issue.
    Returns (subject, preview, body_text, fb_post).
    """
    api_key = (secrets.get("ANTHROPIC_API_KEY")
               or secrets.get("ANTHROPIC_KEY")
               or secrets.get("anthropic"))
    client = anthropic.Anthropic(api_key=api_key)

    build_notes = _gather_build_notes()

    picks_text = "\n".join(
        f"- {s['label']} → {s['url']}" for s in affiliate_slots[:3]
    )

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""
Write issue #{issue_number} of "The Operator" — a weekly digest for people building autonomous income systems.

This week's theme: {theme}

Format your response as JSON with these exact keys:
- "subject": email subject line (max 60 chars). Write like you're texting a sharp friend — lowercase ok, no colons, no "explained", no "how to". Examples: "I broke my funnel and nobody noticed", "the £0 month that changed everything", "stop building features, start buying traffic".
- "preview": preview text shown in inbox (max 90 chars, complements subject — adds context, not a repeat)
- "insight_title": title for the main insight section (5-8 words, punchy, no filler)
- "insight_body": 180-220 word insight on the theme. Voice: direct, no fluff, no motivational filler. Written for someone already building, not someone thinking about it. One concrete idea per paragraph.
- "build_log": 80-100 words. Subscriber-facing "building in public" update. Use the raw build notes below as source material. Rules: NO internal jargon (no API errors, HTTP codes, endpoint names). Do NOT spin small numbers into wins — if 2 people converted, say "2 people". Be brutally honest. If revenue is £0, say so.
- "cta_text": 40-60 word call to action for Battleship Reset (fitness programme for men 40-60). Angle: the same discipline that builds income systems applies to your body. Direct link: battleshipreset.com
- "fb_post": 80-120 word standalone Facebook post based on the insight. Not promotional, not linking to the newsletter. Ends with a question or one-line takeaway. No hashtags. No emojis.

Raw build notes (for the build_log field — rewrite for a general audience):
{build_notes}

Affiliate picks to include (use the label and URL exactly):
{picks_text}

Return only valid JSON. No markdown fences.
"""}]
    )

    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)

    # Build plain text body — ready to paste into Beehiiv's blank draft
    picks_lines = "\n".join(
        f"• {s['label']}\n  {s['url']}" for s in affiliate_slots[:3]
    )

    # Pull guide promos from bot_state (set by pdf_guide_bot)
    _guide_promo_section = ""
    try:
        sys.path.insert(0, str(VAULT_ROOT))
        import scripts.db as _db_nl
        _promos_raw = _db_nl.get_bot_state("guide_promos") or "[]"
        _promos = json.loads(_promos_raw)
        if _promos:
            # Rotate which guide to feature based on issue number
            _featured = _promos[(issue_number - 1) % len(_promos)]
            _guide_promo_section = (
                f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"NEW GUIDE: {_featured['title']}\n\n"
                f"{_featured['price']} — {_featured.get('buy_url', 'battleshipreset.com')}\n"
            )
    except Exception:
        pass

    body_text = f"""THE OPERATOR — Issue #{issue_number}
Building autonomous income. One stream at a time.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

THIS WEEK: {data["insight_title"].upper()}

{data["insight_body"]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

THREE PICKS

{picks_lines}
{_guide_promo_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

THE BUILD LOG

{data["build_log"]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{data["cta_text"]}

→ battleshipreset.com
"""

    return data["subject"], data["preview"], body_text, data.get("fb_post", "")


# ── Schedule check ─────────────────────────────────────────────────────────────

def _should_send_today(state: dict) -> bool:
    """Send once per week on Tuesday (weekday=1)."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 1:  # Tuesday
        return False
    today = now.strftime("%Y-%m-%d")
    return state.get("last_send_date") != today


# ── Stats sync ─────────────────────────────────────────────────────────────────

def _sync_last_issue_stats(state: dict, secrets: dict) -> None:
    """Update open/click stats on the most recent issue (run 48h after send)."""
    issues = state.get("issues", [])
    if not issues:
        return
    last = issues[-1]
    if last.get("stats_synced"):
        return
    sent_at = last.get("sent_at", "")
    if not sent_at:
        return
    sent_dt = datetime.fromisoformat(sent_at)
    if datetime.now(timezone.utc) < sent_dt + timedelta(hours=48):
        return  # Too early — stats not settled yet

    stats = _get_post_stats(last["post_id"], secrets)
    if stats:
        last.update(stats)
        last["stats_synced"] = True
        _save_state(state)
        print(f"  📊 Issue #{last['issue_number']} stats: "
              f"open {stats.get('open_rate', 0):.1%} · "
              f"click {stats.get('click_rate', 0):.1%}")


# ── Main ───────────────────────────────────────────────────────────────────────

def run(secrets: dict, state: dict = None, vault_root: Path = VAULT_ROOT,
        dry_run: bool = False, force: bool = False) -> None:
    """
    Called from battleship_pipeline.py.
    dry_run=True: generate issue and save to file, do not send.
    force=True: send regardless of day-of-week schedule.
    """
    nl_state = _load_state()

    # Always try to sync stats on recent issues
    _sync_last_issue_stats(nl_state, secrets)

    # Subscriber count sync (light API call, do every run)
    if secrets.get("BEEHIIV_API_KEY") and secrets.get("BEEHIIV_PUBLICATION_ID"):
        count = _get_subscriber_count(secrets)
        if count:
            nl_state["subscriber_count"] = count
            _save_state(nl_state)

    if not force and not _should_send_today(nl_state):
        today = datetime.now(timezone.utc)
        days_to_tuesday = (1 - today.weekday()) % 7 or 7
        next_tuesday = (today + timedelta(days=days_to_tuesday)).strftime("%Y-%m-%d")
        print(f"  ℹ️  Newsletter sends Tuesdays — next issue {next_tuesday} "
              f"(subscribers: {nl_state['subscriber_count']})")
        return

    # Pick this week's theme
    theme_idx   = nl_state.get("theme_index", 0) % len(INSIGHT_THEMES)
    theme       = INSIGHT_THEMES[theme_idx]
    issue_num   = nl_state.get("issue_number", 0) + 1
    slots       = nl_state.get("affiliate_slots", DEFAULT_AFFILIATE_SLOTS)

    print(f"  📰 Generating issue #{issue_num} — theme: {theme[:50]}…")

    try:
        subject, preview, body_text, fb_post = _generate_issue(
            issue_num, theme, slots, secrets
        )
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Content generation returned invalid JSON: {e}")
        return
    except Exception as e:
        print(f"  ⚠️  Content generation failed: {e}")
        return

    print(f"  ✉️  Subject: {subject}")

    # Queue FB post from newsletter insight
    if fb_post:
        try:
            sys.path.insert(0, str(VAULT_ROOT))
            from skills.facebook_bot import _queue_post
            _queue_post(fb_post, f"newsletter-{theme[:40]}")
            print(f"  📘 FB post queued from newsletter insight")
        except Exception as e:
            print(f"  ⚠️  FB post queue skipped: {e}")

    post_id = _create_and_send_post(subject, body_text, secrets, dry_run=dry_run)
    if not post_id:
        return

    # Update state
    nl_state["issue_number"]   = issue_num
    nl_state["last_send_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nl_state["theme_index"]    = (theme_idx + 1) % len(INSIGHT_THEMES)
    nl_state["issues"].append({
        "issue_number": issue_num,
        "subject":      subject,
        "theme":        theme,
        "post_id":      post_id,
        "sent_at":      datetime.now(timezone.utc).isoformat(),
        "dry_run":      dry_run,
        "stats_synced": False,
        "open_rate":    None,
        "click_rate":   None,
        "sends":        nl_state["subscriber_count"],
    })
    # Keep last 52 issues
    nl_state["issues"] = nl_state["issues"][-52:]
    _save_state(nl_state)

    mode = "dry-run saved" if dry_run else "sent"
    print(f"  ✅ Issue #{issue_num} {mode} — '{subject}'")


# ── Affiliate slot rotation ────────────────────────────────────────────────────

def rotate_affiliate_slots(secrets: dict) -> None:
    """
    Called monthly. Syncs click counts from last 4 issues' stats,
    then replaces the lowest-performing slot with a new candidate.
    Slots to add must be manually maintained in this function as the
    catalogue grows.
    """
    state = _load_state()
    slots = state.get("affiliate_slots", DEFAULT_AFFILIATE_SLOTS)

    # For now: report current state. Rotation logic extends as catalogue grows.
    print("  📊 Affiliate slot performance:")
    for s in sorted(slots, key=lambda x: x["click_count"], reverse=True):
        print(f"     {s['click_count']:>4} clicks — {s['label'][:55]}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, os

    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                secrets[k.strip()] = v.strip()
    secrets.update(os.environ)

    parser = argparse.ArgumentParser(description="Newsletter bot CLI")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't send")
    parser.add_argument("--send",    action="store_true", help="Force send now")
    parser.add_argument("--stats",   action="store_true", help="Print latest issue stats")
    parser.add_argument("--status",  action="store_true", help="Print current state summary")
    parser.add_argument("--rotate",  action="store_true", help="Review affiliate slot performance")
    args = parser.parse_args()

    if args.stats or args.status:
        st = _load_state()
        print(f"Issue #{st['issue_number']} | Subscribers: {st['subscriber_count']}")
        print(f"Last send: {st.get('last_send_date', 'never')}")
        if st["issues"]:
            last = st["issues"][-1]
            print(f"Last subject: {last['subject']}")
            print(f"Open rate: {last.get('open_rate', 'pending')}")
        sys.exit(0)

    if args.rotate:
        rotate_affiliate_slots(secrets)
        sys.exit(0)

    run(secrets, dry_run=args.dry_run, force=args.send or args.dry_run)
