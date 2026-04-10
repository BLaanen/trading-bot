# Trading System Setup Guide

## What You Need

| Component | Required? | Cost | Purpose |
|-----------|-----------|------|---------|
| Python 3.11+ | Yes | Free | Runtime |
| Alpaca account | Yes (for paper trading) | Free | Paper/live order execution + real-time data |
| Yahoo Finance | Automatic fallback | Free | Data if no Alpaca key |

## Step 1: Install Dependencies

```bash
cd trading/
pip install -r requirements.txt
```

If `multitasking` fails to build:
```bash
pip install multitasking==0.0.11
pip install -r requirements.txt
```

## Step 2: Create an Alpaca Paper Trading Account

1. Go to **https://alpaca.markets** and sign up (free)
2. Once logged in, switch to **Paper Trading** (toggle in the top nav)
3. Go to **API Keys** in the dashboard
4. Click **Generate New Key**
5. Copy both the **API Key ID** and **Secret Key** — the secret is only shown once

**Important:** Paper trading uses fake money. You cannot lose real money.
Alpaca gives you $100,000 in paper money by default, but our system
tracks its own $10K portfolio internally.

## Step 3: Set Your Environment Variables

```bash
# Add these to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ALPACA_API_KEY="your-api-key-id-here"
export ALPACA_API_SECRET="your-secret-key-here"
```

Then reload:
```bash
source ~/.bashrc   # or source ~/.zshrc
```

**Verify it works:**
```bash
cd trading/
python data_provider.py
```

You should see `AlpacaProvider` as the data source instead of `YahooProvider`.

## Step 4: Understand the Three Modes

### Mode 1: Fully Simulated (no API keys needed)
- Data from Yahoo Finance (15-min delay)
- Orders are simulated with fake IDs (`SIM-20260403-AAPL`)
- Good for: learning the system, checking signals

### Mode 2: Paper Trading (free Alpaca account)
- Real-time data from Alpaca
- Real orders on Alpaca's paper exchange (fake money)
- Fills, slippage, and timing are realistic
- **This is where you should spend 2-4 weeks before going live**

### Mode 3: Live Trading (when ready)
- Change `alpaca_paper: bool = False` in config.py
- Change `alpaca_base_url` to `https://api.alpaca.markets`
- **Real money. Do not do this until you've paper traded successfully.**

## Step 5: Run the System

### Quick test (no network needed)
```bash
python test_simulation.py
```
Runs the full pipeline with synthetic data. Validates position sizing,
trailing stops, partial exits, and circuit breakers.

### Check market regime
```bash
python orchestrator.py --regime
```
Tells you: bullish, sideways, or bearish. This determines everything else.

### Scan for signals
```bash
python orchestrator.py --scan
```
Scans your universe (18 stocks + 6 ETFs) for trade setups across all 5
strategies. Shows entry, stop, target, and R:R for each signal.

### Validate strategies against backtests
```bash
python orchestrator.py --validate
```
Backtests each strategy against historical data. Only strategies that pass
(win rate, Sharpe, R:R) get approved for live signals.

### Run the full pipeline
```bash
python orchestrator.py
```
Runs all 8 steps: Regime → Validate → Scan → Filter → Execute → Monitor → Rebalance → Report

### Monitor open positions
```bash
python orchestrator.py --monitor
```
Updates prices, moves trailing stops, triggers partial/full exits.
**Run this every 4 hours during market hours.**

### View portfolio report
```bash
python orchestrator.py --report
```
Shows positions, P&L, heat, drawdown, edge decay, and goal progress.

### Check strategy health
```bash
python orchestrator.py --edge
```
Shows which strategies are performing and which have been auto-disabled.

## Recommended Practice Schedule

### Week 1-2: Learn the System
```
Morning (before market open, ~9:15 AM ET):
  python orchestrator.py --regime        # Check market mood
  python orchestrator.py --scan          # See today's setups

After open (~10:00 AM ET):
  python orchestrator.py                 # Full pipeline (entries happen here)

Midday (~1:00 PM ET):
  python orchestrator.py --monitor       # Trail stops, check exits

Before close (~3:30 PM ET):
  python orchestrator.py --monitor       # Final stop check
  python orchestrator.py --report        # End of day review
```

