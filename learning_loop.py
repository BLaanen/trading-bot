"""
Learning Loop — Post-Day Analysis & Self-Improvement

This is the meta-layer that turns paper trading from "execute signals" into
"learn to trade." Runs automatically at end-of-day and produces:

  1. trade_journal.md — append-only chronological log of all trades + notes
  2. lessons.md       — distilled insights, updated as patterns emerge
  3. hypotheses.md    — active hypotheses being tested, with running results
  4. experiments.json — parameter experiments with outcomes
  5. patterns.json    — what works in what regime (strategy × regime × sector × outcome)

The learning loop runs three stages:
  STAGE 1: COLLECT — pull all closed trades since last run
  STAGE 2: ANALYZE — compute per-trade autopsy (what went right/wrong)
  STAGE 3: SYNTHESIZE — update lessons, hypotheses, patterns
  STAGE 4: ADAPT     — propose parameter changes (flagged for review)

Usage:
  python3.11 learning_loop.py              # Run all stages
  python3.11 learning_loop.py --analyze    # Stage 2 only (no journal update)
  python3.11 learning_loop.py --lessons    # Show current lessons
  python3.11 learning_loop.py --patterns   # Show pattern memory
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

BASE = Path(__file__).parent
JOURNAL_FILE = BASE / "trade_journal.md"
LESSONS_FILE = BASE / "lessons.md"
HYPOTHESES_FILE = BASE / "hypotheses.md"
EXPERIMENTS_FILE = BASE / "experiments.json"
PATTERNS_FILE = BASE / "patterns.json"
LEARNING_STATE_FILE = BASE / "learning_state.json"
TRADES_CSV = BASE / "trades.csv"


@dataclass
class TradeAutopsy:
    """Per-trade post-mortem. Captures what happened and why."""
    ticker: str
    strategy: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_loss: float
    target: float
    shares: int
    pnl: float
    r_multiple: float
    outcome: str  # WIN, LOSS, BE (breakeven), PARTIAL
    hold_days: int
    regime_at_entry: str
    sector: str

    # Autopsy questions
    touched_target: bool = False         # Did price ever reach target?
    touched_stop: bool = False           # Did price ever reach stop?
    max_favorable_excursion: float = 0   # Best R it reached
    max_adverse_excursion: float = 0     # Worst R it reached (negative)

    # Verdict
    setup_valid: bool = True             # Was the original setup thesis sound?
    exit_quality: str = "ok"             # "good", "ok", "bad"
    lesson: str = ""                     # One-line takeaway


@dataclass
class Pattern:
    """A recurring pattern the system has observed."""
    key: str                 # e.g., "PULLBACK_CHOPPY_ENERGY"
    strategy: str
    regime: str
    sector: str
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    avg_r: float = 0.0
    sample_trades: list = field(default_factory=list)  # recent trade tickers

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def confidence(self) -> str:
        n = self.total_trades
        if n < 5:
            return "TOO_FEW"
        if n < 15:
            return "EMERGING"
        if n < 30:
            return "ESTABLISHED"
        return "PROVEN"


def load_learning_state() -> dict:
    if LEARNING_STATE_FILE.exists():
        return json.loads(LEARNING_STATE_FILE.read_text())
    return {
        "last_run": None,
        "last_trade_id_analyzed": 0,
        "total_autopsies": 0,
        "total_lessons_logged": 0,
    }


def save_learning_state(state: dict) -> None:
    state["last_run"] = datetime.now().isoformat()
    LEARNING_STATE_FILE.write_text(json.dumps(state, indent=2))


def load_patterns() -> dict[str, Pattern]:
    if not PATTERNS_FILE.exists():
        return {}
    data = json.loads(PATTERNS_FILE.read_text())
    return {k: Pattern(**v) for k, v in data.items()}


def save_patterns(patterns: dict[str, Pattern]) -> None:
    PATTERNS_FILE.write_text(json.dumps(
        {k: asdict(v) for k, v in patterns.items()},
        indent=2,
    ))


# ─── Stage 1: Collect ──────────────────────────────────────────────────────

def collect_closed_trades(since_trade_id: int = 0) -> list[dict]:
    """Load all closed trades from the trade journal since a given ID."""
    if not TRADES_CSV.exists():
        return []

    import csv
    trades = []
    with open(TRADES_CSV) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i < since_trade_id:
                continue
            # Only SELL rows represent completed trades
            if row.get("action", "").upper() == "SELL":
                trades.append(row)
    return trades


def pair_buys_with_sells() -> list[tuple[dict, dict]]:
    """Pair each BUY with its corresponding SELL to compute the full trade lifecycle."""
    if not TRADES_CSV.exists():
        return []
    import csv
    buys: dict[str, list[dict]] = defaultdict(list)
    pairs: list[tuple[dict, dict]] = []
    with open(TRADES_CSV) as f:
        for row in csv.DictReader(f):
            action = row.get("action", "").upper()
            ticker = row.get("ticker", "")
            if action == "BUY":
                buys[ticker].append(row)
            elif action == "SELL" and buys[ticker]:
                buy = buys[ticker].pop(0)
                pairs.append((buy, row))
    return pairs


# ─── Stage 2: Analyze ──────────────────────────────────────────────────────

def get_sector_for_ticker(ticker: str) -> str:
    """Look up a ticker's sector. Uses correlation_guard.get_sector."""
    try:
        from correlation_guard import get_sector
        return get_sector(ticker)
    except Exception:
        return "UNKNOWN"


