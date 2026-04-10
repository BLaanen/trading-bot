"""
Correlation Guard

If AAPL, MSFT, NVDA, and QQQ all fire signals at the same time,
that's NOT 4 independent bets — it's the same bet 4 times.

A naive system sees 4 trades risking 1% each = 4% risk.
In reality, because they're all correlated, the actual risk
is closer to 4% on a SINGLE outcome (tech goes up or down).

This module:
  1. Calculates rolling correlations between all positions
  2. Assigns each ticker to a correlation cluster
  3. Limits exposure per cluster
  4. Calculates "portfolio heat" — the real risk considering correlations

A 160 IQ trader knows that DIVERSIFICATION IS THE ONLY FREE LUNCH.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime

from config import AgentConfig
from data_provider import get_provider


# Sector mapping for quick lookups (fallback when correlation data unavailable)
SECTOR_MAP = {
    # Tech
    "AAPL": "TECH", "MSFT": "TECH", "GOOGL": "TECH", "META": "TECH",
    "CRM": "TECH", "ADBE": "TECH", "ORCL": "TECH",
    # Semiconductors (a sub-sector, but highly correlated)
    "NVDA": "SEMIS", "AMD": "SEMIS", "AVGO": "SEMIS", "INTC": "SEMIS",
    "QCOM": "SEMIS", "MU": "SEMIS", "AMAT": "SEMIS", "LRCX": "SEMIS",
    "KLAC": "SEMIS", "SNPS": "SEMIS",
    # Consumer
    "AMZN": "CONSUMER", "TSLA": "CONSUMER", "NFLX": "CONSUMER",
    # ETFs
    "QQQ": "TECH_ETF", "SPY": "BROAD_ETF", "IWM": "BROAD_ETF",
    "SOXX": "SEMI_ETF", "SMH": "SEMI_ETF", "XLK": "TECH_ETF",
    "XLF": "FINANCIALS", "XLE": "ENERGY", "XLV": "HEALTH",
    "XLI": "INDUSTRIALS", "XLC": "COMM", "XLY": "CONSUMER",
    "XLP": "STAPLES", "XLU": "UTILITIES", "XLRE": "REAL_ESTATE",
    "ARKK": "TECH_ETF",
}

# Which sectors are highly correlated with each other
CORRELATED_GROUPS = {
    "TECH_MEGA": {"TECH", "SEMIS", "TECH_ETF", "SEMI_ETF"},
    "DEFENSIVE": {"STAPLES", "UTILITIES", "HEALTH"},
    "CYCLICAL": {"CONSUMER", "INDUSTRIALS", "FINANCIALS"},
}


@dataclass
class CorrelationReport:
    portfolio_heat: float        # Actual risk as % of portfolio (accounting for correlation)
    max_cluster_exposure: float  # Largest single cluster as % of portfolio
    cluster_count: int           # How many distinct clusters
    warnings: list[str]
    cluster_breakdown: dict[str, list[str]]  # cluster → list of tickers

    @property
    def diversified(self) -> bool:
        """Is the portfolio adequately diversified?"""
        return self.max_cluster_exposure < 40 and self.cluster_count >= 2


def get_sector(ticker: str) -> str:
    """Get sector for a ticker. Checks dynamic universe first, falls back to hardcoded map."""
    if ticker in SECTOR_MAP:
        return SECTOR_MAP[ticker]
    # Try the dynamic universe sector map (covers 300-500 stocks)
    try:
        from universe import get_sector_map
        dynamic_map = get_sector_map()
        return dynamic_map.get(ticker, "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def get_correlation_cluster(ticker: str) -> str:
    """Map a ticker to its broader correlation cluster."""
    sector = get_sector(ticker)
    for cluster_name, sectors in CORRELATED_GROUPS.items():
        if sector in sectors:
            return cluster_name
    return sector  # If not in a group, the sector IS the cluster


def calculate_correlation_matrix(tickers: list[str], lookback_days: int = 60) -> pd.DataFrame | None:
    """Calculate pairwise correlations from recent returns."""
    if len(tickers) < 2:
        return None

    provider = get_provider()
    returns_data = {}

    for ticker in tickers:
        try:
            data = provider.get_bars(ticker, period="6mo")
            if data is not None and not data.empty and len(data) >= lookback_days:
                returns_data[ticker] = data["Close"].pct_change().iloc[-lookback_days:]
        except Exception:
            continue

    if len(returns_data) < 2:
        return None

    returns_df = pd.DataFrame(returns_data).dropna()
    if len(returns_df) < 20:
        return None

    return returns_df.corr()


def check_new_position(
    new_ticker: str,
    existing_tickers: list[str],
    existing_values: dict[str, float],
    total_value: float,
    config: AgentConfig,
) -> tuple[bool, str]:
    """
    Check if adding a new position would create dangerous concentration.

    Returns (allowed, reason).
    """
    new_cluster = get_correlation_cluster(new_ticker)
    cluster_value = 0

    for ticker in existing_tickers:
        if get_correlation_cluster(ticker) == new_cluster:
            cluster_value += existing_values.get(ticker, 0)

    cluster_pct = cluster_value / total_value * 100 if total_value > 0 else 0

    # Max 35% in any single correlation cluster
    max_cluster_pct = 35
    if cluster_pct >= max_cluster_pct:
        return False, (
            f"{new_ticker} ({new_cluster}) would exceed cluster limit. "
            f"Already {cluster_pct:.0f}% in {new_cluster} (max {max_cluster_pct}%)"
        )

    # Check if this exact sector already has too many positions
    new_sector = get_sector(new_ticker)
    same_sector_count = sum(1 for t in existing_tickers if get_sector(t) == new_sector)
    # In paper exploration mode, allow one more per sector to test the assumption
    sector_cap = getattr(config, "exploration_max_sector", config.max_sector_exposure) \
        if getattr(config, "paper_exploration_mode", False) else config.max_sector_exposure
    if same_sector_count >= sector_cap:
        return False, (
            f"Already {same_sector_count} positions in {new_sector} sector "
            f"(max {sector_cap})"
        )

    return True, f"{new_ticker} adds diversification ({new_cluster})"


def analyze_portfolio(
    tickers: list[str],
    values: dict[str, float],
    total_value: float,
) -> CorrelationReport:
    """Full portfolio correlation analysis."""
    warnings = []
    clusters: dict[str, list[str]] = {}

    # Group by correlation cluster
    for ticker in tickers:
        cluster = get_correlation_cluster(ticker)
        clusters.setdefault(cluster, []).append(ticker)

    # Calculate exposure per cluster
    cluster_exposures = {}
    for cluster, cluster_tickers in clusters.items():
        cluster_value = sum(values.get(t, 0) for t in cluster_tickers)
        cluster_pct = cluster_value / total_value * 100 if total_value > 0 else 0
        cluster_exposures[cluster] = cluster_pct

    max_cluster_exposure = max(cluster_exposures.values()) if cluster_exposures else 0

    # Warnings
    for cluster, pct in cluster_exposures.items():
        if pct > 35:
            warnings.append(f"OVERWEIGHT: {pct:.0f}% in {cluster} (max 35%)")
        elif pct > 25:
            warnings.append(f"Heavy: {pct:.0f}% in {cluster} — watch closely")

    if len(clusters) <= 1 and len(tickers) >= 2:
        warnings.append("NO DIVERSIFICATION: All positions in the same cluster")

    # Portfolio heat: naive risk * average correlation
    # Simple estimate: if all positions are in same cluster, heat = sum of risks
    # If diversified across clusters, heat is reduced
    naive_risk = len(tickers)  # Each position risks 1R
    diversification_factor = len(clusters) / max(len(tickers), 1)
    portfolio_heat = naive_risk * (1 - diversification_factor * 0.3)  # Rough adjustment

    # Try to calculate actual correlation if possible
    corr_matrix = calculate_correlation_matrix(tickers)
    if corr_matrix is not None:
        avg_corr = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)].mean()
        portfolio_heat = naive_risk * (0.5 + avg_corr * 0.5)  # More accurate

        if avg_corr > 0.7:
            warnings.append(f"HIGH CORRELATION: avg pairwise = {avg_corr:.2f}")
        elif avg_corr > 0.5:
            warnings.append(f"Moderate correlation: avg pairwise = {avg_corr:.2f}")

    return CorrelationReport(
        portfolio_heat=round(portfolio_heat, 1),
        max_cluster_exposure=round(max_cluster_exposure, 1),
        cluster_count=len(clusters),
        warnings=warnings,
        cluster_breakdown=clusters,
    )


def print_correlation_report(report: CorrelationReport):
    """Print portfolio diversification analysis."""
    print(f"\n{'='*70}")
    print(f"  CORRELATION & DIVERSIFICATION")
    print(f"{'='*70}")
    print(f"  Portfolio heat:     {report.portfolio_heat:.1f}R effective risk")
    print(f"  Clusters:           {report.cluster_count}")
    print(f"  Max cluster:        {report.max_cluster_exposure:.0f}%")
    print(f"  Diversified:        {'Yes' if report.diversified else 'NO'}")

    print(f"\n  Cluster breakdown:")
    for cluster, tickers in report.cluster_breakdown.items():
        print(f"    {cluster:<15} {', '.join(tickers)}")

    if report.warnings:
        print(f"\n  Warnings:")
        for w in report.warnings:
            print(f"    ! {w}")
    else:
        print(f"\n  No concentration warnings.")


if __name__ == "__main__":
    # Example: check a sample portfolio
    tickers = ["AAPL", "MSFT", "NVDA", "QQQ", "XLE"]
    values = {"AAPL": 1000, "MSFT": 1000, "NVDA": 1000, "QQQ": 1000, "XLE": 1000}
    report = analyze_portfolio(tickers, values, 10000)
    print_correlation_report(report)
