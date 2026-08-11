# Validation findings — does the edge survive real costs?

Campaign run on 90 days of real Deriv M1 candles (May 13 – Aug 11, 2026),
$1 stake × 100 multiplier, commission modeled at Deriv's published per-symbol
rates (fraction of notional, charged once at open).

## Verdict

**The strategy has a real, broad-based gross edge — but it is roughly half the
size of the commission.** Net of realistic costs it loses money on every
volatility index tested.

| | Value |
| --- | --- |
| Gross edge per trade (R_75) | +$0.0133 |
| Commission per trade (R_75, 0.025% of notional) | −$0.0250 |
| Net expectancy per trade | −$0.0117 |
| Break-even commission rate | 0.0133% (real rate is ~2× that) |

## Evidence

1. **Commission sensitivity (R_75, 308 trades):** net PnL falls from +$4.11 at
   zero commission to −$3.59 at the real 0.025% rate. The flip happens between
   0.010% and 0.025%.
2. **Distribution:** the gross result is *not* outlier-driven. Top winner =
   1.1% of gross profits, top 5 = 5.2%; removing the top 5 winners still
   leaves +$3.13 gross. 10/14 weeks positive gross → 4/14 net.
3. **Cross-symbol:** gross profit factor > 1.0 on 4 of 5 symbols (R_10 1.17,
   R_25 1.22, R_50 0.85, R_75 1.28, R_100 1.51) — the effect generalizes —
   but all five are net-negative after their own commission. R_100 is closest
   to viable (break-even 0.0305% vs real 0.0375%).
4. **Walk-forward (8 folds, costs included):** 1/8 out-of-sample folds
   positive, total −$2.28. The earlier 2-of-4 result was small-sample noise.

## Reproduce

```bash
# sensitivity (reuses cached candles)
COMMISSION_RATE=0.00025 SPREAD_POINTS=0 SLIPPAGE_POINTS=0 \
  python -m sidx.research.run_backtest --m1-csv reports/validation_90d/m1_cache.csv --out-dir reports/net

# other symbols
COMMISSION_RATE=0.000375 python -m sidx.research.run_backtest --fetch-candles --days 90 --symbol R_100 --out-dir reports/r100

# distribution analysis
python -m sidx.research.analyze_ledger --ledger reports/net/trade_ledger.csv

# walk-forward with costs
COMMISSION_RATE=0.00025 python -m sidx.research.run_backtest --m1-csv reports/validation_90d/m1_cache.csv --walk-forward 8 --out-dir reports/wf8
```

## What would have to change

- **Trade less, win bigger.** Commission is charged per trade; raising
  edge-per-trade (stricter filters, wider TP multiples) attacks the problem
  directly. Doubling gross edge per trade is the bar on R_75.
- **Prefer R_100.** Strongest gross edge relative to its commission.
- **Verify the real commission** from a live proposal once a valid
  `DERIV_API_TOKEN` is set — the rates used here come from Deriv's published
  tables and should be confirmed per account.

Caveat: zero spread/slippage was assumed (synthetics fill at quote, entries
already lag one bar). If real fills are worse, these results are optimistic —
which only strengthens the conclusion.
