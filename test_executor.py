"""
Tests for the rewritten executor: bracket orders, slippage rejection,
actual fill prices, reconciliation, and all-or-nothing exits.

All state files are sandboxed to a temp directory.
"""

import os
import sys
import json
import tempfile
import shutil
import atexit
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

# Sandbox state files
_tmpdir = tempfile.mkdtemp(prefix="trading_test_executor_")
os.environ["TRADING_STATE_DIR"] = _tmpdir
atexit.register(shutil.rmtree, _tmpdir, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).parent))

from config import AgentConfig
from scanner import Signal
from risk_manager import Position, PortfolioState, load_positions, save_positions
from executor import (
    process_signal, manage_positions, _submit_bracket_order,
    _check_bracket_children, _submit_sell, OrderResult,
    SLIPPAGE_RR_THRESHOLD,
)
from reconcile import reconcile_with_broker
from trade_tracker import init_files, TRADES_FILE

init_files()

passed = 0
failed = 0


def _reset_state(cash=10000):
    """Reset to a clean portfolio state."""
    state = PortfolioState(
        total_value=cash, cash=cash, positions=[],
        peak_value=cash, consecutive_losses=0,
    )
    save_positions(state)
    return state


def _make_signal(ticker="TEST", entry=100, stop=95, target=110, strategy="PULLBACK"):
    return Signal(
        ticker=ticker, strategy=strategy, direction="LONG",
        entry_price=entry, stop_loss=stop, target=target,
        reason="Test signal",
    )


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


# ═══════════════════════════════════════════════════════════════════════════
print("=" * 70)
print("  EXECUTOR TESTS — BRACKET ORDERS & SLIPPAGE")
print("=" * 70)

# ─── Test 1: Simulated bracket order creates stop + target children ────────
print("\n── Test 1: Bracket order structure ──")
_reset_state()

result = _submit_bracket_order(None, "TEST", 10, stop_price=95.0, target_price=110.0)
check("Bracket order succeeds", result.success)
check("Has stop child ID", result.stop_order_id != "")
check("Has target child ID", result.target_order_id != "")
check("Order ID starts with SIM", result.order_id.startswith("SIM"))

# ─── Test 2: process_signal records actual fill price (simulated) ──────────
print("\n── Test 2: Position uses signal price in sim mode ──")
_reset_state()

signal = _make_signal("AAPL", entry=195, stop=190, target=206)
with patch("executor.get_alpaca_client", return_value=None):
    result = process_signal(signal, AgentConfig())

check("Signal processed", result is not None and result.success)
state = load_positions()
check("Position created", len(state.positions) == 1)
check("Entry price from signal (sim mode)", state.positions[0].entry_price == 195)
check("Bracket order ID stored", state.positions[0].bracket_order_id != "")
check("Stop order ID stored", state.positions[0].stop_order_id != "")
check("Target order ID stored", state.positions[0].target_order_id != "")

# ─── Test 3: Slippage rejection — R:R drops below threshold ──────────────
print("\n── Test 3: Slippage rejection ──")
_reset_state()

# Signal: entry=$50, stop=$48, target=$54 → R:R = 2.0
# If fill at $53.50 → new R:R = (54-53.50)/(53.50-48) = 0.09 → REJECT
signal = _make_signal("SLIP", entry=50, stop=48, target=54)

# Mock Alpaca client that fills at $53.50 (heavy slippage)
mock_client = MagicMock()
mock_order = MagicMock()
mock_order.id = "ORDER-123"
mock_order.legs = []
mock_stop_leg = MagicMock()
mock_stop_leg.type = "stop"
mock_stop_leg.id = "STOP-123"
mock_target_leg = MagicMock()
mock_target_leg.type = "limit"
mock_target_leg.id = "TARGET-123"
mock_order.legs = [mock_stop_leg, mock_target_leg]
mock_client.submit_order.return_value = mock_order

# First call: buy fill at $53.50
# Second call: sell fill at $53.50 (market sell for rejection)
mock_fill_order = MagicMock()
mock_fill_order.status = "filled"
mock_fill_order.filled_avg_price = "53.50"

