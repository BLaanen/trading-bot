# Code Conventions

## Naming Patterns

**Files:** `snake_case.py`. Domain modules: `scanner.py`, `executor.py`, `risk_manager.py`, `regime.py`, `trade_tracker.py`, `data_provider.py`. Entry point: `orchestrator.py`.

**Functions & Variables:** `snake_case`. Private functions prefixed with `_`: `_get_provider()`, `_wait_for_fill()`, `_submit_bracket_order()`, `_check_bracket_children()`, `_submit_sell()`.

**Classes & Dataclasses:** `PascalCase`. Core types use `@dataclass`: `AgentConfig`, `Signal`, `Position`, `PortfolioState`, `OrderResult`, `RiskDecision`, `ValidationResult`, `RegimeState`, `CorrelationData`.

**Constants:** `UPPER_SNAKE_CASE`. Thresholds, paths, timeouts: `SLIPPAGE_RR_THRESHOLD`, `FILL_POLL_TIMEOUT`, `ORDER_LOG`, `POSITIONS_FILE`, `TRADES_FILE`.

## Code Style

**Format:** PEP 8. No explicit formatter enforced (no `.flake8` or `pyproject.toml`). Lines ~70–100 chars. 4-space indents.

**Docstrings:** Module-level docstrings are narrative (why + how). See `config.py` (explains 1R asymmetric risk), `scanner.py` (signal structure), `executor.py` (bracket lifecycle), `risk_manager.py` (position sizing + trailing).

**Section markers:** Visual navigation via `# ─── Comment ───────────────────` blocks separating logic sections.

## Import Organization

Order: stdlib → third-party → local. No blank lines between groups.

```python
import sys, json, os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod

from config import AgentConfig
from scanner import Signal
from risk_manager import Position, load_positions, save_positions
```

Optional SDK imports wrapped in `try/except`:
```python
try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False
```

## Error Handling

**Try-except pattern:** Catch specific exceptions where possible. Print warnings, fall back gracefully. No custom exceptions.

```python
try:
    client = tradeapi.REST(api_key, api_secret, config.alpaca_base_url)
    client.get_account()
    return client
except Exception as e:
    print(f"  [WARN] Alpaca connection failed: {e}")
    print(f"  [WARN] Falling back to simulated execution")
    return None
```

**API polling:** Explicit deadline loops with time.time() checks. See `_wait_for_fill()` — polls for 30s, returns (status, fill_price) tuple.

## Logging

**No logging module.** All output via `print()` with structured prefixes.

**Format:** `[LEVEL] message` where LEVEL ∈ {`PASS`, `FAIL`, `WARN`, `INFO`, `EXIT`, `TRAIL`, `SLIPPAGE_REJECT`, `CRITICAL`}.

```python
print(f"  [SLIPPAGE_REJECT] R:R dropped to {new_rr:.2f}")
print(f"  → Filled at ${actual_fill_price:.2f}")
```

**Sections:** Use `= * 70` delimiters for major steps:
```python
print("\n" + "=" * 70)
print("  STEP 1: STRATEGY VALIDATION")
print("=" * 70)
```

## Function Design

**Signature pattern:** Core object first, config last. 3–5 parameters typical.

```python
def process_signal(signal: Signal, config: AgentConfig, regime_name: str = "") -> OrderResult | None:
def calculate_position_size(signal: Signal, state: PortfolioState, config: AgentConfig) -> int:
def _submit_bracket_order(client, ticker: str, shares: int, stop_price: float, target_price: float) -> OrderResult:
```

**Return types:** Explicit union syntax (`OrderResult | None`), tuple for paired results (`tuple[str, float]`), dataclass for complex returns.

**Size:** 20–60 lines. Private helpers extract reusable logic (`_wait_for_fill()`, `_check_bracket_children()`, `_submit_sell()`).

**Properties in dataclasses:** Use `@property` for computed fields. `Position` has `market_value`, `cost_basis`, `pnl`, `pnl_pct`, `r_multiple`, `hit_stop`, `hit_target`. Risk calculations leverage these.

## Module Design

**Pattern:** Export small public API (1–2 dataclasses + 3–5 functions). Cascade: `orchestrator.py` → domain modules (scanner, executor, risk_manager) → `config.py`.

**Data flow:** Pass domain objects (`Signal`, `Position`, `PortfolioState`), never dicts. Example pipeline:
- `scanner.py` generates `list[Signal]`
- `risk_manager.py` evaluates Signal + PortfolioState → `RiskDecision`
- `executor.py` processes Signal → `OrderResult`

**State files:** JSON (positions, order log, last run state) and CSV (trades, portfolio value). Loaded/saved via explicit `load_positions()` / `save_positions()` / `log_trade()`. Path set via `TRADING_STATE_DIR` env var (defaults to script dir).

## Type Hints

**Required on all functions.** Parameter and return types mandatory.

```python
def fetch_data(ticker: str, period: str = "1y") -> pd.DataFrame | None:
def log_trade(ticker: str, action: str, shares: int, price: float, ...) -> None:
def get_bulk_prices(self, tickers: list[str]) -> dict[str, float]:
```

**Union syntax:** Use `|` (PEP 604), not `Union[]`.

**Dataclass fields:** Full type annotations.
```python
@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    trailing: bool = False
    bracket_order_id: str = ""
```

## Comments

**Module docstrings:** Explain problem, solution, and context. Example: "Execution Agent: Handles position lifecycle — entry (bracket order at broker), monitor (check exits), exit (Python backup if broker-side fails)."

**Inline comments:** Minimal. Only for non-obvious math/assumptions: `# Cumulative R gained/lost`, `# 200 SMA as major trend filter`.

**No comment-only lines** between blocks. Use section markers instead.
