# Battleship – Technical Specification
**Last updated:** 2026-03-13
**Status:** Live — intake form, pipeline, and webhook active. First real submission processed.

---

## 1. What This Is

An autonomous online coaching business targeting men aged 40–60 who want to lose weight, build fitness, and feel better without extreme approaches. The product is a 12-week structured programme (£199 one-time or 3×£75) with retention built on Phase 2 monthly coaching (£79/month) anchored around a personal confirmation challenge (Park Run → triathlon → London to Brighton, etc.).

Everything from lead capture to weekly coaching to education delivery runs without manual intervention. The coach's job is to exist — the system does the operational work.

---

## 2. The Client Journey

```
battleshipreset.com
        ↓
Tally intake form (tally.so/r/rjK752 — 35 questions)
        ↓
Tally webhook → POST /tally-webhook → queued JSON file
        ↓
Pipeline processes queue (cron every 2 hours)
        ↓
Claude generates personalised diagnosis (reads coaching-philosophy.md)
        ↓
HTML diagnosis email sent (with Stripe payment link)
        ↓
Client pays £199 at buy.stripe.com
        ↓
Stripe payment detected by pipeline → auto-enrol
        ↓
Claude generates personalised 12-week plan + personal success metrics
        ↓
Onboarding email sent (plan + Zone 2 walking instructions)
        ↓
Week 1: Sleep bonus lesson sent immediately
        ↓
Weeks 2–11: 2 education lessons/week (Mon + Thu)
        ↓
Week 8: Claude-generated confirmation challenge email (calibrated to progress)
        ↓
Client replies with challenge goal → stored in state, acknowledged
        ↓
Every Sunday: check-in request email (link to Google Form)
        ↓
Client submits Google Form check-in
        ↓
Pipeline reads Google Sheet → Claude generates personalised coach reply
        ↓
Coach reply email sent
        ↓
Week 12: Claude generates personalised closing letter
         references challenge goal + pitches Phase 2 (£79/month)
        ↓
Client replies "I'm in" → flagged in dashboard for Phase 2 setup
```

---

## 3. Infrastructure

| Component | Tool | Detail |
|-----------|------|--------|
| Website | Carrd Pro Standard | battleshipreset.com (live) |
| Intake form | Tally (free) | tally.so/r/rjK752 — 35 questions, webhook-based |
| Webhook receiver | Flask `/tally-webhook` | Signature-verified, queues JSON to `clients/tally-queue/` |
| Webhook tunnel | Cloudflare named tunnel | webhook.battleshipreset.com → localhost:5100 (permanent URL) |
| Check-in form | Google Forms | forms.gle/TkBjLWd5aotBGTDAA |
| Check-in data | Google Sheets | Sheet ID: `1sgPM9incm9xezRKXQTNITBmdILcy4olTcYXKzJPdcmk` |
| AI | Anthropic Claude (`claude-sonnet-4-6`) | Diagnosis, plan, check-ins, challenge email, week 12 close, inbound replies |
| Email out | iCloud SMTP (`smtp.mail.me.com:587`) | From: `wbarratt@me.com`, Reply-To: `coach@battleship.me` |
| Email in | iCloud IMAP (`imap.mail.me.com:993`) | Routes coach@, support@, will@ — Claude auto-replies to first two |
| Payments | Stripe Live | `buy.stripe.com/3cI6oG79qefgb1CdhwejK00` |
| Secrets | `~/.battleship.env` | chmod 600 — cron-compatible, no 1Password at runtime |
| Google creds | `~/.battleship-gsheets.json` | Service account for Sheets read access |
| State | `clients/state.json` | All client records — gitignored |
| Dashboard | Flask (`scripts/app.py`) | localhost:5100, auto-starts via LaunchAgent |
| Cron | Every 2 hours | `0 */2 * * *` — battleship_pipeline.py |
| Repo | github.com/billbazza/BattleShip | `clients/` and secrets gitignored |

### Auto-start (macOS LaunchAgents)
Both services start automatically on login and restart if they crash:
- `~/Library/LaunchAgents/com.battleship.dashboard.plist` — Flask app
- `~/Library/LaunchAgents/com.battleship.tunnel.plist` — Cloudflare tunnel

---

## 4. Core Script: `scripts/battleship_pipeline.py`

Single Python file. Runs the full pipeline on every cron execution.

