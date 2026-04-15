# Decisions

## DEC-001: GSD Phase 1 focuses on verification, not new features
**Date:** 2026-04-12
**Context:** System was rewritten on 2026-04-12 (bracket orders, no partial exits, reconciliation). Monday is the first live test.
**Decision:** Phase 1 is purely about verifying existing code works. No new features, no refactors.
**Rationale:** The user's priority is confidence that the system won't fail on Monday market open.

## DEC-002: Incremental save after broker stop replacement
**Date:** 2026-04-14
**Step:** plan-review Step B
**Context:** Phase 2-01 trailing stop broker sync. If process crashes after Alpaca confirms stop replacement but before save_positions, local state is stale.
**Decision:** Call save_positions immediately after each successful _replace_stop_order, not batched at end of manage_positions.
**Rationale:** The crash window between replace confirmation and save is small but the consequence (stale stop in positions.json) creates confusing behavior on restart. Incremental saves eliminate this.
**Confidence:** HIGH

## DEC-003: RiskDecision requires ticker field for trailing stop matching
**Date:** 2026-04-14
**Step:** plan-review Step B
**Context:** Task 3 needs to match RiskDecision back to Position by ticker. RiskDecision had no ticker field — only embedded in reason string.
**Decision:** Add `ticker: str = ""` to RiskDecision dataclass. Populate in update_trailing_stops for every decision.
**Rationale:** Parsing ticker from a human-readable reason string is brittle. A dedicated field is the minimal reliable solution.
**Confidence:** HIGH

### D-001: Speculative plan validated: phase 2
- **Category:** implementation
- **Status:** ACTIVE
- **Confidence:** HIGH
- **Context:** No file overlap with predecessor phases (none)
- **Decision:** Plan proceeds as-is (VALID)
- **Affects:** Phase 2

# Phase 3: Autonomous Decisions

Decisions made autonomously during planning. Review if any seem wrong.

## Plan split: 2 plans, not 1

Phase 3 has 6 ROADMAP milestones across two distinct concerns: error handling/startup (Plan 1, 4 tasks) and data access/file security (Plan 2, 4 tasks). Split to keep each plan under 2500 words and allow independent execution.

## Exception handling scope: core pipeline only

Skipped `legacy/` (run_all.py, scheduler.py, notifier.py) and `analysis/` (learning_loop.py, hypothesis_generator.py, backtest_slippage.py). These are not on the hot trading path. The 10 active files cover all code that runs during market hours via launchd.

## Exception type mapping

| Pattern | Exception types | Rationale |
|---------|----------------|-----------|
| Alpaca API calls | `tradeapi.rest.APIError`, `ConnectionError` | SDK raises APIError for 4xx/5xx; ConnectionError for network |
| Data provider calls | `ConnectionError`, `ValueError` | Network failures + malformed data |
| JSON file I/O | `OSError`, `json.JSONDecodeError` | File system errors + corrupt JSON |
| Config/key lookups | `KeyError`, `ValueError` | Missing keys + bad values |
| Wikipedia scraping | `ConnectionError`, `ValueError`, `OSError` | Network + parse + file |

## Reconciliation recovery: monitor-only mode, not full continue

When reconciliation fails 3 times, the pipeline enters monitor-only mode (trailing stops + exits work, new entries blocked). Alternative was to continue with stale local state — rejected because trading on unreconciled state risks buying into positions we already have or missing exits.

## Credential check: fail fast for trading, skip for read-only

`--scan`, `--report`, `--regime`, `--edge` do not need valid credentials (they use public data or local files). Only `run_full_pipeline`, `--monitor`, and `--execute` validate credentials.

## Universe cache TTL: 24 hours, not 7 days

Current universe.py uses 7-day TTL. Reducing to 24h for the pre-check ensures daily freshness without blocking. The full 7-day rebuild cycle in `build_universe()` remains for the heavy Wikipedia scrape — `ensure_cache` just makes sure *some* cache exists before the scan runs.

## File permissions: chmod after every write, not just creation

Using `os.chmod` after every write (not just `open("w")`) because umask can change between process invocations. Slight overhead but guarantees consistency.

## Scanner provider: optional parameter, not required

`run_full_scan(config, provider=None)` uses optional kwarg for backward compatibility. Direct `--scan` calls still work via lazy `_get_provider()`. Only `run_full_pipeline` passes an explicit provider.

