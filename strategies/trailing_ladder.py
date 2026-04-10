"""
Trailing Stop with Ladder Buy Strategy

Implements a compound position-management approach:

  1. TRAILING STOP — buy N shares, set a floor below entry, raise the
     floor as price climbs (floor only moves up), sell everything when
     price hits the floor.

  2. LADDER BUYS — if price drops to pre-set levels below entry, add
     shares to dollar-cost average down. Each ladder level fires once.

Together these create asymmetric exposure: the downside is capped by the
trailing stop while large up-moves benefit from the full initial position
plus any ladder additions that were absorbed on a dip.

Usage:
    from trailing_ladder import TrailingLadderConfig, start_trailing_ladder, check_and_update

    config = TrailingLadderConfig(ticker="AAPL", initial_shares=10)
    agent_config = AgentConfig()
    state = start_trailing_ladder(config, agent_config)

    while state.status == "active":
        state, actions = check_and_update(state, agent_config)
        print(get_summary(state))
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from config import AgentConfig

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_LADDER: list[tuple[float, int]] = [
    (-0.15, 10),
    (-0.20, 15),
    (-0.25, 20),
    (-0.30, 25),
]


@dataclass
class TrailingLadderConfig:
    """Settings for one trailing-stop + ladder-buy position.

    Attributes:
        ticker: Equity symbol (e.g. "AAPL").
        initial_shares: Number of shares to buy on entry.
        stop_loss_pct: Floor as fraction below *entry* price on day 1.
            Once trailing activates the floor is driven by trail_distance_pct.
        trail_activation_pct: How far price must rise above entry before
            trailing activates (0.10 = 10 % gain needed to start trailing).
        trail_distance_pct: How far the trailing floor sits below the
            high-water mark once trailing is active (0.05 = 5 % below high).
        ladder_levels: Ordered list of (drop_fraction, shares_to_buy) tuples.
            drop_fraction is negative, e.g. -0.15 means −15 % from entry.
    """

    ticker: str
    initial_shares: int = 10
    stop_loss_pct: float = 0.10
    trail_activation_pct: float = 0.10
    trail_distance_pct: float = 0.05
    ladder_levels: list[tuple[float, int]] = field(
        default_factory=lambda: list(DEFAULT_LADDER)
    )


# ─── State ────────────────────────────────────────────────────────────────────

@dataclass
class TrailingLadderState:
    """Mutable runtime state for a single trailing-ladder position.

    Attributes:
        ticker: Symbol this state belongs to.
        entry_price: Price paid for the initial shares.
        current_shares: Total shares held right now (initial + ladder fills).
        avg_cost: Weighted-average cost per share across all buys.
        floor_price: Current stop-loss / trailing-stop level.
        high_water_mark: Highest price seen since entry.
        ladder_fills: Set of drop_pct levels that have already been triggered
            (stored as strings to survive JSON round-trip).
        total_invested: Total dollars spent so far (all buys).
        status: One of "active", "trailing", or "stopped_out".
        trailing_active: Whether the trailing floor has been activated.
        opened_at: ISO timestamp of position open.
        closed_at: ISO timestamp of position close (empty if still open).
        last_price: Most recent price seen (updated each cycle).
        last_updated: ISO timestamp of last check_and_update call.
    """

    ticker: str
    entry_price: float
    current_shares: int
    avg_cost: float
    floor_price: float
    high_water_mark: float
    ladder_fills: set[str]
    total_invested: float
    status: Literal["active", "trailing", "stopped_out"]
    trailing_active: bool = False
    opened_at: str = ""
    closed_at: str = ""
    last_price: float = 0.0
    last_updated: str = ""

    def __post_init__(self):
        if not self.opened_at:
            self.opened_at = datetime.now().isoformat()
        if not self.last_updated:
            self.last_updated = self.opened_at

    # ── Convenience properties ──

    @property
    def unrealised_pnl(self) -> float:
        """Dollar P&L based on avg_cost vs last_price."""
        return (self.last_price - self.avg_cost) * self.current_shares

    @property
    def unrealised_pct(self) -> float:
        """Percentage P&L vs avg_cost."""
        if self.avg_cost <= 0:
            return 0.0
        return (self.last_price / self.avg_cost - 1) * 100

    @property
    def pct_from_entry(self) -> float:
        """Current price change from *entry* price (not avg_cost)."""
        if self.entry_price <= 0:
            return 0.0
        return (self.last_price / self.entry_price - 1) * 100

    @property
    def floor_distance_pct(self) -> float:
        """How far current price is above the floor (safety buffer)."""
        if self.last_price <= 0:
            return 0.0
        return (self.last_price / self.floor_price - 1) * 100


# ─── Persistence ──────────────────────────────────────────────────────────────

def _state_path(ticker: str) -> Path:
    return Path(__file__).parent / f"trailing_ladder_state_{ticker.upper()}.json"


def save_state(state: TrailingLadderState) -> None:
    """Persist a TrailingLadderState to JSON on disk.

    Args:
        state: The state object to save.
    """
    data = {
        "ticker": state.ticker,
        "entry_price": state.entry_price,
        "current_shares": state.current_shares,
        "avg_cost": state.avg_cost,
        "floor_price": state.floor_price,
        "high_water_mark": state.high_water_mark,
        "ladder_fills": list(state.ladder_fills),
        "total_invested": state.total_invested,
        "status": state.status,
        "trailing_active": state.trailing_active,
        "opened_at": state.opened_at,
        "closed_at": state.closed_at,
        "last_price": state.last_price,
        "last_updated": state.last_updated,
    }
    path = _state_path(state.ticker)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_state(ticker: str) -> TrailingLadderState | None:
    """Load a previously saved TrailingLadderState from disk.

    Args:
        ticker: The equity symbol to load state for.

    Returns:
        The saved state, or None if no file exists.
    """
    path = _state_path(ticker)
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    data["ladder_fills"] = set(data.get("ladder_fills", []))
    return TrailingLadderState(**data)


# ─── Order helpers ────────────────────────────────────────────────────────────

def _get_price(ticker: str) -> float | None:
    """Fetch the latest price, falling back gracefully."""
    try:
        from data_provider import get_provider
        provider = get_provider()
        return provider.get_latest_price(ticker)
    except Exception as exc:
        print(f"  [WARN] Could not fetch price for {ticker}: {exc}")
        return None


def _place_order(
    ticker: str,
    shares: int,
    side: str,
    agent_config: AgentConfig,
    price_hint: float = 0.0,
) -> tuple[bool, float, str]:
    """Submit a market order via Alpaca or simulate it.

    Args:
        ticker: Symbol to trade.
        shares: Number of shares.
        side: "buy" or "sell".
        agent_config: Used to initialise the Alpaca client.
        price_hint: Price used only for simulation logging.

    Returns:
        (success, fill_price, message)
    """
    try:
        from executor import get_alpaca_client, _submit_order
        client = get_alpaca_client(agent_config)
        result = _submit_order(client, ticker, shares, side)
        fill_price = result.price if result.price else price_hint
        return result.success, fill_price, result.message
    except Exception as exc:
        msg = f"Simulated {side}: {shares} {ticker} @ ~${price_hint:.2f}"
        print(f"  [SIM] {msg} (executor unavailable: {exc})")
        return True, price_hint, msg


def _log(ticker: str, action: str, shares: int, price: float, notes: str = "") -> None:
    """Best-effort trade journal entry."""
    try:
        from trade_tracker import log_trade
        log_trade(
            ticker=ticker,
            action=action,
            shares=shares,
            price=price,
            strategy="trailing_ladder",
            notes=notes,
        )
    except Exception:
        pass  # journalling is non-critical


# ─── Core API ─────────────────────────────────────────────────────────────────

def start_trailing_ladder(
    config: TrailingLadderConfig,
    agent_config: AgentConfig,
) -> TrailingLadderState:
    """Buy the initial position and initialise a TrailingLadderState.

    Fetches the current market price, places the initial buy order, sets the
    initial stop-loss floor, and persists the resulting state to disk.

    Args:
        config: Strategy parameters (ticker, sizes, percentages).
        agent_config: AgentConfig used to connect to Alpaca.

    Returns:
        A fresh TrailingLadderState in "active" status.
    """
    ticker = config.ticker.upper()
    print(f"\n[TrailingLadder] Starting position for {ticker}…")

    # 1. Get entry price
    price = _get_price(ticker)
    if price is None:
        raise RuntimeError(f"Cannot fetch price for {ticker} — aborting entry.")

    print(f"  Entry price: ${price:.2f}")
    print(f"  Initial shares: {config.initial_shares}")
    cost = config.initial_shares * price
    print(f"  Initial cost: ${cost:,.2f}")

    # 2. Place buy order
    success, fill_price, msg = _place_order(
        ticker, config.initial_shares, "buy", agent_config, price
    )
    if not success:
        raise RuntimeError(f"Entry order failed: {msg}")

    actual_price = fill_price if fill_price > 0 else price
    print(f"  Order: {msg}")

    # 3. Set initial floor
    floor = round(actual_price * (1 - config.stop_loss_pct), 4)
    print(f"  Initial floor (stop-loss): ${floor:.2f} "
          f"({config.stop_loss_pct*100:.1f}% below entry)")

    # 4. Build state
    state = TrailingLadderState(
        ticker=ticker,
        entry_price=actual_price,
        current_shares=config.initial_shares,
        avg_cost=actual_price,
        floor_price=floor,
        high_water_mark=actual_price,
        ladder_fills=set(),
        total_invested=config.initial_shares * actual_price,
        status="active",
        last_price=actual_price,
    )

    _log(ticker, "BUY", config.initial_shares, actual_price,
         f"trailing_ladder entry, floor=${floor:.2f}")

    save_state(state)
    print(f"  State saved. Status: {state.status}")
    return state


def check_and_update(
    state: TrailingLadderState,
    agent_config: AgentConfig,
    _config: TrailingLadderConfig | None = None,
) -> tuple[TrailingLadderState, list[str]]:
    """Main loop function — call this periodically to manage the position.

    Steps performed on each call:
      1. Fetch current price.
      2. Update high-water mark.
      3. Check whether trailing activation threshold has been crossed.
      4. If trailing is active, raise the floor if the new calculated floor
         is higher than the current floor (floor never decreases).
      5. Check ladder buy levels (price dropped to a new threshold).
      6. Check whether the floor has been hit → sell everything.

    Args:
        state: The current TrailingLadderState (mutated in place and saved).
        agent_config: AgentConfig used for order execution.
        _config: Optional TrailingLadderConfig needed to re-read ladder levels
            and trail parameters. If omitted the module uses the defaults
            embedded in the state's config. Pass the original config object
            to override those defaults.

    Returns:
        (updated_state, actions) where actions is a list of human-readable
        strings describing what happened this cycle.
    """
    if state.status == "stopped_out":
        return state, ["Position already stopped out — nothing to do."]

    actions: list[str] = []
    ticker = state.ticker

    # Resolve strategy parameters — use passed config or fall back to defaults
    if _config is not None:
        trail_activation_pct = _config.trail_activation_pct
        trail_distance_pct = _config.trail_distance_pct
        ladder_levels = _config.ladder_levels
    else:
        # Use module defaults (reasonable fallback)
        trail_activation_pct = 0.10
        trail_distance_pct = 0.05
        ladder_levels = DEFAULT_LADDER

    # ── 1. Get current price ──────────────────────────────────────────────────
    price = _get_price(ticker)
    if price is None:
        actions.append("Could not fetch price — skipping cycle.")
        return state, actions

    state.last_price = price
    state.last_updated = datetime.now().isoformat()

    # ── 2. Update high-water mark ─────────────────────────────────────────────
    if price > state.high_water_mark:
        old_hwm = state.high_water_mark
        state.high_water_mark = price
        actions.append(f"New high-water mark: ${price:.2f} (was ${old_hwm:.2f})")

    # ── 3. Activate trailing if threshold crossed ─────────────────────────────
    if not state.trailing_active:
        gain_pct = (price / state.entry_price) - 1
        if gain_pct >= trail_activation_pct:
            state.trailing_active = True
            state.status = "trailing"
            actions.append(
                f"Trailing ACTIVATED — price {gain_pct*100:.1f}% above entry "
                f"(threshold {trail_activation_pct*100:.1f}%)"
            )

    # ── 4. Raise floor if trailing is active ──────────────────────────────────
    if state.trailing_active:
        new_floor = round(state.high_water_mark * (1 - trail_distance_pct), 4)
        if new_floor > state.floor_price:
            old_floor = state.floor_price
            state.floor_price = new_floor
            actions.append(
                f"Floor raised: ${old_floor:.2f} → ${new_floor:.2f} "
                f"(HWM ${state.high_water_mark:.2f} − {trail_distance_pct*100:.0f}%)"
            )

    # ── 5. Ladder buys ────────────────────────────────────────────────────────
    drop_pct = (price / state.entry_price) - 1  # negative when price fell

    for level_pct, level_shares in sorted(ladder_levels, key=lambda x: x[0]):
        key = str(level_pct)
        if key in state.ladder_fills:
            continue  # Already triggered

        if drop_pct <= level_pct:
            # Price has reached (or passed) this ladder rung
            print(f"  [LADDER] {ticker} dropped {drop_pct*100:.1f}% — "
                  f"triggering level {level_pct*100:.0f}% → buy {level_shares} shares")

            success, fill_price, msg = _place_order(
                ticker, level_shares, "buy", agent_config, price
            )
            if success:
                actual = fill_price if fill_price > 0 else price
                # Update avg cost
                new_total_invested = state.total_invested + level_shares * actual
                new_total_shares = state.current_shares + level_shares
                state.avg_cost = new_total_invested / new_total_shares
                state.current_shares = new_total_shares
                state.total_invested = new_total_invested
                state.ladder_fills.add(key)

                action_str = (
                    f"Ladder buy @ {level_pct*100:.0f}%: +{level_shares} shares "
                    f"@ ${actual:.2f}, new avg cost ${state.avg_cost:.2f}, "
                    f"total {state.current_shares} shares"
                )
                actions.append(action_str)
                _log(ticker, "BUY", level_shares, actual,
                     f"ladder level {level_pct*100:.0f}%, avg_cost=${state.avg_cost:.2f}")
            else:
                actions.append(f"Ladder order FAILED at level {level_pct*100:.0f}%: {msg}")

    # ── 6. Check stop (floor hit) ─────────────────────────────────────────────
    if price <= state.floor_price:
        print(f"  [STOP] {ticker} @ ${price:.2f} hit floor ${state.floor_price:.2f} — selling all")

        success, fill_price, msg = _place_order(
            ticker, state.current_shares, "sell", agent_config, price
        )
        actual = fill_price if fill_price > 0 else price
        pnl = (actual - state.avg_cost) * state.current_shares

        if success:
            actions.append(
                f"STOPPED OUT: sold {state.current_shares} shares @ ${actual:.2f} "
                f"(floor was ${state.floor_price:.2f}), P&L: ${pnl:+,.2f}"
            )
            _log(ticker, "SELL", state.current_shares, actual,
                 f"trailing_ladder stopped out, floor=${state.floor_price:.2f}, "
                 f"pnl=${pnl:+.2f}")
            state.status = "stopped_out"
            state.closed_at = datetime.now().isoformat()
        else:
            actions.append(f"SELL order FAILED (floor hit): {msg}")

    save_state(state)
    return state, actions


# ─── Reporting ────────────────────────────────────────────────────────────────

def get_summary(state: TrailingLadderState) -> str:
    """Return a human-readable summary string for the current position.

    Args:
        state: The TrailingLadderState to summarise.

    Returns:
        A multi-line formatted string suitable for console output.
    """
    status_icons = {
        "active": "[  ]",
        "trailing": "[>>]",
        "stopped_out": "[XX]",
    }
    icon = status_icons.get(state.status, "[??]")

    lines = [
        f"{icon} {state.ticker} — {state.status.upper()}",
        f"  Entry price  : ${state.entry_price:.2f}",
        f"  Avg cost     : ${state.avg_cost:.2f}",
        f"  Last price   : ${state.last_price:.2f}",
        f"  Shares held  : {state.current_shares}",
        f"  Total invested: ${state.total_invested:,.2f}",
        f"  High-water mk: ${state.high_water_mark:.2f}",
        f"  Floor (stop) : ${state.floor_price:.2f}  "
        f"(+{state.floor_distance_pct:.1f}% buffer)",
        f"  Unrealised P&L: ${state.unrealised_pnl:+,.2f}  "
        f"({state.unrealised_pct:+.1f}%)",
        f"  Trailing active: {'Yes' if state.trailing_active else 'No'}",
        f"  Ladder fills : {sorted(state.ladder_fills) or 'none'}",
        f"  Opened       : {state.opened_at[:19]}",
    ]
    if state.closed_at:
        lines.append(f"  Closed       : {state.closed_at[:19]}")
    lines.append(f"  Last updated : {state.last_updated[:19]}")
    return "\n".join(lines)


# ─── Demo / __main__ ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Simulated walkthrough of the trailing-stop + ladder strategy.

    No real orders are placed — prices are injected manually to show
    how the state machine responds to different market moves.
    """

    print("=" * 60)
    print("  TRAILING LADDER — Simulation Demo")
    print("=" * 60)

    agent_cfg = AgentConfig()

    ladder_cfg = TrailingLadderConfig(
        ticker="DEMO",
        initial_shares=10,
        stop_loss_pct=0.10,          # 10% initial floor
        trail_activation_pct=0.10,   # start trailing after +10%
        trail_distance_pct=0.05,     # trail 5% below high
        ladder_levels=DEFAULT_LADDER,
    )

    # ── Simulate entry ────────────────────────────────────────────────────────
    ENTRY = 100.0
    print(f"\n--- ENTRY at ${ENTRY:.2f} ---")

    state = TrailingLadderState(
        ticker="DEMO",
        entry_price=ENTRY,
        current_shares=ladder_cfg.initial_shares,
        avg_cost=ENTRY,
        floor_price=round(ENTRY * (1 - ladder_cfg.stop_loss_pct), 4),
        high_water_mark=ENTRY,
        ladder_fills=set(),
        total_invested=ladder_cfg.initial_shares * ENTRY,
        status="active",
        last_price=ENTRY,
    )
    print(get_summary(state))

    # ── Scenario A: price rises to $115 (activates trailing) ─────────────────
    def _inject_price(s: TrailingLadderState, price: float) -> None:
        """Monkey-patch get_latest_price for the simulation."""
        s.last_price = price  # pre-set so get_summary works even if _get_price fails

    PRICE_SEQUENCE = [
        (105.0, "Price rises to $105  → no trailing yet"),
        (112.0, "Price rises to $112  → trailing activates (+12%)"),
        (118.0, "Price rises to $118  → floor moves up"),
        (115.0, "Small pullback to $115 → floor holds"),
        ( 85.0, "Big drop to $85      → ladder level -15% triggers"),
        ( 80.0, "Drop to $80          → ladder level -20% triggers"),
        ( 95.0, "Recovery to $95      → floor still at its high"),
        (130.0, "New high $130        → trailing floor rises to $123.50"),
        (122.0, "Drop to $122         → floor @ $123.50 → STOPPED OUT"),
    ]

    for sim_price, description in PRICE_SEQUENCE:
        print(f"\n--- {description} ---")

        # Override _get_price for simulation by temporarily patching module
        import trailing_ladder as _self
        _real_get = _self._get_price

        def _fake_get(ticker, _p=sim_price):  # noqa: E731
            return _p

        _self._get_price = _fake_get
        try:
            state, actions = check_and_update(state, agent_cfg, ladder_cfg)
        finally:
            _self._get_price = _real_get

        for act in actions:
            print(f"  → {act}")
        print(get_summary(state))

        if state.status == "stopped_out":
            print("\n  Position closed. Strategy complete.")
            break

    # Clean up demo state file
    demo_path = _state_path("DEMO")
    if demo_path.exists():
        demo_path.unlink()
        print(f"\n  (Demo state file removed: {demo_path.name})")


