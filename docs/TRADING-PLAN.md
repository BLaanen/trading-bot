# Trading & Investment Growth Plan: $10K → $100K by End of 2026

> **Start date:** April 2026
> **Target date:** December 31, 2026
> **Starting capital:** $10,000
> **Target capital:** $100,000
> **Required return:** ~900% in ~9 months

---

## Reality Check

A 10x return in 9 months is **extremely aggressive**. For context:
- The S&P 500 averages ~10% per year
- Top hedge funds target 20-30% annually
- A 900% return requires either exceptional concentration risk, leverage, or both

This plan is structured in **phases** that progressively increase risk as your capital and skill grow. The early phases are designed to protect capital while you build edge; later phases deploy that edge more aggressively.

---

## Phase 1: Foundation & Capital Preservation (April 2026)

**Goal:** Set up infrastructure, learn the tools, protect the $10K.

### Actions
1. **Open a brokerage account** with Alpaca (paper + live) for commission-free trading and API access
2. **Allocate initial $10K:**

| Allocation | Amount | Purpose |
|---|---|---|
| Core ETF portfolio | $6,000 | Stable growth base |
| Active trading capital | $3,000 | Swing/momentum trades |
| Cash reserve | $1,000 | Dry powder for opportunities |

3. **Set up backtesting environment** using `backtesting.py` and `fastquant`
4. **Paper trade** your first 2 strategies for at least 2 weeks before going live

### Core ETF Portfolio ($6,000)

| ETF | Allocation | Rationale |
|---|---|---|
| QQQ (Nasdaq 100) | 25% / $1,500 | Tech growth exposure |
| TQQQ (3x Leveraged Nasdaq) | 15% / $900 | Leveraged upside on tech (high risk) |
| SOXX (Semiconductors) | 15% / $900 | AI/chip secular trend |
| XLK (Technology Select) | 15% / $900 | Broad tech diversification |
| SMH (VanEck Semiconductor) | 10% / $600 | Additional semi exposure |
| ARKK (ARK Innovation) | 10% / $600 | High-growth disruptive tech |
| Cash/Short-term bonds | 10% / $600 | Rebalancing buffer |

### Tools to Install
```bash
pip install backtesting fastquant riskfolio-lib yfinance pandas numpy
```

### Risk Rules
- **Max drawdown tolerance:** 15% on total portfolio
- **Stop-loss on every position:** 8% trailing stop
- **Position sizing:** No single stock > 10% of total portfolio
- **Leveraged ETFs:** Max 20% of portfolio at any time

---

## Phase 2: Momentum & Swing Trading ($10K → $25K) — May–June 2026

**Goal:** Use systematic momentum strategies to grow the active trading portion.

### Strategy 1: Moving Average Crossover (Stocks)
- **Universe:** Top 50 Nasdaq stocks by volume
- **Entry:** 10-day EMA crosses above 50-day EMA + RSI > 50
- **Exit:** 10-day EMA crosses below 50-day EMA OR 8% trailing stop
- **Position size:** 5-10% of trading capital per trade
- **Backtest first** using `backtesting.py`

### Strategy 2: Mean Reversion on Oversold ETFs
- **Universe:** Sector ETFs (XLK, XLF, XLE, XLV, XLI, etc.)
- **Entry:** RSI(14) < 30 AND price > 200-day SMA (oversold but uptrend)
- **Exit:** RSI(14) > 60 OR 5% profit target
- **Hold time:** 3-10 days typical

### Strategy 3: Earnings Momentum
- **Pre-earnings:** Buy stocks with strong momentum 5 days before earnings
- **Post-earnings:** Buy gap-ups on strong earnings beats, hold 2-5 days
- **Risk:** Strict 5% stop-loss, never hold through earnings with > 5% of capital

### Monthly Targets

| Month | Starting Capital | Target | Monthly Return |
|---|---|---|---|
| May 2026 | $10,000 | $14,000 | +40% |
| June 2026 | $14,000 | $25,000 | +78% |

### Rebalancing Rule
- Every 2 weeks, rebalance core ETF portfolio to target weights
- Move 30% of active trading profits into core ETF portfolio
- Use `Riskfolio-Lib` for portfolio optimization

---

## Phase 3: Options & Leverage ($25K → $50K) — July–September 2026

**Goal:** Use options to amplify returns on high-conviction trades.

