---
description: Resume the scheduled trading system (load launchd agents)
---

Resume the automated trading schedule. Reloads the three launchd agents so `at_open.sh`, `monitor.sh`, and `eod.sh` fire on schedule again.

Steps:

1. Load each agent:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.bopeterlaanen.trading.at_open.plist
   launchctl load ~/Library/LaunchAgents/com.bopeterlaanen.trading.monitor.plist
   launchctl load ~/Library/LaunchAgents/com.bopeterlaanen.trading.eod.plist
   ```

2. Verify with `launchctl list | grep trading` — should show all three.

3. Report which agents are now loaded and the next scheduled run for each:
   - `at_open`: next run at 15:25 CEST on next trading day
   - `monitor`: next run in <=5 min
   - `eod`: next run at 22:10 CEST

4. If the market is currently open, note: "Monitor will fire within 5 minutes and resume trailing stops on your open positions."

5. Confirm no issues by running `/status` immediately after to verify the system is healthy.
