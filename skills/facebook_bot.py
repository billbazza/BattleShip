"""
Battleship — Facebook Page Bot
Generates content via Claude, posts to Facebook Page via Graph API.

When FB_PAGE_ACCESS_TOKEN is not set, all output goes to facebook_queue/
instead of posting live. Set the token and it goes live automatically.

Usage (standalone test):
    python3 skills/facebook_bot.py --post          # generate + queue/post one post
    python3 skills/facebook_bot.py --queue          # show queued posts
    python3 skills/facebook_bot.py --flush          # post all queued items live

Called from pipeline:
    from skills.facebook_bot import run
    run(secrets, VAULT_ROOT)
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import anthropic

# ── Constants ─────────────────────────────────────────────────────────────────

GRAPH   = "https://graph.facebook.com/v22.0"
VAULT_ROOT = Path(__file__).parent.parent

QUEUE_DIR           = VAULT_ROOT / "facebook_queue"
SCHEDULE_FILE       = VAULT_ROOT / "clients" / "facebook_schedule.json"
STATE_FILE          = VAULT_ROOT / "clients" / "facebook_state.json"
CONTENT_REVIEW_FILE = VAULT_ROOT / "clients" / "content_review.json"

# Post 3x/week: Mon, Wed, Fri
POST_DAYS = {0, 2, 4}

# ── Content themes ─────────────────────────────────────────────────────────────

POST_THEMES = [
    "Why men over 45 keep failing at fitness — and the one thing that actually changes it. Be specific and honest. Reference the real reasons (wrong system, not wrong person).",
    "Visceral fat — what it is, why it's more dangerous than the fat you can see, and the fastest lever to shift it. Reference insulin and fasting briefly.",
    "Zone 2 cardio: why 30 minutes at controlled, conversational intensity burns more fat than going hard. It's not slow — it's the right fuel system. Explain the science simply.",
    "The 80/20 rule of nutrition. What to cut first, what to never give up. Make it feel achievable not restrictive.",
    "A personal story moment from Will — a specific day or memory from when he was unfit and what changed. Raw, not polished.",
    "Sleep and fat loss. Most men don't know that 6 hours of sleep is actively preventing fat loss. Explain the cortisol/insulin loop simply.",
    "Why strength training after 45 is non-negotiable — not for aesthetics, for longevity. Make it feel accessible not intimidating.",
    "The alcohol question. Not 'stop drinking' — a realistic honest take on what alcohol actually does to fat loss and recovery.",
    "Energy vs fitness. Most men think they're tired because they're unfit. It's usually the other way around. The first 3 weeks of the programme change this.",
    "What 12 weeks actually does. Not a transformation photo — a realistic description of what changes: waist, energy, sleep, confidence, blood pressure.",
    "The gym is optional. A post for men who don't want to join a gym. Dumbbells, bands, bodyweight — what's actually possible at home.",
    "Progressive overload explained simply. Why adding one rep or 2.5kg per week is the entire secret to getting stronger. No complexity needed.",
]

POST_PROMPT = """You are writing an organic Facebook post for Battleship Reset — a fitness coaching programme for men 45-60.

Theme: {theme}

Voice: Will Barratt — direct, honest, no bullshit. Has been through it himself (fat at 47, sorted it out with a simple system). Not a gym bro. Talks like a real person, not a brand.

Rules:
- 150-250 words
- First line is the hook — a statement or a fact, NOT "Hey guys" or a question
- No hashtags in the body — add 2-3 relevant ones on a separate line at the end
- One CTA at the very end — vary it across posts, rotating through these naturally:
  "If this sounds like you, take the free quiz at battleshipreset.com — takes 2 minutes and gets you a personalised plan."
  "Answer a few quick questions at battleshipreset.com and get a free personalised reset plan back the same day."
  "If any of this lands, the free quiz at battleshipreset.com is the place to start. Two minutes. No obligation."
  "battleshipreset.com — take the free quiz and find out what your programme actually looks like."
- Maximum 1 emoji, or none
- Do not use bullet points — write in short paragraphs
- Sound like a real person wrote it, not a marketer
- If using stone for weight, add lbs in brackets: e.g. "three stone (42 lbs)"

Write only the post. No subject line, no preamble, no "Here's a post:"."""

COMMENT_PROMPT = """You are Will Barratt, coach at Battleship Reset. Reply to this comment on your Facebook page.

Post topic: {post_topic}
Comment: "{comment}"

Rules:
- 1-3 sentences max
- Warm and direct — not corporate, not sales-y
- If they're asking about the programme or how to sign up: mention the free quiz at battleshipreset.com
- If it's a positive comment: acknowledge specifically, don't just say "thanks!"
- If it's a negative or trolling comment: return exactly the string SKIP
- Never use hashtags or more than 1 emoji
- Sound human

Reply only. Nothing else."""

DM_PROMPT = """You are Will Barratt at Battleship Reset. Reply to this Facebook Messenger message.

Message: "{message}"

Rules:
- Under 80 words
- Warm and direct
- If asking about the programme, cost, or how it works: send them to the free quiz at battleshipreset.com — tell them it takes 2 minutes and they get a personalised plan back same day
- If they've already signed up: thank them, tell them to check their email for their diagnosis
- If it's spam or clearly not relevant: return exactly the string SKIP
- Do not invent pricing or programme details beyond what's above

