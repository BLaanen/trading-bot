# Coding Conventions

**Analysis Date:** 2026-04-09

## Naming Patterns

**Files:** `snake_case.py` (e.g., `scanner.py`, `risk_manager.py`, `data_provider.py`). Entry points that execute are typically named after what they do: `orchestrator.py`, `executor.py`, `backtest_momentum.py`.

**Functions:** `snake_case`, verbs where actions occur (e.g., `run_full_scan()`, `calc_rsi()`, `load_positions()`, `process_signal()`). Private helpers start with `_`: `_get_provider()`.

**Variables:** `snake_case`. Configuration and dataclass fields use full names: `entry_price`, `stop_loss`, `reward_risk_ratio` (not abbreviated).

**Classes:** `PascalCase`. Data classes use `@dataclass`: `AgentConfig`, `Signal`, `Position`, `PortfolioState`. Abstract bases end in ABC: `DataProvider(ABC)`.

## Code Style

**Formatting:** No explicit formatter found. Code follows PEP 8 style: 4-space indents, max line length ~100 chars, docstrings use triple quotes.

**Linting:** No linter config present (no `.flake8`, `.pylintrc`, `pyproject.toml`). Style is enforced by convention: use type hints extensively, avoid bare `except:`.

## Import Organization

**Order:** Standard library imports first, then third-party (pandas, numpy), then local imports. Group by purpose, separated by blank lines. Use full module imports for clarity: `from config import AgentConfig` not `import config`.

Example from `scanner.py`:
```python
import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime

from config import AgentConfig
from data_provider import get_provider
```

## Error Handling

**Patterns:** Use explicit try-except with fallback logic, not bare `except:`. Log errors and return `None` for optional data retrieval.

Example from `scanner.py`:
```python
try:
    data = _get_provider().get_bars(ticker, period=period)
    if data.empty or len(data) < 60:
        return None
    return data
except Exception:
    return None
```

For risky operations, capture and return decision objects. See `orchestrator.py` Step 3 filter layer — every rejection logged with reason.

## Logging

**Framework:** Print statements to stdout, formatted with ASCII boxes for section headers.

Example from `orchestrator.py`:
```python
print("\n" + "=" * 70)
print(f"  STEP 1: STRATEGY VALIDATION")
print("=" * 70)
print(f"  Approved strategies: {len(approved)}")
```

Use indented print blocks for hierarchical output. No formal logging library — stdout is the journal.

## Function Design

**Size:** Functions typically 20-80 lines. Scan strategies (`scan_pullback()`, `scan_ma_bounce()`) are 50-60 lines each — acceptable because they're self-contained logic flows. Extract into helpers when logic repeats: `calc_rsi()`, `find_support()` are reusable indicator functions.

**Parameters:** Keep 3-5 parameters max. Use dataclass objects for config: all functions take `config: AgentConfig`, avoid long parameter lists. Return tuples only when paired results: `calc_stochastic()` → `tuple[pd.Series, pd.Series]`.

## Module Design

**Exports:** Each module is a feature layer. `scanner.py` exports signal-building functions and the `Signal` dataclass. `risk_manager.py` exports position management: `Position`, `PortfolioState`, and functions like `load_positions()`, `evaluate_new_trade()`. No wildcard imports — be explicit.

**Data Flow:** Modules pass data through dataclass objects (`Signal`, `Position`, `PortfolioState`), not dicts. This ensures type safety and IDE autocompletion.

## Type Hints

**Pattern:** Use Python 3.10+ union syntax `list[Signal]`, `dict[str, list[str]]`, `str | None`. All function signatures include return types. Properties use `@property` decorators with computed returns, no `self` type hints needed.

Example from `scanner.py`:
```python
def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
def scan_pullback(ticker: str, config: AgentConfig) -> Signal | None:
```

## Comments

**Pattern:** Module-level docstrings explain the WHY — philosophy and math. See docstring at top of `config.py` explaining the asymmetric risk strategy. Inline comments use `─` box dividers for section breaks, not `#` comments mid-code. Code is self-documenting; comments explain trade-offs.

Example from `scanner.py`:
```python
# ─── Strategy 1: Pullback to Support in Uptrend ─────────────────────────────
# Why it works: you're buying weakness in strength...
```
