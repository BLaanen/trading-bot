# Trading Bot Improvement Plan

## Gap Analysis: Video Strategies vs Current Build

| Video Strategy | Current Status | Priority |
|---------------|---------------|----------|
| Alpaca connection + paper trading | Built (executor.py), needs API keys | P0 - Setup |
| Trailing stop with ladder buys | Trailing stops exist, NO ladder buys | P1 - Enhancement |
| Copy trading (Capitol Trades) | NOT built | P1 - New module |
| Wheel strategy (options) | NOT built | P1 - New module |
| Scheduled monitoring (cron) | NOT built (AUTOMATION-PLAN.md exists) | P1 - New module |
| Daily summaries/notifications | NOT built | P2 - Enhancement |
| Smart money / whale tracking | NOT built | P2 - New module |

## Implementation Phases

### Phase 1: Trailing Stop + Ladder Buy Enhancement
**File:** `trailing_ladder.py`
- Configurable trailing stop with percentage-based floors
- Ladder buy system: auto-buy more shares at configurable dip levels
- Floor only goes up, never down
- Integrates with existing executor.py for order placement

### Phase 2: Capitol Trades Copy Trading
**File:** `copy_trader.py`
- Scrape capitoltrades.com for politician trade data
- Rank politicians by recent performance
- Copy their buys/sells through Alpaca
- Track which politician we're following and their win rate

### Phase 3: Wheel Strategy (Options)
**File:** `wheel_strategy.py`
- Stage 1: Sell cash-secured puts (~10% below current price)
- Stage 2: If assigned, sell covered calls (~10% above cost basis)
- Track premium income across cycles
- Never sell puts without cash to cover assignment
- Never sell calls below cost basis
- Early close at 50% profit

### Phase 4: Scheduler
**File:** `scheduler.py`
- Run strategies on configurable intervals during market hours
- Support multiple strategies running independently
- Market hours awareness (9:30 AM - 4:00 PM ET)
- Daily summary generation at market close

### Phase 5: Notification System
**File:** `notifier.py`
- Console notifications (immediate)
- File-based daily summary
- Telegram bot integration (stub for when bot token is configured)

## Architecture Decisions
- Each new strategy is a standalone module that uses existing `executor.py` for orders
- Each module has its own state file (JSON) for persistence
- Scheduler orchestrates all strategies via a single entry point
- All modules use `data_provider.py` for market data
- All modules use `config.py` for configuration
