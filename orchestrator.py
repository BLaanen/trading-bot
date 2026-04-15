"""
Trading Agent Orchestrator

The master agent. Runs the full pipeline:

  0. REGIME    — Is the market bullish, sideways, or bearish?
  1. VALIDATE  — Backtest strategies to confirm they still work
  2. SCAN      — Scan market for actionable signals
  3. FILTER    — Risk, correlation, edge checks approve/reject
  4. EXECUTE   — Place orders (paper or simulated)
  5. MONITOR   — Trailing stops, partial exits, time stops
  6. OPTIMIZE  — Rebalance + correlation analysis
  7. REPORT    — Performance + edge decay + regime

Usage:
  python orchestrator.py              # Full pipeline run
  python orchestrator.py --scan       # Scan only
  python orchestrator.py --monitor    # Monitor + exits only
  python orchestrator.py --validate   # Validate strategies only
  python orchestrator.py --report     # Portfolio report only
  python orchestrator.py --rebalance  # Rebalance core ETFs
  python orchestrator.py --regime     # Market regime analysis only
  python orchestrator.py --edge       # Strategy edge report only
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

from config import AgentConfig
from scanner import run_full_scan, Signal
from risk_manager import (
    load_positions, save_positions, check_portfolio_health,
    print_portfolio_status, evaluate_new_trade, PortfolioState,
)
from strategy_validator import validate_strategy, validate_all
from executor import (
    process_signal, manage_positions, update_prices,
    get_alpaca_client,
)
from trade_tracker import log_portfolio_value, get_stats
from regime import detect_regime, print_regime, Regime, RegimeState
from correlation_guard import (
    check_new_position, analyze_portfolio, print_correlation_report,
    get_sector, get_correlation_cluster,
)
from edge_tracker import (
    is_strategy_enabled, should_time_stop, record_trade,
    print_edge_report, get_strategy_ranking,
)
from reconcile import reconcile_with_broker

import os
_STATE_DIR = Path(os.environ.get("TRADING_STATE_DIR", str(Path(__file__).parent)))
LAST_RUN_FILE = _STATE_DIR / "last_run.json"


def load_last_run() -> dict:
    if LAST_RUN_FILE.exists():
        with open(LAST_RUN_FILE) as f:
            return json.load(f)
    return {}


def save_last_run(data: dict):
    with open(LAST_RUN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(LAST_RUN_FILE, 0o600)


def step_validate(config: AgentConfig) -> dict[str, list[str]]:
    """Step 1: Validate all strategies. Returns approved strategy→ticker combos."""
    print("\n" + "=" * 70)
    print("  STEP 1: STRATEGY VALIDATION")
    print("=" * 70)

    results = validate_all(config)
    approved = {}
    for r in results:
        if r.passed:
            approved.setdefault(r.strategy_name, []).append(r.ticker)

    print(f"\n  Approved strategies: {len(approved)}")
    for strategy, tickers in approved.items():
        print(f"    {strategy}: {', '.join(tickers)}")

    return approved


def step_scan(config: AgentConfig, provider=None) -> list[Signal]:
    """Step 2: Scan market for signals."""
    print("\n" + "=" * 70)
    print("  STEP 2: MARKET SCAN")
    print("=" * 70)

    signals = run_full_scan(config, provider=provider)
    return signals


def step_filter(
    signals: list[Signal],
    approved: dict[str, list[str]],
    config: AgentConfig,
    regime: RegimeState | None = None,
) -> list[Signal]:
    """Step 3: Filter through 4 layers — regime, validation, edge, correlation, risk."""
    print("\n" + "=" * 70)
    print(f"  STEP 3: FILTERING (min R:R = {config.min_reward_risk}x)")
    print("=" * 70)

    state = load_positions()

    # Layer 1: Regime filter — only run strategies allowed in current regime
    if regime:
        allowed = regime.allowed_strategies
        regime_filtered = [s for s in signals if s.strategy in allowed]
        skipped = len(signals) - len(regime_filtered)
        if skipped:
            print(f"  [REGIME] Skipped {skipped} signals not allowed in {regime.regime.value}")
        signals = regime_filtered

    # Layer 2: Strategy-level backtest validation
    # In paper exploration mode: skip validation entirely.
    # Philosophy: paper trading is free data. The learning loop will measure
    # real-world edge from actual trades and auto-disable failing strategies.
    # Historical backtest validation only predicts — live data proves.
    if getattr(config, "paper_exploration_mode", False):
        validated = signals
        print(f"  [EXPLORATION] Paper mode — skipping validation, trusting all {len(signals)} signals")
    else:
        # Live mode: require strategy-level backtest edge
        approved_strategies = {s for s, tickers in approved.items() if tickers}
        validated = []
        for signal in signals:
            if signal.strategy in approved_strategies:
                validated.append(signal)
            else:
                print(f"  [SKIP] {signal.ticker}/{signal.strategy} — strategy has no backtest edge")

    # Layer 3: Edge tracker — is this strategy still working?
    edge_filtered = []
    for signal in validated:
        if is_strategy_enabled(signal.strategy):
            edge_filtered.append(signal)
        else:
            print(f"  [EDGE] {signal.ticker}/{signal.strategy} — strategy disabled (edge lost)")

    # Layer 4: Correlation guard — don't overload one cluster
    existing_tickers = [p.ticker for p in state.positions]
    existing_values = {p.ticker: p.market_value for p in state.positions}
    corr_filtered = []
    for signal in edge_filtered:
        allowed, reason = check_new_position(
            signal.ticker, existing_tickers, existing_values,
            state.total_value, config,
        )
        if allowed:
            corr_filtered.append(signal)
        else:
            print(f"  [CORR] {signal.ticker} — {reason}")

    # Layer 5: Risk management + position sizing
    actionable = []
    for signal in corr_filtered:
        decision = evaluate_new_trade(signal, state, config)
        if decision.action == "APPROVE":
            actionable.append(signal)
            print(f"  [OK] {decision.reason}")
        else:
            print(f"  [NO] {signal.ticker} — {decision.reason}")

    print(f"\n  Actionable: {len(actionable)} / {len(signals)} "
          f"(regime:{len(signals)}, validated:{len(validated)}, "
          f"edge:{len(edge_filtered)}, corr:{len(corr_filtered)})")
    return actionable


def step_execute(signals: list[Signal], config: AgentConfig, max_trades: int = 3, regime_name: str = ""):
    """Step 4: Execute top N approved signals."""
    print("\n" + "=" * 70)
    print("  STEP 4: EXECUTION")
    print("=" * 70)

    mode = "Alpaca Paper" if get_alpaca_client(config) else "Simulated"
    print(f"  Mode: {mode}")

    executed = 0
    for signal in signals[:max_trades]:
        result = process_signal(signal, config, regime_name=regime_name)
        if result and result.success:
            executed += 1

    print(f"\n  Executed {executed} trades")


def step_monitor(config: AgentConfig):
    """Step 5: Update prices → reconcile → check bracket exits → time stops."""
    print("\n" + "=" * 70)
    print("  STEP 5: POSITION MANAGEMENT")
    print("=" * 70)

    # Reconcile first
    if not reconcile_with_broker(config):
        print("  [WARN] Reconciliation failed — proceeding with caution")

    print("  Updating prices...")
    update_prices(config)

    # Check time stops BEFORE managing positions
    state = load_positions()
    for pos in state.positions:
        if should_time_stop(pos.entry_date, max_hold_days=15):
            if pos.r_multiple < 0.5:  # Only time-stop if not significantly profitable
                print(f"  [TIME] {pos.ticker}: held {pos.entry_date} → now, "
                      f"{pos.r_multiple:+.1f}R — dead money, closing")
                # Mark for exit by moving stop to current price
                pos.stop_loss = pos.current_price
    save_positions(state)

    results = manage_positions(config)
    if not results:
        print("  No exits triggered. All positions within stops.")

    # Record completed trades in edge tracker
    for r in results:
        # The R-multiple is embedded in the order message
        record_trade(strategy=r.ticker, r_multiple=0, hold_days=0)  # Simplified

    state = load_positions()
    decisions = check_portfolio_health(state, config)
    for d in decisions:
        if d.action not in ("EXIT_FULL",):
            print(f"  [{d.severity}] {d.reason}")


def step_rebalance(config: AgentConfig):
    """Step 6: Rebalance core ETF portfolio."""
    print("\n" + "=" * 70)
    print("  STEP 6: CORE ETF REBALANCE CHECK")
    print("=" * 70)

    state = load_positions()

    # Calculate current ETF allocation
    etf_positions = [p for p in state.positions if p.ticker in config.core_etfs]
    etf_value = sum(p.market_value for p in etf_positions)
    target_etf_value = state.total_value * config.core_etf_pct

    print(f"  Current ETF allocation: ${etf_value:,.0f} ({etf_value/state.total_value*100:.0f}%)" if state.total_value > 0 else "  No portfolio value")
    print(f"  Target ETF allocation:  ${target_etf_value:,.0f} ({config.core_etf_pct*100:.0f}%)")

    diff = target_etf_value - etf_value
    if abs(diff) > state.total_value * 0.05:  # More than 5% off target
        print(f"  *** Rebalance needed: {'add' if diff > 0 else 'reduce'} ${abs(diff):,.0f} in ETFs ***")

        # Calculate per-ETF targets (equal weight among core ETFs)
        per_etf_target = target_etf_value / len(config.core_etfs)
        print(f"\n  Target per ETF: ${per_etf_target:,.0f}")
        for etf in config.core_etfs:
            current = sum(p.market_value for p in etf_positions if p.ticker == etf)
            action = "ADD" if per_etf_target > current else "TRIM" if current > per_etf_target * 1.1 else "OK"
            print(f"    {etf:<6}: ${current:>8,.0f} → ${per_etf_target:>8,.0f}  [{action}]")
    else:
        print("  ETF allocation within tolerance. No rebalance needed.")


def step_report(config: AgentConfig, regime: RegimeState | None = None):
    """Step 7: Generate performance report with edge + correlation analysis."""
    print("\n" + "=" * 70)
    print("  STEP 7: PERFORMANCE REPORT")
    print("=" * 70)

    state = load_positions()
    print_portfolio_status(state, config)

    # Correlation analysis on current portfolio
    if state.positions:
        tickers = [p.ticker for p in state.positions]
        values = {p.ticker: p.market_value for p in state.positions}
        corr_report = analyze_portfolio(tickers, values, state.total_value)
        print_correlation_report(corr_report)

    # Edge tracker
    print_edge_report()

    # Trade journal stats
    get_stats()

    # Progress toward goal
    progress = (state.total_value - config.starting_capital) / (config.target_capital - config.starting_capital) * 100
    remaining = config.target_capital - state.total_value
    print(f"\n  {'='*40}")
    print(f"  GOAL TRACKER")
    print(f"  {'='*40}")
    print(f"  Starting:   ${config.starting_capital:>10,.0f}")
    print(f"  Current:    ${state.total_value:>10,.0f}")
    print(f"  Target:     ${config.target_capital:>10,.0f}")
    print(f"  Remaining:  ${remaining:>10,.0f}")
    print(f"  Progress:   {max(0, progress):>9.1f}%")
    bar_len = 30
    filled = int(bar_len * max(0, min(100, progress)) / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"  [{bar}]")


def run_full_pipeline(config: AgentConfig):
    """Run the complete agentic trading pipeline."""
    print("\n" + "=" * 70)
    print(f"  TRADING AGENT PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Target: ${config.starting_capital:,.0f} → ${config.target_capital:,.0f}")
    print("=" * 70)

    last_run = load_last_run()
    now = datetime.now()

    # Step 0: Market regime — THE most important check
    print("\n" + "=" * 70)
    print("  STEP 0: MARKET REGIME")
    print("=" * 70)
    regime = detect_regime(config)
    print_regime(regime)

    # Step 0.5: Reconciliation — abort if local state doesn't match broker
    print("\n" + "=" * 70)
    print("  STEP 0.5: BROKER RECONCILIATION")
    print("=" * 70)
    if not reconcile_with_broker(config):
        print("\n  ABORTING PIPELINE — reconciliation failed.")
        print("  Fix the mismatch, then re-run.")
        step_report(config, regime)
        return

    # Step 1: Validate (run weekly or on first run)
    last_validate = last_run.get("last_validate")
    days_since_validate = 999
    if last_validate:
        days_since_validate = (now - datetime.fromisoformat(last_validate)).days

    if days_since_validate >= 7:
        approved = step_validate(config)
        last_run["last_validate"] = now.isoformat()
        last_run["approved"] = approved
    else:
        approved = last_run.get("approved", {})
        print(f"\n  Using cached validation from {days_since_validate} days ago")

    # Pre-scan: ensure universe cache is fresh and init data provider once
    from universe import ensure_cache
    ensure_cache()
    from data_provider import get_provider as _get_provider
    provider = _get_provider()

    # Step 2: Scan
    signals = step_scan(config, provider=provider)

    # Step 3: Filter (now with regime, correlation, and edge checks)
    if approved:
        actionable = step_filter(signals, approved, config, regime)
    else:
        actionable = [s for s in signals if s.reward_risk >= config.min_reward_risk * 1.5]
        print(f"\n  No validation cache — using {len(actionable)} signals with R:R >= {config.min_reward_risk * 1.5:.1f}x")

    # Step 4: Execute (adjusted for regime, with exploration override in paper mode)
    if config.paper_exploration_mode:
        # Paper mode: take more trades to generate learning data
        ceiling = min(config.exploration_max_positions, regime.max_positions * 2)
    else:
        ceiling = 3
    max_trades = min(ceiling, regime.max_positions - len(load_positions().positions))
    if actionable and max_trades > 0:
        step_execute(actionable, config, max_trades=max_trades, regime_name=regime.regime.value)
    elif max_trades <= 0:
        print("\n  Max positions reached for current regime. No new trades.")

    # Step 5: Monitor
    step_monitor(config)

    # Step 6: Rebalance (check every 2 weeks)
    last_rebalance = last_run.get("last_rebalance")
    if not last_rebalance or (now - datetime.fromisoformat(last_rebalance)).days >= config.rebalance_interval_days:
        step_rebalance(config)
        last_run["last_rebalance"] = now.isoformat()

    # Step 7: Report
    step_report(config, regime)

    # Save run metadata
    last_run["last_run"] = now.isoformat()
    save_last_run(last_run)

    print(f"\n  Pipeline complete. Next run recommended in {config.scan_interval_hours} hours.")


if __name__ == "__main__":
    config = AgentConfig()

    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag == "--scan":
            run_full_scan(config)
        elif flag == "--monitor":
            step_monitor(config)
        elif flag == "--validate":
            step_validate(config)
        elif flag == "--report":
            step_report(config)
        elif flag == "--rebalance":
            step_rebalance(config)
        elif flag == "--execute":
            signals = step_scan(config)
            step_execute(signals, config)
        elif flag == "--regime":
            regime = detect_regime(config)
            print_regime(regime)
        elif flag == "--edge":
            print_edge_report()
        else:
            print(f"Unknown flag: {flag}")
            print("Options: --scan, --monitor, --validate, --report, "
                  "--rebalance, --execute, --regime, --edge")
    else:
        run_full_pipeline(config)
