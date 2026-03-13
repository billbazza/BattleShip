#!/usr/bin/env python3
"""
Battleship Autonomous Pipeline
===============================
Full client journey: Intake → Diagnosis → Enrolment → Plan → Check-ins → Education Drips

HOW IT WORKS:
  1. Polls Typeform for new intake submissions
  2. Claude generates a personalised Diagnosis Report
  3. Sends Email 1 (instant auto-reply) + Email 2 (diagnosis + CTA)
  4. Polls Stripe for successful payments → enrols client automatically
  5. Claude generates personalised 12-week plan
  6. Sends onboarding email + plan delivery email
  7. Every Sunday: sends weekly check-in request (links to Google Form)
  8. Processes Google Sheet check-in responses → Claude generates coach response + sends it
  9. Education drips sent at Weeks 2, 3, 4 automatically

RUN AS CRON (every 2 hours):
  0 */2 * * * /usr/bin/python3 /Users/will/Obsidian-Vaults/BattleShip-Vault/scripts/battleship_pipeline.py >> /Users/will/Obsidian-Vaults/BattleShip-Vault/logs/pipeline.log 2>&1

1PASSWORD SECRETS (create these in 1Password before first run):
  op://Private/Typeform/credential      — Typeform API key
  op://Private/Anthropic/credential    — Claude API key (console.anthropic.com)
  op://Private/SMTP/host               — e.g. smtp.mail.me.com
  op://Private/SMTP/user               — your sending email address
  op://Private/SMTP/password           — app-specific password (NOT your Apple ID password)
  op://Private/Stripe/api-key          — Stripe secret key sk_live_... (optional)
  op://Private/GoogleSheets/sheet-id   — ID from the check-in Sheet URL (optional)
  op://Private/GoogleSheets/creds-path — path to service account JSON e.g. ~/.battleship-gsheets.json (optional)
"""

import subprocess, requests, json, smtplib, sys, os, re, imaplib, email
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("❌ anthropic package not installed. Run: pip3 install anthropic")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

VAULT_ROOT   = Path("/Users/will/Obsidian-Vaults/BattleShip-Vault")
CLIENTS_DIR  = VAULT_ROOT / "clients"
LOGS_DIR     = VAULT_ROOT / "logs"
STATE_FILE   = CLIENTS_DIR / "state.json"

INTAKE_FORM_ID    = "wbD9VYUa"
CHECKIN_FORM_ID   = ""           # Legacy Typeform check-in — replaced by Google Sheets
CHECKIN_GFORM_URL = "https://forms.gle/TkBjLWd5aotBGTDAA"

COACH_NAME  = "William George BattleShip Barratt"
SMTP_PORT   = 587  # STARTTLS; use 465 for SSL

REQUIRED_SECRETS = {
    "typeform":  "op://Private/Typeform/credential",
    "anthropic": "op://Private/Anthropic/credential",
    "smtp_host": "op://Private/SMTP/host",
    "smtp_user": "op://Private/SMTP/username",
    "smtp_pass": "op://Private/SMTP/password",
}
OPTIONAL_SECRETS = {
    "stripe":       "op://Private/Stripe/api-key",
    "notion":       "op://Private/Notion/api-key",
    "gsheets_id":   "op://Private/GoogleSheets/sheet-id",
    "gsheets_creds":"op://Private/GoogleSheets/creds-path",
    "imap_host":    "op://Private/IMAP/host",
    "imap_user":    "op://Private/IMAP/username",
    "imap_pass":    "op://Private/IMAP/password",
}

# Inbound email routing
COACH_EMAIL   = "coach@battleship.me"
SUPPORT_EMAIL = "support@battleship.me"
WILL_EMAIL    = "will@battleship.me"
REPLY_TO      = COACH_EMAIL   # default reply-to on all outgoing client emails

# Notion: ID of the "Battleship Clients" parent page
# Copy the page URL, take the ID after the last / and before any ?
NOTION_PARENT_PAGE_ID = ""  # e.g. "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"

# Education drip schedule — 2 lessons/week max
# Format: week_number → list of (state_key, subject, content_file)
# Week 12 is handled separately by send_week12_close() — not in this dict
EDUCATION_DRIPS = {
    # Week 1: Sleep bonus — sent right after onboarding, before any training starts
    1:  [("edu_sleep",       "Week 1 bonus: sleep — the easiest win in the programme",    "education-lessons/sleep/sleep-for-fat-loss.md")],
    # Week 2: Zone 2 science + nutrition foundation
    2:  [("edu_zone2",       "Why slow walking beats hard running — the science",         "education-lessons/exercises/zone2-walking.md"),
         ("edu_nutrition_1", "The key to success (it's not what you think)",              "education-lessons/nutrition/key-to-success.md")],
    # Week 3: 80/20 + balanced plate
    3:  [("edu_8020",        "The 80/20 rule of nutrition",                               "education-lessons/nutrition/80-20-rule.md"),
         ("edu_plate",       "How to build a balanced plate — no tracking required",      "education-lessons/nutrition/balanced-plate.md")],
    # Week 4: Fat loss fundamentals
    4:  [("edu_fatloss_1",   "How to actually lose fat: getting started",                 "education-lessons/fat-loss/getting-started.md"),
         ("edu_fatloss_2",   "How to actually lose fat: awareness",                       "education-lessons/fat-loss/awareness.md")],
    # Week 5: Closing the gap + consistency
    5:  [("edu_fatloss_3",   "How to actually lose fat: closing the gap",                 "education-lessons/fat-loss/closing-the-gap.md"),
         ("edu_fatloss_4",   "How to actually lose fat: hacking consistency",             "education-lessons/fat-loss/hacking-consistency.md")],
    # Week 6: Whole foods + training begins
    6:  [("edu_wholefoods",  "Your whole foods reference card",                           "education-lessons/nutrition/whole-foods-reference.md"),
         ("edu_training_1",  "Time to add weights — here's what your training looks like","education-lessons/training/workout-overview.md")],
    # Week 7: Gym basics
    7:  [("edu_gym_terms",   "Gym terminology decoded — sets, reps, RPE explained",       "education-lessons/training/gym-terminology.md"),
         ("edu_gymtim",      "Gymtimidation — and why it ends at session three",           "education-lessons/training/gymtimidation.md")],
    # Week 8: Execution
    8:  [("edu_warmup",      "The warm-up you should never skip (especially over 40)",    "education-lessons/training/warm-ups.md"),
         ("edu_prep",        "How to prepare for a session — before, during, after",      "education-lessons/training/workout-prep.md")],
    # Week 9: Load and fat loss science
    9:  [("edu_weight",      "How much weight should you lift? The honest answer",        "education-lessons/training/how-much-weight.md"),
         ("edu_fatloss_t",   "Why lifting beats cardio for body composition",             "education-lessons/training/training-for-fat-loss.md")],
    # Week 10: The method
    10: [("edu_bws",         "The Battleship training method — and why boring works",     "education-lessons/training/bws-method.md")],
    # Week 11: Arms + what comes next
    11: [("edu_arms",        "What about arms? Why the basics come first",                "education-lessons/training/arms-and-basics.md")],
}


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"next_client_number": 1, "processed_intake_ids": [],
            "processed_checkin_ids": [], "clients": {}}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

def next_account_number(state: dict) -> str:
    """Generate next sequential account number e.g. BSR-2026-0001."""
    year = datetime.now().year
    n    = state.get("next_client_number", 1)
    state["next_client_number"] = n + 1
    return f"BSR-{year}-{n:04d}"

def find_client(query: str, state: dict) -> tuple[str, dict] | tuple[None, None]:
    """Find a client by account number, name, or email. Returns (account_no, record)."""
    q = query.strip().lower()
    for acct, cs in state["clients"].items():
        if (acct.lower() == q or
                cs.get("name", "").lower() == q or
                cs.get("email", "").lower() == q or
                q in cs.get("name", "").lower()):
            return acct, cs
    return None, None


# ── Secrets ───────────────────────────────────────────────────────────────────
# Reads from ~/.battleship.env (preferred — works unattended in cron).
# Falls back to 1Password CLI if a value is missing (requires biometric auth).

ENV_FILE = Path.home() / ".battleship.env"

def _read_env_file() -> dict:
    """Parse ~/.battleship.env into a dict."""
    if not ENV_FILE.exists():
        return {}
    result = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result

def op_read(path: str, required: bool = True) -> str | None:
    try:
        return subprocess.check_output(
            ["op", "read", path], stderr=subprocess.STDOUT
        ).decode().strip()
    except subprocess.CalledProcessError as e:
        if required:
            print(f"❌ 1Password read failed for {path}:\n   {e.output.decode().strip()}")
            sys.exit(1)
        return None

