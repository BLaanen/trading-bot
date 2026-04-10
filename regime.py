"""
Market Regime Detector

THE most important missing piece. Our strategies are all long-biased
trend-following. In a bear market or choppy sideways, they get destroyed.

This module answers one question: "Should I be trading right now?"

Three regimes:
  TRENDING_UP   → full position sizes, all strategies active
  SIDEWAYS      → half size, only PULLBACK and POWERX (higher-quality)
  TRENDING_DOWN → no new longs, cash is a position

Detection uses SPY as the market proxy:
  1. Price vs 200 SMA          → above = bullish regime
  2. 50 EMA vs 200 SMA         → golden/death cross
  3. % of universe above 200   → market breadth (how many stocks participating)
  4. Volatility regime (ATR)   → expanding vol = danger
  5. Rate of change momentum   → speed of trend

A world-class trader doesn't just find good entries — they know when
NOT to trade. The best trade is sometimes no trade.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from config import AgentConfig
from data_provider import get_provider


class Regime(Enum):
    TRENDING_UP = "TRENDING_UP"
    SIDEWAYS = "SIDEWAYS"
    TRENDING_DOWN = "TRENDING_DOWN"


@dataclass
class RegimeState:
    regime: Regime
    confidence: float          # 0-1 how sure we are
    spy_vs_200: float          # % above/below 200 SMA
    breadth: float             # % of universe above their 200 SMA
    volatility_percentile: float  # Current vol vs historical (0-100)
    momentum_20d: float        # 20-day rate of change on SPY
    momentum_60d: float        # 60-day rate of change on SPY
    golden_cross: bool         # 50 EMA > 200 SMA
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def position_size_mult(self) -> float:
        """How much to scale position sizes based on regime.

        Not binary — scales continuously. Even in downtrends you can
        trade, but with much smaller size and only the best setups.
        """
        if self.regime == Regime.TRENDING_UP:
            if self.confidence > 0.8 and self.breadth > 70:
                return 1.25  # Push harder in confirmed strong trend
            return 1.0
        elif self.regime == Regime.SIDEWAYS:
            return 0.5   # Half size in chop
        else:
            # Downtrend: not zero, but very selective
            # 25% size = you CAN trade, but only with absolute best setups
            return 0.25

    @property
    def allowed_strategies(self) -> list[str]:
        """Which strategies to run based on regime.

        Key insight: in a bear market, counter-trend strategies can
        still work (sectors rotating into defense, oversold bounces),
        but trend-following strategies (breakout, MA bounce) will fail
        because the trend is against you.
        """
        if self.regime == Regime.TRENDING_UP:
            return ["PULLBACK", "BREAKOUT", "MA_BOUNCE", "SECTOR_MOMENTUM", "POWERX"]
        elif self.regime == Regime.SIDEWAYS:
            # Only the highest-conviction, triple-confirmation strategies
            return ["PULLBACK", "POWERX"]
        else:
            # Downtrend: only relative strength plays and defensive sectors
            # SECTOR_MOMENTUM can find energy/healthcare/staples even in bear markets
            # POWERX triple confirmation filters out most noise
            # NO breakout or MA bounce — those need a trend to ride
            return ["SECTOR_MOMENTUM", "POWERX"]

    @property
    def max_positions(self) -> int:
        """Adjust max positions based on regime."""
        if self.regime == Regime.TRENDING_UP:
            return 6
        elif self.regime == Regime.SIDEWAYS:
            return 3   # Fewer positions in chop
        else:
            return 2   # Bear: 1-2 positions max, only the best


def detect_regime(config: AgentConfig) -> RegimeState:
    """Detect current market regime using SPY as proxy."""
    provider = get_provider()

    # Get SPY data
    spy_data = provider.get_bars("SPY", period="2y")
    if spy_data is None or spy_data.empty or len(spy_data) < 200:
        # Can't determine — assume sideways (conservative)
        return RegimeState(
            regime=Regime.SIDEWAYS, confidence=0.3,
            spy_vs_200=0, breadth=50, volatility_percentile=50,
            momentum_20d=0, momentum_60d=0, golden_cross=True,
        )

    close = spy_data["Close"]
    latest = float(close.iloc[-1])

    # ── Signal 1: Price vs 200 SMA ──
    sma200 = float(close.rolling(200).mean().iloc[-1])
    spy_vs_200 = (latest / sma200 - 1) * 100  # % above/below

    # ── Signal 2: Golden/Death Cross (50 EMA vs 200 SMA) ──
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    golden_cross = ema50 > sma200

    # ── Signal 3: Market Breadth ──
    # What % of our universe is above their own 200 SMA?
    try:
        from universe import get_scan_tickers
        all_tickers = get_scan_tickers()
    except Exception:
        all_tickers = list(set(config.core_etfs + config.sector_etfs))
    above_200 = 0
    total_checked = 0

    for ticker in all_tickers:
        try:
            data = provider.get_bars(ticker, period="1y")
            if data is not None and not data.empty and len(data) >= 200:
                t_close = data["Close"]
                t_sma200 = float(t_close.rolling(200).mean().iloc[-1])
                if float(t_close.iloc[-1]) > t_sma200:
                    above_200 += 1
                total_checked += 1
        except Exception:
            continue

    breadth = (above_200 / total_checked * 100) if total_checked > 0 else 50

    # ── Signal 4: Volatility Regime ──
    # Compare current ATR to historical ATR
    high = spy_data["High"]
    low = spy_data["Low"]
    tr = pd.concat([
        high - low,
        abs(high - close.shift(1)),
        abs(low - close.shift(1)),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    atr_current = float(atr14.iloc[-1])

    # Percentile of current ATR vs last year
    atr_year = atr14.iloc[-252:]
    vol_percentile = float((atr_year < atr_current).mean() * 100)

    # ── Signal 5: Momentum (Rate of Change) ──
    mom_20d = (latest / float(close.iloc[-20]) - 1) * 100 if len(close) >= 20 else 0
    mom_60d = (latest / float(close.iloc[-60]) - 1) * 100 if len(close) >= 60 else 0

    # ── Regime Classification ──
    bull_signals = 0
    bear_signals = 0
    total_signals = 5

    # Price above 200 SMA
    if spy_vs_200 > 2:
        bull_signals += 1
    elif spy_vs_200 < -2:
        bear_signals += 1

    # Golden cross
    if golden_cross:
        bull_signals += 1
    else:
        bear_signals += 1

    # Breadth
    if breadth > 60:
        bull_signals += 1
    elif breadth < 40:
        bear_signals += 1

    # Momentum
    if mom_20d > 2 and mom_60d > 0:
        bull_signals += 1
    elif mom_20d < -2 and mom_60d < 0:
        bear_signals += 1

    # Volatility (high vol in downtrend = bearish, high vol in uptrend = caution)
    if vol_percentile < 60:
        bull_signals += 1  # Low/normal vol is constructive
    elif vol_percentile > 80:
        bear_signals += 1  # Very high vol = stress

    # Classify
    if bull_signals >= 4:
        regime = Regime.TRENDING_UP
        confidence = bull_signals / total_signals
    elif bear_signals >= 3:
        regime = Regime.TRENDING_DOWN
        confidence = bear_signals / total_signals
    else:
        regime = Regime.SIDEWAYS
        confidence = 1 - abs(bull_signals - bear_signals) / total_signals

    return RegimeState(
        regime=regime,
        confidence=confidence,
        spy_vs_200=round(spy_vs_200, 2),
        breadth=round(breadth, 1),
        volatility_percentile=round(vol_percentile, 1),
        momentum_20d=round(mom_20d, 2),
        momentum_60d=round(mom_60d, 2),
        golden_cross=golden_cross,
    )


def print_regime(state: RegimeState):
    """Print regime analysis."""
    colors = {
        Regime.TRENDING_UP: "BULLISH",
        Regime.SIDEWAYS: "NEUTRAL",
        Regime.TRENDING_DOWN: "BEARISH",
    }

    print(f"\n{'='*70}")
    print(f"  MARKET REGIME — {colors[state.regime]} ({state.confidence:.0%} confidence)")
    print(f"{'='*70}")
    print(f"  SPY vs 200 SMA:     {state.spy_vs_200:+.1f}%  {'above' if state.spy_vs_200 > 0 else 'BELOW'}")
    print(f"  50/200 Cross:       {'Golden (bullish)' if state.golden_cross else 'Death (bearish)'}")
    print(f"  Market Breadth:     {state.breadth:.0f}% above 200 SMA "
          f"({'healthy' if state.breadth > 60 else 'narrow' if state.breadth > 40 else 'weak'})")
    print(f"  Volatility:         {state.volatility_percentile:.0f}th percentile "
          f"({'calm' if state.volatility_percentile < 40 else 'normal' if state.volatility_percentile < 70 else 'elevated' if state.volatility_percentile < 85 else 'EXTREME'})")
    print(f"  Momentum 20d:       {state.momentum_20d:+.1f}%")
    print(f"  Momentum 60d:       {state.momentum_60d:+.1f}%")
    print(f"\n  Position sizing:    {state.position_size_mult:.0%} of normal")
    print(f"  Max positions:      {state.max_positions}")
    print(f"  Active strategies:  {', '.join(state.allowed_strategies) or 'NONE — cash'}")

    if state.regime == Regime.TRENDING_DOWN:
        print(f"\n  >>> BEARISH: Trade defensively. 25% size, max 2 positions. <<<")
        print(f"  >>> Focus on relative strength (sectors bucking the trend). <<<")
    elif state.regime == Regime.SIDEWAYS:
        print(f"\n  >>> CHOPPY: Selective mode. Half size, only best setups. <<<")


if __name__ == "__main__":
    config = AgentConfig()
    regime = detect_regime(config)
    print_regime(regime)
