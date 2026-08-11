import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from sidx.config import BotConfig, DerivConnectionConfig, ExecutionConfig, StrategyConfig
from sidx.execution import SimulatedExecution
from sidx.logging_utils import JsonlLogger
from sidx.trade_manager import TradeManager

T0 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)

EXEC = ExecutionConfig(
    mode="sim", stake=1.0, multiplier=100, commission_rate=0.0, spread_points=0.5, slippage_points=0.3
)


def _bot(strategy: StrategyConfig) -> BotConfig:
    return BotConfig(deriv=DerivConnectionConfig(api_token=""), strategy=strategy, execution=EXEC)


def _tm(tmp_path, strategy: StrategyConfig) -> TradeManager:
    bot = _bot(strategy)
    logger = JsonlLogger(tmp_path / "test.jsonl", strategy_version="test")
    return TradeManager(bot, logger, SimulatedExecution(bot.execution))


def _last_event(tm: TradeManager) -> dict:
    lines = tm.logger.path.read_text().strip().splitlines()
    return json.loads(lines[-1])


NO_TRAIL = StrategyConfig(use_trailing_stop=False)
# entry hint 100, atr 1 with defaults (tp_r avg 2.5, sl_atr_mult 0.5):
# BUY fill = 100 + 0.3 slip + 0.25 half-spread = 100.55 -> tp 101.8, sl 100.05


def test_open_sets_levels_and_stake(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    assert asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    p = tm.open_pos
    assert p is not None
    assert p.entry_price == pytest.approx(100.55)
    assert p.stake_paid == pytest.approx(1.0)
    assert p.tp == pytest.approx(101.8)
    assert p.sl == pytest.approx(100.05)


def test_take_profit_positive_pnl(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=1), 101.0, 102.0, 100.6, 101.9, 1))
    assert pnl is not None and pnl > 0
    # exit fill 101.8 - 0.55 = 101.25 -> pnl = 1 * 100 * (101.25-100.55)/100.55
    assert pnl == pytest.approx(100 * (101.25 - 100.55) / 100.55)
    assert _last_event(tm)["reason"] == "take_profit"
    assert not tm.has_position()


def test_stop_loss_capped_at_stake(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=1), 100.2, 100.3, 100.0, 100.1, 1))
    # raw pnl = 100 * (99.5-100.55)/100.55 = -1.044 -> capped at -stake
    assert pnl == pytest.approx(-1.0)
    assert _last_event(tm)["reason"] == "stop_loss"


def test_time_exit(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=9), 100.6, 100.7, 100.4, 100.6, 1))
    assert pnl is not None
    assert _last_event(tm)["reason"] == "time_exit"


def test_stall_exit(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    # after 3 bars, MFE = 100.65 - 100.55 = 0.10 < 0.15 * atr -> stall
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=3), 100.6, 100.65, 100.4, 100.5, 3))
    assert pnl is not None
    assert _last_event(tm)["reason"] == "stall_exit"


def test_trailing_stop_moves_sl(tmp_path):
    strat = StrategyConfig(
        use_trailing_stop=True,
        trailing_atr_mult=0.5,
        tp_r_multiple_min=10.0,
        tp_r_multiple_max=10.0,
        min_hold_bars_for_stall=100,
        max_hold_minutes=100,
    )
    tm = _tm(tmp_path, strat)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    p = tm.open_pos
    assert p.sl == pytest.approx(100.05)
    # close 101.2 -> profit 0.65 >= 0.5 activates trailing; sl -> entry + 0.25
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=1), 101.0, 101.3, 100.9, 101.2, 1))
    assert pnl is None
    assert tm.open_pos.trailing_activated
    assert tm.open_pos.sl == pytest.approx(100.8)
    # bar dips to the trailed stop -> stop_loss exit near breakeven, not capped
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=2), 101.0, 101.1, 100.7, 100.9, 2))
    assert pnl is not None
    assert _last_event(tm)["reason"] == "stop_loss"
    assert pnl > -1.0


def test_sell_side_take_profit(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("SELL", 100.0, 1.0, T0))
    p = tm.open_pos
    # SELL fill = 100 - 0.3 - 0.25 = 99.45 -> tp 98.2, sl 99.95
    assert p.entry_price == pytest.approx(99.45)
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=1), 99.0, 99.3, 98.0, 98.5, 1))
    assert pnl is not None and pnl > 0
    assert _last_event(tm)["reason"] == "take_profit"


def test_commission_reduces_pnl(tmp_path):
    bot = BotConfig(
        deriv=DerivConnectionConfig(api_token=""),
        strategy=NO_TRAIL,
        execution=ExecutionConfig(
            mode="sim", stake=1.0, multiplier=100, commission_rate=0.00025, spread_points=0.5, slippage_points=0.3
        ),
    )
    logger = JsonlLogger(tmp_path / "test.jsonl", strategy_version="test")
    tm = TradeManager(bot, logger, SimulatedExecution(bot.execution))
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    pnl = asyncio.run(tm.on_bar(T0 + timedelta(minutes=1), 101.0, 102.0, 100.6, 101.9, 1))
    gross = 100 * (101.25 - 100.55) / 100.55
    assert pnl == pytest.approx(gross - 100 * 0.00025)


def test_state_roundtrip(tmp_path):
    tm = _tm(tmp_path, NO_TRAIL)
    asyncio.run(tm.try_open("BUY", 100.0, 1.0, T0))
    payload = tm.dump_state()
    tm2 = _tm(tmp_path, NO_TRAIL)
    tm2.load_state(payload)
    assert tm2.dump_state() == payload
    assert tm2.open_pos.stake_paid == pytest.approx(1.0)
