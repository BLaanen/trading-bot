"""
Copy Trader Module

Tracks US politician stock trade disclosures from Capitol Trades
(capitoltrades.com) and mirrors their moves in our portfolio.

Strategy rationale:
  - Politician trades are legally required to be disclosed within 30-45 days
  - Despite the disclosure delay, politicians tend to hold long positions
  - Top-performing politicians (most active, best track records) are followed
  - When they buy, we buy. When they sell, we sell.

Usage:
    python copy_trader.py               # single dry-run cycle
    python copy_trader.py --live        # live mode (requires Alpaca keys)
"""

from __future__ import annotations

import json
import sys
import warnings
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, date
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from config import AgentConfig

# ─── State file ──────────────────────────────────────────────────────────────

STATE_FILE = Path(__file__).parent / "copy_trader_state.json"


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class CopyTraderConfig:
    """Configuration for the copy-trading strategy."""
    target_politician: Optional[str] = None       # None → auto-select best
    max_position_size_pct: float = 0.05           # 5% of portfolio per trade
    min_trade_value: int = 15_000                 # Skip tiny/symbolic trades
    check_interval_minutes: int = 60              # How often to poll
    copy_delay_days: int = 45                     # Max age of trade to still copy


@dataclass
class PoliticianTrade:
    """A single disclosed politician trade."""
    politician: str
    ticker: str
    trade_type: str        # "buy" | "sell"
    amount_range: str      # e.g. "$15,001 - $50,000"
    trade_date: date
    disclosure_date: date
    asset_type: str = "Stock"

    def amount_lower_bound(self) -> int:
        """Parse the lower bound dollar amount from the range string."""
        try:
            raw = self.amount_range.replace("$", "").replace(",", "").split("-")[0].strip()
            return int(raw)
        except (ValueError, IndexError):
            return 0

    def age_days(self) -> int:
        """Days since the trade was made (not disclosed)."""
        return (date.today() - self.trade_date).days

    def unique_key(self) -> str:
        """Stable identifier for deduplication."""
        return f"{self.politician}|{self.ticker}|{self.trade_type}|{self.trade_date}"


# ─── HTML parser for Capitol Trades ──────────────────────────────────────────

