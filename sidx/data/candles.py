from __future__ import annotations

import pandas as pd


def ticks_to_ohlcv(ticks: pd.DataFrame, rule: str = "1min") -> pd.DataFrame:
    """
    Deterministic OHLCV from tick stream.

    Expects columns: ``epoch`` (unix seconds, int/float) and ``price`` (float).
    Same function is used for historical replay and live aggregation buffers.

    Bars are left-labeled, left-closed: ``[t, t + delta)`` → timestamp ``t``.
    """
    if ticks.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = ticks.copy()
    if "epoch" not in df.columns or "price" not in df.columns:
        raise ValueError("ticks must contain epoch and price columns")

    ts = pd.to_datetime(df["epoch"], unit="s", utc=True)
    s = pd.Series(df["price"].astype(float).values, index=ts).sort_index()
    # aggregate duplicate timestamps deterministically: last tick wins for close path
    s = s.groupby(level=0).last()

    r = s.resample(rule, label="left", closed="left")
    out = pd.DataFrame(
        {
            "open": r.first(),
            "high": r.max(),
            "low": r.min(),
            "close": r.last(),
            "volume": r.count(),
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"], how="any")


def m1_m5_from_ticks(ticks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    m1 = ticks_to_ohlcv(ticks, "1min")
    m5 = ticks_to_ohlcv(ticks, "5min")
    return m1, m5


def m5_from_m1(m1: pd.DataFrame) -> pd.DataFrame:
    """Deterministic M5 OHLCV from M1 bars (for candle-based history fetches)."""
    r = m1.resample("5min", label="left", closed="left")
    out = pd.DataFrame(
        {
            "open": r["open"].first(),
            "high": r["high"].max(),
            "low": r["low"].min(),
            "close": r["close"].last(),
            "volume": r["volume"].sum(),
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"], how="any")
