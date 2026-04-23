# TradingView (Pine) ↔ Python (`sidx`) mapping

TradingView is treated as a **non-authoritative lab** unless you complete the parity checks in [SPEC.md](SPEC.md).

## Symbol

- TV chart: search the same volatility index name your broker lists (e.g. “Volatility 75 Index”).
- Python: `DERIV_SYMBOL` (e.g. `R_75`).

## Timeframes

| TV | Python |
|----|--------|
| M1 | `ticks_to_ohlcv(..., "1min")` |
| M5 | `ticks_to_ohlcv(..., "5min")` |

## Indicators (defaults)

| Concept | Pine (approx) | Python |
|---------|---------------|--------|
| EMA20 M1 | `ta.ema(close, 20)` on M1 | `sidx.indicators.ema(m1.close, 20)` |
| EMA50 M5 | `ta.ema(close, 50)` on M5 merged with `merge_asof` backward | `prepare_feature_frame` column `ema50` |
| RSI14 M1 | `ta.rsi(close, 14)` | `rsi_wilder` |
| ATR14 M1 | `ta.atr(14)` (same Wilder smoothing intent) | `atr_wilder` |
| ATR regime | Pine uses **min–max rank** over `atrWin` (see script) | Python uses **rolling quantiles** (`atr_hi` / `atr_lo`) — similar intent, not identical |

## Signals

- **BUY**: M5 `close > ema50`, M1 `low <= ema20`, `rsi < rsi_buy_max`, ATR between `atr_lo` and `atr_hi`.
- **SELL**: mirrored with `rsi > rsi_sell_min`.

Pine reference implementation: [../pine/mean_reversion_v0.pine](../pine/mean_reversion_v0.pine).

## Execution semantics

- Pine `strategy()` fills are **not** identical to Deriv contract fills, fees, or early `sell` availability.
- Any change accepted in Pine must be **ported and re-tested** in `python -m sidx.research.run_backtest` on Deriv `ticks_history` before live use.
