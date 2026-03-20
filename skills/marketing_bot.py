"""
Battleship Reset — Marketing Bot
=================================
Strategy brain for the entire marketing operation.
Works alongside facebook_bot.py (organic) and brand_manager.py (visuals).

Responsibilities:
  1. Maintain USP library and translate into platform-specific copy
  2. Run the content arc — coordinates themes across organic + paid
  3. Track full funnel: impressions → clicks → quiz → diagnosed → paid → retained
  4. End-of-day review: what ran, what performed, what to change tomorrow
  5. Weekly strategy email: what's working, what's not, revised plan
  6. Flags to Will: what's needed (photos, budget, copy tests, actions)
  7. A/B copy variants: generate and track which hooks perform best

Goal: 1 new client per week by week 8.

Called from pipeline:
    from skills.marketing_bot import run as run_marketing
    run_marketing(secrets, state, VAULT_ROOT)

Standalone:
    python3 skills/marketing_bot.py --review        # end-of-day review + email
    python3 skills/marketing_bot.py --strategy      # print current strategy
    python3 skills/marketing_bot.py --funnel        # print funnel snapshot
    python3 skills/marketing_bot.py --copy <format> # generate copy (ad|post|email|hook)
"""

import json
import re
import requests
import anthropic
from datetime import datetime, timedelta, timezone
from pathlib import Path

VAULT_ROOT   = Path(__file__).parent.parent
GRAPH        = "https://graph.facebook.com/v22.0"
STRATEGY_FILE = VAULT_ROOT / "clients" / "marketing_strategy.json"
METRICS_FILE  = VAULT_ROOT / "clients" / "social_metrics.json"

# ── USP Library ────────────────────────────────────────────────────────────────
# Source of truth for all copy. Every ad, post hook, and email subject
# must connect back to at least one of these.

USPS = [
    {
        "id": "cost",
        "headline": "For the cost of one night out a week (£16–17)",
        "detail": "Complete personalised system — no templates, no cookie-cutter PDFs",
        "emotion": "value / no-excuse",
    },
    {
        "id": "personalised",
        "headline": "100% personalised — no two programmes are ever the same",
        "detail": "Built from your exact intake: injuries, work hours, family, gym access",
        "emotion": "bespoke / respected",
    },
    {
        "id": "weekly_review",
        "headline": "Weekly personalised review + adjustments every single week",
        "detail": "Will reads your check-in, replies like a mate who gives a shit, tweaks the plan",
        "emotion": "accountability / not alone",
    },
    {
        "id": "accountability",
        "headline": "Someone in your corner for 12 weeks — no ghosting",
        "detail": "No 'log it in the app and disappear'. Real human contact every week.",
        "emotion": "trust / anti-app",
    },
    {
        "id": "science",
        "headline": "Science delivered like a systems guy explaining to another systems guy",
        "detail": "Zone 2, protein timing, sleep hacks, fat-loss math, alcohol strategy",
        "emotion": "intelligent / peer-to-peer",
    },
    {
        "id": "simple_start",
        "headline": "Starts stupidly simple — walking first, barbell later",
        "detail": "20km/day walking built the habit. No 5am bootcamps, no crash diets.",
        "emotion": "accessible / low-barrier",
    },
    {
        "id": "guarantee",
        "headline": "7-day money-back guarantee — no questions, no hard feelings",
        "detail": "If it doesn't feel right in the first week, you're out.",
        "emotion": "risk-free / confidence",
    },
    {
        "id": "transformation",
        "headline": "47. Desk job. 3 stone gone in 9 months. Fitness age 55 → 17.",
        "detail": "Will did it himself. This is his system, not a theory.",
        "emotion": "proof / relatability",
    },
]

# ── Content arc — 12-week rolling theme plan ──────────────────────────────────
# Organic posts follow this arc. Paid ads amplify the highest-performing angle.

