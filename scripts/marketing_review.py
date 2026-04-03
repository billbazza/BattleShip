#!/usr/bin/env python3
"""
Battleship — Marketing Review (runs 4x/day)
============================================
Separate from the main pipeline. Focuses purely on growth:
  - Reviews post performance since last run
  - Checks ideas bank for stale/unconverted green-lit ideas
  - Nudges marketing bot to generate new idea angles if bank is thin
  - Runs orchestrator Command Report (once per day, first run wins)
  - Sends Telegram nudge if anything needs attention

Runs at: 08:00, 12:00, 16:00, 20:00 via LaunchAgent
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(VAULT_ROOT))

REVIEW_STATE_FILE = VAULT_ROOT / "brand" / "Marketing" / "review_state.json"
IDEAS_FILE        = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"
SOCIAL_METRICS    = VAULT_ROOT / "clients" / "social_metrics.json"
REMINDERS_FILE    = VAULT_ROOT / "brand" / "Marketing" / "reminders.json"


def _load_env() -> dict:
    env = {}
    env_file = Path.home() / ".battleship.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _load_review_state() -> dict:
    if REVIEW_STATE_FILE.exists():
        return json.loads(REVIEW_STATE_FILE.read_text())
    return {"last_review": None, "last_idea_gen": None, "reviews_today": 0, "review_date": None}


def _save_review_state(s: dict):
    REVIEW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_STATE_FILE.write_text(json.dumps(s, indent=2))


def _send_telegram(msg: str, secrets: dict):
    try:
        import requests
        token   = secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = secrets.get("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
    except Exception as e:
        print(f"  ⚠️  Telegram: {e}")


def review_post_performance(secrets: dict) -> list[str]:
    """Check recent FB posts — flag anything that's over-performing or flatlining."""
    alerts = []
    if not SOCIAL_METRICS.exists():
        return alerts
    metrics = json.loads(SOCIAL_METRICS.read_text())
    posts   = metrics.get("posts", {})
    today   = datetime.now(timezone.utc).date()

    for pid, p in posts.items():
        date_str = (p.get("date") or p.get("created_time") or "2000-01-01")[:10]
        try:
            age_days = (today - datetime.strptime(date_str, "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if age_days < 1 or age_days > 7:
            continue
        reach = int(p.get("reach", (p.get("insights") or {}).get("reach", 0)) or 0)
        eng   = int(p.get("likes", 0) or 0) + int(p.get("comments", 0) or 0) + int(p.get("shares", 0) or 0)
        preview = (p.get("preview") or p.get("message") or "")[:50]
        if reach >= 100 or eng >= 10:
            alerts.append(f"🔥 Top post ({age_days}d ago, reach={reach}, eng={eng}): \"{preview}\"")
        elif age_days >= 3 and reach < 5 and eng == 0:
            alerts.append(f"❄️ Flat post ({age_days}d ago, reach={reach}): \"{preview}\"")
    return alerts


def review_ideas_bank(secrets: dict) -> list[str]:
    """Check ideas bank health — thin bank, stale green-lits, no drafts queued."""
    alerts = []
    import scripts.db as db
    ideas = db.get_ideas()
    drafts    = [i for i in ideas if i["status"] == "draft"]
    green_lit = [i for i in ideas if i["status"] == "green_lit"]

    if len(drafts) < 2:
        alerts.append(f"💡 Ideas bank low ({len(drafts)} draft ideas) — needs fresh angles")

    # Green-lit ideas with no live draft/review/queue artifact in SQLite.
    posts = db.get_posts()
    cr_idea_ids = {
        p.get("idea_id")
        for p in posts
        if p.get("idea_id") and p.get("stage") in ("content_review", "awaiting_graphic", "fb_queue", "posted")
    }

    for idea in green_lit:
        if idea["id"] not in cr_idea_ids:
            alerts.append(f"⚠️  Green-lit idea has no draft yet: \"{idea['title']}\"")

    return alerts


def _angle_is_duplicate(new_angle: str, existing: list[str]) -> bool:
    """Keyword overlap check — reject if new angle shares 4+ meaningful words with any existing angle."""
    _stop = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
             "of", "with", "is", "are", "you", "your", "my", "i", "it", "this",
             "that", "they", "he", "she", "we", "not", "no", "do", "don't",
             "men", "man", "40", "50", "60", "after", "over", "about", "why",
             "how", "what", "when", "who", "will", "can", "just", "like", "be"}
    new_words = {w.lower().strip(".,?!'\"") for w in new_angle.split() if w.lower() not in _stop and len(w) > 3}
    for ex in existing:
        ex_words = {w.lower().strip(".,?!'\"") for w in ex.split() if w.lower() not in _stop and len(w) > 3}
        overlap = new_words & ex_words
        if len(overlap) >= 4:
            return True
    return False


def maybe_generate_new_ideas(secrets: dict, state: dict) -> bool:
    """
    If ideas bank is thin or stale and it's been >12h since last idea gen, ask
    marketing_bot's central idea loop to refill the bank.
    """
    ideas = json.loads(IDEAS_FILE.read_text()).get("ideas", []) if IDEAS_FILE.exists() else []
    drafts = [i for i in ideas if i.get("status") in {"draft", "ideas_bank"}]
    stale_mix = False
    try:
        from skills.marketing_bot import _build_idea_loop_context
        loop = _build_idea_loop_context({"ideas": ideas})
        stale_mix = bool(loop.get("saturated_concepts")) or "founder_proof" in loop.get("dominant_categories", [])
    except Exception:
        pass
    if len(drafts) >= 3 and not stale_mix:
        return False

    last_gen = state.get("last_idea_gen")
    if last_gen:
        last_dt = datetime.fromisoformat(last_gen)
        if (datetime.now(timezone.utc) - last_dt) < timedelta(hours=12):
            return False

    print("  💡 Idea loop triggered — asking marketing bot for a fresh slate...")
    try:
        data = json.loads(IDEAS_FILE.read_text()) if IDEAS_FILE.exists() else {"ideas": []}
        from skills.marketing_bot import _generate_new_ideas

        added = _generate_new_ideas(
            secrets,
            data,
            IDEAS_FILE,
            force=stale_mix,
            reason="stale_mix" if stale_mix else "marketing_review_low_bank",
        )
        if added:
            state["last_idea_gen"] = datetime.now(timezone.utc).isoformat()
            print(f"  ✅ Added {added} new ideas to ideas bank")
        return added > 0

    except Exception as e:
        print(f"  ⚠️  Idea generation failed: {e}")
        return False


def run_orchestrator_if_due(secrets: dict):
    """Run the full orchestrator Command Report — once per day, first run wins."""
    try:
        from skills.orchestrator import run as orch_run
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("pipeline", VAULT_ROOT / "scripts" / "battleship_pipeline.py")
        mod  = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        state = mod.load_state()
        orch_run(secrets, state)
    except Exception as e:
        print(f"  ⚠️  Orchestrator: {e}")


def main():
    print(f"\n{'='*50}")
    print(f"📣 Marketing Review — {datetime.now().strftime('%H:%M %a %d %b')}")
    print(f"{'='*50}")

    secrets = _load_env()
    state   = _load_review_state()

    # Track reviews today
    today_str = datetime.now().strftime("%Y-%m-%d")
    if state.get("review_date") != today_str:
        state["reviews_today"] = 0
        state["review_date"]   = today_str
    state["reviews_today"] = state.get("reviews_today", 0) + 1
    state["last_review"]   = datetime.now(timezone.utc).isoformat()

    alerts = []

    # 1. Post performance
    print("\n  [1] Reviewing post performance...")
    perf_alerts = review_post_performance(secrets)
    alerts.extend(perf_alerts)
    for a in perf_alerts:
        print(f"      {a}")

    # 2. Ideas bank health
    print("  [2] Reviewing ideas bank...")
    idea_alerts = review_ideas_bank(secrets)
    alerts.extend(idea_alerts)
    for a in idea_alerts:
        print(f"      {a}")

    # 3. Generate new ideas if bank is thin
    print("  [3] Checking if new ideas needed...")
    generated = maybe_generate_new_ideas(secrets, state)
    if generated:
        alerts.append("💡 3 new content ideas added to ideas bank — check Marketing Bot")

    # 4. Orchestrator Command Report (once/day)
    print("  [4] Orchestrator check...")
    run_orchestrator_if_due(secrets)

    # 5. Telegram summary if anything noteworthy
    if alerts:
        run_num = state["reviews_today"]
        msg = f"📣 *Marketing Review #{run_num}* ({datetime.now().strftime('%H:%M')})\n\n"
        msg += "\n".join(f"• {a}" for a in alerts)
        msg += "\n\nCheck /business for details."
        _send_telegram(msg, secrets)
        print(f"\n  📱 Telegram sent ({len(alerts)} alerts)")
    else:
        print("\n  ✅ All good — no alerts")

    _save_review_state(state)
    print(f"\n✅ Marketing review complete (run #{state['reviews_today']} today)\n")


if __name__ == "__main__":
    main()
