"""
Wheel Strategy — Options Income Module

Implements the classic "wheel" (aka triple income) strategy:

  Stage 1  SELL_PUTS → WAITING_ASSIGNMENT
    Sell a cash-secured put ~10% below current price, 2-4 weeks out.
    Collect premium. If expires worthless → keep premium, repeat.
    If assigned → take delivery of 100 shares, move to Stage 2.

  Stage 2  SELL_CALLS → WAITING_CALL_AWAY
    Sell a covered call ~10% above cost basis, 2-4 weeks out.
    Collect premium. If expires worthless → sell another call.
    If shares called away → sell at profit, go back to Stage 1.

Rules enforced:
  - Never sell a put without sufficient cash for assignment
  - Never sell a call below cost basis (would realise a loss)
  - Close early when contract hits 50% profit
  - Track total premium income across all cycles

Options execution:
  - Set ALPACA_OPTIONS_ENABLED=1 to send real Alpaca options orders
  - Otherwise all orders are SIMULATED (state + premium tracking still work)
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from config import AgentConfig
from data_provider import get_provider
from trade_tracker import log_trade

# ─── Paths ────────────────────────────────────────────────────────────────────

WHEEL_STATE_DIR = Path(__file__).parent / "wheel_states"
WHEEL_STATE_DIR.mkdir(exist_ok=True)

# ─── Configuration ────────────────────────────────────────────────────────────


@dataclass
class WheelConfig:
    """Per-ticker configuration for the wheel strategy."""

    ticker: str
    """Stock symbol to wheel (e.g. 'AAPL')."""

    put_strike_pct: float = 0.10
    """How far below current price to sell the put (0.10 = 10% OTM)."""

    call_strike_pct: float = 0.10
    """How far above cost basis to sell the call (0.10 = 10% OTM)."""

    expiration_weeks_min: int = 2
    """Minimum weeks to expiration when selecting contracts."""

    expiration_weeks_max: int = 4
    """Maximum weeks to expiration when selecting contracts."""

    early_close_pct: float = 0.50
    """Close the position early when unrealised gain ≥ this fraction of premium (0.50 = 50%)."""

    check_interval_minutes: int = 15
    """How often the management loop should run (informational; caller controls scheduling)."""

    @property
    def target_dte(self) -> int:
        """Target days-to-expiration: midpoint of the configured range."""
        avg_weeks = (self.expiration_weeks_min + self.expiration_weeks_max) / 2
        return int(avg_weeks * 7)


# ─── Stage type ───────────────────────────────────────────────────────────────

WheelStage = Literal["SELL_PUTS", "WAITING_ASSIGNMENT", "SELL_CALLS", "WAITING_CALL_AWAY"]

# ─── State ────────────────────────────────────────────────────────────────────


@dataclass
class WheelState:
    """Runtime state for one ticker's wheel cycle."""

    ticker: str
    stage: WheelStage = "SELL_PUTS"

    # Stock position
    shares_owned: int = 0
    cost_basis: float = 0.0
    """Effective per-share cost basis, reduced by premiums received."""

    # Active options contract (None when no position is open)
    current_contract: dict | None = None
    """Keys: type, strike, expiration, premium_collected, open_price, contracts."""

    # Accounting
    total_premium_collected: float = 0.0
    cycles_completed: int = 0
    premium_history: list[dict] = field(default_factory=list)

    # Internal: when did we last check for assignment / call-away?
    last_checked: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ─── Option premium estimator ─────────────────────────────────────────────────


def _black_scholes_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (e.g. 0.05)
        sigma: Implied volatility (e.g. 0.25 for 25%)

    Returns:
        Theoretical call premium per share.
    """
    if T <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    call = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return max(call, 0.01)


def _black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European put price via put-call parity."""
    call = _black_scholes_call(S, K, T, r, sigma)
    put = call - S + K * math.exp(-r * T)
    return max(put, 0.01)


def _norm_cdf(x: float) -> float:
    """Cumulative standard normal distribution (Abramowitz & Stegun approximation)."""
    a1, a2, a3, a4, a5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p = 0.2316419
    if x >= 0:
        t = 1.0 / (1.0 + p * x)
        poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
        return 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly
    else:
        return 1.0 - _norm_cdf(-x)


