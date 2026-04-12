# Trading Concepts — Plain Language Cheat Sheet

This file explains the trading vocabulary used in this codebase. If a term shows up in logs, reports, or code and it's not obvious what it means, look here first.

## The core idea

**Win about half your trades. Make winners bigger than losers.** That's the whole system in one sentence. If you win 50% of the time but your winners are 2.5x the size of your losers, you're profitable. The code, the risk rules, and the learning loop all exist to make that math work.

---

## Position sizing

**R (one unit of risk)**
The amount of money you're risking on a single trade. This system uses 1% of portfolio per trade. On a $10,000 portfolio, 1R = $100. Everything else is measured in Rs — a "+2R winner" means you made $200 on that trade; a "-1R loser" means you lost $100.

**Why R matters:** comparing trades in dollars is misleading because the portfolio size changes. Comparing in R keeps the math clean across time.

**Position size**
The number of shares you buy. It's calculated backward from R: if 1R = $100 and your stop-loss is $2 below entry, you can buy 50 shares ($100 ÷ $2 = 50). A wider stop means smaller position. A tighter stop means bigger position. Risk is constant; share count is the variable.

---

## Stops and exits

**Stop-loss**
A price below your entry where you'll exit the trade and accept the loss. Set before you enter. Never moved down. Mechanical — no second-guessing.

**Target**
A price above your entry where you'll take profits. Usually set at 2R or 3R above entry (2x or 3x the amount you're risking).

**Bracket order**
A single order that creates three linked orders at the broker: the buy, a stop-loss child, and a take-profit child. When the buy fills, both children become active. Whichever child fills first automatically cancels the other. The broker handles exits — Python doesn't need to poll constantly.

**Time stop**
If a stock hasn't hit stop OR target after a set number of days (15 by default), close it. Dead money should get recycled into a better setup.

---

## Risk management

**Heat**
Total risk across all open positions, as a % of portfolio. If you have 4 positions each risking 1% (1R each), your heat is 4%. The system caps heat at 6%. Think of heat as "if every open trade hit its stop today, how much of my portfolio would I lose?"

**Drawdown**
How far the portfolio is below its peak value, as a %. If you peaked at $10,500 and now you're at $9,900, drawdown is 5.7%. The system starts halving position sizes at 10% drawdown and stops trading entirely at 20%.

**Circuit breaker**
Automatic pause after a streak of losses. After 4 consecutive losing trades, the system stops taking new positions for 3 days. This prevents revenge trading after a bad streak.

**Correlation guard**
Blocks bets that are too similar. You can't load up on 4 tech stocks and call it diversified — if tech dumps, all 4 go together. The guard rejects new positions in a sector that's already heavily represented.

---

## Strategies (the 5 scanner setups)

**PULLBACK**
Find a stock in a clear uptrend. Wait for it to pull back to its 21-day exponential moving average (EMA) without breaking trend. Enter when RSI is still healthy (not oversold, not overbought). The idea: strong trends attract dip buyers; you're joining them.

**BREAKOUT**
Find a stock that's been trading sideways in a tight range for weeks. When it breaks above that range on heavy volume, buy it. The idea: sideways consolidation is accumulation; the breakout is the release.

**MA_BOUNCE**
Find a stock in a long-term uptrend (above its 200-day moving average). When it dips to the 50-day MA and bounces, buy. The idea: the 50 MA is a natural support line that institutional buyers defend.

**SECTOR_MOMENTUM**
Buy sector ETFs (XLE for energy, XLK for tech, XLRE for real estate, etc.) when the whole sector is moving up. The idea: individual stock picks are risky; sector bets spread that risk.

**POWERX**
A Markus Heitkoetter setup with three confirming signals: RSI(7) is high (strong momentum), MACD histogram is positive and growing (momentum accelerating), and Stochastic %K is above %D (short-term strength). Only buy when all three agree. Uses fixed percentage stop/target from the PowerX Optimizer (default: 1.5% stop / 4.5% target = R:R 3.0, the "Quick Trades" setting). Other available settings: Conservative (1.5/3.0), M&M Balanced (2.5/5.0), Position Trader (2.5/7.5). These are set in `config.py` via `powerx_stop_pct` and `powerx_target_pct`.

---

## Indicators

**RSI (Relative Strength Index)**
A 0–100 momentum meter. Below 30 = "oversold" (might bounce). Above 70 = "overbought" (might pull back). Most strategies use RSI to confirm a move has room to continue rather than being exhausted.

