"""
Data Provider — Unified market data layer

Abstracts data fetching so the rest of the system doesn't care where
data comes from. Supports multiple backends:

  1. Yahoo Finance (free, no key, delayed) — default
  2. Alpaca Markets (free tier, real-time with API key)
  3. CSV cache (offline backtesting, avoids re-downloading)

The system automatically uses the best available source:
  - Has ALPACA_API_KEY? → Alpaca (real-time, accurate)
  - No key? → Yahoo Finance (delayed but free)
  - Already cached? → Local CSV (fastest, offline)

Usage:
    from data_provider import get_provider
    provider = get_provider()
    data = provider.get_bars("QQQ", period="1y")
    price = provider.get_latest_price("AAPL")
    bulk = provider.get_bulk_prices(["QQQ", "AAPL", "MSFT"])
"""

import os
import hashlib
import pandas as pd
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR = Path(__file__).parent / ".data_cache"


# ─── Abstract Base ──────────────────────────────────────────────────────────

class DataProvider(ABC):
    """Base class for market data providers."""

    name: str = "base"

    @abstractmethod
    def get_bars(
        self,
        ticker: str,
        start: str | None = None,
        end: str | None = None,
        period: str = "1y",
    ) -> pd.DataFrame:
        """Get OHLCV bars. Returns DataFrame with Open, High, Low, Close, Volume columns."""
        ...

    @abstractmethod
    def get_latest_price(self, ticker: str) -> float | None:
        """Get the most recent price for a ticker."""
        ...

    def get_bulk_prices(self, tickers: list[str]) -> dict[str, float]:
        """Get latest prices for multiple tickers."""
        prices = {}
        for t in tickers:
            price = self.get_latest_price(t)
            if price is not None:
                prices[t] = price
        return prices

    def get_returns(
        self,
        tickers: list[str],
        start: str | None = None,
        end: str | None = None,
        period: str = "1y",
    ) -> pd.DataFrame:
        """Get daily returns for multiple tickers."""
        frames = {}
        for t in tickers:
            bars = self.get_bars(t, start=start, end=end, period=period)
            if bars is not None and not bars.empty:
                frames[t] = bars["Close"]

        if not frames:
            return pd.DataFrame()

        prices = pd.DataFrame(frames)
        returns = prices.pct_change().dropna()
        return returns


# ─── Yahoo Finance Provider ─────────────────────────────────────────────────

