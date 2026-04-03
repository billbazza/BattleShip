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
import sys
import uuid
import requests
import anthropic
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

VAULT_ROOT   = Path(__file__).parent.parent
GRAPH        = "https://graph.facebook.com/v22.0"
STRATEGY_FILE = VAULT_ROOT / "clients" / "marketing_strategy.json"
METRICS_FILE  = VAULT_ROOT / "clients" / "social_metrics.json"
CONTENT_REVIEW_FILE = VAULT_ROOT / "clients" / "content_review.json"

IDEA_CATEGORIES = [
    {
        "id": "problem_agitation",
        "label": "Problem Agitation",
        "description": "Name the pain, decline, frustration, or identity hit men over 40 feel.",
        "keywords": ["tired", "exhausted", "old", "crisis", "fine", "body", "stiff", "drained"],
    },
    {
        "id": "founder_proof",
        "label": "Founder Proof",
        "description": "Use Will's own transformation as proof, but only when it adds a fresh lesson.",
        "keywords": ["i ", "my ", "47", "abs", "doctor", "walking", "gym", "stone", "six-pack"],
    },
    {
        "id": "myth_bust",
        "label": "Myth Bust",
        "description": "Attack bad fitness advice, industry lies, or assumptions that keep the audience stuck.",
        "keywords": ["lie", "lied", "industry", "truth", "myth", "accepting", "normal", "failed"],
    },
    {
        "id": "system_education",
        "label": "System Education",
        "description": "Explain a mechanism simply: sleep, cortisol, movement, nutrition, recovery, or habit design.",
        "keywords": ["science", "system", "sleep", "cortisol", "movement", "nutrition", "zone 2", "protein"],
    },
    {
        "id": "objection_crushing",
        "label": "Objection Crushing",
        "description": "Address time, age, price, fear, or gym resistance directly.",
        "keywords": ["busy", "time", "old", "expensive", "price", "cost", "too late", "no gym"],
    },
    {
        "id": "client_case",
        "label": "Client Case",
        "description": "Use a client or composite-client scenario instead of repeating the founder story.",
        "keywords": ["client", "mark", "guy", "member", "men we work with", "lads"],
    },
    {
        "id": "offer_cta",
        "label": "Offer CTA",
        "description": "Explain the programme, what happens next, or who should take the quiz now.",
        "keywords": ["quiz", "programme", "plan", "reset", "personalised", "12-week"],
    },
    {
        "id": "topical_authority",
        "label": "Topical Authority",
        "description": "Use a current conversation, borrowed authority, or cultural reference to create a new entry point.",
        "keywords": ["ozempic", "doctor", "quote", "industry", "headline", "trend"],
    },
]

GENERATOR_STAFF = [
    ("signal_analyst", "reads recent performance, backlog, and learnings to identify what the bank needs next"),
    ("audience_editor", "guards voice and makes sure hooks feel specific to sceptical men 40-60"),
    ("portfolio_manager", "forces variety so the batch behaves like a content slate, not five rewrites"),
    ("conversion_lead", "keeps every idea commercially relevant and tied to the product reality"),
]


