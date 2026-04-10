"""
Hypothesis Generator

Analyzes trade data and pattern memory to spot unexpected correlations,
then writes new hypotheses to hypotheses.md for the learning loop to test.

The goal: discover edges we didn't set out to find.

What it looks for:
  1. Time-of-day effects (morning vs afternoon entries)
  2. Hold-day effects (do longer holds perform better?)
  3. Day-of-week effects (Monday vs Friday)
  4. Consecutive-win / consecutive-loss streaks
  5. Sector rotation (one sector stops working while another starts)
  6. Strategy-ticker affinity (does PowerX work better on semis?)
  7. Volatility regime effects (how does the strategy do in high vs low VIX?)

Usage:
  python3.11 hypothesis_generator.py          # Scan current data and generate hypotheses
  python3.11 hypothesis_generator.py --list   # Show all hypotheses (manual + generated)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
HYPOTHESES_FILE = BASE / "hypotheses.md"
GENERATED_HYPOTHESES_FILE = BASE / "generated_hypotheses.json"
TRADES_CSV = BASE / "trades.csv"

# Minimum trades before a hypothesis makes sense
MIN_TRADES_FOR_HYPOTHESIS = 5


def load_generated() -> dict:
    if GENERATED_HYPOTHESES_FILE.exists():
        return json.loads(GENERATED_HYPOTHESES_FILE.read_text())
    return {"hypotheses": []}


def save_generated(data: dict) -> None:
    GENERATED_HYPOTHESES_FILE.write_text(json.dumps(data, indent=2))


def generate_hypotheses(autopsies: list, patterns: dict) -> list[str]:
    """Scan autopsies + patterns for unexpected correlations. Returns new hypothesis strings."""
    generated = load_generated()
    existing_claims = {h["claim"] for h in generated.get("hypotheses", [])}
    new_hypotheses: list[str] = []

    if len(autopsies) < MIN_TRADES_FOR_HYPOTHESIS:
        return []

    # ── Check 1: Day-of-week effect ──
    dow_stats: dict[str, list[float]] = defaultdict(list)
    for a in autopsies:
        try:
            dt = datetime.fromisoformat(a.entry_date)
            dow = dt.strftime("%A")
            dow_stats[dow].append(a.r_multiple)
        except Exception:
            continue

    if len(dow_stats) >= 3:
        # Find best and worst days
        dow_avg = {d: sum(rs) / len(rs) for d, rs in dow_stats.items() if len(rs) >= 2}
        if dow_avg:
            best_dow = max(dow_avg, key=dow_avg.get)
            worst_dow = min(dow_avg, key=dow_avg.get)
            spread = dow_avg[best_dow] - dow_avg[worst_dow]
            if spread > 1.0:  # Meaningful spread (> 1R difference)
                claim = (
                    f"Entries on {best_dow} outperform {worst_dow} by {spread:.1f}R on average"
                )
                if claim not in existing_claims:
                    new_hypotheses.append(claim)

    # ── Check 2: Hold-duration effect ──
    short_holds = [a for a in autopsies if a.hold_days <= 3]
    long_holds = [a for a in autopsies if a.hold_days >= 7]
    if len(short_holds) >= 3 and len(long_holds) >= 3:
        short_avg = sum(a.r_multiple for a in short_holds) / len(short_holds)
        long_avg = sum(a.r_multiple for a in long_holds) / len(long_holds)
        if abs(short_avg - long_avg) > 0.5:
            winner = "short" if short_avg > long_avg else "long"
            claim = (
                f"{winner.title()}-duration holds (<3d vs >7d) outperform by "
                f"{abs(short_avg - long_avg):.1f}R"
            )
            if claim not in existing_claims:
                new_hypotheses.append(claim)

    # ── Check 3: Strategy × Sector affinity ──
    strategy_sector: dict[tuple, list[float]] = defaultdict(list)
    for a in autopsies:
        strategy_sector[(a.strategy, a.sector)].append(a.r_multiple)

    for (strat, sector), rs in strategy_sector.items():
        if len(rs) < 5:
            continue
        avg = sum(rs) / len(rs)
        if avg > 1.0:  # Strong positive edge
            claim = f"{strat} on {sector} stocks shows strong edge ({avg:+.1f}R avg over {len(rs)} trades)"
            if claim not in existing_claims:
                new_hypotheses.append(claim)
        elif avg < -0.5:
            claim = f"{strat} on {sector} stocks shows negative edge ({avg:+.1f}R avg over {len(rs)} trades)"
            if claim not in existing_claims:
                new_hypotheses.append(claim)

    # ── Check 4: Consecutive streaks ──
    if len(autopsies) >= 10:
        # Look at the last 10 trades — are they all wins or all losses?
        last_10 = autopsies[-10:]
        wins = sum(1 for a in last_10 if a.outcome == "WIN")
        if wins >= 8:
            claim = "Current system is in a strong hot streak (8+ wins out of last 10)"
            if claim not in existing_claims:
                new_hypotheses.append(claim)
        elif wins <= 2:
            claim = "Current system is in a cold streak (8+ losses out of last 10) — investigate regime drift"
            if claim not in existing_claims:
                new_hypotheses.append(claim)

    # ── Check 5: Target vs stop touches ──
    target_touches = sum(1 for a in autopsies if getattr(a, "touched_target", False))
    stop_touches = sum(1 for a in autopsies if getattr(a, "touched_stop", False))
    if len(autopsies) >= 10:
        target_rate = target_touches / len(autopsies)
        if target_rate < 0.3:
            claim = (
                f"Targets are too ambitious — only {target_rate*100:.0f}% of trades reach target. "
                "Consider tightening targets or using trailing stops earlier."
            )
            if claim not in existing_claims:
                new_hypotheses.append(claim)

    # ── Check 6: Winning patterns worth betting more on ──
    for key, p in patterns.items():
        if p.total_trades >= 8 and p.win_rate >= 0.6 and p.avg_r >= 0.8:
            claim = (
                f"{p.strategy} in {p.regime} regime for {p.sector} is a proven edge "
                f"({p.win_rate*100:.0f}% WR, {p.avg_r:+.1f}R avg) — consider increased size"
            )
            if claim not in existing_claims:
                new_hypotheses.append(claim)

    # ── Save + append to hypotheses.md ──
    if new_hypotheses:
        now = datetime.now().isoformat()
        for h in new_hypotheses:
            generated["hypotheses"].append({
                "claim": h,
                "generated_at": now,
                "status": "proposed",
                "wins": 0,
                "losses": 0,
                "evidence": [],
            })
        save_generated(generated)
        append_to_hypotheses_md(new_hypotheses)

    return new_hypotheses


def append_to_hypotheses_md(new_hyps: list[str]) -> None:
    """Append auto-generated hypotheses to hypotheses.md in a dedicated section."""
    if not HYPOTHESES_FILE.exists():
        HYPOTHESES_FILE.write_text("# Active Hypotheses\n\n")

    content = HYPOTHESES_FILE.read_text()

    # Find or create the "Auto-Generated" section
    marker = "## Auto-Generated Hypotheses"
    if marker not in content:
        content += f"\n\n{marker}\n\n"
        content += "These are hypotheses the bot noticed by examining its own trading data.\n"
        content += "Each one is a pattern worth investigating or exploiting.\n\n"

    # Append new ones at the end
    additions = []
    ts = datetime.now().strftime("%Y-%m-%d")
    for h in new_hyps:
        additions.append(f"### [{ts}] {h}\n")
        additions.append("- **Claim**: " + h)
        additions.append("- **Status**: proposed")
        additions.append("- **Evidence**: accumulating")
        additions.append("")

    content += "\n".join(additions)
    HYPOTHESES_FILE.write_text(content)


def list_all_hypotheses() -> None:
    """Print both manual and auto-generated hypotheses."""
    if HYPOTHESES_FILE.exists():
        print(HYPOTHESES_FILE.read_text())
    else:
        print("No hypotheses file yet. Run learning_loop.py first.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        list_all_hypotheses()
        sys.exit(0)

    # Standalone run: load trade data and generate
    print("Generating hypotheses from trade data...")
    try:
        from learning_loop import pair_buys_with_sells, analyze_trade, load_patterns
        pairs = pair_buys_with_sells()
        if not pairs:
            print("No completed trades yet.")
            sys.exit(0)
        autopsies = [analyze_trade(b, s) for b, s in pairs]
        patterns = load_patterns()
        new = generate_hypotheses(autopsies, patterns)
        if new:
            print(f"\nGenerated {len(new)} new hypotheses:")
            for h in new:
                print(f"  • {h}")
        else:
            print("\nNo new hypotheses generated — not enough data or no unusual patterns.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
