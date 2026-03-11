# Battleship Pipeline — Command Reference

All commands run from the vault root:
```
cd /Users/will/Obsidian-Vaults/BattleShip-Vault
python3 scripts/battleship_pipeline.py [command]
```

---

## Normal Run (automated / cron)
```bash
python3 scripts/battleship_pipeline.py
```
Runs the full pipeline:
1. Polls Typeform for new intakes → generates diagnosis → sends diagnosis email
2. Polls Stripe for new payments → enrols paying clients → sends plan + onboarding email
3. Sends weekly check-in requests (Sundays only)
4. Processes check-in responses → generates coach replies
5. Sends education drip emails on schedule

---

## Find a Client
```bash
python3 scripts/battleship_pipeline.py --find=fred
python3 scripts/battleship_pipeline.py --find=fred@email.com
python3 scripts/battleship_pipeline.py --find=BSR-2026-0001
```
Search by name, email address, or account number. Partial matches work.

---

## Enrol a Client (paid — Stripe already confirmed)
```bash
python3 scripts/battleship_pipeline.py --enrol=fred
python3 scripts/battleship_pipeline.py --enrol=BSR-2026-0001
```
Client must be in `diagnosed` status. Generates their 12-week plan and sends the onboarding email.
Use when Stripe payment is confirmed but the pipeline missed it.

---

## Enrol Complimentary (friends, testers, no payment)
```bash
python3 scripts/battleship_pipeline.py --enrol=fred --free
```
Same as above but skips the Stripe requirement. Client is marked `complimentary: true` in state.
Use for: beta testers, friends, anyone you're putting through for free.

---

## Advance a Client's Week
```bash
python3 scripts/battleship_pipeline.py --advance=fred
python3 scripts/battleship_pipeline.py --advance=BSR-2026-0001
```
Bumps `current_week` forward by 1. Use to:
- Skip to a later week for testing
- Correct a week that got stuck due to a pipeline error
- Manually advance someone who joined mid-programme

---

## Full Client Status
```bash
python3 scripts/battleship_pipeline.py --status=fred
python3 scripts/battleship_pipeline.py --status=BSR-2026-0001
```
Shows: week, emails sent, last 10 lines of progress tracker, last 8 event log entries.

---

## Add a Coach Note
```bash
python3 scripts/battleship_pipeline.py --note=fred "Called today — knee improving, back on plan"
```
Writes a timestamped `[COACH NOTE]` entry to the client's event log. Use for anything that happens outside the automated flow: calls, messages, observations.

---

## ⚠️  The Tracking Gap

The progress tracker (`progress-tracker.md`) is only written when a client responds to the weekly check-in Typeform. Until that form exists and clients are filling it in, week advancement is just a number — there's no data behind it.

**Priority: create the weekly check-in Typeform.** It needs to capture:
- Workouts completed this week (which ones, how many)
- How the body felt (energy, sleep, soreness, any injury)
- Weight this week (optional)
- What got in the way, if anything
- One win, one hard thing

Once live, set `CHECKIN_FORM_ID` in the pipeline and the loop closes.

---

## Client Status Reference

| Status      | Meaning                                              |
|-------------|------------------------------------------------------|
| `diagnosed` | Intake received, diagnosis email sent, awaiting payment |
| `active`    | Paid (or complimentary), plan generated, onboarded  |

---

## Logs

Pipeline log (cron output):
```
tail -f logs/pipeline.log
```

Per-client event log:
```
cat clients/BSR-2026-0001-name/event-log.md
```

---

## State File
```
clients/state.json
```
Direct edits are possible but risky. Use `--find` to verify before touching.
Back it up first: `cp clients/state.json clients/state.json.bak`

---

## Cron Schedule
Pipeline runs every 2 hours automatically:
```
crontab -l
```
To disable: `crontab -e` and comment out the battleship line.
