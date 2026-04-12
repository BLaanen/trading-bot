# Weekend Executor Rewrite Plan

Written: 2026-04-12 (Saturday)
Status: TASKS 1-10 COMPLETE. Task 11 (live dry-run) pending Monday.
Context: Long session on 2026-04-10/11 did reorg, found bugs, froze state.

## Current State (read this first)

### Alpaca Broker
- **6 positions still open**, no pending orders, scheduler fully unloaded
- CTRA 29 @ $33.34, DVN 20 @ $47.97, HAL 26 @ $37.94
- XLB 10 @ $52.15, XLK 7 @ $142.54, XLRE 23 @ $42.88
- Verify with: `python3.11 -c "import os; [exec(l.replace('export ','')) for l in open(os.path.expanduser('~/.zshrc')) if l.startswith('export ALPACA_')]; import alpaca_trade_api as t; api=t.REST(os.environ['ALPACA_API_KEY'],os.environ['ALPACA_API_SECRET'],'https://paper-api.alpaca.markets',api_version='v2'); [print(f'{p.symbol}: {p.qty} @ {p.avg_entry_price}') for p in api.list_positions()]"`

### Scheduler
- All 3 launchd agents UNLOADED. Nothing fires automatically.
- `launchctl list | grep trading` should return 0 results.
- Plists at `~/Library/LaunchAgents/com.bopeterlaanen.trading.{at_open,monitor,eod}.plist`
- DO NOT reload until all fixes are verified.

### Local State Files (CORRUPTED — do not trust)
- `positions.json` — contains a reconstruction from 2026-04-10 that is WRONG (XLB stop was set to breakeven incorrectly, triggering a phantom exit)
- `trades.csv` — has 8 real rows + 1 phantom XLB sell at line 9 that never actually executed at Alpaca
- `portfolio_value.csv` — wiped to header only by test_simulation.py
- `order_log.json` — INTACT, has the 7 real Alpaca orders from 2026-04-10
- These files will be rebuilt from Alpaca ground truth after the executor rewrite

### Git
- 3 commits on main:
  - `b042ac0` Initial commit: isolate trading system from home repo
  - `70c6aee` Add session guide, concepts cheat sheet, and slash commands
  - `e391185` Organize files into docs/, analysis/, strategies/, legacy/
- Repo is at `/Users/bopeterlaanen/trading` with its own `.git` (NOT the home-dir Sanity repo)

### Cron
- Crontab is EMPTY (removed duplicate schedule on 2026-04-10, launchd is authoritative)
- DO NOT reinstall cron

---

## Architectural Decisions (already confirmed with user)

1. **Bracket orders at the broker.** When executor opens a position, also place a stop-loss order and a take-profit order via Alpaca's `order_class='bracket'`. The broker handles exits. Python monitor is backup, not primary.

2. **No partial exits.** Classic PowerX: one target, one stop, sell ALL shares at whichever fires first. Remove the partial-exit logic (sell-half-at-target, move-stop-to-breakeven, trail-the-rest). Simpler, fewer bugs.

3. **Actual fill prices everywhere.** After a buy fills, query Alpaca for `filled_avg_price` and use THAT for all downstream: positions.json entry_price, trades.csv price, P&L calculations. Never log the signal's planned price as the actual price.

4. **Post-fill R:R re-validation.** If slippage moved the fill price so much that R:R drops below 1.7, immediately close the position (market sell) and log it as a slippage rejection. This prevents the XLB-style doomed trades.

5. **Reconciliation on startup.** Before any trade logic, compare positions.json against Alpaca's actual positions via API. If they disagree, refuse to trade and alert.

6. **30-minute monitor cadence.** Since broker handles exits, monitor only needs to handle time stops, regime adjustments, edge tracking, and reconciliation. Change StartInterval from 300 to 1800 in the launchd plist.

7. **Sandboxed test_simulation.py.** Tests write to a temp directory, never to real state files.