def estimate_put_premium(
    spot: float,
    strike: float,
    dte: int,
    implied_vol: float = 0.30,
    risk_free_rate: float = 0.05,
) -> float:
    """Estimate a put option premium using Black-Scholes.

    Args:
        spot: Current stock price
        strike: Put strike price (should be < spot for OTM)
        dte: Days to expiration
        implied_vol: Annual implied volatility estimate (default 30%)
        risk_free_rate: Annual risk-free rate (default 5%)

    Returns:
        Premium per share (multiply by 100 for one standard contract).
    """
    T = dte / 365.0
    return _black_scholes_put(spot, strike, T, risk_free_rate, implied_vol)


def estimate_call_premium(
    spot: float,
    strike: float,
    dte: int,
    implied_vol: float = 0.30,
    risk_free_rate: float = 0.05,
) -> float:
    """Estimate a call option premium using Black-Scholes.

    Args:
        spot: Current stock price
        strike: Call strike price (should be > spot for OTM)
        dte: Days to expiration
        implied_vol: Annual implied volatility estimate (default 30%)
        risk_free_rate: Annual risk-free rate (default 5%)

    Returns:
        Premium per share (multiply by 100 for one standard contract).
    """
    T = dte / 365.0
    return _black_scholes_call(spot, strike, T, risk_free_rate, implied_vol)


# ─── Strike calculators ────────────────────────────────────────────────────────


def calculate_put_strike(ticker: str, pct: float) -> tuple[float, float]:
    """Calculate a put strike price ~pct% below current market price.

    Returns:
        (current_price, strike_price) — strike rounded to nearest $0.50.
    """
    provider = get_provider()
    price = provider.get_latest_price(ticker)
    if price is None:
        raise ValueError(f"Could not get price for {ticker}")
    strike = round(price * (1 - pct) / 0.5) * 0.5
    return price, strike


def calculate_call_strike(cost_basis: float, pct: float) -> float:
    """Calculate a call strike price ~pct% above the cost basis.

    The strike must be at or above cost basis to ensure any assignment
    would result in a profit (before accounting for premiums received).

    Returns:
        Strike price rounded to nearest $0.50, always ≥ cost_basis.
    """
    raw = cost_basis * (1 + pct)
    strike = round(raw / 0.5) * 0.5
    return max(strike, math.ceil(cost_basis / 0.5) * 0.5)


# ─── Expiration date picker ────────────────────────────────────────────────────


def _next_friday(weeks_out: int) -> date:
    """Return the Friday that is approximately `weeks_out` weeks from today.

    Options on US equities typically expire on Fridays (standard monthly/weekly).
    """
    today = date.today()
    # Find next Friday
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # already Friday → use next Friday
    next_fri = today + timedelta(days=days_until_friday)
    # Advance by the requested number of additional weeks
    target = next_fri + timedelta(weeks=weeks_out - 1)
    return target


def _choose_expiration(config: WheelConfig) -> date:
    """Pick an expiration date within the configured min/max week range."""
    weeks = (config.expiration_weeks_min + config.expiration_weeks_max) // 2
    return _next_friday(weeks)


# ─── Alpaca options order ──────────────────────────────────────────────────────

_OPTIONS_ENABLED = os.environ.get("ALPACA_OPTIONS_ENABLED", "").lower() in ("1", "true", "yes")


