"""
Execution Agent

Handles the full position lifecycle:
  Entry    → sized by risk manager (1R per trade)
  Monitor  → trailing stops, partial exits
  Exit     → stop hit or trailed out

Supports Alpaca paper trading or simulated execution.
"""

import os
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

from config import AgentConfig
from scanner import Signal
from risk_manager import (
    Position, PortfolioState, RiskDecision,
    load_positions, save_positions, evaluate_new_trade,
    update_trailing_stops, check_portfolio_health,
)
from trade_tracker import log_trade, log_portfolio_value

try:
    import alpaca_trade_api as tradeapi
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False

ORDER_LOG = Path(__file__).parent / "order_log.json"


@dataclass
class OrderResult:
    success: bool
    order_id: str
    ticker: str
    action: str
    shares: int
    price: float
    message: str


def get_alpaca_client(config: AgentConfig):
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret or not HAS_ALPACA:
        return None
    try:
        client = tradeapi.REST(api_key, api_secret, config.alpaca_base_url, api_version="v2")
        # Validate connection on first use
        client.get_account()
        return client
    except Exception as e:
        print(f"  [WARN] Alpaca connection failed: {e}")
        print(f"  [WARN] Falling back to simulated execution")
        return None


def _submit_order(client, ticker: str, shares: int, side: str) -> OrderResult:
    """Submit an order via Alpaca or simulate it."""
    if client:
        try:
            order = client.submit_order(
                symbol=ticker, qty=shares, side=side,
                type="market", time_in_force="day",
            )
            return OrderResult(True, order.id, ticker, side.upper(), shares, 0,
                               f"Alpaca {side}: {order.id}")
        except Exception as e:
            return OrderResult(False, "", ticker, side.upper(), shares, 0,
                               f"Alpaca error: {e}")

    order_id = f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ticker}"
    return OrderResult(True, order_id, ticker, side.upper(), shares, 0,
                       f"Simulated {side}: {shares} {ticker}")


# ─── Entry ───────────────────────────────────────────────────────────────────

def process_signal(signal: Signal, config: AgentConfig, regime_name: str = "") -> OrderResult | None:
    """Evaluate signal → size position → execute entry."""
    state = load_positions()
    decision = evaluate_new_trade(signal, state, config)
    print(f"\n  [{decision.severity}] {decision.reason}")

    if decision.action != "APPROVE":
        return None

    client = get_alpaca_client(config)
    result = _submit_order(client, signal.ticker, decision.adjusted_shares, "buy")
    result.price = signal.entry_price
    print(f"  → {result.message}")

    if result.success:
        new_pos = Position(
            ticker=signal.ticker,
            shares=decision.adjusted_shares,
            entry_price=signal.entry_price,
            current_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            initial_stop=signal.stop_loss,
            target=signal.target,
            strategy=signal.strategy,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
        )
        # Tag the position with the regime at entry (for learning loop autopsy)
        if regime_name:
            new_pos.regime_at_entry = regime_name
        state.positions.append(new_pos)
        state.cash -= decision.adjusted_shares * signal.entry_price
        state.total_value = state.cash + sum(p.market_value for p in state.positions)
        state.trades_since_pause += 1
        save_positions(state)

        log_trade(
            ticker=signal.ticker, action="BUY",
            shares=decision.adjusted_shares, price=signal.entry_price,
            strategy=signal.strategy, stop_loss=signal.stop_loss,
            target=signal.target, notes=signal.reason,
            regime=regime_name,
        )
        _log_order(result)

    return result


# ─── Position management (the important part) ───────────────────────────────

