"""
Alpaca Reconciliation

Compares local positions.json against Alpaca's actual positions via API.
When mismatches are found, auto-fixes local state to match the broker
(broker is always the source of truth) and logs every correction.

Run at the top of every orchestrator cycle before any trading logic.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from config import AgentConfig
from risk_manager import load_positions, save_positions, Position

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

    # Walk through all tickers from both sides
    all_tickers = set(broker_map.keys()) | set(local_map.keys())

    for ticker in sorted(all_tickers):
        broker = broker_map.get(ticker)
        local = local_map.get(ticker)

        if broker and not local:
            # Broker has it, we don't — add it to local state
            msg = f"ADDED {ticker}: {broker['qty']} shares @ ${broker['avg_entry']:.2f} (was at broker but missing locally)"
            corrections.append(msg)
            new_positions.append(Position(
                ticker=ticker,
                shares=broker["qty"],
                entry_price=broker["avg_entry"],
                current_price=broker["current_price"],
                stop_loss=0,  # Unknown — will need manual review or next monitor cycle
                initial_stop=0,
                target=0,
                strategy="UNKNOWN_RECONCILED",
                entry_date=datetime.now().strftime("%Y-%m-%d"),
                high_water_mark=broker["current_price"],
            ))

        elif local and not broker:
            # We think we have it, but broker doesn't — it was closed (stop/target hit)
            pnl = (local.current_price - local.entry_price) * local.shares
            msg = f"REMOVED {ticker}: {local.shares} shares (broker closed it, est P&L ${pnl:.2f})"
            corrections.append(msg)
            # Reclaim the cash from the closed position
            local_state.cash += local.current_price * local.shares
            # Don't add to new_positions — it's gone

        elif broker and local:
            # Both have it — check for qty/price drift
            updated = False
            if broker["qty"] != local.shares:
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

    # Apply corrections
    if corrections:
        print(f"\n  [RECONCILE] AUTO-FIX at {datetime.now().strftime('%H:%M:%S')} — {len(corrections)} correction(s):")
        for c in corrections:
            print(f"    {c}")
            _log_correction(c)

        local_state.positions = new_positions
        # Recalculate total value
        invested = sum(p.current_price * p.shares for p in new_positions)
        local_state.total_value = local_state.cash + invested
        if local_state.total_value > local_state.peak_value:
            local_state.peak_value = local_state.total_value
        save_positions(local_state)
        print(f"    Saved: {len(new_positions)} positions, cash=${local_state.cash:,.2f}, total=${local_state.total_value:,.2f}")
    else:
        # No corrections needed — still update current prices
        for ticker, local in local_map.items():
            if ticker in broker_map:
                local.current_price = broker_map[ticker]["current_price"]
        local_state.positions = list(local_map.values())
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