### Pipeline execution order (every run)
1. `process_tally_queue()` — processes queued Tally submissions → diagnosis → email
2. `check_stripe_payments()` — polls Stripe charges, auto-enrols paying clients
3. `send_weekly_checkin_requests()` — Sundays only, sends check-in link (min 5 days since enrolment)
4. `process_checkin_responses()` — reads Google Sheet, generates personalised coach replies
5. `process_inbound_emails()` — IMAP poll: routes coach@/support@ to Claude, detects challenge replies and Phase 2 sign-ups
6. `send_education_drips()` — sends scheduled lessons (Mon/Thu stagger), Week 8 Claude-generated challenge email
7. `send_week12_close()` — personalised close referencing challenge goal + Phase 2 offer

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
    "tags": { "age": "47", "weight": "14st 6lb", "goal": "lose fat", ... },
    "goal": "Lose fat / get leaner",
    "success_metrics": ["Weight (weekly)", "Waist measurement", "Energy 1-10"],
    "challenge_goal": "Sprint triathlon",
    "phase2_requested": false,
    "complimentary": false
  }
}
```

### Client statuses
| Status | Meaning |
|--------|---------|
| `diagnosed` | Intake received, diagnosis sent, awaiting payment |
| `active` | Paid or complimentary, plan sent, receiving weekly content |
| `complete` | Week 12 close sent |
| `silent` | Stopped responding — manually set via dashboard |
| `refunded` | Payment refunded — manually set via dashboard |
| `archived` | General archive — manually set via dashboard |

### Account number format
`BSR-YYYY-NNNN` — sequential per year. Client folders: `clients/BSR-2026-0001-name/`

### Per-client files (in `clients/<folder>/`)
| File | Contents |
|------|----------|
| `diagnosis.md` | Claude's personalised diagnosis |
| `plan.md` | Full 12-week programme |
| `progress-tracker.md` | Updated each week from check-in data |
| `event-log.md` | Timestamped pipeline events, coach notes, status changes |

### AI prompts
- **DIAGNOSIS_PROMPT** — reads `coaching-philosophy.md` at runtime for edge case handling (low commitment, heavy drinkers, health flags, repeated failures). Assigns personal success metrics by goal type.
- **PLAN_PROMPT** — staged: week 1 walking only, exercises from week 3, one new thing per week.
- **CHECKIN_PROMPT** — reads tracker + personal metrics, produces updated tracker + 150–250 word coach message specific to their goal.
- **CHALLENGE_PROMPT** — Week 8 only, reads 8 weeks of tracker data, calibrates challenge list to actual fitness level.
- **WEEK12_PROMPT** — personal letter referencing challenge goal, honest 18–24 month framing, Phase 2 offer at £79/month.
- **COACH_REPLY_PROMPT** — inbound email auto-reply from coach@ address.
- **SUPPORT_REPLY_PROMPT** — inbound email auto-reply from support@, flags cancellations.

---

## 5. Email System

### HTML templates (`scripts/templates/`)
- `diagnosis_email.html` — dark header, 4 sections, red CTA (£199), 7-day guarantee
- `onboarding_email.html` — welcome, Zone 2 science, baseline measurements

Templates use `%%placeholder%%` tokens (not f-strings) to avoid CSS brace conflicts.

### Education and check-in emails
Styled with inline HTML using the pipeline's `md_to_html()` renderer. Dark callout block for "This week" action sections.

Reply-To on all outgoing emails: `coach@battleship.me`

---

## 6. Education Drip Schedule

2 lessons/week max. Lesson 0 fires Monday (day 0–3 of week), lesson 1 fires Thursday (day 3–6). Week 8 has a third item — Claude-generated, not a static file. Tracked via `emails_sent` keys in state.

| Week | Lesson 1 | Lesson 2 | Lesson 3 |
|------|----------|----------|----------|
| 1 | Sleep + stress | — | — |
| 2 | Zone 2 walking science | The key to success | — |
| 3 | The 80/20 rule | Building a balanced plate | — |
| 4 | Fat loss: getting started (+ calorie target) | Awareness | — |
| 5 | Closing the gap | Hacking consistency | — |
| 6 | Whole foods reference | Workout overview | — |
| 7 | Gym terminology | Gymtimidation | — |
| 8 | Proper warm-ups | Workout prep | **Challenge question** (Claude-generated) |
| 9 | How much weight? | Training for fat loss | — |
| 10 | The Battleship method | — | — |
| 11 | What about arms? | — | — |
| 12 | *Personalised close — see WEEK12_PROMPT* | — | — |

Week 4 calorie target: `weight_lbs × 12` (committed) or `× 15` (difficulty with restriction flagged).
Week 8 challenge email: Claude reads tracker data and calibrates challenge list to actual progress.

---

## 7. Phase 2 — Confirmation Challenge

**Introduced at Week 8** via a personalised email asking: *"If you could do something in the next 12 months that would have seemed completely impossible the day you filled in that form — what would it be?"*

Client reply is stored as `cs["challenge_goal"]` and used in the Week 12 close to build the Phase 2 pitch around their specific goal.

**Challenge tiers:**
- Entry (Weeks 13–20): Park Run, open water swim, weighted walk, 30-mile cycle
- Intermediate (Weeks 20–35): 10km run, sprint triathlon, half marathon, 100-mile cycling week
- Aspirational (Weeks 35–52+): London to Brighton, Olympic tri, multi-day hiking, marathon

**Phase 2 product:** £79/month, no minimum term. Weekly check-ins continue, strength tracked week to week, plan adjusted monthly toward the event, race day prep, post-event debrief.

---

## 8. Flask Dashboard (`scripts/app.py`)

Runs at `http://localhost:5100`. Auto-starts via LaunchAgent.