def load_secrets() -> dict:
    env = _read_env_file()

    key_map = {
        "typeform":      "TYPEFORM_KEY",
        "anthropic":     "ANTHROPIC_KEY",
        "smtp_host":     "SMTP_HOST",
        "smtp_user":     "SMTP_USER",
        "smtp_pass":     "SMTP_PASS",
        "stripe":        "STRIPE_KEY",
        "gsheets_id":    "GSHEETS_ID",
        "gsheets_creds": "GSHEETS_CREDS",
        "imap_host":     "IMAP_HOST",
        "imap_user":     "IMAP_USER",
        "imap_pass":     "IMAP_PASS",
    }
    op_map = {**REQUIRED_SECRETS, **OPTIONAL_SECRETS}

    secrets = {}
    for key, env_var in key_map.items():
        val = env.get(env_var, "").strip()
        if val:
            secrets[key] = val
        elif key in REQUIRED_SECRETS:
            # Fall back to 1Password for required secrets
            secrets[key] = op_read(op_map[key], required=True)
        else:
            secrets[key] = None

    # Expand ~ in paths
    if secrets.get("gsheets_creds"):
        secrets["gsheets_creds"] = str(Path(secrets["gsheets_creds"]).expanduser())

    return secrets


# ── Tally ─────────────────────────────────────────────────────────────────────

TALLY_QUEUE = CLIENTS_DIR / "tally-queue"

def tally_parse_submission(payload: dict) -> dict:
    """Parse a Tally webhook payload into the same format as tf_parse_response."""
    data   = payload.get("data", {})
    fields = data.get("fields", [])

    qa = {}
    for field in fields:
        label = field.get("label", "").strip()
        ftype = field.get("type", "")
        value = field.get("value")
        if value is None or value == "":
            continue
        if isinstance(value, list):
            # Multiple choice — value is list of option labels
            text = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            text = value.get("label", str(value))
        else:
            text = str(value)
        if label:
            qa[label] = text

    name  = next((v for k, v in qa.items() if "first name" in k.lower()), "Client")
    email = next((v for k, v in qa.items() if "send your" in k.lower() or
                  ("email" in k.lower() and "@" in v)), "")
    raw_text = "\n".join(f"**{q}**\n{a}" for q, a in qa.items() if a)

    return {
        "response_id":  data.get("responseId", "tally-" + data.get("submittedAt", "")),
        "submitted_at": data.get("submittedAt", ""),
        "name":         name,
        "email":        email,
        "qa":           qa,
        "raw_text":     raw_text,
    }


def process_tally_queue(secrets: dict, state: dict):
    """Process any queued Tally submissions from the webhook."""
    TALLY_QUEUE.mkdir(parents=True, exist_ok=True)
    files = sorted(TALLY_QUEUE.glob("submission-*.json"))
    if not files:
        print("  (no queued Tally submissions)")
        return

    for f in files:
        try:
            payload = json.loads(f.read_text())
            parsed  = tally_parse_submission(payload)
            if parsed["response_id"] in state["processed_intake_ids"]:
                print(f"  ↩️  Already processed: {f.name}")
                f.unlink()
                continue
            print(f"  📥 Processing Tally submission: {parsed['name']} ({parsed['email']})")
            process_new_intake(parsed, secrets, state)
            f.unlink()
        except Exception as e:
            print(f"  ❌ Error processing {f.name}: {e}")


# ── Typeform ──────────────────────────────────────────────────────────────────

def tf_get_field_map(api_key: str, form_id: str) -> dict:
    r = requests.get(
        f"https://api.typeform.com/forms/{form_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    r.raise_for_status()
    return {f["id"]: f["title"] for f in r.json().get("fields", [])}

def tf_get_responses(api_key: str, form_id: str, count: int = 50) -> list:
    r = requests.get(
        f"https://api.typeform.com/forms/{form_id}/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"page_size": count, "sort": "submitted_at,desc"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("items", [])

def tf_extract_answer(answer: dict) -> str:
    t = answer.get("type")
    if t in ("text", "long_text"): return answer.get("text", "")
    if t == "email":    return answer.get("email", "")
    if t == "number":   return str(answer.get("number", ""))
    if t == "boolean":  return "Yes" if answer.get("boolean") else "No"
    if t == "choice":   return answer.get("choice", {}).get("label", "")
    if t == "choices":
        labels = answer.get("choices", {}).get("labels", [])
        other  = answer.get("choices", {}).get("other", "")
        if other: labels.append(f"Other: {other}")
        return ", ".join(labels)
    return str(answer)

def tf_parse_response(item: dict, field_map: dict) -> dict:
    answers = {a["field"]["id"]: tf_extract_answer(a) for a in item.get("answers", [])}
    qa = {field_map[fid]: val for fid, val in answers.items() if fid in field_map}

    name  = next((v for k, v in qa.items() if "first name" in k.lower()), "Client")
    email = next(
        (v for k, v in qa.items() if "send your" in k.lower() or "email" in k.lower()),
        ""
    )
    raw_text = "\n".join(f"**{q}**\n{a}" for q, a in qa.items() if a and a != "[not answered]")

    return {
        "response_id":  item["response_id"],
        "submitted_at": item["submitted_at"],
        "name":         name,
        "email":        email,
        "qa":           qa,
        "raw_text":     raw_text,
    }


# ── Claude API ────────────────────────────────────────────────────────────────

def call_claude(api_key: str, prompt: str, max_tokens: int = 1500) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


DIAGNOSIS_PROMPT = """\
You are the Intake Agent for Battleship – Midlife Fitness Reset.
A British fitness coaching programme for men 40–60 who've tried and failed before.
Tone: warm, direct, non-shaming. Like a knowledgeable mate who tells it straight.

Read this client's intake form and write their Battleship Diagnosis Report.

CLIENT INTAKE:
{intake_text}

Output EXACTLY this structure (no preamble, no sign-off):

# Battleship Diagnosis Report — {name}

## Why It's Failed Before
[2–3 paragraphs. Focus entirely on system mismatch — wrong tools for their life, not personal weakness.
Reference their specific injuries, schedule, and past attempts by name (gym, HIIT, running, etc).
This should feel like someone finally understood them.]

## What Will Be Different This Time
[2 paragraphs. Explain the Battleship approach specific to this client: Zone 2 walking foundation,
progressive strength modified for their injuries, protein tracking, honest tracking.
End with one confident sentence about why this time is different.]

## Your Week 1 Starting Point
[3 bullet points only — the 3 things they do in Week 1. Ultra-simple. Based on their equipment,
schedule, and injury flags. Do not overwhelm.]

## Why This Is Worth It
[2–3 sentences only. Reframe the investment using something SPECIFIC from their intake answers.
Use one of these angles based on what fits them best:
- Multiple failed attempts: calculate what they've already spent (gym memberships, boot camps, running gear) and note this costs less
- Non-drinker: "You've already made one of the hardest lifestyle choices. This is next."
- BP/cholesterol flagged by GP: "The cost of doing nothing — medication, lost years, appointments — is harder to quantify."
- Desk job + poor sleep: connect investing in health now to performance and energy at work
Frame it as investing in yourself, not spending money. Warm and honest. Never pushy. No price mentioned.]

---
AGENT_TAGS_JSON
{{"main_goal": "...", "constraints": [...], "risk_flags": {{"sleep": "...", "stress": "...", "injuries": [...], "bp": "..."}}, "equipment": [...], "sessions_per_week": 3, "level": "restart"}}
"""

PLAN_PROMPT = """\
You are the Program Agent for Battleship – Midlife Fitness Reset.
Generate a personalised 12-week plan for {name}.

CLIENT TAGS:
{tags_json}

INTAKE SUMMARY:
{intake_text}

CRITICAL RULES FOR HOW TO WRITE THIS PLAN:

1. STAGED REVEAL — do not dump everything at once. Each week introduces ONE new thing.
   The reader should never feel overwhelmed. If they feel overwhelmed, they quit.

2. WALKING COMES FIRST — Week 1 is walking only. Nothing else. No exceptions.
   30 minutes minimum every single day. Frame this as a non-negotiable commitment.
   Explain WHY before asking them to do anything: walking is the most underrated
   fat-loss tool for men over 40. Zone 2 walking burns fat directly, lowers cortisol,
   improves sleep, and reduces blood pressure. You almost don't need anything else
   if you walk consistently. But 30 minutes means they'll want to do more — that's the point.

3. PLAIN ENGLISH ONLY — assume the reader has never exercised before.
   Every exercise must be explained in plain English when first introduced.
   Not just the name — what it IS, what it does, and how to do it in 3 simple steps.
   No jargon without immediate explanation. "Goblet squat" means nothing to someone
   who hasn't exercised in 10 years. Tell them what it is.

4. EXPLAIN THE WHY — before every new element (exercise, nutrition change, habit),
   explain in 1–2 sentences why it's being introduced now and what it does.
   People do things they understand. They skip things they don't.

5. NUTRITION AFTER WALKING — don't introduce nutrition changes until Week 2.
   Week 1 is walking only. Week 2 adds: just track what you eat, change nothing.
   Week 3 adds: hit a protein target. One change at a time.

6. INJURY MODIFICATIONS (apply strictly, name the modification):
   - Bad knee: step-ups not lunges, bodyweight squats above 90° only, no impact
   - Lower back: hip hinges not deadlifts, bird-dog instead of plank if needed
   - High BP: no heavy max-effort lifting, Zone 2 walking is ideal and safe

7. TONE — warm, British, direct. Like a knowledgeable mate. Not a drill sergeant,
   not a cheerleader. Honest about what's hard. Confident it will work.

STRUCTURE (follow exactly):

## The One Commitment
[One paragraph. The walking commitment. Why it matters more than anything else.
Make them feel the importance of this single decision before anything else.]

## Week 1 — Just Walk
[Walking only. 30 mins minimum every day. Explain Zone 2 in plain English.
Nothing else this week. End with: "That's it. Nothing more. Just walk."]

## Week 2 — Walk + Watch
[Continue walking. Add: track food in MyFitnessPal, change nothing yet.
Explain why tracking without changing is powerful — awareness alone shifts behaviour.
No new exercises yet.]

## Week 3 — First Strength Session
[Introduce 2 strength sessions this week. For EACH exercise:
- Plain English name + what it is
- Why it's in the plan (what it does for a man their age)
- How to do it in 3 numbered steps
- Modification if it's too hard or causes pain]

## Weeks 4–8 — Building
[One paragraph per week. Each week adds or progresses one thing.
Reference exercises by name only (already explained in Week 3).
Keep it short — they know the exercises now.]

## Weeks 9–12 — The Home Stretch
[Week 9 is a deload — explain why rest weeks are when muscles actually grow.
Weeks 10–12: push for at least one personal best before the end.]

## Your 3 Numbers
[The only 3 metrics they track: daily steps, morning weight, weekly waist.
Explain each in one sentence. Nothing else.]

Markdown only. No preamble. Under 1000 words total.
"""

CHECKIN_PROMPT = """\
You are the Check-in Agent for Battleship – Midlife Fitness Reset.
Read this client's weekly check-in data and produce two things:

1. An updated progress tracker (filled from the template structure below)
2. A warm British coach message (150–250 words)

CLIENT: {name}
WEEK: {week}

WEEKLY LOG:
{log_text}

PREVIOUS TRACKER STATE:
{tracker_text}

BATTLESHIP TARGETS: 10k steps/day, 160g+ protein/day, energy score >7, alcohol minimal

PROGRESS TRACKER TEMPLATE STRUCTURE:
- Header: Client Name, Start Date, Current Week, Age, Main Goal, Baseline metrics
- Current Progress: all metrics with changes vs baseline
- Non-Scale Wins: qualitative improvements
- Battleship Agent Notes: consistency rating, biggest win, correction, tweaks, trajectory

COACH MESSAGE RULES:
- Praise specific wins first (use actual numbers from their log)
- One correction — gentle, non-shaming
- Next week's focus — one actionable thing
- Warm British tone. No hype. 150–250 words.

Output format:
[TRACKER]
...full updated tracker markdown...
[/TRACKER]
[COACH_MESSAGE]
...coach message only...
[/COACH_MESSAGE]
"""

WEEK12_PROMPT = """\
You are William George BattleShip Barratt, writing a personal end-of-programme message to {name}.

This is the final email of their 12-week Battleship programme. It should feel like a letter from a coach who genuinely knows them — not a template, not a form letter.

CLIENT INTAKE SUMMARY:
{intake_summary}

PROGRESS TRACKER (12 weeks of check-in data):
{tracker_text}

WRITE A PERSONAL CLOSING MESSAGE that:
1. Opens by naming something specific about THEIR journey — a real moment, a real struggle, a real win from their tracker. Not generic.
2. Acknowledges what they came in with (their original problem from intake) vs where they are now.
3. Is honest: 12 weeks is a foundation, not a finish line. Real transformation — the kind that lasts — takes 18–24 months. The men who look and feel genuinely different at 50 vs 45 are the ones who kept going.
4. Transitions naturally to what Phase 2 looks like: monthly coaching, continued education, weekly check-ins, plan progression — for £79/month. No hard sell. Just an honest offer from a coach who wants to see them finish what they started.
5. Closes personally. Not "the Battleship team". You. Will.

TONE: Warm, direct, British. No hype. No exclamation marks. Reads like a letter, not a marketing email.
LENGTH: 300–450 words.
OUTPUT: The message only. No subject line. No preamble.
"""


# ── Notion ───────────────────────────────────────────────────────────────────

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

def notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

def notion_text(content: str) -> dict:
    """Rich text block helper."""
    return {"type": "text", "text": {"content": content}}

def notion_paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [notion_text(text)]}}