ARC_PHASES = [
    {
        "weeks": [1, 2],
        "theme": "Problem Agitation",
        "description": "Make men feel seen. Mirror their exact situation back at them.",
        "usps": ["transformation", "simple_start"],
        "hooks": [
            "Most men over 45 don't have a fitness problem. They have a system problem.",
            "The holiday photo. You know the one.",
            "47. Desk job. Two kids. Zero time. Sound familiar?",
        ],
    },
    {
        "weeks": [3, 4],
        "theme": "Why Everything Else Failed",
        "description": "Discredit gym culture, apps, crash diets. Make them feel validated for quitting before.",
        "usps": ["accountability", "personalised"],
        "hooks": [
            "The gym didn't fail you. The gym's system failed you.",
            "Apps track everything except the one thing that matters: why you stopped.",
            "You didn't lack willpower. You lacked a programme built around your actual life.",
        ],
    },
    {
        "weeks": [5, 6],
        "theme": "The Science (Made Simple)",
        "description": "Educate without patronising. Systems thinkers respect the data.",
        "usps": ["science", "simple_start"],
        "hooks": [
            "Zone 2 cardio burns more fat than going hard. Here's the maths.",
            "Visceral fat doesn't care about your abs workout. It cares about this.",
            "6 hours of sleep is actively preventing your fat loss. The cortisol loop explained.",
        ],
    },
    {
        "weeks": [7, 8],
        "theme": "The System + Proof",
        "description": "Show what's possible. Introduce the programme explicitly.",
        "usps": ["transformation", "weekly_review", "cost"],
        "hooks": [
            "9 months. Here's exactly what I did.",
            "£16 a week. Less than a Friday night. Here's what you get.",
            "What 12 weeks actually does — and it's not just weight loss.",
        ],
    },
    {
        "weeks": [9, 10],
        "theme": "Objection Crushing",
        "description": "Handle every reason not to start. Cost, time, age, gym fear.",
        "usps": ["cost", "simple_start", "guarantee"],
        "hooks": [
            "Too busy? The programme is built around being busy.",
            "Think you're too old? Your biology disagrees.",
            "No gym needed. At least not for the first 6 weeks.",
        ],
    },
    {
        "weeks": [11, 12],
        "theme": "Direct CTA",
        "description": "Close. Quiz link. Urgency. Personal.",
        "usps": ["guarantee", "personalised", "cost"],
        "hooks": [
            "If any of this sounds like you — 2 minutes. That's all it takes.",
            "Free quiz. Personalised plan. Same day. battleshipreset.com",
            "Still thinking about it? That's exactly what I did for 3 years.",
        ],
    },
]

# ── Copy prompts ───────────────────────────────────────────────────────────────

AD_COPY_PROMPT = """You are writing Facebook/Instagram ad copy for Battleship Reset.

USP focus: {usp_headline}
Supporting detail: {usp_detail}
Emotional hook: {emotion}
Arc phase: {arc_theme}

Format: {format}

Voice: Will Barratt — direct, honest, no bullshit. 47-year-old who fixed himself.
Audience: UK men 40-60, desk jobs, know they need to do something, keep putting it off.

Format rules:
- ad_primary: 3-5 sentences. Hook first line. CTA last: "Take the free quiz → battleshipreset.com"
- ad_headline: under 40 chars. Punchy. Statement not question.
- post_hook: first line of a social post. Under 12 words. Stops the scroll.
- email_subject: under 50 chars. Curiosity or direct benefit. No clickbait.

Write only the copy. No preamble."""

STRATEGY_REVIEW_PROMPT = """You are the marketing strategist for Battleship Reset — a 12-week fitness programme for UK men 40-60.

Goal: 1 new paying client per week (£69/week 12 target rate).

Current funnel data:
{funnel_data}

Recent post performance:
{post_performance}

Current arc phase: {arc_phase}
Week of campaign: {campaign_week}

USPs available: {usps}

Analyse the data and produce:
1. What's working (specific, evidence-based)
2. What's not working (specific, with hypothesis why)
3. Tomorrow's priority actions (max 3, numbered)
4. This week's content angle recommendation
5. Anything Will needs to do manually (photos, budget, approvals)

Be direct. No fluff. Talk like a marketing consultant who charges by the insight, not the word."""


# ── State management ───────────────────────────────────────────────────────────

def _load_strategy() -> dict:
    if STRATEGY_FILE.exists():
        return json.loads(STRATEGY_FILE.read_text())
    return {
        "campaign_start": datetime.now(timezone.utc).isoformat(),
        "campaign_week": 1,
        "arc_phase_index": 0,
        "funnel": {
            "impressions": 0,
            "clicks": 0,
            "quiz_starts": 0,
            "diagnosed": 0,
            "paid": 0,
            "retained_week4": 0,
        },
        "copy_tests": [],
        "daily_reviews": [],
        "flags_sent": [],
        "last_review_date": "",
    }


