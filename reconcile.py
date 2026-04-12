"""
Alpaca Reconciliation

Compares local positions.json against Alpaca's actual positions via API.
If they disagree, refuses to trade and logs the mismatch.

Run at the top of every orchestrator cycle before any trading logic.
"""

import os
from datetime import datetime

from config import AgentConfig
from risk_manager import load_positions

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False


def reconcile_with_broker(config: AgentConfig) -> bool:
    """Compare local state against Alpaca. Returns True if they match."""
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret or not HAS_ALPACA:
        print("  [RECONCILE] No Alpaca credentials — skipping reconciliation")
        return True

    try:
        client = tradeapi.REST(api_key, api_secret, config.alpaca_base_url, api_version="v2")
        broker_positions = client.list_positions()
    except Exception as e:
        print(f"  [RECONCILE] Failed to query Alpaca: {e}")
        return False

    local_state = load_positions()

    broker_map = {}
    for bp in broker_positions:
        broker_map[bp.symbol] = {
            "qty": int(bp.qty),
            "avg_entry": float(bp.avg_entry_price),
            "market_value": float(bp.market_value),
        }

    local_map = {}
    for lp in local_state.positions:
        local_map[lp.ticker] = {
            "qty": lp.shares,
            "avg_entry": lp.entry_price,
        }

    all_tickers = set(broker_map.keys()) | set(local_map.keys())
    mismatches = []

    for ticker in sorted(all_tickers):
        broker = broker_map.get(ticker)
        local = local_map.get(ticker)

        if broker and not local:
            mismatches.append(f"  {ticker}: at broker ({broker['qty']} shares @ ${broker['avg_entry']:.2f}) but NOT in local state")
        elif local and not broker:
            mismatches.append(f"  {ticker}: in local state ({local['qty']} shares @ ${local['avg_entry']:.2f}) but NOT at broker")
        elif broker and local:
            if broker["qty"] != local["qty"]:
                mismatches.append(f"  {ticker}: qty mismatch — broker={broker['qty']}, local={local['qty']}")
            if abs(broker["avg_entry"] - local["avg_entry"]) > 0.50:
                mismatches.append(f"  {ticker}: entry price mismatch — broker=${broker['avg_entry']:.2f}, local=${local['avg_entry']:.2f}")

    if mismatches:
        print(f"\n  [RECONCILE] MISMATCH DETECTED at {datetime.now().strftime('%H:%M:%S')}")
        for m in mismatches:
            print(m)
        print(f"\n  [RECONCILE] Refusing to trade until reconciled.")
        print(f"  Fix: update positions.json to match broker, or close stale positions.")
        return False

    print(f"  [RECONCILE] OK — {len(broker_map)} positions match between local and broker")
    return True


if __name__ == "__main__":
    config = AgentConfig()
    result = reconcile_with_broker(config)
    if result:
        print("\n  Reconciliation passed.")
    else:
        print("\n  Reconciliation FAILED — see mismatches above.")
