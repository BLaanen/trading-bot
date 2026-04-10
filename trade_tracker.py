"""
Trade Tracker & Journal

Simple CSV-based trade journal to track performance and enforce risk rules.
Run: python trade_tracker.py
"""

import csv
import os
from datetime import datetime
from pathlib import Path

TRADES_FILE = Path(__file__).parent / "trades.csv"
PORTFOLIO_FILE = Path(__file__).parent / "portfolio_value.csv"

CSV_HEADERS = [
    "date", "ticker", "action", "shares", "price", "total",
    "strategy", "stop_loss", "target", "notes", "outcome", "pnl",
    "regime", "sector"
]

PORTFOLIO_HEADERS = ["date", "total_value", "cash", "invested", "daily_return", "notes"]


def init_files():
    """Create CSV files with headers if they don't exist."""
    for filepath, headers in [(TRADES_FILE, CSV_HEADERS), (PORTFOLIO_FILE, PORTFOLIO_HEADERS)]:
        if not filepath.exists():
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            print(f"  Created {filepath.name}")


def log_trade(
    ticker: str,
    action: str,
    shares: int,
    price: float,
    strategy: str = "",
    stop_loss: float = 0,
    target: float = 0,
    notes: str = "",
    outcome: str = "",
    pnl: float = 0,
    regime: str = "",
    sector: str = "",
):
    """Log a trade to the CSV journal."""
    total = shares * price
    # Auto-detect sector if not provided
    if not sector:
        try:
            from correlation_guard import get_sector
            sector = get_sector(ticker)
        except Exception:
            sector = ""
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        ticker.upper(),
        action.upper(),
        shares,
        f"{price:.2f}",
        f"{total:.2f}",
        strategy,
        f"{stop_loss:.2f}" if stop_loss else "",
        f"{target:.2f}" if target else "",
        notes,
        outcome,
        f"{pnl:.2f}" if pnl else "",
        regime,
        sector,
    ]
    # Ensure headers exist before appending
    file_exists = TRADES_FILE.exists()
    needs_header = not file_exists or TRADES_FILE.stat().st_size == 0
    with open(TRADES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if needs_header:
            writer.writerow(CSV_HEADERS)
        writer.writerow(row)
    print(f"  Logged: {action.upper()} {shares} {ticker.upper()} @ ${price:.2f} = ${total:.2f}")


def log_portfolio_value(total_value: float, cash: float, notes: str = ""):
    """Log daily portfolio value."""
    invested = total_value - cash

    # Calculate daily return
    daily_return = 0
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                prev_value = float(rows[-1]["total_value"])
                if prev_value > 0:
                    daily_return = (total_value - prev_value) / prev_value * 100

    row = [
        datetime.now().strftime("%Y-%m-%d"),
        f"{total_value:.2f}",
        f"{cash:.2f}",
        f"{invested:.2f}",
        f"{daily_return:.2f}",
        notes,
    ]
    # Ensure headers exist before appending
    pf_needs_header = not PORTFOLIO_FILE.exists() or PORTFOLIO_FILE.stat().st_size == 0
    with open(PORTFOLIO_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if pf_needs_header:
            writer.writerow(PORTFOLIO_HEADERS)
        writer.writerow(row)
    print(f"  Portfolio: ${total_value:,.2f} (Cash: ${cash:,.2f}, Invested: ${invested:,.2f})")
    if daily_return:
        print(f"  Daily return: {daily_return:+.2f}%")


def get_stats():
    """Print portfolio and trading stats."""
    if not TRADES_FILE.exists():
        print("  No trades recorded yet.")
        return

    with open(TRADES_FILE) as f:
        reader = csv.DictReader(f)
        trades = list(reader)

    if not trades:
        print("  No trades recorded yet.")
        return

    total_trades = len(trades)
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]

    closed_pnl = sum(float(t["pnl"]) for t in trades if t["pnl"])
    winners = [t for t in trades if t["pnl"] and float(t["pnl"]) > 0]
    losers = [t for t in trades if t["pnl"] and float(t["pnl"]) < 0]

    win_rate = len(winners) / (len(winners) + len(losers)) * 100 if (winners or losers) else 0

    print(f"\n  {'='*40}")
    print(f"  TRADING STATS")
    print(f"  {'='*40}")
    print(f"  Total trades:  {total_trades}")
    print(f"  Buys:          {len(buys)}")
    print(f"  Sells:         {len(sells)}")
    print(f"  Closed P&L:    ${closed_pnl:+,.2f}")
    print(f"  Winners:       {len(winners)}")
    print(f"  Losers:        {len(losers)}")
    print(f"  Win rate:      {win_rate:.1f}%")

    # Check risk rules
    print(f"\n  {'='*40}")
    print(f"  RISK CHECK")
    print(f"  {'='*40}")

    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE) as f:
            reader = csv.DictReader(f)
            values = list(reader)

        if values:
            current = float(values[-1]["total_value"])
            peak = max(float(v["total_value"]) for v in values)
            drawdown = (peak - current) / peak * 100 if peak > 0 else 0

            print(f"  Current value: ${current:,.2f}")
            print(f"  Peak value:    ${peak:,.2f}")
            print(f"  Drawdown:      {drawdown:.1f}%")

            if drawdown > 20:
                print("  *** WARNING: Drawdown > 20%! Stop active trading for 1 week. ***")
            elif drawdown > 15:
                print("  *** CAUTION: Drawdown > 15%. Reduce position sizes. ***")
            elif drawdown > 10:
                print("  * Note: Drawdown > 10%. Stay disciplined. *")
            else:
                print("  Status: Within risk limits.")

    # Check for consecutive losses
    recent_outcomes = [t for t in trades[-5:] if t["pnl"]]
    consecutive_losses = 0
    for t in reversed(recent_outcomes):
        if float(t["pnl"]) < 0:
            consecutive_losses += 1
        else:
            break

    if consecutive_losses >= 3:
        print(f"  *** WARNING: {consecutive_losses} consecutive losses! Take a 3-day break. ***")


if __name__ == "__main__":
    init_files()

    # Example usage
    print("\n  Trade Tracker initialized.")
    print(f"  Trades file:    {TRADES_FILE}")
    print(f"  Portfolio file:  {PORTFOLIO_FILE}")
    print("\n  Example commands:")
    print('    log_trade("QQQ", "BUY", 10, 450.00, strategy="MA Crossover", stop_loss=414.00)')
    print('    log_trade("QQQ", "SELL", 10, 475.00, outcome="WIN", pnl=250.00)')
    print('    log_portfolio_value(10500, 1000)')
    print('    get_stats()')

    get_stats()
