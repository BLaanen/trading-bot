# Architecture

**Analysis Date:** 2026-04-09

## Pattern Overview
**Overall:** Layered agent-based trading pipeline
**Key Characteristics:**
- Sequential decision pipeline: regime detection → validation → scan → filter → execution → monitoring
- Each agent handles one responsibility; orchestrator coordinates
- Position-centric state machine (entry → monitoring → exit)
- 1R (fixed risk per trade) enforced at every layer

## Layers

**Data Layer:**
- Purpose: Unified market data abstraction
- Contains: Multi-backend data provider (Yahoo, Alpaca, CSV cache)
- Location: `data_provider.py`
- Depends on: External APIs (yahoo-fin, Alpaca REST)

**Market Intelligence Layer:**
- Purpose: Generate actionable signals and detect trading regimes
- Contains: Technical scanners, regime detector, universe builder
- Location: `scanner.py`, `regime.py`, `universe.py`
- Depends on: Data Layer

**Validation Layer:**
- Purpose: Backtest strategy signals before trading live
- Contains: Backtesting engine, edge tracking, performance metrics
- Location: `strategy_validator.py`, `edge_tracker.py`
- Depends on: Market Intelligence, Data Layer

**Risk Management Layer:**
- Purpose: Position sizing (1R rule), portfolio constraints, stop management
- Contains: Risk calculator, trailing stop logic, portfolio state
- Location: `risk_manager.py`, `correlation_guard.py`
- Depends on: Market Intelligence Layer

**Execution Layer:**
- Purpose: Place/modify/close orders; reconcile with broker
- Contains: Order submission, position tracking, paper vs live logic
- Location: `executor.py`, `trade_tracker.py`
- Depends on: Risk Management Layer

**Orchestration Layer:**
- Purpose: Coordinate the full pipeline; handle user commands
- Contains: Step execution, logging, reporting
- Location: `orchestrator.py`
- Depends on: All layers

## Data Flow

**Full Pipeline (orchestrator.py → orchestrator.py):**
1. **Regime Detection** (`regime.py`) — Analyze SPY, breadth, volatility to determine TRENDING_UP / SIDEWAYS / TRENDING_DOWN
2. **Validation** (`strategy_validator.py`) — Backtest all 6 strategies on current config; only approved strategies→tickers advance
3. **Scan** (`scanner.py`) — Find entry signals in approved tickers using technical patterns (pullback, breakout, momentum)
4. **Filter** (`risk_manager.py`, `correlation_guard.py`) — Check portfolio health, risk limits, correlation, sector exposure
5. **Execute** (`executor.py`) — Size position (1R rule), submit order, log entry
6. **Monitor** (`executor.py`) — Update trailing stops, detect target/stop hits, log exits
7. **Optimize** (`portfolio_optimizer.py`) — Rebalance core ETFs; analyze edge decay
8. **Report** (`trade_tracker.py`) — Print portfolio status, performance, win rate

## Key Abstractions

**Signal:**
- Purpose: Encodes one entry opportunity (ticker, entry, stop, target, reason)
- Properties: risk (absolute), reward, reward_risk ratio, risk_pct
- Examples: `scanner.py` lines 23-51

**Position:**
- Purpose: Represents an open or closed trade (entry → current price → exit)
- Properties: shares, entry_price, stop_loss, target, r_multiple, market_value, pnl
- Examples: `risk_manager.py` lines 32-80

**Portfolio State:**
- Purpose: Holds all open positions + cash; tracks portfolio-level metrics
- Properties: total positions, total risk %, sector exposure, cash reserve
- Examples: `risk_manager.py` (PortfolioState class)

**Regime State:**
- Purpose: Market condition snapshot (bullish/sideways/bearish + confidence metrics)
- Properties: regime type, breadth, volatility percentile, golden cross, momentum
- Examples: `regime.py` lines 42-51

## Entry Points

**Full Pipeline:**
- Location: `orchestrator.py` main()
- Triggers: `python orchestrator.py` (no args)
- Flow: regime → validate → scan → filter → execute → monitor → optimize → report

**Scan Only:**
- Location: `orchestrator.py` step_scan()
- Triggers: `python orchestrator.py --scan`
- Skips validation, execution; useful for signal testing

**Monitor Only:**
- Location: `orchestrator.py` step_monitor()
- Triggers: `python orchestrator.py --monitor`
- Updates prices; checks stop hits / trailing stops / exits

## Error Handling

**Strategy:** Graceful degradation per agent
- Data unavailable → warn, skip ticker, continue
- Order fails → log, flag position as failed, skip exit
- Correlation check fails → reject new trade, continue scanning
- Regime uncertain → use conservative multiplier (position size down 50%)

**Logging:** All decisions logged to `order_log.json`, `trade_log.json`, `positions.json`

## Cross-Cutting Concerns

**Logging:** JSON files in project root (`order_log.json`, `positions.json`, `trade_log.json`)

**Validation:** Every trade validated against config constraints:
- Portfolio risk cap (6% max total heat)
- Position size cap (10% per position)
- Sector exposure (max 2 per sector)
- Reward-to-risk minimum (2.0:1)
- Liquidity check (min daily volume)

**State Persistence:** `positions.json` is the source of truth for portfolio state; always load before execution
