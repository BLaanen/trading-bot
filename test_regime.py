"""
REGIME DETECTION & PIPELINE FILTERING TESTS

Tests for regime detection, regime-based filtering, position sizing,
and strategy allowlisting across market conditions.

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

# Sandbox state files
_tmpdir = tempfile.mkdtemp(prefix="trading_test_regime_")
os.environ["TRADING_STATE_DIR"] = _tmpdir
atexit.register(shutil.rmtree, _tmpdir, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).parent))

from config import AgentConfig
from scanner import Signal
from regime import Regime, RegimeState, detect_regime
from orchestrator import step_filter
from risk_manager import Position, PortfolioState, load_positions, save_positions
from trade_tracker import init_files

init_files()

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


def _reset_state(cash=10000):
    """Reset to a clean portfolio state."""
    state = PortfolioState(
        total_value=cash, cash=cash, positions=[],
        peak_value=cash, consecutive_losses=0,
    )
    save_positions(state)
    return state


def _make_regime(regime_type=Regime.TRENDING_UP, confidence=0.8,
                 spy_vs_200=5.0, breadth=70.0, vol_pct=40.0,
                 mom_20d=3.0, mom_60d=5.0, golden_cross=True):
    return RegimeState(
        regime=regime_type, confidence=confidence,
        spy_vs_200=spy_vs_200, breadth=breadth,
        volatility_percentile=vol_pct,
        momentum_20d=mom_20d, momentum_60d=mom_60d,
        golden_cross=golden_cross,
    )


def _make_signal(ticker="TEST", entry=100, stop=95, target=110, strategy="PULLBACK"):
    return Signal(
        ticker=ticker, strategy=strategy, direction="LONG",
        entry_price=entry, stop_loss=stop, target=target,
        reason="Test signal",
    )


# ---------------------------------------------------------------------------
# Test 1: TRENDING_UP regime properties
# ---------------------------------------------------------------------------
print("\nTest 1: TRENDING_UP regime properties")
regime = _make_regime(Regime.TRENDING_UP, confidence=0.85, breadth=75.0)
check("allowed_strategies == all 5",
      regime.allowed_strategies == ["PULLBACK", "BREAKOUT", "MA_BOUNCE", "SECTOR_MOMENTUM", "POWERX"])
check("max_positions == 6", regime.max_positions == 6)
check("position_size_mult == 1.25 (high confidence+breadth)",
      regime.position_size_mult == 1.25)

regime_low = _make_regime(Regime.TRENDING_UP, confidence=0.6)
check("position_size_mult == 1.0 (low confidence)",
      regime_low.position_size_mult == 1.0)

# ---------------------------------------------------------------------------
# Test 2: SIDEWAYS regime properties
# ---------------------------------------------------------------------------
print("\nTest 2: SIDEWAYS regime properties")
regime_sw = _make_regime(Regime.SIDEWAYS)
check("allowed_strategies == [PULLBACK, POWERX]",
      regime_sw.allowed_strategies == ["PULLBACK", "POWERX"])
check("max_positions == 3", regime_sw.max_positions == 3)
check("position_size_mult == 0.5", regime_sw.position_size_mult == 0.5)

# ---------------------------------------------------------------------------
# Test 3: TRENDING_DOWN regime properties
# ---------------------------------------------------------------------------
print("\nTest 3: TRENDING_DOWN regime properties")
regime_td = _make_regime(Regime.TRENDING_DOWN)
check("allowed_strategies == [SECTOR_MOMENTUM, POWERX]",
      regime_td.allowed_strategies == ["SECTOR_MOMENTUM", "POWERX"])
check("max_positions == 2", regime_td.max_positions == 2)
check("position_size_mult == 0.25", regime_td.position_size_mult == 0.25)

# ---------------------------------------------------------------------------
# Test 4: detect_regime no data
# ---------------------------------------------------------------------------
print("\nTest 4: detect_regime no data")
mock_provider = MagicMock()
mock_provider.get_bars.return_value = None
with patch("regime.get_provider", return_value=mock_provider):
    result = detect_regime(AgentConfig())
check("regime == SIDEWAYS", result.regime == Regime.SIDEWAYS)
check("confidence == 0.3", result.confidence == 0.3)
check("breadth == 50", result.breadth == 50)

# ---------------------------------------------------------------------------
# Test 5: detect_regime short data
# ---------------------------------------------------------------------------
print("\nTest 5: detect_regime short data")
import pandas as pd
short_df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(100)]})
mock_provider2 = MagicMock()
mock_provider2.get_bars.return_value = short_df
with patch("regime.get_provider", return_value=mock_provider2):
    result2 = detect_regime(AgentConfig())
check("regime == SIDEWAYS", result2.regime == Regime.SIDEWAYS)
check("confidence == 0.3", result2.confidence == 0.3)

# ---------------------------------------------------------------------------
# Test 6: step_filter regime
# ---------------------------------------------------------------------------
print("\nTest 6: step_filter regime")
_reset_state(cash=10000)
filter_signals = [
    _make_signal(ticker="A", strategy="PULLBACK"),
    _make_signal(ticker="B", strategy="BREAKOUT"),
    _make_signal(ticker="C", strategy="POWERX"),
    _make_signal(ticker="D", strategy="MA_BOUNCE"),
]
sideways_regime = _make_regime(Regime.SIDEWAYS)
filter_config = AgentConfig()
filter_config.paper_exploration_mode = True
approved_all = {"PULLBACK": ["*"], "BREAKOUT": ["*"], "POWERX": ["*"], "MA_BOUNCE": ["*"]}
filtered = step_filter(filter_signals, approved=approved_all, config=filter_config, regime=sideways_regime)
check("exactly 2 signals remain", len(filtered) == 2)
filtered_strategies = {s.strategy for s in filtered}
check("only PULLBACK and POWERX", filtered_strategies == {"PULLBACK", "POWERX"})

# ---------------------------------------------------------------------------
# Test 7: max_trades capped by regime.max_positions minus current positions
# ---------------------------------------------------------------------------
print("\nTest 7: max_trades capping")
config7 = AgentConfig()
config7.paper_exploration_mode = True
regime7 = _make_regime(Regime.SIDEWAYS)  # max_positions = 3

# 2 current positions → max_trades = min(ceiling, 3 - 2) = min(6, 1) = 1
ceiling7 = min(config7.exploration_max_positions, regime7.max_positions * 2)
check("ceiling == 6", ceiling7 == 6)
max_trades_2 = min(ceiling7, regime7.max_positions - 2)
check("max_trades == 1 with 2 positions", max_trades_2 == 1)

# 3 current positions → max_trades = min(6, 3 - 3) = 0
max_trades_3 = min(ceiling7, regime7.max_positions - 3)
check("max_trades == 0 with 3 positions (at capacity)", max_trades_3 == 0)

# ---------------------------------------------------------------------------
# Test 8: step_filter with regime=None skips regime filtering
# ---------------------------------------------------------------------------
print("\nTest 8: step_filter no regime")
_reset_state(cash=10000)
signals_8 = [
    _make_signal(ticker="E", strategy="PULLBACK"),
    _make_signal(ticker="F", strategy="BREAKOUT"),
]
config8 = AgentConfig()
config8.paper_exploration_mode = True
approved_8 = {"PULLBACK": ["*"], "BREAKOUT": ["*"]}
filtered_8 = step_filter(signals_8, approved=approved_8, config=config8, regime=None)
check("all signals pass through (no regime filter)", len(filtered_8) == 2)
strats_8 = {s.strategy for s in filtered_8}
check("both PULLBACK and BREAKOUT present", strats_8 == {"PULLBACK", "BREAKOUT"})

# ---------------------------------------------------------------------------
# Test 9: TRENDING_UP high-confidence position_size_mult boundary
# ---------------------------------------------------------------------------
print("\nTest 9: position_size_mult boundary")
r9a = _make_regime(Regime.TRENDING_UP, confidence=0.85, breadth=75.0)
check("confidence=0.85, breadth=75 → mult == 1.25", r9a.position_size_mult == 1.25)

r9b = _make_regime(Regime.TRENDING_UP, confidence=0.80, breadth=75.0)
check("confidence=0.80 (boundary) → mult == 1.0", r9b.position_size_mult == 1.0)

r9c = _make_regime(Regime.TRENDING_UP, confidence=0.85, breadth=70.0)
check("breadth=70.0 (boundary) → mult == 1.0", r9c.position_size_mult == 1.0)

r9d = _make_regime(Regime.TRENDING_UP, confidence=0.7, breadth=80.0)
check("confidence=0.7, breadth=80 → mult == 1.0", r9d.position_size_mult == 1.0)

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*70}")
    if failed:
        sys.exit(1)
    print("All tests passed!")
