"""
Trading Agent Configuration

Built around the PowerX Strategy (Marcus Heitkoetter):
  - Risk 2% of portfolio per trade (the "R")
  - Stop loss at 1x ADR (or PXO-provided level)
  - Profit target at 2x ADR (or PXO-provided level)
  - Position size = min(risk_sizing, portfolio / max_positions)
    → risk_sizing: shares = $risk / risk_per_share
    → position_cap: shares = (portfolio / max_positions) / price
    → take the SMALLER of the two to stay within budget

The math (2% rule):
  - Risk 2% of portfolio per trade
  - At 60% win rate with 2:1 R:R avg:
    10 trades = 6 wins (6 * 2R) + 4 losses (4 * 1R) = +8R net
  - On $10K with 2% risk: 1R = $200, so +8R = +$1,600 per 10 trades
"""

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    # ── Capital ──
    starting_capital: float = 10_000
    target_capital: float = 25_000

    # ── Universe ──
    # Dynamic universe: ~300-500 liquid stocks from S&P 500 + NASDAQ-100,
    # filtered by volume and price. Rebuilt weekly by universe.py.
    # These are fallbacks only — the scanner calls universe.get_scan_tickers()
    # which returns the full dynamic list.
    core_etfs: list[str] = field(default_factory=lambda: [
        "SPY", "QQQ", "IWM", "DIA",
    ])
    sector_etfs: list[str] = field(default_factory=lambda: [
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP",
        "XLU", "XLRE", "XLB", "SOXX", "SMH",
    ])
    # Liquidity filters for dynamic universe builder
    min_scan_volume: int = 500_000     # Min avg daily volume to scan
    min_scan_price: float = 5.0        # No penny stocks

    # ── The core rule: risk per trade (PowerX 2% rule) ──
    # Every trade risks exactly this % of total portfolio.
    # This is the "1R" — the unit everything else is measured in.
    # PowerX Strategy: 2% per trade, sized by ADR-based stop distance.
    risk_per_trade_pct: float = 0.02   # 2% of portfolio = 1R

    # ── Total portfolio risk cap ──
    # NEVER have more than this % of your account at risk at one time
    # across ALL open positions combined. This is your total "heat."
    # With 2% per trade and 6 positions: theoretical max 12% heat,
    # but position cap usually limits actual risk below this.
    max_total_risk_pct: float = 0.12   # 12% total portfolio heat cap

    # ── Asymmetric targets ──
    # Minimum reward-to-risk ratio to take a trade.
    # 2.0 means: if stop is $5 away, target must be $10+ away.
    min_reward_risk: float = 2.0

    # ── Trailing stop system ──
    # When enabled, the stop trails up to lock in profits after 1R gain.
    # When disabled (default), bracket orders handle all exits at the broker.
    use_trailing_stops: bool = False
    trail_activation_r: float = 1.0    # Start trailing after 1R profit
    trail_distance_pct: float = 0.05   # Trail 5% behind the high

    # ── Position management ──
    max_position_pct: float = 0.10     # Max 10% of portfolio per position
    max_open_positions: int = 6        # Focused: fewer, better positions
    cash_reserve_pct: float = 0.05     # Keep 5% cash reserve ($500 on $10K)
    max_sector_exposure: int = 2       # Max 2 positions in same sector

    # ── Strategy parameters ──
    # Pullback-to-support (best R:R setup)
    pullback_lookback: int = 20        # Look for support over 20 bars
    pullback_ma: int = 21              # 21 EMA for trend direction
    pullback_rsi_low: int = 35         # RSI dip zone
    pullback_rsi_high: int = 55        # RSI recovery zone

    # Breakout from consolidation
    consolidation_days: int = 10       # Min days in range
    consolidation_max_range: float = 0.06  # Max 6% range = tight base
    breakout_volume_mult: float = 1.5  # Volume must be 1.5x average

    # PowerX triple confirmation (RSI + MACD + Stochastic)
    powerx_rsi_period: int = 7         # Faster RSI per Heitkoetter
    powerx_macd_fast: int = 12
    powerx_macd_slow: int = 26
    powerx_macd_signal: int = 9
    powerx_stoch_k: int = 14
    powerx_stoch_d: int = 3
    powerx_stoch_slowing: int = 3
    powerx_min_volume: int = 500_000   # Min avg daily volume
    powerx_min_price: float = 10.0     # Min stock price
    # PowerX Optimizer stop/target as fixed % of entry price.
    # Settings from Heitkoetter's PowerX Optimizer:
    #   Conservative:    1.5% risk / 3.0% reward (R:R 2.0)
    #   Quick Trades:    1.5% risk / 4.5% reward (R:R 3.0)
    #   M&M Balanced:    2.5% risk / 5.0% reward (R:R 2.0)
    #   Position Trader: 2.5% risk / 7.5% reward (R:R 3.0)
    # Default: Quick Trades (1.5/4.5) — 60% win rate in backtests, R:R 3.0
    powerx_stop_pct: float = 0.015     # Stop 1.5% below entry
    powerx_target_pct: float = 0.045   # Target 4.5% above entry

    # Trend filter (applied to ALL strategies)
    trend_ema: int = 50                # Must be above 50 EMA to go long
    trend_sma: int = 200               # 200 SMA as major trend filter
    rsi_period: int = 14

    # ── Circuit breakers ──
    max_drawdown_pct: float = 0.10     # 10% drawdown → half position sizes
    kill_drawdown_pct: float = 0.20    # 20% drawdown → stop all trading
    consecutive_loss_limit: int = 4    # 4 losses in a row → pause 3 days
    # After a pause, come back at half size for 5 trades
    comeback_half_size_trades: int = 5

    # ── Backtesting ──
    backtest_start: str = "2022-01-01"
    backtest_end: str = "2026-03-31"
    min_sharpe: float = 0.5
    min_win_rate: float = 0.40         # 40% is fine if R:R is 2.5+
    min_avg_rr: float = 1.8            # Min average R:R across trades
    min_trades: int = 15               # Need enough trades for significance

    # ── Scheduling ──
    scan_interval_hours: int = 4
    rebalance_interval_days: int = 14
    full_review_interval_days: int = 30

    # ── Paper Mode Exploration ──
    # When true, the bot takes MORE trades to generate data for the learning loop.
    # Flip to False before live trading.
    paper_exploration_mode: bool = True
    exploration_max_positions: int = 6       # Up from 3 — more data per day
    exploration_min_reward_risk: float = 2.0 # Match live mode — marginal R:R gets killed by slippage
    exploration_max_sector: int = 3          # Up from 2 — test correlation guard assumption

    # ── Alpaca paper trading ──
    alpaca_paper: bool = True
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # ── Trailing Stop + Ladder Buy ──
    # Enhanced trailing stop with dollar-cost averaging on dips
    default_trail_stop_pct: float = 0.10   # Initial stop loss at 10%
    default_trail_distance: float = 0.05   # Trail 5% below high
    default_trail_activation: float = 0.10 # Activate trailing after 10% gain

    # ── Copy Trading ──
    copy_max_position_pct: float = 0.05    # Max 5% of portfolio per copied trade
    copy_min_trade_value: int = 15_000     # Min politician trade value to copy
    copy_check_interval_min: int = 60      # Check for new trades every 60 min

    # ── Wheel Strategy (Options) ──
    wheel_put_strike_pct: float = 0.10     # Sell puts 10% below current price
    wheel_call_strike_pct: float = 0.10    # Sell calls 10% above cost basis
    wheel_expiration_weeks: int = 3        # 2-4 week expirations
    wheel_early_close_pct: float = 0.50    # Close at 50% profit
    wheel_check_interval_min: int = 15     # Check positions every 15 min

    # ── Scheduler ──
    market_open_hour: int = 9              # Market opens 9:30 AM ET
    market_open_minute: int = 30
    market_close_hour: int = 16            # Market closes 4:00 PM ET
    market_close_minute: int = 0

    def __post_init__(self):
        # Paper exploration mode: loosen filters so we take more trades and
        # generate more data for the learning loop to analyze.
        if self.paper_exploration_mode:
            self.min_reward_risk = self.exploration_min_reward_risk
            self.max_open_positions = self.exploration_max_positions
            # Note: max_sector_exposure is checked dynamically in correlation_guard.py
            #       so both the live value and the override coexist here.

    @property
    def risk_amount(self) -> float:
        """Dollar amount risked per trade at starting capital."""
        return self.starting_capital * self.risk_per_trade_pct

    def risk_at(self, portfolio_value: float) -> float:
        """Dollar amount risked per trade at given portfolio value."""
        return portfolio_value * self.risk_per_trade_pct