def _normalize_ad_account_id(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("act_"):
        return value
    return f"act_{value}" if value else ""

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


def _load_content_review() -> dict:
    if CONTENT_REVIEW_FILE.exists():
        return json.loads(CONTENT_REVIEW_FILE.read_text())
    return {"posts": []}


def _normalise_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _extract_post_date(post: dict) -> str:
    return (
        post.get("tracked")
        or post.get("date")
        or (post.get("created_time", "")[:10] if post.get("created_time") else "")
        or ""
    )


def _clip(text: str, limit: int = 160) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _classify_idea_category(*parts: str) -> str:
    text = _normalise_text(" ".join(p for p in parts if p))
    scores: dict[str, int] = {}
    for cat in IDEA_CATEGORIES:
        score = sum(1 for kw in cat["keywords"] if kw in text)
        if score:
            scores[cat["id"]] = score
    if not scores:
        return "problem_agitation"
    return max(scores.items(), key=lambda item: item[1])[0]


def _serialise_tags(tags) -> str:
    if isinstance(tags, list):
        return json.dumps(tags)
    if isinstance(tags, str):
        return tags
    return "[]"


def _load_marketing_learnings() -> list[dict]:
    try:
        import sys as _sys, pathlib as _pl
        _vault = _pl.Path(__file__).parent.parent
        _sys.path.insert(0, str(_vault))
        import scripts.db as _db
        return _db.get_learnings(source="marketing_bot")
    except Exception:
        return []


def _record_marketing_learning(learning_type: str, text: str, context: str = "") -> None:
    try:
        import sys as _sys, pathlib as _pl
        _vault = _pl.Path(__file__).parent.parent
        _sys.path.insert(0, str(_vault))
        import scripts.db as _db
        _db.record_learning("marketing_bot", learning_type, text, context=context)
    except Exception:
        pass


def _get_marketing_bot_state(key: str) -> str:
    try:
        import sys as _sys, pathlib as _pl
        _vault = _pl.Path(__file__).parent.parent
        _sys.path.insert(0, str(_vault))
        import scripts.db as _db
        return _db.get_bot_state(key) or ""
    except Exception:
        return ""


def _set_marketing_bot_state(key: str, value: str) -> None:
    try:
        import sys as _sys, pathlib as _pl
        _vault = _pl.Path(__file__).parent.parent
        _sys.path.insert(0, str(_vault))
        import scripts.db as _db
        _db.set_bot_state(key, value)
    except Exception:
        pass


def _build_idea_loop_context(ideas_data: dict) -> dict:
    ideas = ideas_data.get("ideas", [])
    review_posts = _load_content_review().get("posts", [])
    metrics_posts = _load_metrics().get("posts", {})
    learnings = _load_marketing_learnings()

    recent_ideas = sorted(
        ideas,
        key=lambda item: ((item.get("added") or ""), (item.get("green_lit") or ""), (item.get("id") or "")),
        reverse=True,
    )[:24]
    category_counts = Counter(
        _classify_idea_category(i.get("title", ""), i.get("angle", ""), i.get("copy", ""))
        for i in recent_ideas
    )
    posted_review = [p for p in review_posts if p.get("status") == "posted"]
    recent_review = sorted(posted_review, key=lambda p: p.get("created", ""), reverse=True)[:12]

    performance_rows = []
    for pid, post in metrics_posts.items():
        date_str = _extract_post_date(post)
        if not date_str:
            continue
        reach = int(post.get("reach", post.get("insights", {}).get("reach", 0) or 0) or 0)
        comments = int(post.get("comments", post.get("insights", {}).get("comments", 0) or 0) or 0)
        likes = int(post.get("likes", post.get("insights", {}).get("likes", 0) or 0) or 0)
        shares = int(post.get("shares", post.get("insights", {}).get("shares", 0) or 0) or 0)
        link_clicks = int(post.get("link_clicks", post.get("insights", {}).get("link_clicks", 0) or 0) or 0)
        score = reach + (comments * 6) + (shares * 8) + (likes * 2) + (link_clicks * 4)
        preview = post.get("preview") or post.get("message", "")
        performance_rows.append({
            "id": pid,
            "date": date_str,
            "score": score,
            "reach": reach,
            "engagement": likes + comments + shares,
            "link_clicks": link_clicks,
            "preview": _clip(preview, 120),
            "category": _classify_idea_category(preview),
        })

    performance_rows.sort(key=lambda row: (row["score"], row["date"]), reverse=True)
    strong_posts = performance_rows[:3]
    weak_posts = sorted(performance_rows, key=lambda row: (row["score"], row["date"]))[:3]

    pending_review = [p for p in review_posts if p.get("status") in {"pending_review", "draft"}]
    rejected_posts = [p for p in review_posts if p.get("status") == "rejected"]
    pending_categories = Counter(_classify_idea_category(p.get("theme", ""), p.get("content", "")) for p in pending_review)

    dominant_categories = [cat for cat, n in category_counts.most_common(2) if n >= 3]
    missing_categories = [cat["id"] for cat in IDEA_CATEGORIES if category_counts.get(cat["id"], 0) == 0]
    needs = []
    if dominant_categories:
        needs.append(f"Recent bank is dominated by {', '.join(dominant_categories)}.")
    if missing_categories:
        needs.append(f"Missing categories in recent bank: {', '.join(missing_categories[:4])}.")
    if pending_categories:
        top_pending = pending_categories.most_common(1)[0][0]
        needs.append(f"Backlog already contains many {top_pending} posts waiting for review.")
    if rejected_posts:
        needs.append(f"{len(rejected_posts)} content-review drafts were rejected; avoid generic rehyping.")

    return {
        "category_counts": dict(category_counts),
        "dominant_categories": dominant_categories,
        "missing_categories": missing_categories,
        "pending_categories": dict(pending_categories),
        "recent_idea_titles": [i.get("title", "") for i in recent_ideas[:16]],
        "recent_idea_snapshots": [
            {
                "title": i.get("title", ""),
                "category": _classify_idea_category(i.get("title", ""), i.get("angle", ""), i.get("copy", "")),
                "status": i.get("status", "draft"),
                "angle": _clip(i.get("angle", ""), 110),
            }
            for i in recent_ideas[:12]
        ],
        "strong_posts": strong_posts,
        "weak_posts": weak_posts,
        "pending_review_count": len(pending_review),
        "rejected_review_count": len(rejected_posts),
        "needs_summary": needs,
        "recent_learnings": learnings[-8:],
        "recent_review_examples": [
            {
                "theme": p.get("theme", ""),
                "status": p.get("status", ""),
                "category": _classify_idea_category(p.get("theme", ""), p.get("content", "")),
            }
            for p in recent_review[:8]
        ],
    }


def _refresh_idea_loop_memory(ideas_data: dict) -> None:
    loop = _build_idea_loop_context(ideas_data)
    strong = loop.get("strong_posts", [])
    weak = loop.get("weak_posts", [])
    dominant = loop.get("dominant_categories", [])

    summary = {
        "strong_categories": [row["category"] for row in strong],
        "weak_categories": [row["category"] for row in weak],
        "dominant_categories": dominant,
        "pending_review_count": loop.get("pending_review_count", 0),
        "rejected_review_count": loop.get("rejected_review_count", 0),
    }
    snapshot = json.dumps(summary, sort_keys=True)
    if _get_marketing_bot_state("marketing_idea_loop_summary") == snapshot:
        return

    if strong:
        top = strong[0]
        _record_marketing_learning(
            "performance_signal",
            f"Recent strongest organic pattern: {top['category']}",
            context=f"{top['preview']} | score={top['score']}",
        )
    if weak:
        bottom = weak[0]
        _record_marketing_learning(
            "performance_signal",
            f"Recent weakest organic pattern: {bottom['category']}",
            context=f"{bottom['preview']} | score={bottom['score']}",
        )
    if "founder_proof" in dominant:
        _record_marketing_learning(
            "pattern_saturation",
            "Founder-proof angle is saturating the bank; force more client/system/objection angles.",
            context=", ".join(dominant),
        )

    _set_marketing_bot_state("marketing_idea_loop_summary", snapshot)


def _choose_generation_slots(loop: dict, phase: dict, batch_size: int = 5) -> list[dict]:
    preferred_order = [
        "problem_agitation",
        "system_education",
        "client_case",
        "objection_crushing",
        "offer_cta",
        "myth_bust",
        "topical_authority",
        "founder_proof",
    ]
    weights = Counter(loop.get("category_counts", {}))
    pending = Counter(loop.get("pending_categories", {}))
    chosen: list[dict] = []
    seen = set()

    def add_slot(cat_id: str, why: str):
        if cat_id in seen or len(chosen) >= batch_size:
            return
        category = next((c for c in IDEA_CATEGORIES if c["id"] == cat_id), None)
        if not category:
            return
        chosen.append({
            "category": cat_id,
            "label": category["label"],
            "brief": category["description"],
            "why": why,
        })
        seen.add(cat_id)

    for cat_id in loop.get("missing_categories", []):
        add_slot(cat_id, "Category absent from the recent bank.")

    if "founder_proof" in loop.get("dominant_categories", []):
        for fallback in ["client_case", "system_education", "objection_crushing"]:
            add_slot(fallback, "Counterweight to repeated founder-story proof.")

    if phase["theme"] in {"The Science (Made Simple)", "The System + Proof"}:
        add_slot("system_education", f"Arc phase {phase['theme']} needs mechanism-led posts.")
    if phase["theme"] == "Objection Crushing":
        add_slot("objection_crushing", "Arc phase explicitly needs objection handling.")
    if phase["theme"] == "Direct CTA":
        add_slot("offer_cta", "Arc phase is closing; at least one idea should sell cleanly.")

    ranked = sorted(
        IDEA_CATEGORIES,
        key=lambda cat: (weights.get(cat["id"], 0) + pending.get(cat["id"], 0), preferred_order.index(cat["id"]) if cat["id"] in preferred_order else 99),
    )
    for cat in ranked:
        why = "Underrepresented across current ideas and review backlog."
        if cat["id"] == "founder_proof":
            why = "Allow one founder-led proof slot only if the slate still needs proof."
        add_slot(cat["id"], why)

    return chosen[:batch_size]


def _render_loop_prompt(loop: dict, phase: dict, slots: list[dict], existing_titles: list[str]) -> str:
    learnings = loop.get("recent_learnings", [])
    learnings_text = "\n".join(
        f"- [{item.get('type', 'note')}] {item.get('text', '')}" + (f" ({item.get('context')})" if item.get("context") else "")
        for item in learnings
    ) or "- No explicit learnings logged yet."

    strong_posts = "\n".join(
        f"- [{row['category']}] {row['preview']} | score={row['score']} reach={row['reach']} eng={row['engagement']} clicks={row['link_clicks']}"
        for row in loop.get("strong_posts", [])
    ) or "- No reliable strong-post data yet."

    weak_posts = "\n".join(
        f"- [{row['category']}] {row['preview']} | score={row['score']} reach={row['reach']} eng={row['engagement']} clicks={row['link_clicks']}"
        for row in loop.get("weak_posts", [])
    ) or "- No reliable weak-post data yet."

    recent_bank = "\n".join(
        f"- [{item['category']}] {item['title']} ({item['status']}) — {item['angle']}"
        for item in loop.get("recent_idea_snapshots", [])
    ) or "- No recent idea history."

    slot_lines = "\n".join(
        f"- {slot['category']}: {slot['brief']} Reason: {slot['why']}"
        for slot in slots
    )

    staff_lines = "\n".join(f"- {name}: {brief}" for name, brief in GENERATOR_STAFF)
    phase_hooks = "\n".join(f"- {hook}" for hook in phase.get("hooks", []))
    return (
        "You are the Battleship Reset idea room. Simulate a four-person staff and output one final coordinated slate.\n\n"
        f"STAFF ROLES\n{staff_lines}\n\n"
        "BUSINESS\n"
        "Battleship Reset = 12-week fitness coaching for men 40-60. Voice: Will Barratt, direct, grounded, anti-fluff, anti-bro-marketing.\n"
        "Original intent: a living business that observes what happened, spots stale patterns, and deliberately introduces new but aligned angles.\n\n"
        f"CURRENT ARC PHASE\n- {phase['theme']}: {phase['description']}\n"
        f"Recommended hooks in this phase:\n{phase_hooks}\n\n"
        "RECENT LOOP SIGNALS\n"
        + "\n".join(f"- {item}" for item in loop.get("needs_summary", []))
        + "\n\n"
        + "TOP / STRONG RECENT POSTS\n"
        + strong_posts
        + "\n\nWEAK / FLAT RECENT POSTS\n"
        + weak_posts
        + "\n\nRECENT BANK SNAPSHOT\n"
        + recent_bank
        + "\n\nRECENT LEARNINGS\n"
        + learnings_text
        + "\n\nEXISTING TITLES TO AVOID\n- "
        + "\n- ".join(existing_titles[:20] or ["None"])
        + "\n\nSLOTS TO FILL\n"
        + slot_lines
        + "\n\nRULES\n"
        + "- Generate exactly one idea per slot.\n"
        + "- Do not produce multiple founder-transformation rewrites unless a slot explicitly requires founder_proof.\n"
        + "- Every idea must feel distinct in category, hook pattern, and proof source.\n"
        + "- Use concrete proof, scenes, or mechanisms. Avoid generic 'you need a plan' filler.\n"
        + "- Stay commercially aligned with Battleship Reset. No motivational poster content.\n"
        + "- If data is weak, infer cautiously from the pattern saturation and backlog signals.\n"
        + "- Prefer underused categories over safe repeats.\n\n"
        + "Return raw JSON only as an array with exactly "
        + str(len(slots))
        + " objects. Each object must be:\n"
        + "[{\"title\":\"...\",\"angle\":\"...\",\"copy\":\"...\",\"category\":\"...\",\"hook_type\":\"...\",\"proof_source\":\"...\",\"staff_note\":\"...\",\"why_now\":\"...\",\"tags\":[\"...\",\"...\"]}]\n"
        + "Copy rules:\n"
        + "- 130-220 words\n"
        + "- First line is a statement, not a question\n"
        + "- Short paragraphs, no bullet points\n"
        + "- End with one natural CTA to quiz or DM\n"
        + "- 2-3 hashtags on final line only\n"
    )


def _parse_json_array(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text).rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group())


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
    token      = secrets.get("FB_USER_TOKEN") or secrets.get("fb_user_token", "")
    account_id = _normalize_ad_account_id(
        secrets.get("fb_ad_account_id") or secrets.get("FB_AD_ACCOUNT_ID", "")
    )
    if not token or not account_id:
        return

    r = requests.get(
        f"{GRAPH}/{account_id}/insights",
        params={
            "date_preset": "last_7d",
            "access_token": token,
        },
        timeout=15,
    )
    if r.ok:
        rows = r.json().get("data", [])
        data = rows[0] if rows else {}
        strategy["funnel"]["impressions"] = int(data.get("impressions", 0))
        strategy["funnel"]["clicks"]      = int(data.get("clicks", 0))
        print(f"  ✅ Ad funnel updated: {strategy['funnel']['impressions']} impressions, {strategy['funnel']['clicks']} clicks")
    else:
        print(f"  ⚠️  Meta insights API {r.status_code} — funnel metrics not updated")


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

    # Inject Will's learnings
    learnings_hint = ""
    try:
        import sys as _sys, pathlib as _pl
        _vault = _pl.Path(__file__).parent.parent
        _sys.path.insert(0, str(_vault))
        import scripts.db as _db
        _learnings = _db.get_learnings(source="marketing_bot")
        if _learnings:
            lines = [f"- [{l['type']}] {l['text']}" + (f" ({l['context']})" if l.get('context') else "")
                     for l in _learnings[-10:]]
            learnings_hint = "\n\nWILL'S FEEDBACK (act on these):\n" + "\n".join(lines)
    except Exception:
        pass

    prompt = AD_COPY_PROMPT.format(
        usp_headline=usp["headline"],
        usp_detail=usp["detail"],
        emotion=usp["emotion"],
        arc_theme=phase["theme"],
        format=format,
    ) + learnings_hint
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

    ideas_file = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"
    if ideas_file.exists():
        try:
            _refresh_idea_loop_memory(json.loads(ideas_file.read_text()))
        except Exception as e:
            print(f"  ⚠️  Idea loop memory refresh failed: {e}")

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

    # Check if ads are intentionally paused
    ads_paused = False
    ads_paused_reason = ""
    try:
        import sys as _sys_ap; _sys_ap.path.insert(0, str(VAULT_ROOT))
        import scripts.db as _db_ap
        ads_paused_reason = _db_ap.get_bot_state("ads_paused_reason") or ""
        ads_paused = bool(ads_paused_reason)
    except Exception:
        pass

    ads_note = f"\nNOTE: Paid ads intentionally paused ({ads_paused_reason}) — zero impressions is expected, do not flag as a problem." if ads_paused else ""

    funnel_text = (
        f"Impressions (7d): {funnel['impressions']}\n"
        f"Clicks (7d): {funnel['clicks']} (CTR: {ctr}%)\n"
        f"Quiz completions / diagnosed: {funnel['diagnosed']}\n"
        f"Paid clients: {funnel['paid']}\n"
        f"Retained to week 4+: {funnel['retained_week4']}\n"
        f"Quiz → paid conversion: {conv_rate}%\n"
        f"Campaign week: {strategy['campaign_week']}/12"
        f"{ads_note}"
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

def _generate_new_ideas(secrets: dict, ideas_data: dict, ideas_file, force: bool = False, reason: str = "bank_low") -> int:
    """
    Generate a coordinated slate of draft ideas.
    The loop now studies recent output, avoids overused categories, and fills
    deliberate content slots so the bank keeps behaving like a living system.
    Returns number of ideas added.
    """
    today = datetime.now(timezone.utc)
    if not force and today.weekday() != 0:
        return 0
    today_str = today.strftime("%Y-%m-%d")
    if not force and ideas_data.get("last_generation_date") == today_str:
        print("  ℹ️  Ideas already generated today — skipping")
        return 0

    # Build rich context: titles + angles from all non-archived ideas
    existing_ideas = [i for i in ideas_data.get("ideas", []) if i.get("status") != "archived"]
    existing_titles = [i.get("title", "") for i in existing_ideas]
    existing_angles = [i.get("angle", "") for i in existing_ideas if i.get("angle")]

    # Also include themes from published DB posts
    try:
        import sys as _sys_gi
        _sys_gi.path.insert(0, str(VAULT_ROOT))
        import scripts.db as _db_gi
        _db_gi.init_db()
        for p in _db_gi.get_posts():
            t = p.get("theme", "")
            if t and t not in existing_titles:
                existing_titles.append(t)
    except Exception:
        pass

    # Identify which themes are saturated (3+ ideas on same core topic)
    _theme_keywords = {
        "no-gym": ["gym", "abs", "set foot"],
        "fitness-age": ["fitness age", "17", "body is 30", "younger than"],
        "exhaustion": ["exhausted", "tired", "can't sleep", "energy"],
        "hormones": ["testosterone", "hormone", "metabolism", "belly"],
        "body-stopped": ["stopped responding", "stopped respond", "wrong programme"],
        "midlife": ["midlife", "midlife crisis", "45", "47", "50"],
        "weight": ["weight", "stone", "fat", "belly appeared"],
    }
    saturated_themes = []
    for theme_name, kws in _theme_keywords.items():
        count = sum(1 for t in existing_titles + existing_angles
                    if any(k.lower() in t.lower() for k in kws))
        if count >= 3:
            saturated_themes.append(theme_name)

    # Collect published ideas (developed_into set) as potential inspiration seeds
    published_ideas = [i for i in existing_ideas if i.get("developed_into")]
    seed_lines = ""
    if published_ideas:
        seed_lines = (
            "\n\nSUCCESSFUL published ideas (use as INSPIRATION ONLY — "
            "build completely new angles from these proven themes, do NOT restate them):\n"
            + "\n".join(f"- {i['title']}: {i.get('angle','')}" for i in published_ideas[-8:])
        )

    strategy = _load_strategy()
    phase    = _current_arc_phase(strategy)
    loop     = _build_idea_loop_context(ideas_data)
    slots    = _choose_generation_slots(loop, phase, batch_size=5)

    # Build the used-angles block for the prompt
    used_block = "\n".join(
        f"- TITLE: {i.get('title','')} | ANGLE: {i.get('angle','')}"
        for i in existing_ideas if i.get("title")
    )

    api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic")
    if not api_key:
        print("  ⚠️  No Anthropic key available for idea generation")
        return 0
    client  = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": _render_loop_prompt(loop, phase, slots, existing_titles)}]
    )
    try:
        new_ideas = _parse_json_array(msg.content[0].text)
    except Exception as e:
        print(f"  ⚠️  Idea generation parse error: {e}")
        return 0

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

    added = 0
    existing_normalised = {_normalise_text(title) for title in existing_titles}
    for item in new_ideas[:len(slots)]:
        title = item.get("title", "").strip()
        if not title:
            continue
        if _normalise_text(title) in existing_normalised:
            print(f"  ⚠️  Skipping title duplicate: {title[:50]}")
            continue
        new_angle = item.get("angle", "")
        if new_angle and _angle_is_duplicate(new_angle, existing_angles):
            print(f"  ⚠️  Skipping angle duplicate: {title[:50]}")
            continue
        category = item.get("category") or _classify_idea_category(title, item.get("angle", ""), item.get("copy", ""))
        tags = item.get("tags") or [category, phase["theme"].lower().replace(" ", "_")]
        notes = " | ".join(filter(None, [
            f"Loop reason: {reason}",
            item.get("staff_note", "").strip(),
            f"Hook type: {item.get('hook_type', '').strip()}",
            f"Proof: {item.get('proof_source', '').strip()}",
        ]))
        idea = {
            "id":           "idea_" + uuid.uuid4().hex[:8],
            "title":        title,
            "angle":        new_angle,
            "copy":         item.get("copy", ""),
            "status":       "draft",
            "added":        today_str,
            "source":       "marketing_bot_loop",
            "developed_into": "",
            "notes":        notes,
            "photo_id":     "",
            "category":     category,
            "hook_type":    item.get("hook_type", ""),
            "proof_source": item.get("proof_source", ""),
            "why_now":      item.get("why_now", ""),
            "tags":         tags,
        }
        ideas_data.setdefault("ideas", []).append(idea)
        existing_normalised.add(_normalise_text(title))