## Execution order

Plan 1 first (exception handling is foundation), then Plan 2. Within Plan 1: Task 1 (exceptions) → Task 2 (credentials) → Task 3 (reconciliation retry) → Task 4 (tests). Within Plan 2: Task 1 (scanner) and Task 2 (universe) can run in parallel, then Task 3 (permissions), then Task 4 (tests).

# Autonomous Decisions — Phase 4

These decisions were made autonomously during auto-mode planning.

## D-004: Two new test files, not one monolith
- **Category:** architecture
- **Decision:** Create test_reconcile.py and test_regime.py as separate standalone scripts
- **Alternatives:** (1) Add to test_executor.py — too large. (2) Single test_coverage.py — mixes domains.
- **Expand scope:** Could add test_scanner.py as a third file for scanner-specific edge cases

## D-005: Same test infrastructure pattern
- **Category:** implementation
- **Decision:** check(), _reset_state, sandbox pattern from test_executor.py
- **Alternatives:** (1) pytest — would change conventions. (2) unittest.TestCase — adds class boilerplate.

## D-006: MagicMock for Alpaca client in reconcile tests
- **Category:** architecture
- **Decision:** MagicMock for controlled broker responses
- **Alternatives:** (1) Monkey-patch — fragile. (2) DI refactor — out of scope.

## D-007: Synthetic RegimeState for regime tests
- **Category:** architecture
- **Decision:** Construct RegimeState directly; mock data provider for detect_regime tests
- **Alternatives:** (1) Live SPY data — non-deterministic. (2) Fixture files — extra maintenance.

# Phase 5 — Autonomous Decisions

Decisions made without user input during planning. Review and override if needed.

## D1: Launchd agent naming convention
**Decision:** Use `com.trading-bot.*` prefix instead of `com.bopeterlaanen.trading.*`
**Why:** Personal identifier in agent names isn't portable. Generic prefix works for any user.
**Risk:** Existing agents on Bo's machine use the old names. Migration requires unloading old + loading new.
**Mitigation:** setup_launchd.sh header includes migration note. schedule.sh updated to new names.

## D2: No dotenv loader — keep shell env vars
**Decision:** Keep the current pattern of exporting env vars in shell profile rather than adding python-dotenv.
**Why:** Adding a dependency just for env loading is unnecessary. Shell scripts already source from .zshrc. The .env.example serves as documentation, not as a runtime file.
**Trade-off:** Slightly more friction for new users (must export vars, not just create .env file). But no new dependency.

## D3: Two plans, not one
**Decision:** Split into Plan 1 (portability/config) and Plan 2 (documentation).
**Why:** 7 milestones decompose into two independent tracks: code changes vs documentation. Smaller plans are easier to execute and review.

## D4: Keep strategies/ standalone files as-is
**Decision:** Don't wire standalone strategies (copy_trader, wheel, trailing_ladder) into the main pipeline.
**Why:** Phase 5 is about making the repo clonable and runnable, not about feature integration. These are experimental and documented as such.

## DEC-008: Strict inequality boundary values in regime tests
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Phase 4-02 regime tests used confidence=0.8 and breadth=70.0 as test inputs expecting position_size_mult=1.25, but regime.py uses strict `>` (not `>=`).
**Decision:** Fix test values to 0.85/75.0 for the "both pass" case. Add explicit at-boundary tests (0.80/70.0) that verify the multiplier is 1.0, not 1.25.
**Rationale:** Tests that use boundary values matching the exact threshold would pass incorrectly or fail unexpectedly depending on `>` vs `>=`. Testing both above and at the boundary catches off-by-one regressions.
**Confidence:** HIGH

## DEC-009: Mock target for detect_regime tests
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan specified patching `data_provider.get_provider` but `regime.py` imports `get_provider` at module level.
**Decision:** Patch `regime.get_provider` to intercept the already-bound reference.
**Rationale:** Python's import binding means patching the original module doesn't affect the already-imported reference in `regime.py`.
**Confidence:** HIGH

## D5: Remove personal identifiers from tracked files only
**Decision:** Only fix hardcoded paths in tracked (git) files. Launchd plists in ~/Library/LaunchAgents/ are machine-local and not tracked.
**Why:** The plists are generated per-user by setup_launchd.sh. No need to track them.

