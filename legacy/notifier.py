"""
notifier.py — Notification System

Pluggable multi-backend notification dispatcher for the trading bot.
Supports console output, file logging, Telegram, and daily markdown summaries.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

# ── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("notifier")

ET = ZoneInfo("US/Eastern")
NOTIFICATIONS_LOG = Path(__file__).parent / "notifications.log"
DAILY_SUMMARIES_DIR = Path(__file__).parent / "daily_summaries"

# ANSI color codes for console output
_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "blue": "\033[34m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "green": "\033[32m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
}


# ── Enums & Dataclasses ───────────────────────────────────────────────────────

class NotificationLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"
    TRADE = "TRADE"
    SUMMARY = "SUMMARY"


@dataclass
class Notification:
    """A single notification event."""

    level: NotificationLevel
    title: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=ET))
    data: Optional[dict[str, Any]] = None

    def format_text(self, include_data: bool = False) -> str:
        """Return a plain-text representation of this notification."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
        lines = [f"[{self.level.value}] {ts} — {self.title}", f"  {self.message}"]
        if include_data and self.data:
            for k, v in self.data.items():
                lines.append(f"    {k}: {v}")
        return "\n".join(lines)


# ── Backend Implementations ───────────────────────────────────────────────────

class _Backend:
    """Abstract base for notification backends."""

    def send(self, notification: Notification) -> None:
        raise NotImplementedError


class ConsoleNotifier(_Backend):
    """Prints notifications to stdout with ANSI color formatting."""

    _LEVEL_COLORS: dict[NotificationLevel, str] = {
        NotificationLevel.INFO: "blue",
        NotificationLevel.WARNING: "yellow",
        NotificationLevel.ALERT: "red",
        NotificationLevel.TRADE: "green",
        NotificationLevel.SUMMARY: "cyan",
    }

    def send(self, notification: Notification) -> None:
        color_key = self._LEVEL_COLORS.get(notification.level, "reset")
        c = _COLORS.get(color_key, "")
        reset = _COLORS["reset"]
        bold = _COLORS["bold"]
        ts = notification.timestamp.strftime("%H:%M:%S")
        badge = f"{c}{bold}[{notification.level.value}]{reset}"
        print(f"{badge} {ts} {bold}{notification.title}{reset}")
        print(f"  {notification.message}")
        if notification.data:
            for k, v in notification.data.items():
                print(f"  {_COLORS['cyan']}{k}{reset}: {v}")
        print()


class FileNotifier(_Backend):
    """Appends notifications to a flat log file."""

    def __init__(self, log_path: Path = NOTIFICATIONS_LOG) -> None:
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, notification: Notification) -> None:
        line = notification.format_text(include_data=True)
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n" + ("-" * 60) + "\n")
        except OSError as exc:
            logger.warning("FileNotifier: could not write to %s: %s", self._path, exc)