def _place_options_order(
    alpaca_client,
    symbol: str,
    option_type: str,  # "put" | "call"
    strike: float,
    expiration: date,
    contracts: int,
    action: str,  # "sell_to_open" | "buy_to_close"
) -> dict:
    """Submit an options order to Alpaca or simulate it.

    When ALPACA_OPTIONS_ENABLED is not set, the order is fully SIMULATED.
    The simulation generates a realistic fill price using Black-Scholes so
    premium tracking and state transitions remain accurate.

    Returns:
        dict with keys: order_id, simulated, fill_price_per_share, message
    """
    sim_tag = "[SIM]" if not _OPTIONS_ENABLED else "[LIVE]"
    exp_str = expiration.strftime("%Y-%m-%d")
    dte = (expiration - date.today()).days

    # Estimate current premium for logging / simulation fill
    provider = get_provider()
    spot = provider.get_latest_price(symbol) or strike  # fallback
    if option_type == "put":
        est_premium = estimate_put_premium(spot, strike, max(dte, 1))
    else:
        est_premium = estimate_call_premium(spot, strike, max(dte, 1))

    print(
        f"  {sim_tag} Options order: {action.upper()} {contracts}x "
        f"{symbol} {exp_str} ${strike:.2f} {option_type.upper()} "
        f"@ ~${est_premium:.2f}/share (total ~${est_premium * 100 * contracts:.2f})"
    )

    if _OPTIONS_ENABLED and alpaca_client is not None:
        try:
            # Alpaca options symbol format: AAPL250117C00150000
            # Format: TICKER + YYMMDD + C/P + 8-digit strike (price * 1000, zero-padded)
            opt_symbol = _alpaca_option_symbol(symbol, expiration, option_type, strike)
            side = "sell" if "sell" in action else "buy"
            order = alpaca_client.submit_order(
                symbol=opt_symbol,
                qty=contracts,
                side=side,
                type="market",
                time_in_force="day",
            )
            return {
                "order_id": order.id,
                "simulated": False,
                "fill_price_per_share": est_premium,
                "message": f"Alpaca order submitted: {order.id}",
            }
        except Exception as exc:
            print(f"  [WARN] Alpaca options order failed: {exc} — falling through to simulation")

    # Simulation: add a small random spread (±5%)
    fill = est_premium * random.uniform(0.95, 1.05)
    order_id = f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{symbol}-{option_type.upper()}"
    return {
        "order_id": order_id,
        "simulated": True,
        "fill_price_per_share": round(fill, 2),
        "message": (
            f"SIMULATED {action.upper()} {contracts}x {symbol} "
            f"{exp_str} ${strike:.2f} {option_type.upper()} "
            f"@ ${fill:.2f}/share = ${fill * 100 * contracts:.2f} total premium"
        ),
    }


def _alpaca_option_symbol(ticker: str, expiration: date, option_type: str, strike: float) -> str:
    """Build an OCC-formatted options symbol for Alpaca.

    Format: <TICKER><YY><MM><DD><C|P><8-digit strike * 1000>
    Example: AAPL250117C00150000  (AAPL, 2025-01-17, Call, $150.00)
    """
    exp_str = expiration.strftime("%y%m%d")
    flag = "C" if option_type.lower() == "call" else "P"
    strike_int = int(strike * 1000)
    return f"{ticker}{exp_str}{flag}{strike_int:08d}"


# ─── Core wheel functions ──────────────────────────────────────────────────────


def start_wheel(config: WheelConfig, agent_config: AgentConfig) -> WheelState:
    """Initiate Stage 1: size and sell the first cash-secured put.

    Checks that sufficient cash is available (assignment would require buying
    100 shares at the strike price per contract).

    Args:
        config: Wheel parameters for this ticker.
        agent_config: Shared agent configuration (for Alpaca connection).

    Returns:
        Initialised WheelState after the first put is sold (or simulated).
    """
    from executor import get_alpaca_client

    state = WheelState(ticker=config.ticker)
    spot, strike = calculate_put_strike(config.ticker, config.put_strike_pct)
    expiration = _choose_expiration(config)
    dte = (expiration - date.today()).days
    contracts = 1  # 1 contract = 100 shares; scale up when capital permits

    # Safety check: do we have enough cash to cover assignment?
    assignment_cost = strike * 100 * contracts
    cash_needed = assignment_cost
    # We read starting_capital as a proxy; a production system would query the broker
    available_cash = agent_config.starting_capital * (1 - agent_config.cash_reserve_pct)
    if cash_needed > available_cash:
        print(
            f"  [WHEEL] Insufficient cash for {config.ticker}: need ${cash_needed:,.2f}, "
            f"available ${available_cash:,.2f}. Reduce contracts or increase capital."
        )
        state.stage = "SELL_PUTS"  # Stay in SELL_PUTS but don't open a contract
        return state

    client = get_alpaca_client(agent_config)
    result = _place_options_order(
        client, config.ticker, "put", strike, expiration, contracts, "sell_to_open"
    )

    premium_per_share = result["fill_price_per_share"]
    total_premium = premium_per_share * 100 * contracts

    state.current_contract = {
        "type": "put",
        "strike": strike,
        "expiration": expiration.isoformat(),
        "premium_collected": total_premium,
        "open_price": premium_per_share,
        "contracts": contracts,
        "order_id": result["order_id"],
        "simulated": result["simulated"],
    }
    state.stage = "WAITING_ASSIGNMENT"
    state.total_premium_collected += total_premium
    state.last_checked = datetime.now().isoformat()

    state.premium_history.append({
        "date": date.today().isoformat(),
        "type": "put",
        "strike": strike,
        "expiration": expiration.isoformat(),
        "premium": total_premium,
        "outcome": "open",
    })

    log_trade(
        ticker=config.ticker,
        action="SELL_PUT",
        shares=contracts * 100,
        price=premium_per_share,
        strategy="wheel",
        notes=(
            f"Strike=${strike:.2f} Exp={expiration} "
            f"{'[SIM]' if result['simulated'] else '[LIVE]'}"
        ),
    )

    print(f"\n  [WHEEL] {config.ticker} started. Stage: WAITING_ASSIGNMENT")
    print(f"          Put sold: ${strike:.2f} strike, exp {expiration}, premium ${total_premium:.2f}")
    save_state(state)
    return state


