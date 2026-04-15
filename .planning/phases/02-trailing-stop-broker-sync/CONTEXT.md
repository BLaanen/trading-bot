# Context — Phase 2: Trailing Stop Broker Sync

## Locked Decisions

1. **Try-then-handle pattern:** Call replace_order first. If it fails, call get_order to check actual status. Don't pre-check — just handle whatever comes back.
2. **Local state updates only on broker confirmation:** Never update pos.stop_loss until the broker confirms the replacement succeeded. Prevents local/broker mismatch (the ALK bug).
3. **Existing exit flow handles filled orders:** If replace fails because the stop already filled, don't process the exit in trailing code. Let _check_bracket_children handle it on the next monitor cycle.
4. **Trail distance 5%:** Config default changes from 3% to 5% to reduce shake-outs on normal dips.
5. **Feature flag:** All trailing logic gated on use_trailing_stops (already implemented, default False).
6. **Simulated mode passthrough:** When no Alpaca client (simulated), update local state directly as before — no broker call needed.

## Key Insight

manage_positions already runs _check_bracket_children (Step 1) before trailing stops (Step 2). This catches most filled exits. But orders can fill between steps, so _replace_stop_order must handle stale order IDs gracefully.

## Review Decisions

1. [review] **Alpaca SDK signature:** `replace_order` takes flat kwargs (`stop_price=str(price)`), not nested dicts. Verified against alpaca_trade_api.REST source.
2. [review] **Guard empty/SIM order IDs:** `_replace_stop_order` must check for empty or simulated order IDs before calling Alpaca. Return early with `(False, "no_order_id")`.
3. [review] **Double-failure handling:** If `get_order` also fails after `replace_order` fails, return `(False, "status_unknown")` rather than letting the exception propagate.
4. [review] **Trailing activation is local-only:** Setting `pos.trailing=True` and updating `high_water_mark` don't need broker confirmation — they're decision state, not order state.
5. [review] **Crash-between-confirm-and-save accepted risk:** If the process crashes after broker confirms replacement but before `save_positions` writes, the local stop will be stale on restart. Accepted: reconcile.py catches position mismatches, and the old stop is still more protective (lower).

6. [review] **Incremental save after replace:** `save_positions` called immediately after each successful `_replace_stop_order`, not deferred to end of `manage_positions`. Prevents crash-between-replace-and-save from leaving local state inconsistent with broker.
7. [review] **RiskDecision.ticker field required:** Must add `ticker: str = ""` to the dataclass. Without it, Task 3 cannot match decisions to positions — ticker was only in the reason string.
8. [review] **Explicit line 318 removal:** Task 1 must delete the direct `pos.stop_loss` mutation. This is the core behavioral change — if it's missed, broker confirmation is bypassed.
9. [review] **Log format specified:** Success prints `[TRAIL] TICKER: broker stop updated $X → $Y`. Failure prints `[WARN] TICKER: broker stop replace failed (reason) — original stop remains`. Double-failure logs raw exception at WARNING.
10. [review] **Integration test added:** Test 9 verifies that a position exiting in Step 1 (_check_bracket_children) is NOT passed to trailing in Step 2.

## Deferred Ideas

- Atomic save for positions.json (write-temp-then-rename) — deferred, low risk given crash window is milliseconds
- Return `(Position, RiskDecision)` pairs from update_trailing_stops instead of matching by ticker — deferred, cleaner but not needed for 6-position max

## Files Modified

- `executor.py` — new _replace_stop_order function, wire trailing decisions into broker calls
- `risk_manager.py` — refactor update_trailing_stops to calculate new stops without modifying pos.stop_loss (return proposed changes)
- `config.py` — update trail_distance_pct default to 0.05
- `test_executor.py` — tests for replace flow (success, filled, failed)