def notion_heading(text: str, level: int = 2) -> dict:
    t = f"heading_{level}"
    return {"object": "block", "type": t, t: {"rich_text": [notion_text(text)]}}

def notion_bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [notion_text(text)]}}

def notion_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}

def notion_callout(text: str, emoji: str = "💡") -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [notion_text(text)], "icon": {"type": "emoji", "emoji": emoji}}}

def markdown_to_notion_blocks(md: str) -> list:
    """Convert simple markdown to Notion blocks (headings, bullets, paragraphs)."""
    blocks = []
    for line in md.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("# "):
            blocks.append(notion_heading(line[2:], 1))
        elif line.startswith("## "):
            blocks.append(notion_heading(line[3:], 2))
        elif line.startswith("### "):
            blocks.append(notion_heading(line[4:], 3))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(notion_bullet(line[2:]))
        elif line.startswith("---"):
            blocks.append(notion_divider())
        else:
            blocks.append(notion_paragraph(line))
    return blocks

def notion_create_page(api_key: str, parent_id: str, title: str, blocks: list) -> str:
    """Create a Notion page and return its URL."""
    # Notion API max 100 blocks per request — chunk if needed
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {"title": {"title": [notion_text(title)]}},
        "children": blocks[:100],
    }
    r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(api_key),
                      json=payload, timeout=20)
    r.raise_for_status()
    page = r.json()
    page_id = page["id"]

    # Append remaining blocks in chunks of 100
    remaining = blocks[100:]
    while remaining:
        chunk = remaining[:100]
        requests.patch(f"{NOTION_API}/blocks/{page_id}/children",
                       headers=notion_headers(api_key),
                       json={"children": chunk}, timeout=20)
        remaining = remaining[100:]

    return page["url"]

def notion_append_blocks(api_key: str, page_id: str, blocks: list):
    """Append blocks to an existing Notion page."""
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i+100]
        requests.patch(f"{NOTION_API}/blocks/{page_id}/children",
                       headers=notion_headers(api_key),
                       json={"children": chunk}, timeout=20)

def build_client_notion_page(name: str, diagnosis: str, week1_plan: str,
                              checkin_form_url: str = "") -> list:
    """Build the initial Notion page blocks for a new client."""
    blocks = []

    # Welcome
    blocks.append(notion_callout(
        f"Welcome to Battleship, {name}. This is your personal programme page — bookmark it.",
        "🚢"
    ))
    blocks.append(notion_divider())

    # Diagnosis
    blocks.append(notion_heading("Your Battleship Diagnosis", 1))
    blocks += markdown_to_notion_blocks(diagnosis)
    blocks.append(notion_divider())

    # Week 1
    blocks.append(notion_heading("Week 1 — Your Starting Point", 1))
    blocks.append(notion_callout(
        "Week 1 has one job: build the walking habit. Read this, do this, nothing more.",
        "🎯"
    ))
    blocks += markdown_to_notion_blocks(week1_plan)
    blocks.append(notion_divider())

    # Exercise guides
    blocks.append(notion_heading("Exercise Guides", 2))
    blocks.append(notion_paragraph(
        "New exercises will appear here each week with plain-English explanations "
        "before you're asked to do them."
    ))
    blocks.append(notion_divider())

    # Progress
    blocks.append(notion_heading("Your Progress", 2))
    blocks.append(notion_paragraph("Your weekly numbers will be tracked here."))
    blocks.append(notion_bullet("Weight (kg): —"))
    blocks.append(notion_bullet("Waist (cm): —"))
    blocks.append(notion_bullet("Daily steps average: —"))
    blocks.append(notion_divider())

    # Check-in
    blocks.append(notion_heading("Weekly Check-In", 2))
    if checkin_form_url:
        blocks.append(notion_paragraph(f"Submit your weekly numbers here: {checkin_form_url}"))
    else:
        blocks.append(notion_paragraph(
            "Reply to your weekly check-in email with your numbers each Sunday."
        ))

    return blocks

