# Technology Stack

**Analysis Date:** 2026-04-12

## Languages
**Primary:** Python 3.11+ (Python 3.9+ supported; 3.11 required for shell wrapper in `at_open.sh`)

## Runtime
**Environment:** CPython 3.11+
**Package Manager:** pip (from `requirements.txt`)
**Version Constraint:** Minimum versions only (yfinance>=0.2.28, pandas>=2.0, numpy>=1.24, etc.)

## Frameworks & Libraries

| Package | Version | Purpose |
|---------|---------|---------|
| alpaca-trade-api | >=3.0 | Bracket orders, position queries, account state (REST v2 client) |
| yfinance | >=0.2.28 | Free market data fallback (15-min delayed, no auth required) |
| pandas | >=2.0 | OHLCV bars, portfolio calculations, trade history |
| numpy | >=1.24 | Numerical computation for RSI, MACD, Stochastic indicators |
| backtesting | >=0.3.3 | Strategy validation engine (`strategy_validator.py`) |
| riskfolio-lib | >=4.0 | Portfolio correlation analysis (`correlation_guard.py`) |
| matplotlib | >=3.7 | Chart generation for reports |
| requests | >=2.31 | HTTP requests (general use) |
| beautifulsoup4 | >=4.12 | HTML parsing for market data |
| lxml | >=5.0 | XML/HTML parsing backend |
| pytz | >=2023.3 | Timezone handling (ET for market hours) |

## Data Pipeline

**Data Sources (per `data_provider.py`):**
1. **Alpaca** — If `ALPACA_API_KEY` set: real-time bars via `get_bars(ticker, '1Day', feed='iex')`
2. **Yahoo Finance** — Fallback if Alpaca missing: delayed bars via `yfinance.download()`
3. **Local CSV Cache** — `.data_cache/` keyed by ticker + hash; backtesting data persists indefinitely

**State Persistence (JSON):**
- `positions.json` — open positions (ticker, shares, entry_price, stop, target, strategy)
- `order_log.json` — order fills from Alpaca (order_id, symbol, filled_avg_price, timestamp)
- `edge_tracker.json` — per-strategy P&L and auto-disable flags
- `learning_state.json` — circuit breaker state (regime, consecutive losses, comeback counter)
- `last_run.json` — timestamp + exit reason from orchestrator

**Trade Output (CSV):**
- `trades.csv` — closed trades (entry_date, entry_price, exit_date, exit_price, P&L, R:R, strategy, regime)
- `portfolio_value.csv` — daily snapshots (date, total_value, cash, open_positions_value)

## Core Modules

| Module | Purpose | Key Dependencies |
|--------|---------|---|
| `orchestrator.py` | Master pipeline: regime → validate → scan → execute → monitor → optimize | config, scanner, executor, risk_manager |
| `config.py` | Single truth for all parameters (risk, position sizing, strategy thresholds) | dataclasses |
| `data_provider.py` | Abstract data source (Alpaca / Yahoo / CSV cache) | alpaca_trade_api, yfinance, pandas |
| `executor.py` | Bracket order submission, fill polling, slippage rejection, position lifecycle | alpaca_trade_api, config |
| `reconcile.py` | Compares local positions.json against Alpaca list_positions() | alpaca_trade_api, risk_manager |
| `risk_manager.py` | Position sizing (1R rule), drawdown circuit breakers, max risk cap | config |
| `scanner.py` | Signal generation (PULLBACK, BREAKOUT, MA_BOUNCE, SECTOR_MOMENTUM, POWERX) | data_provider, config |
| `strategy_validator.py` | Backtest signals before trading (uses backtesting library) | backtesting |
| `regime.py` | Market sentiment detection (bullish/sideways/bearish) | data_provider |
| `correlation_guard.py` | Sector overlap checks (max 2 sectors, correlation limits) | riskfolio_lib, config |
| `edge_tracker.py` | Track per-strategy win rate; auto-disable if underperforming | json |
| `trade_tracker.py` | Log trades and portfolio snapshots to CSV | csv, pandas |
| `universe.py` | Build dynamic scan universe (~300-500 liquid stocks) | data_provider, config |

## Configuration

**Single source of truth:** `config.py` contains `AgentConfig` dataclass with ~50 parameters:
- Capital: starting $10K, target $25K
- Risk: 1% per trade, 6% max portfolio heat (`max_total_risk_pct`)
- Min R:R: 2.0 (slippage threshold 1.5 in `executor.py`)
- Position limits: max 10% per position, 6 concurrent, 15% cash reserve
- Trailing stops: activate at 1R profit, trail 3% behind high
- Strategy thresholds: PULLBACK RSI (35-55), breakout volume 1.5x, PowerX RSI(7) + MACD + Stochastic
- Backtesting: min Sharpe 0.5, min win rate 40%, min avg R:R 1.8

**Environment Variables:**
- `ALPACA_API_KEY`, `ALPACA_API_SECRET` — required (sourced from `~/.zshrc` by shell wrappers)
- `TRADING_STATE_DIR` — optional override for state file location (default: working dir)
- `ALPACA_OPTIONS_ENABLED` — optional, enables Wheel Strategy live options (default: simulated)

## Execution Modes

1. `python orchestrator.py` — Full pipeline (regime → validate → scan → execute → monitor)
2. `python orchestrator.py --scan` — Scan only (no orders)
3. `python orchestrator.py --validate` — Backtest all strategies
4. `python orchestrator.py --monitor` — Monitor exits and trailing stops
5. `python orchestrator.py --report` — Portfolio dashboard
6. `python orchestrator.py --regime` — Market sentiment only
7. `python orchestrator.py --edge` — Strategy performance rankings

**Scheduled via launchd (macOS):**
- 09:25 ET: `at_open.sh` → full pipeline
- 12:30 ET: `monitor.sh` → monitor only
- 16:10 ET: `eod.sh` → full pipeline + learning loop + reports

## Platform Requirements

- **OS:** macOS (launchd scheduler required; Linux/WSL would need systemd replacement)
- **Python:** 3.11+ recommended (3.9+ functional)
- **Broker:** Alpaca Markets (paper: https://paper-api.alpaca.markets)
- **Network:** Required for real-time data and order execution
- **Timezone:** US Eastern (09:30–16:00 ET market hours hardcoded)