def check_and_manage(
    state: WheelState,
    config: WheelConfig,
    agent_config: AgentConfig,
) -> WheelState:
    """Main management loop. Call this on each check interval.

    Handles:
      - SELL_PUTS        → sell a new put if no contract is open
      - WAITING_ASSIGNMENT → check if put was assigned or expired
      - SELL_CALLS       → sell a covered call if no contract is open
      - WAITING_CALL_AWAY → check if shares were called away or call expired
      - Early close (50% profit) on any open contract

    Args:
        state: Current wheel state (mutated in place and saved).
        config: Wheel configuration.
        agent_config: Shared agent config.

    Returns:
        Updated WheelState.
    """
    from executor import get_alpaca_client

    client = get_alpaca_client(agent_config)
    today = date.today()
    print(f"\n  [WHEEL] {state.ticker} check — stage={state.stage}")

    # ── SELL_PUTS: open a new put ────────────────────────────────────────────
    if state.stage == "SELL_PUTS":
        if state.current_contract is None:
            print(f"  [WHEEL] No open put. Selling new put on {state.ticker}…")
            state = start_wheel(config, agent_config)
        else:
            print("  [WHEEL] Already have an open put contract.")

    # ── WAITING_ASSIGNMENT ───────────────────────────────────────────────────
    elif state.stage == "WAITING_ASSIGNMENT":
        if state.current_contract is None:
            # Should not happen, but recover gracefully
            state.stage = "SELL_PUTS"
        else:
            exp = date.fromisoformat(state.current_contract["expiration"])
            spot, _ = calculate_put_strike(state.ticker, 0)  # just get spot
            strike = state.current_contract["strike"]
            premium = state.current_contract["open_price"]

            # ── Early close check ────────────────────────────────────────
            current_premium = _estimate_current_option_price(
                state.current_contract, spot
            )
            if _check_early_close(state.current_contract, current_premium, config):
                state = _close_contract_early(state, config, agent_config, client, spot)
                save_state(state)
                return state

            # ── Expiration check ─────────────────────────────────────────
            if today >= exp:
                if spot <= strike:
                    # Assigned: stock dropped below strike
                    print(
                        f"  [WHEEL] {state.ticker} PUT ASSIGNED at ${strike:.2f} "
                        f"(spot=${spot:.2f}). Taking shares."
                    )
                    state = _handle_assignment(state, config, agent_config, client)
                else:
                    # Expired worthless: keep premium, sell another put
                    print(
                        f"  [WHEEL] {state.ticker} put expired worthless "
                        f"(spot=${spot:.2f} > strike=${strike:.2f}). "
                        f"Premium ${state.current_contract['premium_collected']:.2f} kept."
                    )
                    _record_outcome(state, "expired_worthless")
                    state.cycles_completed += 1
                    state.current_contract = None
                    state.stage = "SELL_PUTS"
            else:
                days_left = (exp - today).days
                print(
                    f"  [WHEEL] Waiting for put expiration. "
                    f"{days_left}d left. Strike=${strike:.2f}, spot=${spot:.2f}"
                )

    # ── SELL_CALLS: open a new call ──────────────────────────────────────────
    elif state.stage == "SELL_CALLS":
        if state.current_contract is None:
            print(f"  [WHEEL] Selling covered call on {state.ticker}…")
            state = _sell_covered_call(state, config, agent_config, client)
        else:
            print("  [WHEEL] Already have an open call contract.")

    # ── WAITING_CALL_AWAY ────────────────────────────────────────────────────
    elif state.stage == "WAITING_CALL_AWAY":
        if state.current_contract is None:
            state.stage = "SELL_CALLS"
        else:
            exp = date.fromisoformat(state.current_contract["expiration"])
            provider = get_provider()
            spot = provider.get_latest_price(state.ticker) or state.current_contract["strike"]
            strike = state.current_contract["strike"]

            # ── Early close check ────────────────────────────────────────
            current_premium = _estimate_current_option_price(
                state.current_contract, spot
            )
            if _check_early_close(state.current_contract, current_premium, config):
                state = _close_contract_early(state, config, agent_config, client, spot)
                save_state(state)
                return state

            if today >= exp:
                if spot >= strike:
                    # Shares called away
                    print(
                        f"  [WHEEL] {state.ticker} CALL EXERCISED at ${strike:.2f} "
                        f"(spot=${spot:.2f}). Shares sold."
                    )
                    state = _handle_call_away(state, config, agent_config, client)
                else:
                    # Call expired worthless
                    print(
                        f"  [WHEEL] {state.ticker} call expired worthless "
                        f"(spot=${spot:.2f} < strike=${strike:.2f}). "
                        f"Premium ${state.current_contract['premium_collected']:.2f} kept. "
                        f"Still own {state.shares_owned} shares."
                    )
                    _record_outcome(state, "expired_worthless")
                    state.current_contract = None
                    state.stage = "SELL_CALLS"
            else:
                days_left = (exp - today).days
                print(
                    f"  [WHEEL] Waiting for call expiration. "
                    f"{days_left}d left. Strike=${strike:.2f}, spot=${spot:.2f}"
                )

    state.last_checked = datetime.now().isoformat()
    save_state(state)
    return state