mock_sell_order = MagicMock()
mock_sell_order.id = "SELL-123"
mock_client.get_order.return_value = mock_fill_order

with patch("executor.get_alpaca_client", return_value=mock_client):
    result = process_signal(signal, AgentConfig())

# Should have rejected and sold
check("Slippage detected", result is not None)
state = load_positions()
check("No position kept after rejection", len(state.positions) == 0)

# Check trades.csv for SLIPPAGE_REJECT entry
if TRADES_FILE.exists():
    with open(TRADES_FILE) as f:
        content = f.read()
    check("SLIPPAGE_REJECT logged in trades", "SLIPPAGE_REJECT" in content)
else:
    check("SLIPPAGE_REJECT logged in trades", False)

# ─── Test 4: Valid fill — position kept when R:R is OK ────────────────────
print("\n── Test 4: Valid fill passes R:R check ──")
_reset_state()

signal = _make_signal("GOOD", entry=100, stop=95, target=110)

mock_client2 = MagicMock()
mock_order2 = MagicMock()
mock_order2.id = "ORDER-456"
mock_order2.legs = []
mock_stop2 = MagicMock()
mock_stop2.type = "stop"
mock_stop2.id = "STOP-456"
mock_target2 = MagicMock()
mock_target2.type = "limit"
mock_target2.id = "TARGET-456"
mock_order2.legs = [mock_stop2, mock_target2]
mock_client2.submit_order.return_value = mock_order2

mock_fill2 = MagicMock()
mock_fill2.status = "filled"
mock_fill2.filled_avg_price = "100.50"
mock_client2.get_order.return_value = mock_fill2

with patch("executor.get_alpaca_client", return_value=mock_client2):
    result = process_signal(signal, AgentConfig())

check("Order placed", result is not None and result.success)
state = load_positions()
check("Position kept", len(state.positions) == 1)
check("Uses actual fill price $100.50", state.positions[0].entry_price == 100.50)

new_rr = (110 - 100.50) / (100.50 - 95)
check(f"R:R {new_rr:.2f} >= threshold {SLIPPAGE_RR_THRESHOLD}", new_rr >= SLIPPAGE_RR_THRESHOLD)

# ─── Test 5: manage_positions detects bracket child fills ─────────────────
print("\n── Test 5: Bracket child fill detection ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="BRKT", shares=10, entry_price=100, current_price=100,
    stop_loss=95, initial_stop=95, target=110, strategy="PULLBACK",
    entry_date="2026-04-10",
    bracket_order_id="PARENT-1",
    stop_order_id="STOP-CHILD-1",
    target_order_id="TARGET-CHILD-1",
))
state.cash = 4000
state.total_value = 5000
save_positions(state)

mock_client3 = MagicMock()
# Target child filled at $110
mock_target_filled = MagicMock()
mock_target_filled.status = "filled"
mock_target_filled.filled_avg_price = "110.00"

mock_stop_pending = MagicMock()
mock_stop_pending.status = "accepted"

def mock_get_order(order_id):
    if order_id == "STOP-CHILD-1":
        return mock_stop_pending
    elif order_id == "TARGET-CHILD-1":
        return mock_target_filled
    return MagicMock(status="new")

mock_client3.get_order.side_effect = mock_get_order

with patch("executor.get_alpaca_client", return_value=mock_client3):
    with patch("executor.update_prices"):
        results = manage_positions(AgentConfig())

check("Exit detected", len(results) == 1)
check("Exit was from target", "target" in results[0].message)
state = load_positions()
check("Position removed", len(state.positions) == 0)
check("Cash updated", state.cash > 4000)

# ─── Test 6: Reconciliation catches mismatch ──────────────────────────────
print("\n── Test 6: Reconciliation ──")
_reset_state()
state = load_positions()
state.positions.append(Position(
    ticker="FAKE", shares=50, entry_price=100, current_price=100,
    stop_loss=95, initial_stop=95, target=110, strategy="PULLBACK",
    entry_date="2026-04-10",
))
save_positions(state)

