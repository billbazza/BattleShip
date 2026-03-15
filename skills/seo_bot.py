"""
Battleship Reset — SEO Bot
==========================
Autonomous Google Business Profile (GBP) optimisation progression.
Works through tasks 0→8 in brand/Marketing/SEO/, one task per week.
Generates copy-paste-ready GBP content and emails Will with specific actions.
After Week 8 → switches to ongoing weekly GBP post + review monitoring cycle.

Standalone:
    python3 skills/seo_bot.py --status          # show current progress
    python3 skills/seo_bot.py --run             # execute this week's task
    python3 skills/seo_bot.py --run-task 3      # run a specific task
    python3 skills/seo_bot.py --weekly-post     # generate this week's GBP post

Called from orchestrator:
    from skills.seo_bot import run as run_seo
    run_seo(secrets, state, pnl, arc_guidance)
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic

VAULT_ROOT  = Path(__file__).parent.parent
SEO_DIR     = VAULT_ROOT / "brand" / "Marketing" / "SEO"
OUTPUTS_DIR = SEO_DIR / "outputs"
STATE_FILE  = SEO_DIR / "seo_state.json"

# ── Task definitions ──────────────────────────────────────────────────────────
# Each task has: what the bot does, what Will needs to do manually in GBP,
# and what tech gap (if any) to flag.

GBP_TASKS = {
    0: {
        "name": "GBP Setup & Verification Check",
        "description": "Verify GBP is claimed, business category set, NAP (name/address/phone) consistent.",
        "bot_action": "audit",
        "will_action": "Confirm GBP is claimed at business.google.com and basic info is complete.",
        "output_file": "00_setup_checklist.md",
        "week": 1,
    },
    1: {
        "name": "Category Audit",
        "description": "Set primary category to 'Personal Trainer' or 'Health Coach'. Add secondary: Life Coach, Weight Loss Service, Wellness Program.",
        "bot_action": "generate_category_recommendations",
        "will_action": "Update GBP categories in business.google.com → Edit Profile → Business Category.",
        "output_file": "01_category_recommendations.md",
        "week": 1,
    },
    2: {
        "name": "Attributes Audit",
        "description": "Enable all relevant GBP attributes — online appointments, online classes, serves men, LGBTQ+ friendly etc.",
        "bot_action": "generate_attributes_checklist",
        "will_action": "Go to GBP → Edit Profile → More → check all recommended attributes.",
        "output_file": "02_attributes_checklist.md",
        "week": 2,
    },
    3: {
        "name": "Competitor Review Teardown",
        "description": "Analyse top 3-5 local fitness coaches/personal trainers on GBP. Review velocity, keywords in reviews, service areas mentioned.",
        "bot_action": "generate_competitor_brief",
        "will_action": "Search Google Maps for 'personal trainer [your area]' and paste the top 5 GBP URLs into the state file.",
        "output_file": "03_competitor_analysis.md",
        "week": 2,
    },
    4: {
        "name": "Review Response Strategy",
        "description": "Create templated responses for 1-5 star reviews. Set up a review request flow for new clients.",
        "bot_action": "generate_review_templates",
        "will_action": "Save review response templates. Share review request link with new clients at week 4 check-in.",
        "output_file": "04_review_strategy.md",
        "week": 3,
    },
    5: {
        "name": "GBP Posts Strategy",
        "description": "Set up weekly GBP post cadence. 4 post types: Offer, Update, Event, Product. Synced with marketing arc.",
        "bot_action": "generate_post_templates",
        "will_action": "Post first GBP post. Set a weekly reminder to post (or let bot draft and you paste).",
        "output_file": "05_posts_strategy.md",
        "week": 3,
    },
    6: {
        "name": "Services Section Optimisation",
        "description": "Write keyword-rich service descriptions for the GBP Services tab. 12-Week Programme, Ongoing Membership, Free Intake Quiz.",
        "bot_action": "generate_service_descriptions",
        "will_action": "Add services in GBP → Edit Profile → Services. Copy descriptions from output file.",
        "output_file": "06_service_descriptions.md",
        "week": 4,
    },
    7: {
        "name": "GBP Description Optimisation",
        "description": "Write a 750-char keyword-rich business description. Primary keywords: midlife fitness coach, walking programme, weight loss over 40.",
        "bot_action": "generate_gbp_description",
        "will_action": "Update GBP → Edit Profile → Business Description. Copy from output file.",
        "output_file": "07_gbp_description.md",
        "week": 4,
    },
    8: {
        "name": "Photo Audit & Upload Plan",
        "description": "Identify best photos from catalogue for GBP. Cover, profile, before/after, lifestyle, home gym.",
        "bot_action": "generate_photo_upload_plan",
        "will_action": "Upload photos to GBP → Add Photos. Use the plan from the output file.",
        "output_file": "08_photo_upload_plan.md",
        "week": 5,
    },
}

# ── Content generators ────────────────────────────────────────────────────────

GBP_BUSINESS_CONTEXT = """
Business: Battleship Reset — Midlife Fitness Reset
Owner: Will Barratt, 47, UK
Transformation: Lost 2 stone in 18 months through walking alone. No gym. No PT. No supplements.
Now has visible abs and a fitness age of 17 (per Apple Watch VO2 max).
Programme: 12-Week Battleship Reset Programme (£199 one-time, or 3×£75)
Ongoing: Battleship Membership (£89/month after Week 12)
Target audience: Men 40-60, UK, who feel stuck, tired, or don't know where to start
Unique angle: Walking-first, progressive, no gym required, science-backed (cortisol/stress/breath)
Website: battleshipreset.com
"""


def _claude_generate(prompt: str, api_key: str, max_tokens: int = 1000) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _task_generate(task_id: int, api_key: str, arc_guidance: dict | None = None) -> str:
    """Generate output content for a given task using Claude."""
    task = GBP_TASKS[task_id]
    arc_context = ""
    if arc_guidance:
        arc_context = f"\nCurrent content arc phase: {arc_guidance.get('phase', '')} — {arc_guidance.get('theme', '')}"

    prompts = {
        0: f"""You are an SEO assistant for a UK fitness coaching business.
{GBP_BUSINESS_CONTEXT}
Generate a GBP setup checklist covering:
1. Claiming/verifying the listing
2. NAP consistency (Name, Address, Phone — note: this is an online-only business, use city/region not home address)
3. Website URL confirmed
4. Hours set to "by appointment" or online
5. Phone/WhatsApp confirmed
Format as a markdown checklist with status fields (✅/⬜) Will can tick off.""",

        1: f"""You are a local SEO specialist.
{GBP_BUSINESS_CONTEXT}
Recommend the optimal GBP category setup. Include:
- Primary category (best match for a midlife online fitness coach in the UK)
- 3-5 secondary categories ranked by relevance
- Why each category helps ranking
- Any categories to AVOID (overly broad ones that dilute relevance)
Format clearly for Will to implement.""",

        2: f"""You are a local SEO specialist.
{GBP_BUSINESS_CONTEXT}
Generate a complete GBP attributes checklist. List every relevant attribute for an online fitness coach:
- Which to enable (and why)
- Which to disable or skip
- Any attributes that are strong ranking signals for fitness/wellness searches
Format as a markdown table: Attribute | Recommended | Reason""",

        3: f"""You are a competitive SEO analyst.
{GBP_BUSINESS_CONTEXT}
Create a competitor research brief for Will to execute. He will search Google Maps for 'personal trainer [his area]' and 'online fitness coach UK'.
Generate:
1. Exactly what to search
2. What to record from each competitor's GBP (review count, velocity, keywords in reviews, services listed)
3. A template table to fill in
4. What patterns to look for
5. How to use this data to outrank them
This brief will be used to complete the analysis once Will provides the competitor URLs.""",

        4: f"""You are a review strategy specialist.
{GBP_BUSINESS_CONTEXT}
Generate:
1. Review request message — SMS/WhatsApp template Will sends to clients at Week 4 and Week 12 of their programme
2. Response templates for: 5-star, 4-star, 3-star, 2-star, 1-star reviews
3. A "review keywords to encourage" list — phrases clients should mention (transformation, walking, midlife, online, UK)
4. How to get the GBP review link to share with clients
Keep the request message natural, not salesy. Will is a real person asking a real client.""",

        5: f"""You are a GBP content strategist.{arc_context}
{GBP_BUSINESS_CONTEXT}
Design a weekly GBP post strategy (4 rotating post types):
1. OFFER post — the programme, current pricing, limited slots
2. UPDATE post — progress update, tip of the week, transformation insight
3. BEFORE/AFTER or RESULT post — social proof, data point
4. EVENT/APPOINTMENT post — "booking for April open"

