# Contributing to the Trading System

## Adding a New Strategy

### Scanner Strategies

Scanner strategies live in `scanner.py` as module-level functions. There is no Scanner class.

**Step 1 — Write the function.**

Add a module-level function to `scanner.py` following the pattern of `scan_pullback()`:

```python
def scan_my_strategy(ticker: str, config: AgentConfig, provider=None) -> Signal | None:
    df = fetch_data(ticker)
    if df is None or len(df) < 50:
        return None
    # ... analysis logic ...
    return Signal(ticker=ticker, strategy="MY_STRATEGY", ...)
```

The function must:
- Accept `ticker: str`, `config: AgentConfig`, and `provider=None`
- Fetch its own data via `fetch_data(ticker)`
- Return a `Signal` namedtuple on a valid setup, or `None` if nothing qualifies

**Step 2 — Register it in `run_full_scan()`.**

Around line 579 in `scanner.py`, there is a `scanners` list of tuples:

```python
scanners = [
    ("Pullback", scan_pullback),
    ("Breakout", scan_consolidation_breakout),
    ("MA Bounce", scan_ma_bounce),
    ("Sector Momentum", scan_sector_momentum),
    ("PowerX", scan_powerx),
]
```

Add your function as a new tuple:

```python
    ("My Strategy", scan_my_strategy),
```

**Step 3 — Add config parameters if needed.**

Any new tunable values belong in the `AgentConfig` dataclass in `config.py`. Do not hardcode thresholds inside the scanner function.

**Step 4 — No edge tracker registration needed.**

`edge_tracker.py` auto-creates an entry for any strategy the first time a trade is recorded under that strategy name. Nothing to do manually.

---

### Standalone Strategies

For strategies that do not fit the scan-one-ticker pattern (for example, running a wheel on a single ETF), use the standalone approach:

1. Create a new file under `strategies/` (e.g., `strategies/my_strategy.py`).
2. Follow the pattern of `strategies/trailing_ladder.py` — a self-contained runner that reads `AgentConfig`, manages its own state, and places orders directly.
3. If the strategy should run on a schedule, wire it into `eod.sh`.

---

## Code Conventions

| Rule | Detail |
|------|--------|
| Config | All parameters live in `AgentConfig` in `config.py`. No magic numbers in strategy code. |
| Orders | Every buy must be a bracket order with a stop-loss and a take-profit. No naked buys. |
| State | Runtime state goes in JSON files (`positions.json`, etc.). These are gitignored and must not be committed. |
| Tests | Test files are named `test_*.py` and live at the repo root. |
| Secrets | API keys come from environment variables only. Never put them in code or config files. |

---

## Running Tests

```bash
python test_simulation.py    # Full pipeline with synthetic data — no broker connection required
python test_executor.py      # Bracket order creation, slippage rejection, and reconciliation logic
```

Run both after any change to `scanner.py`, `executor.py`, `reconcile.py`, or `config.py` before the next scheduled run.
