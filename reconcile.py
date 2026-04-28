"""
Alpaca Reconciliation

Compares local positions.json against Alpaca's actual positions via API.
When mismatches are found, auto-fixes local state to match the broker
(broker is always the source of truth) and logs every correction.

Run at the top of every orchestrator cycle before any trading logic.
"""

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from config import AgentConfig
from risk_manager import load_positions, save_positions, Position
from trade_tracker import log_trade, TRADES_FILE

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False

RECONCILE_LOG = Path(__file__).parent / "logs" / "reconcile.log"


def _log_correction(msg: str):
    """Append a timestamped correction to the reconcile log."""
    RECONCILE_LOG.parent.mkdir(exist_ok=True)
    with open(RECONCILE_LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def _get_recent_sell_fill(client, ticker: str, since_days: int = 7) -> dict | None:
    """Find the most recent SELL fill for a ticker so reconciler P&L matches reality.

    Returns {"fill_price", "qty", "filled_at"} or None if no fill found.
    """
    try:
        # Alpaca wants RFC3339 in UTC: '2006-01-02T15:04:05Z'
        after_dt = datetime.utcnow() - timedelta(days=since_days)
        after = after_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        orders = client.list_orders(
            status="closed",
            symbols=[ticker],
            after=after,
            limit=20,
            direction="desc",
        )
        for order in orders:
            if (
                order.side == "sell"
                and order.filled_qty
                and float(order.filled_qty) > 0
                and order.filled_avg_price
            ):
                return {
                    "fill_price": float(order.filled_avg_price),
                    "qty": int(float(order.filled_qty)),
                    "filled_at": getattr(order, "filled_at", None),
                }
        return None
    except Exception as e:
        print(f"  [RECONCILE] could not fetch sell fill for {ticker}: {e}")
        return None


def _get_original_buy_metadata(ticker: str) -> dict | None:
    """Look up the most recent BUY in trades.csv so re-added positions keep their
    original strategy/stop/target instead of being clobbered with defaults.
    """
    if not TRADES_FILE.exists():
        return None
    try:
        with open(TRADES_FILE) as f:
            reader = csv.DictReader(f)
            buys = [r for r in reader if r.get("ticker") == ticker and r.get("action") == "BUY"]
        if not buys:
            return None
        last = buys[-1]
        stop = float(last["stop_loss"]) if last.get("stop_loss") else None
        target = float(last["target"]) if last.get("target") else None
        return {
            "strategy": last.get("strategy") or "POWERX",
            "stop_loss": stop,
            "target": target,
            "entry_date": last["date"][:10] if last.get("date") else None,
        }
    except Exception as e:
        print(f"  [RECONCILE] could not read trades.csv for {ticker}: {e}")
        return None


def reconcile_with_broker(config: AgentConfig) -> bool:
    """Compare local state against Alpaca and auto-fix mismatches.

    The broker is the source of truth. Three mismatch types:
      1. At broker but not local → add to local state
      2. In local but not at broker → remove from local (broker closed it)
      3. Qty/price mismatch → update local to match broker

    Returns True if reconciliation succeeded (including after auto-fix).
    Returns False only if the Alpaca API is unreachable.
    """
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret or not HAS_ALPACA:
        print("  [RECONCILE] No Alpaca credentials — skipping reconciliation")
        return True

    try:
        client = tradeapi.REST(api_key, api_secret, config.alpaca_base_url, api_version="v2")
        broker_positions = client.list_positions()
        acct = client.get_account()
    except Exception as e:
        print(f"  [RECONCILE] Failed to query Alpaca: {e}")
        return False

    local_state = load_positions()

    broker_map = {}
    for bp in broker_positions:
        broker_map[bp.symbol] = {
            "qty": int(bp.qty),
            "avg_entry": float(bp.avg_entry_price),
            "current_price": float(bp.current_price),
            "market_value": float(bp.market_value),
        }

    local_map = {lp.ticker: lp for lp in local_state.positions}

    corrections = []
    new_positions = []
    cash_delta = 0.0  # net adjustment to local cash from corrections

    # Walk through all tickers from both sides
    all_tickers = set(broker_map.keys()) | set(local_map.keys())

    for ticker in sorted(all_tickers):
        broker = broker_map.get(ticker)
        local = local_map.get(ticker)

        if broker and not local:
            # Broker has it, we don't — add it to local state.
            # Try to recover original strategy/stop/target from trades.csv so we don't
            # clobber a real POWERX/PULLBACK signal with UNKNOWN_RECONCILED defaults.
            metadata = _get_original_buy_metadata(ticker)
            if metadata and metadata["stop_loss"] is not None:
                strategy = metadata["strategy"]
                stop_loss = metadata["stop_loss"]
                target = metadata["target"] or round(broker["avg_entry"] * 1.10, 2)
                entry_date = metadata["entry_date"] or datetime.now().strftime("%Y-%m-%d")
                source = f"recovered from trades.csv ({strategy})"
            else:
                strategy = "UNKNOWN_RECONCILED"
                stop_loss = round(broker["avg_entry"] * 0.95, 2)
                target = round(broker["avg_entry"] * 1.10, 2)
                entry_date = datetime.now().strftime("%Y-%m-%d")
                source = "no prior record; using defaults"
            msg = (
                f"ADDED {ticker}: {broker['qty']} sh @ ${broker['avg_entry']:.2f} "
                f"(was at broker but missing locally; {source})"
            )
            corrections.append(msg)
            cash_delta -= broker["qty"] * broker["avg_entry"]
            new_positions.append(Position(
                ticker=ticker,
                shares=broker["qty"],
                entry_price=broker["avg_entry"],
                current_price=broker["current_price"],
                stop_loss=stop_loss,
                initial_stop=stop_loss,
                target=target,
                strategy=strategy,
                entry_date=entry_date,
                high_water_mark=broker["current_price"],
            ))

        elif local and not broker:
            # We think we have it, but broker doesn't — it was closed (stop/target hit).
            # Query Alpaca for the actual sell fill so P&L and the audit trail match
            # what really happened, instead of estimating from the last cached price.
            fill = _get_recent_sell_fill(client, ticker)
            if fill:
                sell_price = fill["fill_price"]
                sell_qty = fill["qty"] or local.shares
                pnl = (sell_price - local.entry_price) * sell_qty
                cash_delta += sell_qty * sell_price
                msg = (
                    f"REMOVED {ticker}: {sell_qty} sh (broker sold @ ${sell_price:.2f}, "
                    f"P&L ${pnl:+.2f})"
                )
                outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")
                try:
                    log_trade(
                        ticker=ticker,
                        action="SELL",
                        shares=sell_qty,
                        price=sell_price,
                        strategy=local.strategy,
                        pnl=pnl,
                        outcome=outcome,
                        notes="Broker bracket exit (reconciled)",
                    )
                except Exception as e:
                    print(f"  [RECONCILE] sell logged in state but trades.csv write failed: {e}")
            else:
                # No fill found — fall back to old estimate so we still settle local state.
                pnl = (local.current_price - local.entry_price) * local.shares
                cash_delta += local.shares * local.current_price
                msg = (
                    f"REMOVED {ticker}: {local.shares} sh (broker closed it, fill not found, "
                    f"est P&L ${pnl:+.2f})"
                )
            corrections.append(msg)
            # Don't add to new_positions — it's gone

        elif broker and local:
            # Both have it — check for qty/price drift
            updated = False
            if broker["qty"] != local.shares:
                qty_diff = broker["qty"] - local.shares
                # Positive diff = broker bought more; debit local cash. Negative = partial sell; credit.
                cash_delta -= qty_diff * broker["avg_entry"]
                msg = f"FIXED {ticker} qty: local={local.shares} → broker={broker['qty']}"
                corrections.append(msg)
                local.shares = broker["qty"]
                updated = True
            if abs(broker["avg_entry"] - local.entry_price) > 0.50:
                msg = f"FIXED {ticker} entry: local=${local.entry_price:.2f} → broker=${broker['avg_entry']:.2f}"
                corrections.append(msg)
                local.entry_price = broker["avg_entry"]
                updated = True
            local.current_price = broker["current_price"]
            new_positions.append(local)

        # (if neither has it, nothing to do)

    # Always refresh current prices from broker (even without corrections)
    # so total_value reflects live quotes.
    def _recompute_total(state):
        positions_mv = sum(p.shares * p.current_price for p in state.positions)
        state.total_value = round(state.cash + positions_mv, 2)
        if state.total_value > state.peak_value:
            state.peak_value = state.total_value

    # Apply corrections
    if corrections:
        print(f"\n  [RECONCILE] AUTO-FIX at {datetime.now().strftime('%H:%M:%S')} — {len(corrections)} correction(s):")
        for c in corrections:
            print(f"    {c}")
            _log_correction(c)

        local_state.positions = new_positions
        # Adjust local cash by the net delta from the corrections above.
        # Do NOT pull from acct.cash/acct.portfolio_value — that would overwrite
        # the configured $10K-scale ledger with Alpaca's full paper-sandbox balance.
        local_state.cash = round(local_state.cash + cash_delta, 2)
        _recompute_total(local_state)
        save_positions(local_state)
        broker_equity = float(acct.portfolio_value)
        if broker_equity > local_state.total_value * 1.5:
            print(f"    [NOTE] Alpaca paper balance (${broker_equity:,.2f}) exceeds local "
                  f"ledger (${local_state.total_value:,.2f}). Sizing uses local ledger only.")
        print(f"    Saved: {len(new_positions)} positions, cash=${local_state.cash:,.2f}, total=${local_state.total_value:,.2f}")
    else:
        # No corrections needed — still update current prices and recompute total
        for ticker, local in local_map.items():
            if ticker in broker_map:
                local.current_price = broker_map[ticker]["current_price"]
        local_state.positions = list(local_map.values())
        _recompute_total(local_state)
        save_positions(local_state)
        print(f"  [RECONCILE] OK — {len(broker_map)} positions match between local and broker")

    return True


if __name__ == "__main__":
    config = AgentConfig()
    result = reconcile_with_broker(config)
    if result:
        print("\n  Reconciliation passed.")
    else:
        print("\n  Reconciliation FAILED — could not reach Alpaca API.")
