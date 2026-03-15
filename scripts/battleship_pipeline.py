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
    # One lesson per week — strongest signal for that stage of the programme.
    # Dropped lessons (key-to-success, balanced-plate, closing-the-gap, hacking-consistency,
    # whole-foods-reference, gym-terminology, workout-prep, how-much-weight) remain in the vault
    # for Claude to reference in check-in responses or diagnosis emails.
    1:  [("edu_sleep",       "Week 1 bonus: sleep — the easiest win in the programme",        "education-lessons/sleep/sleep-for-fat-loss.md")],
    2:  [("edu_zone2",       "Why slow walking beats hard running — the science",              "education-lessons/exercises/zone2-walking.md")],
    3:  [("edu_8020",        "The 80/20 rule of nutrition",                                    "education-lessons/nutrition/80-20-rule.md")],
    4:  [("edu_fatloss_1",   "How to actually lose fat: getting started",                      "education-lessons/fat-loss/getting-started.md")],
    5:  [("edu_fatloss_2",   "How to actually lose fat: awareness",                            "education-lessons/fat-loss/awareness.md"),
         ("edu_mfp",        "Your calorie tracking tool: MyFitnessPal — simple setup guide",  "education-lessons/Myfitnesspal/myfitnesspal-guide.md")],
    6:  [("edu_training_1",  "Time to add weights — here's what your training looks like",     "education-lessons/training/workout-overview.md")],
    7:  [("edu_gymtim",      "Gymtimidation — and why it ends at session three",               "education-lessons/training/gymtimidation.md")],
    # Week 8: warmup drip + AI-generated challenge email (challenge sent separately)
    8:  [("edu_warmup",      "The warm-up you should never skip (especially over 40)",         "education-lessons/training/warm-ups.md"),
         ("edu_challenge",   "Week 8: What's your challenge?",                                 "education-lessons/training/confirmation-challenge.md")],
    # Week 9: insulin / fasting — the mid-programme strategy unlock for visceral fat
    9:  [("edu_fasting",     "Why fasting is the fastest way to burn dangerous belly fat",     "education-lessons/fasting/jamnadas-fasting-visceral-fat.md")],
    10: [("edu_fatloss_t",   "Why lifting beats cardio for body composition",                  "education-lessons/training/training-for-fat-loss.md")],
    11: [("edu_bws",         "The Battleship training method — and why boring works",          "education-lessons/training/bws-method.md")],
    12: [("edu_arms",        "What about arms? Why the basics come first",                     "education-lessons/training/arms-and-basics.md")],
}


# ── Programme library ─────────────────────────────────────────────────────────

PROGRAMS_DIR = VAULT_ROOT / "11-week-programs"

PROGRAM_FILES = {
    "beginner_bodyweight": "11-week-beginner-bodyweight-strength-training-program.md",
    "bodyweight_full":     "11-week-bodyweight-full-body-program.md",
    "bodyweight_hiit":     "11-week bodyweight HIIT (high-intensity-interval-training)-program.md",
    "resistance_bands":    "11-week-resistance-bands-full-body.md",
    "dumbbell_full_body":  "11-week-dumbbell-full-body-program.md",
    "home_complete":       "11-week-home-complete-program.md",
    "gym_beginner":        "11-week-gym-beginner-machines.md",
    "gym_intermediate":    "11-week-gym-intermediate-ppl.md",
}

PROGRAM_LABELS = {
    "beginner_bodyweight": "Beginner Bodyweight Strength",
    "bodyweight_full":     "Bodyweight Full-Body",
    "bodyweight_hiit":     "Bodyweight HIIT",
    "resistance_bands":    "Resistance Bands Full-Body",
    "dumbbell_full_body":  "Dumbbell Full-Body",
    "home_complete":       "Home Complete (Dumbbells + Bands + Pull-Up Bar)",
    "gym_beginner":        "Gym Beginner (Machines)",
    "gym_intermediate":    "Gym Intermediate (Push / Pull / Legs)",
}

# track → {week: nudge_text}  — included at end of coach message
UPGRADE_NUDGES = {
    "beginner_bodyweight": {
        4: "One thing that would upgrade your programme right now: a resistance band (£8–15 online). "
           "It unlocks pulling movements bodyweight simply can't do — and your programme switches tracks automatically. "
           "If you get one before your next check-in, just mention it.",
        7: "You're ready for more resistance. Resistance bands or a pair of light dumbbells would unlock the next stage. Worth it.",
    },
    "bodyweight_full": {
        4: "You're nailing the bodyweight work. A pair of fixed dumbbells — even a 10kg and 15kg from Decathlon (£25–35 total) — "
           "would let us load the movements you've built and accelerate fat loss significantly. "
           "Get them before next check-in and your programme upgrades automatically.",
        6: "If a gym is at all accessible, now is the time. You've built the base — a barbell and cables from Week 7 would be a serious unlock. "
           "Most gyms are £20–35/month. Just mention it in your check-in if you're open to it.",
    },
    "bodyweight_hiit": {
        4: "HIIT conditions your engine well. To start building more muscle alongside the fat loss — "
           "which is what really changes body composition long-term — a pair of dumbbells is the next step. "
           "Bodyweight can only provide so much resistance. Get them before next check-in and I'll switch your programme.",
    },
    "resistance_bands": {
        4: "The bands are working. A pair of dumbbells from here — even a fixed 10kg and 15kg set — would let us load "
           "squats, rows, and presses with real weight. £25–35 from Decathlon. "
           "Mention it in your next check-in and your programme upgrades.",
    },
    "dumbbell_full_body": {
        6: "You've been consistent and the dumbbells are working. If a gym is viable — even a budget one at £20–25/month — "
           "joining before Week 7 unlocks a barbell, cables, and machines. That means heavier squats, real bench press, "
           "and a Push/Pull/Legs split. A significant step up. Worth considering.",
    },
    "home_complete": {
        6: "Your home programme has been solid. The one thing it genuinely can't replicate is a barbell and heavy cables. "
           "A gym from Week 7 would move you to Push/Pull/Legs — the format that builds the most muscle per session. "
           "If you join before your next check-in I'll switch your programme immediately.",
    },
}