def create_notion_client_portal(folder: str, cs: dict, secrets: dict) -> str | None:
    """Create a Notion page for a newly enrolled client. Returns the page URL."""
    notion_key = secrets.get("notion")
    if not notion_key or not NOTION_PARENT_PAGE_ID:
        return None

    diagnosis  = read_client_file(folder, "diagnosis.md")
    plan       = read_client_file(folder, "plan.md")

    # Extract just Week 1 from the plan for initial delivery
    week1 = plan
    if "## Week 2" in plan:
        week1 = plan.split("## Week 2")[0].strip()
    elif "## Weeks 4" in plan:
        week1 = plan.split("## Weeks 4")[0].strip()

    checkin_url = f"https://form.typeform.com/to/{CHECKIN_FORM_ID}" if CHECKIN_FORM_ID else ""
    blocks = build_client_notion_page(cs["name"], diagnosis, week1, checkin_url)

    print(f"     📄 Creating Notion page for {cs['name']}...")
    url = notion_create_page(
        notion_key,
        NOTION_PARENT_PAGE_ID,
        f"Battleship — {cs['name']}",
        blocks,
    )
    log_event(folder, f"Notion client portal created: {url}")
    print(f"     🔗 Notion page: {url}")
    return url

def update_notion_week(folder: str, cs: dict, secrets: dict, week: int, coach_message: str):
    """Append a new week's content and coach message to the client's Notion page."""
    notion_key = secrets.get("notion")
    page_id = cs.get("notion_page_id")
    if not notion_key or not page_id:
        return

    plan = read_client_file(folder, "plan.md")

    # Extract current week section from plan
    week_marker = f"## Week {week}"
    next_marker = f"## Week {week + 1}" if week < 12 else "## Your 3 Numbers"
    week_content = ""
    if week_marker in plan:
        start = plan.index(week_marker)
        end = plan.index(next_marker) if next_marker in plan else len(plan)
        week_content = plan[start:end].strip()

    blocks = [
        notion_divider(),
        notion_heading(f"Week {week} — Coach Update", 2),
        notion_callout(coach_message, "📋"),
    ]
    if week_content:
        blocks.append(notion_heading(f"Week {week} Plan", 3))
        blocks += markdown_to_notion_blocks(week_content)

    notion_append_blocks(notion_key, page_id, blocks)
    log_event(folder, f"Notion page updated for Week {week}")


# ── Email ─────────────────────────────────────────────────────────────────────

TEMPLATES_DIR = VAULT_ROOT / "scripts" / "templates"

def render_template(template_path: Path, **kwargs) -> str:
    """Load an HTML template and substitute %%key%% placeholders."""
    html = template_path.read_text()
    for key, value in kwargs.items():
        html = html.replace(f"%%{key}%%", str(value) if value else "")
    return html

def md_to_html(text: str, text_color: str = "#2c2c2c") -> str:
    """Convert markdown to email-safe inline-styled HTML."""
    lines = text.split("\n")
    html, in_ul, in_ol, ol_idx = [], False, False, 0

    def close_lists():
        nonlocal in_ul, in_ol, ol_idx
        if in_ul:
            html.append("</ul>")
            in_ul = False
        if in_ol:
            html.append("</ol>")
            in_ol = False
            ol_idx = 0

    for line in lines:
        s = line.strip()

        if not s:
            close_lists()
            continue

        # Inline formatting
        s = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.*?)\*",     r"<em>\1</em>", s)
        s = re.sub(r"`(.*?)`",       r'<code style="background:#f0ece4;padding:1px 5px;border-radius:3px;font-size:14px;">\1</code>', s)

        if s.startswith("---"):
            close_lists()
            html.append('<hr style="border:none;border-top:1px solid #e8e3da;margin:24px 0;">')
        elif s.startswith("### "):
            close_lists()
            html.append(f'<h3 style="margin:22px 0 10px;font-family:Georgia,serif;font-size:17px;font-weight:normal;color:#0a0a0a;">{s[4:]}</h3>')
        elif s.startswith("## "):
            close_lists()
            html.append(f'<h2 style="margin:28px 0 12px;font-family:Georgia,serif;font-size:20px;font-weight:normal;color:#0a0a0a;border-bottom:1px solid #e8e3da;padding-bottom:8px;">{s[3:]}</h2>')
        elif s.startswith("# "):
            close_lists()
            html.append(f'<h1 style="margin:0 0 20px;font-family:Georgia,serif;font-size:24px;font-weight:normal;color:#0a0a0a;">{s[2:]}</h1>')
        elif re.match(r"^\d+\.\s", s):
            if not in_ol:
                html.append('<ol style="margin:10px 0 14px;padding-left:20px;">')
                in_ol = True
            item_text = re.sub(r"^\d+\.\s", "", s)
            html.append(f'<li style="margin:6px 0;font-size:15px;line-height:1.7;color:{text_color};">{item_text}</li>')
        elif s.startswith("- ") or s.startswith("* "):
            if not in_ul:
                html.append('<ul style="margin:10px 0 14px;padding-left:18px;">')
                in_ul = True
            html.append(f'<li style="margin:6px 0;font-size:15px;line-height:1.7;color:{text_color};">{s[2:]}</li>')
        else:
            close_lists()
            html.append(f'<p style="margin:0 0 14px;font-size:15px;line-height:1.75;color:{text_color};">{s}</p>')

    close_lists()
    return "\n".join(html)

def parse_diagnosis_sections(md: str) -> dict:
    """Split Claude's diagnosis markdown into named sections."""
    sections: dict[str, list] = {}
    current_key = None
    for line in md.split("\n"):
        if line.startswith("## "):
            current_key = line[3:].strip()
            sections[current_key] = []
        elif line.startswith("# "):
            pass  # skip main title
        elif current_key:
            sections[current_key].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}