> **Prerequisite:** You must be consistently profitable in Phase 2 before entering Phase 3. If not profitable, stay in Phase 2 and reduce position sizes.

### Portfolio Allocation at $25K

| Allocation | Amount | Purpose |
|---|---|---|
| Core ETF portfolio | $12,000 | Now 48% — growing the stable base |
| Active stock trading | $6,000 | Continuing momentum strategies |
| Options trading | $5,000 | Leveraged directional bets |
| Cash reserve | $2,000 | Dry powder |

### Options Strategies

#### A. Long Calls on Momentum Breakouts
- Buy ATM or slightly OTM calls (30-60 DTE) on stocks breaking out of consolidation
- Max risk per trade: 2% of total portfolio ($500)
- Target: 50-100% return on the option premium
- Exit: Close at 50% loss or 100% gain, whichever comes first

#### B. Bull Call Spreads on High-Conviction ETFs
- Buy ATM call, sell OTM call (30-45 DTE)
- Defined risk, reduced cost basis
- Use on QQQ, SOXX, XLK during confirmed uptrends
- Max risk per spread: $300-500

#### C. Selling Cash-Secured Puts on Stocks You Want to Own
- Sell puts on quality stocks at prices you'd be happy buying
- Collect premium while waiting for entries
- Strike price: 5-10% below current price
- Good for: AAPL, MSFT, NVDA, GOOGL, AMZN

### Monthly Targets

| Month | Starting Capital | Target | Monthly Return |
|---|---|---|---|
| July 2026 | $25,000 | $32,000 | +28% |
| August 2026 | $32,000 | $40,000 | +25% |
| September 2026 | $40,000 | $50,000 | +25% |

### Risk Rules for Options
- **Never risk more than 2% of total portfolio on a single options trade**
- **No naked options** — always defined risk
- **Close losing trades at 50% loss** — no hoping for recovery
- **Take profits at 100% gain** — don't get greedy
- **Max 30% of portfolio in options at any time**

---

## Phase 4: Concentrated Bets & Scaling ($50K → $100K) — October–December 2026

**Goal:** Deploy larger positions in highest-conviction setups.

### Portfolio Allocation at $50K

| Allocation | Amount | Purpose |
|---|---|---|
| Core ETF portfolio | $20,000 | 40% — wealth preservation |
| Active stock trading | $12,000 | Proven strategies at scale |
| Options trading | $10,000 | Amplified returns |
| Concentrated positions | $5,000 | 1-2 high-conviction bets |
| Cash reserve | $3,000 | Always keep dry powder |

### Concentrated Position Criteria
Only enter a concentrated position (5-10% of portfolio) when ALL of these are true:
1. Stock is in a strong uptrend (above 20, 50, and 200 day MAs)
2. Sector has positive momentum
3. Fundamental catalyst exists (earnings beat, product launch, etc.)
4. Technical breakout from a base/consolidation pattern
5. You have backtested a similar setup with positive expectancy

### Monthly Targets

| Month | Starting Capital | Target | Monthly Return |
|---|---|---|---|
| October 2026 | $50,000 | $65,000 | +30% |
| November 2026 | $65,000 | $82,000 | +26% |
| December 2026 | $82,000 | $100,000 | +22% |

---

## Automated Backtesting Setup

### File: `trading/backtest_momentum.py`
Use `backtesting.py` to validate Strategy 1 before trading live:

```python
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA
import yfinance as yf

class MomentumCrossover(Strategy):
    fast_period = 10
    slow_period = 50

    def init(self):
        close = self.data.Close
        self.fast_ma = self.I(SMA, close, self.fast_period)
        self.slow_ma = self.I(SMA, close, self.slow_period)

    def next(self):
        if crossover(self.fast_ma, self.slow_ma):
            self.buy(sl=self.data.Close[-1] * 0.92)  # 8% stop-loss
        elif crossover(self.slow_ma, self.fast_ma):
            self.position.close()

# Download data and run backtest
data = yf.download("QQQ", start="2023-01-01", end="2026-03-31")
data = data.droplevel('Ticker', axis=1) if isinstance(data.columns, pd.MultiIndex) else data

bt = Backtest(data, MomentumCrossover, cash=10000, commission=0.001)
stats = bt.run()
print(stats)
bt.plot()
```

