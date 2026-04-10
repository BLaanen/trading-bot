# Codebase Structure

**Analysis Date:** 2026-04-09

## Directory Layout

```
/Users/bopeterlaanen/trading/
├── .planning/                    # Planning documents (excluded from code)
├── orchestrator.py              # Main entry point: full pipeline coordinator
├── config.py                    # AgentConfig: all trading parameters
│
├── Market Data & Analysis
│  ├── data_provider.py          # Unified data layer (Yahoo, Alpaca, CSV)
│  ├── scanner.py                # Signal generation (6 strategies)
│  ├── regime.py                 # Market regime detection (bullish/sideways/bearish)
│  └── universe.py               # Dynamic ticker universe builder
│
├── Risk & Position Management
│  ├── risk_manager.py           # Position sizing, portfolio constraints
│  ├── correlation_guard.py      # Sector correlation & clustering
│  └── portfolio_optimizer.py    # ETF rebalancing
│
├── Execution
│  ├── executor.py               # Order submission, position tracking
│  └── trade_tracker.py          # Trade logging, performance stats
│
├── Strategy Validation
│  ├── strategy_validator.py     # Backtest strategies before trading
│  ├── edge_tracker.py           # Edge decay, strategy ranking
│  └── backtest_momentum.py      # Historical momentum strategy backtest
│
├── State Files (runtime)
│  ├── positions.json            # Current open positions (source of truth)
│  ├── order_log.json            # All execution events
│  ├── trade_log.json            # Entry/exit records
│  ├── last_run.json             # Pipeline state between runs
│  └── .data_cache/              # OHLCV cache (CSV per ticker)
│
└── Docs
   ├── SETUP-GUIDE.md           # Installation, API key setup
   ├── TRADING-PLAN.md          # Strategy descriptions, parameters
   ├── AUTOMATION-PLAN.md       # Scheduled execution plan
   └── requirements.txt         # Python dependencies
```

## Directory Purposes

**Root:** All Python modules are at root; no src/ subdirectory.

**`.planning/codebase/`:** Mapping documents (ARCHITECTURE.md, STRUCTURE.md, STACK.md, etc.)

**`.data_cache/`:** Ticker→CSV cache for offline backtesting. Keyed by hash(ticker+period).

## Key File Locations

**Entry Points:**
- `orchestrator.py` — Main pipeline; run `python orchestrator.py [--scan|--monitor|--validate|--report|--regime|--rebalance|--edge]`

**Configuration:**
- `config.py` — AgentConfig dataclass; all parameters (risk per trade, max positions, etc.)

**Core Logic by Responsibility:**
- **Data:** `data_provider.py` (abstraction), `scanner.py` (signals), `universe.py` (universe)
- **Risk:** `risk_manager.py` (sizing, constraints), `correlation_guard.py` (sector logic)
- **Execution:** `executor.py` (orders), `trade_tracker.py` (logging)
- **Validation:** `strategy_validator.py` (backtests), `edge_tracker.py` (performance)
- **Regime:** `regime.py` (market state detection)

**State Files (JSON):**
- `positions.json` — Current open positions (PortfolioState); source of truth
- `order_log.json` — All order events (entries, exits, errors)
- `trade_log.json` — Closed trade records (useful for win rate / edge tracking)
- `last_run.json` — Timestamp of last pipeline execution

## Where to Add New Code

**New Strategy:**
1. Add method to `Scanner` class in `scanner.py` (e.g., `_scan_volatility_burst()`)
2. Add to `STRATEGY_RUNNERS` dict in `run_full_scan()` function
3. Register in `strategy_validator.py` — add new entry to `STRATEGY_CONFIGS`
4. Update `config.py` if adding new parameters (e.g., lookback periods)

**New Feature (e.g., Options, Crypto, Futures):**
- Extend `DataProvider` in `data_provider.py` with new backend
- Add new scanner method for asset class
- Extend `PortfolioState` in `risk_manager.py` to track new position type

**New Risk/Filter Check:**
- Add method to `PortfolioState` class in `risk_manager.py` (e.g., `check_vega_exposure()`)
- Call from `step_filter()` in `orchestrator.py`

**Tests:**
- Add test in `test_simulation.py` (only one test file; comprehensive simulation approach)
- Example: test strategy backtests, edge decay, regime detection

## Configuration Pattern

All trading parameters live in `config.py`:
- Capital: `starting_capital`, `target_capital`
- Risk: `risk_per_trade_pct`, `max_total_risk_pct`, `min_reward_risk`
- Position: `max_position_pct`, `max_open_positions`, `max_sector_exposure`
- Strategy: `pullback_lookback`, `breakout_lookback`, `rsi_oversold`, etc.

Pass `AgentConfig` instance to every function; never read config directly.
