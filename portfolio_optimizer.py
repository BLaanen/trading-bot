"""
Portfolio Optimizer using Riskfolio-Lib

Calculates optimal ETF portfolio weights using Modern Portfolio Theory.
Run: pip install riskfolio-lib yfinance pandas matplotlib && python portfolio_optimizer.py
"""

import pandas as pd

from data_provider import get_provider

try:
    import riskfolio as rp
    HAS_RISKFOLIO = True
except ImportError:
    HAS_RISKFOLIO = False


# Core ETF universe from the trading plan
CORE_ETFS = {
    "QQQ": "Nasdaq 100",
    "SOXX": "Semiconductors",
    "XLK": "Technology Select",
    "SMH": "VanEck Semiconductor",
    "ARKK": "ARK Innovation",
    "SPY": "S&P 500",
    "IWM": "Russell 2000",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
}

AGGRESSIVE_ETFS = {
    "QQQ": "Nasdaq 100",
    "TQQQ": "3x Leveraged Nasdaq",
    "SOXX": "Semiconductors",
    "XLK": "Technology Select",
    "SMH": "VanEck Semiconductor",
    "ARKK": "ARK Innovation",
}


def download_returns(tickers: list[str], start: str = "2023-01-01", end: str = "2026-03-31"):
    """Download price data and calculate daily returns via unified provider."""
    provider = get_provider()
    return provider.get_returns(tickers, start=start, end=end)


def optimize_portfolio(returns: pd.DataFrame, objective: str = "Sharpe"):
    """
    Optimize portfolio weights.

    objective: "Sharpe" (max risk-adjusted return) or "MinRisk" (minimum variance)
    """
    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu="hist", method_cov="hist")

    weights = port.optimization(model="Classic", rm="MV", obj=objective)
    return weights


def equal_weight_portfolio(tickers: list[str]):
    """Simple equal-weight allocation as a baseline."""
    weight = 1.0 / len(tickers)
    return {t: weight for t in tickers}


def display_allocation(weights, labels: dict, total_capital: float):
    """Display portfolio allocation with dollar amounts."""
    print(f"\n  {'Ticker':<8} {'Name':<25} {'Weight':>8} {'Amount':>10}")
    print(f"  {'-'*8} {'-'*25} {'-'*8} {'-'*10}")

    if isinstance(weights, pd.DataFrame):
        for ticker in weights.index:
            w = weights.loc[ticker].values[0]
            if w > 0.001:  # Only show meaningful allocations
                name = labels.get(ticker, ticker)
                amount = w * total_capital
                print(f"  {ticker:<8} {name:<25} {w:>7.1%} ${amount:>9,.0f}")
    elif isinstance(weights, dict):
        for ticker, w in weights.items():
            name = labels.get(ticker, ticker)
            amount = w * total_capital
            print(f"  {ticker:<8} {name:<25} {w:>7.1%} ${amount:>9,.0f}")


def simple_optimization(tickers: list[str], labels: dict, capital: float):
    """Fallback optimization without riskfolio-lib using basic stats."""
    returns = download_returns(tickers)

    # Calculate annualized metrics
    annual_returns = returns.mean() * 252
    annual_vol = returns.std() * (252 ** 0.5)
    sharpe = annual_returns / annual_vol

    print("\n  Asset Performance Summary:")
    print(f"  {'Ticker':<8} {'Ann. Return':>12} {'Ann. Vol':>10} {'Sharpe':>8}")
    print(f"  {'-'*8} {'-'*12} {'-'*10} {'-'*8}")

    for ticker in tickers:
        if ticker in annual_returns.index:
            print(f"  {ticker:<8} {annual_returns[ticker]:>11.1%} {annual_vol[ticker]:>9.1%} {sharpe[ticker]:>7.2f}")

    # Simple inverse-volatility weighting
    inv_vol = 1 / annual_vol
    inv_vol_weights = inv_vol / inv_vol.sum()

    print("\n  Inverse-Volatility Weights:")
    weights_dict = {t: inv_vol_weights[t] for t in tickers if t in inv_vol_weights.index}
    display_allocation(weights_dict, labels, capital)

    return weights_dict


if __name__ == "__main__":
    capital = 6000  # Phase 1 core ETF allocation

    print("=" * 60)
    print("  PORTFOLIO OPTIMIZER")
    print(f"  Capital: ${capital:,.0f}")
    print("=" * 60)

    tickers = list(AGGRESSIVE_ETFS.keys())

    if HAS_RISKFOLIO:
        print("\n--- Maximum Sharpe Ratio Portfolio ---")
        returns = download_returns(tickers)
        weights_sharpe = optimize_portfolio(returns, "Sharpe")
        display_allocation(weights_sharpe, AGGRESSIVE_ETFS, capital)

        print("\n--- Minimum Variance Portfolio ---")
        weights_minvar = optimize_portfolio(returns, "MinRisk")
        display_allocation(weights_minvar, AGGRESSIVE_ETFS, capital)
    else:
        print("\n  riskfolio-lib not installed. Using simple optimization.")
        print("  Install with: pip install riskfolio-lib")

    print("\n--- Simple Inverse-Volatility Portfolio ---")
    simple_optimization(tickers, AGGRESSIVE_ETFS, capital)

    print("\n--- Equal Weight Baseline ---")
    eq_weights = equal_weight_portfolio(tickers)
    display_allocation(eq_weights, AGGRESSIVE_ETFS, capital)

    # Phase scaling
    print("\n\n" + "=" * 60)
    print("  ALLOCATION BY PHASE")
    print("=" * 60)

    phases = [
        ("Phase 1 (April)", 10000),
        ("Phase 2 (May-Jun)", 25000),
        ("Phase 3 (Jul-Sep)", 50000),
        ("Phase 4 (Oct-Dec)", 100000),
    ]

    for phase_name, phase_capital in phases:
        print(f"\n  {phase_name} — Total: ${phase_capital:,}")
        core_pct = 0.48 if phase_capital > 10000 else 0.60
        active_pct = 0.24 if phase_capital > 10000 else 0.30
        options_pct = 0.20 if phase_capital > 25000 else 0.0
        cash_pct = 1.0 - core_pct - active_pct - options_pct

        print(f"    Core ETFs:      ${phase_capital * core_pct:>10,.0f} ({core_pct:.0%})")
        print(f"    Active Trading: ${phase_capital * active_pct:>10,.0f} ({active_pct:.0%})")
        if options_pct > 0:
            print(f"    Options:        ${phase_capital * options_pct:>10,.0f} ({options_pct:.0%})")
        print(f"    Cash Reserve:   ${phase_capital * cash_pct:>10,.0f} ({cash_pct:.0%})")

    print("\n\nDone. Use these weights as starting points — adjust based on current market conditions.")
