# Trading System — Session Guide

This file tells Claude how to work in this repo. Read it first when you enter a session here.

## What this is

A Python algorithmic trading system that runs on Alpaca paper trading. One brain (`orchestrator.py`), three shell wrappers (`at_open.sh`, `monitor.sh`, `eod.sh`), and an OS-level schedule (launchd) that runs them automatically during US market hours. The system scans the market, picks trades that pass risk filters, places orders, trails stops, exits at targets, and learns from closed trades — all without human intervention. The user (Bo) uses this to paper trade toward a $10K → $100K goal.

The user is NOT a deep trading expert. They asked earlier builders to set this up and now want to work with the result. Explain trading concepts as needed. Do not assume vocabulary. See `CONCEPTS.md` for plain-language definitions.

## Where to look at session start

Conversation memory does not persist across `/clear` or new sessions. The ground truth lives on disk. At the start of any trading session, read these files in this order:

1. **`positions.json`** — what's currently open: ticker, shares, entry, stop, target, strategy, trailing state
2. **Last 50 lines of `order_log.json`** — recent buy/sell fills with Alpaca order IDs and timestamps
3. **`logs/launchd_monitor.log` (last ~100 lines)** — what the monitor has been doing
4. **`logs/launchd_at_open.log` (last ~50 lines)** — today's entry decisions (if market is open)
5. **`trades.csv` (last ~20 rows)** — recent trade history with P&L and strategy notes

From those five files you can answer: what's open, what happened today, is the system healthy. Do not trust anything remembered from a previous conversation — verify against the files.

## The pipeline in one paragraph

`orchestrator.py` is the brain. It runs in modes selected by flags: `--regime` decides market mood (bullish/sideways/bearish), `--scan` finds setups across 5 strategies, `--validate` backtests them before trusting signals, `--execute` places orders, `--monitor` trails stops and triggers exits, `--report` shows portfolio state, `--edge` shows which strategies are actually earning. With no flag, it runs the full pipeline: Regime → Validate → Scan → Filter → Execute → Monitor → Rebalance → Report. The shell wrappers (`at_open.sh`, `monitor.sh`, `eod.sh`) call the orchestrator with the right flags for their time slot.

## The 5 scanner strategies

Listed by the `strategy` label each one tags onto signals:

- **PULLBACK** — buy strong uptrends on a pullback to the 21 EMA when RSI is still healthy
- **BREAKOUT** — buy confirmed breakouts from a consolidation pattern with rising volume
- **MA_BOUNCE** — buy bounces off the 50-day moving average in an established uptrend
- **SECTOR_MOMENTUM** — buy sector ETFs (XLE, XLK, XLRE, etc.) when sector momentum is accelerating
- **POWERX** — triple-confirm momentum using RSI(7), MACD histogram, and Stochastic %K > %D (Rob Hoffman's PowerX setup, modified)

There are also standalone strategies (`trailing_ladder.py`, `copy_trader.py`, `wheel_strategy.py`) that live outside `scanner.py`. These are newer additions and may or may not be wired into the main pipeline — check before assuming.

## Schedule (launchd is authoritative)

Three launchd agents in `~/Library/LaunchAgents/` handle all automation. Cron was previously duplicating these jobs; cron has been removed as of 2026-04-10. Do NOT reinstall cron.

| Time (CEST) | Time (ET) | Agent | Script | Purpose |
|---|---|---|---|---|
| 15:25 daily | 09:25 | `com.bopeterlaanen.trading.at_open` | `at_open.sh` | Wait for open, scan, filter, enter up to 6 trades |
| Every 5 min | Every 5 min | `com.bopeterlaanen.trading.monitor` | `monitor.sh` | Trail stops, partial/full exits. Silent no-op when market closed. |
| 22:10 daily | 16:10 | `com.bopeterlaanen.trading.eod` | `eod.sh` | Learning loop autopsy of closed trades, daily + weekly reports |

US market hours: 15:30–22:00 CEST / 09:30–16:00 ET, Mon–Fri.

**Verify schedule is loaded:** `launchctl list | grep trading` — should show all three.
**Pause schedule:** `launchctl unload ~/Library/LaunchAgents/com.bopeterlaanen.trading.*.plist`
**Resume schedule:** `launchctl load ~/Library/LaunchAgents/com.bopeterlaanen.trading.*.plist`

## Environment

API credentials come from environment variables set in `~/.zshrc`:
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`

Paper mode is hardcoded in `config.py` via `alpaca_paper: bool = True`. Do NOT flip this to live without explicit user confirmation.

## Git and file layout

- Repo is standalone at `/Users/bopeterlaanen/trading/.git` (initialized 2026-04-10). It is NOT part of any parent repo.
- `git status` inside this directory must show only `/Users/bopeterlaanen/trading` as the toplevel. If it shows anything else, you're in the wrong place — do not commit.
- **Tracked:** source code, shell scripts, config.py, requirements.txt, planning docs, `watchlist.json`, `.planning/codebase/`
- **Gitignored:** `positions.json`, `order_log.json`, `trades.csv`, `portfolio_value.csv`, `learning_state.json`, `edge_tracker.json`, `signals.csv`, `last_run.json`, `logs/`, `__pycache__/`, secrets, generated HTML/PDF reports
- Audit trail files (trades/orders/portfolio) are intentionally local-only per user preference

## Making changes safely

The monitor runs every 5 minutes during market hours (15:30–22:00 CEST). Any change to a Python file that breaks an import, renames a function, or moves a file will cause the next scheduled run to fail and you may miss exits on open positions.

**Before making code changes during market hours:**
1. Check if market is open: `TZ=America/New_York date` — if between 09:30 and 16:00 ET Mon–Fri, market is open
2. If open, prefer small, isolated edits. Avoid anything that touches imports or file paths.
3. For risky changes (file moves, renames, refactors): pause the scheduler, verify `python test_simulation.py` passes, then resume.

**The safe window** for risky changes is after 22:10 CEST (post-eod) until 15:25 the next trading day, and all weekend.

## Routine commands

Run these from inside the trading directory with Python 3.11+:

```bash
python test_simulation.py              # Offline end-to-end test, synthetic data
python orchestrator.py --regime        # Just the regime check
python orchestrator.py --scan          # Just the scanner (no orders)
python orchestrator.py --report        # Portfolio dashboard
python orchestrator.py --edge          # Strategy performance
python orchestrator.py                 # Full pipeline (places orders!)
```

For the full list of strategy-specific runners, see `SETUP-GUIDE.md`.

## What the user wants from you in a session

When a session starts fresh, don't ask "what do you want to do?" — do a quick status check first and present findings, then ask. Specifically:

1. Read the 5 state files listed above
2. Summarize in 3–4 sentences: what's open, today's P&L (realized + unrealized), system health (any errors in logs?), whether the scheduler is loaded
3. Ask what they want to focus on

On Fridays (or when asked for a weekly brief), also:
- Count trades this week (from `trades.csv`)
- Highlight which strategies won vs lost
- Flag any strategies that edge_tracker auto-disabled
- Note goal progress: current portfolio value vs the $10K→$100K trajectory

Slash commands in `.claude/commands/` provide shortcuts for common routines — see what's there.

## What NOT to do

- Don't flip `alpaca_paper` to `False` without explicit user permission.
- Don't commit `positions.json`, `order_log.json`, `trades.csv`, `portfolio_value.csv`, or any `.json` state file. They're gitignored for a reason.
- Don't reinstall cron. Launchd is the one and only scheduler.
- Don't reorganize file paths during market hours.
- Don't trust prior-session claims about bug fixes or strategy changes without verifying them in the actual Python code (grep for the behavior).
- Don't hardcode API keys anywhere. They come from environment variables only.

## Planning docs in this repo

- `TRADING-PLAN.md` — aspirational roadmap ($10K→$100K). Read it for goals but know the 10x target has a 5-10% probability per the doc itself.
- `SETUP-GUIDE.md` — how to install and run manually. Some parts reference the old `scheduler.py` Python-level scheduler — the OS-level launchd is authoritative now.
- `AUTOMATION-PLAN.md` — proposes GitHub Actions or VPS. Neither is what's running. Stale, kept for reference.
- `IMPROVEMENT-PLAN.md` — ongoing improvements list
- `CONCEPTS.md` — plain-language glossary of trading terms used in this codebase
- `.planning/codebase/` — architecture, conventions, stack, structure, testing, integrations maps

## Summary: the first 30 seconds of a session

```
1. cat positions.json
2. tail -50 order_log.json
3. tail -50 logs/launchd_monitor.log
4. launchctl list | grep trading
5. TZ=America/New_York date
→ Present summary, ask what user wants
```
