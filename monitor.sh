#!/bin/bash
#
# Position Monitor — called by launchd 3x daily on trading days:
#   15:00 CEST (09:00 ET) — pre-market reconciliation
#   18:30 CEST (12:30 ET) — midday bracket child check + time stops
#   22:15 CEST (16:15 ET) — post-close reconciliation + portfolio snapshot
#
# Reconciles with Alpaca, checks if bracket exits fired, applies time stops.
# Bracket orders at the broker handle stop-loss and take-profit exits.
# Skips on weekends/holidays.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load Alpaca keys from ~/.zshrc if not already in env (launchd has a minimal env)
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

# Check if today is a trading day (skip weekends and market holidays)
"$PY" -c "
import os, sys
import alpaca_trade_api as tradeapi
api = tradeapi.REST(
    os.environ['ALPACA_API_KEY'],
    os.environ['ALPACA_API_SECRET'],
    'https://paper-api.alpaca.markets',
    api_version='v2',
)
clock = api.get_clock()
# Run if market is open OR if it was open today (post-close check)
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
next_open = str(clock.next_open)[:10]
next_close = str(clock.next_close)[:10]
is_trading_day = clock.is_open or next_close == today or next_open > today
sys.exit(0 if is_trading_day else 2)
" || {
  rc=$?
  if [ $rc -eq 2 ]; then
    # Not a trading day — silent exit
    exit 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Alpaca clock check failed (rc=$rc)"
  exit 1
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor cycle start"
"$PY" orchestrator.py --monitor
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor cycle done"
