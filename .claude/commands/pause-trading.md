---
description: Pause the scheduled trading system (unload launchd agents)
---

Pause the automated trading schedule. This stops `at_open.sh`, `monitor.sh`, and `eod.sh` from firing on schedule. Open positions are NOT closed — they just stop being monitored automatically.

**Lower risk than before:** Bracket orders at the broker handle stop-loss and take-profit exits even when the monitor is paused. Pausing only disables time stops, reconciliation checks, and new entries. Existing positions are still protected by their bracket children at Alpaca.

Steps:
1. Check if market is open: `TZ=America/New_York date`
2. Check open positions: `cat positions.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('positions',[])))"`
3. If market is open AND positions > 0, warn the user explicitly:
   > "Market is open and you have N open positions. Bracket orders at the broker still protect them.
   > Pausing means: no time stops, no reconciliation, no new entries until resumed.
   >
   > Are you sure? Type 'yes pause' to confirm."
4. Only if they confirm (or market is closed / no positions), run:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.bopeterlaanen.trading.at_open.plist
   launchctl unload ~/Library/LaunchAgents/com.bopeterlaanen.trading.monitor.plist
   launchctl unload ~/Library/LaunchAgents/com.bopeterlaanen.trading.eod.plist
   ```
5. Verify with `launchctl list | grep trading` — should return nothing
6. Confirm: "Scheduler paused. Run `/resume-trading` to re-enable. Remember to resume before the next trading day's 15:25 CEST scan."
