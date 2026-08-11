import pandas as pd

from sidx.data.candles import m1_m5_from_ticks, m5_from_m1, ticks_to_ohlcv


def _ticks(n: int) -> pd.DataFrame:
    return pd.DataFrame({"epoch": range(n), "price": [100.0 + i * 0.01 for i in range(n)]})


def test_ticks_to_ohlcv_left_labeled_bars():
    m1 = ticks_to_ohlcv(_ticks(180), "1min")
    assert len(m1) == 3
    first = m1.iloc[0]
    assert first["open"] == 100.0
    assert first["close"] == 100.0 + 59 * 0.01
    assert first["high"] == first["close"]
    assert first["low"] == first["open"]
    assert first["volume"] == 60
    assert m1.index[0] == pd.Timestamp("1970-01-01 00:00:00", tz="UTC")


def test_m1_m5_alignment():
    m1, m5 = m1_m5_from_ticks(_ticks(600))
    assert len(m1) == 10
    assert len(m5) == 2
    # M5 bar aggregates the same ticks as its five M1 bars
    assert m5.iloc[0]["open"] == m1.iloc[0]["open"]
    assert m5.iloc[0]["close"] == m1.iloc[4]["close"]
    assert m5.iloc[0]["volume"] == m1.iloc[:5]["volume"].sum()


def test_m5_from_m1_matches_direct_aggregation():
    m1, m5_direct = m1_m5_from_ticks(_ticks(600))
    m5_resampled = m5_from_m1(m1)
    pd.testing.assert_frame_equal(m5_direct, m5_resampled, check_dtype=False)


def test_empty_and_duplicate_ticks():
    empty = ticks_to_ohlcv(pd.DataFrame(columns=["epoch", "price"]))
    assert empty.empty
    dup = pd.DataFrame({"epoch": [0, 0, 1], "price": [1.0, 2.0, 3.0]})
    m1 = ticks_to_ohlcv(dup, "1min")
    # duplicate timestamp: last tick wins
    assert m1.iloc[0]["open"] == 2.0
    assert m1.iloc[0]["volume"] == 2
