"""
Dynamic Universe Builder

Instead of scanning a hardcoded list of 24 tickers, this module builds
a tradeable universe of 200-500 liquid stocks by pulling index
constituents and filtering for liquidity.

Sources (all free, no API key needed):
  - S&P 500 constituents (Wikipedia)
  - NASDAQ-100 constituents (Wikipedia)
  - Sector ETFs (hardcoded — they don't change often)

Filters:
  - Average daily volume > 500K shares (liquid enough for small account)
  - Price > $5 (no penny stocks)
  - Data must be available from provider

The universe refreshes weekly and caches locally. Between refreshes,
the cached list is used so scans are fast.
"""

import json
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from data_provider import get_provider

CACHE_FILE = Path(__file__).parent / ".universe_cache.json"
REFRESH_DAYS = 7  # Rebuild universe weekly

# ─── Sector ETFs (these rarely change, keep hardcoded) ────────────────────────

CORE_ETFS = ["SPY", "QQQ", "IWM", "DIA"]

SECTOR_ETFS = [
    "XLK",   # Tech
    "XLF",   # Financials
    "XLE",   # Energy
    "XLV",   # Healthcare
    "XLI",   # Industrials
    "XLC",   # Communications
    "XLY",   # Consumer Discretionary
    "XLP",   # Consumer Staples
    "XLU",   # Utilities
    "XLRE",  # Real Estate
    "XLB",   # Materials
    "SOXX",  # Semiconductors
    "SMH",   # Semiconductors (alt)
]

# ─── Sector classification for correlation guard ──────────────────────────────

# GICS-style sector mapping. When we pull S&P 500 constituents from Wikipedia,
# the table includes each company's GICS sector. We map those to short labels
# that the correlation guard understands.

GICS_TO_SECTOR = {
    "Information Technology": "TECH",
    "Semiconductors & Semiconductor Equipment": "SEMIS",
    "Communication Services": "COMM",
    "Consumer Discretionary": "CONSUMER",
    "Consumer Staples": "STAPLES",
    "Financials": "FINANCIALS",
    "Health Care": "HEALTH",
    "Industrials": "INDUSTRIALS",
    "Energy": "ENERGY",
    "Utilities": "UTILITIES",
    "Real Estate": "REAL_ESTATE",
    "Materials": "MATERIALS",
}


