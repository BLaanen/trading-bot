# Automation Plan: Running the Trading System on a Schedule

## Goal

Run the trading pipeline automatically on the recommended daily schedule
so it manages the Alpaca paper trading account without manual intervention.

Two options: **GitHub Actions** (free, simplest) or **cheap VPS** ($4-6/mo, most reliable).

---

## Option A: GitHub Actions (Free Tier)

GitHub gives you 2,000 minutes/month free. Each run takes ~2-5 minutes,
so 4 runs/day × 22 trading days × 5 min = ~440 min/month. Well within free tier.

### What to build

**File: `.github/workflows/trading.yml`**

```yaml
name: Trading Pipeline

on:
  schedule:
    # All times in UTC (ET = UTC-4 during EDT, UTC-5 during EST)
    # 9:15 AM ET = 13:15 UTC (regime check + scan)
    - cron: '15 13 * * 1-5'
    # 10:00 AM ET = 14:00 UTC (full pipeline — entries)
    - cron: '0 14 * * 1-5'
    # 1:00 PM ET = 17:00 UTC (monitor — trail stops)
    - cron: '0 17 * * 1-5'
    # 3:30 PM ET = 19:30 UTC (monitor + report — end of day)
    - cron: '30 19 * * 1-5'
  workflow_dispatch:  # Manual trigger button

env:
  ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
  ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET }}

jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r trading/requirements.txt

      - name: Restore state files
        uses: actions/cache/restore@v4
        with:
          path: |
            trading/positions.json
            trading/order_log.json
            trading/last_run.json
            trading/trades.csv
            trading/portfolio_value.csv
            trading/edge_tracker.json
          key: trading-state-${{ github.run_id }}
          restore-keys: trading-state-

      - name: Determine run mode
        id: mode
        run: |
          HOUR=$(date -u +%H)
          MINUTE=$(date -u +%M)
          if [ "$HOUR" = "13" ]; then
            echo "mode=regime-scan" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "14" ]; then
            echo "mode=full" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "17" ]; then
            echo "mode=monitor" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "19" ]; then
            echo "mode=monitor-report" >> $GITHUB_OUTPUT
          else
            echo "mode=full" >> $GITHUB_OUTPUT
          fi

      - name: Run trading pipeline
        working-directory: trading
        run: |
          MODE="${{ steps.mode.outputs.mode }}"
          case $MODE in
            regime-scan)
              python orchestrator.py --regime
              python orchestrator.py --scan
              ;;
            full)
              python orchestrator.py
              ;;
            monitor)
              python orchestrator.py --monitor
              ;;
            monitor-report)
              python orchestrator.py --monitor
              python orchestrator.py --report
              ;;
          esac

      - name: Save state files
        uses: actions/cache/save@v4
        with:
          path: |
            trading/positions.json
            trading/order_log.json
            trading/last_run.json
            trading/trades.csv
            trading/portfolio_value.csv
            trading/edge_tracker.json
          key: trading-state-${{ github.run_id }}

      - name: Commit state to repo
        run: |
          git config user.name "Trading Bot"
          git config user.email "bot@trading"
          git add -f trading/positions.json trading/order_log.json \
                     trading/last_run.json trading/trades.csv \
                     trading/portfolio_value.csv trading/edge_tracker.json \
                     2>/dev/null || true
          git diff --cached --quiet || \
            git commit -m "Trading state update $(date -u +%Y-%m-%dT%H:%M)" && \
            git push
```

### Setup steps

1. Go to your repo → Settings → Secrets and variables → Actions
2. Add two repository secrets:
   - `ALPACA_API_KEY` → your paper trading API key
   - `ALPACA_API_SECRET` → your paper trading secret
3. Create the workflow file at `.github/workflows/trading.yml`
4. Push to main — the schedule starts automatically
5. You can also hit "Run workflow" manually to test

### GitHub Actions limitations

- **Cron is approximate:** GitHub can delay scheduled runs by 5-15 minutes
  during peak times. For paper trading this doesn't matter much. For live
  trading, this delay could cause missed entries.
- **State persistence:** We commit state files back to the repo after each
  run. This means positions.json, trades.csv, etc. live in the repo and
  survive across runs.
- **No real-time monitoring:** Can't react to sudden price moves between
  scheduled runs. The trailing stop system handles this — stops are placed
  with the broker, not just tracked locally.
- **Market holidays:** The cron runs Mon-Fri regardless. The pipeline
  handles this gracefully — no data = no signals = no trades.

---

## Option B: Cheap VPS ($4-6/month)

More reliable for timing. Better for eventual live trading.

### Recommended providers

| Provider | Plan | Cost | Notes |
|----------|------|------|-------|
| Hetzner | CX22 | €4.35/mo | Best value, EU or US |
| DigitalOcean | Basic | $6/mo | Simple setup |
| Vultr | Cloud Compute | $5/mo | Good US locations |
| Oracle Cloud | Always Free | $0 | Free ARM instance (limited) |

Any 1 vCPU / 1GB RAM instance is more than enough.

### Server setup script

