#!/bin/bash
# install-launchagents.sh
# ─────────────────────────────────────────────────────────────────────────────
# Copies all com.battleship.* plists from this folder into ~/Library/LaunchAgents
# and registers them with launchctl.
#
# Uses the modern macOS 11+ bootstrap/bootout API (not the deprecated load/unload).
#
# Usage — run from ANYWHERE (script resolves its own path):
#   bash /Users/will/Obsidian-Vaults/BattleShip-Vault/scripts/launchagents/install-launchagents.sh
#
# To bootout + re-bootstrap all (e.g. after editing a plist):
#   bash .../install-launchagents.sh --reload
#
# To install just one agent:
#   bash .../install-launchagents.sh com.battleship.claude-agent
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
GUI_DOMAIN="gui/$(id -u)"
RELOAD=false
ONLY_LABEL=""

for arg in "$@"; do
  case "$arg" in
    --reload) RELOAD=true ;;
    com.battleship.*) ONLY_LABEL="$arg" ;;
  esac
done

echo "📦  Battleship LaunchAgents Installer"
echo "      Source  : $SCRIPT_DIR"
echo "      Target  : $LAUNCH_AGENTS_DIR"
echo "      Domain  : $GUI_DOMAIN"
[[ -n "$ONLY_LABEL" ]] && echo "      Filter  : $ONLY_LABEL only"
echo ""

mkdir -p "$LAUNCH_AGENTS_DIR"

for plist in "$SCRIPT_DIR"/com.battleship.*.plist; do
  label="$(basename "$plist" .plist)"

  # Skip if a specific label was requested and this isn't it
  if [[ -n "$ONLY_LABEL" && "$label" != "$ONLY_LABEL" ]]; then
    continue
  fi

  dest="$LAUNCH_AGENTS_DIR/$(basename "$plist")"

  # Bootout first if --reload is set or the service is already registered
  if $RELOAD || launchctl print "$GUI_DOMAIN/$label" &>/dev/null 2>&1; then
    echo "  ⏹   Booting out $label ..."
    launchctl bootout "$GUI_DOMAIN/$label" 2>/dev/null || true
    sleep 1
  fi

  echo "  📋  Copying   $(basename "$plist") → $LAUNCH_AGENTS_DIR/"
  cp "$plist" "$dest"
  chmod 644 "$dest"

  echo "  ▶️   Bootstrapping $label ..."
  launchctl bootstrap "$GUI_DOMAIN" "$dest"

  echo "  ✅  $label registered"
  echo ""
done

echo "Verification:"
echo "  launchctl print $GUI_DOMAIN | grep battleship"
echo ""
launchctl print "$GUI_DOMAIN" 2>/dev/null | grep battleship || echo "  (none found — check plist Label keys)"
