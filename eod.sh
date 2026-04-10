#!/bin/bash
#
# End-of-Day Learning — called by cron after market close
#
# Runs:
#   1. Final position monitor (catches any last-minute exits)
#   2. Daily report (performance snapshot)
#   3. Learning loop (autopsy closed trades, update patterns, propose adaptations)
#   4. Weekly report (on Fridays only)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load Alpaca keys from ~/.zshrc if not already in env
if [ -z "${ALPACA_API_KEY:-}" ] && [ -f "$HOME/.zshrc" ]; then
  ALPACA_LINES=$(grep -E '^export ALPACA_(API_KEY|API_SECRET)=' "$HOME/.zshrc" 2>/dev/null || true)
  if [ -n "$ALPACA_LINES" ]; then
    eval "$ALPACA_LINES"
  fi
fi

PY="/opt/homebrew/bin/python3.11"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3.11)"
fi

echo "════════════════════════════════════════════════════════════════════════"
echo "  END OF DAY — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════════════════════"

echo
echo "=== Final Position Monitor ==="
"$PY" orchestrator.py --monitor || echo "  (monitor failed, continuing)"

echo
echo "=== Daily Report ==="
"$PY" orchestrator.py --report || echo "  (report failed, continuing)"

echo
echo "=== Learning Loop ==="
"$PY" analysis/learning_loop.py || echo "  (learning loop failed, continuing)"

echo
echo "=== Adaptive Config Status ==="
"$PY" analysis/adaptive_config.py --status || echo "  (status failed, continuing)"

# Weekly report on Fridays only (weekday 5 in date format, or $(date +%u) == 5)
if [ "$(date +%u)" = "5" ]; then
  echo
  echo "=== Weekly Report (Friday) ==="
  "$PY" analysis/weekly_report.py || echo "  (weekly report failed, continuing)"
fi

echo
echo "════════════════════════════════════════════════════════════════════════"
echo "  EOD complete — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════════════════════"