Reply only."""


# ── Claude helpers ─────────────────────────────────────────────────────────────

def _claude(prompt: str, secrets: dict, max_tokens: int = 600) -> str:
    client = anthropic.Anthropic(api_key=secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY") or secrets.get("anthropic"))
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ── Queue helpers ──────────────────────────────────────────────────────────────

def _save_to_content_review(content: str, theme: str, status: str = "pending_review",
                             source: str = "facebook_bot", post_id: str = "",
                             idea_id: str = "", image_path: str = ""):
    """Save a post draft to the DB content_review stage (authoritative) + legacy JSON."""
    import sys as _sys
    _sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as _db
    _db.insert_post({
        "theme":      theme,
        "content":    content,
        "stage":      "content_review",
        "source":     source,
        "idea_id":    idea_id or "",
        "image_path": image_path or "",
    })


def _queue_post(content: str, theme: str, image_path=None):
    """Save a generated post to the DB (content_review) for dashboard approval."""
    _save_to_content_review(content, theme, status="pending_review",
                            image_path=str(image_path) if image_path else "")
    print(f"  → Post queued for content review in dashboard")


def _make_post_image(post_text: str, theme: str, secrets: dict) -> Path | None:
    """
    Generate an image card for a scheduled post.
    Strategy:
      1. Try to find a suitable non-face photo from the catalogue
      2. If found: burn the first sentence of the post as a hook overlay
      3. If not found: create a dark quote card with the hook text
    Returns the output Path or None on failure.
    """
    try:
        from skills.brand_manager import create_post_card, create_quote_card, load_catalogue
        import hashlib

        # First sentence = hook burned onto image (max 80 chars)
        first_sentence = post_text.split("\n")[0].split(".")[0].strip()
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "…"
        slug = hashlib.md5(post_text.encode()).hexdigest()[:8]

        # Pick a non-face photo from catalogue
        cat = load_catalogue()
        QUALITY_RANK = {"best": 0, "good": 1, "usable": 2}
        PREFER_USE = {"social_post", "lifestyle_post", "equipment_post", "nutrition_post", "progress_post"}
        candidates = []
        for key, meta in cat.items():
            tags = meta.get("tags", [])
            if "face" in tags:
                continue
            score = (QUALITY_RANK.get(meta.get("quality", "usable"), 2),
                     0 if bool(set(meta.get("use_cases", [])) & PREFER_USE) else 1)
            candidates.append((score, VAULT_ROOT / "brand" / key))
        candidates.sort(key=lambda x: x[0])

        # Also scan random-snaps for uncatalogued images
        snap_dir = VAULT_ROOT / "brand" / "random-snaps"
        cat_keys = set(cat.keys())
        IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG"}
        if snap_dir.exists():
            for img in sorted(snap_dir.iterdir()):
                if img.is_dir():
                    continue  # skip drafts/ and any other subdirs
                rel = "random-snaps/" + img.name
                if img.suffix in IMG_EXTS and rel not in cat_keys:
                    candidates.append(((2, 1), img))

        # Pick first candidate that actually exists on disk
        chosen = None
        for _, p in candidates:
            if Path(p).exists():
                chosen = p
                break

        if chosen:
            return create_post_card(chosen, first_sentence,
                                    output_name=f"post_card_{slug}.jpg")
        else:
            # No suitable photo — dark quote card
            return create_quote_card(first_sentence,
                                     output_name=f"quote_card_{slug}.jpg")
    except Exception as e:
        print(f"  ⚠️  Image generation skipped: {e}")
        return None


def _load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        return json.loads(SCHEDULE_FILE.read_text())
    return {"posted_dates": [], "theme_index": 0, "replied_comments": [], "replied_dms": []}


def _save_schedule(s: dict):
    SCHEDULE_FILE.write_text(json.dumps(s, indent=2))


# ── Graph API helpers ──────────────────────────────────────────────────────────

def _is_live(secrets: dict) -> bool:
    return bool(secrets.get("FB_PAGE_ACCESS_TOKEN") and secrets.get("FB_PAGE_ID"))


def _post_live(message: str, secrets: dict) -> str:
    r = requests.post(
        f"{GRAPH}/{secrets['FB_PAGE_ID']}/feed",
        data={"message": message, "access_token": secrets["FB_PAGE_ACCESS_TOKEN"]},
        timeout=15,
    )
    if not r.ok:
        print(f"  FB error: {r.status_code} {r.text}")
    r.raise_for_status()
    return r.json().get("id", "")


def _get_recent_posts(secrets: dict) -> list:
    r = requests.get(
        f"{GRAPH}/{secrets['FB_PAGE_ID']}/posts",
        params={"access_token": secrets["FB_PAGE_ACCESS_TOKEN"],
                "fields": "id,message,created_time", "limit": 10},
        timeout=15,
    )
    return r.json().get("data", [])


def _get_comments(post_id: str, secrets: dict) -> list:
    token = secrets.get("FB_SYSTEM_TOKEN") or secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    r = requests.get(
        f"{GRAPH}/{post_id}/comments",
        params={"access_token": token,
                "fields": "id,message,from,created_time"},
        timeout=15,
    )
    return r.json().get("data", [])


def _reply_comment(comment_id: str, message: str, secrets: dict):
    requests.post(
        f"{GRAPH}/{comment_id}/comments",
        data={"message": message, "access_token": secrets["FB_PAGE_ACCESS_TOKEN"]},
        timeout=15,
    ).raise_for_status()


def _get_conversations(secrets: dict) -> list:
    r = requests.get(
        f"{GRAPH}/{secrets['FB_PAGE_ID']}/conversations",
        params={"access_token": secrets["FB_PAGE_ACCESS_TOKEN"],
                "fields": "id,messages{id,message,from,created_time}"},
        timeout=15,
    )
    return r.json().get("data", [])


def _send_dm(recipient_id: str, message: str, secrets: dict):
    requests.post(
        f"{GRAPH}/{secrets['FB_PAGE_ID']}/messages",
        json={"recipient": {"id": recipient_id},
              "messaging_type": "RESPONSE",
              "message": {"text": message}},
        params={"access_token": secrets["FB_PAGE_ACCESS_TOKEN"]},
        timeout=15,
    ).raise_for_status()


# ── Core jobs ──────────────────────────────────────────────────────────────────

def post_scheduled_content(secrets: dict):
    """Generate and queue one post for review on Mon/Wed/Fri. Never auto-posts live."""
    today = datetime.now(timezone.utc)
    if today.weekday() not in POST_DAYS:
        return

    schedule = _load_schedule()
    date_key = today.strftime("%Y-%m-%d")
    if date_key in schedule["posted_dates"]:
        return  # already queued today

    # Write the date guard immediately to prevent double-run on simultaneous wake
    schedule["posted_dates"].append(date_key)
    _save_schedule(schedule)

    idx   = schedule["theme_index"] % len(POST_THEMES)
    theme = POST_THEMES[idx]

    # Pull arc guidance from marketing bot to keep organic content aligned
    arc_hint = ""
    try:
        from skills.marketing_bot import get_current_arc_guidance
        arc = get_current_arc_guidance()
        arc_hint = (f"\n\nARC ALIGNMENT (week {arc['week']}): This post should lean into "
                    f"'{arc['theme']}' — {arc['description']}. "
                    f"If relevant, these hooks are performing: {'; '.join(arc['hooks'][:2])}")
    except Exception:
        pass

    # Inject Will's learnings (pivot notes, dismissals, send-backs) into prompt
    learnings_hint = ""
    try:
        import sys as _sys
        _sys.path.insert(0, str(VAULT_ROOT))
        import scripts.db as _db
        _learnings = _db.get_learnings(source="facebook_bot")
        if _learnings:
            lines = [f"- [{l['type']}] {l['text']}" + (f" ({l['context']})" if l.get('context') else "")
                     for l in _learnings[-10:]]
            learnings_hint = "\n\nWILL'S FEEDBACK (act on these):\n" + "\n".join(lines)
    except Exception:
        pass

    post = _claude(POST_PROMPT.format(theme=theme) + arc_hint + learnings_hint, secrets)

    # Generate image card — always goes to pending_review, approved via dashboard
    image_path = _make_post_image(post, theme, secrets)
    _queue_post(post, theme, image_path=image_path)
    print(f"  ✓ Facebook post + image queued for review (pending approval in dashboard)")

    schedule["theme_index"] = idx + 1
    _save_schedule(schedule)


def reply_to_new_comments(secrets: dict):
    """Scan recent posts for unanswered comments and reply via Claude."""
    if not _is_live(secrets):
        return  # comments only make sense when live

    schedule = _load_schedule()
    replied  = set(schedule.get("replied_comments", []))
    posts    = _get_recent_posts(secrets)

    page_id = secrets.get("FB_PAGE_ID", "")
    for post in posts:
        post_topic = (post.get("message", "") or "")[:120]
        for comment in _get_comments(post["id"], secrets):
            cid = comment["id"]
            if cid in replied:
                continue
            # Skip comments made by the page itself (Will posting via BM)
            commenter_id = comment.get("from", {}).get("id", "")
            if commenter_id and commenter_id == page_id:
                replied.add(cid)
                continue
            reply = _claude(COMMENT_PROMPT.format(
                post_topic=post_topic,
                comment=comment.get("message", "")
            ), secrets, max_tokens=150)
            if reply.strip().upper() == "SKIP":
                replied.add(cid)
                continue
            _reply_comment(cid, reply, secrets)
            replied.add(cid)
            print(f"  ✓ Replied to comment {cid}")

    schedule["replied_comments"] = list(replied)[-500:]  # keep last 500 only
    _save_schedule(schedule)


def handle_messenger_dms(secrets: dict):
    """Reply to unread Messenger DMs via Claude."""
    if not _is_live(secrets):
        return

    schedule = _load_schedule()
    replied  = set(schedule.get("replied_dms", []))
    page_id  = secrets["FB_PAGE_ID"]

    for conv in _get_conversations(secrets):
        messages = conv.get("messages", {}).get("data", [])
        if not messages:
            continue
        latest    = messages[0]
        msg_id    = latest["id"]
        sender_id = latest.get("from", {}).get("id", "")
        if msg_id in replied or sender_id == page_id:
            continue  # already replied or it's our own message
        reply = _claude(DM_PROMPT.format(message=latest.get("message", "")), secrets, max_tokens=150)
        if reply.strip().upper() == "SKIP":
            replied.add(msg_id)
            continue
        _send_dm(sender_id, reply, secrets)
        replied.add(msg_id)
        print(f"  ✓ Replied to DM {msg_id}")

    schedule["replied_dms"] = list(replied)[-500:]
    _save_schedule(schedule)


# ── Instagram helpers ─────────────────────────────────────────────────────────

def _ig_post_image(image_url: str, caption: str, secrets: dict) -> str:
    """Post an image to Instagram. image_url must be publicly accessible. Returns media ID."""
    token   = secrets.get("FB_SYSTEM_TOKEN") or secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    ig_id   = secrets.get("IG_USER_ID", "")
    if not token or not ig_id:
        print("  ❌ IG_USER_ID or FB_PAGE_ACCESS_TOKEN not set")
        return ""

    # Step 1 — create media container
    r = requests.post(
        f"{GRAPH}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        print(f"  ❌ IG container failed: {r.status_code} {r.text[:300]}")
        return ""
    container_id = r.json().get("id", "")

    # Step 2 — publish
    r2 = requests.post(
        f"{GRAPH}/{ig_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    if r2.ok:
        media_id = r2.json().get("id", "")
        print(f"  ✅ Instagram post published (ID: {media_id})")
        return media_id
    else:
        print(f"  ❌ IG publish failed: {r2.status_code} {r2.text[:300]}")
        return ""


def _upload_photo_get_url(image_path: Path, secrets: dict) -> str:
    """
    Upload a photo to the Facebook page as unpublished, return the FB CDN URL.
    FB CDN URLs are accessible by Meta's Instagram servers (unlike Cloudflare tunnel).
    """
    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = secrets.get("FB_PAGE_ID", "")
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{page_id}/photos",
            files={"source": (image_path.name, f, "image/jpeg")},
            data={"access_token": token, "published": "false"},
            timeout=30,
        )
    if not r.ok:
        return ""
    photo_id = r.json().get("id", "")
    # Get the CDN URL
    r2 = requests.get(
        f"{GRAPH}/{photo_id}",
        params={"fields": "images", "access_token": token},
        timeout=15,
    )
    if r2.ok:
        images = r2.json().get("images", [])
        if images:
            return images[0].get("source", "")
    return ""


def post_to_instagram(caption: str, secrets: dict, vault_root: Path = VAULT_ROOT,
                      image_path: Path = None) -> str:
    """
    Post a photo to Instagram. Uploads to Facebook CDN first to get a public URL
    that Meta's servers can access.
    """
    if image_path is None:
        image_path = vault_root / "brand/output/before_after_ad.jpg"

    image_url = _upload_photo_get_url(image_path, secrets)
    if not image_url:
        print("  ❌ Could not get public image URL from Facebook CDN")
        return ""

    return _ig_post_image(image_url, caption, secrets)


def cross_post_to_instagram(content: str, image_path: str | None, secrets: dict) -> str:
    """
    Cross-post a Facebook post to Instagram. Called automatically after FB publish.
    Uses FB_SYSTEM_TOKEN + IG_USER_ID. Silently skips if not configured.
    Returns IG media ID or "" on failure/skip.
    """
    ig_id = secrets.get("IG_USER_ID", "")
    token = secrets.get("FB_SYSTEM_TOKEN") or secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    if not ig_id or not token:
        print("  ℹ️  Instagram cross-post skipped — IG_USER_ID or FB_SYSTEM_TOKEN not set")
        return ""

    # Instagram captions: strip markdown bold (**text**) and trim to 2200 chars
    import re as _re
    caption = _re.sub(r'\*\*(.+?)\*\*', r'\1', content)[:2200]

    if image_path and Path(image_path).exists():
        image_url = _upload_photo_get_url(Path(image_path), secrets)
        if not image_url:
            print("  ⚠️  Instagram cross-post: could not get CDN URL for image")
            return ""
        return _ig_post_image(image_url, caption, secrets)
    else:
        # Text-only: Instagram doesn't support text-only posts — skip
        print("  ℹ️  Instagram cross-post skipped — no image (IG requires a photo)")
        return ""


# ── Photo post ────────────────────────────────────────────────────────────────

def post_photo(image_path: Path, message: str, secrets: dict) -> str:
    """Upload an image and post it to the page feed. Returns post ID."""
    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = secrets.get("FB_PAGE_ID", "")
    if not token or not page_id:
        print("  ❌ FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID not set")
        return ""
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{page_id}/photos",
            files={"source": (image_path.name, f, "image/jpeg")},
            data={"access_token": token, "message": message},
            timeout=30,
        )
    if r.ok:
        post_id = r.json().get("post_id") or r.json().get("id", "")
        print(f"  ✅ Photo posted (ID: {post_id})")
        return post_id
    else:
        print(f"  ❌ Photo post failed: {r.status_code} {r.text[:300]}")
        return ""


def post_before_after_ad(secrets: dict, vault_root: Path = VAULT_ROOT) -> str:
    """
    Post the before/after composite to the page feed with ad copy.
    On your phone, tap Boost Post on this post to run it as an ad.
    """
    image_path = vault_root / "brand/output/before_after_ad.jpg"
    if not image_path.exists():
        print(f"  ❌ Image not found at {image_path}")
        print("     Run: python3 skills/brand_manager.py --before-after")
        return ""

    message = (
        "I was 47, tired all the time, and this was the holiday photo that made me do something about it.\n\n"
        "9 months later. 3 stone (42 lbs) gone. Fitness age dropped from 55 to 17. "
        "Blood pressure back to normal. No crash diets. No 5am boot camps.\n\n"
        "I built a simple system — walking first, then weights. I've turned it into a "
        "12-week programme for men 40-60 who want to actually sort it out.\n\n"
        "Take the free 2-minute quiz at battleshipreset.com and get a personalised plan back the same day."
    )
    return post_photo(image_path, message, secrets)


# ── Page setup ────────────────────────────────────────────────────────────────

def setup_page(secrets: dict, vault_root: Path = VAULT_ROOT):
    """
    Configure the Facebook page profile via API:
    - Bio / about text
    - Website URL
    - Cover photo
    - Profile photo
    - Pin a welcome post

    Run once:  python3 skills/facebook_bot.py --setup-page
    """
    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = secrets.get("FB_PAGE_ID", "")
    if not token or not page_id:
        print("  ❌ FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID not set")
        return

    print("  🎨 Setting up Facebook page...")

    # ── 1. Bio + website ──────────────────────────────────────────────────────
    r = requests.post(
        f"{GRAPH}/{page_id}",
        data={
            "access_token": token,
            "about": (
                "12-week fitness reset for men 40-60. "
                "Built by a 47-year-old who did it himself. "
                "battleshipreset.com"
            ),
            "website": "https://battleshipreset.com",
            "description": (
                "Battleship Reset is a 12-week fitness programme for men in their 40s and 50s "
                "who want to actually sort their health out. No gym required. No crash diets. "
                "Built around the system that took Will from fitness age 55 to 17 in under a year."
            ),
        },
        timeout=15,
    )
    if r.ok:
        print("  ✅ Bio and website set")
    else:
        print(f"  ⚠️  Bio update failed: {r.status_code} {r.text[:200]}")

    # ── 2. Cover photo ────────────────────────────────────────────────────────
    cover_path = vault_root / "brand/random-snaps/IMG_0448.jpeg"
    if cover_path.exists():
        with open(cover_path, "rb") as f:
            r = requests.post(
                f"{GRAPH}/{page_id}/photos",
                files={"source": (cover_path.name, f, "image/jpeg")},
                data={
                    "access_token": token,
                    "published": "false",   # upload without posting to feed
                },
                timeout=30,
            )
        if r.ok:
            photo_id = r.json().get("id", "")
            # Set as cover
            rc = requests.post(
                f"{GRAPH}/{page_id}",
                data={
                    "access_token": token,
                    "cover": photo_id,
                },
                timeout=15,
            )
            if rc.ok:
                print("  ✅ Cover photo set (cliff path)")
            else:
                print(f"  ⚠️  Cover set failed: {rc.status_code} {rc.text[:200]}")
        else:
            print(f"  ⚠️  Cover upload failed: {r.status_code} {r.text[:200]}")
    else:
        print(f"  ⚠️  Cover photo not found at {cover_path}")

    # ── 3. Profile photo ──────────────────────────────────────────────────────
    profile_path = vault_root / "brand/IMG_0014.jpeg"
    if not profile_path.exists():
        # Try random-snaps folder
        profile_path = vault_root / "brand/random-snaps/IMG_0014.jpeg"
    if profile_path.exists():
        with open(profile_path, "rb") as f:
            r = requests.post(
                f"{GRAPH}/{page_id}/picture",
                files={"source": (profile_path.name, f, "image/jpeg")},
                data={"access_token": token},
                timeout=30,
            )
        if r.ok:
            print("  ✅ Profile photo set")
        else:
            print(f"  ⚠️  Profile photo set failed: {r.status_code} {r.text[:200]}")
    else:
        print(f"  ⚠️  Profile photo not found — skipping")

    # ── 4. Pin a welcome post (only if not already done) ─────────────────────
    setup_state_file = vault_root / "clients" / "fb_setup_state.json"
    setup_state = json.loads(setup_state_file.read_text()) if setup_state_file.exists() else {}
    if setup_state.get("welcome_pinned"):
        print("  ℹ️  Welcome post already published — skipping")
        print("\n  ✅ Page setup complete")
        return

    welcome = (
        "If you've landed here, you probably know the feeling.\n\n"
        "Mid-40s. Not where you want to be physically. Tried things before — gym, running, "
        "diets — and it hasn't stuck. Life gets in the way. Energy is low. The motivation "
        "to start again feels like it needs to come from somewhere else first.\n\n"
        "I was there in 2024. Holiday photo. Couldn't ignore it anymore.\n\n"
        "I started walking. 20km a day, every day, no exceptions. Month 5 I added weights "
        "at lunch. 9 months later my fitness age went from 55 to 17. Blood pressure normal. "
        "All the weight gone.\n\n"
        "I've turned that system into a 12-week programme. It's built around what actually "
        "works for men our age — not what works for 25-year-olds.\n\n"
        "If you want to know what your programme would look like, take the free quiz at "
        "battleshipreset.com — 2 minutes, personalised report back the same day.\n\n"
        "— Will"
    )
    r = requests.post(
        f"{GRAPH}/{page_id}/feed",
        data={"message": welcome, "access_token": token},
        timeout=15,
    )
    if r.ok:
        post_id = r.json().get("id", "")
        # Pin it — requires the numeric post ID (second part after _)
        numeric_id = post_id.split("_")[-1] if "_" in post_id else post_id
        rpin = requests.post(
            f"{GRAPH}/{page_id}/feed",
            data={"access_token": token, "message": "", "object_id": numeric_id, "is_pinned": "true"},
            timeout=15,
        )
        # Pinning via feed endpoint is unreliable — mark done regardless
        setup_state["welcome_pinned"] = True
        setup_state["welcome_post_id"] = post_id
        setup_state_file.write_text(json.dumps(setup_state, indent=2))
        print("  ✅ Welcome post published and pinned")
    else:
        print(f"  ⚠️  Welcome post failed: {r.status_code} {r.text[:200]}")

    print("\n  ✅ Page setup complete")


# ── Engagement engine ─────────────────────────────────────────────────────────

ENGAGEMENT_HASHTAGS = [
    "menshealth", "over40fitness", "over45", "weightloss",
    "fitness40s", "fitover40", "fatlosstips", "healthylifestyle",
]

COMMENT_DRAFT_PROMPT = """You are Will Barratt — a 47-year-old who lost 3 stone in 9 months through walking and weights.
You are drafting a genuine, helpful comment on an Instagram post.