8. **Close existing positions with simple market sells Monday morning before the new executor runs.** Start fresh with zero positions.

---

## Task List (11 tasks, in dependency order)

### Task 1: Sandbox test_simulation.py
**Files:** `test_simulation.py`, `risk_manager.py`, `trade_tracker.py`
**What:** Add `TRADING_STATE_DIR` environment variable support to risk_manager.py (for `POSITIONS_FILE`) and trade_tracker.py (for `TRADES_FILE`, `PORTFOLIO_FILE`). Default to `Path(__file__).parent` (current behavior). Rewrite test_simulation.py to create a tempdir, set `TRADING_STATE_DIR` before importing, and clean up after.
**Verify:** Run `test_simulation.py` twice. Real `positions.json`/`trades.csv`/`portfolio_value.csv` must be unchanged.
**Risk:** Low. Only changes path resolution, not logic.

### Task 2: Audit all state file references
**Files:** All `.py` files in trading/
**What:** Grep for positions.json, trades.csv, portfolio_value.csv, order_log.json, learning_state.json, edge_tracker.json, signals.csv. Catalog which files read/write each. Ensure ALL writers use the `TRADING_STATE_DIR` mechanism (or at minimum, the same Path base).
**Verify:** List of all readers/writers exists. No hardcoded paths remain outside the env-var-resolved base.
**Risk:** None — audit only.

### Task 3: Rewrite executor.py for bracket orders
**Files:** `executor.py`, possibly `orchestrator.py`
**What:** Replace current flow:
  - OLD: `api.submit_order(buy)` → local tracking → monitor polls until exit
  - NEW: `api.submit_order(buy, order_class='bracket', stop_loss={stop_price: X}, take_profit={limit_price: Y})`
  Alpaca creates the buy with two child orders. When buy fills, children activate.
  
  Key implementation details:
  - Use `alpaca-trade-api`'s bracket support: `api.submit_order(symbol, qty, 'buy', 'market', 'gtc', order_class='bracket', stop_loss={'stop_price': stop}, take_profit={'limit_price': target})`
  - After submission, poll for fill status (up to 30s) to get actual fill price
  - Store the child order IDs in positions.json so we can track/cancel them later
  - The monitor's role changes: instead of placing exits, it checks whether child orders have filled and updates local state accordingly

**Verify:** Place a test bracket order on Alpaca paper for a cheap ticker. Confirm 3 orders appear (parent buy + 2 children). Cancel all.
**Risk:** HIGH — this is the core change. Test thoroughly.

### Task 4: Remove partial exit logic
**Files:** `executor.py`, `risk_manager.py`, `orchestrator.py` (monitor section)
**What:** Delete:
  - `partial_exit_done` field from Position dataclass
  - `original_shares` field from Position dataclass
  - Any code that checks "should we sell half?"
  - The trailing-stop-after-partial logic (trailing stops for full position can stay IF relevant)
  - The "move stop to breakeven after partial" logic
  
  Keep:
  - Position sizing logic (1% risk per trade)
  - Circuit breaker logic
  - Regime-based size adjustments
  
**Verify:** Grep for "partial", "original_shares", "sell half". Should return 0 hits in active code.
**Risk:** Medium — need to find all references.

### Task 5: Fix P&L to use actual fills
**Files:** `executor.py`, `trade_tracker.py`
**What:** In executor.py's buy flow:
  1. Submit bracket order
  2. Wait for fill (poll `api.get_order(order_id)` until status='filled')
  3. Read `filled_avg_price` from the Alpaca order object
  4. Log to trades.csv with the ACTUAL fill price, not the signal's planned price
  5. Log to order_log.json with the ACTUAL fill price
  6. Save to positions.json with actual entry_price
  
  In executor.py's sell flow (when monitor detects a filled child order):
  1. Read `filled_avg_price` from the child order
  2. Compute P&L = (sell_fill - buy_fill) * shares
  3. Log actual P&L to trades.csv
  