### Week 3-4: Track Performance
- Review your paper trades daily
- Check: Are winners bigger than losers? (they should be ~2-3x)
- Check: Is win rate around 40-60%? (that's the sweet spot)
- Check: Are circuit breakers triggering? (if so, you're sizing too big)
- Check the edge report — are any strategies consistently losing?

### When to Go Live
You should see ALL of these before risking real money:
- [ ] 30+ paper trades completed
- [ ] Win rate between 40-60%
- [ ] Average winner is 1.5x+ the average loser
- [ ] Total R is positive (you're net profitable in R-units)
- [ ] No circuit breaker has been triggered by drawdown
- [ ] You understand every trade the system made and why

## Configuration Tuning

All parameters are in `config.py`. The defaults are conservative.
Here's what you might adjust based on paper trading results:

### If you're getting too few signals:
- Lower `min_reward_risk` from 2.0 to 1.8 (accept slightly worse R:R)
- Lower `min_scan_volume` in config (default 500K) to include more stocks
- Lower `breakout_volume_mult` from 1.5 to 1.3 (less strict volume filter)

### If you're getting too many signals:
- Raise `min_reward_risk` to 2.5 (only the best setups)
- Lower `max_open_positions` from 6 to 4
- Raise `breakout_volume_mult` to 2.0

### If drawdowns feel too large:
- Lower `risk_per_trade_pct` from 0.01 to 0.005 (0.5% per trade)
- Lower `max_total_risk_pct` from 0.06 to 0.04
- Lower `max_drawdown_pct` from 0.10 to 0.07

### If growth is too slow:
- Only after 30+ profitable paper trades
- Raise `risk_per_trade_pct` to 0.015 (1.5% per trade)
- Raise `max_total_risk_pct` to 0.08
- This increases both gains AND losses — only do this with proven edge

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | All tunable parameters |
| `orchestrator.py` | Main pipeline (run this) |
| `scanner.py` | Finds trade signals across 5 strategies |
| `risk_manager.py` | Position sizing, stops, heat tracking |
| `executor.py` | Places orders (paper or live) |
| `regime.py` | Market regime detection |
| `correlation_guard.py` | Prevents concentrated bets |
| `edge_tracker.py` | Tracks which strategies are working |
| `strategy_validator.py` | Backtests strategies before deployment |
| `data_provider.py` | Market data (Alpaca or Yahoo) |
| `trade_tracker.py` | Trade journal (CSV log) |
| `test_simulation.py` | Offline test of the full system |

## What the System Does Automatically

- **Sizes every position** so you risk exactly 1% ($100 on $10K)
- **Rejects trades** that would push total heat above 6%
- **Trails stops** up after 1R profit to lock in gains
- **Sells half** at the target, trails the rest for bigger wins
- **Moves stop to breakeven** after partial exit (free trade)
- **Pauses trading** after 4 consecutive losses (3-day cooldown)
- **Halves position sizes** at 10% drawdown
- **Stops all trading** at 20% drawdown
- **Disables strategies** that stop working (edge decay)
- **Blocks correlated bets** (won't let you load up on 4 tech stocks)
- **Adapts to market regime** (full size in bull, half in chop, quarter in bear)

## New Strategies (Video-Inspired)

### Trailing Stop + Ladder Buys
```bash
python trailing_ladder.py             # Run demo
```
Buy a stock, set a trailing stop, and automatically buy more shares at dip levels.
The floor only goes up. Ladder buys lower your average cost on dips.

### Copy Trading (Capitol Trades)
```bash
python copy_trader.py                 # Run copy cycle (dry-run)
```
Tracks US politician stock trades from Capitol Trades. Finds the most
active/successful politician and copies their buys and sells automatically.

### Wheel Strategy (Options)
```bash
python wheel_strategy.py              # Run simulated wheel cycle
```
Sell cash-secured puts → get assigned → sell covered calls → repeat.
Collects premium income at every stage. Works in any market direction.

### Automated Scheduler
```bash
python scheduler.py                   # Start all strategies on schedule
```
Runs all strategies during market hours on configurable intervals.
Generates daily summaries at market close.

### Notifications
```bash
python notifier.py                    # Demo all notification types
```
Console + file + Telegram (when configured) notifications for trades,
alerts, and daily summaries.

## Quick Start: All Strategies Running

After setting up Alpaca API keys:
```bash
# 1. Test the system works
python test_simulation.py

# 2. Start the scheduler (runs everything automatically)
python scheduler.py
```

The scheduler will run:
- Full pipeline every 4 hours
- Trailing stop monitor every 5 minutes
- Copy trader check every 60 minutes
- Wheel strategy check every 15 minutes
- Daily report at market close

## Key Files (Updated)

| File | Purpose |
|------|---------|
| `config.py` | All tunable parameters |
| `orchestrator.py` | Main pipeline (run this) |
| `scanner.py` | Finds trade signals across 5 strategies |
| `risk_manager.py` | Position sizing, stops, heat tracking |
| `executor.py` | Places orders (paper or live) |
| `regime.py` | Market regime detection |
| `correlation_guard.py` | Prevents concentrated bets |
| `edge_tracker.py` | Tracks which strategies are working |
| `strategy_validator.py` | Backtests strategies before deployment |
| `data_provider.py` | Market data (Alpaca or Yahoo) |
| `trade_tracker.py` | Trade journal (CSV log) |
| `test_simulation.py` | Offline test of the full system |
| `trailing_ladder.py` | **NEW** Trailing stop + ladder buy strategy |
| `copy_trader.py` | **NEW** Capitol Trades copy trading |
| `wheel_strategy.py` | **NEW** Wheel strategy (options) |
| `scheduler.py` | **NEW** Market hours automation |
| `notifier.py` | **NEW** Multi-channel notifications |

## What You Need to Do

- **Run the scheduler** to automate everything during market hours
- **Review the daily summary** at end of day
- **Check the edge report** weekly — are strategies still working?
- **Don't override the system** — if it says REJECT, don't force the trade
- **Journal your observations** — what patterns do you notice?
