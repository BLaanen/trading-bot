"""
Market-Open Automation

One-command workflow for every trading day:

  1. Verify Alpaca connection
  2. Check market clock (handles weekends/holidays/early arrivals)
  3. Wait until market has been open 10 minutes (spreads settle)
  4. Run market regime check
  5. Fresh scan against live open prices
  6. Full pipeline: filter → execute → monitor → report
  7. Optionally start the scheduler to keep monitoring

Usage:
  python3.11 at_open.py                  # Full auto workflow
  python3.11 at_open.py --no-wait        # Skip the post-open wait (execute immediately)
  python3.11 at_open.py --no-scheduler   # Exit after execution, don't start scheduler
  python3.11 at_open.py --dry-run        # Plan only, do not place orders
  python3.11 at_open.py --force          # Skip all safety checks (even weekends)
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta

# Ensure env vars are present
if not os.environ.get("ALPACA_API_KEY") or not os.environ.get("ALPACA_API_SECRET"):
    print("ERROR: ALPACA_API_KEY and ALPACA_API_SECRET must be set.")
    print("Add them to ~/.zshrc and reload your shell.")
    sys.exit(1)

import alpaca_trade_api as tradeapi
from config import AgentConfig

POST_OPEN_WAIT_MIN = 10        # Minutes to wait after open before executing
MIN_MINUTES_BEFORE_CLOSE = 30  # Refuse new trades if close is imminent


def banner(text: str, char: str = "=") -> None:
    print()
    print(char * 72)
    print(f"  {text}")
    print(char * 72)


def fmt_td(td: timedelta) -> str:
    """Format a timedelta as 'Xh Ym'."""
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def wait_until(target: datetime, label: str) -> None:
    """Sleep until target datetime, printing a countdown every minute."""
    while True:
        now = datetime.now(target.tzinfo)
        remaining = target - now
        if remaining.total_seconds() <= 0:
            print(f"  {label}: now")
            return
        print(f"  {label}: {fmt_td(remaining)} remaining ({target.strftime('%H:%M %Z')})")
        # Sleep at most 60 seconds, or the remaining time if smaller
        sleep_for = min(60, max(1, int(remaining.total_seconds())))
        time.sleep(sleep_for)


def check_market(api, args) -> bool:
    """Returns True if we should proceed to execute, False to abort."""
    clock = api.get_clock()
    now = clock.timestamp
    next_open = clock.next_open
    next_close = clock.next_close

    print(f"  Now (ET):        {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Market open:     {clock.is_open}")
    print(f"  Next open:       {next_open.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  Next close:      {next_close.strftime('%Y-%m-%d %H:%M %Z')}")

    if args.force:
        print("  [FORCE] Skipping safety checks.")
        return True

    if not clock.is_open:
        until_open = next_open - now
        if until_open > timedelta(hours=1):
            print(f"\n  Market is closed. Next open in {fmt_td(until_open)}.")
            print("  Come back closer to market open. Aborting.")
            return False
        # Market opens within 1 hour — wait for it
        print(f"\n  Market opens in {fmt_td(until_open)}. Waiting...")
        wait_until(next_open, "Market open")
        # Refetch clock after waiting
        clock = api.get_clock()

    # Market is now open — check we're not too close to close
    now = clock.timestamp
    next_close = clock.next_close
    until_close = next_close - now
    if until_close < timedelta(minutes=MIN_MINUTES_BEFORE_CLOSE):
        print(f"\n  Market closes in {fmt_td(until_close)} — too late to open new trades.")
        print("  Aborting execution. Run --monitor only if you have open positions.")
        return False

    # Check how long ago the market opened
    # clock.next_open is the NEXT open (tomorrow), so we compute today's open from the clock
    # For simplicity: if market just opened, wait POST_OPEN_WAIT_MIN for spreads to settle
    session_age = now - clock.next_open if clock.next_open < now else None
    # Fallback: use a simple heuristic — if the market has been open less than
    # POST_OPEN_WAIT_MIN minutes, wait.
    # We can estimate: iterate get_clock() or just sleep if needed.

    if not args.no_wait:
        # Wait POST_OPEN_WAIT_MIN minutes past the open by checking elapsed
        # Use a simple sleep loop: refetch clock, check elapsed
        # Assume today's open was at 9:30 ET — use current day at 9:30 ET
        import pytz
        et = pytz.timezone("US/Eastern")
        now_et = now.astimezone(et)
        today_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et < today_open_et:
            today_open_et = today_open_et - timedelta(days=1)
        elapsed_since_open = now_et - today_open_et
        wait_needed = timedelta(minutes=POST_OPEN_WAIT_MIN) - elapsed_since_open
        if wait_needed > timedelta(seconds=0):
            target = now + wait_needed
            print(f"\n  Waiting {fmt_td(wait_needed)} for spreads to settle (post-open warmup)...")
            wait_until(target, "Spreads settling")
        else:
            print(f"\n  Market already open {fmt_td(elapsed_since_open)} — spreads should be settled.")

    return True


def run_step(label: str, fn, *args, **kwargs):
    banner(label)
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"\n  ERROR in {label}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    parser = argparse.ArgumentParser(description="Automated market-open trading workflow")
    parser.add_argument("--no-wait", action="store_true",
                        help="Skip the 10-minute post-open spread settling wait")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="Exit after execution instead of starting the scheduler")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only — do not place any orders")
    parser.add_argument("--force", action="store_true",
                        help="Skip all safety checks (weekend, holiday, closed market)")
    parser.add_argument("--skip-eod", action="store_true",
                        help="Skip learning loop & weekly report (run those separately via eod.sh)")
    args = parser.parse_args()

    config = AgentConfig()

    banner("ALPACA CONNECTION CHECK", "=")
    api = tradeapi.REST(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_API_SECRET"],
        config.alpaca_base_url,
        api_version="v2",
    )
    try:
        acct = api.get_account()
        print(f"  Account:       {acct.id}")
        print(f"  Status:        {acct.status}")
        print(f"  Cash:          ${float(acct.cash):,.2f}")
        print(f"  Buying power:  ${float(acct.buying_power):,.2f}")
    except Exception as e:
        print(f"  ERROR: Could not connect to Alpaca: {e}")
        sys.exit(1)

    banner("MARKET CLOCK", "=")
    if not check_market(api, args):
        sys.exit(0)

    # Step 0.5: Review yesterday's lessons BEFORE trading today
    # This is the "self-improvement" loop — read what we learned, then trade smarter.
    from pathlib import Path
    lessons_file = Path(__file__).parent / "lessons.md"
    if lessons_file.exists():
        banner("STEP 0.5: LESSONS FROM PRIOR SESSIONS", "~")
        content = lessons_file.read_text()
        # Print just the "what's working / failing" sections, not the full table
        if "What's Working" in content:
            idx = content.find("## Rules Derived From Patterns")
            if idx > 0:
                print(content[idx:idx + 2000])
            else:
                print(content[:2000])
        else:
            print("  No actionable lessons yet — still collecting data.")
    else:
        banner("STEP 0.5: LESSONS FROM PRIOR SESSIONS", "~")
        print("  No prior session data. This is day 1 of learning.")
        print("  The learning loop will build up patterns as trades close.")

    # Step 1: Market regime
    from regime import detect_regime, print_regime
    def _regime():
        r = detect_regime(config)
        print_regime(r)
        return r
    regime = run_step("STEP 1: MARKET REGIME (live)", _regime)

    if regime is None:
        print("\n  Regime detection failed. Aborting.")
        sys.exit(1)

    # Refuse to trade in BEAR regime unless forced
    if regime.regime.value == "BEAR" and not args.force:
        print("\n  BEAR regime detected. New entries disabled. Running monitor only.")
        from orchestrator import step_monitor
        run_step("STEP 2: MONITOR EXISTING POSITIONS", step_monitor, config)
        sys.exit(0)

    # Step 2: Fresh scan
    from scanner import run_full_scan
    def _scan():
        return run_full_scan(config)
    signals = run_step("STEP 2: FRESH MARKET SCAN", _scan)

    if not signals:
        print("\n  No signals found. No trades to execute. Starting monitor instead.")
        from orchestrator import step_monitor
        run_step("STEP 3: MONITOR", step_monitor, config)
        if not args.no_scheduler:
            start_scheduler(config)
        return

    # Step 3: Filter + Execute
    if args.dry_run:
        banner("DRY RUN — NO ORDERS PLACED", "!")
        print(f"  Would evaluate {len(signals)} signals through filters.")
        print("  Re-run without --dry-run to actually execute.")
        return

    # Use the orchestrator's filter + execute flow
    from orchestrator import step_filter, step_execute, step_monitor, step_report
    from strategy_validator import validate_all
    from risk_manager import load_positions

    # Step 3a: Validate strategies (weekly cache handled internally)
    import json
    from pathlib import Path
    last_run_file = Path(__file__).parent / "last_run.json"
    last_run = {}
    if last_run_file.exists():
        try:
            last_run = json.loads(last_run_file.read_text())
        except Exception:
            last_run = {}

    days_since_validate = 999
    if last_run.get("last_validate"):
        try:
            days_since_validate = (
                datetime.now() - datetime.fromisoformat(last_run["last_validate"])
            ).days
        except Exception:
            days_since_validate = 999

    if getattr(config, "paper_exploration_mode", False):
        banner("STEP 3: STRATEGY VALIDATION — SKIPPED (paper exploration mode)", "=")
        print("  Paper mode trusts live data over historical backtests.")
        print("  The learning loop will measure real edge from actual trades.")
        approved = {}  # Empty → filter will use exploration bypass
    elif days_since_validate >= 7:
        banner("STEP 3: STRATEGY VALIDATION (backtest)", "=")
        print("  This may take a few minutes on first run...")
        results = validate_all(config)
        approved = {}
        for r in results:
            if r.passed:
                approved.setdefault(r.strategy_name, []).append(r.ticker)
        last_run["last_validate"] = datetime.now().isoformat()
        last_run["approved"] = approved
        last_run_file.write_text(json.dumps(last_run, indent=2))
    else:
        approved = last_run.get("approved", {})
        print(f"\n  Using cached validation ({days_since_validate} days old)")

    # Step 3b: Filter
    actionable = run_step("STEP 4: FILTER SIGNALS", step_filter, signals, approved, config, regime)
    if not actionable:
        print("\n  No signals survived filtering. No new trades.")
    else:
        # Step 3c: Execute — in paper exploration mode allow up to exploration_max_positions
        # regardless of regime cap (generate more data for learning)
        state = load_positions()
        if getattr(config, "paper_exploration_mode", False):
            cap = config.exploration_max_positions
        else:
            cap = regime.max_positions
        max_new = max(0, cap - len(state.positions))
        if max_new == 0:
            print(f"\n  Already at max positions ({len(state.positions)}/{cap}). No new trades.")
        else:
            run_step(
                f"STEP 5: EXECUTE UP TO {max_new} TRADES",
                step_execute, actionable, config, max_new, regime.regime.value,
            )

    # Step 4: Monitor
    run_step("STEP 6: POSITION MONITORING", step_monitor, config)

    # Step 5: Report
    run_step("STEP 7: REPORT", step_report, config, regime)

    if not args.skip_eod:
        # Step 5.5: Learning Loop — analyze today's closed trades and update lessons/patterns
        from learning_loop import run_full_loop
        run_step("STEP 8: LEARNING LOOP", run_full_loop)

        # Step 5.6: Weekly Report — generate on Fridays (or last trading day of the week)
        today = datetime.now()
        if today.weekday() == 4:  # Friday = 4
            from weekly_report import generate_report
            iso = today.isocalendar()
            def _gen():
                path = generate_report(iso.year, iso.week)
                print(f"  Generated: {path}")
            run_step("STEP 9: WEEKLY REPORT", _gen)

        # Step 5.7: Show current adaptive config status
        from adaptive_config import show_status as show_adaptive_status
        run_step("STEP 10: ADAPTIVE CONFIG STATUS", show_adaptive_status)
    else:
        print("\n  [SKIP] Learning loop & weekly report skipped (run eod.sh after market close)")

    # Save run metadata
    last_run["last_run"] = datetime.now().isoformat()
    last_run_file.write_text(json.dumps(last_run, indent=2))

    # Step 6: Optionally start the scheduler
    if not args.no_scheduler:
        start_scheduler(config)


def start_scheduler(config):
    banner("STARTING SCHEDULER (Ctrl+C to stop)", "*")
    print("  The scheduler will keep running and check positions every 5 minutes.")
    print("  Leave this terminal open, or run in tmux/screen for background operation.")
    print()
    try:
        from scheduler import Scheduler
        from run_all import setup_strategies
        from notifier import get_notifier, NotificationLevel

        scheduler = Scheduler()
        setup_strategies(scheduler, config)

        notifier = get_notifier()
        notifier.notify(
            NotificationLevel.INFO,
            "at_open.py: Trading Day Started",
            "All strategies registered. Monitoring every 5 minutes.",
        )
        scheduler.run_loop(check_interval=30)
    except KeyboardInterrupt:
        print("\n\n  Scheduler stopped by user.")
    except Exception as e:
        print(f"\n  Scheduler error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