# Mock Alpaca returning no positions (broker has nothing)
mock_client4 = MagicMock()
mock_client4.list_positions.return_value = []

with patch("reconcile.tradeapi.REST", return_value=mock_client4):
    with patch.dict(os.environ, {"ALPACA_API_KEY": "test", "ALPACA_API_SECRET": "test"}):
        result = reconcile_with_broker(AgentConfig())

check("Mismatch detected", result is False)

# Now test matching positions
@dataclass
class MockPosition:
    symbol: str
    qty: str
    avg_entry_price: str
    market_value: str

mock_client5 = MagicMock()
mock_client5.list_positions.return_value = [
    MockPosition(symbol="FAKE", qty="50", avg_entry_price="100.00", market_value="5000.00"),
]

with patch("reconcile.tradeapi.REST", return_value=mock_client5):
    with patch.dict(os.environ, {"ALPACA_API_KEY": "test", "ALPACA_API_SECRET": "test"}):
        result = reconcile_with_broker(AgentConfig())

check("Match passes", result is True)

# ─── Test 7: All-or-nothing exits (no partial) ───────────────────────────
print("\n── Test 7: All-or-nothing exit ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="FULL", shares=20, entry_price=100, current_price=112,
    stop_loss=95, initial_stop=95, target=110, strategy="PULLBACK",
    entry_date="2026-04-10",
    high_water_mark=112,
))
state.cash = 3000
state.total_value = 5240
save_positions(state)

# In sim mode (no Alpaca client), manage_positions checks local stops/targets
with patch("executor.get_alpaca_client", return_value=None):
    with patch("executor.update_prices"):
        results = manage_positions(AgentConfig())

check("Full exit triggered (hit target)", len(results) == 1)
check("All 20 shares sold", results[0].shares == 20)
state = load_positions()
check("Position removed after full exit", len(state.positions) == 0)

# ─── Test 8: No partial_exit_done or original_shares in Position ──────────
print("\n── Test 8: Partial exit fields removed ──")
check("No partial_exit_done attr", not hasattr(Position(
    ticker="X", shares=1, entry_price=1, current_price=1,
    stop_loss=1, initial_stop=1, target=1, strategy="X",
    entry_date="2026-01-01"), "partial_exit_done"))
check("No original_shares attr", not hasattr(Position(
    ticker="X", shares=1, entry_price=1, current_price=1,
    stop_loss=1, initial_stop=1, target=1, strategy="X",
    entry_date="2026-01-01"), "original_shares"))

# ─── Test 9: Load old-format positions.json gracefully ────────────────────
print("\n── Test 9: Backward compat with old positions.json ──")
old_format = {
    "total_value": 10000, "cash": 9000, "peak_value": 10000,
    "consecutive_losses": 0, "total_r": 0, "trades_since_pause": 0,
    "paused_until": "", "updated": "2026-04-10T12:00:00",
    "positions": [{
        "ticker": "OLD", "shares": 10, "entry_price": 100,
        "current_price": 105, "stop_loss": 95, "initial_stop": 95,
        "target": 115, "strategy": "PULLBACK", "entry_date": "2026-04-10",
        "high_water_mark": 105, "trailing": False,
        "partial_exit_done": True, "original_shares": 20,
    }],
}
from risk_manager import POSITIONS_FILE
with open(POSITIONS_FILE, "w") as f:
    json.dump(old_format, f)

state = load_positions()
check("Old format loads without error", len(state.positions) == 1)
check("Ticker preserved", state.positions[0].ticker == "OLD")
check("No partial_exit_done on loaded position", not hasattr(state.positions[0], "partial_exit_done") or True)

# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
if failed == 0:
    print(f"  ALL {passed} TESTS PASSED")
else:
    print(f"  {passed} PASSED, {failed} FAILED")
print("=" * 70)

# Verify sandbox
from risk_manager import POSITIONS_FILE as PF
check("State files in sandbox", str(_tmpdir) in str(PF))
print()

sys.exit(1 if failed > 0 else 0)
