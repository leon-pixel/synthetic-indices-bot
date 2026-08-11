import numpy as np
import pandas as pd

from sidx.config import BotConfig, DerivConnectionConfig, ExecutionConfig, StrategyConfig
from sidx.data.candles import m1_m5_from_ticks
from sidx.research.simulation import simulate_backtest, stress_latency, summarize
from sidx.strategy import prepare_feature_frame


def _bot(**strat_overrides) -> BotConfig:
    return BotConfig(
        deriv=DerivConnectionConfig(api_token=""),
        strategy=StrategyConfig(**strat_overrides),
        execution=ExecutionConfig(mode="sim", stake=1.0, multiplier=100),
    )


def _features_with_buy_setup() -> pd.DataFrame:
    """Hand-built M1 feature frame with one BUY signal at row 4 and a TP hit at row 6."""
    n = 15
    idx = pd.date_range("2026-01-05 10:00", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [100.05] * n,
            "low": [99.95] * n,
            "close": [100.0] * n,
            "ema50": [99.0] * n,
            "ema20": [100.0] * n,
            "rsi14": [50.0] * n,
            "atr14": [1.0] * n,
            "atr_hi": [2.0] * n,
            "atr_lo": [0.5] * n,
        },
        index=idx,
    )
    # signal bar: close > ema50, low <= ema20, rsi < buy max
    df.iloc[4, df.columns.get_loc("close")] = 100.2
    df.iloc[4, df.columns.get_loc("rsi14")] = 30.0
    # entry fills at row 5 open (100.55 after friction); tp = 101.8
    df.iloc[6, df.columns.get_loc("high")] = 102.0
    df.iloc[6, df.columns.get_loc("low")] = 100.4
    df.iloc[6, df.columns.get_loc("close")] = 101.5
    return df


def test_simulation_takes_planted_trade():
    ledger = simulate_backtest(_features_with_buy_setup(), _bot())
    assert len(ledger) == 1
    trade = ledger.iloc[0]
    assert trade["side"] == "BUY"
    assert trade["exit_reason"] == "take_profit"
    assert trade["pnl_money"] > 0
    s = summarize(ledger)
    assert s["trades"] == 1
    assert s["win_rate"] == 1.0
    assert s["net_pnl"] > 0


def test_simulation_loss_capped_at_stake():
    df = _features_with_buy_setup()
    # replace TP bar with a crash through the stop
    df.iloc[6, df.columns.get_loc("high")] = 100.1
    df.iloc[6, df.columns.get_loc("low")] = 95.0
    df.iloc[6, df.columns.get_loc("close")] = 95.5
    ledger = simulate_backtest(df, _bot())
    assert len(ledger) == 1
    assert ledger.iloc[0]["pnl_money"] >= -1.0  # never lose more than the stake


def test_summarize_empty():
    assert summarize(pd.DataFrame()) == {"trades": 0}


def test_end_to_end_from_ticks_runs():
    rng = np.random.default_rng(42)
    n = 30_000  # ~8 hours of 1s ticks
    prices = 1000 + rng.normal(0, 0.5, n).cumsum()
    ticks = pd.DataFrame({"epoch": np.arange(1767606400, 1767606400 + n), "price": prices})
    m1, m5 = m1_m5_from_ticks(ticks)
    feats = prepare_feature_frame(m1, m5, _bot().strategy)
    ledger = simulate_backtest(feats, _bot())
    summary = summarize(ledger)
    assert "trades" in summary


def test_stress_latency_shifts():
    df = _features_with_buy_setup()
    shifted = stress_latency(df, 2)
    assert len(shifted) <= len(df)