**Verify:** Simulate a buy where signal says $50 but fill is $50.30. trades.csv must show $50.30, not $50.
**Risk:** Medium — requires understanding Alpaca order lifecycle.

### Task 6: Add post-fill R:R re-validation
**Files:** `executor.py`
**What:** After a buy fills (task 5 gets the actual fill price):
  1. Recalculate: `new_risk = actual_fill - original_stop`, `new_reward = original_target - actual_fill`
  2. `new_rr = new_reward / new_risk`
  3. If `new_rr < 1.5` (slightly below normal 1.7 threshold to allow minor slippage): 
     - Cancel the bracket's child orders
     - Place immediate market sell
     - Log as "SLIPPAGE_REJECT" in trades.csv
     - Alert
  4. If `new_rr >= 1.5`: proceed normally, position is valid
  
**Verify:** Test with a signal where entry=$50, stop=$48, target=$54 (R:R=2.0). Simulate fill at $53.50 → new R:R = (54-53.50)/(53.50-48) = 0.09. Must trigger reject.
**Risk:** Medium — must correctly cancel bracket children before selling.

### Task 7: Add Alpaca reconciliation
**Files:** New file `reconcile.py` or add to `orchestrator.py`
**What:** Function `reconcile_with_broker()`:
  1. Load positions.json
  2. Query `api.list_positions()`
  3. Compare: same tickers? Same quantities? Cost basis within $0.50?
  4. If mismatch: print detailed diff, write to logs, return False
  5. If match: return True
  6. Call this at the TOP of orchestrator.py before any trading logic
  7. If reconcile returns False: skip all trading, only run the report
  
**Verify:** Manually corrupt positions.json (add a fake ticker). Run orchestrator.py --scan. Must refuse to scan and print the mismatch.
**Risk:** Low — additive, doesn't change existing logic.

### Task 8: Reduce monitor cadence
**Files:** `~/Library/LaunchAgents/com.bopeterlaanen.trading.monitor.plist`
**What:** Change `<integer>300</integer>` to `<integer>1800</integer>` (30 min).
**Verify:** `launchctl load` the plist, wait >5 min, confirm monitor only fires at 30-min intervals.
**Risk:** Low — single config change. But must NOT apply until bracket orders are working (task 3 done).
**Depends on:** Task 3.

### Task 9: Write tests
**Files:** `test_simulation.py` (extended), possibly `test_executor.py` (new)
**What:**
  - Test bracket order submission against mocked Alpaca (or a test-mode flag)
  - Test slippage rejection (R:R < 1.5 after fill → immediate sell)
  - Test P&L calculation with actual fill prices
  - Test reconciliation catches a mismatch
  - Backtest: run `analysis/backtest_momentum.py` against 3 months of data to verify the slippage rejection threshold (1.5 R:R) doesn't filter out too many valid signals
**Verify:** All tests pass. Backtest shows rejection rate < 10% (most signals should still pass).
**Depends on:** Tasks 1, 3, 4, 5, 6, 7.

### Task 10: Update CLAUDE.md and CONCEPTS.md
**Files:** `CLAUDE.md`, `CONCEPTS.md`, slash commands in `.claude/commands/`
**What:**
  - Remove references to partial exits and 5-min monitoring
  - Add: bracket orders, reconciliation, slippage rejection
  - Update the pipeline description to reflect new flow
  - Update the slash commands if any reference partial exits or monitor cadence
**Depends on:** Tasks 3, 4, 8.

### Task 11: Final end-to-end dry-run
**What:**
  1. Close the existing 6 positions at Alpaca with market sells (Monday morning)
  2. Reset positions.json and trades.csv to clean state
  3. Run `orchestrator.py --regime` to verify regime detection works
  4. Run `orchestrator.py --scan` to find signals
  5. Place ONE real test bracket order via the new executor on a cheap ticker (~$50 position)
  6. Verify at Alpaca dashboard: 1 buy filled + 2 child orders (stop + target) visible
  7. Wait 5-10 minutes to confirm nothing fires unexpectedly
  8. Cancel all orders / close test position
  9. Run full backtest against 3 months data to validate signal quality
  10. If all pass: reload launchd agents, let Monday's at_open.sh run the full pipeline