def _save_strategy(s: dict):
    STRATEGY_FILE.write_text(json.dumps(s, indent=2))


def _load_metrics() -> dict:
    if METRICS_FILE.exists():
        return json.loads(METRICS_FILE.read_text())
    return {"posts": {}, "page": {}, "ig": {}}


def _current_arc_phase(strategy: dict) -> dict:
    week = strategy.get("campaign_week", 1)
    for phase in ARC_PHASES:
        if week in phase["weeks"]:
            return phase
    return ARC_PHASES[-1]


def _campaign_week(strategy: dict) -> int:
    start = datetime.fromisoformat(strategy["campaign_start"])
    delta = datetime.now(timezone.utc) - start
    return max(1, min(12, delta.days // 7 + 1))


# ── Funnel tracking ────────────────────────────────────────────────────────────

def update_funnel_from_state(state: dict, strategy: dict):
    """Sync pipeline client state into funnel metrics."""
    clients = state.get("clients", {})
    strategy["funnel"]["diagnosed"] = sum(
        1 for cs in clients.values() if cs["status"] in ("diagnosed", "active", "complete")
    )
    strategy["funnel"]["paid"] = sum(
        1 for cs in clients.values() if cs["status"] in ("active", "complete")
    )
    strategy["funnel"]["retained_week4"] = sum(
        1 for cs in clients.values()
        if cs["status"] == "active" and cs.get("current_week", 0) >= 4
    )


def update_funnel_from_fb(secrets: dict, strategy: dict):
    """Pull ad impressions + clicks from Meta if ad account is available."""
    token      = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    account_id = secrets.get("fb_ad_account_id") or secrets.get("FB_AD_ACCOUNT_ID", "")
    if not token or not account_id:
        return

    r = requests.get(
        f"{GRAPH}/{account_id}/insights",
        params={
            "fields": "impressions,clicks,reach",
            "date_preset": "last_7d",
            "access_token": token,
        },
        timeout=15,
    )
    if r.ok:
        data = r.json().get("data", [{}])[0]
        strategy["funnel"]["impressions"] = int(data.get("impressions", 0))
        strategy["funnel"]["clicks"]      = int(data.get("clicks", 0))
        print(f"  ✅ Ad funnel updated: {strategy['funnel']['impressions']} impressions, {strategy['funnel']['clicks']} clicks")


# ── Copy generation ────────────────────────────────────────────────────────────

def generate_copy(format: str, usp_id: str = None, secrets: dict = None) -> str:
    """Generate a single piece of copy for a given format and USP."""
    strategy = _load_strategy()
    phase    = _current_arc_phase(strategy)

    usp = next((u for u in USPS if u["id"] == usp_id), None) if usp_id else USPS[0]
    # Default to arc-recommended USP
    if not usp:
        arc_usp_id = phase["usps"][0] if phase["usps"] else "transformation"
        usp = next((u for u in USPS if u["id"] == arc_usp_id), USPS[0])

    prompt = AD_COPY_PROMPT.format(
        usp_headline=usp["headline"],
        usp_detail=usp["detail"],
        emotion=usp["emotion"],
        arc_theme=phase["theme"],
        format=format,
    )
    api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic") if secrets else None
    if not api_key:
        return "[No API key — run with secrets]"

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    copy = msg.content[0].text.strip()

    # Log the copy test
    strategy["copy_tests"].append({
        "date":   datetime.now(timezone.utc).isoformat()[:10],
        "format": format,
        "usp":    usp["id"],
        "copy":   copy,
        "phase":  phase["theme"],
        "performance": None,  # updated later when metrics arrive
    })
    _save_strategy(strategy)
    return copy


# ── End-of-day review ─────────────────────────────────────────────────────────

def run_daily_review(secrets: dict, state: dict):
    """
    End-of-day review: analyse funnel + content performance,
    generate strategy recommendations, email Will.
    """
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    strategy = _load_strategy()

    if strategy.get("last_review_date") == today:
        print("  ℹ️  Daily review already sent today")
        return

    # Sync funnel
    update_funnel_from_state(state, strategy)
    update_funnel_from_fb(secrets, strategy)
    strategy["campaign_week"] = _campaign_week(strategy)

    # Get recent post performance
    metrics  = _load_metrics()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_posts = {
        pid: m for pid, m in metrics.get("posts", {}).items()
        if m.get("tracked", "") >= week_ago
    }

    # Build performance summary for Claude
    funnel   = strategy["funnel"]
    ctr      = round(funnel["clicks"] / funnel["impressions"] * 100, 2) if funnel["impressions"] > 0 else 0
    conv_rate = round(funnel["diagnosed"] / funnel["clicks"] * 100, 1) if funnel["clicks"] > 0 else 0

    funnel_text = (
        f"Impressions (7d): {funnel['impressions']}\n"
        f"Clicks (7d): {funnel['clicks']} (CTR: {ctr}%)\n"
        f"Quiz completions / diagnosed: {funnel['diagnosed']}\n"
        f"Paid clients: {funnel['paid']}\n"
        f"Retained to week 4+: {funnel['retained_week4']}\n"
        f"Quiz → paid conversion: {conv_rate}%\n"
        f"Campaign week: {strategy['campaign_week']}/12"
    )

    posts_text = "\n".join(
        f"- \"{m.get('preview', '')[:60]}...\" — {m.get('likes', 0)} likes, {m.get('comments', 0)} comments"
        for m in list(recent_posts.values())[:5]
    ) or "No post data yet"

    phase = _current_arc_phase(strategy)
    usps_text = "\n".join(f"- {u['headline']}" for u in USPS)

    prompt = STRATEGY_REVIEW_PROMPT.format(
        funnel_data=funnel_text,
        post_performance=posts_text,
        arc_phase=phase["theme"],
        campaign_week=strategy["campaign_week"],
        usps=usps_text,
    )

    api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic")
    client  = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    review_text = msg.content[0].text.strip()

    # Generate tomorrow's recommended post hook
    tomorrow_hook = generate_copy("post_hook", usp_id=phase["usps"][0] if phase["usps"] else None, secrets=secrets)
    tomorrow_ad   = generate_copy("ad_headline", usp_id=phase["usps"][0] if phase["usps"] else None, secrets=secrets)

    # Plain text
    plain = (
        f"Daily Marketing Review — {today}\n"
        f"Campaign week {strategy['campaign_week']} · Arc: {phase['theme']}\n\n"
        f"FUNNEL\n{funnel_text}\n\n"
        f"STRATEGY ANALYSIS\n{review_text}\n\n"
        f"TOMORROW'S COPY\n"
        f"Post hook: {tomorrow_hook}\n"
        f"Ad headline: {tomorrow_ad}\n"
    )

    # HTML
    funnel_rows = ""
    metrics_data = [
        ("Impressions (7d)", funnel["impressions"], None),
        ("Clicks", funnel["clicks"], f"CTR {ctr}%"),
        ("Quiz completions", funnel["diagnosed"], None),
        ("Paid clients", funnel["paid"], None),
        ("Retained week 4+", funnel["retained_week4"], None),
    ]
    for label, value, sub in metrics_data:
        sub_html = f'<br><span style="font-size:11px;color:#888;">{sub}</span>' if sub else ""
        funnel_rows += (
            f'<tr style="border-bottom:1px solid #f0ece4;">'
            f'<td style="padding:8px 0;font-size:13px;color:#888888;">{label}</td>'
            f'<td style="padding:8px 0;font-size:16px;font-family:Georgia,serif;color:#0a0a0a;text-align:right;">'
            f'{value}{sub_html}</td></tr>'
        )

    review_html = "".join(
        f'<p style="margin:0 0 10px;font-size:14px;line-height:1.7;color:#2c2c2c;">{line}</p>'
        for line in review_text.split("\n") if line.strip()
    )

    copy_html = (
        f'<p style="margin:0 0 8px;padding:12px 16px;background:#f8f6f1;border-left:3px solid #c41e3a;'
        f'font-size:14px;color:#0a0a0a;"><strong>Post hook:</strong> {tomorrow_hook}</p>'
        f'<p style="margin:0;padding:12px 16px;background:#f8f6f1;border-left:3px solid #0a0a0a;'
        f'font-size:14px;color:#0a0a0a;"><strong>Ad headline:</strong> {tomorrow_ad}</p>'
    )

    from scripts.battleship_pipeline import render_internal_email, send_email
    html = render_internal_email(
        title=f"Daily Review — {today}",
        subtitle=f"Campaign Week {strategy['campaign_week']} · {phase['theme']}",
        sections=[
            {"heading": "Funnel",
             "body": f'<table width="100%" cellpadding="0" cellspacing="0">{funnel_rows}</table>',
             "accent": True},
            {"heading": "Strategy analysis", "body": review_html},
            {"heading": "Tomorrow's copy", "body": copy_html, "accent": True},
        ],
    )

    send_email(
        secrets,
        to="will@battleship.me",
        subject=f"[MARKETING] Daily review — {today}",
        plain_body=plain,
        html_body=html,
    )

    strategy["last_review_date"] = today
    strategy["daily_reviews"].append({"date": today, "review": review_text[:500]})
    strategy["daily_reviews"] = strategy["daily_reviews"][-30:]  # keep last 30
    _save_strategy(strategy)
    print(f"  ✅ Daily marketing review sent to will@battleship.me")


# ── Weekly strategy email ─────────────────────────────────────────────────────

def send_weekly_strategy(secrets: dict, state: dict):
    """Monday only — full weekly strategy report with next week's plan."""
    if datetime.now(timezone.utc).weekday() != 0:
        return

    strategy = _load_strategy()
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_key = f"strategy_{datetime.now(timezone.utc).strftime('%Y-%W')}"
    if week_key in strategy.get("flags_sent", []):
        return

    update_funnel_from_state(state, strategy)
    update_funnel_from_fb(secrets, strategy)
    phase      = _current_arc_phase(strategy)
    next_phase = ARC_PHASES[min(strategy.get("arc_phase_index", 0) + 1, len(ARC_PHASES) - 1)]

    funnel  = strategy["funnel"]
    weekly_target = 1  # clients per week target
    on_track = funnel["paid"] >= (strategy["campaign_week"] // 4)

    # Generate 3 copy variants for next week
    variants = []
    for usp_id in (phase["usps"] + ["transformation"])[:3]:
        hook = generate_copy("post_hook", usp_id=usp_id, secrets=secrets)
        variants.append((usp_id, hook))

    plain = (
        f"Weekly Strategy — {today}\n"
        f"Campaign week {strategy['campaign_week']}\n"
        f"On track for 1 client/week: {'YES' if on_track else 'NO — needs attention'}\n\n"
        f"FUNNEL: {funnel['impressions']} impressions → {funnel['clicks']} clicks → "
        f"{funnel['diagnosed']} quiz → {funnel['paid']} paid\n\n"
        f"THIS WEEK: {phase['theme']}\n"
        f"NEXT WEEK: {next_phase['theme']}\n\n"
        f"COPY VARIANTS FOR THIS WEEK:\n"
        + "\n".join(f"- [{usp}] {hook}" for usp, hook in variants)
    )

    # HTML sections
    track_color = "#2a7a2a" if on_track else "#c41e3a"
    track_label = "On track" if on_track else "Behind target"

    funnel_html = (
        f'<div style="display:flex;gap:16px;">'
        + "".join(
            f'<div style="text-align:center;padding:0 16px 0 0;">'
            f'<p style="margin:0;font-size:24px;font-family:Georgia,serif;color:#0a0a0a;">{v}</p>'
            f'<p style="margin:4px 0 0;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">{l}</p>'
            f'</div>'
            for l, v in [
                ("Impressions", funnel["impressions"]),
                ("Clicks", funnel["clicks"]),
                ("Quiz", funnel["diagnosed"]),
                ("Paid", funnel["paid"]),
            ]
        )
        + f'<div style="text-align:center;padding:0 16px;">'
        f'<p style="margin:0;font-size:14px;font-family:Georgia,serif;color:{track_color};">{track_label}</p>'
        f'<p style="margin:4px 0 0;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">vs 1/week target</p>'
        f'</div>'
        f'</div>'
    )

    arc_html = (
        f'<p style="margin:0 0 6px;font-size:13px;color:#555;">This week: <strong>{phase["theme"]}</strong> — {phase["description"]}</p>'
        f'<p style="margin:0;font-size:13px;color:#555;">Next week: <strong>{next_phase["theme"]}</strong> — {next_phase["description"]}</p>'
    )

    variants_html = "".join(
        f'<p style="margin:0 0 10px;padding:12px 16px;background:#f8f6f1;border-left:3px solid #c41e3a;">'
        f'<span style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">{usp}</span><br>'
        f'<span style="font-size:14px;color:#0a0a0a;">{hook}</span></p>'
        for usp, hook in variants
    )

    from scripts.battleship_pipeline import render_internal_email, send_email
    html = render_internal_email(
        title=f"Weekly Strategy — {today}",
        subtitle=f"Campaign Week {strategy['campaign_week']}",
        sections=[
            {"heading": "Funnel this week", "body": funnel_html, "accent": True},
            {"heading": "Content arc", "body": arc_html},
            {"heading": "Copy variants to use this week", "body": variants_html, "accent": True},
        ],
    )

    send_email(
        secrets,
        to="will@battleship.me",
        subject=f"[MARKETING] Weekly strategy — {today}",
        plain_body=plain,
        html_body=html,
    )

    strategy.setdefault("flags_sent", []).append(week_key)
    _save_strategy(strategy)
    print("  ✅ Weekly marketing strategy sent to will@battleship.me")


# ── Arc coordinator — tells facebook_bot what to post ─────────────────────────

def get_current_arc_guidance() -> dict:
    """
    Called by facebook_bot.py to ensure organic posts are in arc alignment.
    Returns theme, suggested hooks, and USPs to emphasise this week.
    """
    strategy = _load_strategy()
    phase    = _current_arc_phase(strategy)
    return {
        "theme":       phase["theme"],
        "description": phase["description"],
        "hooks":       phase["hooks"],
        "usps":        [u for u in USPS if u["id"] in phase["usps"]],
        "week":        strategy["campaign_week"],
    }


# ── Entry point ────────────────────────────────────────────────────────────────

def review_ideas_bank(secrets: dict):
    """
    Check ideas bank for new drafts — flag to Will if green light needed.
    If any idea is green_lit, develop it into a post draft → content review.
    """
    ideas_file   = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"
    content_file = VAULT_ROOT / "clients" / "content_review.json"
    if not ideas_file.exists():
        return

    ideas_data = json.loads(ideas_file.read_text())
    ideas      = ideas_data.get("ideas", [])
    drafts     = [i for i in ideas if i.get("status") == "draft"]
    green_lit  = [i for i in ideas if i.get("status") == "green_lit" and not i.get("developed_into")]

    # Develop any green-lit ideas into post drafts
    for idea in green_lit:
        print(f"  💡 Developing green-lit idea: {idea['title']}")
        api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic")
        client  = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": (
                f"Write a Facebook post for a fitness coaching business targeting men 40+.\n\n"
                f"Idea: {idea['title']}\nAngle: {idea['angle']}\n\n"
                f"Requirements: 150-250 words. Hook in first line. No corporate language. "
                f"Real, direct voice. End with a question or soft CTA to take the quiz at tally.so/r/rjK752. "
                f"2-3 hashtags at the end only."
            )}]
        )
        post_text = msg.content[0].text.strip()

        # Save to content review
        import uuid as _uuid
        if content_file.exists():
            cr_data = json.loads(content_file.read_text())
        else:
            cr_data = {"posts": []}
        cr_id = "cr_" + _uuid.uuid4().hex[:8]
        cr_data.setdefault("posts", []).append({
            "id":          cr_id,
            "created":     datetime.now(timezone.utc).isoformat(),
            "theme":       idea["title"],
            "content":     post_text,
            "status":      "pending_review",
            "source":      "ideas_bank",
            "idea_id":     idea["id"],
            "post_id":     "",
            "reviewed_at": None,
            "edited":      False,
        })
        content_file.write_text(json.dumps(cr_data, indent=2))

        # Mark idea as developed
        idea["developed_into"] = cr_id
        ideas_file.write_text(json.dumps(ideas_data, indent=2))
        print(f"  ✅ Post draft created for '{idea['title']}' → content review")

        # Telegram notification
        try:
            sys.path.insert(0, str(VAULT_ROOT))
            from scripts.telegram_notify import send_message
            send_message(
                f"💡 <b>New post draft ready:</b> \"{idea['title']}\"\n"
                f"Based on your green-lit idea. Review it in the Business Manager → Content Review."
            )
        except Exception:
            pass

    # Flag if there are unreviewed drafts sitting idle
    if drafts:
        reminders_file = VAULT_ROOT / "brand" / "Marketing" / "reminders.json"
        try:
            import requests as _req
            _req.post("http://localhost:5100/api/reminders", json={
                "added_by": "marketing_bot",
                "type": "other",
                "title": f"Green light an idea from the ideas bank ({len(drafts)} waiting)",
                "description": f"Drafts: {', '.join(i['title'] for i in drafts[:3])}. Reply on Telegram or visit Business Manager.",
                "priority": "medium",
            }, timeout=3)
        except Exception:
            pass


