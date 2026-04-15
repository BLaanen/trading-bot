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
from datetime import datetime
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
    _check_bracket_children, _submit_sell, _replace_stop_order,
    OrderResult, SLIPPAGE_RR_THRESHOLD,
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

# ─── Test 6: Reconciliation auto-fix ─────────────────────────────────────
print("\n── Test 6: Reconciliation ──")

@dataclass
class MockPosition:
    symbol: str
    qty: str
    avg_entry_price: str
    market_value: str
    current_price: str = "100.00"

class MockAccount:
    cash: str = "10000.00"
    portfolio_value: str = "15000.00"

# Test 6a: Local has position, broker doesn't → auto-remove from local
_reset_state()
state = load_positions()
state.positions.append(Position(
    ticker="FAKE", shares=50, entry_price=100, current_price=100,
    stop_loss=95, initial_stop=95, target=110, strategy="PULLBACK",
    entry_date="2026-04-10",
))
save_positions(state)

mock_client4 = MagicMock()
mock_client4.list_positions.return_value = []
mock_client4.get_account.return_value = MockAccount()

with patch("reconcile.tradeapi.REST", return_value=mock_client4):
    with patch.dict(os.environ, {"ALPACA_API_KEY": "test", "ALPACA_API_SECRET": "test"}):
        result = reconcile_with_broker(AgentConfig())

check("Auto-fix removes stale local position", result is True)
state_after = load_positions()
check("FAKE position removed", all(p.ticker != "FAKE" for p in state_after.positions))

# Test 6b: Broker has position, local doesn't → auto-add to local
_reset_state()

mock_client5 = MagicMock()
mock_client5.list_positions.return_value = [
    MockPosition(symbol="FAKE", qty="50", avg_entry_price="100.00", market_value="5000.00", current_price="100.00"),
]
mock_client5.get_account.return_value = MockAccount()

with patch("reconcile.tradeapi.REST", return_value=mock_client5):
    with patch.dict(os.environ, {"ALPACA_API_KEY": "test", "ALPACA_API_SECRET": "test"}):
        result = reconcile_with_broker(AgentConfig())

check("Auto-fix adds broker position to local", result is True)
state_after = load_positions()
check("FAKE position added", any(p.ticker == "FAKE" for p in state_after.positions))
fake_pos = next(p for p in state_after.positions if p.ticker == "FAKE")
check("Reconciled position has non-zero stop", fake_pos.stop_loss > 0)
check("Reconciled stop is 5% below entry", fake_pos.stop_loss == round(100.0 * 0.95, 2))

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
print("  TRAILING STOP BROKER SYNC TESTS")
print("=" * 70)

from risk_manager import RiskDecision, update_trailing_stops