For each type, write:
- A template with [PLACEHOLDERS]
- A real example filled in for Battleship Reset
- Best day/time to post (UK, 40-60 male audience)
- CTA to use

Also: note that GBP posts expire after 7 days — weekly posting required.""",

        6: f"""You are a local SEO copywriter.
{GBP_BUSINESS_CONTEXT}
Write GBP service descriptions for:
1. "12-Week Battleship Reset Programme" — £199 one-time
2. "Battleship Membership" — £89/month (ongoing after Week 12)
3. "Free Fitness Intake Quiz" — free lead gen entry point

Each description: 150-250 words, keyword-rich (midlife fitness, walking programme, weight loss over 40, online coach UK), benefit-focused, ends with a soft CTA.
Format each as a ready-to-paste GBP service entry.""",

        7: f"""You are a local SEO copywriter.
{GBP_BUSINESS_CONTEXT}
Write the GBP business description. Requirements:
- Exactly 750 characters (Google's limit — use every character)
- Primary keywords: midlife fitness coach, walking programme, weight loss over 40, online fitness UK
- Opens with the transformation hook (47, walking, 2 stone, no gym)
- Covers who it's for, what they get, why it works
- Ends with battleshipreset.com
- UK English, no American spellings
Count characters and confirm the count at the end.""",

        8: f"""You are a brand asset manager.
{GBP_BUSINESS_CONTEXT}
Create a photo upload plan for GBP. Categories to cover:
1. Profile photo — headshot, confident, good light
2. Cover photo — hero transformation or lifestyle
3. Before/After — transformation composite
4. Team/Owner — Will in action or lifestyle
5. Service delivery — home gym, walking route, Apple Watch data
6. Logo

For each category, recommend which photo from this list to use:
- IMG_0014.jpeg: gym mirror selfie, lean, grey tiles
- IMG_2453.jpeg: outdoor field photo, natural light, sage top
- IMG_3566.jpeg: natural body shot (not selfie), very lean
- IMG_3577.jpeg: full body bedroom, smiling
- IMG_3372.jpeg: outdoor lifestyle, sunglasses, AirPods
- 2024-pool-pic.jpg: pool before shot
- brand/output/before_after_hook_02.jpg: composite with hook text
- random-snaps/IMG_0448.jpeg: cliff path lifestyle

Note any photos that need editing (resize, crop) and provide the exact GBP image specs.""",
    }

    prompt = prompts.get(task_id, f"Generate SEO content for task: {task['description']}")
    return _claude_generate(prompt, api_key, max_tokens=1500)


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "current_task": 0,
        "tasks_complete": [],
        "tasks_pending_will": [],
        "last_run": None,
        "competitor_urls": [],
        "gbp_url": None,
        "week_started": datetime.now(timezone.utc).isoformat(),
        "weekly_post_count": 0,
    }


def _save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2))


def get_current_task(state: dict) -> int:
    """Return the next incomplete task ID, or None if all done."""
    for task_id in range(len(GBP_TASKS)):
        if task_id not in state.get("tasks_complete", []):
            return task_id
    return None  # all tasks done, move to ongoing


# ── Main task runner ──────────────────────────────────────────────────────────

def run_task(task_id: int, secrets: dict, arc_guidance: dict | None = None) -> dict:
    """
    Execute a specific GBP task. Generates output, saves to file.
    Returns dict with task result for email digest.
    """
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")

    task    = GBP_TASKS[task_id]
    print(f"  📍 SEO Task {task_id}: {task['name']}")

    content = _task_generate(task_id, api_key, arc_guidance)

    # Save output
    out_file = OUTPUTS_DIR / task["output_file"]
    header = f"# SEO Task {task_id}: {task['name']}\n*Generated: {datetime.now().strftime('%d %b %Y')}*\n\n"
    out_file.write_text(header + content)
    print(f"     ✅ Output saved: {out_file.name}")

    # Update state
    state = _load_state()
    if task_id not in state["tasks_pending_will"]:
        state["tasks_pending_will"].append(task_id)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    return {
        "task_id":     task_id,
        "name":        task["name"],
        "output_file": str(out_file),
        "will_action": task["will_action"],
        "content_preview": content[:300] + "..." if len(content) > 300 else content,
    }


def run_weekly_task(secrets: dict, arc_guidance: dict | None = None) -> dict | None:
    """
    Run the current week's SEO task if not already done this week.
    Called daily by orchestrator — only runs once per week per task.
    """
    state   = _load_state()
    task_id = get_current_task(state)

    if task_id is None:
        print("  ✅ All GBP setup tasks complete. Running weekly maintenance.")
        return run_weekly_maintenance(secrets, arc_guidance)

    # Check if this task was already run this week
    last_run = state.get("last_run")
    if last_run:
        days_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_run)).days
        if days_since < 7 and task_id in state.get("tasks_pending_will", []):
            print(f"  ℹ️  SEO Task {task_id} already run {days_since} days ago. Waiting for Will to confirm action.")
            return None

    return run_task(task_id, secrets, arc_guidance)


def confirm_task_complete(task_id: int):
    """Mark a task as complete (Will confirmed GBP action was taken)."""
    state = _load_state()
    if task_id not in state["tasks_complete"]:
        state["tasks_complete"].append(task_id)
    if task_id in state.get("tasks_pending_will", []):
        state["tasks_pending_will"].remove(task_id)
    # Advance to next task
    next_task = get_current_task(state)
    if next_task is not None:
        state["current_task"] = next_task
    _save_state(state)
    print(f"  ✅ Task {task_id} marked complete. Next: Task {next_task}")


# ── Weekly GBP post generator ─────────────────────────────────────────────────

def generate_weekly_gbp_post(secrets: dict, arc_guidance: dict | None = None) -> str:
    """Generate this week's GBP post, aligned to the content arc."""
    api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")

    arc_context = ""
    if arc_guidance:
        arc_context = f"This week's content theme: {arc_guidance.get('phase', '')} — {arc_guidance.get('theme', '')}\nFocus message: {arc_guidance.get('focus_message', '')}"

    state     = _load_state()
    post_num  = state.get("weekly_post_count", 0) + 1
    post_type = ["OFFER", "UPDATE", "RESULT", "BOOKING"][((post_num - 1) % 4)]

    prompt = f"""You are a GBP post writer for a UK fitness coaching business.
{GBP_BUSINESS_CONTEXT}
{arc_context}

Write a GBP {post_type} post. Requirements:
- 150-300 words (Google shows ~300 chars in preview — lead with the hook)
- UK English
- Includes a clear call to action: battleshipreset.com or link in bio
- Natural, first-person voice from Will (not corporate)
- Include 2-3 relevant keywords naturally
- Post type: {post_type}

Format:
HEADLINE: [one punchy line]
BODY: [the post]
CTA: [call to action]
HASHTAGS: [5-8 relevant]"""

    content  = _claude_generate(prompt, api_key, max_tokens=600)

    # Save post
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    post_file = OUTPUTS_DIR / f"gbp_post_week_{post_num:02d}.md"
    post_file.write_text(
        f"# GBP Post — Week {post_num} ({post_type})\n"
        f"*Generated: {datetime.now().strftime('%d %b %Y')}*\n"
        f"*Arc: {arc_guidance.get('phase', 'N/A') if arc_guidance else 'N/A'}*\n\n"
        + content
    )

    state["weekly_post_count"] = post_num
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    print(f"  ✅ GBP post Week {post_num} ({post_type}) saved: {post_file.name}")
    return content


def run_weekly_maintenance(secrets: dict, arc_guidance: dict | None = None) -> dict:
    """Ongoing weekly GBP tasks after initial setup is complete."""
    post_content = generate_weekly_gbp_post(secrets, arc_guidance)
    return {
        "mode":        "ongoing",
        "will_action": "Paste the weekly GBP post from brand/Marketing/SEO/outputs/ into your GBP dashboard. Takes 2 minutes.",
        "post_preview": post_content[:300] + "...",
    }


# ── Status report ─────────────────────────────────────────────────────────────

def get_status_report() -> dict:
    """Return current SEO progress for orchestrator/brand PM."""
    state      = _load_state()
    total      = len(GBP_TASKS)
    complete   = len(state.get("tasks_complete", []))
    pending    = state.get("tasks_pending_will", [])
    current    = get_current_task(state)
    pct        = int((complete / total) * 100)

    return {
        "tasks_complete":       complete,
        "tasks_total":          total,
        "completion_pct":       pct,
        "current_task":         current,
        "current_task_name":    GBP_TASKS[current]["name"] if current is not None else "Ongoing maintenance",
        "pending_will_actions": [GBP_TASKS[t]["will_action"] for t in pending],
        "weekly_posts":         state.get("weekly_post_count", 0),
        "gbp_url":              state.get("gbp_url"),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def run(secrets: dict, state: dict, pnl: dict | None = None, arc_guidance: dict | None = None):
    """Called from orchestrator."""
    try:
        result = run_weekly_task(secrets, arc_guidance)
        return result
    except Exception as e:
        print(f"  ⚠️  SEO bot error: {e}")
        return None


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

    parser = argparse.ArgumentParser(description="Battleship SEO Bot")
    parser.add_argument("--status",      action="store_true", help="Show current SEO progress")
    parser.add_argument("--run",         action="store_true", help="Run this week's SEO task")
    parser.add_argument("--run-task",    type=int,            help="Run a specific task by ID (0-8)")
    parser.add_argument("--weekly-post", action="store_true", help="Generate this week's GBP post")
    parser.add_argument("--confirm",     type=int,            help="Mark a task as complete (Will confirmed)")
    args = parser.parse_args()

    if args.status:
        report = get_status_report()
        print(f"\n  SEO Progress: {report['tasks_complete']}/{report['tasks_total']} tasks ({report['completion_pct']}%)")
        print(f"  Current task: {report['current_task_name']}")
        print(f"  Weekly GBP posts: {report['weekly_posts']}")
        if report["pending_will_actions"]:
            print(f"\n  Waiting for Will:")
            for action in report["pending_will_actions"]:
                print(f"    ⏳ {action}")

    elif args.run:
        result = run_weekly_task(secrets)
        if result:
            print(f"\n  Will's action needed: {result.get('will_action', '')}")

    elif args.run_task is not None:
        result = run_task(args.run_task, secrets)
        print(f"\n  Will's action needed: {result.get('will_action', '')}")

    elif args.weekly_post:
        post = generate_weekly_gbp_post(secrets)
        print(f"\n{post}")

    elif args.confirm is not None:
        confirm_task_complete(args.confirm)

    else:
        parser.print_help()