<<<<<<< Updated upstream
        try:
            import sys as _sys_gen
            _sys_gen.path.insert(0, str(VAULT_ROOT))
            import scripts.db as _db_gen
            _db_gen.upsert_idea({
                "id": idea["id"],
                "title": idea["title"],
                "angle": idea["angle"],
                "copy": idea["copy"],
                "status": idea["status"],
                "source": idea["source"],
                "developed_into": "",
                "notes": idea["notes"],
                "tags": _serialise_tags(idea.get("tags", [])),
                "photo_id": idea.get("photo_id") or "",
                "added_at": idea.get("added", today_str),
            })
        except Exception:
            pass
=======
        existing_angles.append(new_angle)
>>>>>>> Stashed changes
        added += 1

    if added:
        ideas_data["last_generation_date"] = today_str
        ideas_data["last_generation_reason"] = reason
        ideas_data["last_generation_slots"] = slots
        ideas_file.write_text(json.dumps(ideas_data, indent=2))
        summary = ", ".join(slot["category"] for slot in slots[:added])
        print(f"  ✅ {added} new draft ideas generated — slate: {summary}")
        for slot in slots[:added]:
            _record_marketing_learning(
                "idea_loop_slot",
                f"Filled {slot['category']} slot for {phase['theme']}",
                context=slot["why"],
            )
    return added


