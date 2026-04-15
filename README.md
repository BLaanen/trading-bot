# Trading Bot

An automated stock trading system that scans the market, picks trades, places orders, and manages risk — all without you watching screens. It runs on your Mac, trades through Alpaca's paper trading platform, and learns from its own results over time.

## Before you start

This system trades with **paper money only**. Paper trading means you're using a simulated brokerage account with fake dollars but real market prices. Your orders execute against real stock data, so the results are realistic, but no actual money is at risk.

**Why start with paper trading?** Because no trading system — no matter how well tested — should touch real money before you've watched it run for weeks or months. Paper trading lets you see how the strategies perform, understand what the system does and why, and build confidence (or discover problems) with zero financial risk. Think of it as a flight simulator for trading.

This codebase is deliberately locked to paper mode. There is no "flip a switch to go live" option. Going live would require intentional code changes, a different Alpaca account, and a conversation about whether the system has earned that trust. That's a future decision, not a setup option.

## What it actually does

Every trading day, this system:

1. **Checks the market mood** — is the broad market trending up, sideways, or down? This determines how aggressive the system should be.
2. **Scans 300+ stocks** looking for specific patterns across 5 strategies (pullbacks, breakouts, moving average bounces, sector momentum, and a momentum triple-check called PowerX).
3. **Filters the results** — rejects trades with bad risk/reward, blocks too much exposure to one sector, and respects portfolio-wide risk limits.
4. **Places bracket orders** — each buy goes to Alpaca as a package deal: the buy itself, plus an automatic stop-loss (exit if you're wrong) and take-profit (exit if you're right). The broker handles the exits.
5. **Monitors positions** during the day — checks if any exits have fired, updates trailing stops if enabled, and reconciles local records against the broker.
6. **Learns from closed trades** — tracks which strategies are actually making money, auto-disables ones that stop working, and generates reports.

All of this runs on a daily schedule via macOS launchd. You set it up once and it runs itself Monday through Friday during US market hours.

## How risk management works

The core principle is simple: **win about half your trades, but make winners bigger than losers**. If you win 50% of the time and winners are 2.5x the size of losers, you're profitable.

The system enforces this mechanically:

- **Fixed risk per trade** — every trade risks exactly 2% of your portfolio. The share count adjusts so the dollar risk stays constant regardless of stock price.
- **Minimum reward-to-risk ratio** — won't take a trade unless the potential reward is at least 2x the potential loss.
- **Portfolio heat cap** — limits total open risk to 12% of the portfolio. If every stop hit at once, you'd lose at most 12%.
- **Circuit breakers** — after 4 consecutive losses, the system pauses for 3 days. At 10% drawdown, it halves position sizes. At 20%, it stops trading entirely.
- **Sector limits** — won't pile into one sector. If you already hold 2 tech stocks, it won't buy a third.

For a deeper explanation of every concept used in this system (R-multiples, bracket orders, stops, indicators, regime detection, edge tracking), read **[CONCEPTS.md](CONCEPTS.md)** — it explains everything in plain language without assuming trading knowledge.

## What markets does this cover?

This system trades **US stocks and ETFs** through Alpaca. That includes companies listed on the NYSE and NASDAQ — the two main US stock exchanges.

Alpaca also offers about 700 **ADRs** (American Depositary Receipts). These are shares of international companies — like Toyota, Nestlé, or Samsung — that trade on US exchanges during US hours. So you can trade some international companies, but through their US-listed ADR, not directly on the Tokyo or Swiss exchange.