# Equipment signals in check-in text that indicate a track upgrade
UPGRADE_SIGNALS: dict[str, tuple[list[str], str]] = {
    # current_track: (signal_phrases, new_track)
    "beginner_bodyweight": (["got bands", "bought bands", "resistance band", "got dumbbells",
                              "bought dumbbells", "got weights", "ordered weights"], "resistance_bands"),
    "bodyweight_full":     (["got dumbbells", "bought dumbbells", "got weights", "ordered weights",
                              "picked up weights", "joined gym", "started gym", "gym membership"], "dumbbell_full_body"),
    "bodyweight_hiit":     (["got dumbbells", "bought dumbbells", "got weights",
                              "joined gym", "started gym", "gym membership"], "dumbbell_full_body"),
    "resistance_bands":    (["got dumbbells", "bought dumbbells", "got weights",
                              "ordered dumbbells", "picked up weights"], "dumbbell_full_body"),
    "dumbbell_full_body":  (["joined gym", "started gym", "gym membership", "signed up to gym",
                              "signed up for gym", "got a gym"], "gym_beginner"),
    "home_complete":       (["joined gym", "started gym", "gym membership",
                              "signed up to gym", "signed up for gym"], "gym_beginner"),
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
        "stripe":             "STRIPE_KEY",
        "stripe_phase2_link": "STRIPE_PHASE2_LINK",
        "fb_ad_account_id":   "FB_AD_ACCOUNT_ID",
        "fb_user_token":      "FB_USER_TOKEN",
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
        value = field.get("value")
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            # Multiple choice — values are option UUIDs; resolve via options array
            options = {o["id"]: o["text"] for o in field.get("options", []) if "id" in o}
            resolved = [options.get(v, v) for v in value]
            text = ", ".join(resolved)
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
{{"main_goal": "...", "constraints": [...], "risk_flags": {{"sleep": "...", "stress": "...", "injuries": [...], "bp": "..."}}, "equipment": [...], "sessions_per_week": 3, "level": "restart", "weight_lbs": 0, "height_inches": 0, "overweight_level": "significant", "success_metrics": [{{"metric": "weight", "how": "weekly, same day, post-toilet", "unit": "kg or lbs"}}, {{"metric": "energy", "how": "self-rate 1-10 each morning", "unit": "1-10"}}]}}

Notes for AGENT_TAGS_JSON:
- weight_lbs: their current weight in lbs (convert from kg/stone if needed). 0 if not stated.
- height_inches: their height in inches (convert from cm/ft if needed). 0 if not stated.
- overweight_level: "significant" if they have a lot to lose (visibly overweight, 2+ stone, BMI likely 30+) or "moderate" if they just want to lose a bit or tone up."""

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

## Your Personal Metrics
[Assign 2–4 metrics ONLY. Choose based on their primary goal and intake answers.
Do NOT default to weight/waist for everyone — match metrics to what they actually care about.

Goal: fat loss → weight (weekly), waist (fortnightly), energy 1–10
Goal: strength/muscle → key lift weight or reps, energy 1–10, optional measurements
Goal: fitness/VO2/cardio → resting heart rate, walking pace on fixed route, VO2 max if Apple Watch, perceived exertion
Goal: blood pressure → BP reading (weekly), weight, sleep quality 1–10
Goal: feel better generally → energy 1–10, sleep 1–10, mood 1–10, one qualitative win

For each metric: one sentence on what it is, how to measure it, and why it's the right number for them.
No more than 4 metrics. Always include at least one qualitative measure.]

Markdown only. No preamble. Under 1000 words total.
"""

CHECKIN_PROMPT = """\
You are the Check-in Agent for Battleship – Midlife Fitness Reset.
Read this client's weekly check-in data and produce two things:

1. An updated progress tracker (filled from the template structure below)
2. A warm British coach message (150–250 words)

CLIENT: {name}
WEEK: {week}
MAIN GOAL: {main_goal}

THIS CLIENT'S PERSONAL METRICS:
{success_metrics}

WEEKLY LOG:
{log_text}

PREVIOUS TRACKER STATE:
{tracker_text}

NEXT WEEK'S PLAN — always close your coach message with these specific targets:
{next_week_plan}

IMPORTANT: Reference this client's personal metrics specifically — not generic targets.
If their goal is fitness/VO2, don't harp on weight. If their goal is fat loss, don't
ignore the scales. Connect every observation back to what THEY said they care about.

WAIST TRACKING: if a waist measurement appears in the log, always include it in the
tracker. If the waist is dropping while the scale is flat — explicitly celebrate this.
Waist loss IS fat loss. This is often the real metric for visceral fat reduction.

PROGRESS TRACKER TEMPLATE STRUCTURE:
- Header: Client Name, Start Date, Current Week, Age, Main Goal, Personal Metrics
- Current Progress: their specific metrics with changes vs baseline
- Non-Scale Wins: qualitative improvements
- Battleship Agent Notes: consistency rating, biggest win, one correction, trajectory

COACH MESSAGE RULES:
- Praise specific wins first — use their actual numbers, name their metric
- One correction only — gentle, non-shaming, actionable
- Connect progress to their stated goal — make them feel it's working for THEM
- Always close with next week's specific targets from the plan above: exact step count,
  push-up sets/reps, and strength session details if applicable. Not vague — actual numbers.
- Warm British tone. No hype. 150–250 words.

Output format:
[TRACKER]
...full updated tracker markdown...
[/TRACKER]
[COACH_MESSAGE]
...coach message only...
[/COACH_MESSAGE]
"""

# ── Win detection ─────────────────────────────────────────────────────────────

WIN_SIGNALS = [
    (r"new.*(?:best|record|max|pb)", "personal best"),
    (r"(?:lifted|pressed|squatted|deadlifted).*(?:first time|never before)", "first lift"),
    (r"(?:ran|walked|hit)\s+[\d,]+\s*steps.*(?:most|ever|best)", "step record"),
    (r"lost\s+[\d.]+\s*(?:kg|lbs|pounds|stone)", "weight drop"),
    (r"waist.*(?:down|smaller|lost|dropped)", "waist drop"),
    (r"(?:first time|never.*before).*(?:press|push.up|pull.up|squat|deadlift)", "first lift"),
]

WIN_PROMPT = """\
You are Will Barratt, coach at Battleship – Midlife Fitness Reset.

A client just submitted their check-in and has hit a win. Write a short celebratory email
(3–4 sentences, no bullet points). Warm and genuine. Reference the specific win. End with
one sentence about what this means for where they're headed.

Client name: {name}
Week: {week}
Win type: {win_type}
Context from their check-in: {context}

Reply with the email body only. Sign off as Will."""

def _detect_wins(parsed: dict, tracker_text: str) -> list[str]:
    combined = (parsed.get("raw_text", "") + " " + tracker_text).lower()
    return [label for pattern, label in WIN_SIGNALS if re.search(pattern, combined)]


# ── Photo prompt schedule ──────────────────────────────────────────────────────

PHOTO_WEEKS = {4: "week4", 8: "week8", 12: "final"}

PHOTO_PROMPT_FILES = {
    4:  "education-lessons/prompts/progress-photo-week4.md",
    8:  "education-lessons/prompts/progress-photo-week8.md",
    12: "education-lessons/prompts/progress-photo-week12.md",
}


# ── Phase 2 email template ─────────────────────────────────────────────────────

PHASE2_EMAIL_BODY = """\
Hi {name},

Good to hear from you — and yes, let's do it.

Phase 2 is £79/month. Weekly check-ins continue, plan adjusts monthly, strength tracked week to week. No minimum term — cancel whenever you want.

Here's the link to set up the payment:

{stripe_link}

Once that's done, reply and I'll confirm you're set up. Everything else continues as normal from next week.

— Will
"""


# ── Adaptive plan — walking/habit targets only, built from Week 1 check-in ────
# Strength training is delivered weekly from the assigned programme track file.

ADAPTIVE_PLAN_PROMPT = """\
You are the Walking & Habits Coach for Battleship – Midlife Fitness Reset.
Build a progressive walking and habit plan for {name} covering Weeks 2–12.
Strength sessions are handled separately — your job is walk targets, push-up challenge, and habit focus only.

INTAKE PROFILE:
Name: {name}, Age: {age}
Goal: {goal}
Constraints: {constraints}
Injuries: {injuries}
Available days: {available_days}

WEEK 1 ACTUAL CHECK-IN DATA:
{week1_data}

RULES:
1. Walking: extract their ACTUAL average step count from the check-in. Start from that number.
   Increase ~20% per week. Target 10,000 steps/day by Week 4–5. State exact steps/day each week.
2. Push-up challenge: 3 × max reps every day — starts Week 2. Build each week.
   When they hit 3×15: move to close-grip or feet-elevated.
3. Habit focus: one per week — nutrition or behaviour. Progress logically
   (e.g. Week 2: log food, Week 3: hit protein target, Week 4: cut late eating).
4. If a target was missed based on check-in: hold steady, note it — do NOT advance.
5. For shoulder/rotator cuff injuries: push-ups are fine if pain-free; note the modification.

FORMAT — use exactly this structure for each week:
## Week N — [one-word theme]
**Walk:** X,XXX steps/day
**Push-up challenge:** 3 × N reps
**Habit:** [one target]
**Coach note:** [one sentence]

Output Weeks 2–12 only. No preamble. Under 600 words.
"""

TRACK_UPGRADE_PROMPT = """\
You are Will Barratt, coach at Battleship – Midlife Fitness Reset.

{name} has just upgraded their training programme.
Previous track: {old_label}
New track: {new_label}

Their first session this week (Week {week}):
{week_session}

Write a short email (100–130 words) that:
1. Makes the upgrade feel like a milestone — one sentence of genuine acknowledgement
2. Tells them exactly what changes: the new session structure in plain English
3. Gives them their Week {week} session in clear, actionable terms
4. Closes with one line of energy — not hype, just forward momentum

Sign off as Will. No bullet points. Output email body only.
"""

GYM_PIVOT_PROMPT = """\
You are Will Barratt, coach at Battleship – Midlife Fitness Reset.

{name} (Week {week}) was on the gym track but their check-in doesn't suggest they've been.

Their check-in:
{checkin_data}

Equipment they have at home: {equipment}

Write a coaching email (150–180 words) that:
1. Doesn't make a big deal of it — one sentence, matter-of-fact
2. Gives them exactly what to do this week at home: 2 supersets using their available
   equipment, specific exercises, sets × reps
3. Leaves the door open — if they join in the next week or two, just reply and we'll switch back
4. Keeps the energy up — different path, not backwards

Sign off as Will. No bullet points in the body. Output email body only.
"""

WEEK12_PROMPT = """\
You are William George BattleShip Barratt, writing a personal end-of-programme message to {name}.

This is the final email of their 12-week Battleship programme. It should feel like a letter from a coach who genuinely knows them — not a template, not a form letter.

CLIENT INTAKE SUMMARY:
{intake_summary}

PROGRESS TRACKER (12 weeks of check-in data):
{tracker_text}

CONFIRMATION CHALLENGE (what they said they wanted to do — from Week 8 email reply):
{challenge_goal}

WRITE A PERSONAL CLOSING MESSAGE that:
1. Opens by naming something specific about THEIR journey — a real moment, a real struggle, a real win from their tracker. Not generic.
2. Acknowledges what they came in with (their original problem from intake) vs where they are now.
3. Is honest: 12 weeks is a foundation, not a finish line. Real transformation — the kind that lasts — takes 18–24 months. The men who look and feel genuinely different at 50 vs 45 are the ones who kept going.
4. If they stated a confirmation challenge (see above), name it specifically and tell them you can train them for it. Build the bridge from where they are now to that goal. Make it feel inevitable, not impossible.
   If they didn't state a challenge, prompt the question: "What would have seemed completely impossible the day you filled in that form? That's what Phase 2 is for."
5. Makes the Phase 2 offer clearly and simply: £79/month, no minimum term, weekly check-ins continue, strength progression tracked week to week, plan adjusted monthly toward their event, race day prep, post-event debrief. Frame it as: "You've built the base. Now pick something that matters to you and we'll train for it."
6. Closes personally. Not "the Battleship team". You. Will.

TONE: Warm, direct, British. No hype. No exclamation marks. Reads like a letter, not a marketing email.
LENGTH: 350–500 words.
OUTPUT: The message only. No subject line. No preamble.
"""

CHALLENGE_PROMPT = """\
You are Will Barratt, writing a short personal email to {name} at Week 8 of their Battleship programme.

The purpose of this email is to ask them one question: what challenge do they want to work toward next?

CLIENT STARTING POINT:
{intake_summary}

PROGRESS TRACKER SO FAR (8 weeks):
{tracker_text}

YOUR JOB:
1. Open with one sentence that acknowledges something REAL about their progress — specific to their tracker,
   not generic. Reference an actual number, change, or observation.

2. Briefly set up the idea: the men who keep going are motivated by something they want to prove to
   themselves. The question stops being "can I do this?" and starts being "what do I want to do with it?"

3. Give them a SHORT personalised list of 4–6 challenge ideas, CALIBRATED to where they actually are.
   - If they started very unfit or are still significantly overweight: lead with accessible challenges
     (Park Run, open water swim, weighted walk, 30-mile cycling day). Don't suggest marathons.
   - If they've made strong progress and look capable: include mid-tier challenges (10km run,
     sprint triathlon, half marathon walk/run, 100-mile cycling week).
   - If they're motoring and came in already somewhat active: include aspirational options
     (Olympic triathlon, London to Brighton, multi-day hiking, full marathon).
   - Always include at least one that feels genuinely ambitious for them specifically — the one that
     makes them think "not sure I could do that" — because that's the one that sticks.
   - Always include at least one that is clearly doable within 6 months so there's an easy entry point.
   - Name each challenge concisely on its own line. One-sentence description of what it involves.

4. Ask the question directly:
   "If you could do something in the next 12 months that would have seemed completely impossible
    the day you filled in that form — what would it be? Reply to this email. One line is enough."

5. Close with 1–2 lines. Warm, not soppy. Sign off as Will.

TONE: Warm, direct, British. Short paragraphs. No hype. No exclamation marks.
LENGTH: 200–300 words.
OUTPUT: Email body only. No subject line. No preamble.
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


def render_internal_email(title: str, subtitle: str, sections: list[dict]) -> str:
    """
    Render a styled internal email (for Will) using internal_email.html.
    sections: list of dicts with keys:
      - heading (optional)
      - body: HTML string
      - dark: bool (dark background, default False)
      - accent: bool (red accent bar, default False)
    """
    bg_light = "#ffffff"
    bg_dark  = "#f8f6f1"
    html_sections = []
    for i, sec in enumerate(sections):
        bg = "#1a1a1a" if sec.get("dark") else (bg_dark if i % 2 == 0 else bg_light)
        text_color = "#cccccc" if sec.get("dark") else "#2c2c2c"
        border = "border-top:3px solid #c41e3a;" if sec.get("accent") else "border-top:1px solid #e8e3da;"
        heading_html = ""
        if sec.get("heading"):
            hc = "#ffffff" if sec.get("dark") else "#0a0a0a"
            heading_html = f'<p style="margin:0 0 14px;font-family:Georgia,serif;font-size:17px;color:{hc};font-weight:normal;padding-bottom:10px;border-bottom:1px solid {"#333" if sec.get("dark") else "#e8e3da"};">{sec["heading"]}</p>'
        body_html = sec.get("body", "")
        html_sections.append(
            f'<tr><td style="padding:28px 44px;background-color:{bg};{border}">'
            f'{heading_html}'
            f'<div style="font-size:14px;line-height:1.7;color:{text_color};">{body_html}</div>'
            f'</td></tr>'
        )
    return render_template(
        TEMPLATES_DIR / "internal_email.html",
        title=title,
        subtitle=subtitle,
        sections="\n".join(html_sections),
        date=datetime.now().strftime("%d %b %Y"),
    )

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
    msg["From"]     = f"Will @ Battleship <{secrets['smtp_user']}>"
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


def email_onboarding(name: str, notion_url: str = None, tracker_url: str = None) -> tuple[str, str, str]:
    subj = f"You're in — welcome to Battleship, {name}"

    # Plain text fallback
    portal = f"\n→ Your programme page: {notion_url}\n" if notion_url else ""
    tracker_line = f"\n→ Your workout tracker: {tracker_url}\n" if tracker_url else ""
    plain = f"Hi {name},\n\nWelcome aboard.{portal}{tracker_line}\n\nOne thing to do today: a 30-minute walk. That's Week 1.\n\nReply with: weight, waist, energy score, steps yesterday.\n\n— {COACH_NAME}"

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

    # Tracker section
    if tracker_url:
        tracker_section = f"""<tr>
      <td bgcolor="#0a0a0a" style="padding:20px 44px;background-color:#0a0a0a;border-top:4px solid #c41e3a;text-align:center;">
        <p style="margin:0 0 8px;font-size:11px;color:#666666;text-transform:uppercase;letter-spacing:2px;font-family:Arial,sans-serif;">Your Workout Tracker</p>
        <a href="{tracker_url}" style="font-family:Arial,sans-serif;font-size:16px;color:#c41e3a;text-decoration:none;font-weight:bold;">Open your tracker &rarr;</a>
        <p style="margin:10px 0 0;font-size:13px;color:#666666;font-family:Arial,sans-serif;">Tap the link &rarr; Share &rarr; Add to Home Screen in Safari.<br>Your exercises, sets, and weights — all in one place.</p>
      </td>
    </tr>"""
    else:
        tracker_section = ""

    html = render_template(
        TEMPLATES_DIR / "onboarding_email.html",
        name=name,
        portal_section=portal_section,
        tracker_section=tracker_section,
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
    philosophy = ""
    philosophy_file = VAULT_ROOT / "coaching-philosophy.md"
    if philosophy_file.exists():
        philosophy = f"\n\nCOACHING PHILOSOPHY & EDGE CASE GUIDELINES:\n{philosophy_file.read_text()}\n"
    prompt = DIAGNOSIS_PROMPT.format(intake_text=client["raw_text"], name=client["name"]) + philosophy
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

    # Extract and store personal success metrics from tags
    cs["goal"]            = tags.get("main_goal", "general health improvement")
    cs["success_metrics"] = tags.get("success_metrics", [])

    save_client_file(folder, "progress-tracker.md",
        f"# Progress Tracker — {cs['name']}\nAccount: {account_no}\n\n*Baseline filled from first check-in.*\n")
    log_event(folder, "12-week plan generated by Claude")

    # Create Notion client portal
    notion_url = create_notion_client_portal(folder, cs, secrets)
    cs["notion_page_id"] = notion_url.split("-")[-1] if notion_url else None
    cs["notion_url"]     = notion_url

    if cs["email"]:
        tracker_url = f"https://webhook.battleshipreset.com/tracker/{account_no}"
        subj5, plain5, html5 = email_onboarding(cs["name"], notion_url, tracker_url)
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

        # Don't send first check-in until at least 5 days after enrolment
        enrolled = datetime.fromisoformat(cs["enrolled_date"]).replace(tzinfo=timezone.utc)
        if (today - enrolled).days < 5:
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


# ── Programme library helpers ─────────────────────────────────────────────────

def _parse_table_lines(lines: list) -> tuple:
    """Parse raw markdown table lines → (headers, list-of-row-dicts)."""
    if len(lines) < 3:
        return [], []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:          # skip the --- separator
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= len(headers):
            rows.append(dict(zip(headers, cells[:len(headers)])))
    return headers, rows


def _parse_md_tables(text: str) -> list:
    """Return all tables in a markdown file as (label, headers, rows) tuples.
    Label is taken from the nearest preceding heading or bold-text line."""
    results = []
    lines   = text.splitlines()
    label   = "Programme"
    buf     = []
    in_tbl  = False

    for line in lines:
        s = line.strip()
        # Capture section headings and bold tracker labels as table labels
        if s.startswith("#"):
            if in_tbl and buf:
                hdrs, rows = _parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
                buf, in_tbl = [], False
            label = s.lstrip("#").strip()
        elif s.startswith("**") and any(w in s for w in ("Tracker", "Day", "Session", "Programme")):
            if in_tbl and buf:
                hdrs, rows = _parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
                buf, in_tbl = [], False
            label = s.strip("*").strip()
        # Table lines
        if s.startswith("|"):
            in_tbl = True
            buf.append(s)
        elif in_tbl:
            if buf:
                hdrs, rows = _parse_table_lines(buf)
                if hdrs and rows:
                    results.append((label, hdrs, rows))
            buf, in_tbl = [], False

    if in_tbl and buf:
        hdrs, rows = _parse_table_lines(buf)
        if hdrs and rows:
            results.append((label, hdrs, rows))

    return results


def _week_row(rows: list, week: int) -> dict:
    """Find the row for a specific week number in a parsed table."""
    for row in rows:
        val = row.get("Week", row.get(list(row.keys())[0], ""))
        try:
            if int(str(val).strip()) == week:
                return row
        except (ValueError, TypeError):
            continue
    return {}


_META_COLS = {
    "Week", "Sets × Reps", "Sets × Goal", "Sets", "Frequency",
    "Circuit Structure (per round)", "Work / Rest per Exercise",
    "Rounds per Session", "Total Time (approx.)",
    "Notes / Weight Used", "Notes / How It Felt", "Notes / Modifications",
    "Notes / Variation Used", "Notes / Weight", "Notes",
    "Key Progression / Focus", "Notes / Modifications",
}


def _format_table_row(label: str, headers: list, row: dict, multi: bool) -> str:
    """Format one table row as readable plain text for an email."""
    lines = []
    if multi:
        lines.append(f"{label}:")

    # Volume line
    for k in ("Sets × Reps", "Sets × Goal", "Sets"):
        if row.get(k):
            lines.append(f"  Volume: {row[k]}")
            break

    # HIIT-specific columns
    for k in ("Circuit Structure (per round)", "Work / Rest per Exercise",
              "Rounds per Session", "Total Time (approx.)"):
        if row.get(k) and row[k] not in ("", "—"):
            lines.append(f"  {k}: {row[k]}")

    # Exercise columns
    for k, v in row.items():
        if k not in _META_COLS and v and v.strip() not in ("", "—", "-"):
            lines.append(f"  • {k}: {v}")

    # Notes / progression cue
    for k in ("Key Progression / Focus", "Notes / Weight Used", "Notes / How It Felt",
              "Notes / Modifications", "Notes / Variation Used", "Notes"):
        if row.get(k) and row[k].strip() not in ("", "—"):
            lines.append(f"  → {row[k]}")
            break

    return "\n".join(lines)


def extract_program_week(track: str, week: int) -> str:
    """Return this week's session(s) from the programme file as formatted plain text.
    Returns empty string if track/file/week not found."""
    filename = PROGRAM_FILES.get(track, "")
    if not filename:
        return ""
    filepath = PROGRAMS_DIR / filename
    if not filepath.exists():
        return ""

    week    = max(1, min(week, 11))   # programmes are 11 weeks; week 12 = close email
    tables  = _parse_md_tables(filepath.read_text())
    if not tables:
        return ""

    multi   = len(tables) > 1
    parts   = []
    for label, headers, rows in tables:
        row = _week_row(rows, week)
        if row:
            parts.append(_format_table_row(label, headers, row, multi))

    return "\n\n".join(parts)


def select_program_track(tags: dict, week1_data: str = "") -> str:
    """Select the best programme track from intake tags + Week 1 check-in signals."""
    equip      = " ".join(tags.get("equipment", [])).lower()
    w1         = week1_data.lower()
    constraints = " ".join(tags.get("constraints", [])).lower()

    # Gym access
    if any(w in equip for w in ("gym", "workplace gym", "office gym", "pool")):
        return "gym_beginner"

    # Full home kit
    has_db    = any(w in equip for w in ("dumbbell", "home weight", "weight", "bench"))
    has_bands = "band" in equip
    has_bar   = "pull" in equip
    if has_db and (has_bands or has_bar):
        return "home_complete"
    if has_db:
        return "dumbbell_full_body"
    if has_bands:
        return "resistance_bands"

    # Bodyweight — pick tier from fitness signals
    very_unfit = any(w in w1 for w in (
        "exhausted", "struggled", "couldn't finish", "very hard",
        "out of breath", "knackered", "never exercise"
    )) or any(w in constraints for w in ("mostly sitting", "sedentary", "never"))

    if very_unfit:
        return "beginner_bodyweight"
    if any(w in w1 for w in ("hiit", "interval training", "hiit class")):
        return "bodyweight_hiit"
    return "bodyweight_full"


def detect_equipment_upgrade(parsed: dict, current_track: str) -> str:
    """Scan check-in text for equipment/gym upgrade signals. Returns new track or empty string."""
    haystack = " ".join([
        parsed.get("raw_text", ""),
        parsed.get("win", ""),
        parsed.get("questions", ""),
    ]).lower()

    # Gym keywords — word-level, not phrase-level
    gym_words    = ("joined the gym", "joined a gym", "gym membership", "started at the gym",
                    "started the gym", "signed up to the gym", "signed up for the gym",
                    "going to the gym", "been to the gym", "at the gym", "my gym")
    db_words     = ("dumbbell", "dumbbells", "a pair of weights", "some weights",
                    "home weights", "bought weights", "got weights")
    band_words   = ("resistance band", "bands", "bought bands", "got bands")
    pullup_words = ("pull-up bar", "pullup bar", "pull up bar")

    has_gym   = any(w in haystack for w in gym_words)
    has_db    = any(w in haystack for w in db_words)
    has_bands = any(w in haystack for w in band_words)
    has_bar   = any(w in haystack for w in pullup_words)

    # Confirm acquisition verb nearby (bought, got, ordered, picked up, joined)
    acquisition = any(w in haystack for w in ("bought", "got ", "ordered", "picked up",
                                               "joined", "signed up", "purchased", "found"))

    if has_gym and acquisition:
        return "gym_beginner"

    bw_tracks = ("bodyweight_full", "bodyweight_hiit", "beginner_bodyweight")
    if current_track in bw_tracks:
        if has_db and acquisition:
            return "dumbbell_full_body"
        if has_bands and acquisition:
            return "resistance_bands"

    if current_track == "resistance_bands":
        if has_db and acquisition:
            return "dumbbell_full_body"

    if current_track in ("dumbbell_full_body", "home_complete"):
        if has_gym and acquisition:
            return "gym_beginner"

    # Check existing UPGRADE_SIGNALS as fallback for exact phrases
    signals, new_track = UPGRADE_SIGNALS.get(current_track, ([], ""))
    for signal in signals:
        if signal in haystack:
            return new_track

    return ""


def get_upgrade_nudge(track: str, week: int) -> str:
    """Return upgrade nudge text for this track/week, or empty string."""
    return UPGRADE_NUDGES.get(track, {}).get(week, "")


def send_track_upgrade_email(cs: dict, new_track: str, secrets: dict):
    """Send a programme-upgrade email and update client state."""
    old_label = PROGRAM_LABELS.get(cs.get("program_track", ""), "previous programme")
    new_label = PROGRAM_LABELS.get(new_track, new_track)
    week      = cs.get("current_week", 1) - 1
    session   = extract_program_week(new_track, week) or "Sessions start this week."

    prompt = TRACK_UPGRADE_PROMPT.format(
        name        = cs["name"],
        old_label   = old_label,
        new_label   = new_label,
        week        = week,
        week_session= session,
    )
    body = call_claude(secrets["anthropic"], prompt, max_tokens=400)
    subj = f"Your programme just upgraded, {cs['name']}"
    send_email(secrets, cs["email"], subj, body)

    cs["program_track"] = new_track
    log_event(cs["folder"], f"Programme upgraded: {old_label} → {new_label} (Week {week})")
    print(f"     ⬆️  Programme upgraded for {cs['name']}: {old_label} → {new_label}")


# ── Adaptive plan helpers ─────────────────────────────────────────────────────

def _extract_week_section(plan_text: str, week: int) -> str:
    """Pull ## Week N block from a plan. Returns empty string if not found."""
    marker      = f"## Week {week}"
    next_marker = f"## Week {week + 1}"
    if marker not in plan_text:
        return ""
    start = plan_text.index(marker)
    end   = plan_text.index(next_marker) if next_marker in plan_text else len(plan_text)
    return plan_text[start:end].strip()


def _generate_adaptive_plan(cs: dict, week1_data: str, secrets: dict):
    """Select programme track + build walking/habit plan from Week 1 check-in data."""
    tags        = cs.get("tags", {})
    constraints = ", ".join(tags.get("constraints", [])) or "none noted"
    injuries    = str(tags.get("risk_flags", {}).get("injuries", [])) or "none"
    avail_days  = ", ".join(tags.get("available_days", [])) or "flexible"

    # Select the programme track from equipment + Week 1 signals
    track = select_program_track(tags, week1_data)
    cs["program_track"]       = track
    cs["adaptive_plan_built"] = True

    # Gym track: set gate flag so we check attendance at Week 3+
    gym_tracks = {"gym_beginner", "gym_intermediate"}
    cs["gym_track"] = "required" if track in gym_tracks else "not_required"

    label = PROGRAM_LABELS.get(track, track)
    print(f"     📋 Programme track selected: {label}")
    log_event(cs["folder"], f"Programme track assigned: {label}")

    # Build the walking + habit plan (strength delivered weekly from programme file)
    prompt = ADAPTIVE_PLAN_PROMPT.format(
        name          = cs["name"],
        age           = tags.get("age", "unknown"),
        goal          = tags.get("main_goal", "general health improvement"),
        constraints   = constraints,
        injuries      = injuries,
        available_days= avail_days,
        week1_data    = week1_data,
    )
    plan_text = call_claude(secrets["anthropic"], prompt, max_tokens=1200)
    save_client_file(cs["folder"], "plan.md", plan_text)
    log_event(cs["folder"], f"Walking/habit plan built from Week 1 data")
    print(f"     ✅ Adaptive plan saved for {cs['name']}")
    return plan_text


def _send_gym_pivot(cs: dict, checkin_data: str, secrets: dict):
    """Send pivot email and switch client to home track."""
    tags      = cs.get("tags", {})
    equipment = ", ".join(tags.get("equipment", [])) or "bodyweight only"
    week      = cs.get("current_week", 1) - 1

    prompt = GYM_PIVOT_PROMPT.format(
        name         = cs["name"],
        week         = week,
        checkin_data = checkin_data[:600],
        equipment    = equipment,
    )
    body = call_claude(secrets["anthropic"], prompt, max_tokens=600)
    subj = f"Quick update on your plan, {cs['name']}"
    send_email(secrets, cs["email"], subj, body)
    cs["gym_track"] = "pivoted"
    log_event(cs["folder"], "Gym pivot email sent — switched to home track")
    print(f"     🏠 Gym pivot sent to {cs['name']}")


def _infer_gym_attendance(parsed: dict) -> bool:
    """Return True if check-in text suggests the client visited a gym this week."""
    haystack = " ".join([
        parsed.get("raw_text", ""),
        parsed.get("workouts", ""),
        parsed.get("win", ""),
    ]).lower()
    gym_signals = ["gym", "joined", "membership", "bench", "cable", "machine",
                   "squat rack", "lat pull", "weights room", "lifted at"]
    return any(s in haystack for s in gym_signals)


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

    # ── Week 1 check-in: build the real adaptive plan ─────────────────────────
    if week == 1 and not cs.get("adaptive_plan_built"):
        print(f"  🏗️  Week 1 data received — building adaptive plan for {cs['name']}...")
        _generate_adaptive_plan(cs, parsed["raw_text"], secrets)

    # ── Equipment / gym upgrade detection ────────────────────────────────────
    current_track = cs.get("program_track", "")
    if current_track:
        new_track = detect_equipment_upgrade(parsed, current_track)
        # Auto-graduate gym_beginner → gym_intermediate after Week 8
        if not new_track and current_track == "gym_beginner" and week >= 8:
            new_track = "gym_intermediate"
        if new_track and new_track != current_track:
            send_track_upgrade_email(cs, new_track, secrets)
            # Upgrade email is supplemental — continue with normal check-in flow
            current_track = new_track

    # ── Gym gate: Week 3+ on gym track, check they've actually been ───────────
    if (week >= 3
            and cs.get("gym_track") == "required"
            and not _infer_gym_attendance(parsed)):
        _send_gym_pivot(cs, parsed["raw_text"], secrets)
        cs["last_checkin_received"] = datetime.now(timezone.utc).isoformat()
        state.setdefault("processed_checkin_ids", []).append(row_id)
        return

    if cs.get("gym_track") == "required" and _infer_gym_attendance(parsed):
        cs["gym_track"] = "confirmed"

    # ── Extract next week's walking/habit plan ────────────────────────────────
    next_week_plan = ""
    if cs.get("folder"):
        plan_text = read_client_file(cs["folder"], "plan.md")
        if plan_text:
            next_week_plan = _extract_week_section(plan_text, week + 1)
    if not next_week_plan:
        next_week_plan = "No walking plan yet — will be built from this week's data."

    # ── Extract next week's strength session from programme file ──────────────
    next_session = ""
    if current_track and week >= 2:
        next_session = extract_program_week(current_track, week + 1)

    # ── Generate coach response ───────────────────────────────────────────────
    existing_tracker = read_client_file(cs["folder"], "progress-tracker.md")
    raw_metrics = cs.get("success_metrics", [])
    metrics_text = "\n".join(
        f"- {m.get('metric','').title()}: {m.get('how','')} ({m.get('unit','')})"
        for m in raw_metrics
    ) if raw_metrics else "- Weight (weekly)\n- Energy 1–10\n- Steps (daily)"

    # Combine walking plan + strength session for the prompt context
    full_next_week = next_week_plan[:600]
    if next_session:
        full_next_week += f"\n\nStrength sessions next week:\n{next_session[:600]}"

    prompt = CHECKIN_PROMPT.format(
        name            = cs["name"],
        week            = week,
        main_goal       = cs.get("goal", cs.get("tags", {}).get("main_goal", "general health improvement")),
        success_metrics = metrics_text,
        log_text        = parsed["raw_text"],
        tracker_text    = existing_tracker[:2000] if existing_tracker else "No previous tracker.",
        next_week_plan  = full_next_week,
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
            notion_url = cs.get("notion_url", "")
            portal_line = f"\n\nYour programme page: {notion_url}" if notion_url else ""

            # Append this week's session block and any upgrade nudge
            session_block = ""
            this_session = extract_program_week(current_track, week) if current_track else ""
            if this_session:
                track_label   = PROGRAM_LABELS.get(current_track, "")
                session_block = f"\n\n---\nYOUR SESSIONS THIS WEEK — Week {week}"
                if track_label:
                    session_block += f" ({track_label})"
                session_block += f"\n\n{this_session}"

            nudge = get_upgrade_nudge(current_track, week) if current_track else ""
            nudge_block = f"\n\n---\n{nudge}" if nudge else ""

            # Progress photo prompt at Weeks 4, 8, 12
            photo_block = ""
            if week in PHOTO_PROMPT_FILES:
                photo_key = f"photo_prompt_{PHOTO_WEEKS[week]}"
                if photo_key not in cs.get("emails_sent", []):
                    photo_path = VAULT_ROOT / PHOTO_PROMPT_FILES[week]
                    if photo_path.exists():
                        photo_block = f"\n\n---\n{photo_path.read_text().strip()}"
                        cs["emails_sent"].append(photo_key)

            # Referral ask at Week 8
            referral_block = ""
            if week == 8 and "referral_ask" not in cs.get("emails_sent", []):
                referral_path = VAULT_ROOT / "education-lessons/referral/week8-referral-ask.md"
                if referral_path.exists():
                    referral_block = f"\n\n---\n{referral_path.read_text().strip()}"
                    cs["emails_sent"].append("referral_ask")

            subj = f"Week {week} review — {cs['name']}"
            body = (f"Hi {cs['name']},\n\n{coach_message}"
                    f"{session_block}{nudge_block}{photo_block}{referral_block}{portal_line}\n\n— {COACH_NAME}")
            send_email(secrets, cs["email"], subj, body)
            log_event(cs["folder"], f"Week {week} coach message sent (track: {current_track})")
            print(f"     ✅ Coach response sent to {cs['name']} (track: {current_track})")

            # Testimonial request at Week 11 — separate short email
            if week == 11 and "testimonial_ask" not in cs.get("emails_sent", []):
                testimonial_path = VAULT_ROOT / "education-lessons/testimonial/week11-testimonial.md"
                if testimonial_path.exists():
                    t_body = testimonial_path.read_text().strip()
                    send_email(secrets, cs["email"], f"One question before we close — {cs['name'].split()[0]}", t_body)
                    cs["emails_sent"].append("testimonial_ask")
                    log_event(cs["folder"], "Week 11 testimonial request sent")
                    print(f"     ⭐ Testimonial request sent to {cs['name']}")

    # Win detection — fire separate celebration email if a win is spotted
    wins = _detect_wins(parsed, tracker_text)
    win_key = f"win_wk{week}"
    if wins and win_key not in cs.get("emails_sent", []):
        win_type = ", ".join(wins)
        win_prompt = WIN_PROMPT.format(
            name=cs["name"],
            week=week,
            win_type=win_type,
            context=parsed.get("raw_text", "")[:500],
        )
        win_body = call_claude(secrets["anthropic"], win_prompt, max_tokens=300)
        send_email(secrets, cs["email"], f"That's a big one, {cs['name'].split()[0]}", win_body)
        cs["emails_sent"].append(win_key)
        log_event(cs["folder"], f"Win celebration email sent (Week {week}): {win_type}")
        print(f"     🏆 Win celebration sent to {cs['name']} ({win_type})")

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
    """Return a personalised calorie target based on body composition.

    Rule (Will's formula):
      - Significantly overweight / lot to lose → weight_lbs × 12
      - Moderate / not really overweight       → weight_lbs × 15
    """
    tags = cs.get("tags", {})
    weight_raw = tags.get("weight_lbs", "") or tags.get("weight", "")

    try:
        lbs = float(str(weight_raw).replace("lbs", "").replace("lb", "").strip())
        if lbs <= 0:
            raise ValueError

        # Try BMI first if height available
        height_raw = tags.get("height_inches", "") or tags.get("height", "")
        multiplier = 12  # default: assume significant if unsure
        try:
            inches = float(str(height_raw).replace("in", "").replace('"', "").strip())
            if inches > 0:
                bmi = (lbs / (inches ** 2)) * 703
                multiplier = 12 if bmi >= 30 else 15
        except (ValueError, TypeError):
            # Fall back to Claude's overweight_level tag
            level = tags.get("overweight_level", "significant").lower()
            multiplier = 12 if level == "significant" else 15

        target = int(lbs * multiplier)
        return f"**Your target: {target} calories/day** (your weight × {multiplier})"
    except (ValueError, TypeError):
        return "**Your target:** use the formula in the lesson — your weight in lbs × 12 if you have a significant amount to lose, or × 15 if you're closer to your goal weight"


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
    # Only fetch unseen emails from the last 7 days — avoids trawling thousands of old unreads
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
    _, data = mail.search(None, f'(UNSEEN SINCE "{since}")')
    uids = data[0].split() if data and data[0] else []
    if not uids:
        print("  📭 No new emails in last 7 days")
        mail.logout()
        return

    print(f"  📬 {len(uids)} unread email(s) (last 7 days)...")
    client = anthropic.Anthropic(api_key=secrets["anthropic"])

    for uid in uids:
        _, msg_data = mail.fetch(uid, "(RFC822)")
        if not msg_data or not isinstance(msg_data[0], tuple):
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, bytes):
            continue
        msg = email.message_from_bytes(raw)

        from_addr  = _decode_header(msg.get("From", ""))
        to_addr    = _decode_header(msg.get("To", "")).lower()
        subject    = _decode_header(msg.get("Subject", ""))
        body       = _get_email_body(msg).strip()

        # Extract sender email from "Name <email>" format
        sender_email = from_addr
        if "<" in from_addr and ">" in from_addr:
            sender_email = from_addr.split("<")[1].rstrip(">").strip().lower()

        # Route: will@ — check for comment approvals, otherwise flag
        if WILL_EMAIL in to_addr:
            if "[COMMENTS]" in subject and sender_email == WILL_EMAIL:
                # Will replied to a comment approval email
                try:
                    from skills.facebook_bot import post_approved_comments
                    post_approved_comments(body, secrets)
                    print(f"  ✅ Comment approval processed")
                except Exception as e:
                    print(f"  ⚠️  Comment approval failed: {e}")
                mail.store(uid, "+FLAGS", "\\Seen")
            else:
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

        # Detect challenge goal reply — store it and send a short acknowledgement
        challenge_keywords = ["what's your challenge", "week 8: what", "confirmation challenge"]
        is_challenge_reply = (
            is_coach and
            not cs.get("challenge_goal") and
            any(kw in subject.lower() for kw in challenge_keywords) and
            len(body) > 3
        )
        if is_challenge_reply:
            cs["challenge_goal"] = body[:500]
            if cs.get("folder"):
                log_event(cs["folder"], f"Challenge goal recorded: {body[:100]}")
            print(f"  🎯 Challenge goal captured for {cs['name']}: {body[:80]}")
            # Send a short personal reply acknowledging it
            ack = (
                f"Got it.\n\n"
                f"We'll keep that in mind as you move into the final weeks. "
                f"By Week 12 we'll talk about what training for that actually looks like.\n\n"
                f"Keep going.\n\n— Will"
            )
            send_email(secrets, sender_email, f"Re: {subject}", ack)
            mail.store(uid, "+FLAGS", "\\Seen")
            if cs.get("folder"):
                log_event(cs["folder"], f"Challenge acknowledgement sent")
            continue

        # Detect Phase 2 sign-up reply — flag for Will to action
        phase2_keywords = ["i'm in", "im in", "sign me up", "phase 2", "continue", "keep going"]
        week12_subject_keywords = ["12 weeks", "what comes next"]
        is_phase2_reply = (
            is_coach and
            cs.get("status") in ("active", "complete") and
            any(kw in body.lower() for kw in phase2_keywords) and
            any(kw in subject.lower() for kw in week12_subject_keywords)
        )
        if is_phase2_reply and not cs.get("phase2_stripe_sent"):
            cs["phase2_requested"] = True
            stripe_p2 = secrets.get("stripe_phase2_link", "")
            if stripe_p2:
                p2_body = PHASE2_EMAIL_BODY.format(
                    name=cs["name"].split()[0],
                    stripe_link=stripe_p2,
                )
                send_email(secrets, sender_email, f"Phase 2 — you're in, {cs['name'].split()[0]}", p2_body)
                cs["phase2_stripe_sent"] = True
                cs["phase2_stripe_sent_at"] = datetime.now(timezone.utc).isoformat()
                if cs.get("folder"):
                    log_event(cs["folder"], f"Phase 2 Stripe link auto-sent")
                print(f"  🚀 Phase 2 Stripe link sent to {cs['name']}")
                mail.store(uid, "+FLAGS", "\\Seen")
                continue
            else:
                if cs.get("folder"):
                    log_event(cs["folder"], f"Phase 2 interest flagged — no STRIPE_PHASE2_LINK set")
                print(f"  🚀 PHASE 2 REQUEST from {cs['name']} — STRIPE_PHASE2_LINK not set, needs manual action")

        # Testimonial capture — detect replies to the Week 11 testimonial ask
        if (is_coach
                and "testimonial_ask" in cs.get("emails_sent", [])
                and not cs.get("testimonial")
                and len(body) > 20):
            testimonial_subjects = ["one question", "before we close", "testimonial"]
            if any(kw in subject.lower() for kw in testimonial_subjects):
                cs["testimonial"] = body[:2000]
                cs["testimonial_received_at"] = datetime.now(timezone.utc).isoformat()
                if cs.get("folder"):
                    log_event(cs["folder"], f"Testimonial received: {body[:80]}")
                print(f"  ⭐ Testimonial captured from {cs['name']}")

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

            # Inject personalised calorie target into fat loss + MFP lessons
            if key in ("edu_fatloss_1", "edu_mfp"):
                calorie_line = _calorie_target(cs)
                if key == "edu_fatloss_1":
                    content = content.replace(
                        "Your number was calculated for you in your diagnosis.",
                        f"Your number was calculated for you in your diagnosis.\n\n{calorie_line}"
                    )
                elif key == "edu_mfp":
                    content = content.replace(
                        "That number is in your plan. Use it.",
                        f"That number is in your plan. Use it.\n\n{calorie_line}"
                    )

            # Challenge email: generate personalised version via Claude
            if key == "edu_challenge":
                tracker_text    = read_client_file(cs["folder"], "progress-tracker.md") if cs.get("folder") else ""
                intake_tags     = cs.get("tags", {})
                intake_summary  = "\n".join(f"{k}: {v}" for k, v in intake_tags.items() if v) or "No intake data."
                challenge_prompt = CHALLENGE_PROMPT.format(
                    name=cs["name"],
                    intake_summary=intake_summary,
                    tracker_text=tracker_text[:2000] if tracker_text else "No tracker data yet.",
                )
                content = call_claude(secrets["anthropic"], challenge_prompt, max_tokens=600)
                # Wrap as plain markdown so the parser below still works
                content = f"# Week 8: What's your challenge?\n\n{content}"

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
                "edu_fasting": "Fasting & Insulin", "edu_arms": "Training",
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

        challenge_goal = cs.get("challenge_goal", "")
        prompt = WEEK12_PROMPT.format(
            name=cs["name"],
            intake_summary=intake_summary or "No intake tags recorded.",
            tracker_text=tracker[:3000] if tracker else "No tracker data — client did not submit check-ins.",
            challenge_goal=challenge_goal or "Not stated — client did not reply to Week 8 challenge email.",
        )
        message = call_claude(secrets["anthropic"], prompt, max_tokens=1200)

        first_name = cs["name"].split()[0]
        subj = f"12 weeks — and what comes next, {first_name}"
        phase2_cta = (
            f"Phase 2 is £79/month — no minimum term, cancel any time.\n\n"
            f"Weekly check-ins continue. Strength tracked week to week. Plan adjusted monthly.\n"
            f"If you have an event in mind, we build toward it. If you don't yet, we'll find one.\n\n"
            f"Reply to this email with 'I'm in' and I'll get you set up."
        )
        body = (
            f"{message}\n\n"
            f"---\n\n"
            f"{phase2_cta}\n\n"
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


# ── Re-engagement Emails ──────────────────────────────────────────────────────

REENGAGE_GENTLE_PROMPT = """\
You are Will Barratt, coach at Battleship – Midlife Fitness Reset.

A client has gone quiet — they haven't submitted a check-in for {days} days.
Write a short, warm nudge (3–5 sentences). No guilt. No pressure. Acknowledge that life
gets in the way. Make it easy to reply with one word about how they're doing. Sign off as Will.

Client name: {name}
Client week: {week}
Their main goal: {goal}

Reply with the email body only. No subject line."""

REENGAGE_PERSONAL_PROMPT = """\
You are Will Barratt, coach at Battleship – Midlife Fitness Reset.

A client has gone quiet for {days} days — this is a longer silence that warrants a personal note.
Write a genuine, human check-in (4–6 sentences). No blame. Acknowledge they may have had a rough
patch — that's normal and recoverable. Make it clear you noticed, you're not annoyed, and you just
want to know they're ok. One CTA: "just reply with how you're doing." Sign off as Will.

Client name: {name}
Client week: {week}
Their main goal: {goal}

Reply with the email body only. No subject line."""


def send_reengagement_emails(state: dict, secrets: dict):
    """Nudge silent active clients — gentle at 10 days, personal at 17+ days."""
    today = datetime.now(timezone.utc).date()

    for slug, cs in state["clients"].items():
        if cs["status"] != "active" or not cs.get("enrolled_date"):
            continue

        last_checkin = cs.get("last_checkin_received")
        if last_checkin:
            days_silent = (today - datetime.fromisoformat(last_checkin).date()).days
        else:
            # No check-in ever — measure from enrolment
            enrolled = datetime.fromisoformat(cs["enrolled_date"]).date()
            days_silent = (today - enrolled).days

        week = cs.get("current_week", 1)
        first = cs["name"].split()[0]
        goal  = cs.get("goal", cs.get("tags", {}).get("main_goal", "general health"))

        gentle_key  = f"reengage_w{week}"
        personal_key = f"reengage_w{week}_2"

        if 10 <= days_silent < 17 and gentle_key not in cs.get("emails_sent", []):
            prompt = REENGAGE_GENTLE_PROMPT.format(
                name=cs["name"], days=days_silent, week=week, goal=goal
            )
            body = call_claude(secrets["anthropic"], prompt, max_tokens=250)
            send_email(secrets, cs["email"], f"Checking in, {first}", body)
            cs["emails_sent"].append(gentle_key)
            if cs.get("folder"):
                log_event(cs["folder"], f"Re-engagement nudge sent (gentle, {days_silent} days silent)")
            print(f"  💬 Re-engagement nudge sent to {cs['name']} ({days_silent} days silent)")

        elif days_silent >= 17 and personal_key not in cs.get("emails_sent", []):
            prompt = REENGAGE_PERSONAL_PROMPT.format(
                name=cs["name"], days=days_silent, week=week, goal=goal
            )
            body = call_claude(secrets["anthropic"], prompt, max_tokens=300)
            send_email(secrets, cs["email"], f"Just checking you're ok, {first}", body)
            cs["emails_sent"].append(personal_key)
            if cs.get("folder"):
                log_event(cs["folder"], f"Re-engagement personal note sent ({days_silent} days silent)")
            print(f"  🔴 Personal re-engagement sent to {cs['name']} ({days_silent} days silent)")


# ── Weekly Digest to Will ──────────────────────────────────────────────────────

def send_weekly_digest(state: dict, secrets: dict):
    """Send a Monday morning operations digest to will@battleship.me."""
    today = datetime.now(timezone.utc)
    if today.weekday() != 0:  # Monday only
        return

    week_key = today.strftime("%Y-%W")
    if ("digest_" + week_key) in state.get("sent_digests", []):
        return

    active = {k: cs for k, cs in state["clients"].items() if cs["status"] == "active"}
    diagnosed = {k: cs for k, cs in state["clients"].items() if cs["status"] == "diagnosed"}
    complete  = {k: cs for k, cs in state["clients"].items() if cs["status"] == "complete"}

    now_date = today.date()
    rows = []
    flags = []

    for acct, cs in sorted(active.items()):
        last_ci = cs.get("last_checkin_received")
        if last_ci:
            days_silent = (now_date - datetime.fromisoformat(last_ci).date()).days
        else:
            enrolled = datetime.fromisoformat(cs.get("enrolled_date", today.isoformat())).date()
            days_silent = (now_date - enrolled).days

        silent_flag = " ⚠️ SILENT" if days_silent >= 10 else ""
        p2_flag     = " ★ P2" if cs.get("phase2_requested") and not cs.get("phase2_stripe_sent") else ""
        testimonial = " ⭐ TESTIOMINAL" if cs.get("testimonial") and not cs.get("testimonial_used") else ""

        row = (f"  {acct}  {cs['name']:20s}  week {cs.get('current_week', 0):>2d}  "
               f"last check-in: {days_silent:>2d}d ago{silent_flag}{p2_flag}{testimonial}")
        rows.append(row)

        if silent_flag:
            flags.append(f"⚠️  {cs['name']} — {days_silent} days silent (week {cs.get('current_week', 0)})")
        if p2_flag:
            flags.append(f"★  {cs['name']} — Phase 2 interest flagged, no Stripe link sent yet")

    body_lines = [
        f"Battleship — Weekly Digest ({today.strftime('%A %d %B %Y')})",
        "",
        f"Active clients: {len(active)}  |  Diagnosed (awaiting payment): {len(diagnosed)}  |  Complete: {len(complete)}",
        "",
        "─" * 60,
        "ACTIVE CLIENTS",
        "─" * 60,
    ]
    body_lines += rows or ["  (none)"]
    if flags:
        body_lines += ["", "FLAGS NEEDING ATTENTION"]
        body_lines += flags
    if diagnosed:
        body_lines += ["", "AWAITING PAYMENT"]
        for acct, cs in diagnosed.items():
            body_lines.append(f"  {acct}  {cs['name']}  {cs['email']}")
    plain = "\n".join(body_lines)

    # ── HTML version ──────────────────────────────────────────────────────────
    def _row_html(label: str, value: str, highlight: bool = False) -> str:
        color = "#c41e3a" if highlight else "#0a0a0a"
        return (f'<tr>'
                f'<td style="padding:6px 0;font-size:13px;color:#888888;width:160px;">{label}</td>'
                f'<td style="padding:6px 0;font-size:13px;color:{color};font-weight:{"600" if highlight else "normal"};">{value}</td>'
                f'</tr>')

    stats_html = (
        '<table cellpadding="0" cellspacing="0" border="0" width="100%">'
        + _row_html("Active clients", str(len(active)))
        + _row_html("Awaiting payment", str(len(diagnosed)), bool(diagnosed))
        + _row_html("Completed", str(len(complete)))
        + '</table>'
    )

    clients_html = '<table cellpadding="0" cellspacing="0" border="0" width="100%" style="font-size:13px;">'
    clients_html += '<tr style="border-bottom:1px solid #e8e3da;"><th style="text-align:left;padding:6px 8px 6px 0;color:#aaaaaa;font-weight:normal;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Client</th><th style="text-align:left;padding:6px 8px;color:#aaaaaa;font-weight:normal;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Week</th><th style="text-align:left;padding:6px 0;color:#aaaaaa;font-weight:normal;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Last check-in</th></tr>'
    for acct, cs in sorted(active.items()):
        last_ci = cs.get("last_checkin_received")
        if last_ci:
            days_silent = (now_date - datetime.fromisoformat(last_ci).date()).days
        else:
            enrolled = datetime.fromisoformat(cs.get("enrolled_date", today.isoformat())).date()
            days_silent = (now_date - enrolled).days
        silent_badge = ' <span style="background:#c41e3a;color:#fff;font-size:10px;padding:1px 6px;border-radius:3px;">SILENT</span>' if days_silent >= 10 else ""
        p2_badge = ' <span style="background:#0a0a0a;color:#fff;font-size:10px;padding:1px 6px;border-radius:3px;">PHASE 2</span>' if cs.get("phase2_requested") else ""
        clients_html += f'<tr style="border-bottom:1px solid #f0ece4;"><td style="padding:8px 8px 8px 0;color:#0a0a0a;">{cs["name"]}{p2_badge}</td><td style="padding:8px;color:#555;">{cs.get("current_week", 0)}</td><td style="padding:8px 0;color:#555;">{days_silent}d ago{silent_badge}</td></tr>'
    if not active:
        clients_html += '<tr><td colspan="3" style="padding:12px 0;color:#aaaaaa;">No active clients</td></tr>'
    clients_html += '</table>'

    sections = [
        {"heading": "This week at a glance", "body": stats_html, "accent": True},
        {"heading": "Active clients", "body": clients_html},
    ]
    if flags:
        flags_html = "".join(
            f'<p style="margin:0 0 10px;padding:10px 14px;background:#fff8f8;border-left:3px solid #c41e3a;font-size:13px;color:#0a0a0a;">{f}</p>'
            for f in flags
        )
        sections.append({"heading": "Flags needing attention", "body": flags_html, "accent": True})
    if diagnosed:
        diag_html = "".join(
            f'<p style="margin:0 0 8px;font-size:13px;color:#0a0a0a;"><strong>{cs["name"]}</strong> · {cs["email"]} · {acct}</p>'
            for acct, cs in diagnosed.items()
        )
        sections.append({"heading": "Awaiting payment", "body": diag_html})

    html = render_internal_email(
        title=f"Weekly Digest — {today.strftime('%A %d %B %Y')}",
        subtitle="Operations Report",
        sections=sections,
    )

    send_email(secrets, WILL_EMAIL, f"Battleship digest — {today.strftime('%d %b')}", plain, html)
    state.setdefault("sent_digests", []).append("digest_" + week_key)
    print(f"  📊 Weekly digest sent to {WILL_EMAIL}")


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

    # 8. Re-engagement nudges for silent clients
    print("\n💬 Re-engagement check...")
    send_reengagement_emails(state, secrets)

    # 9. Weekly digest to Will (Mondays only)
    print("\n📊 Weekly digest (Mondays)...")
    send_weekly_digest(state, secrets)

    # 10. Facebook bot (posts, comment replies, DMs)
    print("\n📘 Facebook bot...")
    try:
        sys.path.insert(0, str(VAULT_ROOT))
        from skills.facebook_bot import run as run_facebook
        run_facebook(secrets, VAULT_ROOT)
    except Exception as e:
        print(f"  ⚠️  Facebook bot skipped: {e}")

    # 11. Facebook ads optimisation (daily)
    print("\n📊 Facebook ads optimisation...")
    try:
        from skills.facebook_ads_bot import run as run_ads
        run_ads(secrets, VAULT_ROOT)
    except Exception as e:
        print(f"  ⚠️  Ads bot skipped: {e}")

    # 12. Accounts bot — scan receipts, update finances.md, P&L report
    print("\n🧾 Accounts bot...")
    try:
        from skills.accounts_bot import run as run_accounts
        run_accounts(secrets, state, VAULT_ROOT)
    except Exception as e:
        print(f"  ⚠️  Accounts bot skipped: {e}")

    # 13. Marketing bot — daily review, weekly strategy, funnel tracking
    print("\n📣 Marketing bot...")
    try:
        from skills.marketing_bot import run as run_marketing
        run_marketing(secrets, state, VAULT_ROOT)
    except Exception as e:
        print(f"  ⚠️  Marketing bot skipped: {e}")

    # 14. Orchestrator — growth coordination (SEO + brand PM + tech backlog)
    print("\n🎯 Orchestrator (growth)...")
    try:
        from skills.orchestrator import run as run_orchestrator
        run_orchestrator(secrets, state)
    except Exception as e:
        print(f"  ⚠️  Orchestrator skipped: {e}")

    # Save state
    save_state(state)

    print(f"\n{'='*60}")
    print(f"✅ Pipeline complete — {len(state['clients'])} client(s) in system")
    for acct, cs in state["clients"].items():
        print(f"   • {acct}  {cs['name']:20s}  {cs['status']:12s}  week {cs.get('current_week', 0)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