def review_ideas_bank(secrets: dict):
    """
    Weekly ideas bank maintenance.
    Generates a fresh batch of draft ideas on Mondays if fewer than 3 undeveloped drafts remain.
    Ideas must be approved/rejected manually via the dashboard — nothing goes live automatically.
    """
    ideas_file = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"
    if not ideas_file.exists():
        return

    ideas_data = json.loads(ideas_file.read_text())
    ideas      = ideas_data.get("ideas", [])

    # ── Arc gate: phase is driven by campaign week, never runs ahead of the calendar ──
    import sys as _sys_rb
    _sys_rb.path.insert(0, str(VAULT_ROOT))
    import scripts.db as _db_rb

    strategy = _load_strategy()
<<<<<<< Updated upstream
    current_idx = strategy.get("arc_phase_index", 0)
    pending = _db_rb.count_pending_posts_for_arc(current_idx)
    phase_posts = [p for p in _db_rb.get_posts() if int(p.get("arc_phase", 0) or 0) == current_idx]

    if pending > 0:
        print(f"  ℹ️  Arc phase {current_idx + 1} has {pending} pending posts — holding phase")
    elif not phase_posts:
        print(f"  ℹ️  Arc phase {current_idx + 1} has no generated posts yet — holding phase")
    else:
        # All posts for current phase are done (or none exist yet) — advance
        if current_idx < len(ARC_PHASES) - 1:
=======
    strategy["campaign_week"] = _campaign_week(strategy)  # refresh before checking phase

    # Compute the correct index based on campaign week — this is the source of truth
    week = strategy["campaign_week"]
    week_based_idx = next(
        (i for i, p in enumerate(ARC_PHASES) if week in p["weeks"]),
        len(ARC_PHASES) - 1,
    )
    current_idx = strategy.get("arc_phase_index", 0)

    # Detect and correct a runaway advance (arc jumped ahead of campaign week)
    if current_idx > week_based_idx:
        print(f"  ⚠️  Arc phase index ({current_idx + 1}) ahead of campaign week {week} — resetting to {week_based_idx + 1}")
        current_idx = week_based_idx
        strategy["arc_phase_index"] = current_idx
        _save_strategy(strategy)

    # Only advance when the campaign week has moved us into the next phase
    # AND there are no pending posts still in queue from the current phase
    if week_based_idx > current_idx:
        pending = _db_rb.count_pending_posts_for_arc(current_idx)
        if pending > 0:
            print(f"  ℹ️  Campaign week {week} ready for phase {week_based_idx + 1} but {pending} phase-{current_idx + 1} posts still queued — holding")
        else:
>>>>>>> Stashed changes
            old_idx = current_idx
            current_idx = week_based_idx
            strategy["arc_phase_index"] = current_idx
            _save_strategy(strategy)
            phase = _current_arc_phase(strategy)
            print(f"  ✅ Arc phase advanced: {old_idx + 1} → {current_idx + 1} ({phase['theme']})")
    else:
        print(f"  ℹ️  Arc phase {current_idx + 1} ({ARC_PHASES[current_idx]['theme']}) — campaign week {week}")

    draft_ideas = [
        i for i in ideas
        if i.get("status") in {"draft", "ideas_bank"} and not i.get("developed_into")
    ]
    undeveloped_drafts = len(draft_ideas)
    loop = _build_idea_loop_context(ideas_data)
    stale_mix = "founder_proof" in loop.get("dominant_categories", []) and undeveloped_drafts < 6

    if stale_mix:
        print("  ℹ️  Ideas bank is repetitive — forcing a diversity refill")
    if undeveloped_drafts < 3 or stale_mix:
        print(f"  ℹ️  Ideas bank needs refresh ({undeveloped_drafts} usable drafts)")
        _generate_new_ideas(
            secrets,
            ideas_data,
            ideas_file,
            force=stale_mix,
            reason="stale_mix" if stale_mix else "bank_low",
        )


