#!/bin/bash
#
# Position Monitor — called by cron every 5 minutes during market hours
#
# Updates prices, trails stops, processes partial exits, triggers full exits.
# Skips gracefully if the market is closed (no-op on holidays/weekends).

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load Alpaca keys from ~/.zshrc if not already in env (cron has a minimal env)
if [ -z "${ALPACA_API_KEY:-}" ] && [ -f "$HOME/.zshrc" ]; then
  ALPACA_LINES=$(grep -E '^export ALPACA_(API_KEY|API_SECRET)=' "$HOME/.zshrc" 2>/dev/null || true)
  if [ -n "$ALPACA_LINES" ]; then
    eval "$ALPACA_LINES"
  fi
fi

if [ -z "${ALPACA_API_KEY:-}" ] || [ -z "${ALPACA_API_SECRET:-}" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ALPACA_API_KEY/SECRET not set"
  exit 1
fi

PY="/opt/homebrew/bin/python3.11"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3.11)"
fi

# Check if market is open — silently exit if not (cron runs every 5 min but market is open only 6.5h)
"$PY" -c "
import os, sys
import alpaca_trade_api as tradeapi
api = tradeapi.REST(
    os.environ['ALPACA_API_KEY'],
    os.environ['ALPACA_API_SECRET'],
    'https://paper-api.alpaca.markets',
    api_version='v2',
)
sys.exit(0 if api.get_clock().is_open else 2)
" || {
  rc=$?
  if [ $rc -eq 2 ]; then
    # Market closed — normal, silent exit
    exit 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Alpaca clock check failed (rc=$rc)"
  exit 1
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor cycle start"
"$PY" orchestrator.py --monitor
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor cycle done"
