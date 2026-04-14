"""
Execution Agent

Handles the full position lifecycle:
  Entry  → bracket order (buy + stop-loss + take-profit) at the broker
  Monitor → check if broker-side exits have filled, update local state
  Exit   → broker handles exits via bracket children; Python is backup

Supports Alpaca paper trading or simulated execution.
"""

import os
import json
import time
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

_STATE_DIR = Path(os.environ.get("TRADING_STATE_DIR", str(Path(__file__).parent)))
ORDER_LOG = _STATE_DIR / "order_log.json"

SLIPPAGE_RR_THRESHOLD = 1.5
FILL_POLL_TIMEOUT = 30
FILL_POLL_INTERVAL = 1


@dataclass
class OrderResult:
    success: bool
    order_id: str
    ticker: str
    action: str
    shares: int
    price: float
    message: str
    stop_order_id: str = ""
    target_order_id: str = ""


def get_alpaca_client(config: AgentConfig):
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret or not HAS_ALPACA:
        return None
    try:
        client = tradeapi.REST(api_key, api_secret, config.alpaca_base_url, api_version="v2")
        client.get_account()
        return client
    except Exception as e:
        print(f"  [WARN] Alpaca connection failed: {e}")
        print(f"  [WARN] Falling back to simulated execution")
        return None


def _wait_for_fill(client, order_id: str) -> tuple[str, float]:
    """Poll Alpaca until the order fills or timeout. Returns (status, fill_price)."""
    deadline = time.time() + FILL_POLL_TIMEOUT
    while time.time() < deadline:
        order = client.get_order(order_id)
        if order.status == "filled":
            return "filled", float(order.filled_avg_price)
        if order.status in ("cancelled", "expired", "rejected"):
            return order.status, 0.0
        time.sleep(FILL_POLL_INTERVAL)
    return "timeout", 0.0


def _submit_bracket_order(client, ticker: str, shares: int, stop_price: float,
                          target_price: float) -> OrderResult:
    """Submit a bracket order via Alpaca: buy + stop-loss child + take-profit child."""
    if client:
        try:
            order = client.submit_order(
                symbol=ticker, qty=shares, side="buy",
                type="market", time_in_force="gtc",
                order_class="bracket",
                stop_loss={"stop_price": str(round(stop_price, 2))},
                take_profit={"limit_price": str(round(target_price, 2))},
            )
            stop_id = ""
            target_id = ""
            if hasattr(order, "legs") and order.legs:
                for leg in order.legs:
                    if leg.type == "stop":
                        stop_id = leg.id
                    elif leg.type == "limit":
                        target_id = leg.id

            return OrderResult(
                True, order.id, ticker, "BUY", shares, 0,
                f"Alpaca bracket: {order.id}",
                stop_order_id=stop_id,
                target_order_id=target_id,
            )
        except Exception as e:
            return OrderResult(False, "", ticker, "BUY", shares, 0,
                               f"Alpaca bracket error: {e}")

    order_id = f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ticker}"
    return OrderResult(
        True, order_id, ticker, "BUY", shares, 0,
        f"Simulated bracket buy: {shares} {ticker}",
        stop_order_id=f"SIM-STOP-{ticker}",
        target_order_id=f"SIM-TARGET-{ticker}",
    )


def _submit_sell(client, ticker: str, shares: int) -> OrderResult:
    """Submit a plain market sell."""
    if client:
        try:
            order = client.submit_order(
                symbol=ticker, qty=shares, side="sell",
                type="market", time_in_force="day",
            )
            return OrderResult(True, order.id, ticker, "SELL", shares, 0,
                               f"Alpaca sell: {order.id}")
        except Exception as e:
            return OrderResult(False, "", ticker, "SELL", shares, 0,
                               f"Alpaca sell error: {e}")

    order_id = f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{ticker}"
    return OrderResult(True, order_id, ticker, "SELL", shares, 0,
                       f"Simulated sell: {shares} {ticker}")


