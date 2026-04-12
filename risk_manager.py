"""
Risk Manager Agent

Two jobs:
  1. BEFORE entry: size the position so you risk exactly 1R ($risk_per_trade)
  2. AFTER entry: trail stops up to let winners run bigger than losers

Position sizing formula:
  shares = portfolio_risk_amount / (entry_price - stop_loss)

This means:
  - Tight stop (2% away) → bigger position
  - Wide stop (5% away) → smaller position
  - But the DOLLAR RISK is always the same: 1% of portfolio

Exit logic (all-or-nothing via bracket orders at broker):
  - Broker handles exits: stop-loss and take-profit are bracket children
  - Python trails stops up as backup (1R profit → start trailing)
  - Stop hit → exit all shares immediately
  - Target hit → exit all shares immediately
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import AgentConfig
from scanner import Signal


@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    current_price: float
    stop_loss: float
    initial_stop: float       # Original stop — never moves down
    target: float
    strategy: str
    entry_date: str
    high_water_mark: float = 0.0    # Highest price since entry
    trailing: bool = False          # Whether trailing stop is active
    regime_at_entry: str = ""       # Market regime when this position was opened (for learning loop)
    bracket_order_id: str = ""      # Parent bracket order ID from Alpaca
    stop_order_id: str = ""         # Child stop-loss order ID
    target_order_id: str = ""       # Child take-profit order ID

    def __post_init__(self):
        if self.high_water_mark == 0:
            self.high_water_mark = self.current_price

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    @property
    def pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        return (self.current_price / self.entry_price - 1) * 100

    @property
    def r_multiple(self) -> float:
        """How many R's we're up/down. 1R = initial risk per share."""
        risk_per_share = self.entry_price - self.initial_stop
        if risk_per_share <= 0:
            return 0
        return (self.current_price - self.entry_price) / risk_per_share

    @property
    def hit_stop(self) -> bool:
        return self.current_price <= self.stop_loss

    @property
    def hit_target(self) -> bool:
        return self.current_price >= self.target


@dataclass
class PortfolioState:
    total_value: float
    cash: float
    positions: list[Position]
    peak_value: float
    consecutive_losses: int
    total_r: float = 0.0             # Cumulative R gained/lost
    trades_since_pause: int = 0      # Trades since last pause (for half-size)
    paused_until: str = ""           # ISO date when pause expires

    @property
    def invested(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_value <= 0:
            return 0
        return (self.peak_value - self.total_value) / self.peak_value * 100

    @property
    def cash_pct(self) -> float:
        return self.cash / self.total_value * 100 if self.total_value > 0 else 100

    @property
    def is_paused(self) -> bool:
        if not self.paused_until:
            return False
        return datetime.now().isoformat() < self.paused_until


@dataclass
class RiskDecision:
    action: str  # "APPROVE", "REJECT", "EXIT_FULL", "TRAIL", "PAUSE"
    reason: str
    adjusted_shares: int = 0
    new_stop: float = 0.0
    severity: str = "INFO"  # INFO, WARNING, CRITICAL


_STATE_DIR = Path(os.environ.get("TRADING_STATE_DIR", str(Path(__file__).parent)))
POSITIONS_FILE = _STATE_DIR / "positions.json"


def save_positions(state: PortfolioState):
    data = {
        "total_value": state.total_value,
        "cash": state.cash,
        "peak_value": state.peak_value,
        "consecutive_losses": state.consecutive_losses,
        "total_r": state.total_r,
        "trades_since_pause": state.trades_since_pause,
        "paused_until": state.paused_until,
        "updated": datetime.now().isoformat(),
        "positions": [
            {
                "ticker": p.ticker, "shares": p.shares,
                "entry_price": p.entry_price, "current_price": p.current_price,
                "stop_loss": p.stop_loss, "initial_stop": p.initial_stop,
                "target": p.target, "strategy": p.strategy,
                "entry_date": p.entry_date,
                "high_water_mark": p.high_water_mark,
                "trailing": p.trailing,
                "bracket_order_id": p.bracket_order_id,
                "stop_order_id": p.stop_order_id,
                "target_order_id": p.target_order_id,
            }
            for p in state.positions
        ],
    }
    with open(POSITIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_positions() -> PortfolioState:
    if not POSITIONS_FILE.exists():
        return PortfolioState(
            total_value=10000, cash=10000, positions=[],
            peak_value=10000, consecutive_losses=0,
        )

    with open(POSITIONS_FILE) as f:
        data = json.load(f)

    positions = []
    for p in data.get("positions", []):
        p.pop("partial_exit_done", None)
        p.pop("original_shares", None)
        positions.append(Position(**p))
    return PortfolioState(
        total_value=data["total_value"],
        cash=data["cash"],
        positions=positions,
        peak_value=data.get("peak_value", data["total_value"]),
        consecutive_losses=data.get("consecutive_losses", 0),
        total_r=data.get("total_r", 0),
        trades_since_pause=data.get("trades_since_pause", 0),
        paused_until=data.get("paused_until", ""),
    )


# ─── Portfolio heat calculation ──────────────────────────────────────────────

def calculate_open_risk(state: PortfolioState) -> float:
    """
    Calculate total dollars currently at risk across ALL open positions.

    This is the "portfolio heat" — how much you'd lose if every single
    stop got hit at the same time.

    Key: positions where stop has been moved to breakeven (after partial
    exit) contribute ZERO heat. This means winning trades that are
    trailing on house money don't count against your risk cap. So you
    can carry more positions once winners start working.
    """
    total_risk = 0
    for pos in state.positions:
        # Risk = distance from current price down to stop, times shares
        # If stop is at or above entry (breakeven), this is zero
        risk_per_share = max(0, pos.current_price - pos.stop_loss)
        total_risk += risk_per_share * pos.shares
    return total_risk


# ─── Position sizing ────────────────────────────────────────────────────────

def calculate_position_size(signal: Signal, state: PortfolioState, config: AgentConfig) -> int:
    """
    Size the position through 4 constraints (takes the smallest):

    1. RISK BUDGET: risk exactly 1% of portfolio per trade
       → shares = $100 budget / $4.50 risk per share = 22 shares

    2. MAX POSITION: no single position > 10% of portfolio
       → shares = $1,000 max / $195 price = 5 shares

    3. CASH AVAILABLE: always keep 15% cash reserve
       → shares = available_cash / price

    4. TOTAL HEAT CAP: all open risk combined can't exceed 6%
       → If you already have 4% at risk, you can only add 2% more
       → But positions trailing at breakeven add 0% heat, so
         winning trades free up room for new ones

    The smallest of these 4 wins.
    """
    risk_budget = config.risk_at(state.total_value)

    # Half size if coming back from a pause
    if state.trades_since_pause < config.comeback_half_size_trades:
        risk_budget *= 0.5

    # Half size if in drawdown
    if state.drawdown_pct >= config.max_drawdown_pct * 100:
        risk_budget *= 0.5

    risk_per_share = signal.entry_price - signal.stop_loss
    if risk_per_share <= 0:
        return 0

    # Constraint 1: Per-trade risk budget (1% of portfolio)
    shares_by_risk = int(risk_budget / risk_per_share)

    # Constraint 2: Max single position size (10% of portfolio)
    shares_by_max_pos = int(state.total_value * config.max_position_pct / signal.entry_price)

    # Constraint 3: Cash available after keeping reserve
    available_cash = state.cash - state.total_value * config.cash_reserve_pct
    shares_by_cash = int(available_cash / signal.entry_price) if available_cash > 0 else 0

    # Constraint 4: Total portfolio heat cap (6% of portfolio)
    current_heat = calculate_open_risk(state)
    max_heat = state.total_value * config.max_total_risk_pct
    remaining_heat = max_heat - current_heat
    if remaining_heat <= 0:
        return 0  # At max heat — no new trades until risk comes off
    shares_by_heat = int(remaining_heat / risk_per_share)

    # Take the most restrictive constraint
    shares = min(shares_by_risk, shares_by_max_pos, shares_by_cash, shares_by_heat)

    if shares < 1:
        return 0

    return shares


# ─── Trailing stop management ───────────────────────────────────────────────

def update_trailing_stops(state: PortfolioState, config: AgentConfig) -> list[RiskDecision]:
    """
    Update stops for all open positions. This is the core of
    "let winners run, cut losers short."
    """
    decisions = []

    for pos in state.positions:
        # Update high water mark
        if pos.current_price > pos.high_water_mark:
            pos.high_water_mark = pos.current_price

        risk_per_share = pos.entry_price - pos.initial_stop
        if risk_per_share <= 0:
            continue

        # Phase 1: Activate trailing after 1R profit
        if not pos.trailing and pos.r_multiple >= config.trail_activation_r:
            pos.trailing = True
            decisions.append(RiskDecision(
                action="TRAIL",
                reason=f"{pos.ticker}: Trailing activated at {pos.r_multiple:.1f}R",
                severity="INFO",
            ))

        # Phase 2: Trail the stop up
        if pos.trailing:
            trail_stop = pos.high_water_mark * (1 - config.trail_distance_pct)
            # Stop can only move UP, never down
            if trail_stop > pos.stop_loss:
                old_stop = pos.stop_loss
                pos.stop_loss = round(trail_stop, 2)
                decisions.append(RiskDecision(
                    action="TRAIL",
                    reason=f"{pos.ticker}: Stop trailed ${old_stop:.2f} → ${pos.stop_loss:.2f} "
                           f"(HWM: ${pos.high_water_mark:.2f}, {pos.r_multiple:.1f}R)",
                    new_stop=pos.stop_loss,
                    severity="INFO",
                ))

    return decisions


# ─── Portfolio health checks ────────────────────────────────────────────────

def check_portfolio_health(state: PortfolioState, config: AgentConfig) -> list[RiskDecision]:
    decisions = []
    dd = state.drawdown_pct

    if dd >= config.kill_drawdown_pct * 100:
        decisions.append(RiskDecision(
            action="PAUSE",
            reason=f"KILL SWITCH: Drawdown {dd:.1f}% exceeds {config.kill_drawdown_pct*100:.0f}%. "
                   "Close all positions. Pause trading for 3 days.",
            severity="CRITICAL",
        ))
    elif dd >= config.max_drawdown_pct * 100:
        decisions.append(RiskDecision(
            action="TRAIL",
            reason=f"Drawdown {dd:.1f}%. Trading at half size. Tightening all stops.",
            severity="WARNING",
        ))

    if state.consecutive_losses >= config.consecutive_loss_limit:
        decisions.append(RiskDecision(
            action="PAUSE",
            reason=f"{state.consecutive_losses} consecutive losses. Pausing for 3 days.",
            severity="WARNING",
        ))

    min_cash = state.total_value * config.cash_reserve_pct
    if state.cash < min_cash:
        decisions.append(RiskDecision(
            action="REJECT",
            reason=f"Cash ${state.cash:,.0f} below reserve ${min_cash:,.0f}.",
            severity="WARNING",
        ))

    # Heat cap check
    current_heat = calculate_open_risk(state)
    max_heat = state.total_value * config.max_total_risk_pct
    heat_pct = current_heat / state.total_value * 100 if state.total_value > 0 else 0
    if current_heat >= max_heat:
        decisions.append(RiskDecision(
            action="REJECT",
            reason=f"Portfolio heat ${current_heat:,.0f} ({heat_pct:.1f}%) at cap "
                   f"(${max_heat:,.0f}, {config.max_total_risk_pct*100:.0f}%). "
                   f"Wait for stops to trail up or positions to exit.",
            severity="WARNING",
        ))

    if len(state.positions) >= config.max_open_positions:
        decisions.append(RiskDecision(
            action="REJECT",
            reason=f"Max positions ({config.max_open_positions}) reached.",
            severity="INFO",
        ))

    for pos in state.positions:
        if pos.hit_stop:
            decisions.append(RiskDecision(
                action="EXIT_FULL",
                reason=f"STOP: {pos.ticker} ${pos.current_price:.2f} <= ${pos.stop_loss:.2f} "
                       f"({pos.r_multiple:+.1f}R, {pos.pnl_pct:+.1f}%)",
                severity="WARNING",
            ))

    return decisions


# ─── New trade evaluation ───────────────────────────────────────────────────

def evaluate_new_trade(signal: Signal, state: PortfolioState, config: AgentConfig) -> RiskDecision:
    # Paused?
    if state.is_paused:
        return RiskDecision(
            action="REJECT", reason="Trading paused.", severity="WARNING",
        )

    health = check_portfolio_health(state, config)
    for d in health:
        if d.action == "PAUSE":
            return RiskDecision(
                action="REJECT", reason=f"Paused: {d.reason}", severity="WARNING",
            )

    if len(state.positions) >= config.max_open_positions:
        return RiskDecision(
            action="REJECT",
            reason=f"Max positions ({config.max_open_positions}) reached.",
        )

    if signal.ticker in {p.ticker for p in state.positions}:
        return RiskDecision(action="REJECT", reason=f"Already holding {signal.ticker}.")

    # R:R gate
    if signal.reward_risk < config.min_reward_risk:
        return RiskDecision(
            action="REJECT",
            reason=f"R:R {signal.reward_risk:.1f}x < minimum {config.min_reward_risk}x.",
        )

    # Note: per-sector and per-strategy caps are handled by correlation_guard.py
    # which runs in orchestrator.step_filter BEFORE signals reach here.
    # The legacy "2 positions per strategy" check was removed — it was redundant
    # and misleadingly used max_sector_exposure as a strategy cap.

    # Size it
    shares = calculate_position_size(signal, state, config)
    if shares <= 0:
        return RiskDecision(action="REJECT", reason="Position size = 0.")

    trade_value = shares * signal.entry_price
    risk_amount = shares * signal.risk
    r_pct = risk_amount / state.total_value * 100

    if trade_value > state.cash - state.total_value * config.cash_reserve_pct:
        return RiskDecision(
            action="REJECT",
            reason=f"Would breach cash reserve. Need ${trade_value:,.0f}, "
                   f"available ${state.cash - state.total_value * config.cash_reserve_pct:,.0f}.",
        )

    # Show heat after this trade
    current_heat = calculate_open_risk(state)
    new_heat = current_heat + risk_amount
    new_heat_pct = new_heat / state.total_value * 100

    return RiskDecision(
        action="APPROVE",
        reason=f"{shares} shares {signal.ticker} @ ${signal.entry_price:.2f} "
               f"(${trade_value:,.0f}, risk ${risk_amount:.0f} = {r_pct:.1f}%, "
               f"R:R={signal.reward_risk:.1f}x, "
               f"heat: {new_heat_pct:.1f}% / {config.max_total_risk_pct*100:.0f}%)",
        adjusted_shares=shares,
    )


# ─── Reporting ───────────────────────────────────────────────────────────────

def print_portfolio_status(state: PortfolioState, config: AgentConfig):
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    progress = (state.total_value - config.starting_capital) / (config.target_capital - config.starting_capital) * 100
    bar_len = 25
    filled = int(bar_len * max(0, min(100, progress)) / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    print(f"\n  Value:      ${state.total_value:>10,.2f}  [{bar}] {max(0,progress):.0f}%")
    print(f"  Cash:       ${state.cash:>10,.2f}  ({state.cash_pct:.0f}%)")
    print(f"  Invested:   ${state.invested:>10,.2f}")
    print(f"  Peak:       ${state.peak_value:>10,.2f}")
    print(f"  Drawdown:   {state.drawdown_pct:>9.1f}%")
    print(f"  Total R:    {state.total_r:>+9.1f}R")

    # Portfolio heat display
    current_heat = calculate_open_risk(state)
    max_heat = state.total_value * config.max_total_risk_pct
    heat_pct = current_heat / state.total_value * 100 if state.total_value > 0 else 0
    heat_bar_len = 20
    heat_filled = int(heat_bar_len * min(heat_pct, config.max_total_risk_pct * 100) / (config.max_total_risk_pct * 100)) if max_heat > 0 else 0
    heat_bar = "█" * heat_filled + "░" * (heat_bar_len - heat_filled)
    print(f"  Heat:       [{heat_bar}] ${current_heat:,.0f} / ${max_heat:,.0f} ({heat_pct:.1f}%)")

    if state.positions:
        # Show per-position risk breakdown
        print(f"\n  {'Ticker':<7} {'Shr':>4} {'Entry':>8} {'Now':>8} {'Stop':>8} "
              f"{'P&L':>8} {'R':>5} {'AtRisk':>7} {'Trail':>5}")
        print(f"  {'─'*7} {'─'*4} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*5} {'─'*7} {'─'*5}")
        for p in state.positions:
            trail_mark = ">>>" if p.trailing else ""
            pos_risk = max(0, p.current_price - p.stop_loss) * p.shares
            risk_label = f"${pos_risk:,.0f}" if pos_risk > 0 else "FREE"
            print(
                f"  {p.ticker:<7} {p.shares:>4} ${p.entry_price:>7.2f} ${p.current_price:>7.2f} "
                f"${p.stop_loss:>7.2f} ${p.pnl:>+7.0f} {p.r_multiple:>+4.1f}R "
                f"{risk_label:>7} {trail_mark}"
            )
    print(f"  Positions:  {len(state.positions):>10} / {config.max_open_positions}")

    decisions = check_portfolio_health(state, config)
    if decisions:
        print(f"\n  ─── Alerts ───")
        for d in decisions:
            icon = {"INFO": " ", "WARNING": "!", "CRITICAL": "X"}[d.severity]
            print(f"  [{icon}] {d.reason}")
    else:
        print(f"\n  All risk checks passed.")


if __name__ == "__main__":
    config = AgentConfig()
    state = load_positions()
    print_portfolio_status(state, config)
