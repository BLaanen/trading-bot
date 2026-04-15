# Roadmap

## Phase 1: Verification & Monday Readiness ✅
**Goal:** Confirm the system works correctly when markets open. Run all tests, verify launchd schedule, validate commands, fix blockers.

**Status:** Complete — system ran first live pipeline Apr 14. 6 bracket order positions open. Reconciliation, scanning, filtering all working. Sector classification fixed for PowerX Optimizer picks.

## Phase 2: Trailing Stop Broker Sync ✅
**Goal:** Make trailing stops actually update the stop-loss order at Alpaca, so the broker's stop moves up with the price. Currently trailing logic only updates local state — the broker order stays at the original stop.

**Status:** Complete — `_replace_stop_order` wired into `manage_positions`, local state updates only on broker confirmation, 9 tests passing.

### Milestones
1. Add `replace_order` call to Alpaca when trailing stop moves up
2. Confirm replacement went through before updating local state
3. Handle failure gracefully (log, retry next cycle, original stop still in place)
4. Trail distance: 5% below high water mark (configurable)
5. Only active when `use_trailing_stops=True` in config
6. Test with mocked Alpaca client
7. Test with live paper position

### Success Criteria
- When trailing activates, Alpaca's stop order price matches positions.json
- Failed replacements don't corrupt local state
- Monitor log shows stop updates with old → new prices
- Existing bracket-only mode (default) unaffected

## Phase 3: Robustness Improvements ✅
**Goal:** Address known concerns — exception handling, N+1 scanner, credential validation, reconciliation recovery.

**Status:** Complete — scanner provider passthrough, universe prebuild with 30s timeout, file permissions 0o600, 18 new tests.

### Milestones
1. Replace broad exception handling with specific exception types
2. Cache scanner data per-ticker to fix N+1 pattern
3. Add credential validation on startup (GET /account)
4. Add reconciliation recovery path (currently blocks ALL trading)
5. Set state file permissions to 600
6. Pre-build universe.json to avoid blocking on Wikipedia scraping

## Phase 4: Test Coverage Expansion ✅
**Goal:** Fill test coverage gaps — reconciliation failures, empty DataFrames, trailing stop broker sync, regime flips.

**Status:** Complete — regime detection tests, step_filter tests, max trades capping, 10 new tests in test_executor.py.

## Phase 5: GitHub & Collaboration Readiness ✅
**Goal:** Prepare the repo for public/shared use. Clean up for others to clone, configure, and run.

**Status:** Complete — README.md, CONTRIBUTING.md, SETUP-GUIDE.md updated. GitHub repo creation deferred (manual step).

### Milestones
1. Create GitHub repo, push codebase
2. Write proper README with setup instructions
3. Add .env.example with required variables documented
4. Ensure config.py has sensible defaults for new users
5. Document PowerX Optimizer integration (external tool, how to add picks)
6. Add contributing guide (how to add a new strategy)
7. Review all hardcoded paths for portability