**Depends on:** All other tasks.

---

## Files Changed by This Plan

### Modified
- `executor.py` — bracket orders, actual fills, R:R re-validation (tasks 3, 5, 6)
- `risk_manager.py` — remove partial exit fields, add TRADING_STATE_DIR (tasks 1, 4)
- `trade_tracker.py` — actual fill P&L, add TRADING_STATE_DIR (tasks 1, 5)
- `orchestrator.py` — reconciliation call, remove partial exit monitor logic (tasks 4, 7)
- `test_simulation.py` — sandbox to tempdir (task 1)
- `eod.sh` — no changes needed (paths already updated in reorg)
- `CLAUDE.md` — architecture updates (task 10)
- `CONCEPTS.md` — remove partial exit section, add bracket orders (task 10)
- `~/Library/LaunchAgents/com.bopeterlaanen.trading.monitor.plist` — cadence change (task 8)

### Possibly New
- `reconcile.py` — Alpaca reconciliation module (task 7) OR added to orchestrator.py
- `test_executor.py` — bracket order tests (task 9)

### State Files (rebuilt, not versioned)
- `positions.json` — rebuilt from Alpaca after closing positions
- `trades.csv` — reset to header only after closing positions
- `portfolio_value.csv` — reset to header only
- `order_log.json` — keep intact (historical audit trail)

---

## How to Start a New Session

When you `/clear` and start fresh, the new session should:

1. Read `CLAUDE.md` (auto-loaded)
2. Read THIS file (`WEEKEND-PLAN.md`) for context
3. Check `TaskList` for current progress
4. Read `positions.json` to see what state files look like
5. Verify scheduler is still unloaded: `launchctl list | grep trading`
6. Pick up the next uncompleted task

The CLAUDE.md file tells the session to read live state files first. This plan tells it what to build. The task list tells it where we left off.

---

## Key Alpaca API Reference for Bracket Orders

```python
# Bracket order: buy + stop-loss + take-profit in one call
order = api.submit_order(
    symbol='AAPL',
    qty=10,
    side='buy',
    type='market',
    time_in_force='gtc',
    order_class='bracket',
    stop_loss={'stop_price': 190.00},
    take_profit={'limit_price': 210.00},
)
# order.legs contains the child orders
# order.legs[0] = stop-loss child
# order.legs[1] = take-profit child

# Check fill:
filled_order = api.get_order(order.id)
filled_order.filled_avg_price  # actual fill price
filled_order.status  # 'filled', 'partially_filled', etc.

# Cancel children (if rejecting due to slippage):
for leg in order.legs:
    api.cancel_order(leg.id)
# Then market sell to close:
api.submit_order(symbol='AAPL', qty=10, side='sell', type='market', time_in_force='day')
```

---

## Acceptance Criteria (Level 3 — user requested)

The weekend work is NOT done until ALL of these pass:

1. `test_simulation.py` runs without touching real state files
2. A real bracket order is placed on Alpaca paper and verified (buy + 2 children visible)
3. A simulated slippage scenario correctly triggers rejection and immediate close
4. P&L in trades.csv uses actual Alpaca fill prices, not signal prices
5. Reconciliation catches a deliberately corrupted positions.json
6. Monitor cadence is 30 min, not 5 min
7. Full backtest against 3 months of data runs and shows:
   - Slippage rejection rate < 10%
   - Strategy R:R and win rate are comparable to pre-rewrite baseline
   - No regressions in signal quality
8. `orchestrator.py --scan` and `orchestrator.py --regime` run without errors
9. All docs (CLAUDE.md, CONCEPTS.md) reflect the new architecture
10. All tasks in the task list are marked completed
