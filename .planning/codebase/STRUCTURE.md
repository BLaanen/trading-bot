# Codebase Structure

**Analysis Date:** 2026-04-12

## Directory Layout

```
/Users/bopeterlaanen/trading/
├── .planning/codebase/              # Mapping documents (ARCHITECTURE.md, etc.)
├── .claude/commands/                # Slash command shortcuts
├── .data_cache/                     # OHLCV cache (CSV per ticker, keyed by hash)
│
├── Core Pipeline (root)
│  ├── orchestrator.py               # Main entry point: regime → validate → scan → filter → execute → monitor
│  ├── config.py                     # AgentConfig: all trading parameters (risk, position, strategy)
│  ├── reconcile.py                  # Alpaca reconciliation: compare local vs broker state before trading
│
├── Market Data & Signals
│  ├── data_provider.py              # Unified data layer (Yahoo, Alpaca, CSV cache)
│  ├── scanner.py                    # 5 core strategies: PULLBACK, BREAKOUT, MA_BOUNCE, SECTOR_MOMENTUM, POWERX
│  ├── regime.py                     # Market condition detection (TRENDING_UP, SIDEWAYS, TRENDING_DOWN)
│  └── universe.py                   # Dynamic S&P 500 / NASDAQ-100 universe builder (~300-500 tickers)
│
├── Risk & Position Management
│  ├── risk_manager.py               # Position sizing (1R rule), PortfolioState, trailing stops
│  ├── correlation_guard.py          # Sector clustering, new-position correlation checks
│  └── analysis/
│     └── portfolio_optimizer.py    # ETF rebalancing (core_etfs list)
│
├── Execution & Monitoring
│  ├── executor.py                   # Bracket order lifecycle: entry → monitor → exit
│  │                                  # Includes slippage rejection (R:R < 1.5 → immediate sell)
│  ├── trade_tracker.py              # Trade logging (entry/exit records), performance stats
│  └── at_open.py                    # Shell wrapper integration (used by at_open.sh)
│
├── Strategy Validation & Learning
│  ├── strategy_validator.py         # Backtest strategies; determine which to approve for scanning
│  ├── edge_tracker.py               # Edge decay tracking, strategy ranking, auto-disable
│  └── analysis/
│     ├── learning_loop.py           # Post-day autopsy: journal, lessons, hypotheses, pattern memory
│     ├── weekly_report.py           # Weekly P&L, strategy win rates, regime performance
│     ├── hypothesis_generator.py    # Generate new hypotheses from trade data
│     ├── adaptive_config.py         # Propose config changes based on edge decay
│     ├── backtest_momentum.py       # Historical momentum strategy backtest
│     └── backtest_slippage.py       # Slippage analysis across strategies
│
├── Standalone Strategies (not in core scanner)
│  └── strategies/
│     ├── copy_trader.py             # Follow politician trades (SeekingAlpha)
│     ├── trailing_ladder.py         # Dollar-cost averaging on dips
│     └── wheel_strategy.py          # Options: sell puts → assignment → sell calls
│
├── Legacy (deprecated)
│  └── legacy/
│     ├── scheduler.py               # Old Python-level scheduler (replaced by launchd)
│     ├── run_all.py                 # Old multi-script runner
│     └── notifier.py                # Old notification system
│
├── Testing
│  ├── test_simulation.py            # Comprehensive end-to-end offline test (no Alpaca required)
│  └── test_executor.py              # Bracket order, slippage, reconciliation tests
│
├── State Files (runtime, gitignored)
│  ├── positions.json                # Current open positions (PortfolioState) — source of truth
│  ├── order_log.json                # All execution events (submissions, fills, cancellations, errors)
│  ├── trade_log.json                # Entry/exit records (used by learning loop)
│  ├── trades.csv                    # Closed trades with P&L, win rate, strategy labels
│  ├── learning_state.json           # Learning loop state (last run date, pattern hash)
│  ├── portfolio_value.csv           # Daily portfolio value time series
│  ├── last_run.json                 # Pipeline execution timestamp and state flags
│  ├── trade_journal.md              # (Learning) Append-only chronological trade log
│  ├── lessons.md                    # (Learning) Distilled insights
│  ├── hypotheses.md                 # (Learning) Active experiment hypotheses
│  ├── patterns.json                 # (Learning) Pattern memory (strategy × regime × outcome)
│  └── experiments.json              # (Learning) Parameter experiments with results
│
├── Docs & Config
│  ├── CLAUDE.md                     # Session guide (read first: ground truth on how to use repo)
│  ├── CONCEPTS.md                   # Plain-language glossary (trading terms)
│  ├── TRADING-PLAN.md               # Aspirational roadmap ($10K → $100K)
│  ├── SETUP-GUIDE.md                # Manual installation & run instructions
│  ├── AUTOMATION-PLAN.md            # (Stale) proposed VPS/GitHub Actions setup
│  ├── IMPROVEMENT-PLAN.md           # Ongoing improvements list
│  ├── requirements.txt              # Python 3.11+ dependencies
│  ├── .nvmrc                        # Node version (if applicable)
│  └── watchlist.json                # Tracked tickers for sector ETF rebalancing
│
└── Shell Wrappers (launchd scheduled)
   ├── at_open.sh                   # 09:25 ET: reconcile → scan → execute
   ├── monitor.sh                   # 12:30 ET: monitor exits, trailing stops, reconcile
   └── eod.sh                       # 16:10 ET: final monitor, learning loop, daily/weekly report
```

