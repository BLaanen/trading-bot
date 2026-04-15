---
phase: 04-test-coverage-expansion
plan: 2
---

## Decisions

- [review] Boundary test values must use strict-inequality-satisfying values (0.85/75.0, not 0.8/70.0) because regime.py line 65 uses `>` not `>=`
- [review] Mock target for detect_regime tests is `regime.get_provider` (module-level import), not `data_provider.get_provider`
- [review] Test 9 expanded to 4 boundary cases: both pass, confidence-at-boundary, breadth-at-boundary, confidence-below

## Deferred Ideas

- Extract max_trades calculation from orchestrator.py into a testable function (currently tested via arithmetic reimplementation, not actual code call) -- deferred because orchestrator refactor is out of scope for test coverage phase
