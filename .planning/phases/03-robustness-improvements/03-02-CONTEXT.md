# Context — Plan 03-02: Scanner Cache, Universe Prebuild & File Permissions

## Decisions

- [review] Provider kwarg must be threaded through all 5 strategy scan functions (scan_pullback, scan_consolidation_breakout, scan_ma_bounce, scan_sector_momentum, scan_powerx), not just run_full_scan. Each calls fetch_data directly at lines 183, 257, 332, 408, 485.
- [review] ensure_cache() reuses REFRESH_DAYS (7 days) from build_universe, not a separate 24h TTL. Avoids daily unnecessary Wikipedia rebuilds.
- [review] signal.alarm must save/restore pre-existing SIGALRM handler. Documented as main-thread-only constraint.
- [review] chmod coverage expanded from 6 to 8 write paths: added trade_tracker.py append (line 78) and at_open.py write_text (lines 294, 349).
- [review] Test count expanded from 3 to 9. Universe tests go in new test_universe.py file. Tests cover timeout fallback, stale cache, signal restoration, and permissions on all state files.
- [review] chmod-after-write race condition accepted for current threat model (solo macOS paper trading). If deployed to shared/VPS, switch to atomic write pattern (write to temp, chmod temp, rename).
- [review] Plan clarified: provider passthrough solves provider re-initialization overhead, not N+1 per-ticker HTTP calls (that would require a batch fetch layer in data_provider).

## Deferred Ideas

- Atomic file write pattern (write → temp → chmod → rename) — deferred, solo macOS threat model doesn't warrant complexity
- DRY helper function for chmod pattern (`_secure_write`) — deferred, 8 one-line additions don't yet warrant an abstraction
- Replace signal.alarm with concurrent.futures timeout — deferred, more portable but adds complexity for a call that runs once per pipeline
- Per-ticker data caching in provider (batch fetch) to fully solve N+1 — separate concern, belongs in a future plan
