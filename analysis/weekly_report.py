"""
Weekly Report Generator

Generates a comprehensive weekly summary of:
  - Trade performance (wins/losses, R, P&L)
  - Best and worst patterns
  - Hypothesis status updates
  - Parameter changes made during the week
  - New hypotheses generated
  - Lessons learned
  - Proposals to review

Saved to: reports/YYYY-WW.md (ISO week number)

Usage:
  python3.11 weekly_report.py              # Generate for the current week
  python3.11 weekly_report.py --week 15    # Generate for a specific ISO week
  python3.11 weekly_report.py --last       # Generate for the previous week
  python3.11 weekly_report.py --view       # Show the most recent report
"""

import csv
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE / "reports"
TRADES_CSV = BASE / "trades.csv"
PORTFOLIO_CSV = BASE / "portfolio_value.csv"
PATTERNS_FILE = BASE / "patterns.json"
ADAPTATIONS_FILE = BASE / "adaptations.json"
OVERRIDES_FILE = BASE / "config_overrides.json"
CHANGELOG_FILE = BASE / "config_changelog.md"
GENERATED_HYPOTHESES_FILE = BASE / "generated_hypotheses.json"


def iso_week_bounds(year: int, week: int) -> tuple[date, date]:
    """Get Monday and Sunday of a given ISO week."""
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_trades_in_range(start: date, end: date) -> list[dict]:
    if not TRADES_CSV.exists():
        return []
    trades = []
    with open(TRADES_CSV) as f:
        for row in csv.DictReader(f):
            try:
                trade_date = datetime.strptime(row["date"][:10], "%Y-%m-%d").date()
                if start <= trade_date <= end:
                    trades.append(row)
            except (ValueError, KeyError):
                continue
    return trades


def get_portfolio_in_range(start: date, end: date) -> list[dict]:
    if not PORTFOLIO_CSV.exists():
        return []
    entries = []
    with open(PORTFOLIO_CSV) as f:
        for row in csv.DictReader(f):
            try:
                entry_date = datetime.strptime(row["date"][:10], "%Y-%m-%d").date()
                if start <= entry_date <= end:
                    entries.append(row)
            except (ValueError, KeyError):
                continue
    return entries