```bash
#!/bin/bash
# server-setup.sh — Run once on a fresh Ubuntu 22.04+ VPS

# System
sudo apt update && sudo apt install -y python3.12 python3-pip git cron

# Clone repo
git clone https://github.com/BLaanen/ivar.git ~/ivar
cd ~/ivar/trading
pip install -r requirements.txt

# Set credentials
echo 'export ALPACA_API_KEY="your-key"' >> ~/.bashrc
echo 'export ALPACA_API_SECRET="your-secret"' >> ~/.bashrc
source ~/.bashrc

# Create the runner script
cat > ~/run-trading.sh << 'SCRIPT'
#!/bin/bash
source ~/.bashrc
cd ~/ivar/trading

MODE=${1:-full}

case $MODE in
  regime)
    python3 orchestrator.py --regime
    python3 orchestrator.py --scan
    ;;
  full)
    python3 orchestrator.py
    ;;
  monitor)
    python3 orchestrator.py --monitor
    ;;
  report)
    python3 orchestrator.py --monitor
    python3 orchestrator.py --report
    ;;
esac

# Push state back to repo (optional — for visibility)
cd ~/ivar
git add -f trading/positions.json trading/order_log.json \
           trading/last_run.json trading/trades.csv \
           trading/portfolio_value.csv trading/edge_tracker.json \
           2>/dev/null
git diff --cached --quiet || \
  git commit -m "State update $(date -u +%Y-%m-%dT%H:%M)" && \
  git push
SCRIPT
chmod +x ~/run-trading.sh

# Set up cron schedule (all times ET, adjust for your server timezone)
# Use: sudo timedatectl set-timezone America/New_York
(crontab -l 2>/dev/null; cat << 'CRON'
# Trading schedule (Eastern Time)
15 9  * * 1-5  ~/run-trading.sh regime  >> ~/trading.log 2>&1
0  10 * * 1-5  ~/run-trading.sh full    >> ~/trading.log 2>&1
0  13 * * 1-5  ~/run-trading.sh monitor >> ~/trading.log 2>&1
30 15 * * 1-5  ~/run-trading.sh report  >> ~/trading.log 2>&1
CRON
) | crontab -

echo "Done. Check schedule with: crontab -l"
echo "View logs with: tail -f ~/trading.log"
```

### VPS advantages over GitHub Actions

- **Exact timing:** Cron fires on the second, no 5-15 min delay
- **State is local:** No need to commit/restore state files each run
- **Always-on:** Could add intraday monitoring (every 30 min)
- **Notifications:** Easy to add email/Telegram/Discord alerts
- **Live-ready:** When you switch from paper to live, the server is
  already set up and proven reliable

---

## Option C (future): Add Notifications

Regardless of where you run it, add alerts so you know what happened:

### Telegram bot (free, easy)

```python
# notifications.py
import os, requests

def notify(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
        )
```

Hook it into the orchestrator after key events:
- New trade opened → "Bought 22 NVDA @ $195, stop $190.50, target $204"
- Partial exit → "Sold half NVDA at +2.1R (+$210)"
- Stop hit → "AAPL stopped out at -1.0R (-$100)"
- Daily summary → "Day P&L: +$150, Heat: 3.2%/6%, 4 open positions"
- Circuit breaker → "WARNING: 4 consecutive losses, pausing 3 days"

---

## Recommendation

**Start with GitHub Actions.** It's free, it's already where your repo lives,
and for paper trading the 5-15 min timing uncertainty doesn't matter. You'll
see the output in the Actions tab and state files commit to the repo.

**Move to a VPS when:**
- You're ready for live trading (timing matters more)
- You want intraday monitoring more frequently than 4x/day
- You want real-time notifications
- GitHub Actions timing delays bother you

---

## Implementation Checklist

### Phase 1: GitHub Actions (do now)
- [ ] Create `.github/workflows/trading.yml`
- [ ] Add `ALPACA_API_KEY` and `ALPACA_API_SECRET` as repo secrets
- [ ] Remove state files from `.gitignore` (they need to persist in repo)
- [ ] Test with manual workflow dispatch
- [ ] Verify paper trades appear in Alpaca dashboard
- [ ] Run for 1 week, check Actions logs daily

### Phase 2: Notifications (do after 1 week)
- [ ] Create Telegram bot via @BotFather
- [ ] Add `notifications.py` with trade alerts
- [ ] Hook into orchestrator entry/exit/circuit-breaker events
- [ ] Add notification secrets to GitHub Actions

### Phase 3: VPS migration (do when going live)
- [ ] Provision cheap VPS (Hetzner/DigitalOcean)
- [ ] Run `server-setup.sh`
- [ ] Verify cron schedule fires correctly for 1 week on paper
- [ ] Switch to live when paper results are proven

---

## Time Stops: Already Built

The system already handles stocks that go sideways and never hit
stop or target. From `edge_tracker.py:224`:

```python
def should_time_stop(entry_date, max_hold_days=15):
    """If a trade hasn't moved in 15 days, close it."""
```

The monitor step (`orchestrator.py:196`) checks every position:
- Held 15+ days AND below +0.5R → **close it** (dead money)
- Held 15+ days AND above +0.5R → **keep it** (it's working, let trail handle it)

This prevents capital from being trapped in a sideways stock. The freed-up
cash and heat capacity can go to a new, better setup.

To adjust the hold period, change `max_hold_days=15` in `orchestrator.py:196`.
Shorter (10 days) = more aggressive capital recycling.
Longer (20 days) = more patience for slower setups.
