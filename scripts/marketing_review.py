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

VAULT_ROOT = Path("/Users/will/Obsidian-Vaults/BattleShip-Vault")
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
        age_days = (today - datetime.strptime(p.get("date", "2000-01-01"), "%Y-%m-%d").date()).days
        if age_days < 1 or age_days > 7:
            continue
        reach = p.get("reach", 0)
        eng   = p.get("likes", 0) + p.get("comments", 0) + p.get("shares", 0)
        preview = p.get("preview", "")[:50]
        if reach >= 100 or eng >= 10:
            alerts.append(f"🔥 Top post ({age_days}d ago, reach={reach}, eng={eng}): \"{preview}\"")
        elif age_days >= 3 and reach < 5 and eng == 0:
            alerts.append(f"❄️ Flat post ({age_days}d ago, reach={reach}): \"{preview}\"")
    return alerts


def review_ideas_bank(secrets: dict) -> list[str]:
    """Check ideas bank health — thin bank, stale green-lits, no drafts queued."""
    alerts = []
    if not IDEAS_FILE.exists():
        return alerts
    ideas = json.loads(IDEAS_FILE.read_text()).get("ideas", [])
    drafts    = [i for i in ideas if i["status"] == "draft"]
    green_lit = [i for i in ideas if i["status"] == "green_lit"]

    if len(drafts) < 2:
        alerts.append(f"💡 Ideas bank low ({len(drafts)} draft ideas) — needs fresh angles")

    # Green-lit ideas older than 3 days with no content_review entry
    cr_file = VAULT_ROOT / "clients" / "content_review.json"
    cr_idea_ids = set()
    if cr_file.exists():
        cr_data = json.loads(cr_file.read_text())
        cr_idea_ids = {p.get("idea_id") for p in cr_data.get("posts", [])}

    for idea in green_lit:
        if idea["id"] not in cr_idea_ids:
            alerts.append(f"⚠️  Green-lit idea has no draft yet: \"{idea['title']}\"")

    return alerts


def maybe_generate_new_ideas(secrets: dict, state: dict) -> bool:
    """
    If ideas bank has <3 drafts and it's been >12h since last idea gen, ask
    marketing bot to generate 3 new idea angles and add them to the bank.
    """
    ideas = json.loads(IDEAS_FILE.read_text()).get("ideas", []) if IDEAS_FILE.exists() else []
    drafts = [i for i in ideas if i["status"] == "draft"]
    if len(drafts) >= 3:
        return False

    last_gen = state.get("last_idea_gen")
    if last_gen:
        last_dt = datetime.fromisoformat(last_gen)
        if (datetime.now(timezone.utc) - last_dt) < timedelta(hours=12):
            return False

    print("  💡 Ideas bank thin — generating new angles via Claude...")
    try:
        import anthropic
        api_key = secrets.get("ANTHROPIC_KEY", "")
        if not api_key:
            return False
        client = anthropic.Anthropic(api_key=api_key)

        # Read social metrics for context
        context = ""
        if SOCIAL_METRICS.exists():
            m = json.loads(SOCIAL_METRICS.read_text())
            recent_posts = sorted(m.get("posts", {}).values(),
                                   key=lambda x: x.get("date", ""), reverse=True)[:3]
            if recent_posts:
                context = "Recent posts performance:\n" + "\n".join(
                    f"- \"{p.get('preview','')[:60]}\" → reach={p.get('reach',0)}, eng={p.get('likes',0)+p.get('comments',0)}"
                    for p in recent_posts
                )

        prompt = f"""You are the marketing strategist for Battleship Reset — a 12-week home fitness programme for men 40+.
Will Barratt (founder, 47) lost 2 stone in 18 months via walking, no gym, no PT. Now has visible abs, fitness age of 17.
Product: £199 one-time. Target: men 40-55, UK, busy, sceptical of fads.

{context}

Generate 3 fresh content ideas that would resonate on Facebook with this audience.
Each idea should have a clear contrarian or emotional hook.
Return as JSON array:
[
  {{"title": "Short punchy title", "angle": "1-2 sentence explanation of the unique angle and why it stops the scroll"}},
  ...
]
Only return the JSON array. No other text."""

        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            return False
        new_ideas = json.loads(match.group())

        # Append to ideas bank
        import uuid
        data = json.loads(IDEAS_FILE.read_text()) if IDEAS_FILE.exists() else {"ideas": []}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing_titles = {i["title"].lower() for i in data["ideas"]}
        added = 0
        for idea in new_ideas:
            if idea.get("title", "").lower() in existing_titles:
                continue
            data["ideas"].append({
                "id":           "idea_" + uuid.uuid4().hex[:3],
                "title":        idea["title"],
                "angle":        idea["angle"],
                "status":       "draft",
                "added":        today,
                "green_lit":    None,
                "developed_into": None,
                "notes":        "Auto-generated by marketing review"
            })
            added += 1

        IDEAS_FILE.write_text(json.dumps(data, indent=2))
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
