---
description: Narrative of what the trading system did today — scans, entries, exits, decisions
---

Tell the story of today's trading session in plain English. The user wants to feel caught up after being away.

Data sources:
1. `logs/launchd_at_open.log` — today's entries from the 15:25 CEST scan
2. `logs/launchd_monitor.log` — the last ~200 lines covering today
3. `order_log.json` — orders with today's date
4. `trades.csv` — rows with today's date
5. `positions.json` — current open positions
6. `signals.csv` — what the scanner found (may include signals that were rejected by filters)

Write a short narrative (3–5 paragraphs, under 500 words) covering:

**Paragraph 1 — Market open and the scan**
What did the regime check say (bullish/sideways/bearish)? How many signals did the scanner find? How many were filtered out and why? Which signals made it through?

**Paragraph 2 — Entries**
Which trades actually got placed, at what prices, for which strategies? If there were rejections (correlation guard, heat cap, already open), note them.

**Paragraph 3 — Intraday action**
What did the monitor do throughout the day? Any trailing stop moves? Any partial exits hit? Any full exits or stop-outs? Any alerts or warnings in the log?

**Paragraph 4 — End of day state**
What's open heading into the next session? What's the P&L for today (realized + unrealized)? Any positions close to stops or targets?

**Paragraph 5 — Anything unusual**
Errors, warnings, unexpected rejections, schedule anomalies. If nothing unusual, skip this paragraph.

Write like you're catching someone up over coffee, not writing a compliance report. Explain jargon. Use specific numbers. Don't invent anything — if a log doesn't tell you something, say "no record of that in today's logs."

If the market hasn't opened today yet (before 15:30 CEST), say so and explain what's scheduled next.
