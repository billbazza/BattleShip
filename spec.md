# Battleship – Technical Specification
**Last updated:** 2026-03-11
**Status:** Active development — pipeline live, no paying clients yet

---

## 1. What This Is

An autonomous online coaching business targeting men aged 40–60 who want to lose weight, build fitness, and feel better without extreme approaches. The product is a 12-week structured programme (£199 one-time) with the business model built on Phase 2 monthly coaching (£79/month) for long-term retention.

Everything from lead capture to weekly coaching to education delivery runs without manual intervention. The coach's job is to exist — the system does the operational work.

---

## 2. The Client Journey

```
Typeform intake form
        ↓
Pipeline polls every 2 hours (cron)
        ↓
Claude generates personalised diagnosis
        ↓
HTML diagnosis email sent (with Stripe payment link)
        ↓
Client pays £199 at buy.stripe.com
        ↓
Stripe payment detected by pipeline
        ↓
Claude generates personalised 12-week plan
        ↓
Onboarding email sent (plan + Zone 2 walking instructions)
        ↓
Week 1: Sleep bonus lesson sent
        ↓
Weeks 2–11: 2 education lessons/week (Mon + Thu)
        ↓
Every Sunday: check-in request email (link to Google Form)
        ↓
Client submits Google Form check-in
        ↓
Pipeline reads Google Sheet → Claude generates coach reply
        ↓
Coach reply email sent (Monday morning)
        ↓
Week 12: Claude generates personalised closing letter + Phase 2 offer
```

---

## 3. Infrastructure

| Component | Tool | Notes |
|-----------|------|-------|
| Intake form | Typeform (`wbD9VYUa`) | Prospect-facing — keep polished |
| Check-in form | Google Forms | Existing clients only — free, unlimited |
| Check-in data | Google Sheets | Sheet ID: `1sgPM9incm9xezRKXQTNITBmdILcy4olTcYXKzJPdcmk` |
| AI | Anthropic Claude (`claude-sonnet-4-6`) | Diagnosis, plan, check-in replies, week 12 close |
| Email | iCloud SMTP (`smtp.mail.me.com:587`) | Sent from `wbarratt@me.com` |
| Payments | Stripe Live | `buy.stripe.com/3cI6oG79qefgb1CdhwejK00` |
| Secrets | `~/.battleship.env` | Chmod 600 — no 1Password at runtime (cron compatible) |
| Google creds | `~/.battleship-gsheets.json` | Service account for Sheets read access |
| State | `clients/state.json` | All client records, pipeline state |
| Dashboard | Flask (`scripts/app.py`) | `localhost:5100` — local only |
| Cron | Every 2 hours | `/usr/local/bin/python3 .../battleship_pipeline.py` |
| Repo | `github.com/billbazza/BattleShip` | `clients/` and secrets gitignored |

---

## 4. Core Script: `scripts/battleship_pipeline.py`

Single Python file (~1,400 lines). Runs the full pipeline on every cron execution.

### Key constants (top of file)
```python
INTAKE_FORM_ID    = "wbD9VYUa"          # Typeform
CHECKIN_GFORM_URL = "https://forms.gle/TkBjLWd5aotBGTDAA"  # Google Form
COACH_NAME        = "William George BattleShip Barratt"
PAYMENT_LINK      = "https://buy.stripe.com/3cI6oG79qefgb1CdhwejK00"
```

### Pipeline execution order (every run)
1. `process_new_intake()` — polls Typeform, generates diagnosis, sends email
2. `check_stripe_payments()` — polls Stripe charges, auto-enrols paying clients
3. `send_weekly_checkin_requests()` — Sundays only, sends check-in link to active clients
4. `process_checkin_responses()` — reads Google Sheet, generates coach replies
5. `send_education_drips()` — sends scheduled lessons (Mon/Thu stagger)
6. `send_week12_close()` — personalised close + Phase 2 offer at week 12

### Client state record (in `state.json`)
```json
{
  "BSR-2026-0001": {
    "name": "John Smith",
    "email": "john@email.com",
    "account_no": "BSR-2026-0001",
    "folder": "BSR-2026-0001-john-smith",
    "status": "active",
    "current_week": 3,
    "enrolled_date": "2026-03-01",
    "emails_sent": ["diagnosis", "onboarding", "edu_sleep", "edu_zone2"],
    "tags": { "age": "47", "weight_lbs": "195", "goal": "lose 20lbs", ... },
    "complimentary": false
  }
}
```

### Client statuses
| Status | Meaning |
|--------|---------|
| `diagnosed` | Intake received, diagnosis email sent, awaiting payment |
| `active` | Paid (or complimentary), plan sent, receiving weekly content |
| `complete` | Week 12 close sent |

### Account number format
`BSR-YYYY-NNNN` — sequential per year, assigned at intake. Client folders: `clients/BSR-2026-0001-name/`

### Per-client files (in `clients/<folder>/`)
| File | Contents |
|------|----------|
| `diagnosis.md` | Claude's personalised diagnosis |
| `plan.md` | Full 12-week programme |
| `progress-tracker.md` | Updated each week from check-in data |
| `event-log.md` | Timestamped pipeline events and coach notes |

### AI prompts
- **DIAGNOSIS_PROMPT** — 4 sections: why it's failed before, what will be different, week 1 starting point, why it's worth it. Ends with `AGENT_TAGS_JSON` block of structured data.
- **PLAN_PROMPT** — staged reveal: week 1 walking only, exercises introduced in week 3 with plain-English guides, one new thing per week.
- **CHECKIN_PROMPT** — reads weekly log, produces updated progress tracker + 150–250 word coach message.
- **WEEK12_PROMPT** — personal letter referencing 12 weeks of actual data, honest about 18–24 month timeline, soft Phase 2 offer.