## Directory Purposes

**Root:** All core Python modules at root (no src/ subdirectory). Entry point is `orchestrator.py`.

**`analysis/`:** Post-trade learning and adaptive configuration. Runs after market close.

**`strategies/`:** Standalone strategies (copy trading, options wheel, ladder buys) — not in core scanner.

**`legacy/`:** Deprecated code (old scheduler, notifier) — kept for reference, not used.

**`.planning/codebase/`:** Mapping documents (read by plan-work index).

**`.data_cache/`:** OHLCV CSV cache, keyed by hash(ticker+period). Survives between runs for offline backtesting.

## Key File Locations

**Entry Points:**
- `orchestrator.py` — Main pipeline; run with `python orchestrator.py [--scan|--monitor|--validate|--report|--regime|--rebalance|--edge]`

**Configuration:**
- `config.py` — AgentConfig dataclass; all parameters (capital, risk per trade, max positions, strategy params, Alpaca settings)

**Core Logic by Responsibility:**
- **Data:** `data_provider.py`; **Signals:** `scanner.py` (5 core strategies); **Universe:** `universe.py`
- **Risk:** `risk_manager.py` (sizing, constraints); **Correlation:** `correlation_guard.py`
- **Execution:** `executor.py` (bracket orders, slippage); **Logging:** `trade_tracker.py`
- **Validation:** `strategy_validator.py`; **Edge:** `edge_tracker.py`
- **Reconciliation:** `reconcile.py` (compare local vs broker before trading)
- **Regime:** `regime.py`

**State Files (JSON, source of truth):**
- `positions.json` — Current open positions (PortfolioState object, serialized)
- `order_log.json` — All order events (submissions, fills, errors, cancellations)
- `trade_log.json` — Closed trade records (ticker, action, shares, price, P&L, strategy)

**Learning Files (MD + JSON, appended by learning loop):**
- `trade_journal.md` — Chronological entry/exit log with notes
- `lessons.md` — Distilled insights from closed trades
- `patterns.json` — Pattern memory: {strategy: {regime: {outcome: count}}}

## Where to Add New Code

**New Scanner Strategy:**
1. Add method to `Scanner` class in `scanner.py` (e.g., `_scan_volatility_burst()`)
2. Add to `STRATEGY_RUNNERS` dict in `run_full_scan()` function
3. Register in `strategy_validator.py` — add new entry to `STRATEGY_CONFIGS` with backtest params
4. Update `config.py` if adding new parameters (e.g., lookback periods, indicator thresholds)

**New Standalone Strategy:**
- Create in `strategies/` (e.g., `strategies/my_strategy.py`)
- Implement entry/exit logic; optionally hook into orchestrator via `--strategy my_strategy` flag
- Document in `SETUP-GUIDE.md`

**New Risk/Filter Check:**
1. Add method to `PortfolioState` class in `risk_manager.py` (e.g., `check_vega_exposure()`)
2. Call from `step_filter()` in `orchestrator.py`
3. Update `config.py` if adding new parameters (e.g., max vega cap)

**New Analysis/Learning Feature:**
- Add to `analysis/` (e.g., `analysis/my_analyzer.py`)
- Hook into `learning_loop.py` in the SYNTHESIZE or ADAPT stage
- Document in `TRADING-PLAN.md`

**Tests:**
- Add test in `test_simulation.py` (comprehensive offline simulation)
- Or add integration test in `test_executor.py` (bracket order, slippage scenarios)
- Run: `python test_simulation.py` or `python test_executor.py`

## Configuration Pattern

All trading parameters live in `config.py` (AgentConfig dataclass):
- **Capital:** starting_capital, target_capital
- **Risk:** risk_per_trade_pct (1% per trade), max_total_risk_pct (6% portfolio heat), min_reward_risk (2.0:1)
- **Position:** max_position_pct (10%), max_open_positions (6), max_sector_exposure (2)
- **Strategy:** strategy-specific params (pullback_lookback=20, breakout_volume_mult=1.5, powerx_stop_pct=0.015, etc.)
- **Slippage:** SLIPPAGE_RR_THRESHOLD=1.5 (in executor.py, not config)
- **Paper Mode:** alpaca_paper=True, paper_exploration_mode=True (loosen filters for more trades)

Pass AgentConfig instance to every function that needs parameters; never read config directly.

## Special Directories

**`.data_cache/`:** Ticker→CSV cache directory. Used by `data_provider.py` for offline backtesting. Does not need to be tracked in git (recreated on demand).

**`logs/`:** Launchd scheduler logs (`launchd_at_open.log`, `launchd_monitor.log`, `launchd_eod.log`). Helps diagnose scheduled job failures.

**`reports/`:** Generated HTML/PDF reports from weekly_report.py. Gitignored; regenerated weekly.