What's **not** included:
- European or Asian stock exchanges directly
- Forex (currency trading)
- Futures or commodities
- Crypto (Alpaca supports it, but this system doesn't use it)

**Paper trading works from any country** — there are no geographic restrictions. If you later want to trade with real money, live trading from outside the US requires verification with Alpaca.

All scanning and trading happens during **US market hours**: 9:30 AM to 4:00 PM Eastern Time, Monday through Friday.

## Getting started

### What you need

- A Mac (the scheduling uses macOS launchd)
- Python 3.11 or newer
- An Alpaca account (free — no deposit needed for paper trading)

### Setup

```bash
git clone <this-repo> && cd trading
./setup.sh
```

The setup script walks you through everything step by step:

1. **Checks your Python version** — tells you how to install 3.11+ if you don't have it
2. **Installs dependencies** — the Python packages the system needs (pandas, yfinance, alpaca SDK, etc.)
3. **Helps you create Alpaca API keys** — walks you through signing up at [alpaca.markets](https://app.alpaca.markets/signup) and generating paper trading API keys, then saves them to your shell profile
4. **Chooses your starting amount** — Alpaca gives you $100K in paper money, but that's unrealistic. You pick a budget the system actually uses for position sizing and risk management.
5. **Verifies the connection** — confirms your keys work and shows your paper account balance
6. **Runs the test suite** — makes sure everything installed correctly

After setup completes, try these commands to explore:

```bash
python3.11 orchestrator.py --scan      # See what setups the scanner finds today
python3.11 orchestrator.py --report    # View the portfolio dashboard
python3.11 orchestrator.py --regime    # Check the current market regime
python3.11 orchestrator.py --edge      # See which strategies are performing
```

When you're ready to let it trade (with paper money), run the full pipeline:

```bash
python3.11 orchestrator.py             # Scan → filter → place orders → monitor
```

To set up the daily automated schedule so it runs by itself, see the [Full Setup Guide](docs/SETUP-GUIDE.md).

## The 5 strategies

Each strategy looks for a different pattern. The system runs all five every scan and combines the results.

| Strategy | What it looks for |
|----------|-------------------|
| **Pullback** | A stock in a strong uptrend that dips temporarily — buying the dip in an existing trend |
| **Breakout** | A stock that's been trading sideways for weeks and suddenly breaks out on high volume |
| **MA Bounce** | A stock that touches its 50-day moving average and bounces — a support level that big institutions defend |
| **Sector Momentum** | Whole sectors (tech, energy, real estate) gaining momentum — broader bets instead of individual stock picks |
| **PowerX** | Three separate momentum indicators all agreeing at once — a high-conviction signal with fixed stop/target percentages |

## Configuration

Key settings live in `config.py`. The defaults are conservative and designed for paper trading:

| Setting | Default | What it controls |
|---------|---------|------------------|
| `risk_per_trade_pct` | `0.02` | How much of your portfolio to risk on each trade (2%) |
| `max_open_positions` | `6` | Maximum number of trades open at once |
| `use_trailing_stops` | `False` | Whether stops move up to lock in profits as a trade runs |
| `alpaca_paper` | `True` | Paper mode — hardcoded on, don't change this |

## Project structure

| File | What it does |
|------|--------------|
| `orchestrator.py` | The brain — runs the full pipeline or individual steps via flags |
| `scanner.py` | Scans stocks for setups across all 5 strategies |
| `executor.py` | Places bracket orders, monitors fills, handles slippage rejection |
| `risk_manager.py` | Position sizing, trailing stops, portfolio health checks |
| `reconcile.py` | Compares local state against broker — refuses to trade on mismatch |
| `config.py` | All tunable parameters in one place |
| `universe.py` | Builds and caches the list of stocks to scan |
| `correlation_guard.py` | Blocks overexposure to a single sector |
| `CONCEPTS.md` | Plain-language glossary of every trading term used here |

## For Collaborators (using Claude Code)

This repo is designed to work with [Claude Code](https://claude.ai/claude-code), an AI coding assistant that runs in your terminal. Claude Code reads the system's configuration files automatically and understands the trading pipeline, so you can ask it questions or give it tasks in plain English.

### Starting a session

When you open Claude Code in this repo, it reads `CLAUDE.md` automatically and checks the system status — open positions, today's P&L, scheduler health. You don't need to tell it anything; it starts by showing you what's going on.

### Useful commands

These slash commands are shortcuts for common tasks:

| Command | What it does |
|---------|--------------|
| `/status` | What's open, today's P&L, system health |
| `/edge-check` | Which strategies are earning vs fading |
| `/run-scan` | Run the scanner manually right now |
| `/weekly-brief` | Friday-style summary of the week |
| `/what-happened-today` | Narrative of today's activity |
| `/why-this-trade` | Explain a specific trade |
| `/pause-trading` / `/resume-trading` | Stop/start the automated schedule |

### When to clear a session

Claude Code sessions accumulate context as you work. If a session gets long or you're switching topics, type `/clear` to start fresh. Claude re-reads the system state files automatically, so nothing is lost — the ground truth lives in `positions.json`, `trades.csv`, and the log files, not in conversation memory.

### What persists across sessions

Positions, trade history, portfolio value, edge tracking, and configuration all live in files on disk. Clearing a session or starting a new one doesn't affect any of this. The only thing lost on `/clear` is the conversation itself.

## Daily schedule

Once set up, the system runs itself via three scheduled jobs:

| Time (ET) | What happens |
|-----------|--------------|
| 09:25 AM | **Morning scan** — wait for market open, reconcile, scan for setups, place bracket orders |
| 12:30 PM | **Midday check** — check if any exits fired, update trailing stops, reconcile |
| 04:10 PM | **End of day** — final monitor, run the learning loop, generate daily/weekly reports |

US market hours are 9:30 AM to 4:00 PM Eastern, Monday through Friday.

## Learn more

- **[CONCEPTS.md](CONCEPTS.md)** — the most important file if you're new. Explains every trading concept in plain language.
- **[Full Setup Guide](docs/SETUP-GUIDE.md)** — detailed installation, launchd setup, tuning strategies, backtesting.
- **[Contributing](CONTRIBUTING.md)** — how to add a 6th strategy or modify existing ones.