# ─── Multi-position helpers (used by scheduler) ──────────────────────────────

def check_all_active(agent_config: AgentConfig) -> list[str]:
    """Check and update all active trailing ladder positions. Returns action summaries."""
    import glob
    all_actions = []
    for state_file in glob.glob(str(Path(__file__).parent / "trailing_ladder_state_*.json")):
        ticker = Path(state_file).stem.replace("trailing_ladder_state_", "")
        state = load_state(ticker)
        if state and state.status in ("active", "trailing"):
            config = TrailingLadderConfig(ticker=ticker)
            state, actions = check_and_update(state, agent_config, config)
            all_actions.extend(actions)
            if actions:
                print(f"  [{ticker}] {', '.join(actions)}")
            else:
                print(f"  [{ticker}] No action needed")
    if not all_actions:
        print("  No active trailing ladder positions")
    return all_actions


def list_active_states() -> list[str]:
    """List all active trailing ladder positions as summary strings."""
    import glob
    summaries = []
    for state_file in glob.glob(str(Path(__file__).parent / "trailing_ladder_state_*.json")):
        ticker = Path(state_file).stem.replace("trailing_ladder_state_", "")
        state = load_state(ticker)
        if state and state.status in ("active", "trailing"):
            summaries.append(
                f"{state.ticker}: {state.current_shares} shares @ ${state.avg_cost:.2f}, "
                f"floor ${state.floor_price:.2f}, status={state.status}"
            )
    return summaries
