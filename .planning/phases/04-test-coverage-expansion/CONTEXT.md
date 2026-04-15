---
phase: 04-test-coverage-expansion
status: locked
---

# Phase 4 Context: Test Coverage Expansion

## Decisions (Locked)

### D-004: Two new test files, not one monolith
**Category:** architecture
**Decision:** Create `test_reconcile.py` (reconciliation + empty DataFrame tests) and `test_regime.py` (regime detection + pipeline filtering tests) as separate standalone scripts.
**Rationale:** Follows existing pattern (test_simulation.py, test_executor.py). Each file stays focused. Tests for reconcile.py belong with reconcile tests; regime/orchestrator filtering tests belong together.
**Alternatives:** (1) Add all tests to test_executor.py — rejected, would make it 900+ lines and mix concerns. (2) Single test_coverage.py — rejected, two distinct domains.
**Affects:** test file organization

### D-005: Use same test infrastructure pattern (check(), _reset_state, sandbox)
**Category:** implementation
**Decision:** Replicate the sandbox + check() pattern from test_executor.py. No pytest, no unittest.
**Rationale:** Matches existing conventions (TESTING.md). Consistency > framework preferences.
**Affects:** all new test files

### D-006: Mock reconcile.py's Alpaca client via MagicMock, not live calls
**Category:** architecture
**Decision:** Use unittest.mock.MagicMock for the Alpaca REST client in reconciliation tests, same as test_executor.py does for executor tests.
**Rationale:** test_executor.py already uses MagicMock successfully. Reconciliation tests need controlled broker responses (positions, failures, qty mismatches).
**Alternatives:** (1) Monkey-patch module globals — fragile. (2) Dependency injection — would require refactoring reconcile.py, out of scope for a test-only phase.
**Affects:** test_reconcile.py

### D-007: Regime tests use synthetic RegimeState, not live SPY data
**Category:** architecture
**Decision:** Test RegimeState properties and step_filter by constructing RegimeState directly with known values. Test detect_regime by mocking the data provider to return controlled SPY DataFrames.
**Rationale:** Tests must be deterministic and offline. Real SPY data changes daily.
**Affects:** test_regime.py

## Discretion Areas

- Test naming follows existing "Test N: description" pattern but executor can adjust numbering
- Exact assertion count per test is flexible — cover the documented scenarios
- Helper functions (_make_position, _make_regime, etc.) can be structured as needed

## Deferred Ideas

- Code coverage tooling (pytest-cov or similar) — out of scope, would change test infrastructure
- Property-based testing for edge cases — future phase
- Integration tests against Alpaca paper sandbox — requires live credentials, separate concern
