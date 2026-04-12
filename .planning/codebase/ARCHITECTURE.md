# Architecture

**Analysis Date:** 2026-04-12

## Pattern Overview

**Overall:** Layered agent-based trading pipeline with broker-native position management
**Key Characteristics:**
- Sequential decision pipeline: reconcile → regime → validate → scan → filter → execute → monitor
- Each agent handles one responsibility; orchestrator coordinates
- Bracket orders at broker handle position exits; Python is backup and metadata keeper
- 1R (fixed risk per trade) enforced at every layer
- Post-trade learning loop (analysis/) captures patterns and edge decay

## Layers

**Data Layer:**
- Purpose: Unified market data abstraction
- Contains: Multi-backend data provider (Yahoo, Alpaca, CSV cache)
- Location: `data_provider.py`
- Depends on: External APIs (yahoo-fin, Alpaca REST)

**Market Intelligence Layer:**
- Purpose: Generate actionable signals and detect trading regimes
- Contains: Technical scanners (5 core + 3 standalone), regime detector, universe builder
- Location: `scanner.py`, `regime.py`, `universe.py`
- Depends on: Data Layer

**Validation Layer:**
- Purpose: Backtest strategy signals before trading live; track edge decay
- Contains: Backtesting engine, edge tracking, performance metrics
- Location: `strategy_validator.py`, `edge_tracker.py`, `analysis/`
- Depends on: Market Intelligence, Data Layer

**Risk Management Layer:**
- Purpose: Position sizing (1R rule), portfolio constraints, correlation analysis
- Contains: Risk calculator, trailing stop logic, portfolio state, sector guard
- Location: `risk_manager.py`, `correlation_guard.py`
- Depends on: Market Intelligence Layer

**Execution Layer:**
- Purpose: Bracket order lifecycle; reconciliation with broker; trade logging
- Contains: Bracket order submission, fill polling, slippage rejection, exit monitoring
- Location: `executor.py`, `trade_tracker.py`, `reconcile.py`
- Depends on: Risk Management Layer

**Orchestration Layer:**
- Purpose: Coordinate full pipeline; handle user commands; delegate to steps
- Contains: Step execution, error handling, multi-mode dispatch
- Location: `orchestrator.py`
- Depends on: All layers

**Learning/Analysis Layer:**
- Purpose: Post-trade autopsy and pattern recognition; adaptive config
- Contains: Trade journal, lessons, hypotheses, pattern memory, experiment tracking
- Location: `analysis/learning_loop.py`, `analysis/weekly_report.py`, `analysis/hypothesis_generator.py`
- Depends on: Trade history (trades.csv, trade_log.json)

## Data Flow

**Full Pipeline (`orchestrator.py` main):**
1. **Reconcile** (`reconcile.py`) — Compare local state vs. Alpaca; refuse trading if mismatch
2. **Regime Detection** (`regime.py`) — Analyze SPY, breadth, volatility → TRENDING_UP / SIDEWAYS / TRENDING_DOWN
3. **Validation** (`strategy_validator.py`) — Backtest all 6 core strategies on current config
4. **Scan** (`scanner.py`) — Find entry signals in approved tickers using technical patterns
5. **Filter** (`risk_manager.py`, `correlation_guard.py`) — Check portfolio health, risk limits, correlation, sector
6. **Execute** (`executor.py`) — Size position (1R rule), submit bracket order, log entry
7. **Monitor** (`executor.py`) — Poll Alpaca for bracket exit fills; update trailing stops; log exits
8. **Optimize** (`analysis/portfolio_optimizer.py`) — Rebalance core ETFs
9. **Report** (`trade_tracker.py`) — Print portfolio status, performance, edge report
10. **Learn** (`analysis/learning_loop.py`) — (End-of-day) Autopsy closed trades; update patterns

**Bracket Order Lifecycle:**
- Entry: `process_signal()` → `_submit_bracket_order()` → buy + stop-loss + take-profit children
- Monitor: `manage_positions()` → query broker for child fills → update local state
- Exit: Broker executes stop or target; Python logs the exit via trade_tracker
- Slippage Check: Post-fill R:R re-validation; immediate market sell if degraded below 1.5

## Key Abstractions

**Signal (scanner.py):**
- Encodes one entry opportunity (ticker, entry, stop, target, reason)
- Properties: risk, reward, reward_risk ratio, risk_pct
- Example: `PULLBACK: SPY at $425, stop at $410, target at $445 (R:R 2.0)`

**Position (risk_manager.py):**
- Represents an open trade (entry → current → exit)
- Properties: shares, entry_price, stop_loss, target, high_water_mark, bracket_order_id, stop_order_id, target_order_id
- Stores regime_at_entry for post-trade learning

**PortfolioState (risk_manager.py):**
- Holds all open positions + cash + portfolio-level metrics
- Properties: total risk %, sector exposure, cash reserve, pause state
- Source of truth: persisted to `positions.json`

**Regime State (regime.py):**
- Market condition snapshot (bullish/sideways/bearish + confidence)
- Properties: regime type, breadth percentile, volatility percentile, momentum, golden cross

**OrderResult (executor.py):**
- Encodes one order submission outcome
- Properties: success, order_id, ticker, shares, price, bracket children IDs (stop_order_id, target_order_id)

## Entry Points

**Full Pipeline:**
- Command: `python orchestrator.py` (no args)
- Flow: reconcile → regime → validate → scan → filter → execute → monitor → optimize → report

**Scan Only:** `python orchestrator.py --scan` — signal testing without execution

**Monitor Only:** `python orchestrator.py --monitor` — update prices, check stop/target hits, trailing stops

**Other Modes:** --validate, --report, --regime, --rebalance, --edge

## Error Handling

**Strategy:** Graceful degradation per agent
- Data unavailable → warn, skip ticker, continue
- Reconciliation fails → refuse all trades until fixed
- Order fails → log, flag position failed, skip exit
- Slippage detected → immediate market sell, log SLIPPAGE_REJECT
- Bracket fill times out → cancel children, log timeout
- Regime uncertain → use conservative position size (50% multiplier)

**Logging:**
- `order_log.json` — order submissions, fills, cancellations, errors
- `trade_log.json` — entry/exit records with outcome labels (normal, slippage_reject, timeout, etc.)
- `positions.json` — current open positions (source of truth)
- `trades.csv` — historical closed trades with P&L and win rate

## Cross-Cutting Concerns

**State Persistence:**
- `positions.json` — current open positions (PortfolioState); loaded at start, saved after every trade
- `order_log.json` — chronological order events
- `last_run.json` — pipeline run timestamp and state flags

**Validation Rules** (enforced before entry):
- Portfolio risk cap: 6% max total heat (all open positions combined)
- Position size cap: 10% of portfolio per position
- Sector exposure: max 2 positions per sector (customizable in paper exploration mode)
- Reward-to-risk minimum: 2.0:1 (slippage rejection at 1.5:1 after fill)
- Liquidity check: min 500k daily volume for scan tickers

**Regime Awareness:**
- Position size multiplier applies based on regime (50% in uncertain regimes)
- Strategy approval based on recent backtest results
- Risk multiplier adjusts capital deployment based on market conditions
