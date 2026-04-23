from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

import pandas as pd

from sidx.config import StrategyConfig
from sidx.indicators import atr_wilder, ema, rsi_wilder, rolling_quantile


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass(frozen=True)
class Signal:
    side: Side
    reasons: tuple[str, ...]


def prepare_feature_frame(m1: pd.DataFrame, m5: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    m1 = m1.sort_index()
    m5 = m5.sort_index().copy()
    m5["ema50"] = ema(m5["close"], cfg.ema_slow)

    left = m1.reset_index()
    left = left.rename(columns={left.columns[0]: "ts"})
    right = m5.reset_index()
    right = right.rename(columns={right.columns[0]: "ts"})
    right = right[["ts", "ema50"]].sort_values("ts")
    merged = pd.merge_asof(left.sort_values("ts"), right, on="ts", direction="backward")
    out = merged.set_index("ts").sort_index()

    c = out["close"]
    h, l = out["high"], out["low"]
    out["ema20"] = ema(c, cfg.ema_fast)
    out["rsi14"] = rsi_wilder(c, cfg.rsi_period)
    out["atr14"] = atr_wilder(h, l, c, cfg.atr_period)
    hi = rolling_quantile(out["atr14"], cfg.atr_pct_window, cfg.atr_high_pct)
    lo = rolling_quantile(out["atr14"], cfg.atr_pct_window, cfg.atr_low_pct)
    out["atr_hi"] = hi
    out["atr_lo"] = lo
    return out


def evaluate_signal(row: pd.Series, cfg: StrategyConfig) -> Signal:
    reasons: list[str] = []
    if pd.isna(row.get("ema50")) or pd.isna(row.get("ema20")) or pd.isna(row.get("rsi14")):
        return Signal(Side.NONE, ("warmup",))

    close = float(row["close"])
    low = float(row["low"])
    high = float(row["high"])
    ema50 = float(row["ema50"])
    ema20 = float(row["ema20"])
    rsi = float(row["rsi14"])
    atr = float(row["atr14"]) if not pd.isna(row["atr14"]) else float("nan")
    atr_hi = row.get("atr_hi")
    atr_lo = row.get("atr_lo")

    if pd.isna(atr) or pd.isna(atr_hi) or pd.isna(atr_lo):
        return Signal(Side.NONE, ("atr_warmup",))

    if not (float(atr_lo) <= atr <= float(atr_hi)):
        return Signal(Side.NONE, ("atr_regime",))

    # BUY
    if close > ema50 and low <= ema20 and rsi < cfg.rsi_buy_max:
        reasons.append("trend_m5_up")
        reasons.append("pullback_ema20")
        reasons.append("rsi_exhaustion_buy")
        reasons.append("atr_ok")
        return Signal(Side.BUY, tuple(reasons))

    # SELL (mirror)
    if close < ema50 and high >= ema20 and rsi > cfg.rsi_sell_min:
        reasons.append("trend_m5_down")
        reasons.append("pullback_ema20")
        reasons.append("rsi_exhaustion_sell")
        reasons.append("atr_ok")
        return Signal(Side.SELL, tuple(reasons))

    return Signal(Side.NONE, ("no_match",))


def series_signals(features: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    out: list[Literal["BUY", "SELL", "NONE"]] = []
    for _, row in features.iterrows():
        sig = evaluate_signal(row, cfg)
        out.append(sig.side.value)
    return pd.Series(out, index=features.index, name="signal")
