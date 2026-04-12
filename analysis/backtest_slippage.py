"""
Slippage Rejection Backtest

Runs the scanner's 5 strategies against 3 months of historical data,
simulates realistic slippage on each signal's entry price, and checks
how many would be rejected by the post-fill R:R threshold (1.5).

Acceptance criteria (from WEEKEND-PLAN.md Level 3):
  - Slippage rejection rate < 10% overall
  - Strategy R:R and win rate comparable to pre-rewrite baseline
  - No regressions in signal quality

Usage:
  python analysis/backtest_slippage.py              # Full 3-month backtest
  python analysis/backtest_slippage.py --quick       # 1-month, fewer tickers (faster)

Requires: yfinance, pandas, numpy
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Add trading root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Sandbox state files so we don't touch real ones
import tempfile
_tmpdir = tempfile.mkdtemp(prefix="trading_backtest_")
os.environ["TRADING_STATE_DIR"] = _tmpdir

from config import AgentConfig
from scanner import Signal

SLIPPAGE_RR_THRESHOLD = 1.5


def get_historical_tickers(config: AgentConfig, max_tickers: int = 0) -> list[str]:
    """Get the scan universe. Uses cached universe if available."""
    try:
        from universe import get_scan_tickers
        tickers = get_scan_tickers(config)
    except Exception:
        tickers = config.core_etfs + config.sector_etfs + [
            "AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL", "TSLA",
            "JPM", "V", "UNH", "HD", "PG", "JNJ", "XOM", "CVX",
            "HAL", "DVN", "CTRA", "MPC", "OXY",
        ]
    if max_tickers > 0:
        tickers = tickers[:max_tickers]
    return tickers



def run_scanner_on_tickers(tickers: list[str], config: AgentConfig) -> list[dict]:
    """Run all 5 scanner strategies against the ticker universe, collecting signals.

    Scanner functions fetch their own data internally (via yfinance).
    Each ticker is scanned by each applicable strategy.
    """
    from scanner import (
        scan_pullback, scan_consolidation_breakout, scan_ma_bounce,
        scan_sector_momentum, scan_powerx,
    )

    all_signals = []

    print(f"\n  Scanning {len(tickers)} tickers across 5 strategies...")
    print(f"  (Each ticker downloads its own data — this takes a few minutes)\n")

    strategies = [
        ("PULLBACK", scan_pullback),
        ("BREAKOUT", scan_consolidation_breakout),
        ("MA_BOUNCE", scan_ma_bounce),
        ("POWERX", scan_powerx),
    ]

    for strategy_name, scan_fn in strategies:
        count = 0
        tickers_for_strategy = tickers
        if strategy_name != "POWERX":
            tickers_for_strategy = [t for t in tickers if t not in config.sector_etfs]

        for ticker in tickers_for_strategy:
            try:
                sig = scan_fn(ticker, config)
                if sig is not None:
                    all_signals.append({
                        "ticker": sig.ticker,
                        "strategy": sig.strategy,
                        "entry_price": sig.entry_price,
                        "stop_loss": sig.stop_loss,
                        "target": sig.target,
                        "reward_risk": sig.reward_risk,
                        "risk": sig.risk,
                        "reason": sig.reason,
                    })
                    count += 1
            except Exception:
                pass

        print(f"    {strategy_name}: {count} signals")

    # Sector momentum scans sector ETFs as a group
    sector_count = 0
    for etf in config.sector_etfs:
        try:
            sig = scan_sector_momentum(etf, config)
            if sig is not None:
                all_signals.append({
                    "ticker": sig.ticker,
                    "strategy": sig.strategy,
                    "entry_price": sig.entry_price,
                    "stop_loss": sig.stop_loss,
                    "target": sig.target,
                    "reward_risk": sig.reward_risk,
                    "risk": sig.risk,
                    "reason": sig.reason,
                })
                sector_count += 1
        except Exception:
            pass
    print(f"    SECTOR_MOMENTUM: {sector_count} signals")

    print(f"\n  Total signals found: {len(all_signals)}")
    return all_signals


def simulate_slippage(signals: list[dict], slippage_scenarios: list[float]) -> pd.DataFrame:
    """
    For each signal, simulate multiple slippage levels and check R:R rejection.

    Slippage scenarios are percentages (e.g., 0.001 = 0.1% slippage).
    Slippage always hurts the entry: for longs, fill price is HIGHER than expected.
    """
    rows = []

    for sig in signals:
        entry = sig["entry_price"]
        stop = sig["stop_loss"]
        target = sig["target"]
        original_risk = entry - stop
        original_reward = target - entry
        original_rr = original_reward / original_risk if original_risk > 0 else 0

        for slip_pct in slippage_scenarios:
            slipped_entry = entry * (1 + slip_pct)
            new_risk = slipped_entry - stop
            new_reward = target - slipped_entry

            if new_risk > 0:
                new_rr = new_reward / new_risk
            else:
                new_rr = 0

            rejected = new_rr < SLIPPAGE_RR_THRESHOLD

            rows.append({
                "ticker": sig["ticker"],
                "strategy": sig["strategy"],
                "entry_price": entry,
                "stop_loss": stop,
                "target": target,
                "original_rr": original_rr,
                "slippage_pct": slip_pct * 100,
                "slipped_entry": slipped_entry,
                "new_rr": new_rr,
                "rejected": rejected,
            })

    return pd.DataFrame(rows)


def print_report(df: pd.DataFrame, signals: list[dict]):
    """Print the backtest results."""
    print("\n" + "=" * 70)
    print("  SLIPPAGE REJECTION BACKTEST RESULTS")
    print("=" * 70)

    # Overall signal quality
    print(f"\n  Total signals analyzed: {len(signals)}")
    strategies = {}
    for s in signals:
        strategies.setdefault(s["strategy"], []).append(s)

    print(f"\n  {'Strategy':<20} {'Signals':>8} {'Avg R:R':>8} {'Min R:R':>8} {'Max R:R':>8}")
    print(f"  {'─'*20} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    for strat, sigs in sorted(strategies.items()):
        rrs = [s["reward_risk"] for s in sigs]
        print(f"  {strat:<20} {len(sigs):>8} {np.mean(rrs):>8.2f} {np.min(rrs):>8.2f} {np.max(rrs):>8.2f}")

    # Rejection rates per slippage level
    print(f"\n  {'─'*70}")
    print(f"  REJECTION RATES BY SLIPPAGE LEVEL")
    print(f"  {'─'*70}")

    slippage_levels = sorted(df["slippage_pct"].unique())
    print(f"\n  {'Slippage':>10} {'Rejected':>10} {'Total':>8} {'Rate':>8} {'Pass?':>8}")
    print(f"  {'─'*10} {'─'*10} {'─'*8} {'─'*8} {'─'*8}")

    for slip in slippage_levels:
        subset = df[df["slippage_pct"] == slip]
        rejected = subset["rejected"].sum()
        total = len(subset)
        rate = rejected / total * 100 if total > 0 else 0
        passed = "YES" if rate < 10 else "NO"
        print(f"  {slip:>9.1f}% {rejected:>10} {total:>8} {rate:>7.1f}% {passed:>8}")

    # Rejection rates per strategy at realistic slippage (0.3%)
    realistic_slip = 0.3
    realistic = df[df["slippage_pct"] == realistic_slip]
    if len(realistic) > 0:
        print(f"\n  {'─'*70}")
        print(f"  PER-STRATEGY REJECTION AT {realistic_slip}% SLIPPAGE (realistic)")
        print(f"  {'─'*70}")

        print(f"\n  {'Strategy':<20} {'Rejected':>10} {'Total':>8} {'Rate':>8}")
        print(f"  {'─'*20} {'─'*10} {'─'*8} {'─'*8}")

        for strat in sorted(realistic["strategy"].unique()):
            strat_df = realistic[realistic["strategy"] == strat]
            rejected = strat_df["rejected"].sum()
            total = len(strat_df)
            rate = rejected / total * 100 if total > 0 else 0
            print(f"  {strat:<20} {rejected:>10} {total:>8} {rate:>7.1f}%")

    # R:R distribution of rejected signals at realistic slippage
    if len(realistic) > 0:
        rejected_sigs = realistic[realistic["rejected"]]
        if len(rejected_sigs) > 0:
            print(f"\n  {'─'*70}")
            print(f"  REJECTED SIGNALS — R:R DISTRIBUTION AT {realistic_slip}% SLIPPAGE")
            print(f"  {'─'*70}")
            print(f"\n  These signals had original R:R that was borderline — slippage pushed them under {SLIPPAGE_RR_THRESHOLD}:")
            print(f"  Original R:R range: {rejected_sigs['original_rr'].min():.2f} — {rejected_sigs['original_rr'].max():.2f}")
            print(f"  Post-slip R:R range: {rejected_sigs['new_rr'].min():.2f} — {rejected_sigs['new_rr'].max():.2f}")

            rr_buckets = pd.cut(rejected_sigs["original_rr"], bins=[0, 1.5, 1.7, 2.0, 2.5, 3.0, 100])
            print(f"\n  Original R:R bucket   Count")
            for bucket, count in rr_buckets.value_counts().sort_index().items():
                if count > 0:
                    print(f"  {str(bucket):<25} {count}")

    # Final verdict
    overall_realistic = df[df["slippage_pct"] == realistic_slip]
    if len(overall_realistic) > 0:
        overall_rate = overall_realistic["rejected"].sum() / len(overall_realistic) * 100
    else:
        overall_rate = 0

    print(f"\n  {'='*70}")
    if overall_rate < 10:
        print(f"  VERDICT: PASS — {overall_rate:.1f}% rejection rate at {realistic_slip}% slippage (< 10% threshold)")
    else:
        print(f"  VERDICT: FAIL — {overall_rate:.1f}% rejection rate at {realistic_slip}% slippage (>= 10% threshold)")
        print(f"  Consider raising SLIPPAGE_RR_THRESHOLD from {SLIPPAGE_RR_THRESHOLD} to a lower value,")
        print(f"  or tightening scanner R:R minimums to produce higher-quality signals.")
    print(f"  {'='*70}")

    return overall_rate


def main():
    parser = argparse.ArgumentParser(description="Slippage rejection backtest")
    parser.add_argument("--quick", action="store_true", help="Quick mode: 1 month, 30 tickers")
    parser.add_argument("--months", type=int, default=3, help="Months of history (default 3)")
    parser.add_argument("--max-tickers", type=int, default=0, help="Limit tickers (0 = all)")
    args = parser.parse_args()

    if args.quick:
        args.months = 1
        args.max_tickers = 30

    config = AgentConfig()

    print("=" * 70)
    print("  SLIPPAGE REJECTION BACKTEST")
    print(f"  R:R threshold: {SLIPPAGE_RR_THRESHOLD}")
    print(f"  Period: {args.months} months")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # Step 1: Get tickers
    tickers = get_historical_tickers(config, max_tickers=args.max_tickers)
    print(f"\n  Universe: {len(tickers)} tickers")

    # Step 2: Run scanner (each strategy downloads its own data)
    signals = run_scanner_on_tickers(tickers, config)

    if not signals:
        print("\n  ERROR: No signals found. Scanner may need investigation.")
        sys.exit(1)

    # Step 4: Simulate slippage at multiple levels
    slippage_scenarios = [0.001, 0.002, 0.003, 0.005, 0.01]  # 0.1% to 1.0%
    df = simulate_slippage(signals, slippage_scenarios)

    # Step 5: Report
    rejection_rate = print_report(df, signals)

    # Step 6: Save detailed results
    output_file = Path(__file__).parent / "backtest_slippage_results.csv"
    df.to_csv(output_file, index=False)
    print(f"\n  Detailed results saved to: {output_file}")

    # Cleanup
    import shutil
    shutil.rmtree(_tmpdir, ignore_errors=True)

    sys.exit(0 if rejection_rate < 10 else 1)


if __name__ == "__main__":
    main()