# ─── Internal helpers ──────────────────────────────────────────────────────────


def _estimate_current_option_price(contract: dict, spot: float) -> float:
    """Estimate the current fair value of an open contract.

    Uses Black-Scholes with the same IV assumption as when we opened.
    This is used to decide whether the 50% profit target has been hit.
    """
    exp = date.fromisoformat(contract["expiration"])
    dte = (exp - date.today()).days
    if dte <= 0:
        # At or past expiration: intrinsic value only
        if contract["type"] == "put":
            return max(contract["strike"] - spot, 0.0)
        else:
            return max(spot - contract["strike"], 0.0)
    if contract["type"] == "put":
        return estimate_put_premium(spot, contract["strike"], dte)
    else:
        return estimate_call_premium(spot, contract["strike"], dte)


def _check_early_close(contract: dict, current_premium: float, config: WheelConfig) -> bool:
    """Return True if the contract should be closed early (50% profit rule).

    We *sold* the option, so we want to *buy it back* when it has lost value.
    Profit = original_premium - current_ask.
    Close when profit / original_premium >= early_close_pct.
    """
    original = contract["open_price"]
    if original <= 0:
        return False
    profit_pct = (original - current_premium) / original
    if profit_pct >= config.early_close_pct:
        print(
            f"  [WHEEL] Early-close triggered: contract at {profit_pct:.0%} profit "
            f"(original ${original:.2f}, now ~${current_premium:.2f})"
        )
        return True
    return False


def _close_contract_early(
    state: WheelState,
    config: WheelConfig,
    agent_config: AgentConfig,
    client,
    spot: float,
) -> WheelState:
    """Buy back the open contract to lock in the profit."""
    contract = state.current_contract
    exp = date.fromisoformat(contract["expiration"])

    result = _place_options_order(
        client,
        state.ticker,
        contract["type"],
        contract["strike"],
        exp,
        contract["contracts"],
        "buy_to_close",
    )

    buyback_cost = result["fill_price_per_share"] * 100 * contract["contracts"]
    net_profit = contract["premium_collected"] - buyback_cost
    state.total_premium_collected += net_profit  # premium already counted on open; adjust
    # Note: premium_collected was already added at open, so we subtract the buyback cost
    state.total_premium_collected -= contract["premium_collected"]
    state.total_premium_collected += net_profit

    print(
        f"  [WHEEL] Contract closed early. "
        f"Net profit: ${net_profit:.2f} (collected ${contract['premium_collected']:.2f}, "
        f"bought back for ${buyback_cost:.2f})"
    )
    _record_outcome(state, "early_close", net_profit=net_profit)

    if contract["type"] == "put":
        state.cycles_completed += 1
        state.current_contract = None
        state.stage = "SELL_PUTS"
    else:
        state.current_contract = None
        state.stage = "SELL_CALLS"  # Still own shares, sell another call

    log_trade(
        ticker=state.ticker,
        action="BUY_TO_CLOSE",
        shares=contract["contracts"] * 100,
        price=result["fill_price_per_share"],
        strategy="wheel",
        outcome="WIN_EARLY",
        pnl=net_profit,
        notes=f"Early close at 50%+ profit. Strike=${contract['strike']:.2f}",
    )
    return state