### File: `trading/portfolio_optimizer.py`
Use `Riskfolio-Lib` for portfolio optimization:

```python
import riskfolio as rp
import yfinance as yf
import pandas as pd

# Define ETF universe
tickers = ["QQQ", "TQQQ", "SOXX", "XLK", "SMH", "ARKK"]

# Download price data
data = yf.download(tickers, start="2023-01-01", end="2026-03-31")
data = data["Close"]

# Calculate returns
returns = data.pct_change().dropna()

# Build portfolio object
port = rp.Portfolio(returns=returns)
port.assets_stats(method_mu="hist", method_cov="hist")

# Optimize for maximum Sharpe ratio
weights = port.optimization(model="Classic", rm="MV", obj="Sharpe")
print("Optimal Portfolio Weights:")
print(weights.T)

# Plot efficient frontier
ax = rp.plot_frontier(
    w_frontier=port.efficient_frontier(model="Classic", rm="MV", points=50),
    mu=port.mu, cov=port.cov,
    returns=returns
)
```

---

## Portfolio Rebalancing Schedule

| Frequency | Action |
|---|---|
| Daily | Review open positions, check stop-losses |
| Weekly | Review sector momentum, adjust watchlist |
| Bi-weekly | Rebalance core ETF portfolio to target weights |
| Monthly | Full portfolio review, move profits from active to core |
| Quarterly | Reassess strategy performance, cut underperformers |

---

## Key Metrics to Track

| Metric | Target | Red Flag |
|---|---|---|
| Win rate | > 55% | < 45% |
| Risk/reward ratio | > 2:1 | < 1:1 |
| Max drawdown | < 15% | > 25% |
| Sharpe ratio | > 1.5 | < 0.5 |
| Monthly return | > 20% | Negative 2 months in a row |

---

## Emergency Rules

1. **If portfolio drops 20% from peak:** Stop all active trading for 1 week. Review all positions. Only resume with 50% position sizes.
2. **If portfolio drops 30% from peak:** Close all active and options positions. Move everything to core ETFs. Reassess entire strategy.
3. **If you lose 3 trades in a row:** Take a 3-day break from active trading. Review your journal.
4. **If a single trade loses > 5% of portfolio:** Review position sizing rules immediately.

---

## Tools & Infrastructure

| Tool | Purpose | Setup |
|---|---|---|
| Alpaca | Paper trading + live execution | alpaca.markets |
| backtesting.py | Strategy validation | `pip install backtesting` |
| fastquant | Quick strategy testing | `pip install fastquant` |
| Riskfolio-Lib | Portfolio optimization | `pip install riskfolio-lib` |
| yfinance | Market data | `pip install yfinance` |
| TradingView | Charts and screening | tradingview.com |
| Trading journal | Track every trade | Spreadsheet or Notion |

---

## Honest Probability Assessment

| Outcome | Probability |
|---|---|
| Reach $100K by Dec 2026 | ~5-10% |
| Reach $50K by Dec 2026 | ~15-20% |
| Reach $25K by Dec 2026 | ~30-40% |
| Stay around $10-15K | ~25-30% |
| Lose significant capital | ~15-20% |

The plan is structured to **maximize the upside case while limiting catastrophic downside**. The emergency rules and position sizing limits are there to ensure that even in the worst case, you don't lose everything.

---

## Weekly Checklist

- [ ] Review all open positions and stop-losses
- [ ] Check sector momentum (rising/falling)
- [ ] Run backtests on any new strategy ideas
- [ ] Update trading journal with all trades
- [ ] Calculate current portfolio value and track against targets
- [ ] Review news/catalysts for the coming week
- [ ] Rebalance if any position is > 2% off target weight

---

## Getting Started This Week

1. **Day 1:** Set up Alpaca paper trading account
2. **Day 2:** Install Python tools (`backtesting.py`, `riskfolio-lib`, `yfinance`)
3. **Day 3:** Run the momentum backtest script on QQQ, SOXX, XLK
4. **Day 4:** Set up core ETF portfolio allocation in paper account
5. **Day 5:** Start paper trading Strategy 1 (MA Crossover)
6. **Day 6-7:** Review results, adjust parameters, research upcoming catalysts

---

*This plan is for educational and informational purposes. All trading involves risk of loss. Past performance does not guarantee future results. Never invest money you cannot afford to lose.*