def send_email(secrets: dict, to: str, subject: str, plain_body: str, html_body: str = None):
    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = f"Will Barratt – Battleship <{secrets['smtp_user']}>"
    msg["To"]       = to
    msg["Reply-To"] = COACH_EMAIL
    msg.attach(MIMEText(plain_body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(secrets["smtp_host"], SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(secrets["smtp_user"], secrets["smtp_pass"])
        s.sendmail(secrets["smtp_user"], to, msg.as_string())
    print(f"    📧 '{subject[:55]}' → {to}")


def email_diagnosis(name: str, diagnosis: str,
                    payment_link: str = "https://buy.stripe.com/3cI6oG79qefgb1CdhwejK00") -> tuple[str, str, str]:
    subj = f"Your Battleship Diagnosis, {name}"

    # Plain text fallback
    plain = f"Hi {name},\n\n{diagnosis}\n\n---\n\nIf this resonated, the next step is straightforward.\n\n→ {payment_link}\n\nNo pressure. Reply with any questions.\n\n— {COACH_NAME}"

    # Parse sections for HTML
    secs = parse_diagnosis_sections(diagnosis)
    html = render_template(
        TEMPLATES_DIR / "diagnosis_email.html",
        name=name,
        section_failed=md_to_html(secs.get("Why It's Failed Before", diagnosis)),
        section_different=md_to_html(secs.get("What Will Be Different This Time", "")),
        section_week1=md_to_html(secs.get("Your Week 1 Starting Point", "")),
        section_worth_it=md_to_html(secs.get("Why This Is Worth It", ""), text_color="#cccccc"),
        payment_link=payment_link,
        coach_name=COACH_NAME,
    )
    return subj, plain, html


def email_onboarding(name: str, notion_url: str = None) -> tuple[str, str, str]:
    subj = f"You're in — welcome to Battleship, {name}"

    # Plain text fallback
    portal = f"\n→ Your programme page: {notion_url}\n" if notion_url else ""
    plain = f"Hi {name},\n\nWelcome aboard.{portal}\n\nOne thing to do today: a 30-minute walk. That's Week 1.\n\nReply with: weight, waist, energy score, steps yesterday.\n\n— {COACH_NAME}"

    # Portal section (optional)
    if notion_url:
        portal_section = f"""<tr>
      <td bgcolor="#f0ede6" style="padding:20px 44px;background-color:#f0ede6;border-top:1px solid #e8e3da;text-align:center;">
        <p style="margin:0 0 8px;font-size:13px;color:#888888;text-transform:uppercase;letter-spacing:1px;">Your Programme Page</p>
        <a href="{notion_url}" style="font-family:Georgia,serif;font-size:16px;color:#c41e3a;text-decoration:none;font-weight:bold;">Bookmark this link →</a>
        <p style="margin:6px 0 0;font-size:13px;color:#aaaaaa;">Your diagnosis, plan, exercise guides, and progress are all here.</p>
      </td>
    </tr>"""
    else:
        portal_section = ""

    html = render_template(
        TEMPLATES_DIR / "onboarding_email.html",
        name=name,
        portal_section=portal_section,
        coach_name=COACH_NAME,
    )
    return subj, plain, html


def email_weekly_checkin_request(name: str, week: int, checkin_form_url: str = "") -> tuple[str, str]:
    subj = f"Week {week} check-in — how did it go, {name}?"
    form_line = f"\n→ {checkin_form_url}\n" if checkin_form_url else "\nReply to this email with your numbers.\n"
    body = f"""Hi {name},

Week {week} done. Time to log it.
{form_line}
- Weight this morning (kg)
- Waist (cm) — every 2 weeks
- Average daily steps
- Average protein (g/day)
- Alcohol units this week
- Energy score average (1–10)
- Workouts completed vs target
- Any issues or injuries
- One win from this week (mandatory — find one)

I'll review and send your Week {week + 1} adjustment by Tuesday.

— {COACH_NAME}

P.S. A MyFitnessPal weekly summary screenshot saves typing."""
    return subj, body


# ── Client Folder ─────────────────────────────────────────────────────────────

def client_folder_name(account_no: str, name: str) -> str:
    """e.g. BSR-2026-0001-will"""
    return f"{account_no}-{name.lower().replace(' ', '-')}"

def save_client_file(folder: str, filename: str, content: str):
    path = CLIENTS_DIR / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text(content)

def read_client_file(folder: str, filename: str) -> str:
    path = CLIENTS_DIR / folder / filename
    return path.read_text() if path.exists() else ""

def log_event(folder: str, event: str):
    log_file = CLIENTS_DIR / folder / "log.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(log_file, "a") as f:
        f.write(f"- {ts}: {event}\n")


# ── Pipeline: Intake → Diagnosis ──────────────────────────────────────────────

def process_new_intake(client: dict, secrets: dict, state: dict):
    # Skip if email already in system
    existing = next(
        (acct for acct, cs in state["clients"].items()
         if cs.get("email") == client["email"] and cs.get("status") != "error"),
        None
    )
    if existing:
        state["processed_intake_ids"].append(client["response_id"])
        print(f"\n  ⏭  Skipping duplicate: {client['name']} ({existing})")
        return

    account_no = next_account_number(state)
    folder     = client_folder_name(account_no, client["name"])

    print(f"\n  🆕 New intake: {client['name']} → {account_no} ({folder})")

    # Save raw intake
    save_client_file(folder, "intake.md",
        f"# Intake — {client['name']}\nAccount: {account_no}\nSubmitted: {client['submitted_at']}\n\n{client['raw_text']}"
    )

    # Generate diagnosis via Claude
    print("     🧠 Generating diagnosis...")
    prompt = DIAGNOSIS_PROMPT.format(intake_text=client["raw_text"], name=client["name"])
    raw = call_claude(secrets["anthropic"], prompt, max_tokens=1800)

    # Extract tags JSON — find any JSON block regardless of marker
    tags = {}
    json_match = re.search(r'```(?:json)?\s*\n(\{.*?\})\s*\n```', raw, re.DOTALL)
    if json_match:
        try:
            tags = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    else:
        bare_match = re.search(r'AGENT_TAGS_JSON\s*(\{.*?\})\s*$', raw, re.DOTALL)
        if bare_match:
            try:
                tags = json.loads(bare_match.group(1))
            except json.JSONDecodeError:
                pass

    # Strip JSON block and trailing dividers from diagnosis text
    diagnosis_text = re.sub(r'\n---\s*\nAGENT_TAGS_JSON.*$', '', raw, flags=re.DOTALL)
    diagnosis_text = re.sub(r'\n```(?:json)?\s*\n\{.*?\}\s*\n```\s*$', '', diagnosis_text, flags=re.DOTALL)
    diagnosis_text = re.sub(r'\n---\s*$', '', diagnosis_text).strip()

    save_client_file(folder, "diagnosis.md", diagnosis_text)
    save_client_file(folder, "tags.json", json.dumps(tags, indent=2))
    log_event(folder, "Diagnosis generated by Claude")

    # Send diagnosis email
    if client["email"]:
        subj, plain, html = email_diagnosis(client["name"], diagnosis_text)
        send_email(secrets, client["email"], subj, plain, html)
        log_event(folder, "Diagnosis email sent")

    # Update state and save immediately
    state["clients"][account_no] = {
        "account_no":            account_no,
        "folder":                folder,
        "name":                  client["name"],
        "email":                 client["email"],
        "intake_date":           client["submitted_at"][:10],
        "status":                "diagnosed",
        "current_week":          0,
        "enrolled_date":         None,
        "emails_sent":           ["diagnosis"],
        "tags":                  tags,
        "last_checkin_request":  None,
        "last_checkin_received": None,
        "notion_page_id":        None,
        "notion_url":            None,
    }
    state["processed_intake_ids"].append(client["response_id"])
    save_state(state)
    print(f"     ✅ {account_no} — {client['name']} → diagnosed")


# ── Pipeline: Payment → Enrolment ─────────────────────────────────────────────

def enrol_client(account_no: str, cs: dict, secrets: dict):
    """Generate plan and send onboarding emails after payment detected."""
    folder = cs["folder"]
    print(f"\n  💳 Enrolling {cs['name']} ({account_no})...")

    intake_text = read_client_file(folder, "intake.md")
    tags_raw    = read_client_file(folder, "tags.json")
    tags        = json.loads(tags_raw) if tags_raw else {}

    prompt = PLAN_PROMPT.format(
        name=cs["name"],
        tags_json=json.dumps(tags, indent=2),
        intake_text=intake_text[:3000],
    )
    print("     🧠 Generating 12-week plan...")
    plan = call_claude(secrets["anthropic"], prompt, max_tokens=2000)
    save_client_file(folder, "plan.md", plan)
    save_client_file(folder, "progress-tracker.md",
        f"# Progress Tracker — {cs['name']}\nAccount: {account_no}\n\n*Baseline filled from first check-in.*\n")
    log_event(folder, "12-week plan generated by Claude")

    # Create Notion client portal
    notion_url = create_notion_client_portal(folder, cs, secrets)
    cs["notion_page_id"] = notion_url.split("-")[-1] if notion_url else None
    cs["notion_url"]     = notion_url

    if cs["email"]:
        subj5, plain5, html5 = email_onboarding(cs["name"], notion_url)
        send_email(secrets, cs["email"], subj5, plain5, html5)
        log_event(folder, "Onboarding email sent")

    cs["status"]        = "active"
    cs["current_week"]  = 1
    cs["enrolled_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cs["emails_sent"].append("onboarding")
    print(f"     ✅ {account_no} {cs['name']} enrolled — Week 1 starts now")


def check_stripe_payments(state: dict, secrets: dict):
    """Poll Stripe for new payments and enrol matching diagnosed clients."""
    stripe_key = secrets.get("stripe")
    if not stripe_key:
        return

    diagnosed = {slug: cs for slug, cs in state["clients"].items() if cs["status"] == "diagnosed"}
    if not diagnosed:
        return

    r = requests.get(
        "https://api.stripe.com/v1/charges",
        auth=(stripe_key, ""),
        params={"limit": 50},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  ⚠️  Stripe API error {r.status_code}")
        return

    paid_emails = {
        c["billing_details"].get("email", "").lower()
        for c in r.json().get("data", [])
        if c.get("paid") and c.get("billing_details", {}).get("email")
    }

    for acct, cs in diagnosed.items():
        if cs["email"].lower() in paid_emails:
            enrol_client(acct, cs, secrets)
            log_event(cs["folder"], "Payment detected via Stripe — auto-enrolled")


# ── Pipeline: Weekly Check-In Requests ────────────────────────────────────────

def send_weekly_checkin_requests(state: dict, secrets: dict):
    """Every Sunday, send check-in request to all active clients."""
    today = datetime.now(timezone.utc)
    if today.weekday() != 6:  # 6 = Sunday
        return

    checkin_url = CHECKIN_GFORM_URL or (f"https://form.typeform.com/to/{CHECKIN_FORM_ID}" if CHECKIN_FORM_ID else "")

    for slug, cs in state["clients"].items():
        if cs["status"] != "active":
            continue

        last = cs.get("last_checkin_request")
        if last:
            days_since = (today - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            if days_since < 6:
                continue  # already sent this week

        week = cs.get("current_week", 1)
        print(f"  📅 Sending Week {week} check-in request to {cs['name']}...")

        subj, body = email_weekly_checkin_request(cs["name"], week, checkin_url)
        send_email(secrets, cs["email"], subj, body)
        log_event(cs["folder"], f"Week {week} check-in request sent")

        cs["last_checkin_request"] = today.isoformat()
        cs["current_week"] = week + 1


# ── Google Sheets check-in polling ────────────────────────────────────────────

def gsheets_get_rows(sheet_id: str, creds_path: str) -> list[dict]:
    """Return all rows from 'Form Responses 1' as a list of dicts keyed by header."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_file = Path(creds_path).expanduser()
    if not creds_file.exists():
        print(f"  ⚠️  Google Sheets credentials not found at {creds_path}")
        return []

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = Credentials.from_service_account_file(str(creds_file), scopes=scopes)
    gc     = gspread.authorize(creds)

    try:
        sh     = gc.open_by_key(sheet_id)
        ws     = sh.sheet1
        rows   = ws.get_all_records()   # list of dicts, header row as keys
        return rows
    except Exception as e:
        print(f"  ⚠️  Google Sheets error: {e}")
        return []


def gsheets_parse_row(row: dict) -> dict:
    """Normalise a Google Forms response row into the same shape as tf_parse_response."""
    # Keyword matching — tolerant of question wording variations in the form
    field_map = {
        "email":     ["email address", "email"],
        "workouts":  ["workouts", "how many workout", "sessions"],
        "steps":     ["steps", "daily steps", "average steps"],
        "weight":    ["weight", "current weight"],
        "waist":     ["waist"],
        "calories":  ["calories", "calorie", "mfp", "myfitnesspal", "daily cal"],
        "feel":      ["body feel", "overall", "how did your body"],
        "energy":    ["energy"],
        "sleep":     ["sleep quality", "sleep"],
        "injury":    ["pain", "soreness", "injury", "flag"],
        "obstacles": ["got in the way", "obstacle", "challenge"],
        "win":       ["went well", "win", "proud"],
        "hard":      ["felt hard", "hard", "struggled"],
        "questions": ["question", "anything else"],
        "timestamp": ["timestamp"],
    }

    parsed = {k: "" for k in field_map}
    for col_header, value in row.items():
        col_lower = col_header.lower()
        for field_key, keywords in field_map.items():
            if any(kw in col_lower for kw in keywords):
                parsed[field_key] = str(value).strip()
                break

    # Build a structured raw_text for Claude — numbers first so trends are obvious
    labels = {
        "weight":    "Weight this week",
        "waist":     "Waist (cm/inches)",
        "steps":     "Avg daily steps",
        "calories":  "Avg daily calories (MFP)",
        "workouts":  "Workouts completed",
        "feel":      "Body felt (1–5)",
        "energy":    "Energy (1–5)",
        "sleep":     "Sleep quality (1–5)",
        "injury":    "Pain/injury",
        "obstacles": "What got in the way",
        "win":       "One win",
        "hard":      "One hard thing",
        "questions": "Questions for coach",
    }
    lines = []
    for key, label in labels.items():
        val = parsed.get(key, "")
        if val:
            lines.append(f"{label}: {val}")
    parsed["raw_text"] = "\n".join(lines)
    return parsed


# ── Pipeline: Process Check-In Responses ──────────────────────────────────────

def _process_single_checkin(state: dict, secrets: dict, parsed: dict, row_id: str):
    """Shared logic: match check-in data to a client and generate coach response."""
    matching_key = next(
        (k for k, cs in state["clients"].items()
         if cs["email"].lower() == parsed.get("email", "").lower()),
        None
    )
    if not matching_key:
        print(f"  ⚠️  Check-in from unknown email: {parsed.get('email')}")
        state.setdefault("processed_checkin_ids", []).append(row_id)
        return

    cs   = state["clients"][matching_key]
    week = cs.get("current_week", 1) - 1

    print(f"\n  📋 Processing Week {week} check-in for {cs['name']}...")

    existing_tracker = read_client_file(cs["folder"], "progress-tracker.md")
    prompt = CHECKIN_PROMPT.format(
        name=cs["name"],
        week=week,
        log_text=parsed["raw_text"],
        tracker_text=existing_tracker[:2000] if existing_tracker else "No previous tracker.",
    )
    raw = call_claude(secrets["anthropic"], prompt, max_tokens=2000)

    tracker_text  = ""
    coach_message = ""
    if "[TRACKER]" in raw and "[/TRACKER]" in raw:
        tracker_text = raw.split("[TRACKER]")[1].split("[/TRACKER]")[0].strip()
    if "[COACH_MESSAGE]" in raw and "[/COACH_MESSAGE]" in raw:
        coach_message = raw.split("[COACH_MESSAGE]")[1].split("[/COACH_MESSAGE]")[0].strip()

    if tracker_text:
        save_client_file(cs["folder"], "progress-tracker.md", tracker_text)
        log_event(cs["folder"], f"Week {week} progress tracker updated")

    if coach_message:
        update_notion_week(cs["folder"], cs, secrets, week, coach_message)
        if cs["email"]:
            notion_url   = cs.get("notion_url", "")
            portal_line  = f"\n\nYour programme page: {notion_url}" if notion_url else ""
            subj = f"Week {week} review — {cs['name']}"
            send_email(secrets, cs["email"], subj,
                       f"Hi {cs['name']},\n\n{coach_message}{portal_line}\n\n— {COACH_NAME}")
            log_event(cs["folder"], f"Week {week} coach message sent")
            print(f"     ✅ Coach response sent to {cs['name']}")

    cs["last_checkin_received"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("processed_checkin_ids", []).append(row_id)


def process_checkin_responses(state: dict, secrets: dict):
    """Poll Google Sheet (or legacy Typeform) for check-in responses and process new ones."""

    # ── Google Sheets path (preferred) ────────────────────────────────────────
    sheet_id   = secrets.get("gsheets_id", "")
    creds_path = secrets.get("gsheets_creds", "")

    if sheet_id and creds_path:
        rows = gsheets_get_rows(sheet_id, creds_path)
        for i, row in enumerate(rows):
            # Use row index as stable ID (Google Sheets rows don't have UUIDs)
            row_id = f"gsheet-row-{i+2}"   # +2 because row 1 is header
            if row_id in state.get("processed_checkin_ids", []):
                continue
            parsed = gsheets_parse_row(row)
            if not parsed.get("email"):
                continue
            _process_single_checkin(state, secrets, parsed, row_id)
        return

    # ── Legacy Typeform fallback ───────────────────────────────────────────────
    if not CHECKIN_FORM_ID:
        print("  (check-in form not configured — skipping)")
        return

    field_map = tf_get_field_map(secrets["typeform"], CHECKIN_FORM_ID)
    responses  = tf_get_responses(secrets["typeform"], CHECKIN_FORM_ID)
    for item in responses:
        rid = item.get("response_id", "")
        if rid in state.get("processed_checkin_ids", []):
            continue
        parsed = tf_parse_response(item, field_map)
        _process_single_checkin(state, secrets, parsed, rid)


# ── Pipeline: Education Drips ─────────────────────────────────────────────────

def _calorie_target(cs: dict) -> str:
    """Return a personalised calorie target line based on intake weight and food relationship."""
    tags = cs.get("tags", {})
    weight_raw = tags.get("weight_lbs", "") or tags.get("weight", "")
    food_rel   = tags.get("food_relationship", "").lower()

    try:
        lbs = float(str(weight_raw).replace("lbs","").replace("lb","").strip())
        # If they flagged difficulty with restriction, use ×15; otherwise ×12
        hard = any(w in food_rel for w in ["hard", "difficult", "struggle", "restrict", "comfort", "emotional"])
        multiplier = 15 if hard else 12
        target = int(lbs * multiplier)
        return f"**Your target: {target} calories/day** (your weight × {multiplier})"
    except (ValueError, TypeError):
        return "**Your target:** use the formula in the lesson — your weight in lbs × 12 (or × 15 if you find restriction difficult)"


def _decode_header(value: str) -> str:
    """Decode RFC2047 encoded email header."""
    parts = decode_header(value or "")
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_email_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


COACH_REPLY_PROMPT = """You are Will Barratt, founder of Battleship – Midlife Fitness Reset.
A client has emailed coach@battleship.me with a question or update.

Write a reply in Will's voice: direct, warm, no fluff, no corporate tone. Like a knowledgeable mate who happens to know a lot about fitness and nutrition. Short paragraphs. Never use bullet points in replies unless listing specific actions. Sign off as Will.

Client name: {name}
Client week: {week}
Their message:
---
{message}
---

Client background (from their intake):
{background}

Reply only with the email body — no subject line, no preamble."""


SUPPORT_REPLY_PROMPT = """You are handling support for Battleship – Midlife Fitness Reset on behalf of Will Barratt.
A client has emailed support@battleship.me.

Write a helpful, warm reply. If they mention cancellation or a refund, acknowledge it with empathy, ask what's gone wrong, and let them know Will will be in touch personally — do NOT promise a refund or process anything. For technical issues or programme questions, resolve them directly. Sign off as "The Battleship Team".

Client name: {name}
Their message:
---
{message}
---

Reply only with the email body — no subject line, no preamble."""


def process_inbound_emails(state: dict, secrets: dict):
    """Poll coach@ and support@ inboxes, auto-reply to client emails via Claude."""
    if not secrets.get("imap_host") or not secrets.get("imap_user") or not secrets.get("imap_pass"):
        print("  ⚠️  IMAP credentials not set — skipping inbound email processing")
        return

    print(f"  📬 Connecting to {secrets['imap_host']}...")
    try:
        mail = imaplib.IMAP4_SSL(secrets["imap_host"], 993)
        mail.login(secrets["imap_user"], secrets["imap_pass"])
    except Exception as e:
        print(f"  ❌ IMAP login failed: {e}")
        return

    mail.select("INBOX")
    _, data = mail.search(None, "UNSEEN")
    uids = data[0].split()
    if not uids:
        print("  📭 No new emails")
        mail.logout()
        return

    print(f"  📬 {len(uids)} unread email(s)...")
    client = anthropic.Anthropic(api_key=secrets["anthropic"])

    for uid in uids:
        _, msg_data = mail.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        from_addr  = _decode_header(msg.get("From", ""))
        to_addr    = _decode_header(msg.get("To", "")).lower()
        subject    = _decode_header(msg.get("Subject", ""))
        body       = _get_email_body(msg).strip()

        # Extract sender email from "Name <email>" format
        sender_email = from_addr
        if "<" in from_addr and ">" in from_addr:
            sender_email = from_addr.split("<")[1].rstrip(">").strip().lower()

        # Route: will@ — skip, just flag
        if WILL_EMAIL in to_addr:
            print(f"  👤 Email to will@ from {sender_email} — needs your personal reply")
            mail.store(uid, "+FLAGS", "\\Seen")
            continue

        # Determine routing
        is_coach   = COACH_EMAIL in to_addr
        is_support = SUPPORT_EMAIL in to_addr
        if not is_coach and not is_support:
            print(f"  ❓ Unrecognised To: address ({to_addr}) — skipping")
            continue

        # Find matching client
        acct, cs = find_client(sender_email, state)
        if not acct:
            print(f"  ⚠️  Unknown sender {sender_email} — no matching client, skipping")
            mail.store(uid, "+FLAGS", "\\Seen")
            continue

        print(f"  ✉️  {'coach@' if is_coach else 'support@'} from {cs['name']} ({sender_email})")

        # Build prompt
        enrolled  = datetime.fromisoformat(cs.get("enrolled_date", datetime.now(timezone.utc).isoformat())).date()
        week      = ((datetime.now(timezone.utc).date() - enrolled).days // 7) + 1
        background = cs.get("intake_summary", cs.get("goal", "No background on file."))

        if is_coach:
            prompt = COACH_REPLY_PROMPT.format(
                name=cs["name"], week=week, message=body, background=background
            )
            from_label = COACH_EMAIL
        else:
            prompt = SUPPORT_REPLY_PROMPT.format(name=cs["name"], message=body)
            from_label = SUPPORT_EMAIL
            # Flag cancellation/refund requests to Will
            if any(w in body.lower() for w in ["cancel", "refund", "stop", "quit the programme", "quit the program"]):
                print(f"  🚨 CANCELLATION REQUEST from {cs['name']} — flagged for Will's attention")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        reply_body = response.content[0].text.strip()

        # Re: subject
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        plain_reply = reply_body
        send_email(secrets, sender_email, reply_subject, plain_reply)
        mail.store(uid, "+FLAGS", "\\Seen")

        if cs.get("folder"):
            log_event(cs["folder"], f"Inbound email replied ({'coach' if is_coach else 'support'}): {subject[:60]}")
        print(f"  ✅ Replied to {cs['name']}")

    mail.logout()


def send_education_drips(state: dict, secrets: dict):
    """Send up to 2 education emails/week to each active client on schedule."""
    today = datetime.now(timezone.utc).date()

    for slug, cs in state["clients"].items():
        if cs["status"] != "active" or not cs.get("enrolled_date"):
            continue

        enrolled = datetime.fromisoformat(cs["enrolled_date"]).date()
        week     = ((today - enrolled).days // 7) + 1

        drips = EDUCATION_DRIPS.get(week, [])
        if not drips:
            continue

        # Stagger: lesson index 0 on day 1 of the week (Monday), index 1 on day 4 (Thursday)
        day_of_week = (today - enrolled).days % 7   # 0=Mon … 6=Sun within current week
        for idx, (key, subject, content_file) in enumerate(drips):
            if key in cs.get("emails_sent", []):
                continue

            # Lesson 0 fires Monday (day 0–3), lesson 1 fires Thursday (day 3–6)
            if idx == 1 and day_of_week < 3:
                continue   # too early in the week for second lesson

            content_path = VAULT_ROOT / content_file
            if not content_path.exists():
                print(f"  ⚠️  Education content not found: {content_file}")
                continue

            content = content_path.read_text()

            # Inject personalised calorie target into fat loss lesson
            if key == "edu_fatloss_1":
                calorie_line = _calorie_target(cs)
                content = content.replace(
                    "Your number was calculated for you in your diagnosis.",
                    f"Your number was calculated for you in your diagnosis.\n\n{calorie_line}"
                )

            # Parse lesson markdown: extract title, "This week" block, body
            lines        = content.splitlines()
            lesson_title = lines[0].lstrip("# ").strip() if lines else subject
            body_md      = "\n".join(lines[1:]).strip()

            # Pull out "This week" section as a dark callout block
            this_week_md  = ""
            this_week_html = ""
            if "## This week" in body_md:
                parts        = body_md.split("## This week", 1)
                body_md      = parts[0].strip()
                this_week_md = parts[1].strip()
            if this_week_md:
                this_week_html = f"""
    <tr>
      <td bgcolor="#0a0a0a" style="padding:28px 44px;background-color:#0a0a0a;border-top:4px solid #c41e3a;">
        <p style="margin:0 0 10px;font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:#666666;font-family:Arial,sans-serif;">This week</p>
        {md_to_html(this_week_md, text_color="#cccccc")}
      </td>
    </tr>"""

            # Determine lesson label from module
            label_map = {
                "edu_sleep": "Sleep & Stress", "edu_zone2": "Zone 2 Cardio",
                "edu_nutrition_1": "Nutrition", "edu_8020": "Nutrition",
                "edu_plate": "Nutrition", "edu_fatloss_1": "Fat Loss",
                "edu_fatloss_2": "Fat Loss", "edu_fatloss_3": "Fat Loss",
                "edu_fatloss_4": "Fat Loss", "edu_wholefoods": "Nutrition",
                "edu_training_1": "Training", "edu_gym_terms": "Training",
                "edu_gymtim": "Training", "edu_warmup": "Training",
                "edu_prep": "Training", "edu_weight": "Training",
                "edu_fatloss_t": "Training", "edu_bws": "Training",
            }
            lesson_label = label_map.get(key, "Education")

            # Build plain text fallback
            plain_body = (
                f"Hi {cs['name']},\n\nThis week's Battleship education.\n\n"
                f"---\n\n{content}\n\n---\n\n"
                f"Got a question? Just reply.\n\n— {COACH_NAME}"
            )

            # Build HTML
            edu_template = TEMPLATES_DIR / "education_email.html"
            html_body = render_template(
                edu_template,
                subject      = subject,
                week         = str(week),
                lesson_label = lesson_label,
                lesson_title = lesson_title,
                lesson_body  = md_to_html(body_md),
                this_week_block = this_week_html,
                coach_name   = COACH_NAME,
            )

            print(f"  📚 Sending '{key}' to {cs['name']} (Week {week})...")
            send_email(secrets, cs["email"], subject, plain_body, html_body)
            if cs.get("folder"):
                log_event(cs["folder"], f"Education drip '{key}' sent (Week {week})")
            cs["emails_sent"].append(key)


# ── Week 12 Personal Close ────────────────────────────────────────────────────

def send_week12_close(state: dict, secrets: dict):
    """Generate and send a personalised end-of-programme message at Week 12."""
    today = datetime.now(timezone.utc).date()

    for acct, cs in state["clients"].items():
        if cs["status"] != "active" or not cs.get("enrolled_date"):
            continue
        if "week12_close" in cs.get("emails_sent", []):
            continue

        enrolled = datetime.fromisoformat(cs["enrolled_date"]).date()
        week = ((today - enrolled).days // 7) + 1
        if week < 12:
            continue

        print(f"\n  🎓 Generating Week 12 personal close for {cs['name']}...")

        tracker     = read_client_file(cs["folder"], "progress-tracker.md")
        intake_tags = cs.get("tags", {})
        intake_summary = "\n".join(f"{k}: {v}" for k, v in intake_tags.items() if v)

        prompt = WEEK12_PROMPT.format(
            name=cs["name"],
            intake_summary=intake_summary or "No intake tags recorded.",
            tracker_text=tracker[:3000] if tracker else "No tracker data — client did not submit check-ins.",
        )
        message = call_claude(secrets["anthropic"], prompt, max_tokens=1000)

        subj = f"12 weeks — and what comes next, {cs['name'].split()[0]}"
        body = (
            f"{message}\n\n"
            f"---\n\n"
            f"If you'd like to continue: reply to this email and I'll send you the details for Phase 2.\n\n"
            f"— {COACH_NAME}\n"
            f"will@battleshipreset.com"
        )

        send_email(secrets, cs["email"], subj, body)
        log_event(cs["folder"], "Week 12 personal close sent")
        cs["emails_sent"].append("week12_close")
        cs["status"] = "complete"
        print(f"     ✅ Week 12 close sent to {cs['name']}")


# ── Enrol Client Manually ─────────────────────────────────────────────────────

def manual_enrol(query: str, state: dict, secrets: dict, free: bool = False):
    """--enrol accepts account number, name, or email. --free skips Stripe requirement."""
    acct, cs = find_client(query, state)
    if not cs:
        print(f"❌ No client found matching '{query}'")
        print("   Use --find=<query> to search")
        return
    if cs["status"] == "active" and not free:
        print(f"⚠️  {cs['name']} ({acct}) is already '{cs['status']}'")
        return
    if cs["status"] not in ("diagnosed", "active"):
        print(f"⚠️  {cs['name']} ({acct}) has status '{cs['status']}' — must be 'diagnosed' first")
        return
    if free:
        cs["complimentary"] = True
        print(f"  🎁 Complimentary enrolment — Stripe skipped")
    enrol_client(acct, cs, secrets)
    log_event(cs["folder"], f"Manually enrolled via --enrol {'(complimentary)' if free else ''}")
    save_state(state)
    print(f"✅ {acct} {cs['name']} enrolled and state saved.")


def cmd_advance(query: str, state: dict):
    """--advance=<query> — bump a client's current_week forward by 1."""
    acct, cs = find_client(query, state)
    if not cs:
        print(f"❌ No client found matching '{query}'")
        return
    if cs["status"] != "active":
        print(f"⚠️  {cs['name']} is not active (status: {cs['status']})")
        return
    before = cs.get("current_week", 1)
    cs["current_week"] = before + 1
    log_event(cs["folder"], f"Week manually advanced from {before} to {cs['current_week']}")
    save_state(state)
    print(f"✅ {acct} {cs['name']} advanced to week {cs['current_week']}")

def cmd_find(query: str, state: dict):
    """--find=<query> — search clients by account number, name, or email."""
    print(f"\n🔍 Searching for '{query}'...\n")
    results = []
    q = query.strip().lower()
    for acct, cs in state["clients"].items():
        if (q in acct.lower() or
                q in cs.get("name", "").lower() or
                q in cs.get("email", "").lower()):
            results.append((acct, cs))
    if not results:
        print("  No clients found.")
        return
    for acct, cs in results:
        print(f"  {acct}  {cs['name']:20s}  {cs['email']:30s}  {cs['status']}  week {cs.get('current_week', 0)}")
        print(f"         Folder: clients/{cs['folder']}/")
        print(f"         Enrolled: {cs.get('enrolled_date') or 'not yet'}")
        print()


def cmd_status(query: str, state: dict):
    """--status=<query> — full client report: week, emails, tracker, recent events."""
    acct, cs = find_client(query, state)
    if not cs:
        print(f"❌ No client found matching '{query}'")
        return

    folder_path = CLIENTS_DIR / cs["folder"]
    print(f"\n{'='*60}")
    print(f"  {acct}  —  {cs['name']}")
    print(f"{'='*60}")
    print(f"  Email:     {cs['email']}")
    print(f"  Status:    {cs['status']}")
    print(f"  Week:      {cs.get('current_week', 0)}")
    print(f"  Enrolled:  {cs.get('enrolled_date') or 'not yet'}")
    if cs.get("complimentary"):
        print(f"  Plan:      Complimentary (no charge)")
    print(f"  Emails:    {', '.join(cs.get('emails_sent', []))}")
    print(f"  Folder:    clients/{cs['folder']}/")

    # Progress tracker summary
    tracker = read_client_file(cs["folder"], "progress-tracker.md")
    if tracker:
        lines = tracker.strip().splitlines()
        print(f"\n  Progress tracker ({len(lines)} lines):")
        for line in lines[-10:]:   # last 10 lines
            print(f"    {line}")
    else:
        print(f"\n  Progress tracker: none yet (no check-ins received)")

    # Recent event log
    log = read_client_file(cs["folder"], "event-log.md")
    if log:
        entries = [l for l in log.strip().splitlines() if l.strip()]
        print(f"\n  Recent events:")
        for entry in entries[-8:]:
            print(f"    {entry}")
    print(f"\n{'='*60}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}\n🚀 Battleship Pipeline — {ts}\n{'='*60}")

    # Manual enrolment: --enrol=<name|email|account>  add --free to skip Stripe
    if any(a.startswith("--enrol=") for a in sys.argv):
        query = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--enrol="))
        free  = "--free" in sys.argv
        state = load_state()
        print("\n🔐 Loading secrets from 1Password...")
        secrets = load_secrets()
        manual_enrol(query, state, secrets, free=free)
        return

    if any(a.startswith("--find=") for a in sys.argv):
        query = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--find="))
        cmd_find(query, load_state())
        return

    if any(a.startswith("--advance=") for a in sys.argv):
        query = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--advance="))
        state = load_state()
        cmd_advance(query, state)
        return

    if any(a.startswith("--status=") for a in sys.argv):
        query = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--status="))
        cmd_status(query, load_state())
        return

    if any(a.startswith("--note=") for a in sys.argv):
        # --note=fred "Did 3 walks this week, knee feeling better"
        query = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--note="))
        note_args = [a for a in sys.argv if not a.startswith("--note=") and not a.startswith("scripts/")]
        note_text = note_args[-1] if len(note_args) > 1 else ""
        if not note_text:
            print("Usage: --note=<client> \"note text\"")
            return
        state = load_state()
        acct, cs = find_client(query, state)
        if not cs:
            print(f"❌ No client found matching '{query}'")
            return
        log_event(cs["folder"], f"[COACH NOTE] {note_text}")
        save_state(state)
        print(f"✅ Note added to {cs['name']}'s event log")
        return

    state = load_state()

    print("\n🔐 Loading secrets from 1Password...")
    secrets = load_secrets()
    print("✅ Secrets loaded.")

    # 1. New intakes (Tally webhook queue)
    print("\n📥 Checking for new intake responses...")
    process_tally_queue(secrets, state)

    # 2. Stripe payment check
    print("\n💳 Checking Stripe for new payments...")
    check_stripe_payments(state, secrets)

    # 3. Weekly check-in requests (Sundays only)
    print("\n📅 Weekly check-in requests (Sundays)...")
    send_weekly_checkin_requests(state, secrets)

    # 4. Process check-in responses
    print("\n📋 Processing check-in responses...")
    process_checkin_responses(state, secrets)

    # 5. Inbound email replies (coach@ and support@)
    print("\n📬 Processing inbound emails...")
    process_inbound_emails(state, secrets)

    # 6. Education drips
    print("\n📚 Education drip schedule...")
    send_education_drips(state, secrets)

    # 7. Week 12 personal close
    print("\n🎓 Week 12 close...")
    send_week12_close(state, secrets)

    # Save state
    save_state(state)

    print(f"\n{'='*60}")
    print(f"✅ Pipeline complete — {len(state['clients'])} client(s) in system")
    for acct, cs in state["clients"].items():
        print(f"   • {acct}  {cs['name']:20s}  {cs['status']:12s}  week {cs.get('current_week', 0)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
