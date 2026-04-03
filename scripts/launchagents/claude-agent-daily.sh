#!/bin/bash
# claude-agent-daily.sh
# Called by com.battleship.claude-agent LaunchAgent at 06:00 daily.
# Gathers vault context, builds a prompt, and runs claude --print.
# All output is appended to ~/Library/Logs/battleship-claude-agent.log

set -euo pipefail

# ── Log setup ─────────────────────────────────────────────────────────────────
mkdir -p "$HOME/Library/Logs"
LOG="$HOME/Library/Logs/battleship-claude-agent.log"

{
  echo ""
  echo "======================================================"
  echo "  Battleship Claude Agent — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "======================================================"
} >> "$LOG"

# ── PATH: launchd gives a bare environment — build it up ─────────────────────
# 1. Start with common system + Homebrew locations
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# 2. Add user-local bin dirs where npm / pip / direct installs land
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/bin:$PATH"
export PATH="$HOME/Library/Application Support/npm/bin:$PATH"

# 3. nvm — if installed, try to source it so its managed node/npm land in PATH
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  source "$NVM_DIR/nvm.sh" 2>/dev/null || true
fi

# 4. If still missing, source the user's login shell profile as a last resort
if ! command -v claude &>/dev/null; then
  for profile in "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bash_profile" "$HOME/.profile"; do
    [[ -f "$profile" ]] && source "$profile" 2>/dev/null || true
  done
fi

# ── Locate claude binary ───────────────────────────────────────────────────────
# Primary: hardcoded nvm path (current node version as of 2026-03-25)
CLAUDE_BIN="$HOME/.nvm/versions/node/v24.14.0/bin/claude"

# Fallback 1: nvm glob — handles node version upgrades automatically
if [[ ! -x "$CLAUDE_BIN" ]]; then
  for candidate in "$HOME"/.nvm/versions/node/*/bin/claude; do
    if [[ -x "$candidate" ]]; then
      CLAUDE_BIN="$candidate"
    fi
  done
  # The loop leaves CLAUDE_BIN as the last (highest) match; sort to get newest
  CLAUDE_BIN="$(printf '%s\n' "$HOME"/.nvm/versions/node/*/bin/claude \
    | grep -v '\*' | sort -V | tail -1)"
fi

# Fallback 2: anything in PATH (covers npm-global, homebrew, /usr/local, etc.)
if [[ ! -x "$CLAUDE_BIN" ]]; then
  CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi

if [[ -z "$CLAUDE_BIN" ]]; then
  {
    echo "ERROR: claude CLI not found in any of:"
    echo "  PATH = $PATH"
    echo ""
    echo "Fix: find the real path with 'which claude' in your terminal,"
    echo "then hard-code it at the top of claude-agent-daily.sh"
    echo ""
    echo "  CLAUDE_BIN=/path/to/claude   # add this near line 80 of the script"
  } >> "$LOG"
  exit 1
fi

{
  echo "Claude binary : $CLAUDE_BIN"
  echo "Version       : $("$CLAUDE_BIN" --version 2>&1 | head -1)"
  echo "Node PATH     : $(command -v node 2>/dev/null || echo n/a)"
} >> "$LOG"

# ── Gather vault context ───────────────────────────────────────────────────────
VAULT="/Users/will/Obsidian-Vaults/BattleShip-Vault"
TODAY="$(date +%Y-%m-%d)"

LOG_LINES="$(tail -n 60 "$VAULT/logs/pipeline.log"           2>/dev/null || echo '(pipeline.log not found)')"
LEARNINGS="$(tail -n 80 "$VAULT/learnings.md"                2>/dev/null || echo '(learnings.md not found)')"
BRIEFING="$(cat          "$VAULT/clients/morning_briefing.json" 2>/dev/null || echo '{}')"
FINANCES="$(tail -n 30   "$VAULT/finances.md"                 2>/dev/null || echo '(finances.md not found)')"

# ── Build prompt in a temp file ────────────────────────────────────────────────
TMPFILE="$(mktemp /tmp/battleship-daily-prompt.XXXXXX)"
trap 'rm -f "$TMPFILE"' EXIT

# printf line-by-line avoids heredoc '<' chars which break plist XML
printf '%s\n' \
  "You are the autonomous business agent for Battleship Reset, running the daily routine described in CLAUDE.md." \
  "" \
  "Today is $TODAY." \
  "" \
  "=== RECENT PIPELINE LOG (last 60 lines) ===" \
  "$LOG_LINES" \
  "" \
  "=== RECENT LEARNINGS (last 80 lines) ===" \
  "$LEARNINGS" \
  "" \
  "=== MORNING BRIEFING JSON ===" \
  "$BRIEFING" \
  "" \
  "=== RECENT FINANCES ===" \
  "$FINANCES" \
  "" \
  "=== YOUR TASKS FOR TODAY ===" \
  "Perform the daily routine from CLAUDE.md in this exact order:" \
  "" \
  "1. CONTEXT LOAD: Summarise the current business state (MRR, active clients, pipeline health, marketing arc week)." \
  "" \
  "2. KPI REVIEW: Check weekly goals:" \
  "   - Clients this week (target: 1-5 after week 4)" \
  "   - Content published this week (target: 5+ pieces)" \
  "   - Cash flow (target: £3,000 MRR by day 90)" \
  "   State on-track or off-track and by how much." \
  "" \
  "3. PIPELINE LOG CHECK: Scan for errors, warnings, anomalies. List actionable issues (recurring exceptions, auth failures, skipped steps). If none, state 'Pipeline clean'." \
  "" \
  "4. PRIORITISE: Name the single highest-ROI task for today. Lead gen > content > skill experiments. State why." \
  "" \
  "5. DAILY LOG ENTRY: Write a concise entry for $VAULT/logs/daily-log-$TODAY.md (date, KPI snapshot, pipeline status, top priority, 1-3 key insights)." \
  "" \
  "6. LEARNINGS UPDATE: Append 3 new bullet insights to $VAULT/learnings.md using format: - [YYYY-MM-DD] [category] insight" \
  "" \
  "Output in clearly labelled sections. Direct and actionable — no padding." \
  > "$TMPFILE"

{
  echo "Prompt size   : $(wc -c < "$TMPFILE") bytes"
  echo "Running claude --print ..."
  echo ""
} >> "$LOG"

# ── Run Claude (stdin avoids all arg-quoting edge cases) ──────────────────────
"$CLAUDE_BIN" --print < "$TMPFILE" >> "$LOG" 2>&1
EXIT_CODE=$?

{
  echo ""
  echo "Exit code: $EXIT_CODE  |  Finished: $(date '+%H:%M:%S')"
  echo ""
} >> "$LOG"

exit $EXIT_CODE
