# Phase 3 — Multiplier contracts, correct PnL, tests & real-data validation

Phase 3 fixes the biggest correctness gap in the bot and adds the safety net of
an automated test suite plus CI.

## 1. Why the execution model changed

Previously the live path bought **digital CALL/PUT contracts** (fixed expiry,
all-or-nothing payout) while the strategy and backtester assumed a
**price-tracking position** with TP/SL levels. Those are fundamentally
different products: a digital option's payoff does not depend on *how far*
price moves, so the strategy's TP/SL/trailing logic was meaningless against it,
and the PnL math mixed up money amounts with price levels.

The bot now trades **Deriv multiplier contracts** (`MULTUP` for BUY,
`MULTDOWN` for SELL):

- PnL tracks the underlying: `pnl = stake × multiplier × price_change / entry_price`
- Losses are capped at the stake (you can never lose more than you paid)
- The strategy's TP/SL price levels convert cleanly to broker-side
  `limit_order` take-profit / stop-loss money amounts, sent with the proposal
- The bot still manages time exits, stall exits, and the trailing stop itself;
  the broker-side TP/SL acts as a safety net if the bot goes offline

The simulated execution and the research backtester now use the **same PnL
model** (stake × multiplier × price return, loss capped at stake, friction
applied at entry and at the determined exit level), so paper results and
backtest results are directly comparable.

### New config

```
STAKE=1.0        # money per contract = max loss per trade
MULTIPLIER=100   # Deriv leverage; valid values are symbol-specific
```

Startup validation (`--validate-startup`, on by default) now checks
`MULTUP`/`MULTDOWN` proposals. If your `MULTIPLIER` value isn't accepted for
the symbol, the error from Deriv lists the accepted values — pick one of those.

### What is still not modeled

- Deriv charges a small **commission** on multiplier contracts; the simulator
  does not model it (spread/slippage knobs partially cover it).
- Overnight/funding adjustments on positions held long (irrelevant here: max
  hold is minutes).

## 2. Real-data validation

Tick history on Deriv only goes back ~1 day, but **M1 candle history goes back
90+ days** and is public (no token needed). The backtester can now use it:

```bash
# 30 days of real R_75 M1 candles
python -m sidx.research.run_backtest --fetch-candles --days 30 --out-dir reports/validation_30d

# 90 days
python -m sidx.research.run_backtest --fetch-candles --days 90 --out-dir reports/validation_90d

# walk-forward robustness check (4 folds with RSI grid search)
python -m sidx.research.run_backtest --fetch-candles --days 30 --walk-forward 4 --out-dir reports/wf
```

The fetched candles are cached to `m1_cache.csv` in the output directory.

Also fixed while validating: the tick-history request sent `"subscribe": 0`,
which the Deriv API rejects — the field must be omitted. The `--fetch` path
never actually worked against the real API before this.

## 3. Tests & CI

`tests/` contains a pytest suite covering:

| File | Covers |
| --- | --- |
| `test_candles.py` | tick→OHLCV determinism, M1/M5 alignment, duplicate ticks |
| `test_indicators.py` | EMA/RSI/ATR/quantile sanity and bounds |
| `test_strategy.py` | BUY/SELL/none rules, ATR regime filter, warmup guard |
| `test_risk.py` | session hours, cooldown, trade caps, loss halts, day rollover, persistence |
| `test_trade_manager.py` | open levels, TP/SL/time/stall/trailing exits, loss cap at stake, state roundtrip |
| `test_state_store.py` | atomic state save/load, corrupt-file tolerance |
| `test_simulation.py` | end-to-end backtest on planted setups, loss capping, summary metrics |

Run locally:

```bash
pip install -r requirements-dev.txt
pytest -q
```

GitHub Actions (`.github/workflows/ci.yml`) runs the suite on Python 3.9 and
3.11 plus a smoke backtest on every push and pull request.