class YahooProvider(DataProvider):
    """Free data from Yahoo Finance. No API key required.

    Limitations:
    - 15-20 min delayed during market hours
    - Rate limited on heavy use
    - End-of-day bars only (no intraday)
    - Yahoo can change/break their API at any time
    """

    name = "yahoo"

    def __init__(self):
        import yfinance  # noqa: F401  — verify it's installed
        self._yf = yfinance

    def get_bars(self, ticker, start=None, end=None, period="1y"):
        kwargs = {"progress": False}
        if start and end:
            kwargs["start"] = start
            kwargs["end"] = end
        else:
            kwargs["period"] = period

        data = self._yf.download(ticker, **kwargs)
        if isinstance(data.columns, pd.MultiIndex):
            data = data.droplevel("Ticker", axis=1)
        data = data.dropna()
        return data

    def get_latest_price(self, ticker):
        try:
            data = self.get_bars(ticker, period="5d")
            if data.empty:
                return None
            return float(data["Close"].iloc[-1])
        except Exception:
            return None

    def get_bulk_prices(self, tickers):
        """Optimized bulk download for Yahoo."""
        try:
            data = self._yf.download(tickers, period="5d", progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"]
            else:
                close = data[["Close"]]
                close.columns = tickers

            prices = {}
            for t in tickers:
                if t in close.columns:
                    val = close[t].dropna()
                    if not val.empty:
                        prices[t] = float(val.iloc[-1])
            return prices
        except Exception:
            return super().get_bulk_prices(tickers)


# ─── Alpaca Provider ─────────────────────────────────────────────────────────

class AlpacaProvider(DataProvider):
    """Real-time data from Alpaca Markets (free tier available).

    Setup:
    1. Sign up at https://alpaca.markets (free paper trading account)
    2. Get API keys from the dashboard
    3. Set environment variables:
       export ALPACA_API_KEY="your-key"
       export ALPACA_API_SECRET="your-secret"

    Benefits over Yahoo:
    - Real-time prices (no 15min delay)
    - Reliable API with SLA
    - Same API for data AND execution
    - Minute-level bars available
    - Consistent, well-documented
    """

    name = "alpaca"

    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        import alpaca_trade_api as tradeapi
        base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self._api = tradeapi.REST(api_key, api_secret, base_url, api_version="v2")

    def get_bars(self, ticker, start=None, end=None, period="1y"):
        if not start:
            days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
            delta = days.get(period, 365)
            start = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
        if not end:
            # Default end to yesterday — Alpaca free tier SIP data excludes today
            end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            # feed='iex' uses IEX exchange data (free tier, no delay restriction).
            # SIP feed requires a paid subscription for recent data.
            bars = self._api.get_bars(ticker, "1Day", start=start, end=end, feed="iex").df
            if bars.empty:
                return pd.DataFrame()
            bars = bars.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            return bars[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            # Log specific error so we know what failed (fixes CONCERNS.md silent failure)
            print(f"  [AlpacaProvider] get_bars({ticker}) failed: {type(e).__name__}: {e}")
            return pd.DataFrame()

    def get_latest_price(self, ticker):
        try:
            trade = self._api.get_latest_trade(ticker)
            return float(trade.price)
        except Exception as e:
            print(f"  [AlpacaProvider] get_latest_price({ticker}) failed: {type(e).__name__}: {e}")
            return None

    def get_bulk_prices(self, tickers):
        prices = {}
        try:
            snapshots = self._api.get_snapshots(tickers)
            for ticker, snap in snapshots.items():
                if snap and snap.latest_trade:
                    prices[ticker] = float(snap.latest_trade.price)
        except Exception as e:
            print(f"  [AlpacaProvider] get_snapshots failed: {type(e).__name__}: {e}")
            prices = super().get_bulk_prices(tickers)
        return prices


# ─── Cached Provider (wraps another provider) ───────────────────────────────

class CachedProvider(DataProvider):
    """Wraps another provider with local CSV caching.

    - Historical bars are cached to avoid re-downloading
    - Cache expires after `max_age_hours` for recent data
    - Backtesting data is cached indefinitely (end date in the past)
    """

    name = "cached"

    def __init__(self, inner: DataProvider, max_age_hours: int = 4):
        self._inner = inner
        self._max_age = timedelta(hours=max_age_hours)
        CACHE_DIR.mkdir(exist_ok=True)

    def _cache_key(self, ticker: str, start: str | None, end: str | None, period: str) -> Path:
        raw = f"{ticker}_{start}_{end}_{period}"
        h = hashlib.md5(raw.encode()).hexdigest()[:12]
        return CACHE_DIR / f"{ticker}_{h}.csv"

    def _is_fresh(self, path: Path, end: str | None) -> bool:
        if not path.exists():
            return False
        # If end date is in the past, cache forever (backtest data)
        if end:
            try:
                end_dt = datetime.strptime(end, "%Y-%m-%d")
                if end_dt < datetime.now() - timedelta(days=1):
                    return True  # Historical data doesn't change
            except ValueError:
                pass
        # Otherwise check age
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < self._max_age

    def get_bars(self, ticker, start=None, end=None, period="1y"):
        cache_path = self._cache_key(ticker, start, end, period)

        if self._is_fresh(cache_path, end):
            try:
                data = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                if not data.empty:
                    return data
            except Exception:
                pass

        # Fetch from inner provider
        data = self._inner.get_bars(ticker, start=start, end=end, period=period)
        if not data.empty:
            data.to_csv(cache_path)
        return data

    def get_latest_price(self, ticker):
        return self._inner.get_latest_price(ticker)

    def get_bulk_prices(self, tickers):
        return self._inner.get_bulk_prices(tickers)


# ─── Provider Factory ───────────────────────────────────────────────────────

def get_provider(use_cache: bool = True) -> DataProvider:
    """Get the best available data provider.

    Priority:
    1. Alpaca (if ALPACA_API_KEY is set) — real-time, reliable
    2. Yahoo Finance (free fallback) — delayed but works

    Both are wrapped with caching by default.
    """
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")

    if api_key and api_secret:
        try:
            provider = AlpacaProvider(api_key, api_secret)
            print(f"  Data source: Alpaca Markets (real-time)")
        except Exception:
            provider = YahooProvider()
            print(f"  Data source: Yahoo Finance (Alpaca failed, falling back)")
    else:
        provider = YahooProvider()
        print(f"  Data source: Yahoo Finance (free, ~15min delayed)")

    if use_cache:
        provider = CachedProvider(provider)

    return provider


# ─── Convenience functions ──────────────────────────────────────────────────

_default_provider: DataProvider | None = None


def _get_default() -> DataProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = get_provider()
    return _default_provider


def get_bars(ticker: str, **kwargs) -> pd.DataFrame:
    """Quick access: get_bars("QQQ", period="1y")"""
    return _get_default().get_bars(ticker, **kwargs)


def get_price(ticker: str) -> float | None:
    """Quick access: get_price("AAPL") → 195.32"""
    return _get_default().get_latest_price(ticker)


def get_prices(tickers: list[str]) -> dict[str, float]:
    """Quick access: get_prices(["QQQ", "SPY"]) → {"QQQ": 480.5, "SPY": 520.1}"""
    return _get_default().get_bulk_prices(tickers)


if __name__ == "__main__":
    provider = get_provider()

    print(f"\n  Provider: {provider.name}")
    print(f"  Cache dir: {CACHE_DIR}")

    # Test with a few tickers
    test_tickers = ["QQQ", "SPY", "AAPL"]

    print(f"\n  Latest prices:")
    prices = provider.get_bulk_prices(test_tickers)
    for t, p in prices.items():
        print(f"    {t}: ${p:.2f}")

    print(f"\n  QQQ daily bars (last 5):")
    bars = provider.get_bars("QQQ", period="1mo")
    if not bars.empty:
        print(bars.tail().to_string())

    print(f"\n  QQQ daily returns (last 5):")
    returns = provider.get_returns(test_tickers, period="3mo")
    if not returns.empty:
        print(returns.tail().to_string())