def _replace_stop_order(client, stop_order_id: str, new_stop_price: float) -> tuple[bool, str]:
    """Replace a bracket stop-loss order at Alpaca with a new price."""
    if not stop_order_id or stop_order_id.startswith("SIM"):
        return (False, "no_order_id")
    try:
        client.replace_order(stop_order_id, stop_price=str(round(new_stop_price, 2)))
        return (True, "replaced")
    except Exception as e:
        try:
            order = client.get_order(stop_order_id)
            if order.status == "filled":
                return (False, "already_filled")
            if order.status in ("canceled", "expired"):
                return (False, f"order_{order.status}")
            return (False, f"error: {e}")
        except Exception as e2:
            print(f"  [WARN] {stop_order_id}: replace failed and status check failed: {e2}")
            return (False, "status_unknown")


# ─── Entry ───────────────────────────────────────────────────────────────────

def process_signal(signal: Signal, config: AgentConfig, regime_name: str = "") -> OrderResult | None:
    """Evaluate signal → size position → bracket order → wait for fill → validate R:R."""
    state = load_positions()
    decision = evaluate_new_trade(signal, state, config)
    print(f"\n  [{decision.severity}] {decision.reason}")

    if decision.action != "APPROVE":
        return None

    client = get_alpaca_client(config)
    result = _submit_bracket_order(
        client, signal.ticker, decision.adjusted_shares,
        stop_price=signal.stop_loss, target_price=signal.target,
    )
    print(f"  → {result.message}")

    if not result.success:
        _log_order(result)
        return result

    # Wait for the buy leg to fill and get actual price
    actual_fill_price = signal.entry_price  # fallback for simulated mode
    if client:
        status, fill_price = _wait_for_fill(client, result.order_id)
        if status != "filled":
            print(f"  [WARN] Buy order {status} for {signal.ticker}")
            _log_order(result)
            return OrderResult(False, result.order_id, signal.ticker, "BUY",
                               decision.adjusted_shares, 0,
                               f"Buy {status}: {result.order_id}")
        actual_fill_price = fill_price
        print(f"  → Filled at ${actual_fill_price:.2f} (signal was ${signal.entry_price:.2f})")

    result.price = actual_fill_price

    # Post-fill R:R re-validation
    new_risk = actual_fill_price - signal.stop_loss
    new_reward = signal.target - actual_fill_price
    if new_risk > 0:
        new_rr = new_reward / new_risk
    else:
        new_rr = 0

    if new_rr < SLIPPAGE_RR_THRESHOLD:
        print(f"  [SLIPPAGE_REJECT] R:R dropped to {new_rr:.2f} (threshold {SLIPPAGE_RR_THRESHOLD})")
        # Cancel bracket children
        if client:
            for child_id in [result.stop_order_id, result.target_order_id]:
                if child_id:
                    try:
                        client.cancel_order(child_id)
                    except Exception:
                        pass
        # Immediate market sell
        sell_result = _submit_sell(client, signal.ticker, decision.adjusted_shares)
        sell_price = actual_fill_price  # approximate for logging
        if client and sell_result.success:
            sell_status, sp = _wait_for_fill(client, sell_result.order_id)
            if sell_status == "filled":
                sell_price = sp
        sell_result.price = sell_price

        pnl = (sell_price - actual_fill_price) * decision.adjusted_shares
        log_trade(
            ticker=signal.ticker, action="SELL",
            shares=decision.adjusted_shares, price=sell_price,
            strategy=signal.strategy, outcome="SLIPPAGE_REJECT", pnl=pnl,
            notes=f"R:R {new_rr:.2f} < {SLIPPAGE_RR_THRESHOLD} after fill at ${actual_fill_price:.2f}",
            regime=regime_name,
        )
        log_trade(
            ticker=signal.ticker, action="BUY",
            shares=decision.adjusted_shares, price=actual_fill_price,
            strategy=signal.strategy, stop_loss=signal.stop_loss,
            target=signal.target, notes=f"Slippage rejected — filled ${actual_fill_price:.2f}",
            regime=regime_name,
        )
        _log_order(result)
        _log_order(sell_result)
        print(f"  → Slippage reject: sold at ${sell_price:.2f}, P&L ${pnl:+.2f}")
        return sell_result

    # Valid fill — record the position with actual fill price
    new_pos = Position(
        ticker=signal.ticker,
        shares=decision.adjusted_shares,
        entry_price=actual_fill_price,
        current_price=actual_fill_price,
        stop_loss=signal.stop_loss,
        initial_stop=signal.stop_loss,
        target=signal.target,
        strategy=signal.strategy,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        bracket_order_id=result.order_id,
        stop_order_id=result.stop_order_id,
        target_order_id=result.target_order_id,
    )
    if regime_name:
        new_pos.regime_at_entry = regime_name
    state.positions.append(new_pos)
    state.cash -= decision.adjusted_shares * actual_fill_price
    state.total_value = state.cash + sum(p.market_value for p in state.positions)
    state.trades_since_pause += 1
    save_positions(state)

    log_trade(
        ticker=signal.ticker, action="BUY",
        shares=decision.adjusted_shares, price=actual_fill_price,
        strategy=signal.strategy, stop_loss=signal.stop_loss,
        target=signal.target, notes=signal.reason,
        regime=regime_name,
    )
    _log_order(result)

    return result


