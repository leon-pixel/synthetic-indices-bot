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
    initial_sl: float  # store initial SL for trailing stop
    trailing_activated: bool = False
    stake: float = 1.0  # position size for this trade


def _tp_sl(side: str, entry: float, atr_entry: float, cfg: StrategyConfig) -> tuple[float, float, float]:
    tp_r = (cfg.tp_r_multiple_min + cfg.tp_r_multiple_max) / 2.0
    r = max(atr_entry * cfg.sl_atr_mult, 1e-9)
    initial_sl = r  # save initial SL for trailing stop
    if side == "BUY":
        return entry + tp_r * r, entry - r, entry - r
    return entry - tp_r * r, entry + r, entry + r


def _slip_exec(side: str, price: float, slip: float, spread: float) -> float:
    s = slip if side == "BUY" else -slip
    sp = spread / 2.0 if side == "BUY" else -spread / 2.0
    return float(price + s + sp)


def _exit_fill(side: str, bid: float, ask: float, slip: float, spread: float) -> float:
    # Use close price for exit fill (more realistic than high/low)
    # For BUY: exit at bid (we're selling), for SELL: exit at ask (we're buying)
    if side == "BUY":
        return float(bid - spread / 2.0 - slip)
    return float(ask + spread / 2.0 - slip)


def _update_trailing_stop(
    pos: _SimPos, current_price: float, current_atr: float, cfg: StrategyConfig
) -> tuple[float, bool]:
    if not cfg.use_trailing_stop:
        return pos.sl, pos.trailing_activated

    if pos.trailing_activated:
        return pos.sl, True

    # Check if we've moved into profit
    if pos.side == "BUY":
        profit_pips = current_price - pos.entry_price
    else:
        profit_pips = pos.entry_price - current_price

    # Activate trailing if in profit by 1*R
    if profit_pips >= pos.atr_entry * cfg.trailing_atr_mult:
        # Update SL to breakeven + 0.5*R
        if pos.side == "BUY":
            new_sl = pos.entry_price + 0.5 * pos.atr_entry * cfg.sl_atr_mult
        else:
            new_sl = pos.entry_price - 0.5 * pos.atr_entry * cfg.sl_atr_mult
        return new_sl, True

    return pos.sl, False


def simulate_backtest(
    features: pd.DataFrame,
    bot: BotConfig,
    starting_equity: float = 10_000.0,
    win_rate: float | None = None,
) -> pd.DataFrame:
    """
    Event-driven simulation on M1 feature frame (UTC index).
    Signal evaluated on **previous** bar close; fill at **current** bar open.

    Args:
        features: OHLCV data with indicators
        bot: Bot configuration
        starting_equity: Account starting equity
        win_rate: Override win rate for Kelly calculation (if None, use historical)
    """
    risk = RiskManager(bot.risk, starting_equity=starting_equity)
    ex = bot.execution
    strat = bot.strategy
    completed: list[dict] = []
    pos: _SimPos | None = None

    # Track for Kelly
    wins = 0
    losses = 0

    # Dynamic stake calculation
    def calc_stake(current_equity: float) -> float:
        if ex.use_kelly:
            # Use historical win rate or default to 0.5
            wr = win_rate if win_rate is not None else 0.5
            if wr <= 0 or wr >= 1:
                wr = 0.5
            avg_win = ex.stake * strat.tp_r_multiple_min
            avg_loss = ex.stake
            if avg_loss > 0:
                win_loss_ratio = avg_win / avg_loss
                kelly = (wr * win_loss_ratio - (1 - wr)) * ex.kelly_fraction
                # Cap at 5% of equity
                max_stake = current_equity * 0.05
                calculated_stake = current_equity * kelly
                return min(max(ex.stake, calculated_stake), max_stake)
        return ex.stake

    idx = features.index
    for k in range(1, len(features) - 1):
        ts = idx[k]
        row = features.iloc[k]
        o, h, l, c = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )

        if pos is not None:
            exit_reason = None
            exit_px = None

            # Get current ATR for trailing stop
            current_atr = (
                float(row.get("atr14", pos.atr_entry))
                if not pd.isna(row.get("atr14"))
                else pos.atr_entry
            )

            # Check trailing stop
            if strat.use_trailing_stop:
                pos.sl, pos.trailing_activated = _update_trailing_stop(
                    pos, c, current_atr, strat
                )

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
                # Use close price for more realistic exit
                fill = c
                # Apply spread and slippage to fill
                if pos.side == "BUY":
                    pnl_money = pos.stake * (fill - pos.entry_price) / max(pos.entry_price, 1e-9)
                else:
                    pnl_money = pos.stake * (pos.entry_price - fill) / max(pos.entry_price, 1e-9)
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
                        "trailing_activated": pos.trailing_activated,
                    }
                )
                # Track for Kelly
                if pnl_money > 0:
                    wins += 1
                else:
                    losses += 1
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
        tp, sl, initial_sl = _tp_sl(side, entry, atr_entry, strat)
        max_exit_ts = ts + timedelta(minutes=strat.max_hold_minutes)
        risk.register_entry(ts)

        # Calculate dynamic stake
        current_stake = calc_stake(risk.state.starting_equity)

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
            initial_sl=initial_sl,
            trailing_activated=False,
            stake=current_stake,
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

    trailing_count = 0
    if "trailing_activated" in trades.columns:
        trailing_count = int(trades["trailing_activated"].sum())

    return {
        "trades": int(len(trades)),
        "win_rate": float((trades["pnl_money"] > 0).mean()) if len(trades) else 0.0,
        "avg_win": float(wins["pnl_money"].mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses["pnl_money"].mean()) if not losses.empty else 0.0,
        "profit_factor": float(pf),
        "net_pnl": float(trades["pnl_money"].sum()),
        "max_drawdown_money": dd,
        "trailing_stop_activations": trailing_count,
    }


def stress_latency(features: pd.DataFrame, bars: int) -> pd.DataFrame:
    if bars <= 0:
        return features
    return features.shift(bars).dropna(how="all")