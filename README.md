# Trading Bot
Algorithmic paper trading system for Alpaca, scanning 5 strategies across 300+ stocks.

## What it does

- Scans S&P 500 + NASDAQ-100 for setups across 5 strategies (Pullback, Breakout, MA Bounce, Sector Momentum, PowerX)
- Places bracket orders at Alpaca (entry + stop-loss + take-profit in one atomic order)
- Sizes positions using the 2% risk rule — never risks more than 2% of portfolio on any trade
- Monitors positions, trails stops, and learns from closed trades
- Adapts to market regime (bullish/sideways/bearish) — trades bigger in bull markets, smaller in bear
- Auto-disables strategies that stop performing (edge decay tracking)
- Runs unattended via macOS launchd on a daily schedule

## Quickstart

1. Clone the repo
2. `pip install -r requirements.txt`
3. Export your Alpaca keys to your shell profile (`~/.zshrc` or `~/.bashrc`):
   ```bash
   export ALPACA_API_KEY="your-key"
   export ALPACA_API_SECRET="your-secret"
   ```
4. `python test_simulation.py` — verify install
5. `python orchestrator.py --scan` — see today's signals
6. `python orchestrator.py` — run full pipeline (places paper orders)

## Architecture

`orchestrator.py` is the brain — it runs the full pipeline or individual modes via flags (`--regime`, `--scan`, `--execute`, `--monitor`, `--report`, `--edge`). `scanner.py` finds setups across all five strategies. `executor.py` places bracket orders at Alpaca. `reconcile.py` validates local state against broker positions before any trading begins. Three shell wrappers (`at_open.sh`, `monitor.sh`, `eod.sh`) are called by macOS launchd on a fixed daily schedule, covering open, midday, and end-of-day.

## The 5 Strategies

- **Pullback** — buys strong uptrends on a pullback to the 21 EMA when RSI is still healthy
- **Breakout** — buys confirmed breakouts from a consolidation pattern with rising volume
- **MA Bounce** — buys bounces off the 50-day moving average in an established uptrend
- **Sector Momentum** — buys sector ETFs when sector momentum is accelerating
- **PowerX** — triple-confirm momentum using RSI(7), MACD histogram, and Stochastic (modified PowerX setup)

## Configuration

All key knobs live in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `risk_per_trade_pct` | `0.02` | Max portfolio risk per trade (2% rule) |
| `max_open_positions` | `6` | Maximum concurrent open positions |
| `use_trailing_stops` | `False` | Enable trailing stops instead of fixed stops |

Paper mode is hardcoded via `alpaca_paper: bool = True`. Do not change this to `False` without intentional review.

See [Full Setup Guide](docs/SETUP-GUIDE.md) for complete tuning options, backtesting instructions, and strategy parameters.

## Schedule

Automated via macOS launchd (three agents in `~/Library/LaunchAgents/`):

| Time (ET) | Script | Purpose |
|---|---|---|
| 09:25 | `at_open.sh` | Wait for open, reconcile, scan, place bracket orders |
| 12:30 | `monitor.sh` | Midday: check bracket exits, time stops, reconcile |
| 16:10 | `eod.sh` | Final monitor + learning loop + daily/weekly reports |

Check schedule is loaded: `launchctl list | grep trading`

## Links

- [Full Setup Guide](docs/SETUP-GUIDE.md) — detailed setup and tuning
- [Contributing](CONTRIBUTING.md) — how to add strategies
- [Glossary](CONCEPTS.md) — plain-language trading terms
