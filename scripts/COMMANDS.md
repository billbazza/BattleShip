# Battleship — Command Reference
**Last updated:** 2026-03-13

All pipeline commands run from the vault root:
```bash
cd /Users/will/Obsidian-Vaults/BattleShip-Vault
python3 scripts/battleship_pipeline.py [command]
```

---

## Services

### Start / check services
Both auto-start on login via LaunchAgent. If something looks wrong:

```bash
# Check what's running
launchctl list | grep battleship

# Restart Flask dashboard
launchctl stop com.battleship.dashboard && launchctl start com.battleship.dashboard

# Restart Cloudflare tunnel
launchctl stop com.battleship.tunnel && launchctl start com.battleship.tunnel

# Check Flask is up
curl -s http://localhost:5100/api/status

# View live logs
tail -f logs/app.log
tail -f logs/tunnel.log
tail -f logs/pipeline.log
```

### Dashboard
Open in browser: http://localhost:5100

System status panel on homepage shows health of all services (tunnel, DNS, SMTP, Stripe, Claude, cron, etc.).

---

## Pipeline — Normal Run (cron / manual)

```bash
python3 scripts/battleship_pipeline.py
```

Runs the full pipeline in order:
1. Processes queued Tally intake submissions → diagnosis → email
2. Polls Stripe for new payments → auto-enrols paying clients
3. Sends weekly check-in requests (Sundays only, min 5 days after enrolment)
4. Processes Google Sheet check-in responses → personalised coach replies
5. Polls IMAP for inbound emails → Claude auto-replies to coach@/support@
6. Sends education drip emails on schedule (Mon + Thu stagger)
7. Sends Week 12 personalised close + Phase 2 offer

Cron schedule: `0 */2 * * *` (every 2 hours)

---

## Find a Client

```bash
python3 scripts/battleship_pipeline.py --find=fred
python3 scripts/battleship_pipeline.py --find=fred@email.com
python3 scripts/battleship_pipeline.py --find=BSR-2026-0001
```

Search by name, email, or account number. Partial matches work.

---

## Full Client Status

```bash
python3 scripts/battleship_pipeline.py --status=fred
python3 scripts/battleship_pipeline.py --status=BSR-2026-0001
```

Shows: week, emails sent, last 10 lines of progress tracker, last 8 event log entries.

---

## Enrol a Client

**Paid** (Stripe confirmed, pipeline missed it):
```bash
python3 scripts/battleship_pipeline.py --enrol=BSR-2026-0001
```

**Complimentary** (friends, testers, no payment):
```bash
python3 scripts/battleship_pipeline.py --enrol=BSR-2026-0001 --free
```

Client must be in `diagnosed` status. Generates their 12-week plan and sends onboarding email. Marked `complimentary: true` in state if --free.

---

## Advance a Client's Week

```bash
python3 scripts/battleship_pipeline.py --advance=BSR-2026-0001
```

Bumps `current_week` forward by 1. Use to correct a stuck week or skip ahead for testing.

---

## Add a Coach Note

```bash
python3 scripts/battleship_pipeline.py --note=BSR-2026-0001 "Called today — knee improving"
```

Writes a timestamped `[COACH NOTE]` entry to the client's event log.

---

## Client Management (Dashboard)

The following actions are available via the dashboard UI at `http://localhost:5100/client/<acct>`:

| Action | When available | Effect |
|--------|---------------|--------|
| Enrol (paid) | `diagnosed` | Generates plan, sends onboarding |
| Enrol (complimentary) | `diagnosed` | Same, no Stripe required |
| Advance Week | `active` | Bumps current_week by 1 |
| Add note | Always | Timestamped entry in event-log.md |
| Went silent | Any | Sets status → `silent`, logged |
| Refunded | Any | Sets status → `refunded`, logged |
| Archive | Any | Sets status → `archived`, logged |
| Delete record | Non-active only | Removes from state.json, files kept on disk |

---

## Client Status Reference

| Status | Meaning |
|--------|---------|
| `diagnosed` | Intake received, diagnosis sent, awaiting payment |
| `active` | Paid or complimentary, plan sent, receiving weekly content |
| `complete` | Week 12 close sent |
| `silent` | Stopped responding |
| `refunded` | Payment returned |
| `archived` | General archive |

---

## Logs

```bash
# Pipeline runs (cron output)
tail -f logs/pipeline.log

# Flask dashboard
tail -f logs/app.log

# Cloudflare tunnel
tail -f logs/tunnel.log

# Per-client event log
cat clients/BSR-2026-0001-name/event-log.md
```

---

## State File

```
clients/state.json
```

Direct edits are possible but risky. Use `--find` to verify before touching.
Always back up first:
```bash
cp clients/state.json clients/state.json.bak
```

---

## Growth Bots (Orchestrator + SEO + Tech)

### Orchestrator — full daily growth run
```bash
python3 skills/orchestrator.py --run        # runs all growth bots, sends Command Report email
python3 skills/orchestrator.py --brief      # print brand PM brief to console (no email)
python3 skills/orchestrator.py --status     # show all bot statuses in one view
```

### SEO Bot — Google Business Profile progression
```bash
python3 skills/seo_bot.py --status          # show GBP task progress (0-8 tasks)
python3 skills/seo_bot.py --run             # run this week's SEO task (generates output, emails Will)
python3 skills/seo_bot.py --run-task 3      # run specific task by number (0-8)
python3 skills/seo_bot.py --weekly-post     # generate this week's GBP post copy
python3 skills/seo_bot.py --confirm 2       # mark task 2 as complete (you made the GBP change)
```
Outputs saved to: `brand/Marketing/SEO/outputs/`

### Tech Bot — gap tracking + cost analysis
```bash
python3 skills/tech_bot.py --backlog        # show all tech gaps, costs, workarounds
python3 skills/tech_bot.py --report         # full markdown report with revenue-gated recommendations
python3 skills/tech_bot.py --flag "GBP API" --cost 35 --unlock 1000  # manually flag a gap
```
Backlog stored in: `brand/Marketing/tech_backlog.json`

### Brand/after composites with hooks
```bash
python3 skills/brand_manager.py --hook-variants       # generate all 12 hooked before/after images
python3 skills/brand_manager.py --before-after        # plain before/after (no hook)
python3 skills/brand_manager.py --before-after --headline "47. Walking. That's it."  # custom hook
```
Hook variants saved to: `brand/output/before_after_hook_01.jpg` through `_12.jpg`

---

## Webhook

Tally submissions arrive at: `https://webhook.battleshipreset.com/tally-webhook`

Queued as JSON files in `clients/tally-queue/` — processed on next pipeline run (or immediately via background process triggered by the webhook).

To manually reprocess a stuck submission:
```bash
# File will be in clients/tally-queue/
ls clients/tally-queue/
python3 scripts/battleship_pipeline.py   # processes all queued files
```
