"""
Unified Trading Bot Runner

Starts all strategies on the scheduler:
  - Full pipeline (every 4 hours)
  - Trailing stop monitor (every 5 minutes)
  - Copy trader (every 60 minutes)
  - Wheel strategy (every 15 minutes)
  - Daily report at market close

Usage:
  python run_all.py              # Start scheduler with all strategies
  python run_all.py --once       # Run all strategies once, then exit
  python run_all.py --status     # Show status of all strategies
"""

import sys
from datetime import datetime

from config import AgentConfig
from scheduler import Scheduler, ScheduleConfig, MarketHours
from notifier import get_notifier, NotificationLevel


def setup_strategies(scheduler: Scheduler, config: AgentConfig):
    """Register all trading strategies with the scheduler."""

    # Strategy 1: Full pipeline (scan + filter + execute + monitor)
    def run_pipeline():
        from orchestrator import run_full_pipeline
        run_full_pipeline(config)

    scheduler.add_schedule(ScheduleConfig(
        name="full_pipeline",
        callback=run_pipeline,
        interval_minutes=config.scan_interval_hours * 60,
        market_hours_only=True,
    ))

    # Strategy 2: Position monitor (trailing stops, partial exits)
    def run_monitor():
        from orchestrator import step_monitor
        step_monitor(config)

    scheduler.add_schedule(ScheduleConfig(
        name="position_monitor",
        callback=run_monitor,
        interval_minutes=5,
        market_hours_only=True,
    ))

    # Strategy 3: Trailing stop + ladder buy
    def run_trailing():
        from trailing_ladder import check_all_active
        check_all_active(config)

    scheduler.add_schedule(ScheduleConfig(
        name="trailing_ladder",
        callback=run_trailing,
        interval_minutes=5,
        market_hours_only=True,
    ))

    # Strategy 4: Copy trading
    def run_copy_trader():
        from copy_trader import run_copy_cycle, CopyTraderConfig
        copy_config = CopyTraderConfig(
            max_position_size_pct=config.copy_max_position_pct,
            min_trade_value=config.copy_min_trade_value,
        )
        run_copy_cycle(copy_config, config)

    scheduler.add_schedule(ScheduleConfig(
        name="copy_trader",
        callback=run_copy_trader,
        interval_minutes=config.copy_check_interval_min,
        market_hours_only=True,
    ))

    # Strategy 5: Wheel strategy
    def run_wheel():
        from wheel_strategy import check_all_wheels
        check_all_wheels(config)

    scheduler.add_schedule(ScheduleConfig(
        name="wheel_strategy",
        callback=run_wheel,
        interval_minutes=config.wheel_check_interval_min,
        market_hours_only=True,
    ))

    # Daily report at market close
    def run_daily_report():
        from orchestrator import step_report
        from regime import detect_regime
        regime = detect_regime(config)
        step_report(config, regime)
        notifier = get_notifier()
        notifier.notify(
            NotificationLevel.SUMMARY,
            "Daily Trading Summary",
            f"Market close report generated at {datetime.now().strftime('%H:%M')}",
        )

    scheduler.add_schedule(ScheduleConfig(
        name="daily_report",
        callback=run_daily_report,
        interval_minutes=24 * 60,  # Once per day
        market_hours_only=False,
    ))


def run_once(config: AgentConfig):
    """Run all strategies once without the scheduler."""
    print(f"\n{'='*70}")
    print(f"  RUNNING ALL STRATEGIES — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    market = MarketHours()
    if not market.is_market_open():
        print(f"\n  Market is closed. Next open: {market.next_open()}")
        print("  Running anyway for testing...\n")

    # 1. Full pipeline
    print("\n--- Full Pipeline ---")
    from orchestrator import run_full_pipeline
    run_full_pipeline(config)

    # 2. Check trailing stops
    print("\n--- Trailing Ladder Check ---")
    try:
        from trailing_ladder import check_all_active
        check_all_active(config)
    except Exception as e:
        print(f"  [SKIP] Trailing ladder: {e}")

    # 3. Copy trader
    print("\n--- Copy Trader Check ---")
    try:
        from copy_trader import run_copy_cycle, CopyTraderConfig
        copy_config = CopyTraderConfig()
        run_copy_cycle(copy_config, config)
    except Exception as e:
        print(f"  [SKIP] Copy trader: {e}")

    # 4. Wheel strategy
    print("\n--- Wheel Strategy Check ---")
    try:
        from wheel_strategy import check_all_wheels
        check_all_wheels(config)
    except Exception as e:
        print(f"  [SKIP] Wheel strategy: {e}")

    print(f"\n{'='*70}")
    print(f"  ALL STRATEGIES COMPLETE")
    print(f"{'='*70}")


def show_status():
    """Show current status of all strategies."""
    print(f"\n{'='*70}")
    print(f"  TRADING BOT STATUS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    market = MarketHours()
    print(f"\n  Market: {'OPEN' if market.is_market_open() else 'CLOSED'}")
    if not market.is_market_open():
        print(f"  Next open: {market.next_open()}")

    # Check active trailing stops
    print(f"\n  Trailing Ladder Positions:")
    try:
        from trailing_ladder import list_active_states
        states = list_active_states()
        if states:
            for s in states:
                print(f"    {s}")
        else:
            print("    None active")
    except Exception:
        print("    Module not initialized")

    # Check copy trader
    print(f"\n  Copy Trader:")
    try:
        from copy_trader import load_state
        state = load_state()
        if state:
            print(f"    Following: {state.get('target_politician', 'None')}")
            print(f"    Trades copied: {len(state.get('copied_trades', []))}")
        else:
            print("    Not initialized")
    except Exception:
        print("    Not initialized")

    # Check wheel strategy
    print(f"\n  Wheel Strategy:")
    try:
        from wheel_strategy import list_active_wheels
        wheels = list_active_wheels()
        if wheels:
            for w in wheels:
                print(f"    {w}")
        else:
            print("    None active")
    except Exception:
        print("    Not initialized")


if __name__ == "__main__":
    config = AgentConfig()

    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag == "--once":
            run_once(config)
        elif flag == "--status":
            show_status()
        else:
            print(f"Unknown flag: {flag}")
            print("Options: --once, --status, or no flag for scheduler mode")
    else:
        print(f"\n{'='*70}")
        print(f"  TRADING BOT SCHEDULER")
        print(f"  Starting all strategies on automated schedules...")
        print(f"{'='*70}")

        scheduler = Scheduler()
        setup_strategies(scheduler, config)

        notifier = get_notifier()
        notifier.notify(
            NotificationLevel.INFO,
            "Trading Bot Started",
            f"All strategies registered. Scheduler running.",
        )

        try:
            scheduler.run_loop(check_interval=30)
        except KeyboardInterrupt:
            print("\n\n  Scheduler stopped by user.")
            notifier.notify(
                NotificationLevel.WARNING,
                "Trading Bot Stopped",
                "Scheduler halted by user interrupt.",
            )