def _handle_assignment(
    state: WheelState,
    config: WheelConfig,
    agent_config: AgentConfig,
    client,
) -> WheelState:
    """Process put assignment: receive 100 shares per contract at the strike price.

    The effective cost basis is the strike minus all premiums received so far,
    which makes the wheel income-aware.
    """
    contract = state.current_contract
    strike = contract["strike"]
    contracts = contract["contracts"]
    shares = contracts * 100

    # Effective cost basis per share: strike reduced by premium received
    premium_per_share = state.total_premium_collected / shares if shares else 0
    effective_basis = strike - premium_per_share

    state.shares_owned = shares
    state.cost_basis = effective_basis
    _record_outcome(state, "assigned")
    state.current_contract = None
    state.stage = "SELL_CALLS"

    log_trade(
        ticker=state.ticker,
        action="ASSIGNED",
        shares=shares,
        price=strike,
        strategy="wheel",
        notes=(
            f"Put assigned at ${strike:.2f}. "
            f"Effective basis=${effective_basis:.2f} (after premiums)."
        ),
    )
    print(
        f"  [WHEEL] Assigned {shares} shares of {state.ticker} at ${strike:.2f}. "
        f"Effective cost basis: ${effective_basis:.2f}/share. Moving to SELL_CALLS."
    )
    return state


def _sell_covered_call(
    state: WheelState,
    config: WheelConfig,
    agent_config: AgentConfig,
    client,
) -> WheelState:
    """Sell a covered call against the owned shares."""
    strike = calculate_call_strike(state.cost_basis, config.call_strike_pct)
    expiration = _choose_expiration(config)
    contracts = state.shares_owned // 100

    if contracts < 1:
        print(f"  [WHEEL] Not enough shares ({state.shares_owned}) to sell a call.")
        return state

    # Guard: never sell below cost basis
    if strike < state.cost_basis:
        strike = math.ceil(state.cost_basis / 0.5) * 0.5
        print(f"  [WHEEL] Strike adjusted to ${strike:.2f} to stay above cost basis.")

    result = _place_options_order(
        client, state.ticker, "call", strike, expiration, contracts, "sell_to_open"
    )

    premium_per_share = result["fill_price_per_share"]
    total_premium = premium_per_share * 100 * contracts

    state.current_contract = {
        "type": "call",
        "strike": strike,
        "expiration": expiration.isoformat(),
        "premium_collected": total_premium,
        "open_price": premium_per_share,
        "contracts": contracts,
        "order_id": result["order_id"],
        "simulated": result["simulated"],
    }
    state.stage = "WAITING_CALL_AWAY"
    state.total_premium_collected += total_premium

    state.premium_history.append({
        "date": date.today().isoformat(),
        "type": "call",
        "strike": strike,
        "expiration": expiration.isoformat(),
        "premium": total_premium,
        "outcome": "open",
    })

    log_trade(
        ticker=state.ticker,
        action="SELL_CALL",
        shares=contracts * 100,
        price=premium_per_share,
        strategy="wheel",
        notes=(
            f"Strike=${strike:.2f} Exp={expiration} Basis=${state.cost_basis:.2f} "
            f"{'[SIM]' if result['simulated'] else '[LIVE]'}"
        ),
    )

    print(
        f"  [WHEEL] Covered call sold: ${strike:.2f} strike, exp {expiration}, "
        f"premium ${total_premium:.2f}. Stage: WAITING_CALL_AWAY"
    )
    return state


