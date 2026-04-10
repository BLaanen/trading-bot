"""
Momentum Crossover Backtesting Strategy

Tests a 10/50 EMA crossover strategy on ETFs and stocks.
Run: pip install backtesting yfinance pandas && python backtest_momentum.py
"""

import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA


class MomentumCrossover(Strategy):
    """10/50 Moving Average Crossover with trailing stop-loss."""

    fast_period = 10
    slow_period = 50
    stop_loss_pct = 0.08  # 8% trailing stop

    def init(self):
        close = self.data.Close
        self.fast_ma = self.I(SMA, close, self.fast_period)
        self.slow_ma = self.I(SMA, close, self.slow_period)

    def next(self):
        if crossover(self.fast_ma, self.slow_ma):
            sl_price = self.data.Close[-1] * (1 - self.stop_loss_pct)
            self.buy(sl=sl_price)
        elif crossover(self.slow_ma, self.fast_ma):
            if self.position:
                self.position.close()


class RSIMomentum(Strategy):
    """RSI + MA trend filter strategy for mean reversion entries."""

    rsi_period = 14
    sma_period = 200
    rsi_oversold = 30
    rsi_exit = 60
    profit_target_pct = 0.05  # 5% profit target

    def init(self):
        close = self.data.Close
        self.sma = self.I(SMA, close, self.sma_period)

        # Calculate RSI manually
        def calc_rsi(close, period):
            delta = pd.Series(close).diff()
            gain = delta.where(delta > 0, 0).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))

        self.rsi = self.I(calc_rsi, close, self.rsi_period)

    def next(self):
        # Entry: RSI oversold + price above long-term trend
        if (
            not self.position
            and self.rsi[-1] < self.rsi_oversold
            and self.data.Close[-1] > self.sma[-1]
        ):
            sl_price = self.data.Close[-1] * 0.95  # 5% stop
            tp_price = self.data.Close[-1] * (1 + self.profit_target_pct)
            self.buy(sl=sl_price, tp=tp_price)

        # Exit: RSI recovered
        elif self.position and self.rsi[-1] > self.rsi_exit:
            self.position.close()


def download_data(ticker: str, start: str = "2023-01-01", end: str = "2026-03-31"):
    """Download and clean OHLCV data from Yahoo Finance."""
    data = yf.download(ticker, start=start, end=end, progress=False)
    # Handle multi-level columns from yfinance
    if isinstance(data.columns, pd.MultiIndex):
        data = data.droplevel("Ticker", axis=1)
    data = data.dropna()
    return data


def run_backtest(ticker: str, strategy_class, cash: int = 10000, **kwargs):
    """Run a backtest and print results."""
    print(f"\n{'='*60}")
    print(f"  {strategy_class.__name__} on {ticker}")
    print(f"{'='*60}")

    data = download_data(ticker)
    if data.empty:
        print(f"  No data available for {ticker}")
        return None

    bt = Backtest(data, strategy_class, cash=cash, commission=0.001, **kwargs)
    stats = bt.run()

    print(f"  Start:            {stats['Start']}")
    print(f"  End:              {stats['End']}")
    print(f"  Duration:         {stats['Duration']}")
    print(f"  Return:           {stats['Return [%]']:.2f}%")
    print(f"  Buy & Hold:       {stats['Buy & Hold Return [%]']:.2f}%")
    print(f"  Max Drawdown:     {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  # Trades:         {stats['# Trades']}")
    print(f"  Win Rate:         {stats['Win Rate [%]']:.1f}%")
    print(f"  Sharpe Ratio:     {stats['Sharpe Ratio']:.3f}" if stats['Sharpe Ratio'] else "  Sharpe Ratio:     N/A")
    print(f"  Final Equity:     ${stats['Equity Final [$]']:,.2f}")

    return stats


if __name__ == "__main__":
    # Test both strategies on core ETFs
    tickers = ["QQQ", "SOXX", "XLK", "SMH"]

    print("\n" + "=" * 60)
    print("  MOMENTUM CROSSOVER STRATEGY BACKTEST")
    print("=" * 60)

    for ticker in tickers:
        run_backtest(ticker, MomentumCrossover)

    print("\n" + "=" * 60)
    print("  RSI MEAN REVERSION STRATEGY BACKTEST")
    print("=" * 60)

    for ticker in tickers:
        run_backtest(ticker, RSIMomentum)

    print("\n\nDone. Review results above to validate strategies before live trading.")
