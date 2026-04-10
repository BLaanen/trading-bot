# Active Hypotheses

These are beliefs we're testing with real trade data. Each hypothesis has:
- **Claim**: what we believe is true
- **Test**: how we'll measure it
- **Status**: accumulating data / confirmed / rejected
- **Evidence**: trade-by-trade results

## H1: Pullback setups work best in NEUTRAL regime

- **Claim**: PULLBACK strategy has higher win rate in NEUTRAL vs BULL regime
- **Test**: compare win rate of PULLBACK trades tagged NEUTRAL vs BULL after 10+ of each
- **Status**: accumulating data
- **Evidence**: TBD

## H2: Energy sector correlation guard is too strict

- **Claim**: Allowing 3 Energy positions (vs 2) would improve returns when Energy is trending
- **Test**: backtest with max_sector_exposure=3 on historical energy rallies
- **Status**: untested
- **Evidence**: TBD

## H3: 10-minute post-open wait improves fills

- **Claim**: Waiting 10 minutes after market open reduces slippage vs market-open fills
- **Test**: compare avg slippage on immediate-open fills vs +10min fills
- **Status**: accumulating data
- **Evidence**: TBD (need to log slippage per fill)

## H4: Target hit rate predicts strategy edge

- **Claim**: A strategy where >40% of trades touch their target is a valid edge
- **Test**: compute target-touch-rate per strategy, correlate with total R
- **Status**: needs implementation
- **Evidence**: TBD

## H5: Paper trading is free data — explore aggressively

- **Claim**: In paper mode, running MORE strategies (even marginal ones) generates more data to learn from
- **Test**: enable all 5 strategies in all regimes for 2 weeks, measure which actually produce edge
- **Status**: proposed change to config
- **Evidence**: TBD

## Adding New Hypotheses

When you notice a pattern, add a hypothesis here. The learning loop will keep an eye on it.
