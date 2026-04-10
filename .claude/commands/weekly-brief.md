---
description: Friday-style weekly summary of trades, strategy performance, and goal progress
---

Generate a weekly trading brief in plain English, the kind Bo would want to read over coffee on a Saturday morning.

Data sources:
1. `trades.csv` — filter to rows from the last 7 days. For each: date, ticker, action, shares, price, strategy, outcome, P&L.
2. `order_log.json` — tail for context on recent fills
3. `positions.json` — what's still open going into next week
4. `edge_tracker.json` — per-strategy rolling edge stats
5. `portfolio_value.csv` — start-of-week and end-of-week value, 7-day delta
6. `learning_state.json` — any strategies auto-disabled this week, circuit breaker state
7. `logs/launchd_at_open.log` — did the daily scan run every trading day?

Structure the brief like this:

## Week of [date range]

**Bottom line:** One sentence. Portfolio up/down $X (Y%), W wins L losses, N open heading into next week.

### What happened
Narrative paragraph covering: how did the week start, what strategies hit, what worked, what didn't, any circuit breaker or auto-disable events.

### Trade-by-trade
A table of closed trades this week with ticker, strategy, outcome, R-multiple, P&L. Sort by P&L descending (biggest winner first, biggest loser last).

### Strategy scorecard
Per-strategy rolling edge from edge_tracker.json. Use plain language:
- "PULLBACK is earning — 5 trades, +1.2R average. Keep running it."
- "POWERX is struggling — 3 trades, -0.4R average. Monitor; if this continues, the edge tracker will auto-disable it."

### Still open
Current positions with entry date, days held, unrealized P&L, distance to stop and target. Flag any approaching time stop (>10 days held).

### Goal progress
Current portfolio value vs the $10K → $100K goal. What % of the way there. What the monthly run rate needs to be to hit year-end. Be honest if it's off track — the user wants reality, not pep talks.

### Flags for attention
Anything unusual: errors in logs, strategies auto-disabled, drawdown events, circuit breakers triggered, schedule missing a run.

### Next week watch
If there are upcoming earnings, Fed events, or market catalysts that could affect open positions, mention them. If you don't know, skip this section rather than inventing it.

Keep the total under 600 words. Write like you're explaining to a smart friend, not a finance professor. Explain any jargon inline.