def check_direction(secrets: dict):
    """
    If recent posts are getting zero engagement, flag a direction pivot.
    Called daily by marketing bot run().
    """
    metrics = _load_metrics()
    posts   = list(metrics.get("posts", {}).values())
    if len(posts) < 3:
        return  # not enough data

    # Check last 3 posts for engagement
    recent = sorted(posts, key=lambda p: p.get("tracked", ""), reverse=True)[:3]
    zero_engagement = all(
        (p.get("likes", 0) + p.get("comments", 0) + p.get("shares", 0)) == 0
        for p in recent
    )
    if not zero_engagement:
        return

    print("  ⚠️  3 consecutive posts with zero engagement — flagging direction pivot")
    try:
        import requests as _req
        _req.post("http://localhost:5100/api/reminders", json={
            "added_by": "marketing_bot",
            "type": "other",
            "title": "Direction review needed — 3 posts with zero engagement",
            "description": "Recent posts are getting no traction. Consider: different hook, different time, different format, or pivot the arc phase. Discuss with Claude on Telegram.",
            "priority": "high",
        }, timeout=3)
    except Exception:
        pass

    try:
        from scripts.telegram_notify import send_message
        send_message(
            "⚠️ <b>Direction check</b>\n\n"
            "Last 3 posts got zero engagement. Something's not connecting.\n\n"
            "Want to talk through a pivot? Reply here."
        )
    except Exception:
        pass


