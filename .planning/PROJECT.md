# Trading System

## Vision
Automated algorithmic trading system running on Alpaca paper trading, targeting $10K to $100K growth through disciplined, rules-based strategies with a learning loop.

## Scope
- 5 core scanner strategies (PULLBACK, BREAKOUT, MA_BOUNCE, SECTOR_MOMENTUM, POWERX)
- Bracket order execution with broker-native stop-loss and take-profit
- 1R risk management, correlation guard, sector exposure limits
- Automated daily schedule via launchd (scan, monitor, EOD)
- Post-trade learning loop with edge tracking and auto-disable
- Paper trading only (Alpaca paper mode)

## Out of scope (v1)
- Live trading (requires explicit user approval)
- Options strategies beyond wheel (standalone)
- Multi-broker support
- Web dashboard or UI

## Collaboration Goal
Share as a public GitHub repo so friends can clone, configure with their own Alpaca keys, and paper trade. Designed for collaboration — contributors can add strategies, improve risk management, or tune parameters.

## Constraints
- Solo operator (Bo) initially, expanding to collaborators via GitHub
- macOS local execution (no cloud infra yet)
- Python 3.11+, no additional frameworks
- Alpaca paper API for all execution
- Must not trade during code changes

## Tech Stack
- Python 3.11+
- Alpaca Trade API (paper mode)
- yfinance / Yahoo Finance for data
- pandas, numpy for analysis
- launchd for scheduling (NOT cron)

## Success Criteria
- System runs autonomously Mon-Fri without errors
- Bracket orders execute and exits fire at broker
- Reconciliation catches any state drift
- Edge tracker identifies and disables losing strategies
- Weekly reports generate automatically