def generate_report(year: int, week: int) -> Path:
    """Build a full weekly report and write it to reports/YYYY-WW.md."""
    REPORTS_DIR.mkdir(exist_ok=True)
    start, end = iso_week_bounds(year, week)

    trades = get_trades_in_range(start, end)
    portfolio = get_portfolio_in_range(start, end)

    lines = []
    lines.append(f"# Weekly Report — Week {week} of {year}")
    lines.append("")
    lines.append(f"**Period:** {start.strftime('%Y-%m-%d')} (Mon) → {end.strftime('%Y-%m-%d')} (Sun)")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # ── Section 1: Portfolio Performance ──
    lines.append("## 1. Portfolio Performance")
    lines.append("")
    if portfolio:
        start_val = float(portfolio[0]["total_value"])
        end_val = float(portfolio[-1]["total_value"])
        change = end_val - start_val
        pct = (change / start_val * 100) if start_val > 0 else 0
        lines.append(f"- **Start value:** ${start_val:,.2f}")
        lines.append(f"- **End value:**   ${end_val:,.2f}")
        lines.append(f"- **Change:**      ${change:+,.2f} ({pct:+.2f}%)")
    else:
        lines.append("*No portfolio snapshots recorded this week.*")
    lines.append("")

    # ── Section 2: Trade Summary ──
    lines.append("## 2. Trade Summary")
    lines.append("")
    buys = [t for t in trades if t.get("action", "").upper() == "BUY"]
    sells = [t for t in trades if t.get("action", "").upper() == "SELL"]
    wins = [t for t in sells if "WIN" in t.get("outcome", "").upper()]
    losses = [t for t in sells if "LOSS" in t.get("outcome", "").upper()]
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in sells)
    win_rate = len(wins) / max(len(sells), 1) * 100 if sells else 0

    lines.append(f"- **Entries opened:** {len(buys)}")
    lines.append(f"- **Exits closed:**   {len(sells)}")
    lines.append(f"- **Wins / Losses:**  {len(wins)} / {len(losses)}")
    lines.append(f"- **Win rate:**       {win_rate:.0f}%")
    lines.append(f"- **Total P&L:**      ${total_pnl:+,.2f}")
    lines.append("")

    # ── Section 3: Biggest Winners & Losers ──
    if sells:
        lines.append("## 3. Biggest Winners & Losers")
        lines.append("")
        sells_by_pnl = sorted(sells, key=lambda t: float(t.get("pnl", 0) or 0), reverse=True)

        lines.append("### Top 3 Winners")
        for t in sells_by_pnl[:3]:
            pnl = float(t.get("pnl", 0) or 0)
            lines.append(f"- **{t.get('ticker', '?')}** ({t.get('strategy', '?')}): ${pnl:+,.2f}")

        lines.append("")
        lines.append("### Top 3 Losers")
        for t in sells_by_pnl[-3:][::-1]:
            pnl = float(t.get("pnl", 0) or 0)
            lines.append(f"- **{t.get('ticker', '?')}** ({t.get('strategy', '?')}): ${pnl:+,.2f}")
        lines.append("")

    # ── Section 4: Strategy Performance ──
    lines.append("## 4. Strategy Performance (this week)")
    lines.append("")
    strat_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    for t in sells:
        strat = t.get("strategy", "UNKNOWN")
        pnl = float(t.get("pnl", 0) or 0)
        strat_stats[strat]["pnl"] += pnl
        if "WIN" in t.get("outcome", "").upper():
            strat_stats[strat]["wins"] += 1
        elif "LOSS" in t.get("outcome", "").upper():
            strat_stats[strat]["losses"] += 1

    if strat_stats:
        lines.append("| Strategy | Wins | Losses | Win Rate | P&L |")
        lines.append("|----------|------|--------|----------|-----|")
        for strat, s in sorted(strat_stats.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
            total = s["wins"] + s["losses"]
            wr = s["wins"] / total * 100 if total else 0
            lines.append(f"| {strat} | {s['wins']} | {s['losses']} | {wr:.0f}% | ${s['pnl']:+,.2f} |")
    else:
        lines.append("*No closed trades to report this week.*")
    lines.append("")

    # ── Section 5: Pattern Memory Snapshot ──
    lines.append("## 5. Pattern Memory (top 10)")
    lines.append("")
    if PATTERNS_FILE.exists():
        patterns = json.loads(PATTERNS_FILE.read_text())
        ranked = sorted(
            patterns.values(),
            key=lambda p: (p["wins"] + p["losses"] >= 5, p.get("avg_r", 0)),
            reverse=True,
        )
        lines.append("| Pattern | Wins | Losses | Avg R | Confidence |")
        lines.append("|---------|------|--------|-------|------------|")
        for p in ranked[:10]:
            total = p["wins"] + p["losses"]
            conf = (
                "PROVEN" if total >= 30
                else "ESTABLISHED" if total >= 15
                else "EMERGING" if total >= 5
                else "TOO_FEW"
            )
            lines.append(f"| {p['key']} | {p['wins']} | {p['losses']} | {p.get('avg_r', 0):+.2f}R | {conf} |")
    else:
        lines.append("*No pattern memory yet.*")
    lines.append("")

    # ── Section 6: Config Changes ──
    lines.append("## 6. Config Changes This Week")
    lines.append("")
    overrides = {}
    if OVERRIDES_FILE.exists():
        overrides = json.loads(OVERRIDES_FILE.read_text())
    applied_this_week = [
        (k, v) for k, v in overrides.items()
        if isinstance(v, dict) and v.get("applied_at", "")[:10] >= start.isoformat()
    ]
    if applied_this_week:
        for k, v in applied_this_week:
            lines.append(f"- **{k}** = `{v.get('value')}`")
            lines.append(f"  - Reason: {v.get('reason', '')}")
    else:
        lines.append("*No config changes auto-applied this week.*")
    lines.append("")

    # ── Section 7: New Hypotheses ──
    lines.append("## 7. New Hypotheses Generated")
    lines.append("")
    if GENERATED_HYPOTHESES_FILE.exists():
        data = json.loads(GENERATED_HYPOTHESES_FILE.read_text())
        new_this_week = [
            h for h in data.get("hypotheses", [])
            if h.get("generated_at", "")[:10] >= start.isoformat()
        ]
        if new_this_week:
            for h in new_this_week:
                lines.append(f"- {h['claim']}")
        else:
            lines.append("*No new hypotheses this week.*")
    else:
        lines.append("*No hypothesis generator data yet.*")
    lines.append("")

    # ── Section 8: Dangerous Proposals (need review) ──
    lines.append("## 8. Proposals Awaiting Human Review")
    lines.append("")
    if ADAPTATIONS_FILE.exists():
        adaptations = json.loads(ADAPTATIONS_FILE.read_text())
        dangerous = [
            p for p in adaptations.values()
            if p.get("category") == "dangerous" and not p.get("applied")
        ]
        if dangerous:
            for p in dangerous:
                lines.append(f"- ⚠️  {p['text']}")
                lines.append(f"  - Seen {p['confirmations']} times")
        else:
            lines.append("*No dangerous proposals pending review.*")
    else:
        lines.append("*No adaptations data yet.*")
    lines.append("")

    # ── Section 9: Next Week Focus ──
    lines.append("## 9. Next Week Focus")
    lines.append("")
    if sells:
        avg_r = sum(float(t.get("pnl", 0) or 0) for t in sells) / max(len(sells), 1)
        if win_rate >= 60 and avg_r > 0:
            lines.append("- ✅ System is in a **hot streak** — maintain current parameters.")
        elif win_rate < 40:
            lines.append("- ⚠️  Win rate below 40% — investigate regime drift and pattern failures.")
            lines.append("- Consider lowering `exploration_max_positions` to reduce overexposure.")
        else:
            lines.append("- System is performing in the expected range. Keep collecting data.")
    else:
        lines.append("- No closed trades this week. Nothing to analyze yet.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by weekly_report.py — part of the trading bot learning loop.*")

    # Write to file
    filename = f"{year}-W{week:02d}.md"
    output = REPORTS_DIR / filename
    output.write_text("\n".join(lines))
    return output


def get_most_recent_report() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    reports = sorted(REPORTS_DIR.glob("*.md"), reverse=True)
    return reports[0] if reports else None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag == "--view":
            recent = get_most_recent_report()
            if recent:
                print(recent.read_text())
            else:
                print("No reports yet. Generate one first with: python3.11 weekly_report.py")
            sys.exit(0)
        elif flag == "--last":
            last_week = datetime.now().isocalendar()
            week = last_week.week - 1
            year = last_week.year
            if week < 1:
                year -= 1
                week = 52
            path = generate_report(year, week)
            print(f"Generated: {path}")
        elif flag == "--week":
            week = int(sys.argv[2])
            year = datetime.now().year
            path = generate_report(year, week)
            print(f"Generated: {path}")
        else:
            print(f"Unknown flag: {flag}")
            print("Options: --view, --last, --week N")
    else:
        now = datetime.now().isocalendar()
        path = generate_report(now.year, now.week)
        print(f"Generated: {path}")