# ─── Position management ─────────────────────────────────────────────────────

def manage_positions(config: AgentConfig) -> list[OrderResult]:
    """
    Monitor loop (runs every 30 min):
      1. Check if any bracket children have filled at the broker
      2. Update trailing stops (backup — broker handles primary exits)
      3. Process any locally detected stop hits (safety net)
    """
    state = load_positions()
    if not state.positions:
        return []

    results = []
    client = get_alpaca_client(config)

    # Step 1: Check broker for filled bracket children
    if client:
        positions_after_broker = []
        for pos in state.positions:
            filled_child = _check_bracket_children(client, pos)
            if filled_child:
                order_id, fill_price, exit_type = filled_child
                pnl = (fill_price - pos.entry_price) * pos.shares
                r_result = (fill_price - pos.entry_price) / (pos.entry_price - pos.initial_stop) if pos.entry_price != pos.initial_stop else 0

                if pnl < 0:
                    state.consecutive_losses += 1
                    outcome = "LOSS"
                else:
                    state.consecutive_losses = 0
                    outcome = "WIN" if exit_type == "target" else "WIN_TRAILED"

                state.cash += pos.shares * fill_price
                state.total_r += r_result

                log_trade(
                    ticker=pos.ticker, action="SELL", shares=pos.shares,
                    price=fill_price, strategy=pos.strategy,
                    outcome=outcome, pnl=pnl,
                    notes=f"Bracket {exit_type} at {r_result:+.1f}R (broker-side)",
                )
                result = OrderResult(True, order_id, pos.ticker, "SELL",
                                     pos.shares, fill_price,
                                     f"Bracket {exit_type}: {order_id}")
                _log_order(result)
                results.append(result)
                print(f"  [EXIT] {pos.ticker}: {outcome} at {r_result:+.1f}R "
                      f"(${pnl:+,.0f}) — broker {exit_type}")
            else:
                positions_after_broker.append(pos)
        state.positions = positions_after_broker
    else:
        # Simulated mode: use local stop/target checking
        positions_after_broker = state.positions

    # Step 2: Update trailing stops and sync to broker
    trail_decisions = update_trailing_stops(state, config)
    for d in trail_decisions:
        if d.new_stop and d.ticker:
            pos = next((p for p in state.positions if p.ticker == d.ticker), None)
            if not pos:
                continue
            if client:
                old_stop = pos.stop_loss
                success, reason = _replace_stop_order(client, pos.stop_order_id, d.new_stop)
                if success:
                    pos.stop_loss = d.new_stop
                    save_positions(state)
                    print(f"  [TRAIL] {d.ticker}: broker stop updated ${old_stop:.2f} → ${d.new_stop:.2f}")
                elif reason == "already_filled":
                    print(f"  [TRAIL] {d.ticker}: stop already filled — exit handled next cycle")
                else:
                    print(f"  [WARN] {d.ticker}: broker stop replace failed ({reason}) — original stop remains")
            else:
                pos.stop_loss = d.new_stop
                print(f"  [TRAIL] {d.reason}")
        else:
            print(f"  [TRAIL] {d.reason}")

    # Step 3: Local stop check (safety net for simulated mode or broker lag)
    positions_after = []
    for pos in state.positions:
        if pos.hit_stop:
            result = _submit_sell(client, pos.ticker, pos.shares)
            sell_price = pos.current_price
            if client and result.success:
                status, sp = _wait_for_fill(client, result.order_id)
                if status == "filled":
                    sell_price = sp
            result.price = sell_price

            if result.success:
                pnl = (sell_price - pos.entry_price) * pos.shares
                r_result = pos.r_multiple
                state.cash += pos.shares * sell_price

                if pnl < 0:
                    state.consecutive_losses += 1
                    outcome = "LOSS"
                else:
                    state.consecutive_losses = 0
                    outcome = "WIN_TRAILED"

                state.total_r += r_result

                log_trade(
                    ticker=pos.ticker, action="SELL", shares=pos.shares,
                    price=sell_price, strategy=pos.strategy,
                    outcome=outcome, pnl=pnl,
                    notes=f"Local stop at {r_result:+.1f}R",
                )
                _log_order(result)
                results.append(result)
                print(f"  [EXIT] {pos.ticker}: {outcome} at {r_result:+.1f}R (${pnl:+,.0f})")
            else:
                positions_after.append(pos)
        elif pos.hit_target:
            result = _submit_sell(client, pos.ticker, pos.shares)
            sell_price = pos.current_price
            if client and result.success:
                status, sp = _wait_for_fill(client, result.order_id)
                if status == "filled":
                    sell_price = sp
            result.price = sell_price

            if result.success:
                pnl = (sell_price - pos.entry_price) * pos.shares
                r_result = pos.r_multiple
                state.cash += pos.shares * sell_price
                state.consecutive_losses = 0
                state.total_r += r_result

                log_trade(
                    ticker=pos.ticker, action="SELL", shares=pos.shares,
                    price=sell_price, strategy=pos.strategy,
                    outcome="WIN", pnl=pnl,
                    notes=f"Target hit at {r_result:+.1f}R",
                )
                _log_order(result)
                results.append(result)
                print(f"  [EXIT] {pos.ticker}: WIN at {r_result:+.1f}R (${pnl:+,.0f})")
            else:
                positions_after.append(pos)
        else:
            positions_after.append(pos)

    state.positions = positions_after
    state.total_value = state.cash + sum(p.market_value for p in state.positions)
    state.peak_value = max(state.peak_value, state.total_value)

    health = check_portfolio_health(state, config)
    for d in health:
        if d.action == "PAUSE" and not state.paused_until:
            state.paused_until = (datetime.now() + timedelta(days=3)).isoformat()
            state.trades_since_pause = 0
            print(f"  [PAUSE] {d.reason}")

    save_positions(state)
    return results


def _check_bracket_children(client, pos: Position) -> tuple[str, float, str] | None:
    """Check if a bracket child order (stop or target) has filled at the broker."""
    for order_id, exit_type in [(pos.stop_order_id, "stop"), (pos.target_order_id, "target")]:
        if not order_id:
            continue
        try:
            order = client.get_order(order_id)
            if order.status == "filled":
                return order_id, float(order.filled_avg_price), exit_type
        except Exception:
            pass
    return None


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
        print(f"\n  Managed {len(results)} exits")

    signals = run_full_scan(config)
    for signal in signals[:3]:
        process_signal(signal, config)