## D6: SETUP-GUIDE.md surgery, not rewrite
**Decision:** Make targeted fixes to the existing SETUP-GUIDE.md rather than rewriting from scratch.
**Why:** The guide has good structure and helpful content. Only the stale parts (scheduler.py, partial exits, duplicate tables) need updating. A rewrite would lose the tested explanations.

## DEC-010: Provider passthrough must reach all 5 strategy functions
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan 03-02 Task 1 threaded provider only into run_full_scan and fetch_data, but 5 strategy functions (scan_pullback, scan_consolidation_breakout, scan_ma_bounce, scan_sector_momentum, scan_powerx) call fetch_data directly at lines 183, 257, 332, 408, 485.
**Decision:** Add provider=None parameter to all 5 strategy functions and pass through to fetch_data.
**Rationale:** Without this, the provider passthrough is dead code — strategy functions bypass it via the global singleton.
**Confidence:** HIGH

## DEC-011: ensure_cache uses existing REFRESH_DAYS, not separate 24h TTL
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan specified max_age_hours=24 but universe.py already uses REFRESH_DAYS=7 for cache staleness. Two TTLs for the same cache causes daily unnecessary Wikipedia rebuilds.
**Decision:** ensure_cache reuses REFRESH_DAYS from build_universe. One TTL, one source of truth.
**Rationale:** The intent is "make sure cache exists before scan runs," not "rebuild daily." Using the existing 7-day TTL avoids unnecessary network calls.
**Confidence:** HIGH

## DEC-012: chmod coverage expanded to 8 write paths
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan listed 6 chmod locations but missed trade_tracker.py append path (line 78) and at_open.py write_text calls (lines 294, 349).
**Decision:** Expand to 8 write paths covering all state file writes.
**Rationale:** Incomplete chmod leaves files at default 0o644 permissions, defeating the security goal.
**Confidence:** HIGH

## DEC-013: CONTRIBUTING.md must use actual scanner function names and signatures
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan 05-02 Task 2 referenced `_scan_pullback()` as a class method and `STRATEGY_RUNNERS` dict, but scanner.py uses module-level functions (`scan_pullback(ticker, config) -> Signal | None`) and a `scanners` list of tuples.
**Decision:** Fix all references to match actual code: module-level functions, correct signature, `scanners` list registration.
**Rationale:** Documentation that describes nonexistent code patterns will confuse contributors and erode trust in the guide.
**Confidence:** HIGH

## DEC-014: PowerX Optimizer docs reference flat tickers array
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan 05-02 Task 3 said "add tickers to watchlist.json under the powerx_optimizer key" but watchlist.json has a flat `tickers` array, no nested keys.
**Decision:** Fix to reference `tickers` array directly.
**Rationale:** Wrong instructions would cause a JSON structure error or silent data loss.
**Confidence:** HIGH

## DEC-015: edge_tracker auto-registers strategies, no manual step needed
**Date:** 2026-04-15
**Step:** plan-review Step B
**Context:** Plan 05-02 CONTRIBUTING.md step 5 said "Add the strategy name to edge_tracker.py." But `record_trade()` (line 139) auto-creates entries for unknown strategies.
**Decision:** Remove manual registration step from contributing guide.
**Rationale:** Telling contributors to register strategies that auto-register creates busywork and confusion when they can't find a registration point.
**Confidence:** HIGH

### D-002: Speculative plan validated: phase 3
- **Category:** implementation
- **Status:** ACTIVE
- **Confidence:** HIGH
- **Context:** No file overlap with predecessor phases (none)
- **Decision:** Plan proceeds as-is (VALID)
- **Affects:** Phase 3

### D-003: Speculative plan validated: phase 4
- **Category:** implementation
- **Status:** ACTIVE
- **Confidence:** HIGH
- **Context:** No file overlap with predecessor phases (none)
- **Decision:** Plan proceeds as-is (VALID)
- **Affects:** Phase 4

### D-004: Speculative plan validated: phase 5
- **Category:** implementation
- **Status:** ACTIVE
- **Confidence:** HIGH
- **Context:** No file overlap with predecessor phases (none)
- **Decision:** Plan proceeds as-is (VALID)
- **Affects:** Phase 5