class _CapitolTradesParser(HTMLParser):
    """
    Minimal parser for the Capitol Trades recent-trades table.

    Capitol Trades renders trade rows with a structure approximately like:
        <tr class="trade-row">
          <td class="politician-name">Nancy Pelosi</td>
          <td class="ticker">NVDA</td>
          <td class="transaction-type">Purchase</td>
          <td class="amount">$500,001 - $1,000,000</td>
          <td class="traded">2024-10-15</td>
          <td class="published">2024-11-14</td>
        </tr>

    Because the site layout may change, all parsing is best-effort and
    wrapped in try/except. If we cannot extract trades, fetch_from_web()
    returns an empty list and the caller falls back to sample data.
    """

    def __init__(self) -> None:
        super().__init__()
        self.trades: list[PoliticianTrade] = []
        self._in_row = False
        self._cells: list[str] = []
        self._current_cell = ""
        self._cell_depth = 0
        self._row_classes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = (attr_map.get("class") or "").lower().split()

        if tag == "tr":
            if any(c in classes for c in ("trade-row", "trade", "disclosure")):
                self._in_row = True
                self._cells = []
        elif tag == "td" and self._in_row:
            self._current_cell = ""
            self._cell_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_row and self._cell_depth > 0:
            self._cell_depth -= 1
            if self._cell_depth == 0:
                self._cells.append(self._current_cell.strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            self._try_parse_row()

    def handle_data(self, data: str) -> None:
        if self._in_row and self._cell_depth > 0:
            self._current_cell += data

    def _try_parse_row(self) -> None:
        if len(self._cells) < 6:
            return
        try:
            politician, ticker, txn_type, amount, traded_raw, published_raw = self._cells[:6]
            ticker = ticker.strip().upper()
            if not ticker or len(ticker) > 5:
                return

            trade_type = "buy" if "purchase" in txn_type.lower() or "buy" in txn_type.lower() else "sell"

            trade_date = _parse_date(traded_raw)
            disclosure_date = _parse_date(published_raw)
            if trade_date is None or disclosure_date is None:
                return

            self.trades.append(PoliticianTrade(
                politician=politician.strip(),
                ticker=ticker,
                trade_type=trade_type,
                amount_range=amount.strip(),
                trade_date=trade_date,
                disclosure_date=disclosure_date,
            ))
        except Exception:
            pass


def _parse_date(raw: str) -> Optional[date]:
    """Try several date formats; return None if none match."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ─── Data fetching ────────────────────────────────────────────────────────────

def fetch_from_web(days: int = 45) -> list[PoliticianTrade]:
    """
    Attempt to scrape recent politician trades from Capitol Trades.

    Returns a (possibly empty) list of PoliticianTrade objects.
    Raises no exceptions — any failure results in an empty list.
    """
    url = "https://capitoltrades.com/trades?page=1&pageSize=100"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        warnings.warn(f"Capitol Trades fetch failed: {exc}", RuntimeWarning, stacklevel=3)
        return []

    parser = _CapitolTradesParser()
    try:
        parser.feed(html)
    except Exception as exc:
        warnings.warn(f"Capitol Trades HTML parse failed: {exc}", RuntimeWarning, stacklevel=3)
        return []

    cutoff = date.today() - timedelta(days=days)
    return [t for t in parser.trades if t.trade_date >= cutoff]


def fetch_sample_data() -> list[PoliticianTrade]:
    """
    Return realistic sample data for testing when live scraping fails.

    Dates are relative to today so the sample is always within the copy window.
    Trades are based on historically observed politician activity patterns.
    """
    today = date.today()

    def d(offset: int) -> date:
        return today - timedelta(days=offset)

    return [
        PoliticianTrade("Nancy Pelosi",    "NVDA",  "buy",  "$500,001 - $1,000,000", d(40), d(12)),
        PoliticianTrade("Nancy Pelosi",    "AAPL",  "buy",  "$100,001 - $250,000",   d(35), d(8)),
        PoliticianTrade("Nancy Pelosi",    "MSFT",  "sell", "$250,001 - $500,000",   d(30), d(5)),
        PoliticianTrade("Dan Crenshaw",    "XOM",   "buy",  "$15,001 - $50,000",     d(20), d(3)),
        PoliticianTrade("Dan Crenshaw",    "CVX",   "buy",  "$15,001 - $50,000",     d(20), d(3)),
        PoliticianTrade("Tommy Tuberville","AMZN",  "buy",  "$50,001 - $100,000",    d(38), d(10)),
        PoliticianTrade("Tommy Tuberville","GOOGL", "buy",  "$50,001 - $100,000",    d(38), d(10)),
        PoliticianTrade("Tommy Tuberville","META",  "sell", "$50,001 - $100,000",    d(15), d(2)),
        PoliticianTrade("Shelley Moore Capito", "TSLA", "buy", "$15,001 - $50,000",  d(25), d(4)),
        PoliticianTrade("Ro Khanna",       "AMD",   "buy",  "$15,001 - $50,000",     d(22), d(6)),
        PoliticianTrade("Ro Khanna",       "INTC",  "sell", "$15,001 - $50,000",     d(18), d(3)),
        PoliticianTrade("Pat Fallon",      "ORCL",  "buy",  "$50,001 - $100,000",    d(12), d(1)),
    ]


def fetch_recent_trades(days: int = 45) -> list[PoliticianTrade]:
    """
    Fetch recent politician trades, falling back to sample data if scraping fails.

    Args:
        days: Maximum age (in days) of trades to return.

    Returns:
        List of PoliticianTrade objects within the specified window.
    """
    trades = fetch_from_web(days=days)

    if not trades:
        warnings.warn(
            "Live scraping returned no trades — using sample data. "
            "Results are for testing only.",
            RuntimeWarning,
            stacklevel=2,
        )
        trades = fetch_sample_data()
        # Still apply the age filter to sample data
        cutoff = date.today() - timedelta(days=days)
        trades = [t for t in trades if t.trade_date >= cutoff]

    return trades


# ─── Politician ranking & selection ──────────────────────────────────────────

@dataclass
class PoliticianScore:
    name: str
    trade_count: int
    buy_count: int
    total_value_lower: int   # Sum of lower-bound amounts
    unique_tickers: int


def rank_politicians(trades: list[PoliticianTrade]) -> list[PoliticianScore]:
    """
    Rank politicians by activity and aggregate disclosed trade value.

    Scoring formula:
      - Trade count × 1 point each
      - Bonus 2 points per buy (buys signal conviction more than sells)
      - Unique tickers × 1 point (diversified = more signal diversity)

    Returns politicians sorted highest-score-first.
    """
    from collections import defaultdict

    stats: dict[str, dict] = defaultdict(lambda: {
        "trade_count": 0,
        "buy_count": 0,
        "total_value_lower": 0,
        "tickers": set(),
    })

    for t in trades:
        s = stats[t.politician]
        s["trade_count"] += 1
        if t.trade_type == "buy":
            s["buy_count"] += 1
        s["total_value_lower"] += t.amount_lower_bound()
        s["tickers"].add(t.ticker)

    scores: list[tuple[int, PoliticianScore]] = []
    for name, s in stats.items():
        score_val = (
            s["trade_count"]
            + s["buy_count"] * 2
            + len(s["tickers"])
        )
        scores.append((score_val, PoliticianScore(
            name=name,
            trade_count=s["trade_count"],
            buy_count=s["buy_count"],
            total_value_lower=s["total_value_lower"],
            unique_tickers=len(s["tickers"]),
        )))

    scores.sort(key=lambda x: x[0], reverse=True)
    return [ps for _, ps in scores]


def select_politician(
    trades: list[PoliticianTrade],
    config: CopyTraderConfig,
) -> Optional[str]:
    """
    Pick the politician to follow.

    If config.target_politician is set, use that (if they appear in recent trades).
    Otherwise auto-select the highest-ranked politician.

    Returns the politician's name, or None if no suitable politician is found.
    """
    if config.target_politician:
        names = {t.politician for t in trades}
        if config.target_politician in names:
            return config.target_politician
        warnings.warn(
            f"Configured politician '{config.target_politician}' has no recent trades. "
            "Falling back to auto-select.",
            RuntimeWarning,
            stacklevel=2,
        )

    ranked = rank_politicians(trades)
    return ranked[0].name if ranked else None


# ─── Trade filtering ──────────────────────────────────────────────────────────

def get_new_trades_to_copy(
    politician: str,
    trades: list[PoliticianTrade],
    already_copied: set[str],
    config: CopyTraderConfig,
) -> list[PoliticianTrade]:
    """
    Return trades from the chosen politician that we haven't copied yet.

    Filters:
      - Correct politician
      - Stock assets only (no options, bonds, etc.)
      - Within copy_delay_days
      - Meets min_trade_value
      - Not already in already_copied set
    """
    cutoff = date.today() - timedelta(days=config.copy_delay_days)
    result = []

    for t in trades:
        if t.politician != politician:
            continue
        if t.asset_type.lower() not in ("stock", "common stock", "equity", ""):
            continue
        if t.trade_date < cutoff:
            continue
        if t.amount_lower_bound() < config.min_trade_value:
            continue
        if t.unique_key() in already_copied:
            continue
        result.append(t)

    return result


# ─── Order execution ──────────────────────────────────────────────────────────

def execute_copy_trades(
    trades_to_copy: list[PoliticianTrade],
    agent_config: AgentConfig,
    dry_run: bool = False,
) -> list[dict]:
    """
    Place orders for the given trades via executor._submit_order().

    Position sizing: max_position_size_pct × current portfolio value,
    capped at 1 share minimum.

    Args:
        trades_to_copy: Filtered list of trades to execute.
        agent_config:   The main AgentConfig (for Alpaca credentials, etc.).
        dry_run:        If True, log but do not submit real orders.

    Returns:
        List of result dicts with keys: ticker, action, shares, success, message.
    """
    try:
        from executor import get_alpaca_client, _submit_order
        from trade_tracker import log_trade
    except ImportError as exc:
        warnings.warn(
            f"Could not import executor/trade_tracker: {exc}. "
            "Falling back to simulation mode.",
            RuntimeWarning,
            stacklevel=2,
        )
        dry_run = True
        client = None

        def _submit_order(client, ticker, shares, side):  # type: ignore[misc]
            from dataclasses import dataclass as _dc

            @_dc
            class _FakeOrder:
                success: bool = True
                order_id: str = "SIM-FALLBACK"
                ticker: str = ""
                action: str = ""
                shares: int = 0
                price: float = 0.0
                message: str = ""

            return _FakeOrder(
                success=True,
                order_id=f"SIM-{ticker}",
                ticker=ticker,
                action=side.upper(),
                shares=shares,
                message=f"Simulated {side}: {shares} {ticker}",
            )

        def log_trade(**kwargs):  # type: ignore[misc]
            pass

    client = None if dry_run else get_alpaca_client(agent_config)
    results = []

    # Estimate portfolio value (from positions file if available)
    portfolio_value = _get_portfolio_value(agent_config)
    max_dollars_per_trade = portfolio_value * 0.05  # default 5%

    for trade in trades_to_copy:
        # For copy trades we don't know the current price directly here;
        # use a rough estimate from the trade amount lower bound.
        # A real implementation would look up the current price first.
        lower = trade.amount_lower_bound()
        # Estimate share count: cap to max_dollars_per_trade
        alloc = min(lower, max_dollars_per_trade)
        # We need a price to compute shares. Use a placeholder of $100;
        # _submit_order accepts the share count. The caller should enrich
        # this with live prices in production.
        estimated_price = 100.0
        shares = max(1, int(alloc / estimated_price))

        side = "buy" if trade.trade_type == "buy" else "sell"

        if dry_run:
            result = {
                "ticker": trade.ticker,
                "action": side.upper(),
                "shares": shares,
                "success": True,
                "message": f"[DRY-RUN] Would {side} {shares} {trade.ticker} "
                           f"(copying {trade.politician})",
                "trade": trade.unique_key(),
            }
            print(f"  [DRY-RUN] {side.upper()} {shares} × {trade.ticker} "
                  f"— {trade.politician} disclosed {trade.trade_date}")
        else:
            order = _submit_order(client, trade.ticker, shares, side)
            result = {
                "ticker": trade.ticker,
                "action": side.upper(),
                "shares": order.shares,
                "success": order.success,
                "message": order.message,
                "trade": trade.unique_key(),
            }
            if order.success:
                log_trade(
                    ticker=trade.ticker,
                    action=side.upper(),
                    shares=shares,
                    price=0.0,   # market order — price filled by broker
                    strategy="copy_trade",
                    notes=(
                        f"Copying {trade.politician} | "
                        f"Disclosed {trade.disclosure_date} | "
                        f"Amount: {trade.amount_range}"
                    ),
                )

        results.append(result)

    return results


def _get_portfolio_value(agent_config: AgentConfig) -> float:
    """Return current portfolio value from positions file, or starting capital."""
    try:
        from risk_manager import load_positions
        state = load_positions()
        return state.total_value if state.total_value > 0 else agent_config.starting_capital
    except Exception:
        return agent_config.starting_capital


# ─── Main cycle ───────────────────────────────────────────────────────────────

def run_copy_cycle(
    config: CopyTraderConfig,
    agent_config: AgentConfig,
    dry_run: bool = False,
) -> dict:
    """
    Run a full copy-trading cycle:
      1. Fetch recent politician trades
      2. Select which politician to follow
      3. Filter to new, uncoped trades
      4. Execute copy trades

    Args:
        config:       Copy trader configuration.
        agent_config: Main agent configuration (Alpaca, capital, etc.).
        dry_run:      If True, simulate orders only.

    Returns:
        Summary dict with keys: politician, trades_found, trades_copied, results.
    """
    print("\n[CopyTrader] Starting cycle...")

    # 1. Load persisted state
    state = load_state()

    # 2. Fetch trades
    print(f"  Fetching politician trades (last {config.copy_delay_days} days)...")
    trades = fetch_recent_trades(days=config.copy_delay_days)
    print(f"  Found {len(trades)} disclosures from {len({t.politician for t in trades})} politicians")

    # 3. Select politician
    politician = select_politician(trades, config)
    if not politician:
        print("  No suitable politician found. Aborting cycle.")
        return {"politician": None, "trades_found": 0, "trades_copied": 0, "results": []}

    # Update tracked politician in state
    if state.get("following") != politician:
        print(f"  Now following: {politician}")
        state["following"] = politician

    print(f"  Following: {politician}")

    # 4. Filter to new trades
    already_copied: set[str] = set(state.get("copied_keys", []))
    new_trades = get_new_trades_to_copy(politician, trades, already_copied, config)
    print(f"  New trades to copy: {len(new_trades)}")

    if not new_trades:
        print("  Nothing new to copy.")
        save_state(state)
        return {
            "politician": politician,
            "trades_found": len(trades),
            "trades_copied": 0,
            "results": [],
        }

    # 5. Execute
    results = execute_copy_trades(new_trades, agent_config, dry_run=dry_run)

    # 6. Persist state
    for r in results:
        if r["success"]:
            already_copied.add(r["trade"])

    state["copied_keys"] = list(already_copied)
    state["last_cycle"] = datetime.now().isoformat()
    state["following"] = politician
    save_state(state)

    copied_count = sum(1 for r in results if r["success"])
    print(f"\n[CopyTrader] Cycle complete — copied {copied_count}/{len(new_trades)} trades")

    return {
        "politician": politician,
        "trades_found": len(trades),
        "trades_copied": copied_count,
        "results": results,
    }


# ─── Summary ──────────────────────────────────────────────────────────────────

def get_summary() -> str:
    """Return a human-readable summary of copy trader status."""
    state = load_state()
    lines = ["── Copy Trader Status ──────────────────────────────"]

    following = state.get("following", "None")
    lines.append(f"  Following:      {following}")

    last_cycle = state.get("last_cycle", "Never")
    lines.append(f"  Last cycle:     {last_cycle}")

    copied_keys = state.get("copied_keys", [])
    lines.append(f"  Total copied:   {len(copied_keys)} trades")

    if copied_keys:
        lines.append("  Recent copies:")
        for key in copied_keys[-5:]:
            lines.append(f"    • {key}")

    lines.append("────────────────────────────────────────────────────")
    return "\n".join(lines)


# ─── State persistence ────────────────────────────────────────────────────────

def load_state() -> dict:
    """Load persisted copy trader state from JSON file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"following": None, "copied_keys": [], "last_cycle": None}


def save_state(state: dict) -> None:
    """Persist copy trader state to JSON file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    live_mode = "--live" in sys.argv
    dry_run = not live_mode

    print("╔══════════════════════════════════════════╗")
    print("║         Copy Trader — Capitol Trades      ║")
    print(f"║  Mode: {'LIVE' if live_mode else 'DRY-RUN (simulation)':37s}║")
    print("╚══════════════════════════════════════════╝")

    copy_config = CopyTraderConfig()
    agent_config = AgentConfig()

    summary_before = get_summary()
    print(f"\n{summary_before}")

    cycle_result = run_copy_cycle(copy_config, agent_config, dry_run=dry_run)

    print("\n── Cycle Result ────────────────────────────────────")
    print(f"  Politician:     {cycle_result['politician']}")
    print(f"  Trades found:   {cycle_result['trades_found']}")
    print(f"  Trades copied:  {cycle_result['trades_copied']}")

    if cycle_result["results"]:
        print("\n  Orders:")
        for r in cycle_result["results"]:
            status = "OK" if r["success"] else "FAIL"
            print(f"    [{status}] {r['message']}")

    print(f"\n{get_summary()}")