---

## 5. Email System

Two HTML templates in `scripts/templates/`:
- `diagnosis_email.html` — dark header, 4 sections, red CTA button (£199), 7-day guarantee
- `onboarding_email.html` — welcome, Zone 2 science, baseline measurements, 12-week timeline

Templates use `%%placeholder%%` tokens (not f-strings) to avoid CSS brace-escaping issues.

Education and check-in emails are plain text — personal, not designed.

Every email footer includes: *"Got a question? Just reply — I read every one."*

---

## 6. Education Drip Schedule

2 lessons/week max. Lesson 1 fires Monday (day 0–3 of week), lesson 2 fires Thursday (day 3–6). Tracked via `emails_sent` keys in client state.

| Week | Lesson 1 | Lesson 2 |
|------|----------|----------|
| 1 | Sleep + stress bonus | — |
| 2 | Zone 2 walking science | The key to success |
| 3 | The 80/20 rule | Building a balanced plate |
| 4 | Fat loss: getting started (+ personal calorie target) | Awareness |
| 5 | Closing the gap | Hacking consistency |
| 6 | Whole foods reference | Workout overview |
| 7 | Gym terminology | Gymtimidation |
| 8 | Proper warm-ups | Workout prep |
| 9 | How much weight? | Training for fat loss |
| 10 | The Battleship training method | — |
| 11 | (available) | — |
| 12 | *Personalised close — Claude-generated, not a lesson* | — |

Week 4 calorie target is personalised: `weight_lbs × 12` (committed) or `× 15` (if client flagged difficulty with restriction in intake).

---

## 7. Exercise Library (`education-lessons/exercises/`)

Plain-English guides for each exercise. Format: what it is → why it's in your plan → how to do it (3 steps) → what it should feel like → modifications.

| File | Exercise |
|------|----------|
| `zone2-walking.md` | Zone 2 cardio — the foundation |
| `goblet-squat.md` | Goblet squat |
| `hip-hinge.md` | Dumbbell Romanian deadlift |
| `push-up.md` | Push-up (incline modification) |
| `dumbbell-row.md` | Single-arm dumbbell row |
| `step-up.md` | Step-up (replaces lunges for bad knees) |
| `plank.md` | Plank (bird-dog modification) |

---

## 8. CLI Commands (`scripts/COMMANDS.md`)

All run from vault root: `python3 scripts/battleship_pipeline.py [command]`

| Command | Action |
|---------|--------|
| *(no args)* | Full pipeline run |
| `--find=<query>` | Search by name, email, or account number |
| `--status=<query>` | Full client report: week, emails, tracker, event log |
| `--enrol=<query>` | Manually enrol a diagnosed client (Stripe confirmed) |
| `--enrol=<query> --free` | Enrol without payment (testers, friends) |
| `--advance=<query>` | Bump current_week forward by 1 |
| `--note=<query> "text"` | Add a coach note to event log |

---

## 9. Flask Dashboard (`scripts/app.py`)

Runs locally at `http://localhost:5100`. Start with `python3 scripts/app.py`.

| Route | Page |
|-------|------|
| `/` | Dashboard — all clients, status badges, week numbers |
| `/client/<acct>` | Client detail — meta, action buttons, tracker, plan, diagnosis, event log |
| `/run` | Run pipeline manually, see terminal output |

Action buttons appear contextually: Enrol / Enrol Complimentary (when `diagnosed`), Advance Week (when `active`), coach note field always present.

---

## 10. Secrets (`~/.battleship.env`)

```
TYPEFORM_KEY=...
ANTHROPIC_KEY=...
SMTP_HOST=smtp.mail.me.com
SMTP_USER=wbarratt@me.com
SMTP_PASS=...
STRIPE_KEY=sk_live_...
GSHEETS_ID=1sgPM9incm9xezRKXQTNITBmdILcy4olTcYXKzJPdcmk
GSHEETS_CREDS=~/.battleship-gsheets.json
```

Refresh from 1Password while authenticated: run the populate script (`scripts/setup-1password-secrets.sh` or the inline Python in the session history). Only needed when a key rotates.

---

## 11. What's Not Built Yet

| Item | Priority | Notes |
|------|----------|-------|
| Carrd website (battleshipreset.com) | **High** | Stripe compliance requirement |
| Social content (Instagram/Facebook) | **High** | Sales engine — nothing sells without this |
| Phase 2 product definition | Medium | What does £79/month actually include? |
| WhatsApp/Telegram check-in bot | Low | Better UX than form — build after first 5 clients |
| MFP integration | Low | API locked down — manual friend-add is the workaround |
| Email HTML templates for education/check-in | Low | Currently plain text — works fine |

---

## 12. Known Limitations

- **Typeform quota hit** — intake form only, no new submissions until quota resets or plan upgrades. New client acquisition is paused until Carrd + social drives traffic anyway.
- **Old clients in state** (will, john, fred) use pre-BSR slug format — they work but won't get account numbers. New submissions get BSR-YYYY-NNNN.
- **Check-in email mismatch** — test submissions using `barhomebridge@icloud.com` won't match client records unless state is updated manually.
- **Week 12 Phase 2 offer** hardcoded at £79/month — price not yet formally decided.
- **No email HTML for education drips** — plain text only. Sufficient for now.
