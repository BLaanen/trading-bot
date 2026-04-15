# Requirements

## Phase 1: Verification & Hardening ✅

REQ-01: Full pipeline runs without errors (scan → filter → execute → monitor → report)
REQ-02: Bracket orders submit correctly to Alpaca paper API
REQ-03: Reconciliation accurately detects local vs broker mismatches
REQ-04: Slippage rejection fires when fill degrades R:R below 1.5
REQ-05: Trailing stops configurable via use_trailing_stops flag (default: off)
REQ-06: Time stops apply after 15 days for stale positions
REQ-07: Edge tracker correctly tracks win/loss per strategy
REQ-08: Learning loop generates journal entries and pattern memory
REQ-09: All 3 launchd agents load and fire on schedule
REQ-10: test_simulation.py passes in sandbox without touching live state
REQ-11: test_executor.py passes with mocked Alpaca client
REQ-12: Slash commands (/status, /edge-check, etc.) work correctly

## Phase 2: Trailing Stop Broker Sync

REQ-25: When trailing stop moves up, call Alpaca replace_order to update the broker's stop-loss order
REQ-26: Verify replacement succeeded before updating positions.json
REQ-27: If replace_order fails, log warning and retry next monitor cycle (original stop remains)
REQ-28: Trail distance defaults to 5% below high water mark (configurable via config.py)
REQ-29: Trailing only activates when use_trailing_stops=True
REQ-30: Test trailing stop broker sync with mocked Alpaca client
REQ-31: No trailing logic runs when use_trailing_stops=False (current default)

## Phase 3: Robustness Improvements

REQ-13: Replace broad exception handling with specific exception types
REQ-14: Cache scanner data per-ticker to fix N+1 pattern
REQ-15: Add credential validation on startup (GET /account)
REQ-16: Add reconciliation recovery path (currently blocks ALL trading)
REQ-17: Set state file permissions to 600
REQ-18: Add mode flag (simulated vs live) to order_log.json entries
REQ-19: Pre-build universe.json to avoid blocking on Wikipedia scraping

## Phase 4: Test Coverage

REQ-20: Integration test for reconciliation failure scenarios
REQ-21: Test empty DataFrame handling in all calc_* functions
REQ-22: Test trailing stop broker sync updates both positions.json and Alpaca order
REQ-23: Test regime-flip mid-scan edge case
REQ-24: Stress test with 500+ ticker universe

## Phase 5: GitHub & Collaboration

REQ-32: GitHub repo created with clean commit history
REQ-33: README with setup instructions (Python, Alpaca keys, launchd)
REQ-34: .env.example documenting all required environment variables
REQ-35: config.py works with sensible defaults for new users
REQ-36: No hardcoded paths — all paths relative or configurable
REQ-37: Contributing guide documenting how to add a new strategy
REQ-38: PowerX Optimizer integration documented (adding external picks to universe)
