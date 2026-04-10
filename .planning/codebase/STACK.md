# Technology Stack

**Analysis Date:** 2026-04-09

## Languages
**Primary:** Python 3.11+ — all trading logic, data processing, strategy execution

## Runtime
**Environment:** CPython 3.11+
**Package Manager:** pip, `requirements.txt` (7 core dependencies)

## Frameworks & Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| **yfinance** | >=0.2.28 | Market data (free, delayed) |
| **pandas** | >=2.0 | Data frames, OHLCV processing, returns analysis |
| **numpy** | >=1.24 | Numerical computation for indicators, correlations |
| **backtesting** | >=0.3.3 | Strategy backtesting engine |
| **riskfolio-lib** | >=4.0 | Portfolio optimization, correlation analysis |
| **matplotlib** | >=3.7 | Charts and performance visualization |
| **alpaca-trade-api** | >=3.0 | Live/paper trading, real-time data (optional) |

## Data Pipeline

- **Source 1:** Alpaca REST API (real-time if `ALPACA_API_KEY` set)
- **Source 2:** Yahoo Finance (fallback, 15-min delayed)
- **Caching:** Local CSV files in `.data_cache/` — keyed by ticker + data hash to avoid re-downloads

See `data_provider.py:DataProvider` — pluggable backend supports swapping data sources.

## Core Modules

All in `/Users/bopeterlaanen/trading/`:

| Module | Purpose |
|--------|---------|
| `config.py` | `AgentConfig` dataclass — 50+ parameters for position sizing, risk, strategy thresholds |
| `data_provider.py` | Abstract `DataProvider` with Alpaca, Yahoo Finance, CSV cache backends |
| `scanner.py` | Market scanning — PowerX, Pullback, Consolidation strategies |
| `strategy_validator.py` | Backtest validation before live deployment |
| `orchestrator.py` | Main pipeline: regime → validate → scan → filter → execute → monitor → optimize |
| `executor.py` | Order submission (Alpaca or simulated) + position lifecycle |
| `risk_manager.py` | Position sizing (1R rule), trailing stops, portfolio constraints |
| `regime.py` | Market regime detection (bullish/sideways/bearish) |
| `correlation_guard.py` | Sector exposure checks, position correlation limits |
| `edge_tracker.py` | Win rate, strategy ranking, disabled-strategy management |
| `trade_tracker.py` | Trade logging (CSV), portfolio value history |
| `portfolio_optimizer.py` | Position rebalancing, volatility analysis |
| `universe.py` | Dynamic ticker universe (~300-500 liquid S&P 500 / NASDAQ-100) |
| `backtest_momentum.py` | Standalone momentum strategy backtest |

## Configuration

All parameters in `config.py` → `AgentConfig`:
- **Capital:** Starting $10K, target $25K
- **Risk:** 1% per trade, 6% max portfolio heat
- **Strategies:** PowerX (7-RSI), Pullback, Consolidation breakout
- **Position limits:** Max 10% per position, 6 concurrent, 15% cash reserve

## Execution Modes

1. **Simulated** (default) — No API keys; Yahoo Finance data; fake order IDs
2. **Paper Trading** — Alpaca free account; real-time data; fake money
3. **Live Trading** — Real Alpaca account; real capital (config switch)

## Platform Requirements

**Development:** macOS (zsh), Linux, or Windows with Python 3.11+
**Production:** Any system with Python 3.11, network access to Alpaca/Yahoo Finance APIs
