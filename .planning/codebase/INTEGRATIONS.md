# External Integrations

**Analysis Date:** 2026-04-12

## APIs & External Services

### Alpaca Markets
**SDK:** `alpaca-trade-api>=3.0` (Python REST client)
**Auth:** `ALPACA_API_KEY` + `ALPACA_API_SECRET` environment variables
**Base URL:** `https://paper-api.alpaca.markets` (paper mode, hardcoded in `config.py`)

**Used in:**
- `executor.py` — bracket order submission and fill polling
- `data_provider.py` — historical bars via `get_bars(ticker, '1Day', feed='iex')`
- `reconcile.py` — position state reconciliation before trading

**Endpoints:**
- `client.get_account()` — verify auth, fetch cash/equity
- `client.submit_order(symbol, qty, side='buy', order_class='bracket', stop_loss, take_profit)` — entry bracket order (buy + stop-loss child + take-profit child)
- `client.get_order(order_id)` — poll for fill status and `filled_avg_price`
- `client.cancel_order(order_id)` — cancel bracket exit legs
- `client.list_positions()` — fetch current positions for reconciliation
- `client.get_bars(ticker, '1Day', start, end, feed='iex')` — historical 1D bars

**Key Behavior:**
- All buy orders are **bracket orders** (buy + stop-loss + take-profit children)
- After fill, Python polls `get_order()` for `filled_avg_price` and uses THAT as entry (not the target price)
- If fill degrades R:R below 1.5, position is immediately closed with SLIPPAGE_REJECT log
- Broker handles stop-loss and take-profit exits; Python is backup monitor

### Yahoo Finance
**SDK:** `yfinance>=0.2.28`
**Auth:** None (public API)
**Purpose:** Fallback market data when Alpaca unavailable or API key not set

**Used in:**
- `data_provider.py` — YahooProvider backend

**Calls:**
- `yfinance.download(ticker, period='5d', progress=False)` — latest close price
- `yfinance.download(tickers, period='5d')` — bulk prices
- `yfinance.download(ticker, start=..., end=...)` — historical bars by date range

**Limitations:**
- 15-20 min delay during market hours
- Rate limited on heavy use
- End-of-day bars only (no intraday)
- Never used if `ALPACA_API_KEY` is set

## Data Storage

### Local File State (JSON)
**Location:** Working directory (configurable via `TRADING_STATE_DIR` env var)

| File | Purpose | Updated | Read By |
|------|---------|---------|---------|
| `positions.json` | Current open positions: ticker, shares, entry_price, stop, target, strategy, trailing_high | Each cycle | risk_manager, executor, reconcile |
| `order_log.json` | Alpaca order fills with order IDs, timestamps, fill prices (append-only) | On order fill | executor, trade_tracker |
| `edge_tracker.json` | Per-strategy P&L, win rate, consecutive losses, auto-disable flag | Trade close | scanner, orchestrator |
| `learning_state.json` | Regime state, consecutive loss counter, comeback trade counter | Each cycle | regime, executor, orchestrator |
| `last_run.json` | Timestamp + exit reason (for debugging) | End of run | (logging only) |

### Trade History (CSV)
**Location:** Working directory (append-only)

| File | Columns | Written By | Read By |
|------|---------|-----------|---------|
| `trades.csv` | entry_date, entry_price, exit_date, exit_price, shares, P&L, R:R, strategy, regime, notes | trade_tracker | analysis scripts, reports |
| `portfolio_value.csv` | date, total_value, cash, positions_value | trade_tracker | drawdown analysis, Sharpe calculation |

### Market Data Cache
**Location:** `.data_cache/` directory
**Key Scheme:** `{ticker}_{sha256(start+end+period)}.csv`
**Lifecycle:**
- Backtesting data (end date in past): cached indefinitely
- Recent data: checked for staleness; auto-refreshed if >1 day old

**Used by:** `data_provider.py` CachedProvider backend

### Universe Cache
**File:** `.universe_cache.json`
**Contents:** ~300–500 liquid tickers from S&P 500 + NASDAQ-100
**Refreshed:** Weekly by `universe.py`
**Fallback:** Core ETFs in `config.py` if cache missing

## CI/CD & Deployment

### Scheduler (macOS launchd)
**Three agents in `~/Library/LaunchAgents/`:**

| Agent ID | Script | Time (ET) | Command |
|----------|--------|-----------|---------|
| `com.bopeterlaanen.trading.at_open` | `at_open.sh` | 09:25 | Full pipeline: reconcile → scan → execute |
| `com.bopeterlaanen.trading.monitor` | `monitor.sh` | 12:30 | Monitor only: check exits, trailing stops |
| `com.bopeterlaanen.trading.eod` | `eod.sh` | 16:10 | Full pipeline + learning loop + reports |

**Verify loaded:** `launchctl list \| grep trading`
**Pause:** `launchctl unload ~/Library/LaunchAgents/com.bopeterlaanen.trading.*.plist`
**Resume:** `launchctl load ~/Library/LaunchAgents/com.bopeterlaanen.trading.*.plist`

### Shell Wrappers
**`at_open.sh`, `monitor.sh`, `eod.sh`:**
- Extract `ALPACA_API_KEY` and `ALPACA_API_SECRET` from `~/.zshrc` if not in environment
- Run Python with appropriate flags (e.g., `python orchestrator.py --monitor`)
- Tee output to timestamped log in `logs/launchd_*.log`

**No external CI.** Tests run locally:
- `python test_simulation.py` — offline end-to-end with synthetic data
- `python test_executor.py` — bracket order, slippage, reconciliation tests

## Environment Configuration

### Required (for Paper/Live Trading)
```
ALPACA_API_KEY       # API key ID from Alpaca dashboard
ALPACA_API_SECRET    # API secret (shown once at account creation)
```
**Source:** `~/.zshrc` (shell wrappers extract these)

### Optional
- `TRADING_STATE_DIR` — override state file location (default: working dir); used by tests
- `ALPACA_OPTIONS_ENABLED` — set to `"1"`, `"true"`, or `"yes"` to enable Wheel Strategy live options (default: simulated)

### Secrets Management
- **No `.env` file.** All env vars in shell profile (`~/.zshrc`).
- **Paper mode hardcoded:** `config.py` has `alpaca_paper: bool = True`
  - Must change Python code + env to enable live trading (safety-first design)
- **Audit trail:** All trades logged locally to `order_log.json` and `trades.csv` (no cloud logging)

### Configuration Files
- `config.py` — AgentConfig dataclass with 50+ parameters (risk, position sizing, strategy thresholds)
- `watchlist.json` — user-maintained tickers (fallback if dynamic universe not available)
- `.universe_cache.json` — cached scan universe, refreshed weekly by `universe.py`
