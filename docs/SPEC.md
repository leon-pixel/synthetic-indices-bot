# Execution spec: Deriv synthetic indices

## Venue (locked)

- **Broker / API**: [Deriv](https://developers.deriv.com/) WebSocket API v3.
- **Source of truth for research**: Deriv `ticks_history` + the same tick→candle code path as live.
- **Paper vs live**: use a **Virtual / demo** account token for `DERIV_API_TOKEN` until metrics are stable.

## Symbols (examples)

| Internal name | Typical Deriv symbol | Notes |
|----------------|----------------------|--------|
| Volatility 75 (1s) | `R_75` | Fast synthetic; high noise — use strict filters. |
| Volatility 100 (1s) | `R_100` | Often used in examples. |
| Volatility 10 (1s) | `R_10` | Slower moves; different ATR scale. |

Confirm the exact symbol string in your Deriv account’s **Market** list before going live. Synthetic names can differ slightly by region/product.

## Contract assumptions (defaults in `sidx/config.py`)

- **Contract style**: short-dated **CALL / PUT**-style digital contracts (`contract_type`: `CALL` / `PUT`) aligned with signal direction, with `duration` + `duration_unit` in minutes.
- **Important**: not every `duration` is valid for every symbol — the API returns an error if unsupported. Treat `min_contract_minutes` / `max_contract_minutes` as **config** and validate once per symbol on demo.
- **Early exit**: when the API exposes `sell` for the purchased contract, the **Trade manager** requests `sell` for TP/SL/time exits. If `sell` is unavailable for a symbol/contract combo, the bot must **not** claim intrabar TP/SL; fall back to **hold-to-expiry** or disable live mode for that combo.

## Risk defaults (blueprint)

- Risk per trade: **0.25%–0.5%** of equity (stake sizing — implemented as configured stake cap, not auto-margin math).
- Max trades / day, max daily loss %, max consecutive losses, cooldown minutes, session windows: see `RiskConfig` in `sidx/config.py`.
- **Kill switch**: when any cap trips, `RiskManager` flips `trading_halted_until` to next UTC day (or process exit).

## TradingView parity (optional)

TradingView can differ from Deriv in **timestamp alignment**, **session cuts**, **synthetic feed vendor**, and **missing ticks**. Use TV only for **visual hypothesis generation**.

### Parity checklist (manual)

1. Overlay **M1 close** from Deriv tick replay vs TV export for the same window (sample 1–3 days).
2. Compare **RSI(14)** at bar closes; investigate if median absolute delta > ~1–2 pts.
3. Compare **EMA20/EMA50**; small differences are normal; large gaps mean feeds differ.

If parity fails: keep TV **out** of the validation path; use Python on Deriv ticks only.
