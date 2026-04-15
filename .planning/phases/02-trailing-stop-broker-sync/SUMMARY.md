# Summary — Phase 2: Trailing Stop Broker Sync

## Status: Complete

## What was built

When trailing stops are enabled (`use_trailing_stops=True`), the system now replaces the broker's stop-loss order at Alpaca when the trailing stop moves up. Local state only updates after broker confirmation, preventing local/broker mismatch.

### Changes by file

- **`risk_manager.py`** — `update_trailing_stops` proposes stop changes via `RiskDecision.new_stop` without modifying `pos.stop_loss`. Local-only state (`high_water_mark`, `trailing`) is updated directly. The `ticker` field on `RiskDecision` maps decisions back to positions.

- **`executor.py`** — New `_replace_stop_order(client, stop_order_id, new_stop_price)` function handles all failure paths: success, already-filled, canceled/expired, double-failure (replace + get_order both fail). Guards against empty/SIM order IDs. `manage_positions` Step 2 wires trailing decisions to broker calls — updates `pos.stop_loss` only on broker confirmation. Simulated mode updates directly.

- **`config.py`** — `trail_distance_pct` default is 0.05 (5% below high water mark).

- **`test_executor.py`** — 9 new tests (Tests 10-18) covering: replace success, already-filled, other error, double failure, no order ID, trailing disabled, simulated mode, two positions trailing independently, exited position skipped.

### Requirements covered

| Requirement | Status |
|-------------|--------|
| REQ-25: Call replace_order when trailing stop moves | Done |
| REQ-26: Verify replacement before updating positions.json | Done |
| REQ-27: Log warning and retry next cycle on failure | Done |
| REQ-28: Trail distance 5% default, configurable | Done |
| REQ-29: Only active when use_trailing_stops=True | Done |
| REQ-30: Test with mocked Alpaca client | Done (9 tests) |
| REQ-31: No trailing logic when disabled | Done |

### Test results

- 51 tests total, all passing
- 9 new trailing stop broker sync tests
- All tests run in sandboxed temp directory, no live state touched

### Decisions

1. Try-then-handle pattern for replace_order (no pre-check)
2. Local state updates only on broker confirmation
3. Existing exit flow handles filled orders (no duplicate exit logic)
4. Trail distance 5% to reduce shake-outs
5. Feature flag gates all trailing logic
6. Crash-between-confirm-and-save accepted as low risk (reconcile.py catches drift)
