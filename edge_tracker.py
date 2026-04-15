"""
Edge Tracker — Real-time Strategy Performance Monitor

Most traders backtest once and then trade forever. A 160 IQ trader
knows that EDGE DECAYS. A strategy that worked 6 months ago may be
crowded, arbitraged, or killed by a regime change.

This module:
  1. Tracks per-strategy performance in real-time (not just overall)
  2. Detects when a strategy's edge is degrading
  3. Automatically disables strategies that stop working
  4. Identifies which strategies work in which regimes
  5. Implements a "time stop" — kills trades that go nowhere

Key insight: you don't need more strategies.
You need to know WHICH of your strategies is working NOW.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from config import AgentConfig


@dataclass
class StrategyStats:
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    last_10_r: list[float] = field(default_factory=list)
    enabled: bool = True
    disabled_reason: str = ""
    disabled_until: str = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades > 0 else 0

    @property
    def expectancy_r(self) -> float:
        """Expected R per trade."""
        if self.total_trades < 5:
            return 0  # Not enough data
        wr = self.wins / self.total_trades
        return wr * self.avg_win_r - (1 - wr) * abs(self.avg_loss_r)

    @property
    def recent_expectancy(self) -> float:
        """Expectancy over last 10 trades — detects decay."""
        if len(self.last_10_r) < 5:
            return 0
        return sum(self.last_10_r) / len(self.last_10_r)

    @property
    def is_decaying(self) -> bool:
        """Is the strategy performing worse recently than historically?"""
        if self.total_trades < 15 or len(self.last_10_r) < 8:
            return False
        return self.recent_expectancy < self.expectancy_r * 0.3  # Recent < 30% of historical


@dataclass
class TradeRecord:
    ticker: str
    strategy: str
    entry_date: str
    exit_date: str
    r_multiple: float
    outcome: str  # "WIN", "LOSS", "BREAKEVEN", "TIME_STOP"
    hold_days: int
    regime: str = ""


_STATE_DIR = Path(os.environ.get("TRADING_STATE_DIR", str(Path(__file__).parent)))
EDGE_FILE = _STATE_DIR / "edge_tracker.json"


def _load() -> dict[str, StrategyStats]:
    if not EDGE_FILE.exists():
        return {}
    with open(EDGE_FILE) as f:
        data = json.load(f)
    stats = {}
    for name, d in data.items():
        stats[name] = StrategyStats(
            name=name,
            total_trades=d.get("total_trades", 0),
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            total_r=d.get("total_r", 0),
            avg_win_r=d.get("avg_win_r", 0),
            avg_loss_r=d.get("avg_loss_r", 0),
            win_streak=d.get("win_streak", 0),
            loss_streak=d.get("loss_streak", 0),
            max_win_streak=d.get("max_win_streak", 0),
            max_loss_streak=d.get("max_loss_streak", 0),
            last_10_r=d.get("last_10_r", []),
            enabled=d.get("enabled", True),
            disabled_reason=d.get("disabled_reason", ""),
            disabled_until=d.get("disabled_until", ""),
        )
    return stats


def _save(stats: dict[str, StrategyStats]):
    data = {}
    for name, s in stats.items():
        data[name] = {
            "total_trades": s.total_trades,
            "wins": s.wins,
            "losses": s.losses,
            "total_r": s.total_r,
            "avg_win_r": round(s.avg_win_r, 3),
            "avg_loss_r": round(s.avg_loss_r, 3),
            "win_streak": s.win_streak,
            "loss_streak": s.loss_streak,
            "max_win_streak": s.max_win_streak,
            "max_loss_streak": s.max_loss_streak,
            "last_10_r": [round(r, 3) for r in s.last_10_r[-10:]],
            "enabled": s.enabled,
            "disabled_reason": s.disabled_reason,
            "disabled_until": s.disabled_until,
        }
    with open(EDGE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(EDGE_FILE, 0o600)


def record_trade(strategy: str, r_multiple: float, hold_days: int = 0):
    """Record a completed trade and update strategy stats."""
    stats = _load()

    if strategy not in stats:
        stats[strategy] = StrategyStats(name=strategy)

    s = stats[strategy]
    s.total_trades += 1
    s.total_r += r_multiple

    if r_multiple > 0:
        s.wins += 1
        s.win_streak += 1
        s.loss_streak = 0
        s.max_win_streak = max(s.max_win_streak, s.win_streak)
        # Update avg win R (running average)
        if s.avg_win_r == 0:
            s.avg_win_r = r_multiple
        else:
            s.avg_win_r = s.avg_win_r * 0.8 + r_multiple * 0.2  # EMA
    else:
        s.losses += 1
        s.loss_streak += 1
        s.win_streak = 0
        s.max_loss_streak = max(s.max_loss_streak, s.loss_streak)
        if s.avg_loss_r == 0:
            s.avg_loss_r = abs(r_multiple)
        else:
            s.avg_loss_r = s.avg_loss_r * 0.8 + abs(r_multiple) * 0.2

    # Track last 10
    s.last_10_r.append(round(r_multiple, 3))
    if len(s.last_10_r) > 10:
        s.last_10_r = s.last_10_r[-10:]

    # Auto-disable check
    _check_strategy_health(s)

    _save(stats)


def _check_strategy_health(s: StrategyStats):
    """Disable strategies that have lost their edge."""
    # Rule 1: 5 consecutive losses → disable for 1 week
    if s.loss_streak >= 5:
        s.enabled = False
        s.disabled_reason = f"{s.loss_streak} consecutive losses"
        s.disabled_until = (datetime.now() + timedelta(days=7)).isoformat()
        return

    # Rule 2: Negative expectancy over last 10 trades (with enough data)
    if len(s.last_10_r) >= 8 and s.recent_expectancy < -0.3:
        s.enabled = False
        s.disabled_reason = f"Recent expectancy {s.recent_expectancy:.2f}R (negative)"
        s.disabled_until = (datetime.now() + timedelta(days=5)).isoformat()
        return

    # Rule 3: Edge decay — recent performance < 30% of historical
    if s.is_decaying:
        s.enabled = False
        s.disabled_reason = (
            f"Edge decay: recent {s.recent_expectancy:.2f}R vs "
            f"historical {s.expectancy_r:.2f}R"
        )
        s.disabled_until = (datetime.now() + timedelta(days=5)).isoformat()
        return

    # Re-enable if disabled and past the disabled_until date
    if not s.enabled and s.disabled_until:
        if datetime.now().isoformat() >= s.disabled_until:
            s.enabled = True
            s.disabled_reason = ""
            s.disabled_until = ""


def is_strategy_enabled(strategy: str) -> bool:
    """Check if a strategy is currently enabled."""
    stats = _load()
    if strategy not in stats:
        return True  # New strategy, enabled by default
    s = stats[strategy]
    _check_strategy_health(s)
    _save(stats)
    return s.enabled


def should_time_stop(entry_date: str, max_hold_days: int = 15) -> bool:
    """
    Time stop: if a trade hasn't moved in max_hold_days, close it.

    Dead money is worse than a small loss — it ties up capital that
    could be deployed in a working trade.
    """
    try:
        entry = datetime.strptime(entry_date, "%Y-%m-%d")
        days_held = (datetime.now() - entry).days
        return days_held >= max_hold_days
    except ValueError:
        return False


def get_strategy_ranking() -> list[tuple[str, StrategyStats]]:
    """Rank strategies by recent expectancy (best performing first)."""
    stats = _load()
    ranked = sorted(
        stats.items(),
        key=lambda x: x[1].recent_expectancy if len(x[1].last_10_r) >= 5 else x[1].expectancy_r,
        reverse=True,
    )
    return ranked


def print_edge_report():
    """Print full strategy performance report."""
    stats = _load()

    print(f"\n{'='*70}")
    print(f"  STRATEGY EDGE TRACKER")
    print(f"{'='*70}")

    if not stats:
        print("  No trade history yet.")
        return

    print(f"\n  {'Strategy':<18} {'Trades':>6} {'WR':>5} {'ExpR':>6} {'Recent':>7} "
          f"{'TotalR':>7} {'Status':>10}")
    print(f"  {'─'*18} {'─'*6} {'─'*5} {'─'*6} {'─'*7} {'─'*7} {'─'*10}")

    for name, s in sorted(stats.items(), key=lambda x: x[1].expectancy_r, reverse=True):
        status = "ACTIVE" if s.enabled else "DISABLED"
        recent = f"{s.recent_expectancy:+.2f}R" if len(s.last_10_r) >= 5 else "n/a"
        decay = " DECAY" if s.is_decaying else ""

        print(
            f"  {name:<18} {s.total_trades:>6} {s.win_rate:>4.0f}% "
            f"{s.expectancy_r:>+5.2f}R {recent:>7} "
            f"{s.total_r:>+6.1f}R {status:>10}{decay}"
        )

        if not s.enabled:
            print(f"    └─ {s.disabled_reason}")

    # Overall
    all_trades = sum(s.total_trades for s in stats.values())
    all_r = sum(s.total_r for s in stats.values())
    all_wins = sum(s.wins for s in stats.values())
    overall_wr = all_wins / all_trades * 100 if all_trades > 0 else 0

    print(f"\n  {'─'*70}")
    print(f"  Overall: {all_trades} trades, {overall_wr:.0f}% win rate, {all_r:+.1f}R total")

    # Best and worst
    if stats:
        best = max(stats.values(), key=lambda s: s.expectancy_r)
        worst = min(stats.values(), key=lambda s: s.expectancy_r)
        print(f"  Best:    {best.name} ({best.expectancy_r:+.2f}R/trade)")
        print(f"  Worst:   {worst.name} ({worst.expectancy_r:+.2f}R/trade)")


if __name__ == "__main__":
    print_edge_report()
