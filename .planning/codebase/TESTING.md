# Testing Framework & Patterns

## Test Framework

**No pytest, unittest, or nose.** Tests are **standalone executable scripts** run with `python test_*.py`. Output is print-based; assertions are custom `check()` function calls (not assert statements).

**Test files:** `test_simulation.py` (end-to-end), `test_executor.py` (bracket orders & slippage). Both at project root.

**Runner:** `python test_simulation.py` and `python test_executor.py`. No test discovery. Both run to completion and print pass/fail counts.

## Run Commands

```bash
python test_simulation.py        # Full pipeline: scan → risk → execute → monitor → report
python test_executor.py          # Bracket orders, slippage, reconciliation
python test_simulation.py 2>&1 | tail -20  # See summary
```

## Test File Organization

**Location:** Project root, same level as `orchestrator.py`.

**Structure per test file:**

1. **Sandbox setup:** Redirect state files to temp dir BEFORE importing trading modules
2. **Imports & helpers:** Import config, modules, define `_reset_state()`, `_make_signal()`, `generate_trending_data()`
3. **Test sections:** Numbered TEST blocks with visual dividers (`= * 70`, `─ * 70`)
4. **Results summary:** Final print of `{passed} passed, {failed} failed`

## Test Structure

**Linear flow with sections.** Each test block:
1. Reset state (call `_reset_state(cash=10000)`)
2. Set up test data (signals, prices, positions)
3. Run component(s) under test
4. Check results via `check(name, condition)`

Example (`test_executor.py` lines 75–80):
```python
print("\n── Test 1: Bracket order structure ──")
_reset_state()
result = _submit_bracket_order(None, "TEST", 10, stop_price=95.0, target_price=110.0)
check("Bracket order succeeds", result.success)
check("Order has ID", result.order_id != "")
```

## Assertion Style

**Custom `check()` function.** No assert statements. Tallies pass/fail globally.

```python
def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")
```

Output immediately visible; counters track overall result. See `test_executor.py` lines 60–67.

## Mocking & Synthetic Data

**No unittest.mock.patch.** Instead: synthetic data generation + simulated execution.

**Synthetic OHLCV:** `generate_trending_data()` in `test_simulation.py` creates realistic price series using random walk with drift.

```python
def generate_trending_data(ticker: str, days: int = 200, start_price: float = 100,
                           trend: float = 0.0005, volatility: float = 0.015) -> pd.DataFrame:
    np.random.seed(hash(ticker) % 2**31)  # Deterministic
    returns = np.random.normal(trend, volatility, days)
    close = start_price * np.cumprod(1 + returns)
    # ... generate OHLC from close
    return DataFrame with Open, High, Low, Close, Volume
```

**Manual signals:** Build via Signal constructor, not scanner. Example:
```python
Signal(
    ticker="AAPL", strategy="POWERX", direction="LONG",
    entry_price=195.00, stop_loss=190.50, target=204.00,
    reason="Triple confirm: RSI(7)=62 cross, MACD hist +0.45",
)
```

**Alpaca mock:** Functions check `if client is None` and use simulated execution. `_submit_bracket_order(None, ...)` returns synthetic OrderResult. See `executor.py` line 165.

**State isolation:** Temp directory sandboxes all file writes. See `test_simulation.py` lines 26–28:
```python
_tmpdir = tempfile.mkdtemp(prefix="trading_test_")
os.environ["TRADING_STATE_DIR"] = _tmpdir
atexit.register(shutil.rmtree, _tmpdir, ignore_errors=True)
```

## Coverage Requirements

**No code coverage tool enforced.** Coverage is manual: tests exercise critical paths.

**Critical paths tested:**
- Signal generation + R:R validation
- Position sizing (risk calculation, share count)
- Bracket order structure + fill polling
- Slippage rejection (R:R degradation)
- Trailing stop activation + updates
- All-or-nothing exits (stop + target)
- Portfolio state persistence (load/save)
- Edge cases: empty portfolio, max positions, pause logic

**Both test files verify end-to-end.** `test_simulation.py` is comprehensive; `test_executor.py` focuses on execution logic.

## Test Data Patterns

**Reproducible synthetic:** `np.random.seed(hash(ticker) % 2**31)` ensures same price series per ticker across runs.

**Hard-coded signals:** R:R ratios, stops, targets explicit in test data. Example: `Signal(entry=100, stop=95, target=110)` = 5% risk, 10% reward, R:R 2.0.

**Timestamps:** `datetime.now()` or explicit ISO strings.

**CSV validation:** Read trade_tracker CSV output post-test. `get_stats()` parses trades.csv to count wins, losses, sum P&L.

**No fixtures.** Fresh state created per test via `_reset_state()` and helpers.

## Test Data Safety

**Before running `test_simulation.py`:** Read comments. It sandboxes to temp dir — real positions.json/trades.csv never touched.

**After running:** Temp dir auto-cleaned via `atexit.register(shutil.rmtree)`.

**Check results:** Final output shows `Passed: N, Failed: M`. If M > 0, review failures and re-run to debug.

**Integration test (test_simulation.py):** Full pipeline (scan, risk, execute, monitor, report) with synthetic data. Slowest but most comprehensive.

**Unit test (test_executor.py):** Focused on bracket orders, slippage, reconciliation. Faster, more targeted.