def analyze_trade(buy: dict, sell: dict) -> TradeAutopsy:
    """Build a TradeAutopsy for a completed buy → sell pair."""
    entry_price = float(buy["price"])
    exit_price = float(sell["price"])
    shares = int(float(buy["shares"]))
    stop = float(buy.get("stop_loss", 0) or 0)
    target = float(buy.get("target", 0) or 0)
    pnl = shares * (exit_price - entry_price)

    # R multiple
    initial_risk = abs(entry_price - stop) if stop else 0
    if initial_risk > 0:
        r_multiple = (exit_price - entry_price) / initial_risk
    else:
        r_multiple = 0

    outcome_raw = sell.get("outcome", "").upper()
    if "WIN" in outcome_raw:
        outcome = "WIN"
    elif "LOSS" in outcome_raw:
        outcome = "LOSS"
    else:
        outcome = "BE"

    # Hold days
    try:
        buy_date = datetime.fromisoformat(buy.get("date", "")[:10])
        sell_date = datetime.fromisoformat(sell.get("date", "")[:10])
        hold_days = (sell_date - buy_date).days
    except Exception:
        hold_days = 0

    # Exit quality heuristic
    if r_multiple >= 2.0:
        exit_quality = "good"
    elif r_multiple >= 0.5:
        exit_quality = "ok"
    elif r_multiple >= -1.1:
        exit_quality = "ok"  # Stop hit cleanly, no slippage
    else:
        exit_quality = "bad"  # Worse than planned loss (slippage, gap)

    # One-line lesson
    ticker = buy.get("ticker", "")
    strategy = buy.get("strategy", "")
    if outcome == "WIN" and r_multiple >= 2:
        lesson = f"Winner: {strategy} on {ticker} hit {r_multiple:.1f}R — plan worked as designed"
    elif outcome == "WIN":
        lesson = f"Small win: {strategy} on {ticker} closed at {r_multiple:.1f}R — below target, trail activated"
    elif outcome == "LOSS" and r_multiple <= -1.1:
        lesson = f"Bad loss: {strategy} on {ticker} gapped through stop, -{abs(r_multiple):.1f}R"
    elif outcome == "LOSS":
        lesson = f"Clean stop: {strategy} on {ticker} stopped at -1R, thesis invalidated"
    else:
        lesson = f"Trade closed {ticker} at {r_multiple:+.1f}R"

    # Read regime + sector from buy row (new columns), fall back to lookup
    regime = buy.get("regime", "") or "UNKNOWN"
    sector = buy.get("sector", "") or get_sector_for_ticker(ticker)

    return TradeAutopsy(
        ticker=ticker,
        strategy=strategy,
        entry_date=buy.get("date", "")[:10],
        exit_date=sell.get("date", "")[:10],
        entry_price=entry_price,
        exit_price=exit_price,
        stop_loss=stop,
        target=target,
        shares=shares,
        pnl=pnl,
        r_multiple=round(r_multiple, 2),
        outcome=outcome,
        hold_days=hold_days,
        regime_at_entry=regime,
        sector=sector,
        exit_quality=exit_quality,
        lesson=lesson,
    )