def run(secrets: dict, state: dict, vault_root: Path = VAULT_ROOT):
    """Called from battleship_pipeline.py main()."""
    try:
        run_daily_review(secrets, state)
        send_weekly_strategy(secrets, state)
        review_ideas_bank(secrets)
        check_direction(secrets)
    except Exception as e:
        print(f"  ⚠️  Marketing bot error: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()

    parser = argparse.ArgumentParser(description="Battleship Marketing Bot")
    parser.add_argument("--review",    action="store_true", help="Run end-of-day review now")
    parser.add_argument("--strategy",  action="store_true", help="Print current strategy state")
    parser.add_argument("--funnel",    action="store_true", help="Print funnel snapshot")
    parser.add_argument("--copy",      type=str,            help="Generate copy (ad_primary|ad_headline|post_hook|email_subject)")
    parser.add_argument("--usp",       type=str,            help="USP ID to use with --copy")
    args = parser.parse_args()

    if args.review:
        sys.path.insert(0, str(VAULT_ROOT))
        state_file = VAULT_ROOT / "clients" / "state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"clients": {}}
        # Force re-run by clearing last review date
        s = _load_strategy()
        s["last_review_date"] = ""
        _save_strategy(s)
        run_daily_review(secrets, state)

    elif args.strategy:
        s = _load_strategy()
        phase = _current_arc_phase(s)
        print(f"\nCampaign week: {s['campaign_week']}")
        print(f"Arc phase: {phase['theme']} — {phase['description']}")
        print(f"Funnel: {s['funnel']}")
        print(f"\nSuggested hooks:")
        for h in phase["hooks"]:
            print(f"  - {h}")

    elif args.funnel:
        s = _load_strategy()
        f = s["funnel"]
        ctr = round(f["clicks"] / f["impressions"] * 100, 2) if f["impressions"] else 0
        print(f"\nFunnel snapshot:")
        print(f"  Impressions: {f['impressions']}")
        print(f"  Clicks:      {f['clicks']} (CTR {ctr}%)")
        print(f"  Quiz:        {f['diagnosed']}")
        print(f"  Paid:        {f['paid']}")
        print(f"  Retained:    {f['retained_week4']}")

    elif args.copy:
        result = generate_copy(args.copy, usp_id=args.usp, secrets=secrets)
        print(f"\n{result}")

    else:
        parser.print_help()
