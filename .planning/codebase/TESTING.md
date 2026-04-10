# Testing Patterns

**Analysis Date:** 2026-04-09

## Test Framework

**Runner:** Python's built-in `unittest` module (implicit via test file structure). No pytest config found. Test file `test_simulation.py` runs standalone: `python test_simulation.py`.

**Run Commands:**
```bash
python test_simulation.py        # Full system simulation
python orchestrator.py --validate  # Unit-level strategy validation via backtest
python orchestrator.py --monitor   # Live position management test
```

No formal test runner config. Tests are executable scripts that print results to stdout.

## Test File Organization

**Location:** `test_simulation.py` is at project root (same level as `orchestrator.py`). No `tests/` directory. Tests import modules directly via `sys.path.insert()`.

**Naming:** Single file `test_simulation.py`. Reflects end-to-end testing philosophy — entire pipeline tested in one scenario rather than isolated unit tests.

## Test Structure

**Patterns:** Linear test flow with numbered sections (TEST 1, TEST 2, etc.). Each section:
1. Generates synthetic data or state
2. Runs system components
3. Prints assertions and intermediate state
4. Progresses to next scenario

No assertions — validation is visual (print statements verify expected behavior). Test traces a full trade lifecycle: entry → price moves → trailing stops → partial exits → final close.

Example from `test_simulation.py`:
```python
print("\n" + "─" * 70)
print("  TEST 1: Signal Generation")
print("─" * 70)

signals = [
    Signal(ticker="AAPL", strategy="POWERX", ...),
    ...
]

for s in signals:
    print(f"  {s.ticker:<6} R:R={s.reward_risk:.1f}x")
```

## Mocking

**Framework:** Manual mocking via synthetic data generation. `test_simulation.py` creates fake OHLCV data with `generate_trending_data()`:

```python
def generate_trending_data(ticker: str, days: int = 200, 
                          start_price: float = 100,
                          trend: float = 0.0005, 
                          volatility: float = 0.015) -> pd.DataFrame:
    """Generate realistic OHLCV data with a trend."""
    np.random.seed(hash(ticker) % 2**31)
    ...
```

Price movement scenarios are hardcoded dicts:
```python
price_moves = {
    "AAPL": 199.00,   # Up ~2%
    "NVDA": 845.00,   # Down slightly
}
```

No mocking library (no `unittest.mock`). State is mocked by creating `PortfolioState` objects directly and manipulating `position.current_price`.

## Coverage

**Requirements:** None enforced. No coverage tool or targets specified. Test coverage is determined by manual inspection: does the end-to-end test exercise all major code paths?

**Strategy validation (backtesting) happens in `strategy_validator.py` — validates signals against historical data per strategy type, ensuring only strategies with Sharpe >= 0.5 and win rate >= 40% are approved for trading.

## Test Data

**Pattern:** Synthetic data is seeded for reproducibility (`np.random.seed(hash(ticker) % 2**31)`). Hard-coded signal prices test specific scenarios: rejection cases (bad R:R), edge cases (stop at entry price), normal flow (5+ positions through lifecycle).

Test verifies 6 key properties (see test output):
1. Position sizing scales to 1% risk per trade
2. Signals with R:R < 2.0x are rejected
3. Partial exits execute at target, stop moves to breakeven
4. Trailing stops activate after 1R profit
5. Circuit breakers pause trading on 20% drawdown
6. Final P&L math = R × position size × 1R dollar amount

No assertions — visual output is the verdict.
