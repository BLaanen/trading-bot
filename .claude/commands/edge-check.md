---
description: Show which strategies are earning vs fading, in plain language
---

Run `python orchestrator.py --edge` from the trading directory, then translate the output into plain English.

Also read `edge_tracker.json` directly to get the raw per-strategy stats: trade count, win rate, average R, rolling edge window.

Present the results like this:

## Strategy edge report

For each strategy (PULLBACK, BREAKOUT, MA_BOUNCE, SECTOR_MOMENTUM, POWERX), show:

- **Strategy name** — status: [EARNING / WATCH / DECAYING / DISABLED]
- Trades: N (last 30 days / all time)
- Win rate: X%
- Average R: +Y.Y or -Y.Y
- One-sentence plain-language take

Use these status rules:
- **EARNING:** rolling edge > +0.3R — the strategy is making money, keep running it
- **WATCH:** rolling edge between 0 and +0.3R — breakeven-ish, monitor
- **DECAYING:** rolling edge < 0 but not yet auto-disabled — losing money, tracker is watching
- **DISABLED:** strategy has been auto-disabled by edge tracker — not taking new signals

At the end:

**Summary:** "N strategies earning, M watching, K decaying, L disabled."

**Recommendation:** If any strategy is decaying or disabled, say what that means for the user's approach. Don't recommend overriding the tracker — if the system disabled a strategy, trust it.

Keep under 300 words.