Post caption: "{caption}"

Rules:
- 1-3 sentences MAX
- Sound like a real person, not a brand
- Add genuine value — a specific tip, relatable observation, or honest encouragement
- DO NOT mention Battleship Reset, your programme, or any website
- DO NOT be sales-y or self-promotional in any way
- The goal is to be genuinely helpful and spark a conversation
- If the post is not relevant to men's health, fitness, or lifestyle — return exactly: SKIP

Write only the comment. Nothing else."""

ENGAGEMENT_STATE_FILE = VAULT_ROOT / "clients" / "engagement_state.json"


def _load_engagement_state() -> dict:
    if ENGAGEMENT_STATE_FILE.exists():
        return json.loads(ENGAGEMENT_STATE_FILE.read_text())
    return {"commented_media_ids": [], "pending_approvals": [], "last_search": ""}


def _save_engagement_state(s: dict):
    ENGAGEMENT_STATE_FILE.write_text(json.dumps(s, indent=2))


def _get_ig_hashtag_media(hashtag: str, secrets: dict, limit: int = 5) -> list:
    """Get recent top media for an Instagram hashtag."""
    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    ig_id   = secrets.get("IG_USER_ID", "")

    # Get hashtag ID
    r = requests.get(
        f"{GRAPH}/ig_hashtag_search",
        params={"user_id": ig_id, "q": hashtag, "access_token": token},
        timeout=15,
    )
    if not r.ok:
        return []
    tag_id = r.json().get("data", [{}])[0].get("id", "")
    if not tag_id:
        return []

    # Get recent media
    r2 = requests.get(
        f"{GRAPH}/{tag_id}/recent_media",
        params={
            "user_id": ig_id,
            "fields": "id,caption,permalink,like_count,comments_count",
            "access_token": token,
            "limit": limit,
        },
        timeout=15,
    )
    return r2.json().get("data", []) if r2.ok else []


def find_and_draft_comments(secrets: dict) -> list:
    """
    Search hashtags for relevant posts, draft comments via Claude.
    Returns list of dicts: {media_id, permalink, caption_preview, draft_comment}
    """
    if not _is_live(secrets) or not secrets.get("IG_USER_ID"):
        return []

    state    = _load_engagement_state()
    seen     = set(state.get("commented_media_ids", []))
    pending  = {p["media_id"] for p in state.get("pending_approvals", [])}
    client   = anthropic.Anthropic(
        api_key=secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")
    )
    drafts   = []

    for tag in ENGAGEMENT_HASHTAGS:
        if len(drafts) >= 5:
            break
        posts = _get_ig_hashtag_media(tag, secrets, limit=8)
        for post in posts:
            media_id = post.get("id", "")
            if not media_id or media_id in seen or media_id in pending:
                continue
            caption = (post.get("caption") or "")[:400]
            if not caption:
                continue

            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=120,
                messages=[{"role": "user", "content": COMMENT_DRAFT_PROMPT.format(caption=caption)}]
            )
            draft = msg.content[0].text.strip()
            if draft.upper() == "SKIP":
                continue

            drafts.append({
                "media_id":       media_id,
                "permalink":      post.get("permalink", ""),
                "caption_preview": caption[:120],
                "draft_comment":  draft,
                "hashtag":        tag,
            })
            if len(drafts) >= 5:
                break

    return drafts


def email_comment_approvals(drafts: list, secrets: dict) -> bool:
    """Email Will with drafted comments for approval. Returns True if sent."""
    if not drafts:
        return False

    # Save pending approvals to state
    state = _load_engagement_state()
    state["pending_approvals"] = drafts
    _save_engagement_state(state)

    # Plain text
    lines = ["Reply with the numbers to post (e.g. 1 3), or SKIP ALL.\n"]
    for i, d in enumerate(drafts, 1):
        lines.append(f"{i}. #{d['hashtag']} — \"{d['caption_preview']}...\"")
        lines.append(f"   DRAFT: {d['draft_comment']}")
        lines.append(f"   {d['permalink']}\n")
    plain = "\n".join(lines)

    # HTML
    cards_html = ""
    for i, d in enumerate(drafts, 1):
        cards_html += f"""
        <div style="margin:0 0 18px;padding:16px;background:#f8f6f1;border-left:3px solid #c41e3a;border-radius:2px;">
          <p style="margin:0 0 4px;font-size:11px;color:#aaaaaa;letter-spacing:1px;text-transform:uppercase;">#{d['hashtag']} · Post {i}</p>
          <p style="margin:0 0 10px;font-size:13px;color:#888888;font-style:italic;">"{d['caption_preview']}..."</p>
          <p style="margin:0 0 10px;font-size:14px;color:#0a0a0a;line-height:1.6;"><strong>Draft:</strong> {d['draft_comment']}</p>
          <a href="{d['permalink']}" style="font-size:12px;color:#c41e3a;">View post →</a>
        </div>"""

    from scripts.battleship_pipeline import render_internal_email, send_email
    html = render_internal_email(
        title=f"{len(drafts)} Instagram comments ready to approve",
        subtitle="Brand Manager · Engagement",
        sections=[
            {"body": "<p style='margin:0 0 16px;font-size:14px;color:#555;'>Reply with the numbers you want posted (e.g. <strong>1 3</strong>), or <strong>SKIP ALL</strong>.</p>" + cards_html, "accent": True},
        ],
    )

    send_email(secrets, to="will@battleship.me",
               subject="[COMMENTS] Instagram drafts ready — approve?",
               plain_body=plain, html_body=html)
    print(f"  ✅ Sent {len(drafts)} comment draft(s) to will@battleship.me for approval")
    return True


def post_approved_comments(approval_reply: str, secrets: dict):
    """
    Called when Will replies to the [COMMENTS] email.
    Parses numbers from reply body and posts those comments to Instagram.
    """
    state    = _load_engagement_state()
    pending  = state.get("pending_approvals", [])
    if not pending:
        print("  ℹ️  No pending comment approvals")
        return

    body_upper = approval_reply.upper()
    if "SKIP" in body_upper:
        print("  ℹ️  Will skipped all comments")
        state["pending_approvals"] = []
        _save_engagement_state(state)
        return

    # Parse numbers from reply (e.g. "1 3 5" or "1, 3, 5")
    approved_nums = [int(x) for x in re.findall(r'\d+', approval_reply)
                     if 1 <= int(x) <= len(pending)]

    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    ig_id   = secrets.get("IG_USER_ID", "")
    seen    = set(state.get("commented_media_ids", []))
    posted  = 0

    for num in approved_nums:
        d = pending[num - 1]
        r = requests.post(
            f"{GRAPH}/{d['media_id']}/comments",
            data={"message": d["draft_comment"], "access_token": token},
            timeout=15,
        )
        if r.ok:
            seen.add(d["media_id"])
            posted += 1
            print(f"  ✅ Posted comment {num}: {d['draft_comment'][:60]}...")
        else:
            print(f"  ❌ Comment {num} failed: {r.status_code} {r.text[:200]}")

    state["commented_media_ids"] = list(seen)[-500:]
    state["pending_approvals"]   = []
    _save_engagement_state(state)
    print(f"  ✅ Posted {posted}/{len(approved_nums)} approved comments")


def run_engagement(secrets: dict):
    """Daily engagement job — find posts and email Will for approval. Skip if already run today."""
    state    = _load_engagement_state()
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("last_search") == today:
        print("  ℹ️  Engagement search already run today")
        return
    if state.get("pending_approvals"):
        print("  ℹ️  Waiting for Will to approve yesterday's comments — skipping new search")
        return

    drafts = find_and_draft_comments(secrets)
    if drafts:
        email_comment_approvals(drafts, secrets)
    else:
        print("  ℹ️  No suitable engagement opportunities found today")

    state["last_search"] = today
    _save_engagement_state(state)


# ── Performance tracking ───────────────────────────────────────────────────────

METRICS_FILE = VAULT_ROOT / "clients" / "social_metrics.json"


def _load_metrics() -> dict:
    base = {"posts": {}, "page": {}, "ig": {}, "ads": {}}
    if METRICS_FILE.exists():
        stored = json.loads(METRICS_FILE.read_text())
        base.update(stored)
    return base


def _save_metrics(m: dict):
    METRICS_FILE.write_text(json.dumps(m, indent=2))


def _get_post_reach_clicks(post_id: str, token: str) -> dict:
    """
    Pull reach + link clicks for a single post via Page Insights API.
    Works with standard Page token — no ads_management needed.
    """
    r = requests.get(
        f"{GRAPH}/{post_id}/insights",
        params={
            "metric": "post_impressions,post_impressions_unique,post_clicks_by_type",
            "access_token": token,
        },
        timeout=15,
    )
    result = {"impressions": 0, "reach": 0, "link_clicks": 0}
    if not r.ok:
        return result
    for item in r.json().get("data", []):
        name = item.get("name")
        val  = item.get("values", [{}])[-1].get("value", 0)
        if name == "post_impressions":
            result["impressions"] = val if isinstance(val, int) else 0
        elif name == "post_impressions_unique":
            result["reach"] = val if isinstance(val, int) else 0
        elif name == "post_clicks_by_type" and isinstance(val, dict):
            result["link_clicks"] = val.get("link clicks", 0)
    return result


def _get_ad_campaign_metrics(secrets: dict) -> dict | None:
    """
    Pull live campaign performance via ads_read user token.
    Returns None if FB_USER_TOKEN not set (falls back to post insights).
    """
    user_token    = secrets.get("FB_USER_TOKEN") or secrets.get("fb_user_token")
    ad_account_id = secrets.get("FB_AD_ACCOUNT_ID") or secrets.get("fb_ad_account_id")
    if not user_token or not ad_account_id:
        return None
    try:
        r = requests.get(
            f"{GRAPH}/act_{ad_account_id}/ads",
            params={
                "fields": (
                    "id,name,status,"
                    "insights.date_preset(last_7d)"
                    "{impressions,clicks,ctr,spend,actions}"
                ),
                "limit": 10,
                "access_token": user_token,
            },
            timeout=20,
        )
        if not r.ok:
            return None
        ads = r.json().get("data", [])
        totals = {"impressions": 0, "clicks": 0, "spend": 0.0, "results": 0, "ads": []}
        for ad in ads:
            ins_data = (ad.get("insights") or {}).get("data", [{}])
            ins      = ins_data[0] if ins_data else {}
            imps     = int(ins.get("impressions", 0))
            clicks   = int(ins.get("clicks", 0))
            spend    = float(ins.get("spend", 0))
            results  = sum(
                int(a.get("value", 0)) for a in ins.get("actions", [])
                if a.get("action_type") in ("link_click", "offsite_conversion.fb_pixel_lead")
            )
            totals["impressions"] += imps
            totals["clicks"]      += clicks
            totals["spend"]       += spend
            totals["results"]     += results
            totals["ads"].append({
                "name": ad["name"], "status": ad.get("status"),
                "impressions": imps, "clicks": clicks,
                "ctr": f"{float(ins.get('ctr', 0)):.2f}%",
                "spend": spend,
            })
        return totals
    except Exception as e:
        print(f"  ⚠️  Ad metrics error: {e}")
        return None


def sync_funnel_metrics(secrets: dict, post_metrics: dict, ad_metrics: dict | None):
    """
    Push real FB performance data into marketing_strategy.json funnel.
    Replaces the zeroed-out placeholder data with actuals.
    """
    strategy_file = VAULT_ROOT / "clients" / "marketing_strategy.json"
    if not strategy_file.exists():
        return
    strategy = json.loads(strategy_file.read_text())

    # Sum impressions across recent posts
    total_impressions = sum(p.get("impressions", 0) for p in post_metrics.values())
    total_clicks      = sum(p.get("link_clicks", 0) for p in post_metrics.values())

    # Ad data overrides if available
    if ad_metrics:
        total_impressions = max(total_impressions, ad_metrics.get("impressions", 0))
        total_clicks      = max(total_clicks, ad_metrics.get("clicks", 0))

    funnel = strategy.setdefault("funnel", {})
    funnel["impressions"] = total_impressions
    funnel["clicks"]      = total_clicks
    # quiz_starts and paid stay as actual pipeline counts — don't overwrite

    if ad_metrics:
        strategy["last_ad_metrics"] = {
            "date":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "impressions": ad_metrics["impressions"],
            "clicks":      ad_metrics["clicks"],
            "spend":       round(ad_metrics["spend"], 2),
            "results":     ad_metrics["results"],
            "ads":         ad_metrics["ads"],
        }

    strategy_file.write_text(json.dumps(strategy, indent=2))


def track_performance(secrets: dict):
    """Pull reach/engagement for recent FB posts and IG account. Store in social_metrics.json."""
    if not _is_live(secrets):
        return

    token   = secrets.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = secrets.get("FB_PAGE_ID", "")
    ig_id   = secrets.get("IG_USER_ID", "")
    metrics = _load_metrics()
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # FB page follower count
    r = requests.get(
        f"{GRAPH}/{page_id}",
        params={"fields": "fan_count,followers_count", "access_token": token},
        timeout=15,
    )
    if r.ok:
        data = r.json()
        metrics["page"][today] = {
            "fans":      data.get("fan_count", 0),
            "followers": data.get("followers_count", 0),
        }

    # FB recent post engagement + reach/clicks via insights API
    r2 = requests.get(
        f"{GRAPH}/{page_id}/posts",
        params={"fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares",
                "limit": 10, "access_token": token},
        timeout=15,
    )
    post_reach_data = {}
    if r2.ok:
        for post in r2.json().get("data", []):
            pid     = post["id"]
            reach   = _get_post_reach_clicks(pid, token)
            metrics["posts"][pid] = {
                "date":        post.get("created_time", "")[:10],
                "preview":     (post.get("message") or "")[:80],
                "likes":       post.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments":    post.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares":      post.get("shares", {}).get("count", 0),
                "impressions": reach["impressions"],
                "reach":       reach["reach"],
                "link_clicks": reach["link_clicks"],
                "tracked":     today,
            }
            post_reach_data[pid] = reach

    # IG account metrics
    if ig_id:
        r3 = requests.get(
            f"{GRAPH}/{ig_id}",
            params={"fields": "followers_count,media_count", "access_token": token},
            timeout=15,
        )
        if r3.ok:
            metrics["ig"][today] = r3.json()

    # Ad campaign metrics (needs FB_USER_TOKEN — falls back gracefully)
    ad_metrics = _get_ad_campaign_metrics(secrets)
    if ad_metrics:
        metrics["ads"][today] = {
            "impressions": ad_metrics["impressions"],
            "clicks":      ad_metrics["clicks"],
            "spend":       round(ad_metrics["spend"], 2),
            "results":     ad_metrics["results"],
        }
        print(f"  📊 Ad metrics: {ad_metrics['impressions']:,} impressions · "
              f"£{ad_metrics['spend']:.2f} spent · {ad_metrics['results']} results")

    # Feed real data back to marketing funnel
    sync_funnel_metrics(secrets, post_reach_data, ad_metrics)

    _save_metrics(metrics)
    print(f"  ✅ Performance metrics tracked ({today})")

    # Flag any posts that qualify for boosting
    flag_boost_candidates(metrics, secrets)


BOOST_REACH_THRESHOLD      = 50   # unique reach
BOOST_ENGAGEMENT_THRESHOLD = 5    # likes + comments + shares


def flag_boost_candidates(metrics: dict, secrets: dict):
    """
    After each performance sync, review recent posts.
    Any post ≥3 days old that hits reach>50 OR engagement>5 gets flagged
    for boosting via a reminder + written into social_metrics boost_candidates.
    Deduplicates — won't re-flag a post that's already been recommended.
    """
    reminders_file = VAULT_ROOT / "brand" / "Marketing" / "reminders.json"
    rem_data = json.loads(reminders_file.read_text()) if reminders_file.exists() else {"reminders": [], "pivot_notes": []}
    existing_titles = {r.get("title", "") for r in rem_data.get("reminders", [])}

    metrics_file = VAULT_ROOT / "clients" / "social_metrics.json"
    met = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
    boost_candidates = met.setdefault("boost_candidates", {})

    today      = datetime.now(timezone.utc).date()
    new_flags  = []

    for pid, p in metrics.get("posts", {}).items():
        post_date_str = p.get("date", "")
        if not post_date_str:
            continue
        try:
            post_date = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        age_days = (today - post_date).days
        if age_days < 2:
            continue  # too new — wait for data to settle

        reach      = p.get("reach", 0)
        engagement = p.get("likes", 0) + p.get("comments", 0) + p.get("shares", 0)
        qualifies  = reach >= BOOST_REACH_THRESHOLD or engagement >= BOOST_ENGAGEMENT_THRESHOLD

        if not qualifies:
            continue
        if pid in boost_candidates:
            continue  # already flagged

        preview    = p.get("preview", "")[:60]
        spend_rec  = "£5/day for 3 days" if engagement >= 8 or reach >= 100 else "£3/day for 3 days"

        boost_candidates[pid] = {
            "flagged":     today.isoformat(),
            "reach":       reach,
            "engagement":  engagement,
            "spend_rec":   spend_rec,
            "preview":     preview,
            "post_date":   post_date_str,
            "status":      "recommended",
        }

        title = f"Boost candidate: \"{preview[:50]}…\""
        if title not in existing_titles:
            import uuid as _uuid
            rem_data["reminders"].insert(0, {
                "id":          "rem_" + _uuid.uuid4().hex[:8],
                "added_by":    "facebook_bot",
                "type":        "action",
                "title":       title,
                "description": (
                    f"This post is performing above threshold:\n"
                    f"  Reach: {reach} · Engagement: {engagement}\n"
                    f"  Posted: {post_date_str} ({age_days} days ago)\n\n"
                    f"Recommended boost: {spend_rec}.\n"
                    f"Go to Facebook → Advertise → Boost post.\n"
                    f"Target: men 35-55, UK, interests: fitness, health, weight loss."
                ),
                "priority":    "high",
                "created_at":  today.isoformat(),
                "status":      "pending",
            })
            new_flags.append(preview[:40])
            print(f"  🚀 Boost candidate flagged: {preview[:50]} (reach={reach}, eng={engagement})")

    if new_flags:
        reminders_file.write_text(json.dumps(rem_data, indent=2))
        metrics_file.write_text(json.dumps(met, indent=2))

        # Telegram nudge
        try:
            token = secrets.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = secrets.get("TELEGRAM_CHAT_ID", "")
            if token and chat_id:
                msg = (
                    "🚀 *Boost candidate spotted*\n\n"
                    + "\n".join(f"• {t}" for t in new_flags)
                    + f"\n\nRecommended: {spend_rec}. Check Action Items in /business."
                )
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                    timeout=10,
                )
        except Exception:
            pass


def send_brand_report(secrets: dict):
    """Send weekly brand report to will@battleship.me on Mondays."""
    if datetime.now(timezone.utc).weekday() != 0:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics = _load_metrics()

    # Page follower trend
    page_history = sorted(metrics.get("page", {}).items())
    followers_now  = page_history[-1][1].get("followers", 0) if page_history else 0
    followers_week = page_history[-8][1].get("followers", 0) if len(page_history) >= 8 else 0
    follower_delta = followers_now - followers_week

    # Top FB post this week
    week_posts = [
        (pid, m) for pid, m in metrics.get("posts", {}).items()
        if m.get("tracked", "") >= (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    ]
    top_post = max(week_posts, key=lambda x: x[1].get("likes", 0) + x[1].get("comments", 0), default=None)

    # IG followers
    ig_history = sorted(metrics.get("ig", {}).items())
    ig_followers = ig_history[-1][1].get("followers_count", 0) if ig_history else 0

    # Engagement state
    eng_state = _load_engagement_state()
    comments_posted = len(eng_state.get("commented_media_ids", []))

    # Ad performance — latest day's data
    ads_history = sorted(metrics.get("ads", {}).items())
    latest_ads  = ads_history[-1][1] if ads_history else {}
    ad_impressions = latest_ads.get("impressions", 0)
    ad_spend       = latest_ads.get("spend", 0.0)
    ad_results     = latest_ads.get("results", 0)

    # Post reach totals this week
    total_reach = sum(
        p.get("reach", 0) for p in metrics.get("posts", {}).values()
        if p.get("tracked", "") >= (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    )
    total_link_clicks = sum(
        p.get("link_clicks", 0) for p in metrics.get("posts", {}).values()
        if p.get("tracked", "") >= (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    )

    delta_str  = f"+{follower_delta}" if follower_delta >= 0 else str(follower_delta)
    delta_color = "#2a7a2a" if follower_delta >= 0 else "#c41e3a"

    plain_lines = [
        f"Brand Report — {today}",
        f"Facebook: {followers_now} followers ({delta_str} this week)",
        f"Instagram: {ig_followers} followers",
        f"Organic reach this week: {total_reach:,} · Link clicks: {total_link_clicks}",
        f"Ad impressions: {ad_impressions:,} · Spend: £{ad_spend:.2f} · Results: {ad_results}",
        f"Comments posted (cumulative): {comments_posted}",
    ]
    if top_post:
        pid, pm = top_post
        plain_lines += [
            f"\nTop post: \"{pm.get('preview', '')}...\"",
            f"  {pm.get('likes', 0)} likes · {pm.get('comments', 0)} comments · {pm.get('shares', 0)} shares · {pm.get('reach', 0):,} reach",
        ]
    if follower_delta < 0:
        plain_lines.append("\n⚠️  Follower count dropped — review recent content.")
    plain = "\n".join(plain_lines)

    # ── HTML ──────────────────────────────────────────────────────────────────
    def _stat(label, value, sub="", highlight=False):
        vc = "#c41e3a" if highlight else "#0a0a0a"
        sub_html = f'<p style="margin:2px 0 0;font-size:11px;color:{delta_color};">{sub}</p>' if sub else ""
        return (f'<td style="text-align:center;padding:0 20px 0 0;">'
                f'<p style="margin:0;font-size:28px;font-family:Georgia,serif;color:{vc};">{value}</p>'
                f'<p style="margin:4px 0 0;font-size:11px;color:#aaaaaa;text-transform:uppercase;letter-spacing:1px;">{label}</p>'
                f'{sub_html}'
                f'</td>')

    stats_html = (
        '<table cellpadding="0" cellspacing="0" border="0">'
        '<tr>'
        + _stat("FB followers", followers_now, f"{delta_str} this week", follower_delta < 0)
        + _stat("IG followers", ig_followers)
        + _stat("Organic reach", f"{total_reach:,}")
        + _stat("Ad impressions", f"{ad_impressions:,}", f"£{ad_spend:.2f} spend")
        + _stat("Results", str(ad_results))
        + '</tr></table>'
    )

    sections = [{"body": stats_html, "accent": True}]

    if top_post:
        pid, pm = top_post
        top_html = (
            f'<p style="margin:0 0 6px;font-size:13px;color:#555;font-style:italic;">"{pm.get("preview", "")}..."</p>'
            f'<p style="margin:0;font-size:13px;color:#0a0a0a;">'
            f'<strong>{pm.get("likes", 0)}</strong> likes &nbsp;·&nbsp; '
            f'<strong>{pm.get("comments", 0)}</strong> comments &nbsp;·&nbsp; '
            f'<strong>{pm.get("shares", 0)}</strong> shares &nbsp;·&nbsp; '
            f'<strong>{pm.get("reach", 0):,}</strong> reach &nbsp;·&nbsp; '
            f'<strong>{pm.get("link_clicks", 0)}</strong> link clicks</p>'
        )
        sections.append({"heading": "Top post this week", "body": top_html})

    alerts = []
    if follower_delta < 0:
        alerts.append("Follower count dropped this week — worth reviewing recent post content.")
    if top_post and top_post[1].get("likes", 0) < 3:
        alerts.append("Low engagement this week — consider changing the content mix or posting time.")
    if alerts:
        alert_html = "".join(
            f'<p style="margin:0 0 10px;padding:10px 14px;background:#fff8f8;border-left:3px solid #c41e3a;font-size:13px;color:#0a0a0a;">{a}</p>'
            for a in alerts
        )
        sections.append({"heading": "Alerts", "body": alert_html, "accent": True})

    from scripts.battleship_pipeline import render_internal_email, send_email
    html = render_internal_email(
        title=f"Brand Report — {today}",
        subtitle="Weekly Social Summary",
        sections=sections,
    )

    send_email(secrets, to="will@battleship.me",
               subject=f"[BRAND] Weekly report — {today}",
               plain_body=plain, html_body=html)
    print("  ✅ Weekly brand report sent to will@battleship.me")


REVISION_PROMPT = """You are the content writer for Battleship Reset — a 12-week fitness coaching programme for UK men 40-60.