def check_direction(secrets: dict):
    """
    If recent posts have zero engagement, act autonomously:
    advance the arc phase and regenerate next queued posts with a sharper hook.
    Logs what it did — no action item for Will.
    """
    metrics = _load_metrics()
    posts   = list(metrics.get("posts", {}).values())
    if len(posts) < 3:
        return

    recent = sorted(posts, key=lambda p: p.get("tracked", ""), reverse=True)[:3]
    zero_engagement = all(
        (p.get("likes", 0) + p.get("comments", 0) + p.get("shares", 0)) == 0
        for p in recent
    )
    if not zero_engagement:
        return

    print("  ⚠️  3 consecutive zero-engagement posts — regenerating queued posts with sharper hooks")

    # Arc phase advancement is handled by the gate in review_ideas_bank() —
    # check_direction() only regenerates queued content, never touches the arc index.
    strategy = _load_strategy()
    phase = _current_arc_phase(strategy)

    # Regenerate next 3 queued posts with sharper hooks for the current arc phase
    import sys as _sys
    _sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as _db
    try:
        queued = _db.get_posts(stage="fb_queue")[:3]
        api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic")
        client  = anthropic.Anthropic(api_key=api_key)
        for p in queued:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=900,
                messages=[{"role": "user", "content": (
                    f"Rewrite this Facebook post for Battleship Reset with a much sharper hook.\n\n"
                    f"Current arc phase: {phase['theme']} — {phase['description']}\n"
                    f"Original theme: {p['theme']}\n\n"
                    f"Rules:\n"
                    f"- 150-250 words\n"
                    f"- First line must STOP the scroll — a bold fact or provocative statement\n"
                    f"- Align the angle with the arc phase: {phase['theme']}\n"
                    f"- Direct, honest voice (Will Barratt, 47, transformed himself)\n"
                    f"- MUST end with: battleshipreset.com — take the free quiz\n"
                    f"- 2-3 hashtags on final line only\n"
                    f"- Write only the post"
                )}]
            )
            new_content = msg.content[0].text.strip()
            _db.update_post(p["id"], {"content": new_content})
            print(f"  ✅ Regenerated: {p['theme'][:50]}")
    except Exception as e:
        print(f"  ⚠️  Post regeneration failed: {e}")

    # 3. Auto-assign photos to queued posts missing one
    try:
        from skills.facebook_bot import _make_post_image
        queued_all = _db.get_posts(stage="fb_queue")
        no_photo = [p for p in queued_all if not p.get("image_path")]
        for p in no_photo[:5]:
            img = _make_post_image(p["content"], p["theme"], secrets)
            if img:
                _db.update_post(p["id"], {"image_path": str(img)})
                print(f"  ✅ Auto-assigned photo: {p['theme'][:45]}")
    except Exception as e:
        print(f"  ⚠️  Photo auto-assign failed: {e}")



