# Phase 5 Context

## What this phase does
Prepares the repo so someone else can clone it, configure it, and run it. Two tracks: portability fixes (hardcoded paths, env vars, launchd setup) and documentation (README, contributing guide, setup guide cleanup).

## Dependencies on earlier phases
- Phase 3 (robustness): credential validation makes the startup experience clearer for new users
- Phase 4 (tests): test suite gives new users confidence the system works after cloning

## Key files to modify
- `schedule.sh` — hardcoded `/Users/bopeterlaanen/trading/logs`
- `monitor.sh`, `eod.sh` — hardcoded `/opt/homebrew/bin/python3.11`
- `config.py` — add .env.example pointer in docstring
- `docs/SETUP-GUIDE.md` — stale content (scheduler.py, partial exits, duplicate tables)

## Key files to create
- `.env.example` — env var template
- `README.md` — GitHub landing page
- `CONTRIBUTING.md` — how to add strategies
- `setup_launchd.sh` — generates launchd plists for any user

## What NOT to touch
- `CLAUDE.md` — Bo's session guide, not for public consumption
- `positions.json`, `trades.csv`, etc. — runtime state, gitignored
- `legacy/` — left as-is, documented as deprecated
- Standalone strategies in `strategies/` — not wiring into main pipeline

## Decisions

- [review] Scanner functions are module-level (scan_pullback, scan_powerx, etc.), not class methods. CONTRIBUTING.md must reflect this.
- [review] The `scanners` list in `run_full_scan()` (scanner.py:578) uses tuples `("Name", func)`, not a STRATEGY_RUNNERS dict. CONTRIBUTING.md registration step must match.
- [review] watchlist.json uses a flat `tickers` array — no `powerx_optimizer` key. PowerX Optimizer docs must describe the actual structure.
- [review] edge_tracker.py auto-creates strategy entries via `record_trade()` (line 139-144). No manual registration needed. CONTRIBUTING.md step 5 removed.
- [review] Plan 05-02 depends on Plan 05-01 for `.env.example`. README quickstart must work with or without it.

## Deferred Ideas

- Add an ASCII architecture diagram to README (beyond text description) — deferred to keep initial docs simple
- Add a `Makefile` or `just` file for common commands (test, scan, report) — nice for new users but adds a file to maintain