def _fetch_html_tables(url: str) -> list:
    """Fetch HTML tables from a URL with a User-Agent (Wikipedia blocks default requests)."""
    import requests
    from io import StringIO
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def _fetch_sp500() -> list[dict]:
    """
    Pull S&P 500 constituents from Wikipedia.
    Returns list of {ticker, name, sector}.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = _fetch_html_tables(url)
        df = tables[0]
        results = []
        for _, row in df.iterrows():
            ticker = str(row["Symbol"]).replace(".", "-")  # BRK.B → BRK-B (Yahoo format)
            sector = str(row.get("GICS Sector", "Unknown"))
            sub_industry = str(row.get("GICS Sub-Industry", ""))
            # Map semis separately from broader tech
            if "Semiconductor" in sub_industry:
                mapped_sector = "SEMIS"
            else:
                mapped_sector = GICS_TO_SECTOR.get(sector, "UNKNOWN")
            results.append({
                "ticker": ticker,
                "name": str(row.get("Security", "")),
                "sector": mapped_sector,
            })
        return results
    except Exception as e:
        print(f"  [UNIVERSE] Failed to fetch S&P 500: {e}")
        return []


def _fetch_nasdaq100() -> list[dict]:
    """
    Pull NASDAQ-100 constituents from Wikipedia.
    Returns list of {ticker, name, sector}.
    """
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        tables = _fetch_html_tables(url)
        # The constituents table has columns: Company, Ticker, GICS Sector, GICS Sub-Industry
        # Find the right table by looking for one with a "Ticker" column
        df = None
        for table in tables:
            cols = [str(c).lower() for c in table.columns]
            if any("ticker" in c for c in cols):
                df = table
                break
        if df is None:
            return []

        # Normalize column names
        df.columns = [str(c).strip() for c in df.columns]
        ticker_col = [c for c in df.columns if "ticker" in c.lower()][0]
        name_col = [c for c in df.columns if "company" in c.lower()]
        sector_col = [c for c in df.columns if "sector" in c.lower()]

        results = []
        for _, row in df.iterrows():
            ticker = str(row[ticker_col]).replace(".", "-").strip()
            name = str(row[name_col[0]]) if name_col else ""
            sector = str(row[sector_col[0]]) if sector_col else "UNKNOWN"
            sub = str(row.get("GICS Sub-Industry", "")) if "GICS Sub-Industry" in df.columns else ""
            if "Semiconductor" in sub or "Semiconductor" in sector:
                mapped = "SEMIS"
            else:
                mapped = GICS_TO_SECTOR.get(sector, "UNKNOWN")
            results.append({"ticker": ticker, "name": name, "sector": mapped})
        return results
    except Exception as e:
        print(f"  [UNIVERSE] Failed to fetch NASDAQ-100: {e}")
        return []


def _filter_by_liquidity(
    candidates: list[dict],
    min_volume: int = 500_000,
    min_price: float = 5.0,
) -> list[dict]:
    """
    Filter candidates by average daily volume and price.

    Uses Yahoo Finance BULK download for all tickers in one call.
    Alpaca's free IEX feed reports only ~5-10% of real volume, which
    would incorrectly reject most mid-caps. Yahoo has full consolidated volume.
    """
    import yfinance as yf
    tickers = [s["ticker"] for s in candidates]
    total = len(tickers)
    print(f"  [UNIVERSE] Bulk downloading 1mo of data for {total} tickers from Yahoo...")

    passed = []
    # yfinance bulk download — all tickers in one HTTP call
    try:
        data = yf.download(tickers, period="1mo", progress=False, group_by="ticker", threads=True)
    except Exception as e:
        print(f"  [UNIVERSE] Bulk download failed: {e}")
        return passed

    for stock in candidates:
        ticker = stock["ticker"]
        try:
            # yf.download returns MultiIndex columns: (TICKER, field)
            if (ticker, "Volume") not in data.columns:
                continue
            vol_series = data[(ticker, "Volume")].dropna()
            close_series = data[(ticker, "Close")].dropna()
            if len(vol_series) < 5 or len(close_series) < 1:
                continue

            avg_volume = float(vol_series.mean())
            last_price = float(close_series.iloc[-1])

            if avg_volume >= min_volume and last_price >= min_price:
                stock["avg_volume"] = int(avg_volume)
                stock["last_price"] = round(float(last_price), 2)
                passed.append(stock)
        except Exception:
            continue

    return passed


def build_universe(
    min_volume: int = 500_000,
    min_price: float = 5.0,
    force_refresh: bool = False,
) -> dict:
    """
    Build the tradeable universe. Returns dict with:
      - tickers: list of ticker strings
      - sector_map: {ticker: sector} for correlation guard
      - etfs: list of ETF tickers
      - metadata: {ticker: {name, sector, avg_volume, last_price}}
      - built_at: timestamp
      - count: total tickers

    Caches result for REFRESH_DAYS. Pass force_refresh=True to rebuild.
    """
    # Check cache first
    if not force_refresh and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            built_at = datetime.fromisoformat(cached["built_at"])
            if datetime.now() - built_at < timedelta(days=REFRESH_DAYS):
                print(f"  [UNIVERSE] Using cached universe: {cached['count']} tickers "
                      f"(built {built_at.strftime('%Y-%m-%d')})")
                return cached
        except (json.JSONDecodeError, KeyError):
            pass  # Cache corrupted, rebuild

    print(f"\n  [UNIVERSE] Building fresh universe (min vol: {min_volume:,}, min price: ${min_price})")

    # Step 1: Pull index constituents
    print(f"  [UNIVERSE] Fetching S&P 500 constituents...")
    sp500 = _fetch_sp500()
    print(f"  [UNIVERSE]   → {len(sp500)} S&P 500 stocks")

    print(f"  [UNIVERSE] Fetching NASDAQ-100 constituents...")
    ndx100 = _fetch_nasdaq100()
    print(f"  [UNIVERSE]   → {len(ndx100)} NASDAQ-100 stocks")

    # Merge and deduplicate (prefer S&P 500 sector classification)
    seen_tickers = set()
    all_candidates = []
    for stock in sp500 + ndx100:
        if stock["ticker"] not in seen_tickers:
            seen_tickers.add(stock["ticker"])
            all_candidates.append(stock)

    print(f"  [UNIVERSE] {len(all_candidates)} unique candidates after merge")

    # Step 2: Filter by liquidity
    print(f"  [UNIVERSE] Filtering by liquidity...")
    liquid = _filter_by_liquidity(all_candidates, min_volume, min_price)
    print(f"  [UNIVERSE]   → {len(liquid)} passed liquidity filter")

    # Sort by volume (most liquid first)
    liquid.sort(key=lambda s: s.get("avg_volume", 0), reverse=True)

    # Step 3: Build the result
    tickers = [s["ticker"] for s in liquid]
    sector_map = {s["ticker"]: s["sector"] for s in liquid}
    metadata = {
        s["ticker"]: {
            "name": s.get("name", ""),
            "sector": s["sector"],
            "avg_volume": s.get("avg_volume", 0),
            "last_price": s.get("last_price", 0),
        }
        for s in liquid
    }

    result = {
        "tickers": tickers,
        "sector_map": sector_map,
        "etfs": CORE_ETFS + SECTOR_ETFS,
        "metadata": metadata,
        "built_at": datetime.now().isoformat(),
        "count": len(tickers) + len(CORE_ETFS) + len(SECTOR_ETFS),
    }

    # Cache it
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  [UNIVERSE] Universe built: {result['count']} total tickers "
          f"({len(tickers)} stocks + {len(CORE_ETFS) + len(SECTOR_ETFS)} ETFs)")

    # Print sector breakdown
    sector_counts: dict[str, int] = {}
    for sector in sector_map.values():
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    print(f"\n  Sector breakdown:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"    {sector:<15} {count:>4} stocks")

    return result


def _load_watchlist() -> list[str]:
    """Load extra tickers from watchlist.json — always scanned regardless of liquidity."""
    watchlist_file = Path(__file__).parent / "watchlist.json"
    if not watchlist_file.exists():
        return []
    try:
        data = json.loads(watchlist_file.read_text())
        return list(data.get("tickers", []))
    except Exception:
        return []


def get_scan_tickers() -> list[str]:
    """
    Get the full list of tickers to scan. This is what scanner.py calls.
    Returns stocks + ETFs + manual watchlist (deduplicated).
    """
    universe = build_universe()
    watchlist = _load_watchlist()
    return list(set(universe["tickers"] + universe["etfs"] + watchlist))


def get_sector_map() -> dict[str, str]:
    """
    Get the ticker → sector mapping for the full universe.
    Used by correlation_guard.py for sector classification.
    """
    universe = build_universe()

    # Start with the dynamic map
    sector_map = dict(universe["sector_map"])

    # Add ETF classifications
    etf_sectors = {
        "SPY": "BROAD_ETF", "QQQ": "TECH_ETF", "IWM": "BROAD_ETF", "DIA": "BROAD_ETF",
        "XLK": "TECH_ETF", "XLF": "FINANCIALS", "XLE": "ENERGY", "XLV": "HEALTH",
        "XLI": "INDUSTRIALS", "XLC": "COMM", "XLY": "CONSUMER", "XLP": "STAPLES",
        "XLU": "UTILITIES", "XLRE": "REAL_ESTATE", "XLB": "MATERIALS",
        "SOXX": "SEMI_ETF", "SMH": "SEMI_ETF",
    }
    sector_map.update(etf_sectors)
    return sector_map


# ─── Fallback universe (if network unavailable) ──────────────────────────────

FALLBACK_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "JNJ", "V", "UNH", "MA", "PG", "XOM", "HD", "CVX", "MRK",
    "ABBV", "PEP", "KO", "COST", "AVGO", "TMO", "MCD", "WMT", "CSCO",
    "ACN", "LIN", "CRM", "AMD", "ADBE", "NFLX", "TXN", "INTC", "QCOM",
    "AMAT", "LRCX", "AMGN", "HON", "LOW", "UPS", "BA", "CAT", "GS",
    "BLK", "DE", "ISRG", "MDLZ", "ADP",
]


if __name__ == "__main__":
    print("Building tradeable universe...\n")
    result = build_universe(force_refresh=True)
    print(f"\nTotal: {result['count']} tickers ready to scan")
    print(f"\nTop 20 by volume:")
    for ticker in result["tickers"][:20]:
        meta = result["metadata"][ticker]
        print(f"  {ticker:<6} {meta['name']:<30} {meta['sector']:<15} "
              f"vol: {meta['avg_volume']:>12,}  ${meta['last_price']:>8.2f}")
