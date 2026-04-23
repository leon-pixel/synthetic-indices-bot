from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sidx.config import BotConfig, StrategyConfig
from sidx.execution import DerivExecution, OrderResult, SimulatedExecution
from sidx.logging_utils import JsonlLogger


Side = Literal["BUY", "SELL"]


@dataclass
class OpenPosition:
    contract_id: str
    side: Side
    entry_price: float
    opened_at: datetime
    tp: float
    sl: float
    max_exit_ts: datetime
    stall_check_bars: int
    atr_entry: float


class TradeManager:
    """
    Live/paper helper: one open position at a time; TP/SL/time/stall enforced on M1 closes + tick mid.
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
                "opened_at": p.opened_at.isoformat(),
                "tp": p.tp,
                "sl": p.sl,
                "max_exit_ts": p.max_exit_ts.isoformat(),
                "stall_check_bars": p.stall_check_bars,
                "atr_entry": p.atr_entry,
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
            opened_at=datetime.fromisoformat(op["opened_at"]),
            tp=float(op["tp"]),
            sl=float(op["sl"]),
            max_exit_ts=datetime.fromisoformat(op["max_exit_ts"]),
            stall_check_bars=int(op.get("stall_check_bars", self.bot.strategy.min_hold_bars_for_stall)),
            atr_entry=float(op["atr_entry"]),
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

    async def try_open(self, side: Side, entry_price: float, atr_entry: float, ts: datetime) -> bool:
        if self.open_pos:
            return False
        res: OrderResult = await self.execution.open(side, entry_price)
        if not res.ok or not res.contract_id or res.buy_price is None:
            self.logger.log({"event": "open_failed", "side": side, "error": res.error})
            return False
        tp, sl, stall_bars = self.build_levels(side, res.buy_price, atr_entry, self.bot.strategy)
        max_exit = ts + timedelta(minutes=self.bot.strategy.max_hold_minutes)
        self.open_pos = OpenPosition(
            contract_id=res.contract_id,
            side=side,
            entry_price=res.buy_price,
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
                "entry": res.buy_price,
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

        res = await self.execution.close(p.contract_id, bid=l, ask=h, side=p.side)
        if not res.ok or res.buy_price is None:
            self.logger.log({"event": "close_failed", "error": res.error, "contract_id": p.contract_id})
            self.open_pos = None
            return 0.0

        fill = float(res.buy_price)
        if p.side == "BUY":
            pnl_money = self.bot.execution.stake * (fill - p.entry_price) / max(p.entry_price, 1e-9)
        else:
            pnl_money = self.bot.execution.stake * (p.entry_price - fill) / max(p.entry_price, 1e-9)
        self.logger.log(
            {
                "event": "closed",
                "side": p.side,
                "entry": p.entry_price,
                "exit": fill,
                "pnl_money": pnl_money,
                "reason": exit_reason,
                "ts": ts.isoformat(),
            }
        )
        self.open_pos = None
        return float(pnl_money)

    async def reconcile_open_position(self, ts: datetime) -> float | None:
        """
        Broker reconciliation for external closures/restarts.
        Returns pnl_money if local position was reconciled and closed.
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
        is_sold = bool(status.get("is_sold", False))
        if not is_sold:
            return None
        sell_price = float(status.get("sell_price", 0) or 0)
        buy_price = float(status.get("buy_price", p.entry_price) or p.entry_price)
        if sell_price <= 0:
            sell_price = buy_price
        if p.side == "BUY":
            pnl_money = self.bot.execution.stake * (sell_price - p.entry_price) / max(p.entry_price, 1e-9)
        else:
            pnl_money = self.bot.execution.stake * (p.entry_price - sell_price) / max(p.entry_price, 1e-9)
        self.logger.log(
            {
                "event": "closed",
                "side": p.side,
                "entry": p.entry_price,
                "exit": sell_price,
                "pnl_money": pnl_money,
                "reason": "reconcile_closed",
                "ts": ts.isoformat(),
                "contract_id": p.contract_id,
            }
        )
        self.open_pos = None
        return float(pnl_money)
