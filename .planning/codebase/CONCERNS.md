# Codebase Concerns

**Analysis Date:** 2026-04-09

## Tech Debt

**Silent API failures with broad exception handling:**
- Issue: Multiple providers catch `Exception` globally, masking real errors (rate limits, auth failures, network timeouts)
- Files: `data_provider.py:126-127`, `data_provider.py:146-147`, `data_provider.py:192-193`, `data_provider.py:199-200`, `data_provider.py:208-209`, `scanner.py:76-77`
- Impact: System gracefully degrades but loses debugging information; auth issues go unnoticed until production
- Fix approach: Catch specific exceptions (e.g., `AuthenticationError`, `RateLimitError`, `TimeoutError`); log and emit metrics before returning fallback

**Price data gaps not validated before use:**
- Issue: `executor.py:241-242` only checks if ticker exists in prices dict, doesn't validate against None or stale prices
- Files: `executor.py:237-244`, `data_provider.py:129-147` (bulk_prices)
- Impact: If a price fetch returns None for a ticker in portfolio, position PnL calculations will fail silently; trailing stop triggers may use stale high_water_mark
- Fix approach: Validate all prices non-None before position updates; require minimum freshness check (< 1hr old) before trading

**N+1 scanner pattern — loops through 300+ tickers per scanner:**
- Issue: `scanner.py:610-618` calls scanner function for EACH ticker in ALL tickers (5 scanners × 300+ tickers = 1500+ function calls per scan)
- Files: `scanner.py:610-618`, `scanner.py:587-645`
- Impact: At ~200ms per ticker, scan cycle takes 5+ minutes; each call to `fetch_data()` re-downloads bars even if cached
- Fix approach: Batch fetch all ticker bars once, pass to scanner functions; vectorize indicator calcs where possible (e.g., RSI across all tickers in one call)

**Risky bare except in strategy validation:**
- Issue: `strategy_validator.py:346` catches all exceptions during backtest validation without logging reason
- Files: `strategy_validator.py:342-347`
- Impact: Backtesting can silently fail for bad data, returning false negatives; no signal what went wrong (bad OHLC shape, missing column, etc.)
- Fix approach: Log exception type/message before returning failed result; add validation for OHLC shape before backtest

## Security Considerations

**API credentials not validated before use:**
- Risk: `executor.py:47-52` and `data_provider.py:285-294` check env vars but don't validate format or expiration; invalid keys silently fall back to Yahoo Finance
- Files: `executor.py:47-52`, `data_provider.py:285-294`
- Recommendations: Add startup check: call `test_api_connection()` on Alpaca; warn if keys present but invalid; refuse to trade on invalid keys

**positions.json and order_log.json not encrypted:**
- Risk: Trade history, entry prices, stops all stored plain-text on disk
- Files: `risk_manager.py:128-150` (POSITIONS_FILE), `executor.py:33` (ORDER_LOG)
- Recommendations: Encrypt sensitive fields at rest; use `cryptography` lib; rotate keys on access

## Performance Bottlenecks

**Weekly universe rebuild blocks on Wikipedia fetch:**
- Problem: `universe.py:75-95` makes 2 HTTP requests to Wikipedia (S&P 500 + NASDAQ-100) sequentially, no timeout; blocks entire scan if Wikipedia slow
- File: `universe.py:75-95`, `universe.py:120-140`

**Scanning 300+ tickers sequentially instead of parallel:**
- Problem: `scanner.py:610-618` processes one ticker at a time; CPU idle 95% of time waiting for data_provider calls
- File: `scanner.py:610-618`

**Cache invalidation too aggressive on live data:**
- Problem: `data_provider.py:235-248` expires all non-historical cache every 4 hours; forces re-download on every scan if using real-time Alpaca
- File: `data_provider.py:225-228`, `data_provider.py:235-248`

## Fragile Areas

**Position sizing can round to 0 shares:**
- Why fragile: `risk_manager.py:250` uses `int()` truncation; tight stops + low risk amount can round down to 0
- File: `risk_manager.py:238-250`
- Test coverage: No test for minimum share size; affects small accounts (<$1K)
- Fix: Add check `if shares_by_risk < 1: return REJECT`

**Trailing stop logic assumes price always moves up:**
- Why fragile: `risk_manager.py:288-300` updates high_water_mark but only if current_price > previous high_water_mark; gaps down overnight cause stale HWM
- File: `risk_manager.py:288-300`
- Test coverage: Untested for overnight gaps; may trail stop at wrong level after hard reversal

**Partial exit can create fractional shares:**
- Why fragile: `executor.py:145` calculates `exit_shares = int(pos.shares * config.partial_exit_pct)` but doesn't validate remaining shares >= 1
- File: `executor.py:144-147`
- Test coverage: Manual trades OK, but backtester may fail if exit creates 0 shares

**Regime detection depends on single 200-SMA cross:**
- Why fragile: `regime.py` determines bull/bear/sideways from SPY 200 SMA alone; one false signal derails edge tracking
- File: `regime.py` (full file)
- Test coverage: No validation against known market regimes (March 2020, Jan 2022, etc.)

## Dependencies at Risk

**yfinance (0.2.28+) — single point of failure:**
- Risk: Yahoo Finance API is not guaranteed stable; yfinance reverse-engineers it; breakage = entire system halts
- Migration plan: Ensure Alpaca key/secret are set for fallback; add Twelve Data or Alpha Vantage as tertiary provider

**alpaca-trade-api (3.0+) — unstable API surface:**
- Risk: Alpaca frequently changes endpoint behavior; 3.0 had breaking changes in bar requests
- Migration plan: Pin to specific version (3.0.4+); test API compatibility monthly; have manual execution docs

**backtesting (0.3.3) — minimal maintenance:**
- Risk: Backtesting lib hasn't had major updates; community fork `backtrader` is more maintained
- Migration plan: If backtesting breaks, switch to `backtrader` or pandas-only backtest loop

## Test Coverage Gaps

**No integration tests for Alpaca order flow:**
- What's not tested: Real order submission, fills, position updates from live API
- Priority: High — live trading depends on this working
- Gap: Only simulated orders are tested

**No tests for data provider fallback chain:**
- What's not tested: Behavior when Alpaca fails mid-scan; whether Yahoo provider gracefully takes over
- Priority: High — if Alpaca auth breaks, system must degrade safely
- Gap: Only happy path tested

**No stress tests for trailing stops with gaps:**
- What's not tested: Overnight gaps > ATR; fast market opens; what happens if price skips stop_loss level
- Priority: Medium — edge case but capital at risk
- Gap: Simulator doesn't model pre-market gaps

**Strategy validator backtest edge cases:**
- What's not tested: Minimum data requirements (< 200 bars); NaN in OHLC; dividend/split adjusted vs raw prices
- Priority: Medium — can cause silent validation failures
- Gap: No parametrized tests for data quality issues