def manage_positions(config: AgentConfig) -> list[OrderResult]:
    """
    The core loop that runs every cycle:
      1. Update prices
      2. Update trailing stops
      3. Process partial exits
      4. Process full exits (stops)
    """
    state = load_positions()
    if not state.positions:
        return []

    results = []
    client = get_alpaca_client(config)

    # Step 1: Update trailing stops (moves stops up, flags partial exits)
    trail_decisions = update_trailing_stops(state, config)
    for d in trail_decisions:
        print(f"  [TRAIL] {d.reason}")

    # Step 2: Process partial exits
    positions_after = []
    for pos in state.positions:
        if not pos.partial_exit_done and pos.hit_target:
            exit_shares = int(pos.shares * config.partial_exit_pct)
            if exit_shares >= 1:
                result = _submit_order(client, pos.ticker, exit_shares, "sell")
                result.price = pos.current_price

                if result.success:
                    pnl = exit_shares * (pos.current_price - pos.entry_price)
                    state.cash += exit_shares * pos.current_price
                    pos.shares -= exit_shares
                    pos.partial_exit_done = True
                    # Safety: if partial exit leaves 0 shares, mark for full exit
                    if pos.shares < 1:
                        pos.shares = 0

                    # Move stop to breakeven on remaining shares
                    if config.move_stop_to_entry:
                        pos.stop_loss = pos.entry_price

                    r_earned = pos.r_multiple
                    state.consecutive_losses = 0
                    state.total_r += r_earned * (exit_shares / pos.original_shares)

                    log_trade(
                        ticker=pos.ticker, action="SELL", shares=exit_shares,
                        price=pos.current_price, strategy=pos.strategy,
                        outcome="WIN_PARTIAL", pnl=pnl,
                        notes=f"Partial exit at {r_earned:.1f}R, {pos.shares} shares remain",
                    )
                    _log_order(result)
                    results.append(result)
                    print(f"  [PARTIAL] Sold {exit_shares} {pos.ticker} at {r_earned:.1f}R "
                          f"(+${pnl:.0f}), stop → ${pos.stop_loss:.2f}")

            positions_after.append(pos)

        elif pos.hit_stop:
            # Full exit on stop
            result = _submit_order(client, pos.ticker, pos.shares, "sell")
            result.price = pos.current_price

            if result.success:
                pnl = pos.pnl
                r_result = pos.r_multiple
                state.cash += pos.shares * pos.current_price

                if pnl < 0:
                    state.consecutive_losses += 1
                    outcome = "LOSS"
                else:
                    state.consecutive_losses = 0
                    outcome = "WIN_TRAILED"

                state.total_r += r_result

                log_trade(
                    ticker=pos.ticker, action="SELL", shares=pos.shares,
                    price=pos.current_price, strategy=pos.strategy,
                    outcome=outcome, pnl=pnl,
                    notes=f"Stop hit at {r_result:+.1f}R",
                )
                _log_order(result)
                results.append(result)
                print(f"  [EXIT] {pos.ticker}: {outcome} at {r_result:+.1f}R (${pnl:+,.0f})")
            else:
                positions_after.append(pos)
        else:
            positions_after.append(pos)

    state.positions = positions_after
    state.total_value = state.cash + sum(p.market_value for p in state.positions)
    state.peak_value = max(state.peak_value, state.total_value)

    # Check if we need to pause
    health = check_portfolio_health(state, config)
    for d in health:
        if d.action == "PAUSE" and not state.paused_until:
            state.paused_until = (datetime.now() + timedelta(days=3)).isoformat()
            state.trades_since_pause = 0
            print(f"  [PAUSE] {d.reason}")

    save_positions(state)
    return results


# ─── Price updates ───────────────────────────────────────────────────────────

def update_prices(config: AgentConfig):
    """Update all position prices from market data."""
    from data_provider import get_provider

    state = load_positions()
    if not state.positions:
        return

    tickers = [p.ticker for p in state.positions]
    provider = get_provider()
    prices = provider.get_bulk_prices(tickers)

    for pos in state.positions:
        if pos.ticker in prices:
            pos.current_price = prices[pos.ticker]
            if pos.current_price > pos.high_water_mark:
                pos.high_water_mark = pos.current_price

    state.total_value = state.cash + sum(p.market_value for p in state.positions)
    state.peak_value = max(state.peak_value, state.total_value)
    save_positions(state)

    log_portfolio_value(state.total_value, state.cash, notes="price-update")


# ─── Order logging ───────────────────────────────────────────────────────────

def _log_order(result: OrderResult):
    orders = []
    if ORDER_LOG.exists():
        with open(ORDER_LOG) as f:
            orders = json.load(f)
    orders.append({
        "timestamp": datetime.now().isoformat(),
        "order_id": result.order_id, "ticker": result.ticker,
        "action": result.action, "shares": result.shares,
        "price": result.price, "success": result.success,
        "message": result.message,
    })
    with open(ORDER_LOG, "w") as f:
        json.dump(orders, f, indent=2)


if __name__ == "__main__":
    from scanner import run_full_scan

    config = AgentConfig()
    print(f"Execution Agent — {'Alpaca Paper' if get_alpaca_client(config) else 'Simulated'}")

    update_prices(config)
    results = manage_positions(config)
    if results:
        print(f"\n  Managed {len(results)} exits/partials")

    signals = run_full_scan(config)
    for signal in signals[:3]:
        process_signal(signal, config)