# ─── Stage 3: Synthesize ───────────────────────────────────────────────────

def update_patterns(autopsies: list[TradeAutopsy]) -> dict[str, Pattern]:
    """Aggregate autopsies into pattern memory keyed by strategy × regime × sector."""
    patterns = load_patterns()

    for a in autopsies:
        key = f"{a.strategy}_{a.regime_at_entry}_{a.sector}"
        if key not in patterns:
            patterns[key] = Pattern(
                key=key,
                strategy=a.strategy,
                regime=a.regime_at_entry,
                sector=a.sector,
            )
        p = patterns[key]
        if a.outcome == "WIN":
            p.wins += 1
        elif a.outcome == "LOSS":
            p.losses += 1
        p.total_r += a.r_multiple
        if p.total_trades > 0:
            p.avg_r = round(p.total_r / p.total_trades, 2)
        # Keep last 10 sample trades
        p.sample_trades = ([a.ticker] + p.sample_trades)[:10]

    save_patterns(patterns)
    return patterns


def append_to_journal(autopsies: list[TradeAutopsy]) -> None:
    """Append each autopsy to the trade journal as markdown."""
    if not autopsies:
        return

    header = f"\n## Trading Session — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    lines = [header]

    for a in autopsies:
        lines.append(f"### {a.ticker} — {a.strategy} — {a.outcome} ({a.r_multiple:+.1f}R)\n")
        lines.append(f"- **Entry:** ${a.entry_price:.2f} on {a.entry_date}")
        lines.append(f"- **Exit:** ${a.exit_price:.2f} on {a.exit_date}")
        lines.append(f"- **Stop:** ${a.stop_loss:.2f} | **Target:** ${a.target:.2f}")
        lines.append(f"- **Held:** {a.hold_days} day(s) | **Sector:** {a.sector}")
        lines.append(f"- **PnL:** ${a.pnl:+,.2f} | **R:** {a.r_multiple:+.2f} | **Quality:** {a.exit_quality}")
        lines.append(f"- **Lesson:** {a.lesson}")
        lines.append("")

    content = "\n".join(lines)

    if not JOURNAL_FILE.exists():
        JOURNAL_FILE.write_text(
            "# Trade Journal\n\n"
            "Append-only log of all trades. Each entry includes outcome and lesson.\n"
            + content
        )
    else:
        with open(JOURNAL_FILE, "a") as f:
            f.write(content)


def distill_lessons(patterns: dict[str, Pattern]) -> None:
    """Rewrite lessons.md with the top patterns — the stuff that's working and not."""
    ranked = sorted(
        patterns.values(),
        key=lambda p: (p.total_trades >= 5, p.avg_r, p.total_trades),
        reverse=True,
    )

    lines = [
        "# Lessons Learned",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Pattern Memory (strategy × regime × sector)",
        "",
        "| Pattern | Wins | Losses | Win Rate | Avg R | Confidence |",
        "|---------|------|--------|----------|-------|------------|",
    ]

    for p in ranked[:30]:
        lines.append(
            f"| {p.key} | {p.wins} | {p.losses} | "
            f"{p.win_rate*100:.0f}% | {p.avg_r:+.2f}R | {p.confidence} |"
        )

    lines.append("")
    lines.append("## Rules Derived From Patterns")
    lines.append("")

    working = [p for p in ranked if p.total_trades >= 5 and p.avg_r >= 0.5]
    failing = [p for p in ranked if p.total_trades >= 5 and p.avg_r < -0.3]

    if working:
        lines.append("### What's Working (avg R >= +0.5 with 5+ trades)")
        for p in working:
            lines.append(f"- **{p.key}**: {p.avg_r:+.2f}R avg, {p.win_rate*100:.0f}% win rate — keep running")
        lines.append("")
    else:
        lines.append("### What's Working")
        lines.append("- *Not enough data yet. Need at least 5 trades per pattern to establish confidence.*")
        lines.append("")

    if failing:
        lines.append("### What's Failing (avg R < -0.3 with 5+ trades)")
        for p in failing:
            lines.append(f"- **{p.key}**: {p.avg_r:+.2f}R avg, {p.win_rate*100:.0f}% win rate — investigate or disable")
        lines.append("")

    LESSONS_FILE.write_text("\n".join(lines))


