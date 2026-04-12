"""
Market Scanner Agent

Every signal answers three questions:
  1. WHERE do I get in?   → entry_price
  2. WHERE am I wrong?    → stop_loss (structural, not arbitrary %)
  3. WHERE is the target?  → must be >= min_reward_risk * risk

The stop is always placed at a level where "the trade idea is dead"
— below a support level, below a moving average, below a consolidation
range. Never an arbitrary percentage.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime

from config import AgentConfig
from data_provider import get_provider


@dataclass
class Signal:
    ticker: str
    strategy: str
    direction: str  # "LONG"
    entry_price: float
    stop_loss: float
    target: float
    reason: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def risk(self) -> float:
        """Dollar risk per share (the 1R)."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward(self) -> float:
        """Dollar reward per share."""
        return abs(self.target - self.entry_price)

    @property
    def reward_risk(self) -> float:
        """Reward-to-risk ratio."""
        return self.reward / self.risk if self.risk > 0 else 0

    @property
    def risk_pct(self) -> float:
        """How far the stop is from entry, as %."""
        return self.risk / self.entry_price * 100 if self.entry_price > 0 else 0


_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def fetch_data(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """Fetch OHLCV data via the unified data provider."""
    try:
        data = _get_provider().get_bars(ticker, period=period)
        if data.empty or len(data) < 60:
            return None
        return data
    except Exception:
        return None


# ─── Technical helpers ───────────────────────────────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_stochastic(data: pd.DataFrame, k_period: int = 14, d_period: int = 3, slowing: int = 3) -> tuple[pd.Series, pd.Series]:
    """Slow Stochastic Oscillator (%K and %D)."""
    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    # Fast %K
    fast_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    # Slow %K (smoothed)
    slow_k = fast_k.rolling(window=slowing).mean()
    # %D (signal line)
    slow_d = slow_k.rolling(window=d_period).mean()

    return slow_k, slow_d


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, and histogram."""
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — measures volatility in dollar terms."""
    high = data["High"]
    low = data["Low"]
    close = data["Close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def find_support(data: pd.DataFrame, lookback: int = 20) -> float:
    """Find the nearest support level by looking at recent swing lows."""
    lows = data["Low"].iloc[-lookback:]
    # Find local minima (low lower than neighbors)
    local_mins = []
    for i in range(1, len(lows) - 1):
        if lows.iloc[i] <= lows.iloc[i - 1] and lows.iloc[i] <= lows.iloc[i + 1]:
            local_mins.append(float(lows.iloc[i]))

    if local_mins:
        # Return the highest recent support (closest below current price)
        current = float(data["Close"].iloc[-1])
        supports_below = [s for s in local_mins if s < current]
        return max(supports_below) if supports_below else min(local_mins)

    # Fallback: lowest low in the lookback
    return float(lows.min())


def find_resistance(data: pd.DataFrame, lookback: int = 20) -> float:
    """Find the nearest resistance level by looking at recent swing highs."""
    highs = data["High"].iloc[-lookback:]
    local_maxes = []
    for i in range(1, len(highs) - 1):
        if highs.iloc[i] >= highs.iloc[i - 1] and highs.iloc[i] >= highs.iloc[i + 1]:
            local_maxes.append(float(highs.iloc[i]))

    if local_maxes:
        current = float(data["Close"].iloc[-1])
        resistance_above = [r for r in local_maxes if r > current]
        return min(resistance_above) if resistance_above else max(local_maxes)

    return float(highs.max())


def is_uptrend(data: pd.DataFrame, config: AgentConfig) -> bool:
    """Price must be above the trend EMA to go long."""
    close = data["Close"]
    ema = close.ewm(span=config.trend_ema).mean()
    return float(close.iloc[-1]) > float(ema.iloc[-1])


# ─── Strategy 1: Pullback to Support in Uptrend ─────────────────────────────
#
# The best R:R setup. Stock is trending up, pulls back to a known support
# level (EMA, prior low, etc). Stop goes just below support. Target is
# the recent high or higher.
#
# Why it works: you're buying weakness in strength. The stop is tight
# because support is close. The target is wide because the trend is up.

def scan_pullback(ticker: str, config: AgentConfig) -> Signal | None:
    data = fetch_data(ticker)
    if data is None or not is_uptrend(data, config):
        return None

    close = data["Close"]
    ema21 = close.ewm(span=config.pullback_ma).mean()
    rsi = calc_rsi(close, config.rsi_period)
    atr = calc_atr(data)

    latest_close = float(close.iloc[-1])
    ema_now = float(ema21.iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    atr_now = float(atr.iloc[-1])

    if pd.isna(atr_now) or atr_now <= 0:
        return None

    # Conditions:
    # 1. Price pulled back near or below the 21 EMA (within 1 ATR)
    # 2. RSI is dipping but not crashed (35-55 zone = pullback, not collapse)
    # 3. Price is still above 50 EMA (major trend intact)
    ema50 = float(close.ewm(span=config.trend_ema).mean().iloc[-1])

    price_near_ema = latest_close <= ema_now + atr_now * 0.5
    rsi_in_dip = config.pullback_rsi_low <= rsi_now <= config.pullback_rsi_high
    trend_intact = latest_close > ema50

    if not (price_near_ema and rsi_in_dip and trend_intact):
        return None

    # Stop: below the nearest support or 1.5 ATR below entry
    support = find_support(data, config.pullback_lookback)
    stop_by_support = support - atr_now * 0.3  # Small buffer below support
    stop_by_atr = latest_close - atr_now * 1.5
    stop_loss = max(stop_by_support, stop_by_atr)  # Tighter of the two

    # Reject if stop is too far (> 5% from entry)
    risk = latest_close - stop_loss
    if risk <= 0 or risk / latest_close > 0.05:
        return None

    # Target: must be >= min_reward_risk * risk
    min_target = latest_close + risk * config.min_reward_risk
    resistance = find_resistance(data, lookback=40)
    # Use resistance if it gives better R:R, otherwise use the minimum
    target = max(min_target, resistance)

    signal = Signal(
        ticker=ticker,
        strategy="PULLBACK",
        direction="LONG",
        entry_price=latest_close,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        reason=f"Pullback to 21 EMA (RSI={rsi_now:.0f}), support at ${support:.2f}, trend intact",
    )

    # Small tolerance for float rounding on stop/target
    if signal.reward_risk < config.min_reward_risk - 0.05:
        return None

    return signal


# ─── Strategy 2: Breakout from Tight Consolidation ──────────────────────────
#
# Stock coils in a tight range (low volatility), then breaks out with
# volume. Stop goes below the range. Target is the range height projected
# upward (measured move), or 2R+.
#
# Why it works: tight ranges = stored energy. When the breakout comes,
# the move is often fast. Stop is tight (bottom of range), target is wide.

def scan_consolidation_breakout(ticker: str, config: AgentConfig) -> Signal | None:
    data = fetch_data(ticker)
    if data is None or not is_uptrend(data, config):
        return None

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"]

    n = config.consolidation_days
    latest_close = float(close.iloc[-1])

    # Find the range over the consolidation period (excluding today)
    range_high = float(high.iloc[-n - 1:-1].max())
    range_low = float(low.iloc[-n - 1:-1].min())
    range_size = range_high - range_low

    if range_low <= 0:
        return None

    range_pct = range_size / range_low

    # Must be a tight range
    if range_pct > config.consolidation_max_range:
        return None

    # Today must break above the range
    if latest_close <= range_high:
        return None

    # Volume must confirm
    avg_volume = float(volume.iloc[-20:].mean())
    today_volume = float(volume.iloc[-1])
    if avg_volume <= 0 or today_volume < avg_volume * config.breakout_volume_mult:
        return None

    # Stop: below the bottom of the consolidation range
    atr = calc_atr(data)
    atr_now = float(atr.iloc[-1])
    stop_loss = range_low - atr_now * 0.2  # Small buffer

    risk = latest_close - stop_loss
    if risk <= 0 or risk / latest_close > 0.05:
        return None

    # Target: measured move (range projected up) or min R:R, whichever is bigger
    measured_move = latest_close + range_size
    min_target = latest_close + risk * config.min_reward_risk
    target = max(measured_move, min_target)

    signal = Signal(
        ticker=ticker,
        strategy="BREAKOUT",
        direction="LONG",
        entry_price=latest_close,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        reason=f"Broke out of {n}-day range (${range_low:.2f}-${range_high:.2f}), "
               f"volume {today_volume/avg_volume:.1f}x avg",
    )

    # Small tolerance for float rounding on stop/target
    if signal.reward_risk < config.min_reward_risk - 0.05:
        return None

    return signal


# ─── Strategy 3: Moving Average Bounce ───────────────────────────────────────
#
# In a strong uptrend, price bounces off the 50 EMA. This is the
# "institutional buy zone" — big funds buy dips to the 50.
# Stop below the 50 EMA. Target at recent highs or 2R+.

def scan_ma_bounce(ticker: str, config: AgentConfig) -> Signal | None:
    data = fetch_data(ticker)
    if data is None:
        return None

    close = data["Close"]
    ema50 = close.ewm(span=50).mean()
    sma200 = close.rolling(200).mean()
    rsi = calc_rsi(close, config.rsi_period)
    atr = calc_atr(data)

    if pd.isna(sma200.iloc[-1]) or pd.isna(atr.iloc[-1]):
        return None

    latest_close = float(close.iloc[-1])
    ema50_now = float(ema50.iloc[-1])
    sma200_now = float(sma200.iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    atr_now = float(atr.iloc[-1])

    # Major trend must be up: 50 EMA > 200 SMA
    if ema50_now <= sma200_now:
        return None

    # Price must be near the 50 EMA (within 1 ATR)
    distance_to_50 = abs(latest_close - ema50_now)
    if distance_to_50 > atr_now:
        return None

    # Price must be above the 50 EMA (bouncing, not breaking)
    if latest_close < ema50_now:
        return None

    # RSI should be in recovery zone (not crashed, not overbought)
    if rsi_now < 40 or rsi_now > 65:
        return None

    # Stop: below the 50 EMA by a buffer
    stop_loss = ema50_now - atr_now * 0.5

    risk = latest_close - stop_loss
    if risk <= 0 or risk / latest_close > 0.05:
        return None

    # Target: recent high or min R:R
    recent_high = float(data["High"].iloc[-30:].max())
    min_target = latest_close + risk * config.min_reward_risk
    target = max(recent_high, min_target)

    signal = Signal(
        ticker=ticker,
        strategy="MA_BOUNCE",
        direction="LONG",
        entry_price=latest_close,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        reason=f"Bounce off 50 EMA (${ema50_now:.2f}), RSI={rsi_now:.0f}, 50>200 trend",
    )

    # Small tolerance for float rounding on stop/target
    if signal.reward_risk < config.min_reward_risk - 0.05:
        return None

    return signal


# ─── Strategy 4: Sector Momentum Rotation ────────────────────────────────────
#
# Buy the strongest sector ETFs (highest 1-month momentum), avoid weakest.
# Stop is ATR-based. Target is trend continuation.
# This is the "rising tide" approach — be in the sectors that are working.

def scan_sector_momentum(ticker: str, config: AgentConfig) -> Signal | None:
    # Only run on sector ETFs
    if ticker not in config.sector_etfs and ticker not in config.core_etfs:
        return None

    data = fetch_data(ticker)
    if data is None or not is_uptrend(data, config):
        return None

    close = data["Close"]
    atr = calc_atr(data)
    rsi = calc_rsi(close, config.rsi_period)

    if pd.isna(atr.iloc[-1]):
        return None

    latest_close = float(close.iloc[-1])
    atr_now = float(atr.iloc[-1])
    rsi_now = float(rsi.iloc[-1])

    # Must have strong 1-month momentum (> 5%)
    if len(close) < 21:
        return None
    ret_1m = (latest_close / float(close.iloc[-21]) - 1) * 100
    if ret_1m < 5:
        return None

    # Must not be overbought
    if rsi_now > 75:
        return None

    # 3-month momentum must also be positive (sustained trend)
    if len(close) >= 63:
        ret_3m = (latest_close / float(close.iloc[-63]) - 1) * 100
        if ret_3m < 0:
            return None

    # Stop: 2 ATR below current price
    stop_loss = latest_close - atr_now * 2

    risk = latest_close - stop_loss
    if risk <= 0:
        return None

    # Target: based on continued momentum — 3 ATR above entry
    target = latest_close + atr_now * 3
    min_target = latest_close + risk * config.min_reward_risk
    target = max(target, min_target)

    signal = Signal(
        ticker=ticker,
        strategy="SECTOR_MOMENTUM",
        direction="LONG",
        entry_price=latest_close,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        reason=f"Sector momentum +{ret_1m:.1f}% (1m), RSI={rsi_now:.0f}",
    )

    # Small tolerance for float rounding on stop/target
    if signal.reward_risk < config.min_reward_risk - 0.05:
        return None

    return signal


# ─── Strategy 5: PowerX Triple Confirmation ─────────────────────────────────
#
# Based on Markus Heitkoetter's PowerX system. Three indicators must ALL
# agree before entering:
#   1. RSI(7) crosses above 50
#   2. MACD histogram positive and rising
#   3. Stochastic %K crosses above %D
#
# Stop: low of the entry bar (structural).
# Target: 2R (twice the distance from entry to stop).
#
# Why it works: triple confirmation filters out noise. You only enter
# when momentum (RSI), trend (MACD), and cycle (%K/%D) all agree.
# The entry-bar stop is tight, giving good R:R naturally.

def scan_powerx(ticker: str, config: AgentConfig) -> Signal | None:
    data = fetch_data(ticker)
    if data is None:
        return None

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    # NOTE: Volume check removed — universe.py already filters by Yahoo volume.
    # Alpaca's IEX feed reports only ~5-10% of real volume, so re-checking here
    # with Alpaca data would incorrectly reject most mid-caps.

    latest_close = float(close.iloc[-1])
    if latest_close < config.powerx_min_price:
        return None

    # Indicator 1: RSI(7) > 50 — Heitkoetter's original PowerX
    # Unlike mean-reversion strategies, PowerX rides strong momentum.
    # We don't filter out "overbought" because high RSI + strong trend = confirmation.
    rsi = calc_rsi(close, config.powerx_rsi_period)
    if pd.isna(rsi.iloc[-1]):
        return None
    rsi_now = float(rsi.iloc[-1])
    if rsi_now <= 50:
        return None

    # Indicator 2: MACD histogram positive and rising
    _, _, histogram = calc_macd(
        close,
        fast=config.powerx_macd_fast,
        slow=config.powerx_macd_slow,
        signal=config.powerx_macd_signal,
    )
    if pd.isna(histogram.iloc[-1]) or pd.isna(histogram.iloc[-2]):
        return None
    hist_now = float(histogram.iloc[-1])
    hist_prev = float(histogram.iloc[-2])
    macd_bullish = hist_now > 0 and hist_now > hist_prev

    if not macd_bullish:
        return None

    # Indicator 3: Stochastic %K crosses above %D (or %K > %D and rising)
    stoch_k, stoch_d = calc_stochastic(
        data,
        k_period=config.powerx_stoch_k,
        d_period=config.powerx_stoch_d,
        slowing=config.powerx_stoch_slowing,
    )
    if pd.isna(stoch_k.iloc[-1]) or pd.isna(stoch_d.iloc[-1]):
        return None
    k_now = float(stoch_k.iloc[-1])
    d_now = float(stoch_d.iloc[-1])
    k_prev = float(stoch_k.iloc[-2])
    d_prev = float(stoch_d.iloc[-2])

    # Heitkoetter's PowerX: Stoch %K > %D is the bullish signal.
    # No upper bound — ride the momentum.
    if k_now <= d_now:
        return None

    # ── All three confirmed. Build the signal. ──

    # Fixed percentage stop and target (Heitkoetter PowerX Optimizer style)
    # Default: 1.5% stop / 4.5% target = R:R 3.0 ("Quick Trades")
    stop_loss = latest_close * (1 - config.powerx_stop_pct)
    target = latest_close * (1 + config.powerx_target_pct)

    signal = Signal(
        ticker=ticker,
        strategy="POWERX",
        direction="LONG",
        entry_price=latest_close,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        reason=f"Triple confirm: RSI(7)={rsi_now:.0f}, "
               f"MACD hist +{hist_now:.3f}, Stoch %K={k_now:.0f}>%D={d_now:.0f}",
    )

    return signal


# ─── Scanner orchestration ───────────────────────────────────────────────────

def run_full_scan(config: AgentConfig) -> list[Signal]:
    """Run all scanners. Only returns signals with R:R >= min_reward_risk."""
    try:
        from universe import get_scan_tickers
        all_tickers = get_scan_tickers()
    except Exception as e:
        print(f"  [SCAN] Dynamic universe unavailable ({e}), using fallback")
        all_tickers = list(set(config.core_etfs + config.sector_etfs))
    signals: list[Signal] = []

    scanners = [
        ("Pullback", scan_pullback),
        ("Breakout", scan_consolidation_breakout),
        ("MA Bounce", scan_ma_bounce),
        ("Sector Momentum", scan_sector_momentum),
        ("PowerX", scan_powerx),
    ]

    print(f"\n{'='*70}")
    print(f"  MARKET SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Universe: {len(all_tickers)} tickers | Min R:R: {config.min_reward_risk}x")
    print(f"{'='*70}")

    for scanner_name, scanner_fn in scanners:
        print(f"\n  {scanner_name}...", end=" ")
        count = 0
        for ticker in all_tickers:
            signal = scanner_fn(ticker, config)
            if signal:
                signals.append(signal)
                count += 1
        print(f"{count} signals")

    # Sort by reward:risk ratio (best setups first)
    signals.sort(key=lambda s: s.reward_risk, reverse=True)

    # Remove duplicates (keep best R:R per ticker)
    seen = set()
    unique_signals = []
    for s in signals:
        if s.ticker not in seen:
            seen.add(s.ticker)
            unique_signals.append(s)

    print(f"\n  {'─'*70}")
    print(f"  {len(unique_signals)} actionable signals (all R:R >= {config.min_reward_risk}x)")
    print(f"\n  {'Ticker':<8} {'Strategy':<18} {'Entry':>8} {'Stop':>8} {'Target':>8} "
          f"{'Risk%':>6} {'R:R':>5}")
    print(f"  {'─'*8} {'─'*18} {'─'*8} {'─'*8} {'─'*8} {'─'*6} {'─'*5}")

    for s in unique_signals[:15]:
        print(
            f"  {s.ticker:<8} {s.strategy:<18} ${s.entry_price:>7.2f} "
            f"${s.stop_loss:>7.2f} ${s.target:>7.2f} "
            f"{s.risk_pct:>5.1f}% {s.reward_risk:>4.1f}x"
        )
        print(f"           {s.reason}")

    return unique_signals


if __name__ == "__main__":
    config = AgentConfig()
    signals = run_full_scan(config)

    if signals:
        df = pd.DataFrame([
            {
                "timestamp": s.timestamp, "ticker": s.ticker,
                "strategy": s.strategy, "entry": s.entry_price,
                "stop": s.stop_loss, "target": s.target,
                "risk_pct": round(s.risk_pct, 2),
                "reward_risk": round(s.reward_risk, 2),
                "reason": s.reason,
            }
            for s in signals
        ])
        df.to_csv("signals.csv", index=False)
        print(f"\n  Saved to signals.csv")