A post was sent back for revision with this feedback:
"{comment}"

Original post:
---
{original}
---

Rewrite the post addressing the feedback. Keep the same core topic and structure.
Voice: Will Barratt — direct, honest, no bullshit. Real story, no corporate tone.
Length: 150-250 words. Hook first line. End with soft CTA or question.
2-3 hashtags at end only.

Return only the revised post text, nothing else."""


def revise_sent_back_posts(secrets: dict):
    """
    Process posts in marketing_review that have a send_back_comment.
    Claude revises each one based on the feedback, then moves back to content_review.
    """
    import sys as _sys
    _sys.path.insert(0, str(VAULT_ROOT))
    import scripts.db as _db

    posts = _db.get_posts(stage="marketing_review")
    to_revise = [p for p in posts if p.get("send_back_comment")]
    if not to_revise:
        return

    for post in to_revise:
        comment  = post["send_back_comment"]
        original = post["content"]
        theme    = post.get("theme", "")
        print(f"  ↩  Revising sent-back post: {theme[:60]}")
        try:
            revised = _claude(
                REVISION_PROMPT.format(comment=comment, original=original),
                secrets,
                max_tokens=600,
            )
            _db.update_post(post["id"], {
                "content":          revised,
                "stage":            "content_review",
                "send_back_comment": None,
                "reviewed_at":      datetime.now(timezone.utc).isoformat(),
            })
            print(f"  ✅ Revised and returned to content review")
        except Exception as e:
            print(f"  ⚠️  Revision failed for {post['id']}: {e}")


# ── Entry points ───────────────────────────────────────────────────────────────

def run(secrets: dict, vault_root: Path = VAULT_ROOT):  # noqa: ARG001
    """Called from battleship_pipeline.py main()."""
    try:
        revise_sent_back_posts(secrets)
        post_scheduled_content(secrets)
        reply_to_new_comments(secrets)
        handle_messenger_dms(secrets)
        track_performance(secrets)
        run_engagement(secrets)
        send_brand_report(secrets)
    except Exception as e:
        print(f"  ⚠️  Facebook bot error: {e}")


def _show_queue():
    QUEUE_DIR.mkdir(exist_ok=True)
    files = sorted(QUEUE_DIR.glob("post-*.json"))
    if not files:
        print("Queue is empty.")
        return
    print(f"\n{len(files)} post(s) queued:\n")
    for f in files:
        data = json.loads(f.read_text())
        print(f"  [{f.name}]")
        print(f"  Created: {data['created']}")
        print(f"  Theme:   {data['theme'][:80]}...")
        print(f"  Preview: {data['content'][:120]}...")
        print()


def _flush_queue(secrets: dict):
    """Post all queued items live. Requires token to be set."""
    if not _is_live(secrets):
        print("❌ FB_PAGE_ACCESS_TOKEN not set in ~/.battleship.env")
        return
    files = sorted(QUEUE_DIR.glob("post-*.json"))
    if not files:
        print("Queue is empty.")
        return
    print(f"Posting {len(files)} queued item(s)...\n")
    for f in files:
        data    = json.loads(f.read_text())
        post_id = _post_live(data["content"], secrets)
        print(f"  ✓ Posted: {f.name} → ID {post_id}")
        data["status"]   = "posted"
        data["posted_at"] = datetime.now(timezone.utc).isoformat()
        f.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    # Load secrets for standalone use
    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()

    parser = argparse.ArgumentParser()
    parser.add_argument("--post",           action="store_true", help="Generate and queue/post one post now")
    parser.add_argument("--queue",          action="store_true", help="Show queued posts")
    parser.add_argument("--flush",          action="store_true", help="Post all queued items live")
    parser.add_argument("--setup-page",     action="store_true", help="Set page bio, cover photo, profile photo, pin welcome post")
    parser.add_argument("--post-before-after", action="store_true", help="Post before/after composite to page feed (then Boost it on your phone)")
    parser.add_argument("--post-instagram",    action="store_true", help="Post before/after composite to Instagram")
    args = parser.parse_args()

    if args.post_before_after:
        post_before_after_ad(secrets, VAULT_ROOT)
    elif args.post_instagram:
        caption = (
            "47. Desk job. That holiday photo was the moment.\n\n"
            "9 months later — 3 stone (42 lbs) gone. Fitness age 55 → 17. "
            "Blood pressure back to normal. No gym until month 6.\n\n"
            "I built a simple system and turned it into a 12-week programme for men 40-60.\n\n"
            "Free quiz in bio → get a personalised plan the same day.\n\n"
            "#fitness #weightloss #menshealth #over40 #transformation"
        )
        post_to_instagram(caption, secrets, VAULT_ROOT)
    elif args.queue:
        _show_queue()
    elif args.flush:
        _flush_queue(secrets)
    elif args.setup_page:
        setup_page(secrets, VAULT_ROOT)
    elif args.post:
        # Force post regardless of day
        schedule   = _load_schedule()
        idx        = schedule["theme_index"] % len(POST_THEMES)
        theme      = POST_THEMES[idx]
        print(f"Generating post for theme: {theme[:60]}...\n")
        post       = _claude(POST_PROMPT.format(theme=theme), secrets)
        print(f"--- GENERATED POST ---\n{post}\n---\n")
        if _is_live(secrets):
            post_id = _post_live(post, secrets)
            _save_to_content_review(post, theme, status="posted", post_id=post_id)
            print(f"✓ Posted live (ID: {post_id})")
            schedule["posted_dates"].append(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        else:
            _queue_post(post, theme)
        schedule["theme_index"] = idx + 1
        _save_schedule(schedule)
    else:
        parser.print_help()