def _sync_ideas_to_db() -> None:
    """Sync ideas-bank.json → SQLite. Never downgrades a status (archived stays archived). Removes DB ideas not in JSON."""
    _STATUS_RANK = {"draft": 0, "green_lit": 1, "ideas_bank": 1, "archived": 2}
    try:
        import sys as _sys
        _sys.path.insert(0, str(VAULT_ROOT))
        import scripts.db as _db
        ideas_file = VAULT_ROOT / "brand" / "Marketing" / "ideas-bank.json"
        if not ideas_file.exists():
            return
        data  = json.loads(ideas_file.read_text())
        ideas = data.get("ideas", [])
        json_ids = {i["id"] for i in ideas if i.get("id")}
        json_dirty = False
        for idea in ideas:
            if not idea.get("id"):
                continue
            json_status = idea.get("status", "draft")
            existing    = _db.get_idea(idea["id"])
            if existing:
                db_status = existing.get("status", "draft")
                if _STATUS_RANK.get(db_status, 0) > _STATUS_RANK.get(json_status, 0):
                    # DB has a more final status — propagate back to JSON, skip DB write
                    idea["status"] = db_status
                    json_dirty = True
                    continue
            _db.upsert_idea({
                "id":             idea["id"],
                "title":          idea.get("title", ""),
                "angle":          idea.get("angle", ""),
                "copy":           idea.get("copy", ""),
                "status":         json_status,
                "source":         idea.get("source", "marketing_bot"),
                "notes":          idea.get("notes", ""),
                "tags":           _serialise_tags(idea.get("tags", [])),
                "photo_id":       idea.get("photo_id"),
                "developed_into": idea.get("developed_into") or "",
                "added_at":     idea.get("added", idea.get("created", datetime.now(timezone.utc).date().isoformat())),
                "green_lit_at": idea.get("green_lit") or idea.get("green_lit_at"),
            })
        # Remove DB ideas that no longer exist in JSON
        deleted = _db.delete_ideas_not_in(list(json_ids))
        if json_dirty:
            ideas_file.write_text(json.dumps(data, indent=2))
        print(f"  🔄 Synced {len(ideas)} ideas → DB ({deleted} removed)")
    except Exception as e:
        print(f"  ⚠️  ideas DB sync failed: {e}")


def run(secrets: dict, state: dict, vault_root: Path = VAULT_ROOT):
    """Called from battleship_pipeline.py main(). Each step runs independently."""
    steps = [
        ("daily review",    lambda: run_daily_review(secrets, state)),
        ("weekly strategy", lambda: send_weekly_strategy(secrets, state)),
        ("ideas bank",      lambda: review_ideas_bank(secrets)),
        ("check direction", lambda: check_direction(secrets)),
        ("sync ideas→db",   lambda: _sync_ideas_to_db()),
    ]
    for name, fn in steps:
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"  ❌ Marketing bot — {name} failed: {e}")
            print(traceback.format_exc()[-600:])


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
