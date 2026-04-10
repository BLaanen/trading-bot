"""
scheduler.py — Market Hours Scheduler

Runs trading strategy callbacks on configurable intervals, respecting
US market hours. Supports both run_once() (external cron) and run_loop()
(standalone daemon) execution modes.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")

ET = ZoneInfo("US/Eastern")
STATE_FILE = Path(__file__).parent / "scheduler_state.json"


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ScheduleConfig:
    """Configuration for a recurring scheduled task."""

    name: str
    callback: Callable
    interval_minutes: int
    market_hours_only: bool = True
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon–Fri


# ── MarketHours ───────────────────────────────────────────────────────────────

class MarketHours:
    """Utility class for US Eastern market-hours logic."""

    MARKET_OPEN = (9, 30)    # 9:30 AM ET
    MARKET_CLOSE = (16, 0)   # 4:00 PM ET
    PREMARKET_OPEN = (4, 0)  # 4:00 AM ET
    AFTERHOURS_CLOSE = (20, 0)  # 8:00 PM ET

    @staticmethod
    def _now_et() -> datetime:
        return datetime.now(tz=ET)

    @classmethod
    def is_market_day(cls, dt: Optional[datetime] = None) -> bool:
        """Returns True if the given date (default: now) is a weekday (Mon–Fri).

        Note: does not account for US holidays — use a calendar library for that.
        """
        dt = dt or cls._now_et()
        return dt.weekday() < 5

    @classmethod
    def is_market_open(cls, dt: Optional[datetime] = None) -> bool:
        """Returns True if US equity market is currently open (9:30–16:00 ET)."""
        dt = dt or cls._now_et()
        if not cls.is_market_day(dt):
            return False
        t = (dt.hour, dt.minute)
        return cls.MARKET_OPEN <= t < cls.MARKET_CLOSE

    @classmethod
    def is_premarket(cls, dt: Optional[datetime] = None) -> bool:
        """Returns True if currently in pre-market hours (4:00–9:30 AM ET)."""
        dt = dt or cls._now_et()
        if not cls.is_market_day(dt):
            return False
        t = (dt.hour, dt.minute)
        return cls.PREMARKET_OPEN <= t < cls.MARKET_OPEN

    @classmethod
    def is_afterhours(cls, dt: Optional[datetime] = None) -> bool:
        """Returns True if currently in after-hours trading (16:00–20:00 ET)."""
        dt = dt or cls._now_et()
        if not cls.is_market_day(dt):
            return False
        t = (dt.hour, dt.minute)
        return cls.MARKET_CLOSE <= t < cls.AFTERHOURS_CLOSE

    @classmethod
    def next_open(cls, dt: Optional[datetime] = None) -> datetime:
        """Returns the next market open as a timezone-aware datetime (ET)."""
        dt = dt or cls._now_et()
        candidate = dt.replace(hour=cls.MARKET_OPEN[0], minute=cls.MARKET_OPEN[1], second=0, microsecond=0)
        # If we're already past open today, move to tomorrow
        if dt >= candidate:
            candidate += timedelta(days=1)
        # Skip to next weekday
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate


# ── Schedule entry (internal state) ──────────────────────────────────────────

@dataclass
class _ScheduleEntry:
    config: ScheduleConfig
    last_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None


# ── Scheduler ────────────────────────────────────────────────────────────────

class Scheduler:
    """
    Manages a set of recurring scheduled callbacks with market-hours awareness.

    Usage (standalone loop)::

        scheduler = Scheduler()
        scheduler.add_schedule(ScheduleConfig("my_task", my_fn, interval_minutes=5))
        scheduler.run_loop()

    Usage (external cron, call every minute)::

        scheduler = Scheduler()
        scheduler.add_schedule(...)
        scheduler.run_once()
    """

    def __init__(self) -> None:
        self._entries: dict[str, _ScheduleEntry] = {}
        self._daily_log: list[dict] = []
        self._load_state()

    # ── Registration ─────────────────────────────────────────────────────────

    def add_schedule(self, config: ScheduleConfig) -> None:
        """Register a recurring task."""
        if config.name in self._entries:
            logger.warning("Schedule '%s' already exists — replacing.", config.name)
        self._entries[config.name] = _ScheduleEntry(config=config)
        logger.info("Registered schedule '%s' (every %d min, market_hours_only=%s)",
                    config.name, config.interval_minutes, config.market_hours_only)

    def remove_schedule(self, name: str) -> None:
        """Unregister a scheduled task by name."""
        if name in self._entries:
            del self._entries[name]
            logger.info("Removed schedule '%s'.", name)
        else:
            logger.warning("remove_schedule: '%s' not found.", name)

    # ── Execution ─────────────────────────────────────────────────────────────

    def run_once(self) -> None:
        """
        Check all schedules and execute any that are due right now.

        Suitable for external cron — call once per minute.
        """
        now_et = datetime.now(tz=ET)
        mh = MarketHours()

        for name, entry in self._entries.items():
            if not self._is_due(entry, now_et, mh):
                continue
            logger.info("Running schedule '%s'…", name)
            try:
                entry.config.callback()
                entry.last_run = now_et
                entry.run_count += 1
                self._daily_log.append({
                    "name": name,
                    "ts": now_et.isoformat(),
                    "status": "ok",
                })
                logger.info("Schedule '%s' completed successfully.", name)
            except Exception:
                tb = traceback.format_exc()
                entry.error_count += 1
                entry.last_error = tb
                self._daily_log.append({
                    "name": name,
                    "ts": now_et.isoformat(),
                    "status": "error",
                    "error": tb,
                })
                logger.error("Schedule '%s' raised an exception:\n%s", name, tb)

        self._save_state()

    def run_loop(self, check_interval: int = 60) -> None:
        """
        Blocking loop that checks schedules continuously.

        Args:
            check_interval: Seconds between schedule checks (default 60).
        """
        logger.info("Scheduler loop started (check_interval=%ds).", check_interval)
        while True:
            self.run_once()
            time.sleep(check_interval)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, dict]:
        """
        Returns a dict of schedule names → status info.

        Keys per entry: last_run, next_run, run_count, error_count, last_error.
        """
        now_et = datetime.now(tz=ET)
        result = {}
        for name, entry in self._entries.items():
            next_run = self._compute_next_run(entry, now_et)
            result[name] = {
                "last_run": entry.last_run.isoformat() if entry.last_run else None,
                "next_run": next_run.isoformat() if next_run else "unknown",
                "run_count": entry.run_count,
                "error_count": entry.error_count,
                "last_error": entry.last_error,
                "interval_minutes": entry.config.interval_minutes,
                "market_hours_only": entry.config.market_hours_only,
            }
        return result

    def generate_daily_summary(self) -> str:
        """Generates a text summary of all schedule activity for today."""
        lines = [
            f"=== Scheduler Daily Summary — {datetime.now(tz=ET).date()} ===",
            "",
        ]
        status = self.get_status()
        for name, info in status.items():
            lines.append(f"[{name}]")
            lines.append(f"  Runs today   : {info['run_count']}")
            lines.append(f"  Errors today : {info['error_count']}")
            lines.append(f"  Last run     : {info['last_run'] or 'never'}")
            if info["last_error"]:
                lines.append(f"  Last error   : {info['last_error'][:200]}")
            lines.append("")

        lines.append(f"Total events logged: {len(self._daily_log)}")
        summary = "\n".join(lines)
        logger.info("Daily summary generated.")
        return summary

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_due(self, entry: _ScheduleEntry, now_et: datetime, mh: MarketHours) -> bool:
        """Returns True if a schedule entry should run right now."""
        cfg = entry.config

        # Day-of-week filter
        if now_et.weekday() not in cfg.days:
            return False

        # Market-hours gate
        if cfg.market_hours_only and not mh.is_market_open(now_et):
            return False

        # Special case: fixed daily-close schedule (4:05 PM ET)
        # Detected by interval_minutes == 0 (sentinel) — we use 1-minute window
        if cfg.interval_minutes == 0:
            target = now_et.replace(hour=16, minute=5, second=0, microsecond=0)
            window_start = target - timedelta(seconds=30)
            window_end = target + timedelta(seconds=30)
            if not (window_start <= now_et <= window_end):
                return False
            # Only run once per day
            if entry.last_run and entry.last_run.date() == now_et.date():
                return False
            return True

        # Interval-based check
        if entry.last_run is None:
            return True  # Never run — run now if other conditions pass
        elapsed = (now_et - entry.last_run).total_seconds() / 60.0
        return elapsed >= cfg.interval_minutes

    def _compute_next_run(self, entry: _ScheduleEntry, now_et: datetime) -> Optional[datetime]:
        """Estimate the next scheduled run time."""
        if entry.config.interval_minutes == 0:
            target = now_et.replace(hour=16, minute=5, second=0, microsecond=0)
            if now_et > target:
                target += timedelta(days=1)
            return target
        if entry.last_run is None:
            return now_et
        return entry.last_run + timedelta(minutes=entry.config.interval_minutes)

    # ── State persistence ─────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persist schedule run-state to disk."""
        state: dict = {}
        for name, entry in self._entries.items():
            state[name] = {
                "last_run": entry.last_run.isoformat() if entry.last_run else None,
                "run_count": entry.run_count,
                "error_count": entry.error_count,
            }
        state["_daily_log"] = self._daily_log[-500:]  # Keep last 500 events
        try:
            STATE_FILE.write_text(json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("Could not save scheduler state: %s", exc)

    def _load_state(self) -> None:
        """Restore schedule run-state from disk (best-effort)."""
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text())
            self._persisted_state = raw
            self._daily_log = raw.get("_daily_log", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load scheduler state: %s", exc)
            self._persisted_state = {}

    def _apply_persisted_state(self, name: str, entry: _ScheduleEntry) -> None:
        """Apply saved state to a newly registered entry (call after add_schedule)."""
        saved = getattr(self, "_persisted_state", {}).get(name)
        if not saved:
            return
        if saved.get("last_run"):
            entry.last_run = datetime.fromisoformat(saved["last_run"])
        entry.run_count = saved.get("run_count", 0)
        entry.error_count = saved.get("error_count", 0)


# ── __main__ demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    def _stub(name: str) -> Callable:
        def _fn():
            logger.info("[stub] %s executed.", name)
        _fn.__name__ = name
        return _fn

    scheduler = Scheduler()

    scheduler.add_schedule(ScheduleConfig(
        name="trailing_monitor",
        callback=_stub("trailing_monitor"),
        interval_minutes=5,
        market_hours_only=True,
    ))
    scheduler.add_schedule(ScheduleConfig(
        name="copy_trader_check",
        callback=_stub("copy_trader_check"),
        interval_minutes=60,
        market_hours_only=True,
    ))
    scheduler.add_schedule(ScheduleConfig(
        name="wheel_check",
        callback=_stub("wheel_check"),
        interval_minutes=15,
        market_hours_only=True,
    ))
    scheduler.add_schedule(ScheduleConfig(
        name="daily_report",
        callback=_stub("daily_report"),
        interval_minutes=0,       # Sentinel → fixed 4:05 PM ET
        market_hours_only=False,  # Runs just after close
    ))
    scheduler.add_schedule(ScheduleConfig(
        name="full_pipeline",
        callback=_stub("full_pipeline"),
        interval_minutes=240,     # 4 hours
        market_hours_only=True,
    ))

    print("=== Schedule Status ===")
    for sched_name, info in scheduler.get_status().items():
        print(f"  {sched_name}: next_run={info['next_run']}")

    if "--loop" in sys.argv:
        scheduler.run_loop()
    else:
        print("\nRunning run_once() check…")
        scheduler.run_once()
        print(scheduler.generate_daily_summary())
