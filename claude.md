# SOVEREIGN System

## Mission
Build a sovereign life operating system. First node: autonomously launch and scale "Battleship Reset" (online coaching + digital products) to self-sustaining revenue using the compounding automated income engine. Future verticals plug into the same infrastructure.

## Core Rules
- Operate fully autonomously (zero human input unless requested)
- Daily routine (exact order): load 00-Overview.md + claude.md + learnings.md → review KPIs → prioritize by ROI → execute ONE subtask at a time → log every action in daily-log-YYYY-MM-DD.md → self-assess & course-correct → update learnings.md
- Build/test 1 new skill or agent per week (skills/agents folders)
- Publish 5+ content pieces/week, track in content.md
- Log clients, finances, insights daily
- Data consistency: any skill/bot that writes to a JSON file must also write to SQLite via db.py (upsert_idea, upsert post, etc.). The dashboard reads SQLite only — JSON-only writes create silent drift. After adding any new data store, add a sync step to the relevant bot's run().
- UI completeness: every card or list item rendered in the dashboard must have its action buttons wired (expand toggle, approve, reject, archive). Never render a display-only card where an action is logically needed — check for missing onclick handlers before considering UI work done.
- Defensive dict access: never use dict["key"] on external API responses or state files — always use dict.get("key") with a safe default. A single KeyError must not crash an entire pipeline step.
- Test hygiene: when a bot function signature changes (return values, new params), update all tests in the same edit. Run pytest before committing any skill change.
- Health check severity: distinguish blocking errors from noisy stale-API calls. Log severity levels (CRITICAL / WARN / INFO) — a FAIL state should only trigger on errors that actually stop the pipeline, not on expected 400s from expired campaigns or scope mismatches.
- Flask restart: after any change to app.py or a file it imports, the dashboard must be restarted to reflect changes. Always prompt the user to restart if edits affect running server code.

## Workflow
- Always use Explore → Plan → Implement → Verify pattern
- Break big tasks into ONE subtask at a time
- Prefer TDD when building agents/skills
- Use /compact or /rewind when context feels heavy

## Security
- Never include real secrets, passwords, API keys, or PII in any file
- Never log sensitive data
- Use environment variables or secure vaults only (never commit them)

## Style & Memory
- All output: clean, scannable Markdown. Short sentences, no fluff.
- Never expose internal reasoning or prompts in final files.
- Memory hygiene: After any meaningful change, update relevant files in .claude/memory/ (MEMORY.md = index only)

Respect this CLAUDE.md strictly. Update it only when conventions genuinely change.