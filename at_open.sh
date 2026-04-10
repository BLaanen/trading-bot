#!/bin/bash
#
# Market-Open Automation — one command to run the full trading day
#
# Usage:
#   ./at_open.sh                 # Full auto: wait for open, scan, execute, monitor
#   ./at_open.sh --dry-run       # Plan only (safe, no orders placed)
#   ./at_open.sh --no-scheduler  # Execute then exit (don't start scheduler)
#   ./at_open.sh --no-wait       # Skip the 10-min post-open spread wait
#   ./at_open.sh --force         # Override safety checks (weekends/closed market)
#
# Requires ALPACA_API_KEY and ALPACA_API_SECRET in ~/.zshrc (already set).

set -e

# Resolve the script directory so this works from anywhere
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# If env vars are not already set (e.g. running from cron), extract them from ~/.zshrc
if [ -z "${ALPACA_API_KEY:-}" ] && [ -f "$HOME/.zshrc" ]; then
  # Grep the export lines from .zshrc without actually sourcing it (bash can't handle zsh syntax)
  ALPACA_LINES=$(grep -E '^export ALPACA_(API_KEY|API_SECRET)=' "$HOME/.zshrc" 2>/dev/null || true)
  if [ -n "$ALPACA_LINES" ]; then
    eval "$ALPACA_LINES"
  fi
fi

# Verify env vars are set
if [ -z "${ALPACA_API_KEY:-}" ] || [ -z "${ALPACA_API_SECRET:-}" ]; then
  echo "ERROR: ALPACA_API_KEY and ALPACA_API_SECRET must be set."
  echo "Add them to ~/.zshrc:"
  echo "  export ALPACA_API_KEY=\"...\""
  echo "  export ALPACA_API_SECRET=\"...\""
  exit 1
fi

# Pick the right Python (3.11 required)
if command -v python3.11 >/dev/null 2>&1; then
  PY="python3.11"
else
  echo "ERROR: python3.11 not found. Install with: brew install python@3.11"
  exit 1
fi

# Log the run
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/at_open_$(date +%Y%m%d_%H%M%S).log"

echo "════════════════════════════════════════════════════════════════════════"
echo "  TRADING DAY — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  Working dir: $SCRIPT_DIR"
echo "  Python:      $($PY --version)"
echo "  Log file:    $LOG_FILE"
echo "════════════════════════════════════════════════════════════════════════"
echo

# Tee output to both terminal and log file
"$PY" at_open.py "$@" 2>&1 | tee "$LOG_FILE"
