import pandas as pd

from sidx.config import StrategyConfig
from sidx.strategy import Side, evaluate_signal

CFG = StrategyConfig()


def _row(**overrides) -> pd.Series:
    base = {
        "close": 100.0,
        "low": 99.9,
        "high": 100.1,
        "ema50": 100.0,
        "ema20": 100.0,
        "rsi14": 50.0,
        "atr14": 1.0,
        "atr_hi": 2.0,
        "atr_lo": 0.5,
    }
    base.update(overrides)
    return pd.Series(base)


def test_buy_signal():
    row = _row(close=100.5, ema50=100.0, low=99.9, ema20=100.0, rsi14=CFG.rsi_buy_max - 1)
    sig = evaluate_signal(row, CFG)
    assert sig.side == Side.BUY
    assert "rsi_exhaustion_buy" in sig.reasons


def test_sell_signal():
    row = _row(close=99.5, ema50=100.0, high=100.1, ema20=100.0, rsi14=CFG.rsi_sell_min + 1)
    sig = evaluate_signal(row, CFG)
    assert sig.side == Side.SELL


def test_no_signal_neutral_rsi():
    row = _row(close=100.5, rsi14=50.0)
    assert evaluate_signal(row, CFG).side == Side.NONE


def test_atr_regime_blocks():
    row = _row(close=100.5, rsi14=CFG.rsi_buy_max - 1, atr14=3.0)  # above atr_hi
    sig = evaluate_signal(row, CFG)
    assert sig.side == Side.NONE
    assert sig.reasons == ("atr_regime",)


def test_warmup_blocks():
    row = _row(ema50=float("nan"))
    sig = evaluate_signal(row, CFG)
    assert sig.side == Side.NONE
    assert sig.reasons == ("warmup",)