def update_hypotheses() -> None:
    """Initialize hypotheses.md if missing, with starter hypotheses to test."""
    if HYPOTHESES_FILE.exists():
        return

    content = """# Active Hypotheses

These are beliefs we're testing with real trade data. Each hypothesis has:
- **Claim**: what we believe is true
- **Test**: how we'll measure it
- **Status**: accumulating data / confirmed / rejected
- **Evidence**: trade-by-trade results

## H1: Pullback setups work best in NEUTRAL regime

- **Claim**: PULLBACK strategy has higher win rate in NEUTRAL vs BULL regime
- **Test**: compare win rate of PULLBACK trades tagged NEUTRAL vs BULL after 10+ of each
- **Status**: accumulating data
- **Evidence**: TBD

## H2: Energy sector correlation guard is too strict

- **Claim**: Allowing 3 Energy positions (vs 2) would improve returns when Energy is trending
- **Test**: backtest with max_sector_exposure=3 on historical energy rallies
- **Status**: untested
- **Evidence**: TBD

## H3: 10-minute post-open wait improves fills

- **Claim**: Waiting 10 minutes after market open reduces slippage vs market-open fills
- **Test**: compare avg slippage on immediate-open fills vs +10min fills
- **Status**: accumulating data
- **Evidence**: TBD (need to log slippage per fill)

## H4: Target hit rate predicts strategy edge

- **Claim**: A strategy where >40% of trades touch their target is a valid edge
- **Test**: compute target-touch-rate per strategy, correlate with total R
- **Status**: needs implementation
- **Evidence**: TBD

## H5: Paper trading is free data — explore aggressively

- **Claim**: In paper mode, running MORE strategies (even marginal ones) generates more data to learn from
- **Test**: enable all 5 strategies in all regimes for 2 weeks, measure which actually produce edge
- **Status**: proposed change to config
- **Evidence**: TBD

## Adding New Hypotheses

When you notice a pattern, add a hypothesis here. The learning loop will keep an eye on it.
"""
    HYPOTHESES_FILE.write_text(content)


# ─── Stage 4: Adapt (propose changes) ──────────────────────────────────────

def propose_adaptations(patterns: dict[str, Pattern]) -> list[str]:
    """Propose parameter changes based on patterns. These are SUGGESTIONS only — never applied automatically."""
    proposals = []

    # Disable patterns that are clearly losing
    for p in patterns.values():
        if p.total_trades >= 10 and p.avg_r < -0.5:
            proposals.append(
                f"Consider disabling {p.strategy} in {p.regime} regime for {p.sector} — "
                f"{p.wins}W/{p.losses}L, {p.avg_r:+.2f}R avg over {p.total_trades} trades"
            )

    # Scale up patterns that are clearly winning
    for p in patterns.values():
        if p.total_trades >= 15 and p.avg_r >= 1.0 and p.win_rate >= 0.5:
            proposals.append(
                f"Consider increasing position size for {p.strategy}/{p.regime}/{p.sector} — "
                f"PROVEN edge: {p.win_rate*100:.0f}% wr, {p.avg_r:+.2f}R avg"
            )

    return proposals


# ─── Main ──────────────────────────────────────────────────────────────────

