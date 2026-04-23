from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import pandas as pd

from sidx.config import BotConfig, StrategyConfig
from sidx.risk import RiskManager
from sidx.strategy import Side, evaluate_signal


@dataclass
class _SimPos:
    side: Literal["BUY", "SELL"]
    entry_idx: int
    entry_ts: pd.Timestamp
    entry_price: float
    tp: float
    sl: float
    max_exit_ts: pd.Timestamp
    atr_entry: float
    reasons: str


def _tp_sl(side: str, entry: float, atr_entry: float, cfg: StrategyConfig) -> tuple[float, float]:
    tp_r = (cfg.tp_r_multiple_min + cfg.tp_r_multiple_max) / 2.0
    r = max(atr_entry * cfg.sl_atr_mult, 1e-9)
    if side == "BUY":
        return entry + tp_r * r, entry - r
    return entry - tp_r * r, entry + r


def _slip_exec(side: str, price: float, slip: float, spread: float) -> float:
    s = slip if side == "BUY" else -slip
    sp = spread / 2.0 if side == "BUY" else -spread / 2.0
    return float(price + s + sp)


def _exit_fill(side: str, bid: float, ask: float, slip: float, spread: float) -> float:
    if side == "BUY":
        return float(bid - spread / 2.0 - slip)
    return float(ask + spread / 2.0 - slip)


def simulate_backtest(features: pd.DataFrame, bot: BotConfig) -> pd.DataFrame:
    """
    Event-driven simulation on M1 feature frame (UTC index).
    Signal evaluated on **previous** bar close; fill at **current** bar open.
    """
    risk = RiskManager(bot.risk, starting_equity=10_000.0)
    ex = bot.execution
    strat = bot.strategy
    completed: list[dict] = []
    pos: _SimPos | None = None

    idx = features.index
    for k in range(1, len(features) - 1):
        ts = idx[k]
        row = features.iloc[k]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        if pos is not None:
            exit_reason = None
            exit_px = None
            if pos.side == "BUY":
                if l <= pos.sl:
                    exit_px, exit_reason = pos.sl, "stop_loss"
                elif h >= pos.tp:
                    exit_px, exit_reason = pos.tp, "take_profit"
            else:
                if h >= pos.sl:
                    exit_px, exit_reason = pos.sl, "stop_loss"
                elif l <= pos.tp:
                    exit_px, exit_reason = pos.tp, "take_profit"
            if exit_px is None and ts >= pos.max_exit_ts:
                exit_px, exit_reason = c, "time_exit"
            if exit_px is None and (k - pos.entry_idx) >= strat.min_hold_bars_for_stall:
                window = features.iloc[pos.entry_idx : k + 1]
                if pos.side == "BUY":
                    mfe = float(window["high"].max() - pos.entry_price)
                else:
                    mfe = float(pos.entry_price - window["low"].min())
                if mfe < strat.stall_mfe_atr_mult * max(pos.atr_entry, 1e-9):
                    exit_px, exit_reason = c, "stall_exit"

            if exit_px is not None:
                fill = _exit_fill(pos.side, bid=l, ask=h, slip=ex.slippage_points, spread=ex.spread_points)
                if pos.side == "BUY":
                    pnl_money = ex.stake * (fill - pos.entry_price) / max(pos.entry_price, 1e-9)
                else:
                    pnl_money = ex.stake * (pos.entry_price - fill) / max(pos.entry_price, 1e-9)
                risk.register_exit(ts, pnl_money)
                completed.append(
                    {
                        "entry_ts": pos.entry_ts,
                        "exit_ts": ts,
                        "side": pos.side,
                        "entry": pos.entry_price,
                        "exit": fill,
                        "pnl_money": pnl_money,
                        "exit_reason": exit_reason,
                        "hold_bars": k - pos.entry_idx,
                        "signal_reasons": pos.reasons,
                    }
                )
                pos = None

        if pos is not None:
            continue

        prev = features.iloc[k - 1]
        sig = evaluate_signal(prev, strat)
        if sig.side == Side.NONE:
            continue
        ok, _why = risk.can_trade(ts)
        if not ok:
            continue
        side: Literal["BUY", "SELL"] = "BUY" if sig.side == Side.BUY else "SELL"
        atr_entry = float(prev["atr14"])
        entry = _slip_exec(side, o, ex.slippage_points, ex.spread_points)
        tp, sl = _tp_sl(side, entry, atr_entry, strat)
        max_exit_ts = ts + timedelta(minutes=strat.max_hold_minutes)
        risk.register_entry(ts)
        pos = _SimPos(
            side=side,
            entry_idx=k,
            entry_ts=ts,
            entry_price=entry,
            tp=tp,
            sl=sl,
            max_exit_ts=max_exit_ts,
            atr_entry=atr_entry,
            reasons="|".join(sig.reasons),
        )

    return pd.DataFrame(completed)


def summarize(ledger: pd.DataFrame) -> dict:
    if ledger.empty:
        return {"trades": 0}
    trades = ledger.copy()
    wins = trades[trades["pnl_money"] > 0]
    losses = trades[trades["pnl_money"] < 0]
    gross_win = float(wins["pnl_money"].sum()) if not wins.empty else 0.0
    gross_loss = float(-losses["pnl_money"].sum()) if not losses.empty else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    pnl = trades["pnl_money"].reset_index(drop=True)
    eq = pd.concat([pd.Series([0.0], dtype="float64"), pnl], ignore_index=True).cumsum()
    dd = float((eq - eq.cummax()).min())
    return {
        "trades": int(len(trades)),
        "win_rate": float((trades["pnl_money"] > 0).mean()) if len(trades) else 0.0,
        "avg_win": float(wins["pnl_money"].mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses["pnl_money"].mean()) if not losses.empty else 0.0,
        "profit_factor": float(pf),
        "net_pnl": float(trades["pnl_money"].sum()),
        "max_drawdown_money": dd,
    }


def stress_latency(features: pd.DataFrame, bars: int) -> pd.DataFrame:
    if bars <= 0:
        return features
    return features.shift(bars).dropna(how="all")