class TelegramNotifier(_Backend):
    """
    Sends notifications via Telegram Bot API.

    Requires env vars:
      TELEGRAM_BOT_TOKEN — bot token from @BotFather
      TELEGRAM_CHAT_ID   — target chat/channel ID

    Falls back to a warning log if either var is missing.
    """

    def __init__(self) -> None:
        self._token = os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self._token or not self._chat_id:
            logger.warning(
                "TelegramNotifier: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. "
                "Telegram notifications will be silently dropped."
            )

    def send(self, notification: Notification) -> None:
        if not self._token or not self._chat_id:
            return

        text = (
            f"*[{notification.level.value}]* {notification.title}\n"
            f"{notification.message}"
        )
        if notification.data:
            extras = "\n".join(f"• `{k}`: {v}" for k, v in notification.data.items())
            text += f"\n\n{extras}"

        try:
            import urllib.request
            import urllib.parse
            import json as _json

            payload = _json.dumps({
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode()
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning("TelegramNotifier: HTTP %d", resp.status)
        except Exception as exc:
            logger.warning("TelegramNotifier: failed to send — %s", exc)


class DailySummaryNotifier(_Backend):
    """
    Collects all notifications for the day and writes a markdown summary
    to daily_summaries/YYYY-MM-DD.md when generate_daily_summary() is called.
    """

    def __init__(self, summaries_dir: Path = DAILY_SUMMARIES_DIR) -> None:
        self._dir = summaries_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._buffer: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self._buffer.append(notification)

    def flush(self) -> Path:
        """Write buffered notifications to today's markdown summary file."""
        today = datetime.now(tz=ET).date()
        out_path = self._dir / f"{today}.md"

        lines = [
            f"# Trading Notifications — {today}",
            "",
            f"Generated: {datetime.now(tz=ET).strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
        ]

        # Group by level
        by_level: dict[NotificationLevel, list[Notification]] = {
            lvl: [] for lvl in NotificationLevel
        }
        for n in self._buffer:
            by_level[n.level].append(n)

        for lvl in NotificationLevel:
            items = by_level[lvl]
            if not items:
                continue
            lines.append(f"## {lvl.value} ({len(items)})")
            lines.append("")
            for n in items:
                ts = n.timestamp.strftime("%H:%M:%S")
                lines.append(f"### {ts} — {n.title}")
                lines.append(f"{n.message}")
                if n.data:
                    lines.append("")
                    for k, v in n.data.items():
                        lines.append(f"- **{k}**: {v}")
                lines.append("")

        try:
            out_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("DailySummaryNotifier: wrote %s", out_path)
        except OSError as exc:
            logger.warning("DailySummaryNotifier: could not write %s: %s", out_path, exc)

        return out_path


# ── Notifier (facade) ─────────────────────────────────────────────────────────

class Notifier:
    """
    Facade that dispatches notifications to all registered backends.

    Instantiate directly or use get_notifier() for the process singleton.
    """

    def __init__(self, backends: Optional[list[_Backend]] = None) -> None:
        self._backends: list[_Backend] = backends or [
            ConsoleNotifier(),
            FileNotifier(),
        ]
        # Keep a reference to DailySummaryNotifier if present (for flush)
        self._daily: Optional[DailySummaryNotifier] = next(
            (b for b in self._backends if isinstance(b, DailySummaryNotifier)), None
        )

    def add_backend(self, backend: _Backend) -> None:
        """Add a notification backend at runtime."""
        self._backends.append(backend)
        if isinstance(backend, DailySummaryNotifier):
            self._daily = backend

    # ── Core dispatch ─────────────────────────────────────────────────────────

    def notify(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Send a notification to all configured backends."""
        n = Notification(level=level, title=title, message=message, data=data)
        for backend in self._backends:
            try:
                backend.send(n)
            except Exception as exc:
                logger.error("Backend %s failed: %s", type(backend).__name__, exc)

    # ── Convenience methods ───────────────────────────────────────────────────

    def notify_trade(
        self,
        action: str,
        ticker: str,
        shares: float,
        price: float,
        reason: str,
    ) -> None:
        """Convenience method for trade execution notifications."""
        value = shares * price
        self.notify(
            level=NotificationLevel.TRADE,
            title=f"{action.upper()} {ticker}",
            message=reason,
            data={
                "action": action,
                "ticker": ticker,
                "shares": shares,
                "price": f"${price:.2f}",
                "value": f"${value:,.2f}",
            },
        )

    def notify_alert(self, title: str, message: str) -> None:
        """Convenience method for alert-level notifications."""
        self.notify(level=NotificationLevel.ALERT, title=title, message=message)

    def generate_daily_summary(self) -> Optional[Path]:
        """
        Flush the DailySummaryNotifier buffer to a markdown file.

        Returns the path to the written file, or None if not configured.
        """
        if self._daily:
            return self._daily.flush()
        logger.warning("generate_daily_summary: DailySummaryNotifier not configured.")
        return None


# ── Singleton factory ─────────────────────────────────────────────────────────

_SINGLETON: Optional[Notifier] = None


def get_notifier() -> Notifier:
    """
    Return the process-level Notifier singleton.

    On first call, builds a default Notifier with Console + File + DailySummary
    backends. Add Telegram by setting TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
    env vars before the first call, or call get_notifier().add_backend(TelegramNotifier()).
    """
    global _SINGLETON
    if _SINGLETON is None:
        backends: list[_Backend] = [
            ConsoleNotifier(),
            FileNotifier(),
            DailySummaryNotifier(),
        ]
        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            backends.append(TelegramNotifier())
        _SINGLETON = Notifier(backends=backends)
        logger.info("Notifier singleton created with %d backends.", len(backends))
    return _SINGLETON


# ── Module-level convenience aliases ─────────────────────────────────────────

def notify(
    level: NotificationLevel,
    title: str,
    message: str,
    data: Optional[dict[str, Any]] = None,
) -> None:
    """Module-level shortcut — delegates to the singleton Notifier."""
    get_notifier().notify(level, title, message, data)


def notify_trade(
    action: str,
    ticker: str,
    shares: float,
    price: float,
    reason: str,
) -> None:
    """Module-level shortcut for trade notifications."""
    get_notifier().notify_trade(action, ticker, shares, price, reason)


def notify_alert(title: str, message: str) -> None:
    """Module-level shortcut for alert notifications."""
    get_notifier().notify_alert(title, message)


def generate_daily_summary() -> Optional[Path]:
    """Module-level shortcut — generates and writes the daily summary."""
    return get_notifier().generate_daily_summary()


# ── __main__ demo ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    n = get_notifier()

    n.notify(NotificationLevel.INFO, "Bot started", "Trading bot initialised and ready.")

    n.notify(NotificationLevel.WARNING, "Low volume detected",
             "AAPL volume is 30% below 20-day average — signals may be unreliable.",
             data={"ticker": "AAPL", "volume_ratio": 0.70})

    n.notify_alert("Risk limit approaching",
                   "Current portfolio heat at 5.2% — approaching 6% cap.")

    n.notify_trade(
        action="BUY",
        ticker="NVDA",
        shares=10,
        price=875.50,
        reason="Momentum breakout above 20-day high; R:R = 2.8",
    )

    n.notify_trade(
        action="SELL",
        ticker="NVDA",
        shares=5,
        price=910.00,
        reason="Partial exit at +2R; trailing stop raised to breakeven.",
    )

    n.notify(NotificationLevel.SUMMARY, "End-of-day report",
             "Pipeline completed. 3 trades executed, net P&L: +$312.",
             data={"trades": 3, "winners": 2, "losers": 1, "pnl": "$312"})

    summary_path = n.generate_daily_summary()
    if summary_path:
        print(f"\nDaily summary written to: {summary_path}")