**EMA (Exponential Moving Average)**
A moving average that weighs recent prices more than old ones. The 21 EMA and 50 EMA are common trend markers. Prices above the 21 EMA = short-term uptrend.

**MACD (Moving Average Convergence Divergence)**
A momentum indicator built from two moving averages. The "histogram" is the gap between them. When the histogram grows positive, momentum is accelerating up. When it turns negative, it's flipping.

**Stochastic**
A 0–100 oscillator comparing recent close to recent highs and lows. Uses two lines: %K (fast) and %D (slow). When %K crosses above %D, short-term momentum is turning up.

**Volume**
How many shares traded. High volume on an up move = conviction. Low volume = nobody cares. Breakout strategies require volume confirmation.

---

## Market regime

**Bullish regime**
Broad market is trending up. S&P 500 above its 200-day MA, most stocks rising. The system allows full position sizes and takes more signals.

**Sideways regime**
Broad market is chopping without trend. The system reduces position sizes and gets pickier about signals.

**Bearish regime**
Broad market is trending down. The system cuts position sizes further and may stop taking long trades altogether.

The regime check (`orchestrator.py --regime`) sets the multiplier that scales every other risk parameter. It's the first thing the pipeline does each morning.

---

## Orders and execution

**Paper trading**
Fake money on Alpaca's simulated exchange. Real prices, real fills, realistic slippage — no real dollars at risk. This system runs in paper mode.

**Slippage**
The gap between the price you expected and the price you actually got. A market order might "slip" a few cents on a thin stock. After a buy fills, the system checks whether slippage degraded the R:R ratio below 1.5. If so, it immediately closes the position ("slippage rejection") rather than holding a bad trade.

**Fill**
When your order actually executes. "Filled at $47.89" means you bought at $47.89. The system always uses the actual fill price from Alpaca for all calculations, never the scanner's planned price.

**Reconciliation**
Before any trading logic runs, the system compares its local positions.json against Alpaca's actual positions via API. If they disagree (different tickers, quantities, or entry prices), it refuses to trade until the mismatch is fixed. This prevents the local state from drifting away from reality.

**Alpaca**
The broker this system uses. Free, commission-free, has a paper trading account with $100,000 in fake money by default. The Python SDK is `alpaca-trade-api`.

---

## The learning loop

After every closed trade, `learning_loop.py` runs an "autopsy": it looks at what happened (win? loss? how many Rs? which strategy?) and updates `edge_tracker.json` with rolling stats per strategy.

**Edge**
How well a strategy is performing, measured in average R per trade. Positive edge = making money. Negative edge = losing money. The tracker updates on a rolling window so it catches strategies that stop working.

**Edge decay**
When a strategy's edge drops over time. If PULLBACK used to average +0.8R per trade and is now averaging -0.2R over the last 20 trades, it's decaying. The system auto-disables strategies that go negative on rolling edge.

**Autopsy**
A per-trade review after close: what was the setup, what happened, was it a win or loss, which strategy, which regime, how many Rs. Written to `trades.csv` and summarized in the weekly report.

**Hypothesis generator**
`hypothesis_generator.py` looks at the autopsy history and proposes new hypotheses ("POWERX trades entered between 10:00–10:30 have 30% higher win rate") to test. Currently experimental.

---

## Reports

**Daily report**
Generated at end of day by `eod.sh`. Covers: positions open, today's P&L (realized from exits + unrealized on open positions), which strategies traded, which got rejected, heat level, drawdown, any circuit breaker state.

**Weekly report**
Generated on Fridays by `weekly_report.py`. Covers: trades this week, wins vs losses, strategy breakdown, best and worst trades, edge decay alerts, goal progress ($10K→$100K trajectory).

---

## Math example

Let's say you have $10,000, 1% risk per trade (1R = $100), and the system is trading well.

- 10 trades: 5 wins, 5 losses (50% win rate)
- Wins average +2.5R each = +$250 × 5 = +$1,250
- Losses average -1R each = -$100 × 5 = -$500
- **Net: +$750 over 10 trades**

That's how winners being bigger than losers compensates for only winning half the time. If you ever see wins shrinking or losses growing in the edge report, that math is breaking — time to investigate.

---

## When something looks wrong

If a log or report uses a term that isn't in this file, add it. This document should grow as we discover what vocabulary matters. The goal is: any future session can start here and understand what the system is talking about without reading academic finance papers.