def run_full_loop():
    print("=" * 70)
    print(f"  LEARNING LOOP — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    state = load_learning_state()

    # Stage 1: Collect
    print("\n[1/4] COLLECT — pairing buys with sells...")
    pairs = pair_buys_with_sells()
    print(f"  Found {len(pairs)} completed trades in trades.csv")

    if not pairs:
        print("\n  No completed trades yet. Run after a trading day that closed positions.")
        update_hypotheses()  # Still set up the hypotheses file
        save_learning_state(state)
        return

    # Stage 2: Analyze
    print(f"\n[2/4] ANALYZE — building autopsies for {len(pairs)} trades...")
    autopsies = [analyze_trade(b, s) for b, s in pairs]
    for a in autopsies[-5:]:  # Show last 5
        print(f"  {a.entry_date} {a.ticker:<6} {a.strategy:<10} "
              f"{a.outcome:<4} {a.r_multiple:+.1f}R  {a.lesson[:50]}")

    # Stage 3: Synthesize
    print(f"\n[3/4] SYNTHESIZE — updating patterns and journal...")
    patterns = update_patterns(autopsies)
    append_to_journal(autopsies)
    distill_lessons(patterns)
    update_hypotheses()

    # Summary stats
    total_r = sum(a.r_multiple for a in autopsies)
    wins = sum(1 for a in autopsies if a.outcome == "WIN")
    losses = sum(1 for a in autopsies if a.outcome == "LOSS")
    win_rate = wins / (wins + losses) * 100 if (wins + losses) else 0
    avg_r = total_r / len(autopsies) if autopsies else 0

    print(f"\n  Summary:")
    print(f"    Total trades analyzed: {len(autopsies)}")
    print(f"    Wins: {wins}  Losses: {losses}  Win rate: {win_rate:.0f}%")
    print(f"    Total R: {total_r:+.2f}R  Avg R: {avg_r:+.2f}R")
    print(f"    Patterns tracked: {len(patterns)}")

    # Stage 4: Adapt — record proposals with adaptive_config for auto-apply
    print(f"\n[4/4] ADAPT — proposing and applying parameter changes...")
    proposals = propose_adaptations(patterns)
    if proposals:
        print(f"  {len(proposals)} proposals this run:")
        for p in proposals:
            print(f"    • {p}")
        # Record proposals and apply any that have enough confirmations
        from adaptive_config import record_proposals, apply_pending
        record_proposals(proposals)
        applied = apply_pending()
        if applied:
            print(f"\n  Auto-applied {len(applied)} safe proposals after {len(applied)} confirmations each.")
    else:
        print("  No proposals. Not enough confident patterns yet.")

    # Stage 5: Hypothesis generation — spot unexpected patterns
    print(f"\n[5/6] HYPOTHESIZE — looking for emergent patterns...")
    try:
        from hypothesis_generator import generate_hypotheses
        new_hyps = generate_hypotheses(autopsies, patterns)
        if new_hyps:
            print(f"  Generated {len(new_hyps)} new hypothesis(es) to test.")
        else:
            print("  No new hypotheses. Current data doesn't suggest anything unexpected yet.")
    except ImportError:
        print("  hypothesis_generator not available")

    state["total_autopsies"] = len(autopsies)
    save_learning_state(state)

    print("\n" + "=" * 70)
    print(f"  Journal:    {JOURNAL_FILE.name}")
    print(f"  Lessons:    {LESSONS_FILE.name}")
    print(f"  Hypotheses: {HYPOTHESES_FILE.name}")
    print(f"  Patterns:   {PATTERNS_FILE.name}")
    print("=" * 70)


def show_lessons():
    if LESSONS_FILE.exists():
        print(LESSONS_FILE.read_text())
    else:
        print("No lessons yet. Run learning_loop.py after closing some trades.")


def show_patterns():
    patterns = load_patterns()
    if not patterns:
        print("No patterns in memory yet.")
        return
    for k, p in sorted(patterns.items(), key=lambda kv: kv[1].avg_r, reverse=True):
        print(f"{k:<40} W:{p.wins:>2} L:{p.losses:>2} WR:{p.win_rate*100:>3.0f}% "
              f"avgR:{p.avg_r:+.2f}  [{p.confidence}]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag == "--lessons":
            show_lessons()
        elif flag == "--patterns":
            show_patterns()
        elif flag == "--analyze":
            run_full_loop()
        else:
            print(f"Unknown flag: {flag}")
            print("Options: --lessons, --patterns, --analyze, or no flag for full loop")
    else:
        run_full_loop()
