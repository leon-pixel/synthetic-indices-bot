import numpy as np
import pandas as pd

from sidx.indicators import atr_wilder, ema, rolling_quantile, rsi_wilder


def test_ema_constant_series():
    s = pd.Series([5.0] * 50)
    out = ema(s, 20)
    assert np.allclose(out, 5.0)


def test_rsi_bounds_random_walk():
    rng = np.random.default_rng(7)
    close = pd.Series(100 + rng.normal(0, 1, 500).cumsum())
    r = rsi_wilder(close, 14)
    assert r.between(0, 100).all()


def test_rsi_uptrend_is_high():
    # mostly-up series (small pullbacks keep the denominator non-zero)
    steps = [1.0 if i % 5 else -0.05 for i in range(100)]
    close = pd.Series(100 + np.cumsum(steps))
    r = rsi_wilder(close, 14)
    assert r.iloc[-1] > 65


def test_atr_positive():
    rng = np.random.default_rng(3)
    close = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    high = close + 0.5
    low = close - 0.5
    a = atr_wilder(high, low, close, 14)
    assert (a.iloc[1:] > 0).all()


def test_rolling_quantile_order():
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(0, 1, 400))
    hi = rolling_quantile(s, 100, 0.85)
    lo = rolling_quantile(s, 100, 0.15)
    valid = hi.notna() & lo.notna()
    assert (hi[valid] >= lo[valid]).all()
