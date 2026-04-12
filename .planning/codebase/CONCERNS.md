# Trading System — Known Concerns & Fragile Areas

## Tech Debt

**Broad exception handling masks root causes.** Across the codebase, `except Exception:` patterns (often with bare `pass` or generic returns) hide failures:
- `data_provider.py:197-200, 206-208, 217-219` — data fetch failures logged only as print statements, don't propagate upstream
- `executor.py:110-112, 133-135, 195-196` — order submission errors swallowed; API auth failures = silent fallback to simulation
- `universe.py:113-115, 155-157, 181-183` — Wikipedia scraping failures leave universe empty or stale

Fix: Replace with specific exception types (ConnectionError, ValueError, etc.) and propagate critical failures to orchestrator's decision loop.

**N+1 scanner pattern.** `scanner.py:594-599` iterates all tickers sequentially, calling `scanner_fn(ticker)` which internally calls `fetch_data(ticker)` → `get_provider().get_bars()`. In full scan: 200+ tickers × 5 scanners = 1000+ API calls. Each ticker-strategy combo fetches the same 1-year OHLCV bar series independently.

Fix: Cache bars-per-ticker once before scanner loop, pass cached data to each strategy. Would reduce calls 5-10x.

**Stale data risk in monitor/trailing.** `executor.py` manages positions but `manage_positions()` relies on a single price snapshot per run. If monitor runs only once at 18:30 CEST, intraday stops/targets could fire without local state update for ~6 hours. Position high_water_mark may be stale.

Fix: Monitor should query latest prices from Alpaca before trailing stops (optional: run monitor twice daily).

## Security Considerations

**API credentials validated weakly.** `executor.py:55-67` and `data_provider.py:295-307` call `get_alpaca_client()` or `AlpacaProvider()` without verifying keys are valid before passing to library. If keys are malformed or expired, try/except catches and falls back to simulation silently — user won't know they're not trading live.

Fix: Add explicit credential validation on startup: `GET /account` call and confirm paper/live mode.

**State files readable by all users.** `positions.json`, `order_log.json`, `trades.csv` have permissions `644` (world-readable). On shared systems, portfolio state is exposed.

Fix: Set permissions to `600` in `trade_tracker.py:init_files()` and `risk_manager.py:save_positions()`.

**No audit log for simulated vs. live mode.** Cannot verify if trades were sent to Alpaca or simulated. Critical for debugging order mismatches.

Fix: Add mode flag to order_log.json entries.

## Performance Bottlenecks

**Universe rebuild on every scan.** `universe.py` fetches S&P 500 + NASDAQ-100 from Wikipedia on every run unless cache applies. Missing cache → scan hangs 5+ seconds on HTTP.

Fix: Pre-build universe.json at startup; scan never blocks on web requests.

**Cache invalidation fragile.** `data_provider.py:245-258` checks cache freshness by file mtime. Cache key includes `period` string — `period="1y"` and `period="1y "` generate different keys. No cache busting on provider upgrade.

Fix: Use consistent period normalization; include provider version in cache key.

**Backtesting not parallelized.** `strategy_validator.py` runs `validate_all()` sequentially. With 5 strategies × 500 tickers, validation takes minutes.

Fix: Use multiprocessing pool; checkpoint after each strategy.

## Fragile Areas

**Position sizing edge case: zero risk.** `risk_manager.py:245-247` returns 0 shares if `risk_per_share <= 0`. CAN occur if position is manually edited in JSON. Silently rejects with no feedback.

Fix: Validate `signal.risk > 0` at scanner output, not sizing stage.

**Trailing stop can invert above entry.** `risk_manager.py:305-316` calculates `stop_loss = high_water_mark * (1 - trail_distance_pct)`. If HWM is close to target, trailing can place stop ABOVE entry. Next bar exits at loss.

Fix: Clamp trailing stop to never exceed `entry_price + 0.5*risk`.

**Regime detection incomplete in downtrends.** `regime.py:76-90` only runs PULLBACK/POWERX in TRENDING_DOWN. No short strategies exist. If regime flips, cash sits idle with no defense against further drawdown.

Fix: Implement short strategies or add "exit all, sit in cash" decision.

**Reconciliation mismatch blocks all trading.** `reconcile.py:72-78` refuses to trade if ANY position mismatches. A single stale position or rounding error freezes entire system. No recovery except manual JSON edit.

Fix: Log mismatch but proceed with REDUCED position sizes. Add CLI command to re-sync.

## Dependencies at Risk

**yfinance is community-maintained, no SLA.** `data_provider.py:90-147` depends on yfinance for free data. Yahoo Finance can IP-block heavy users or change API without notice.

Risk: yfinance outage → no data → no signals → no trades. Fix: Pre-fetch data EOD Friday, cache it.

**alpaca-trade-api version lock uncertain.** `requirements.txt` specifies `>=3.0` with no upper bound. Alpaca may break backward compatibility in v4+. Library uses undocumented `order.legs` attribute.

Risk: Dependency upgrade breaks bracket parsing. Fix: Pin to `==3.2.1` after testing.

**backtesting library inactive.** `strategy_validator.py` uses backtesting.py but maintainer is inactive. No pandas 2.1+ support tested.

Risk: Future pandas incompatibility. Fix: Freeze `backtesting==0.3.3` and pandas `<2.2` or migrate to vectorbt.

## Test Coverage Gaps

**No integration test for reconciliation failure.** `test_executor.py` and `test_simulation.py` mock or skip reconcile. Can't reproduce broker-vs-local mismatch without live API.

Fix: Add integration test with mock Alpaca API returning deliberate mismatches.

**No stress test for regime flips.** If regime changes mid-scan (market crash at 14:00 ET), strategies allowed at scan start may be disallowed by execution. Execution proceeds with wrong position size.

Fix: Check regime before EVERY signal execution, not just at step start.

**No fallback chain tests.** `data_provider.py` tries Alpaca → Yahoo. If both fail, returns empty DataFrame. Scanner handles `data is None` but `data.empty` crashes calc_* functions.

Fix: Unit test `test_empty_dataframe_handling()` — verify all calc_* return gracefully on 0 bars.

**Monitor not tested end-to-end.** `manage_positions()` never tested to verify trailing stops update positions.json and broker state.

Fix: Add `test_monitor_trailing_stop_updated()` with synthetic position and mock price.

---

**Actionable priority:**
1. **CRITICAL:** Credential validation on startup (security + UX)
2. **HIGH:** Cache scanner data per-ticker; fix N+1 pattern
3. **HIGH:** Reconciliation recovery path (currently blocks trading)
4. **MEDIUM:** State file permissions 600 (security)
5. **MEDIUM:** Broad exception → specific types (debugging)