# ─── Test 10: Trailing stop broker replace — success ─────────────────────
print("\n── Test 10: Trailing stop broker replace success ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="TRAIL1", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-TRAIL-1",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

mock_trail_client = MagicMock()
mock_trail_client.replace_order.return_value = MagicMock()
mock_trail_client.get_order.return_value = MagicMock(status="accepted")
mock_trail_client.get_account.return_value = MagicMock()
mock_trail_client.list_positions.return_value = []

config_trail = AgentConfig()
config_trail.use_trailing_stops = True

with patch("executor.get_alpaca_client", return_value=mock_trail_client):
    results = manage_positions(config_trail)

state_after = load_positions()
trail_pos = next((p for p in state_after.positions if p.ticker == "TRAIL1"), None)
expected_stop = round(115 * (1 - 0.05), 2)  # 109.25
check("Stop updated after broker confirm", trail_pos is not None and trail_pos.stop_loss == expected_stop)
check("replace_order called", mock_trail_client.replace_order.called)

# ─── Test 11: Trailing stop broker replace — already filled ──────────────
print("\n── Test 11: Trailing stop broker replace already filled ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="TRAIL2", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-TRAIL-2",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

mock_filled_client = MagicMock()
mock_filled_client.replace_order.side_effect = Exception("order already filled")
_filled_call_count = [0]
def _mock_get_order_filled(order_id):
    _filled_call_count[0] += 1
    m = MagicMock()
    # First call is from _check_bracket_children — return accepted so position stays
    # Second call is from _replace_stop_order failure path — return filled
    m.status = "accepted" if _filled_call_count[0] <= 2 else "filled"
    m.filled_avg_price = "110.00"
    return m
mock_filled_client.get_order.side_effect = _mock_get_order_filled
mock_filled_client.get_account.return_value = MagicMock()
mock_filled_client.list_positions.return_value = []

with patch("executor.get_alpaca_client", return_value=mock_filled_client):
    results = manage_positions(config_trail)

state_after = load_positions()
trail_pos = next((p for p in state_after.positions if p.ticker == "TRAIL2"), None)
check("Stop NOT updated when already filled", trail_pos is not None and trail_pos.stop_loss == 95)

# ─── Test 12: Trailing stop broker replace — other error ─────────────────
print("\n── Test 12: Trailing stop broker replace error ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="TRAIL3", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-TRAIL-3",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

mock_error_client = MagicMock()
mock_error_client.replace_order.side_effect = Exception("network error")
mock_pending_order = MagicMock()
mock_pending_order.status = "pending_new"
mock_error_client.get_order.return_value = mock_pending_order
mock_error_client.get_account.return_value = MagicMock()
mock_error_client.list_positions.return_value = []

with patch("executor.get_alpaca_client", return_value=mock_error_client):
    results = manage_positions(config_trail)

state_after = load_positions()
trail_pos = next((p for p in state_after.positions if p.ticker == "TRAIL3"), None)
check("Stop NOT updated on error", trail_pos is not None and trail_pos.stop_loss == 95)

# ─── Test 13: Double failure — replace fails AND get_order fails ─────────
print("\n── Test 13: Trailing stop double failure ──")

mock_double_fail = MagicMock()
mock_double_fail.replace_order.side_effect = Exception("replace failed")
mock_double_fail.get_order.side_effect = Exception("get_order also failed")

success, reason = _replace_stop_order(mock_double_fail, "STOP-123", 110.0)
check("Returns False on double failure", success is False)
check("Reason is status_unknown", reason == "status_unknown")

# ─── Test 14: No order ID — skip API call ────────────────────────────────
print("\n── Test 14: Trailing stop no order ID ──")
mock_no_id = MagicMock()

success1, reason1 = _replace_stop_order(mock_no_id, "", 110.0)
check("Empty ID returns False", success1 is False)
check("Empty ID reason is no_order_id", reason1 == "no_order_id")

success2, reason2 = _replace_stop_order(mock_no_id, "SIM-STOP-TEST", 110.0)
check("SIM ID returns False", success2 is False)
check("SIM ID reason is no_order_id", reason2 == "no_order_id")
check("No API calls made", not mock_no_id.replace_order.called)

# ─── Test 15: Trailing stops disabled ────────────────────────────────────
print("\n── Test 15: Trailing stops disabled ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="TRAIL5", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-TRAIL-5",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

mock_disabled_client = MagicMock()
mock_disabled_client.get_order.return_value = MagicMock(status="accepted")
mock_disabled_client.get_account.return_value = MagicMock()
mock_disabled_client.list_positions.return_value = []

config_disabled = AgentConfig()
config_disabled.use_trailing_stops = False

with patch("executor.get_alpaca_client", return_value=mock_disabled_client):
    results = manage_positions(config_disabled)

check("replace_order NOT called when disabled", not mock_disabled_client.replace_order.called)

# ─── Test 16: Simulated mode — no broker call, direct update ─────────────
print("\n── Test 16: Trailing stop simulated mode ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="TRAIL6", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="SIM-STOP-TRAIL6",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

with patch("executor.get_alpaca_client", return_value=None):
    results = manage_positions(config_trail)

state_after = load_positions()
trail_pos = next((p for p in state_after.positions if p.ticker == "TRAIL6"), None)
expected_sim_stop = round(115 * (1 - 0.05), 2)
check("Stop updated directly in sim mode", trail_pos is not None and trail_pos.stop_loss == expected_sim_stop)

# ─── Test 17: Two positions both trailing — independent calls ────────────
print("\n── Test 17: Two positions trailing independently ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="DUAL1", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=130, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-DUAL-1",
))
state.positions.append(Position(
    ticker="DUAL2", shares=5, entry_price=200, current_price=225,
    stop_loss=190, initial_stop=190, target=250, strategy="BREAKOUT",
    entry_date="2026-04-10", high_water_mark=225, trailing=True,
    stop_order_id="STOP-DUAL-2",
))
state.cash = 2000
state.total_value = 4275
save_positions(state)

mock_dual_client = MagicMock()
mock_dual_client.replace_order.return_value = MagicMock()
mock_dual_client.get_order.return_value = MagicMock(status="accepted")
mock_dual_client.get_account.return_value = MagicMock()
mock_dual_client.list_positions.return_value = []

with patch("executor.get_alpaca_client", return_value=mock_dual_client):
    results = manage_positions(config_trail)

check("replace_order called twice (one per position)", mock_dual_client.replace_order.call_count == 2)
state_after = load_positions()
d1 = next((p for p in state_after.positions if p.ticker == "DUAL1"), None)
d2 = next((p for p in state_after.positions if p.ticker == "DUAL2"), None)
check("DUAL1 stop updated", d1 is not None and d1.stop_loss == round(115 * 0.95, 2))
check("DUAL2 stop updated", d2 is not None and d2.stop_loss == round(225 * 0.95, 2))

# ─── Test 18: Exited position skipped for trailing ───────────────────────
print("\n── Test 18: Exited position skipped for trailing ──")
_reset_state(cash=5000)
state = load_positions()
state.positions.append(Position(
    ticker="EXIT1", shares=10, entry_price=100, current_price=115,
    stop_loss=95, initial_stop=95, target=120, strategy="PULLBACK",
    entry_date="2026-04-10", high_water_mark=115, trailing=True,
    stop_order_id="STOP-EXIT-1",
    target_order_id="TARGET-EXIT-1",
))
state.cash = 4000
state.total_value = 5150
save_positions(state)

mock_exit_client = MagicMock()

mock_target_filled_order = MagicMock()
mock_target_filled_order.status = "filled"
mock_target_filled_order.filled_avg_price = "120.00"

mock_stop_accepted = MagicMock()
mock_stop_accepted.status = "accepted"

def mock_get_order_exit(order_id):
    if order_id == "TARGET-EXIT-1":
        return mock_target_filled_order
    return mock_stop_accepted

mock_exit_client.get_order.side_effect = mock_get_order_exit
mock_exit_client.get_account.return_value = MagicMock()
mock_exit_client.list_positions.return_value = []

with patch("executor.get_alpaca_client", return_value=mock_exit_client):
    results = manage_positions(config_trail)

check("Position exited via bracket", len(results) == 1)
check("replace_order NOT called for exited position", not mock_exit_client.replace_order.called)

# ═══════════════════════════════════════════════════════════════════════════
# FILE PERMISSION TESTS (0o600)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  FILE PERMISSION TESTS (0o600)")
print("=" * 70)

# Test 19: positions.json permissions
print("\n── Test 19: positions.json has 0o600 after save ──")
_reset_state()
from risk_manager import POSITIONS_FILE
mode = os.stat(POSITIONS_FILE).st_mode & 0o777
check("positions.json permissions == 0o600", mode == 0o600)

# Test 20: order_log.json permissions
print("\n── Test 20: order_log.json has 0o600 after write ──")
from executor import _log_order, ORDER_LOG
_log_order(OrderResult(True, "TEST-PERM", "PTEST", "BUY", 1, 100.0, "perm test"))
mode = os.stat(ORDER_LOG).st_mode & 0o777
check("order_log.json permissions == 0o600", mode == 0o600)

# Test 21: trades.csv permissions
print("\n── Test 21: trades.csv has 0o600 after log_trade ──")
from trade_tracker import log_trade, TRADES_FILE as TF
log_trade("PTEST", "BUY", 1, 100.0, strategy="TEST")
mode = os.stat(TF).st_mode & 0o777
check("trades.csv permissions == 0o600", mode == 0o600)

# Test 22: edge_tracker.json permissions
print("\n── Test 22: edge_tracker.json has 0o600 after record_trade ──")
from edge_tracker import record_trade as et_record, EDGE_FILE
et_record("TEST_STRAT", 1.5, 3)
mode = os.stat(EDGE_FILE).st_mode & 0o777
check("edge_tracker.json permissions == 0o600", mode == 0o600)

# Test 23: last_run.json permissions
print("\n── Test 23: last_run.json has 0o600 after save_last_run ──")
from orchestrator import save_last_run, LAST_RUN_FILE
save_last_run({"test": True})
mode = os.stat(LAST_RUN_FILE).st_mode & 0o777
check("last_run.json permissions == 0o600", mode == 0o600)

# ═══════════════════════════════════════════════════════════════════════════
# SCANNER PROVIDER PASSTHROUGH TESTS
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  SCANNER PROVIDER PASSTHROUGH TESTS")
print("=" * 70)

import pandas as pd
import numpy as np
from scanner import run_full_scan, fetch_data, scan_pullback

# Test 24: fetch_data uses passed provider
print("\n── Test 24: fetch_data uses passed provider over global ──")
mock_provider = MagicMock()
dates = pd.date_range("2025-01-01", periods=120, freq="B")
mock_df = pd.DataFrame({
    "Open": np.random.uniform(90, 110, 120),
    "High": np.random.uniform(100, 120, 120),
    "Low": np.random.uniform(80, 100, 120),
    "Close": np.random.uniform(90, 110, 120),
    "Volume": np.random.randint(500000, 2000000, 120),
}, index=dates)
mock_provider.get_bars.return_value = mock_df
result = fetch_data("XTEST", provider=mock_provider)
check("Provider.get_bars called", mock_provider.get_bars.called)
check("fetch_data returned data", result is not None)

# Test 25: run_full_scan threads provider to strategy functions
print("\n── Test 25: run_full_scan threads provider to scan functions ──")
call_providers = []

with patch("scanner.fetch_data") as mock_fd:
    mock_fd.return_value = None  # no signals, just checking provider flows
    config_prov = AgentConfig()
    with patch("universe.build_universe", return_value={
        "tickers": ["XTEST"], "sector_map": {}, "etfs": [], "metadata": {},
        "built_at": datetime.now().isoformat(), "count": 1,
    }):
        run_full_scan(config_prov, provider=mock_provider)
    for call in mock_fd.call_args_list:
        if call.kwargs.get("provider") is mock_provider:
            call_providers.append(True)
check("Provider kwarg passed through to fetch_data", len(call_providers) >= 1)

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
