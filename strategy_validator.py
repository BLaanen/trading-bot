"""
Strategy Validator Agent

Backtests strategies with the asymmetric R:R model before live deployment.
Validates that a strategy can:
  - Win at least ~40-50% of trades
  - Average winners are >= 2x average losers
  - Expectancy per trade is positive
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from backtesting import Backtest, Strategy
from backtesting.test import SMA

from config import AgentConfig
from data_provider import get_provider


@dataclass
class ValidationResult:
    strategy_name: str
    ticker: str
    passed: bool
    total_return: float
    buy_hold_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    avg_win_r: float       # Average winner in R multiples
    avg_loss_r: float      # Average loser in R multiples
    expectancy_r: float    # Expected R per trade
    reason: str


# ─── Backtesting helper ─────────────────────────────────────────────────────

def calc_rsi_series(close, period):
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_atr_series(high, low, close, period=14):
    tr1 = pd.Series(high) - pd.Series(low)
    tr2 = abs(pd.Series(high) - pd.Series(close).shift(1))
    tr3 = abs(pd.Series(low) - pd.Series(close).shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


# ─── Strategy: Pullback ─────────────────────────────────────────────────────

class PullbackStrategy(Strategy):
    ema_period = 21
    trend_ema = 50
    rsi_period = 14
    atr_stop_mult = 1.5
    reward_risk = 2.0

    def init(self):
        self.ema = self.I(lambda c: pd.Series(c).ewm(span=self.ema_period).mean(), self.data.Close)
        self.ema_trend = self.I(lambda c: pd.Series(c).ewm(span=self.trend_ema).mean(), self.data.Close)
        self.rsi = self.I(calc_rsi_series, self.data.Close, self.rsi_period)
        self.atr = self.I(calc_atr_series, self.data.High, self.data.Low, self.data.Close)

    def next(self):
        if not self.position:
            price = self.data.Close[-1]
            atr = self.atr[-1]
            if pd.isna(atr) or atr <= 0:
                return

            near_ema = price <= self.ema[-1] + atr * 0.5
            rsi_dip = 35 <= self.rsi[-1] <= 55
            trend_up = price > self.ema_trend[-1]

            if near_ema and rsi_dip and trend_up:
                stop = price - atr * self.atr_stop_mult
                risk = price - stop
                target = price + risk * self.reward_risk
                self.buy(sl=stop, tp=target)


# ─── Strategy: Breakout from consolidation ───────────────────────────────────

class BreakoutStrategy(Strategy):
    lookback = 10
    trend_ema = 50
    atr_buffer = 0.2
    reward_risk = 2.0

    def init(self):
        self.ema = self.I(lambda c: pd.Series(c).ewm(span=self.trend_ema).mean(), self.data.Close)
        self.atr = self.I(calc_atr_series, self.data.High, self.data.Low, self.data.Close)

    def next(self):
        if self.position:
            return
        if len(self.data) < self.lookback + 2:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        if pd.isna(atr) or atr <= 0:
            return

        # Trend filter
        if price <= self.ema[-1]:
            return

        # Check consolidation range (excluding today)
        range_high = max(self.data.High[-self.lookback - 1:-1])
        range_low = min(self.data.Low[-self.lookback - 1:-1])
        range_pct = (range_high - range_low) / range_low if range_low > 0 else 1

        # Must be tight range and breaking out
        if range_pct > 0.06 or price <= range_high:
            return

        # Volume confirmation
        avg_vol = pd.Series(self.data.Volume[-20:]).mean()
        if avg_vol <= 0 or self.data.Volume[-1] < avg_vol * 1.5:
            return

        stop = range_low - atr * self.atr_buffer
        risk = price - stop
        if risk <= 0:
            return
        target = price + risk * self.reward_risk
        self.buy(sl=stop, tp=target)


# ─── Strategy: MA Bounce ─────────────────────────────────────────────────────

class MABounceStrategy(Strategy):
    ema50_period = 50
    sma200_period = 200
    rsi_period = 14
    reward_risk = 2.0

    def init(self):
        self.ema50 = self.I(lambda c: pd.Series(c).ewm(span=self.ema50_period).mean(), self.data.Close)
        self.sma200 = self.I(SMA, self.data.Close, self.sma200_period)
        self.rsi = self.I(calc_rsi_series, self.data.Close, self.rsi_period)
        self.atr = self.I(calc_atr_series, self.data.High, self.data.Low, self.data.Close)

    def next(self):
        if self.position:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        if pd.isna(self.sma200[-1]) or pd.isna(atr) or atr <= 0:
            return

        # 50 EMA > 200 SMA (uptrend)
        if self.ema50[-1] <= self.sma200[-1]:
            return

        # Price near 50 EMA (within 1 ATR) and above it
        distance = abs(price - self.ema50[-1])
        if distance > atr or price < self.ema50[-1]:
            return

        # RSI in recovery zone
        if self.rsi[-1] < 40 or self.rsi[-1] > 65:
            return

        stop = self.ema50[-1] - atr * 0.5
        risk = price - stop
        if risk <= 0:
            return
        target = price + risk * self.reward_risk
        self.buy(sl=stop, tp=target)


# ─── Strategy: PowerX Triple Confirmation ────────────────────────────────────

def calc_stoch_k(high, low, close, period=14, slowing=3):
    h = pd.Series(high)
    l = pd.Series(low)
    c = pd.Series(close)
    lowest = l.rolling(period).min()
    highest = h.rolling(period).max()
    fast_k = 100 * (c - lowest) / (highest - lowest)
    return fast_k.rolling(slowing).mean()


def calc_stoch_d(high, low, close, period=14, slowing=3, d_period=3):
    k = calc_stoch_k(high, low, close, period, slowing)
    return k.rolling(d_period).mean()


def calc_macd_hist(close, fast=12, slow=26, signal=9):
    c = pd.Series(close)
    macd_line = c.ewm(span=fast).mean() - c.ewm(span=slow).mean()
    signal_line = macd_line.ewm(span=signal).mean()
    return macd_line - signal_line


class PowerXStrategy(Strategy):
    """Triple confirmation: RSI(7) > 50, MACD hist > 0, Stoch %K > %D."""
    rsi_period = 7
    reward_risk = 2.0

    def init(self):
        self.rsi = self.I(calc_rsi_series, self.data.Close, self.rsi_period)
        self.macd_hist = self.I(calc_macd_hist, self.data.Close)
        self.stoch_k = self.I(calc_stoch_k, self.data.High, self.data.Low, self.data.Close)
        self.stoch_d = self.I(calc_stoch_d, self.data.High, self.data.Low, self.data.Close)
        self.atr = self.I(calc_atr_series, self.data.High, self.data.Low, self.data.Close)

    def next(self):
        if self.position:
            return

        price = self.data.Close[-1]
        atr = self.atr[-1]
        if pd.isna(atr) or atr <= 0 or pd.isna(self.stoch_k[-1]):
            return

        # Triple confirmation
        rsi_bull = self.rsi[-1] > 50
        macd_bull = self.macd_hist[-1] > 0 and self.macd_hist[-1] > self.macd_hist[-2]
        stoch_bull = self.stoch_k[-1] > self.stoch_d[-1]

        if not (rsi_bull and macd_bull and stoch_bull):
            return

        # Stop: low of entry bar
        stop = self.data.Low[-1] - atr * 0.1
        risk = price - stop
        if risk <= 0 or risk / price > 0.05:
            return

        target = price + risk * self.reward_risk
        self.buy(sl=stop, tp=target)


# ─── Mapping ─────────────────────────────────────────────────────────────────

STRATEGIES = {
    "PULLBACK": PullbackStrategy,
    "BREAKOUT": BreakoutStrategy,
    "MA_BOUNCE": MABounceStrategy,
    "POWERX": PowerXStrategy,
    # SECTOR_MOMENTUM uses the same logic as PULLBACK for validation
    "SECTOR_MOMENTUM": PullbackStrategy,
}


# ─── Validation ──────────────────────────────────────────────────────────────

def validate_strategy(
    strategy_name: str,
    ticker: str,
    config: AgentConfig,
) -> ValidationResult:
    strategy_class = STRATEGIES.get(strategy_name)
    if not strategy_class:
        return ValidationResult(
            strategy_name=strategy_name, ticker=ticker, passed=False,
            total_return=0, buy_hold_return=0, sharpe_ratio=0,
            max_drawdown=0, win_rate=0, num_trades=0,
            avg_win_r=0, avg_loss_r=0, expectancy_r=0,
            reason=f"Unknown strategy: {strategy_name}",
        )

    provider = get_provider()
    data = provider.get_bars(ticker, start=config.backtest_start, end=config.backtest_end)
    if data.empty or len(data) < 200:
        return ValidationResult(
            strategy_name=strategy_name, ticker=ticker, passed=False,
            total_return=0, buy_hold_return=0, sharpe_ratio=0,
            max_drawdown=0, win_rate=0, num_trades=0,
            avg_win_r=0, avg_loss_r=0, expectancy_r=0,
            reason=f"Insufficient data for {ticker}",
        )

    bt = Backtest(data, strategy_class, cash=10000, commission=0.001)
    stats = bt.run()

    total_return = stats["Return [%]"]
    buy_hold = stats["Buy & Hold Return [%]"]
    sharpe = stats["Sharpe Ratio"] or 0
    max_dd = abs(stats["Max. Drawdown [%]"])
    win_rate = stats["Win Rate [%]"] or 0
    num_trades = stats["# Trades"]

    # Calculate R-based metrics from trade results
    trades_df = stats._trades if hasattr(stats, '_trades') else None
    avg_win_r = 0
    avg_loss_r = 0
    expectancy_r = 0

    if trades_df is not None and len(trades_df) > 0:
        returns_pct = trades_df["ReturnPct"] if "ReturnPct" in trades_df.columns else pd.Series()
        if not returns_pct.empty:
            winners = returns_pct[returns_pct > 0]
            losers = returns_pct[returns_pct < 0]
            avg_win = float(winners.mean()) if len(winners) > 0 else 0
            avg_loss = float(abs(losers.mean())) if len(losers) > 0 else 1
            avg_win_r = avg_win / avg_loss if avg_loss > 0 else avg_win
            avg_loss_r = 1.0  # By definition
            wr = len(winners) / len(returns_pct)
            expectancy_r = wr * avg_win_r - (1 - wr) * avg_loss_r

    # Validation criteria
    failures = []
    if num_trades < config.min_trades:
        failures.append(f"{num_trades} trades < {config.min_trades} min")
    if win_rate < config.min_win_rate * 100:
        failures.append(f"WR {win_rate:.0f}% < {config.min_win_rate*100:.0f}%")
    if sharpe < config.min_sharpe:
        failures.append(f"Sharpe {sharpe:.2f} < {config.min_sharpe}")
    if avg_win_r > 0 and avg_win_r < config.min_avg_rr:
        failures.append(f"Avg W:L {avg_win_r:.1f}x < {config.min_avg_rr}x")
    if expectancy_r < 0:
        failures.append(f"Negative expectancy ({expectancy_r:.2f}R)")
    if max_dd > 30:
        failures.append(f"Drawdown {max_dd:.0f}% > 30%")

    passed = len(failures) == 0
    reason = "PASSED" if passed else f"FAILED: {'; '.join(failures)}"

    return ValidationResult(
        strategy_name=strategy_name, ticker=ticker, passed=passed,
        total_return=total_return, buy_hold_return=buy_hold,
        sharpe_ratio=sharpe, max_drawdown=max_dd, win_rate=win_rate,
        num_trades=num_trades, avg_win_r=avg_win_r, avg_loss_r=avg_loss_r,
        expectancy_r=expectancy_r, reason=reason,
    )


def validate_all(config: AgentConfig) -> list[ValidationResult]:
    results = []
    try:
        from universe import get_scan_tickers
        all_tickers = get_scan_tickers()
        # Validate on a broader sample to improve chance of finding strategy edge.
        # Note: filter is strategy-level (not ticker-level), so we just need ANY ticker
        # per strategy to pass for the strategy to be trusted on new signals.
        test_tickers = all_tickers[:25]
    except Exception:
        test_tickers = config.core_etfs[:4] + config.sector_etfs[:6]

    print(f"\n{'='*75}")
    print(f"  STRATEGY VALIDATION — Asymmetric R:R Model")
    print(f"  Period: {config.backtest_start} → {config.backtest_end}")
    print(f"  Min: WR >= {config.min_win_rate*100:.0f}%, Avg R:R >= {config.min_avg_rr}x, "
          f"Sharpe >= {config.min_sharpe}, Trades >= {config.min_trades}")
    print(f"{'='*75}")

    for strategy_name in STRATEGIES:
        print(f"\n  --- {strategy_name} ---")
        for ticker in test_tickers:
            result = validate_strategy(strategy_name, ticker, config)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(
                f"  [{status}] {ticker:<6} "
                f"Ret={result.total_return:>+6.1f}% "
                f"WR={result.win_rate:>4.0f}% "
                f"W:L={result.avg_win_r:>4.1f}x "
                f"Exp={result.expectancy_r:>+5.2f}R "
                f"Sharpe={result.sharpe_ratio:>5.2f} "
                f"DD={result.max_drawdown:>4.0f}% "
                f"N={result.num_trades:>3}"
            )
            if not result.passed:
                print(f"          {result.reason}")

    passed = [r for r in results if r.passed]
    print(f"\n{'='*75}")
    print(f"  {len(passed)}/{len(results)} passed")

    if passed:
        best = sorted(passed, key=lambda r: r.expectancy_r, reverse=True)[:5]
        print(f"\n  Top 5 by expectancy:")
        for r in best:
            print(f"    {r.strategy_name:<18} {r.ticker:<6} "
                  f"Exp={r.expectancy_r:+.2f}R  WR={r.win_rate:.0f}%  "
                  f"W:L={r.avg_win_r:.1f}x")

    return results


if __name__ == "__main__":
    config = AgentConfig()
    validate_all(config)