def _handle_call_away(
    state: WheelState,
    config: WheelConfig,
    agent_config: AgentConfig,
    client,
) -> WheelState:
    """Process call exercise: shares sold at strike price. Return to Stage 1."""
    contract = state.current_contract
    strike = contract["strike"]
    shares = state.shares_owned

    sale_proceeds = strike * shares
    cost_of_shares = state.cost_basis * shares
    stock_pnl = sale_proceeds - cost_of_shares

    total_income = state.total_premium_collected  # includes all premiums
    print(
        f"  [WHEEL] Shares called away at ${strike:.2f}. "
        f"Stock gain: ${stock_pnl:+,.2f}. "
        f"Total premium income this cycle: ${total_income:.2f}."
    )

    _record_outcome(state, "called_away", net_profit=stock_pnl)
    state.shares_owned = 0
    state.cost_basis = 0.0
    state.cycles_completed += 1
    state.current_contract = None
    state.stage = "SELL_PUTS"

    log_trade(
        ticker=state.ticker,
        action="CALL_AWAY",
        shares=shares,
        price=strike,
        strategy="wheel",
        outcome="WIN",
        pnl=stock_pnl,
        notes=f"Shares called away. Total premium collected: ${total_income:.2f}",
    )
    return state


def _record_outcome(state: WheelState, outcome: str, net_profit: float = 0.0):
    """Update the most recent premium_history entry with its outcome."""
    if state.premium_history:
        state.premium_history[-1]["outcome"] = outcome
        if net_profit:
            state.premium_history[-1]["net_profit"] = net_profit


# ─── Summary ──────────────────────────────────────────────────────────────────


def get_summary(state: WheelState) -> str:
    """Return a human-readable status string for the wheel."""
    lines = [
        f"  Wheel: {state.ticker}",
        f"  Stage: {state.stage}",
        f"  Cycles completed: {state.cycles_completed}",
        f"  Total premium collected: ${state.total_premium_collected:,.2f}",
    ]
    if state.shares_owned:
        lines.append(f"  Shares owned: {state.shares_owned} @ cost basis ${state.cost_basis:.2f}")
    if state.current_contract:
        c = state.current_contract
        lines.append(
            f"  Open {c['type'].upper()}: strike=${c['strike']:.2f} "
            f"exp={c['expiration']} premium=${c['premium_collected']:.2f}"
        )
    if state.premium_history:
        lines.append(f"  Premium history ({len(state.premium_history)} entries):")
        for entry in state.premium_history[-3:]:
            lines.append(
                f"    {entry['date']} {entry['type'].upper()} "
                f"${entry['strike']:.2f} → ${entry['premium']:.2f} [{entry['outcome']}]"
            )
    return "\n".join(lines)


# ─── Persistence ──────────────────────────────────────────────────────────────


def _state_path(ticker: str) -> Path:
    return WHEEL_STATE_DIR / f"{ticker.upper()}_wheel_state.json"


def save_state(state: WheelState) -> None:
    """Persist wheel state to disk as JSON."""
    path = _state_path(state.ticker)
    with open(path, "w") as f:
        json.dump(state.as_dict(), f, indent=2)


def load_state(ticker: str) -> WheelState | None:
    """Load wheel state from disk. Returns None if no state exists."""
    path = _state_path(ticker)
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return WheelState(**data)


# ─── Demo / __main__ ─────────────────────────────────────────────────────────


