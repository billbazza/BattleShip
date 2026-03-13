# Battleship — Midlife Fitness Reset

**Owner:** Will Barratt
**Live site:** https://battleshipreset.com
**Last updated:** March 2026

Online coaching for men 45–60. Automated intake, personalised plans, weekly check-ins, education drips, and programme delivery — all running on a single Python pipeline with no third-party automation tools.

---

## How the system works

```
Tally intake form
       ↓
webhook.battleshipreset.com (Cloudflare tunnel → localhost:5100)
       ↓
battleship_pipeline.py — Claude API
       ↓
Diagnosis email → Stripe payment link
       ↓
Enrolment → 12-week adaptive plan
       ↓
Weekly: check-in request → Google Form → check-in response (coach message + session block + nudge)
        Education drip (1/week, Weeks 1–12)
       ↓
Week 8: challenge email
Week 12: close + Phase 2 pitch
```

---

## Running the system

```bash
# Dashboard (localhost:5100)
python3 scripts/app.py

# Run pipeline manually
python3 scripts/battleship_pipeline.py

# Full command reference
cat scripts/COMMANDS.md
```

Cron runs the pipeline every 15 minutes via LaunchAgent (`com.battleship.pipeline`).
Dashboard runs persistently via LaunchAgent (`com.battleship.dashboard`).
Cloudflare tunnel runs via LaunchAgent (`com.battleship.tunnel`).

---

## Root files

| File | Purpose |
|------|---------|
| `00-Overview.md` | Business overview, brand pillars, navigation hub |
| `About-Will.md` | Will's personal transformation story — used in brand/marketing |
| `claude.md` | AI operating instructions (loaded as context in every session) |
| `coaching-philosophy.md` | Loaded by pipeline for diagnosis and check-in generation |
| `spec.md` | Full system specification |
| `clients.md` | Client pipeline log (leads → active) |
| `content.md` | Content publishing tracker |
| `finances.md` | Revenue, costs, cash flow |
| `learnings.md` | Daily insights and reflections |

---

## Folder structure

```
scripts/
  battleship_pipeline.py   — main pipeline (intake, enrolment, check-ins, drips, email)
  app.py                   — Flask dashboard (localhost:5100)
  COMMANDS.md              — CLI reference for all pipeline operations

clients/
  state.json               — all client state (single source of truth)
  BSR-2026-NNNN/           — per-client folder (plan.md, tracker, diagnosis, event-log)

education-lessons/
  sleep/                   — Week 1
  exercises/               — Zone 2, movement
  nutrition/               — 80/20, plate method, fat loss
  fat-loss/                — Fat loss series (Weeks 4–5)
  training/                — Gym, sessions, methods (Weeks 6–11)
  fasting/                 — Insulin & fasting lessons (Week 9)
                             jamnadas-fasting-visceral-fat.md  ← drip
                             insulin-fasting-visceral-fat.md   ← Claude reference only
  found-time.md            — "Exercise that doesn't cost you a minute"

11-week-programs/
  8 tracks selected at Week 1 check-in based on equipment:
  ├── beginner-bodyweight-strength-training
  ├── bodyweight-full-body
  ├── bodyweight-hiit
  ├── resistance-bands-full-body
  ├── dumbbell-full-body
  ├── home-complete (dumbbells + bands + pull-up bar)
  ├── gym-beginner (machines)
  └── gym-intermediate (push/pull/legs) — auto-assigned at Week 8

brand/          — logos, brand assets, website copy
expenses/       — expense records
logs/           — pipeline execution logs
skills/         — automation skill scripts
archive/        — superseded files (blueprints, old templates, sub-agents)
```

---

## Key integrations

| Service | Purpose |
|---------|---------|
| Tally | Intake form (form ID: rjK752) |
| Stripe | Payment link (live) |
| Google Forms/Sheets | Weekly check-ins |
| Postmark | Transactional email |
| Cloudflare | Tunnel + DNS (battleshipreset.com) |
| Claude API | Diagnosis, adaptive plan, check-in responses, challenge email, close email |

Secrets: `~/.battleship.env`
Google credentials: `~/.battleship-gsheets.json`

---

## Email addresses

| Address | Handled by |
|---------|-----------|
| coach@battleship.me | Claude (auto-reply) |
| support@battleship.me | Claude (auto-reply, flags cancellations) |
| will@battleship.me | Will (manual) |
