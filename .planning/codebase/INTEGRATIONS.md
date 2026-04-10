# External Integrations

**Analysis Date:** 2026-04-09

## APIs & External Services

### Market Data & Trading

**Alpaca Markets** — https://alpaca.markets
- Real-time OHLCV data and order execution
- Used in: `data_provider.py`, `executor.py`
- SDK: `alpaca-trade-api>=3.0`
- Auth: `ALPACA_API_KEY`, `ALPACA_API_SECRET` (env vars)
- Modes: Paper trading (free, $100K fake capital) or Live (real money)
- Base URL: `https://paper-api.alpaca.markets` (paper) or `https://api.alpaca.markets` (live)

**Yahoo Finance** — Free market data
- OHLCV fallback when Alpaca not configured
- Used in: `data_provider.py` (YahooProvider backend)
- SDK: `yfinance>=0.2.28`
- Auth: None (public API)
- Limitations: ~15-minute delay, rate-limited

## Data Storage

**Local File System:**
- **Position state:** `positions.json` — current open positions (JSON)
- **Order log:** `order_log.json` — execution history (JSON)
- **Trade tracker:** `trades.csv` — all executed trades with entry/exit/P&L
- **Portfolio value:** `portfolio_value.csv` — daily portfolio value history
- **Market data cache:** `.data_cache/` — ticker CSV files keyed by hash to avoid re-downloads
- **Universe cache:** `.universe_cache.json` — dynamic ticker list (refreshed weekly)
- **Last run state:** `last_run.json` — timestamp + execution mode

Location: `/Users/bopeterlaanen/trading/` (all local, no cloud backend)

**Database:** None. All state is file-based (JSON/CSV) for portability and auditability.

## CI/CD & Deployment

**None configured.** Manual execution via:
```bash
python orchestrator.py              # Full pipeline
python orchestrator.py --scan       # Signals only
python orchestrator.py --validate   # Backtest validate
python orchestrator.py --report     # Performance report
```

No GitHub Actions, no cloud deployment. Local-only.

## Environment Configuration

### Required Variables (for Paper/Live Trading)
```
ALPACA_API_KEY       # Alpaca account API key ID
ALPACA_API_SECRET    # Alpaca account secret (shown once at creation)
```

Set in shell profile (`~/.zshrc`, `~/.bashrc`) — see `SETUP-GUIDE.md`.

### Optional Variables
None — all strategy parameters hardcoded in `config.py`.

### Secrets Management
- Keys stored in shell environment only
- No `.env` files checked into repo
- See `SETUP-GUIDE.md` for setup instructions