def _run_simulated_cycle(ticker: str = "AAPL", num_checks: int = 6) -> None:
    """Run a simulated wheel cycle, printing state after each step.

    This exercises all four stages without real money:
      1. start_wheel → sells a put (simulated)
      2. Simulate put expiring worthless → back to SELL_PUTS
      3. start_wheel again → sells another put (simulated)
      4. Simulate assignment → move to SELL_CALLS
      5. sell_covered_call → sells a call (simulated)
      6. Simulate call expiring worthless → back to SELL_CALLS
    """
    print("\n" + "=" * 60)
    print(f"  WHEEL STRATEGY — SIMULATED CYCLE on {ticker}")
    print("=" * 60)

    config = WheelConfig(ticker=ticker)
    agent_config = AgentConfig(starting_capital=25_000)

    # ── Step 1: Start the wheel ───────────────────────────────────────────
    print("\n--- Step 1: Start wheel (sell first put) ---")
    state = start_wheel(config, agent_config)
    print(get_summary(state))

    # ── Step 2: Simulate put expiring worthless ───────────────────────────
    print("\n--- Step 2: Simulate put expiring worthless ---")
    if state.current_contract:
        # Fast-forward the expiration date to today so it triggers
        state.current_contract["expiration"] = date.today().isoformat()
        # Force spot above strike so it expires worthless
        provider = get_provider()
        spot = provider.get_latest_price(ticker) or 200.0
        strike = state.current_contract["strike"]
        if spot <= strike:
            print(f"  [SIM] Adjusting strike to ${spot * 0.92:.2f} to simulate OTM expiry")
            state.current_contract["strike"] = round(spot * 0.92 / 0.5) * 0.5
        save_state(state)
        state = check_and_manage(state, config, agent_config)
    print(get_summary(state))

    # ── Step 3: Sell another put ──────────────────────────────────────────
    print("\n--- Step 3: Sell another put ---")
    state = check_and_manage(state, config, agent_config)
    print(get_summary(state))

    # ── Step 4: Simulate assignment ───────────────────────────────────────
    print("\n--- Step 4: Simulate put assignment (stock dropped) ---")
    if state.current_contract:
        state.current_contract["expiration"] = date.today().isoformat()
        # Force spot below strike to trigger assignment
        strike = state.current_contract["strike"]
        state.current_contract["strike"] = strike  # keep strike, spot will be above it
        # We need spot < strike; patch the contract so it looks assigned
        # by temporarily overriding the strike above current spot
        provider = get_provider()
        spot = provider.get_latest_price(ticker) or 200.0
        state.current_contract["strike"] = round(spot * 1.08 / 0.5) * 0.5
        print(f"  [SIM] Setting strike to ${state.current_contract['strike']:.2f} > spot ${spot:.2f}")
        save_state(state)
        state = check_and_manage(state, config, agent_config)
    print(get_summary(state))

    # ── Step 5: Sell covered call ─────────────────────────────────────────
    print("\n--- Step 5: Sell covered call ---")
    state = check_and_manage(state, config, agent_config)
    print(get_summary(state))

    # ── Step 6: Simulate call expiring worthless ──────────────────────────
    print("\n--- Step 6: Simulate call expiring worthless ---")
    if state.current_contract:
        state.current_contract["expiration"] = date.today().isoformat()
        provider = get_provider()
        spot = provider.get_latest_price(ticker) or 200.0
        # Force spot below strike
        strike = state.current_contract["strike"]
        if spot >= strike:
            state.current_contract["strike"] = round(spot * 1.12 / 0.5) * 0.5
        save_state(state)
        state = check_and_manage(state, config, agent_config)
    print(get_summary(state))

    print("\n" + "=" * 60)
    print("  FINAL WHEEL SUMMARY")
    print("=" * 60)
    print(get_summary(state))
    print(
        f"\n  State file: {_state_path(ticker)}"
    )


# ─── Multi-wheel helpers (used by scheduler) ─────────────────────────────────

def check_all_wheels(agent_config: AgentConfig) -> list[str]:
    """Check and manage all active wheel positions. Returns action summaries."""
    import glob
    all_actions = []
    for state_file in glob.glob(str(Path(__file__).parent / "wheel_state_*.json")):
        ticker = Path(state_file).stem.replace("wheel_state_", "")
        state = load_state(ticker)
        if state:
            config = WheelConfig(ticker=ticker)
            state = check_and_manage(state, config, agent_config)
            summary = f"[{ticker}] Stage: {state.stage}, Premium: ${state.total_premium_collected:.2f}"
            all_actions.append(summary)
            print(f"  {summary}")
    if not all_actions:
        print("  No active wheel positions")
    return all_actions


def list_active_wheels() -> list[str]:
    """List all active wheel positions as summary strings."""
    import glob
    summaries = []
    for state_file in glob.glob(str(Path(__file__).parent / "wheel_state_*.json")):
        ticker = Path(state_file).stem.replace("wheel_state_", "")
        state = load_state(ticker)
        if state:
            summaries.append(
                f"{state.ticker}: stage={state.stage}, shares={state.shares_owned}, "
                f"premium=${state.total_premium_collected:.2f}, cycles={state.cycles_completed}"
            )
    return summaries


if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    _run_simulated_cycle(ticker)
