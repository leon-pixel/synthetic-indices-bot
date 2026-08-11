from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sidx.config import BotConfig, StrategyConfig
from sidx.execution import CloseResult, DerivExecution, OrderResult, SimulatedExecution
from sidx.logging_utils import JsonlLogger


Side = Literal["BUY", "SELL"]


@dataclass
class OpenPosition:
    contract_id: str
    side: Side
    entry_price: float  # underlying spot at entry
    stake_paid: float  # money debited for the contract
    opened_at: datetime
    tp: float
    sl: float
    max_exit_ts: datetime
    stall_check_bars: int
    atr_entry: float
    trailing_activated: bool = False


class TradeManager:
    """
    Live/paper helper: one open position at a time; TP/SL/time/stall/trailing
    enforced on M1 closes. Mirrors the backtest exit model in research/simulation.py.
    """

    def __init__(self, bot: BotConfig, logger: JsonlLogger, execution: SimulatedExecution | DerivExecution) -> None:
        self.bot = bot
        self.logger = logger
        self.execution = execution
        self.open_pos: OpenPosition | None = None

    def has_position(self) -> bool:
        return self.open_pos is not None

    def dump_state(self) -> dict[str, Any]:
        p = self.open_pos
        if not p:
            return {"open_pos": None}
        return {
            "open_pos": {
                "contract_id": p.contract_id,
                "side": p.side,
                "entry_price": p.entry_price,
                "stake_paid": p.stake_paid,
                "opened_at": p.opened_at.isoformat(),
                "tp": p.tp,
                "sl": p.sl,
                "max_exit_ts": p.max_exit_ts.isoformat(),
                "stall_check_bars": p.stall_check_bars,
                "atr_entry": p.atr_entry,
                "trailing_activated": p.trailing_activated,
            }
        }

    def load_state(self, payload: dict[str, Any]) -> None:
        op = payload.get("open_pos")
        if not isinstance(op, dict):
            self.open_pos = None
            return
        self.open_pos = OpenPosition(
            contract_id=str(op["contract_id"]),
            side=str(op["side"]),  # type: ignore[arg-type]
            entry_price=float(op["entry_price"]),
            stake_paid=float(op.get("stake_paid", self.bot.execution.stake)),
            opened_at=datetime.fromisoformat(op["opened_at"]),
            tp=float(op["tp"]),
            sl=float(op["sl"]),
            max_exit_ts=datetime.fromisoformat(op["max_exit_ts"]),
            stall_check_bars=int(op.get("stall_check_bars", self.bot.strategy.min_hold_bars_for_stall)),
            atr_entry=float(op["atr_entry"]),
            trailing_activated=bool(op.get("trailing_activated", False)),
        )

    def build_levels(self, side: Side, entry: float, atr_entry: float, strat: StrategyConfig) -> tuple[float, float, int]:
        tp_r = (strat.tp_r_multiple_min + strat.tp_r_multiple_max) / 2.0
        r = max(atr_entry * strat.sl_atr_mult, 1e-9)
        if side == "BUY":
            tp = entry + tp_r * r
            sl = entry - r
        else:
            tp = entry - tp_r * r
            sl = entry + r
        stall_bars = int(strat.min_hold_bars_for_stall)
        return tp, sl, stall_bars

    def _update_trailing(self, p: OpenPosition, close_price: float) -> None:
        """Mirror of research/simulation.py trailing: once price moves
        trailing_atr_mult * ATR in favor, move SL to breakeven + 0.5R (one-shot)."""
        strat = self.bot.strategy
        if not strat.use_trailing_stop or p.trailing_activated:
            return
        if p.side == "BUY":
            profit = close_price - p.entry_price
        else:
            profit = p.entry_price - close_price
        if profit >= p.atr_entry * strat.trailing_atr_mult:
            offset = 0.5 * p.atr_entry * strat.sl_atr_mult
            p.sl = p.entry_price + offset if p.side == "BUY" else p.entry_price - offset
            p.trailing_activated = True

    async def try_open(self, side: Side, entry_price: float, atr_entry: float, ts: datetime) -> bool:
        if self.open_pos:
            return False
        # provisional levels from the entry hint, sent broker-side as limit_order
        prov_tp, prov_sl, _ = self.build_levels(side, entry_price, atr_entry, self.bot.strategy)
        res: OrderResult = await self.execution.open(side, entry_price, tp_price=prov_tp, sl_price=prov_sl)
        if not res.ok or not res.contract_id or res.entry_price is None:
            self.logger.log({"event": "open_failed", "side": side, "error": res.error})
            return False
        entry = float(res.entry_price)
        tp, sl, stall_bars = self.build_levels(side, entry, atr_entry, self.bot.strategy)
        max_exit = ts + timedelta(minutes=self.bot.strategy.max_hold_minutes)
        self.open_pos = OpenPosition(
            contract_id=res.contract_id,
            side=side,
            entry_price=entry,
            stake_paid=float(res.stake_paid or self.bot.execution.stake),
            opened_at=ts,
            tp=tp,
            sl=sl,
            max_exit_ts=max_exit,
            stall_check_bars=stall_bars,
            atr_entry=atr_entry,
        )
        self.logger.log(
            {
                "event": "opened",
                "side": side,
                "entry": entry,
                "stake": self.open_pos.stake_paid,
                "tp": tp,
                "sl": sl,
                "contract_id": res.contract_id,
                "ts": ts.isoformat(),
            }
        )
        return True

    async def on_bar(
        self,
        ts: datetime,
        o: float,
        h: float,
        l: float,
        c: float,
        bars_since_entry: int,
    ) -> float | None:
        """
        Process M1 bar; returns realized pnl_money if closed else None.
        """
        p = self.open_pos
        if not p:
            return None

        self._update_trailing(p, c)

        exit_reason = None
        exit_price = None
        if p.side == "BUY":
            if l <= p.sl:
                exit_price, exit_reason = p.sl, "stop_loss"
            elif h >= p.tp:
                exit_price, exit_reason = p.tp, "take_profit"
        else:
            if h >= p.sl:
                exit_price, exit_reason = p.sl, "stop_loss"
            elif l <= p.tp:
                exit_price, exit_reason = p.tp, "take_profit"
        if exit_price is None and ts >= p.max_exit_ts:
            exit_price, exit_reason = c, "time_exit"
        # stall: after N bars, if favorable excursion too small
        if exit_price is None and bars_since_entry >= p.stall_check_bars:
            if p.side == "BUY":
                mfe = h - p.entry_price
            else:
                mfe = p.entry_price - l
            if mfe < self.bot.strategy.stall_mfe_atr_mult * max(p.atr_entry, 1e-9):
                exit_price, exit_reason = c, "stall_exit"

        if exit_price is None:
            return None

        res: CloseResult = await self.execution.close(
            p.contract_id,
            side=p.side,
            entry_price=p.entry_price,
            stake_paid=p.stake_paid,
            exit_price=float(exit_price),
        )
        if not res.ok or res.pnl_money is None:
            self.logger.log({"event": "close_failed", "error": res.error, "contract_id": p.contract_id})
            self.open_pos = None
            return 0.0

        pnl_money = float(res.pnl_money)
        self.logger.log(
            {
                "event": "closed",
                "side": p.side,
                "entry": p.entry_price,
                "exit": res.exit_price,
                "pnl_money": pnl_money,
                "reason": exit_reason,
                "ts": ts.isoformat(),
                "contract_id": p.contract_id,
            }
        )
        self.open_pos = None
        return pnl_money

    async def reconcile_open_position(self, ts: datetime) -> float | None:
        """
        Broker reconciliation for external closures/restarts (e.g. broker-side
        TP/SL on the multiplier contract fired). Returns pnl_money if the local
        position was reconciled and closed.
        """
        p = self.open_pos
        if not p:
            return None
        getter = getattr(self.execution, "get_open_contract_status", None)
        if not callable(getter):
            return None
        status = await getter(p.contract_id)
        if not status:
            return None
        if status.get("error"):
            self.logger.log({"event": "reconcile_error", "contract_id": p.contract_id, "error": status.get("error")})
            return None
        if not bool(status.get("is_sold", False)):
            return None
        # Deriv reports realized profit directly; trust it over price math.
        profit = status.get("profit")
        if profit is not None:
            pnl_money = float(profit)
        else:
            sold_for = float(status.get("sell_price", 0) or 0)
            pnl_money = sold_for - p.stake_paid if sold_for > 0 else 0.0
        self.logger.log(
            {
                "event": "closed",
                "side": p.side,
                "entry": p.entry_price,
                "exit": float(status.get("sell_price", 0) or 0) or None,
                "pnl_money": pnl_money,
                "reason": "reconcile_closed",
                "ts": ts.isoformat(),
                "contract_id": p.contract_id,
            }
        )
        self.open_pos = None
        return float(pnl_money)
