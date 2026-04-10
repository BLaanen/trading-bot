---
description: Show what's currently open, today's P&L, and system health
---

Read the live trading state from disk and give me a concise status summary.

Steps:
1. Read `positions.json` for all open positions (ticker, shares, entry, current, stop, target, strategy, unrealized P&L)
2. Read the last ~30 lines of `order_log.json` for recent order activity
3. Read the last ~50 lines of `logs/launchd_monitor.log` to confirm the monitor is healthy
4. Run `launchctl list | grep trading` to confirm all 3 launchd agents are loaded
5. Run `TZ=America/New_York date` and determine if the US market is currently open (09:30-16:00 ET, Mon-Fri)
6. If `trades.csv` has rows from today, count them and sum today's realized P&L

Then present a summary in this format:

**Market:** [Open/Closed] ([time ET])
**Scheduler:** [3/3 loaded / WARN: N missing]
**Open positions:** [count], total cost basis $[X], unrealized P&L $[Y]
**Today's activity:** [N orders, $X realized P&L]
**Positions table:** ticker | strategy | entry | current | % | stop distance

At the end, flag anything that looks off:
- Any position within 1% of its stop loss
- Any error lines in the monitor log
- Any launchd job not loaded
- Portfolio in drawdown > 5% from peak

Keep the response under 300 words. No narrative preamble — just the summary.
