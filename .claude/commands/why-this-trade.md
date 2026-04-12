---
description: Explain a specific trade — why it was entered, current state, exit triggers
argument-hint: <TICKER>
---

Explain the trade for ticker `$ARGUMENTS` in plain language. The user wants to understand why the system took this trade and what it's waiting for.

Steps:
1. Look up the ticker in `positions.json` — if it's open, grab: entry price, current price, stop, target, strategy, entry date, bracket order IDs
2. Find the entry row in `trades.csv` — grab the strategy, notes, sector, regime
3. Find the entry order in `order_log.json` — grab the Alpaca order ID and fill timestamp
4. Calculate: days held, current R-multiple (unrealized), distance to stop (%), distance to target (%), whether it's above high-water mark

Then explain:

**$ARGUMENTS ([strategy]) — entered [date]**

One paragraph on WHY the system took this trade. Use the `notes` column from trades.csv as the basis, but translate any jargon using CONCEPTS.md. If the strategy was PULLBACK, say "the system saw [ticker] pulling back to its 21-day moving average in a strong uptrend with RSI still healthy — this is the classic dip-buy setup." If POWERX, explain the triple confirmation. Etc.

One paragraph on CURRENT STATE. Entry vs current price. Is it working or struggling? How many Rs up or down? How far from stop? How far from target?

One paragraph on WHAT TRIGGERS AN EXIT. The broker has bracket children: a stop-loss order and a take-profit order. Explain what prices those are set at. If it's been held > 10 days, mention the 15-day time stop. Exits are all-or-nothing (full position, no partials).

End with: "Bottom line: this trade is [winning/losing/neutral], needs [X] to [do Y], and the system will [exit action] if [condition]."

If the ticker is NOT in `positions.json`, check `trades.csv` for a historical closed trade with that ticker and explain that one instead, noting it's already closed.

If the ticker doesn't appear anywhere, say so clearly: "[ticker] has no record in our trade history."
