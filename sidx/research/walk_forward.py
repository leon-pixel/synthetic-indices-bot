from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pandas as pd

from sidx.config import BotConfig, StrategyConfig
from sidx.research.simulation import simulate_backtest, summarize
from sidx.strategy import prepare_feature_frame


def time_splits(index: pd.DatetimeIndex, n_folds: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if n_folds < 2 or len(index) < n_folds * 50:
        return [(index.min(), index.max())]
    edges = pd.date_range(start=index.min(), end=index.max(), periods=n_folds + 1, tz="UTC")
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def masks_for_fold(
    idx: pd.DatetimeIndex,
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    test_fold: int,
) -> tuple[pd.Series, pd.Series]:
    train = pd.Series(False, index=idx)
    test = pd.Series(False, index=idx)
    for i, (a, b) in enumerate(windows):
        seg = (idx >= a) & (idx < b)
        if i == test_fold:
            test |= seg
        else:
            train |= seg
    return train, test


def grid_search_rsi(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    base: BotConfig,
    rsi_buy_grid: Iterable[float],
    rsi_sell_grid: Iterable[float],
    train_mask: pd.Series,
    test_mask: pd.Series,
) -> tuple[StrategyConfig, dict, dict]:
    best_score = float("-inf")
    best_strat = base.strategy
    for rb in rsi_buy_grid:
        for rs in rsi_sell_grid:
            strat = replace(base.strategy, rsi_buy_max=float(rb), rsi_sell_min=float(rs))
            bot = replace(base, strategy=strat)
            feats = prepare_feature_frame(m1, m5, strat)
            tr = feats.loc[train_mask.reindex(feats.index).fillna(False)]
            if len(tr) < 200:
                continue
            led = simulate_backtest(tr, bot)
            summ = summarize(led)
            pf = float(summ.get("profit_factor", 0.0))
            trades = int(summ.get("trades", 0))
            score = pf if trades >= 5 else -1.0
            if score > best_score:
                best_score = score
                best_strat = strat

    if best_score == float("-inf"):
        best_strat = base.strategy

    bot_best = replace(base, strategy=best_strat)
    feats = prepare_feature_frame(m1, m5, best_strat)
    train_led = simulate_backtest(feats.loc[train_mask.reindex(feats.index).fillna(False)], bot_best)
    test_led = simulate_backtest(feats.loc[test_mask.reindex(feats.index).fillna(False)], bot_best)
    return best_strat, summarize(train_led), summarize(test_led)