| Route | Function |
|-------|----------|
| `/` | Dashboard — system status panel + all clients |
| `/client/<acct>` | Client detail — meta, actions, tracker, plan, diagnosis, event log |
| `/run` | Run pipeline manually, see output |
| `/api/status` | JSON health check for all services |
| `/tally-webhook` | Receives Tally form submissions (POST, signature-verified) |
| `/action/<acct>/enrol` | Enrol client (paid) |
| `/action/<acct>/enrol_free` | Enrol client (complimentary) |
| `/action/<acct>/advance` | Advance current week by 1 |
| `/action/<acct>/note` | Add coach note to event log |
| `/action/<acct>/setstatus` | Change status: silent / refunded / archived |
| `/action/<acct>/delete` | Remove from state (keeps files, blocked for active paying clients) |

### System status panel
Homepage shows live health checks for: Flask, Cloudflare tunnel, webhook DNS, cron schedule, Claude API, Stripe, SMTP, IMAP, Google Sheets, pipeline last run, queued submissions.

---

## 9. Secrets (`~/.battleship.env`)

```
ANTHROPIC_KEY=sk-ant-...
SMTP_HOST=smtp.mail.me.com
SMTP_USER=wbarratt@me.com
SMTP_PASS=xxxx-xxxx-xxxx-xxxx
IMAP_HOST=imap.mail.me.com
IMAP_USER=wbarratt@me.com
IMAP_PASS=xxxx-xxxx-xxxx-xxxx
STRIPE_KEY=sk_live_...
GSHEETS_ID=1sgPM9incm9xezRKXQTNITBmdILcy4olTcYXKzJPdcmk
GSHEETS_CREDS=~/.battleship-gsheets.json
TALLY_WEBHOOK_SECRET=       # from Tally → Integrations → Webhooks
```

---

## 10. Coaching Philosophy (`coaching-philosophy.md`)

Loaded into the diagnosis prompt at runtime. Defines:
- Edge case handling: low commitment, heavy drinkers, health flags (BP, heart, injuries)
- Motivation flags: repeated failure reframing, unrealistic goals
- Positive signals to lean into
- Tone rules (no shame, no corporate wellness language, write like Will speaks)
- Personal success metrics by goal type
- Phase 2 confirmation challenge framework

---

## 11. Known Limitations / Outstanding

| Item | Status | Notes |
|------|--------|-------|
| Tally webhook signing secret | Not yet set | Add to ~/.battleship.env once Tally shows it |
| webhook.battleshipreset.com DNS | Propagating | NS change from GoDaddy → Cloudflare in progress |
| Social content (Instagram/Facebook) | Not started | Main sales engine — priority once first clients active |
| Facebook ads | Not started | Budget TBD |
| Phase 2 Stripe product | Not created | £79/month recurring — create when first Phase 2 client ready |
| Legacy clients (john, will, fred) | In state | Pre-BSR format, work fine, won't get account numbers |
