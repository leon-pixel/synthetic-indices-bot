from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import websockets

from sidx.config import BotConfig, ExecutionConfig

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of opening a position.

    entry_price is the underlying spot reference (NOT money);
    stake_paid is the money debited for the contract.
    """

    ok: bool
    contract_id: str | None
    entry_price: float | None
    stake_paid: float | None
    error: str | None = None


@dataclass
class CloseResult:
    """Result of closing a position.

    pnl_money is realized profit/loss in account currency.
    exit_price is the underlying spot at exit when known (sim), else None.
    """

    ok: bool
    contract_id: str | None
    exit_price: float | None
    pnl_money: float | None
    error: str | None = None


class SimulatedExecution:
    """
    Models Deriv multiplier PnL: pnl = stake * multiplier * signed price return,
    with spread/slippage friction applied to entry and exit fills.
    """

    def __init__(self, cfg: ExecutionConfig) -> None:
        self.cfg = cfg
        self._i = 0

    async def open(
        self,
        side: str,
        entry_price_hint: float,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> OrderResult:
        self._i += 1
        slip = self.cfg.slippage_points if side == "BUY" else -self.cfg.slippage_points
        spread = self.cfg.spread_points / 2 if side == "BUY" else -self.cfg.spread_points / 2
        fill = entry_price_hint + slip + spread
        return OrderResult(
            ok=True,
            contract_id=f"sim-{self._i}",
            entry_price=float(fill),
            stake_paid=float(self.cfg.stake),
            error=None,
        )

    async def close(
        self,
        contract_id: str,
        side: str,
        entry_price: float,
        stake_paid: float,
        exit_price: float,
    ) -> CloseResult:
        # exit fill: adverse spread/slippage around the determined exit level
        if side == "BUY":
            fill = exit_price - self.cfg.spread_points / 2 - self.cfg.slippage_points
            ret = (fill - entry_price) / max(entry_price, 1e-9)
        else:
            fill = exit_price + self.cfg.spread_points / 2 + self.cfg.slippage_points
            ret = (entry_price - fill) / max(entry_price, 1e-9)
        pnl = stake_paid * float(self.cfg.multiplier) * ret
        # multiplier contracts cannot lose more than the stake
        pnl = max(pnl, -stake_paid)
        return CloseResult(ok=True, contract_id=contract_id, exit_price=float(fill), pnl_money=float(pnl), error=None)

    async def validate_contract_setup(self) -> tuple[bool, str]:
        return True, "sim_mode_no_contract_validation"

    async def get_open_contract_status(self, contract_id: str) -> dict[str, Any] | None:
        return {"contract_id": contract_id, "is_sold": False, "status": "sim_open"}


class DerivExecution:
    """
    Multiplier contracts (MULTUP/MULTDOWN): they track the underlying price
    directly, so strategy TP/SL price levels map cleanly. TP/SL are also
    attached broker-side via limit_order (converted to money amounts).
    """

    def __init__(self, bot: BotConfig) -> None:
        self.bot = bot

    async def _with_ws(self, coro):
        url = f"{self.bot.deriv.ws_url}?app_id={self.bot.deriv.app_id}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"authorize": self.bot.deriv.api_token}))
            while True:
                msg = json.loads(await ws.recv())
                if "authorize" in msg and isinstance(msg["authorize"], dict):
                    break
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
            return await coro(ws)

    def _price_distance_to_money(self, entry: float, target: float) -> float:
        """Convert a TP/SL price distance into a money amount for limit_order."""
        ex = self.bot.execution
        dist = abs(target - entry) / max(entry, 1e-9)
        return round(ex.stake * ex.multiplier * dist, 2)

    def _limit_order(self, entry_hint: float, tp_price: float | None, sl_price: float | None) -> dict[str, float]:
        out: dict[str, float] = {}
        if tp_price is not None:
            tp_money = self._price_distance_to_money(entry_hint, tp_price)
            if tp_money >= 0.01:
                out["take_profit"] = tp_money
        if sl_price is not None:
            # loss on a multiplier contract is capped at the stake
            sl_money = min(self._price_distance_to_money(entry_hint, sl_price), round(self.bot.execution.stake, 2))
            if sl_money >= 0.01:
                out["stop_loss"] = sl_money
        return out

    async def open(
        self,
        side: str,
        entry_price_hint: float,
        tp_price: float | None = None,
        sl_price: float | None = None,
    ) -> OrderResult:
        if not self.bot.deriv.api_token:
            return OrderResult(False, None, None, None, "missing DERIV_API_TOKEN")

        ctype = "MULTUP" if side == "BUY" else "MULTDOWN"
        limit_order = self._limit_order(entry_price_hint, tp_price, sl_price)

        async def inner(ws) -> OrderResult:
            req: dict[str, Any] = {
                "proposal": 1,
                "amount": float(self.bot.execution.stake),
                "basis": "stake",
                "contract_type": ctype,
                "currency": self.bot.execution.currency,
                "multiplier": int(self.bot.execution.multiplier),
                "symbol": self.bot.deriv.symbol,
                "req_id": 1,
            }
            if limit_order:
                req["limit_order"] = limit_order
            await ws.send(json.dumps(req))
            proposal_id = None
            ask_price = None
            spot = None
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return OrderResult(False, None, None, None, str(msg["error"]))
                if msg.get("msg_type") == "proposal":
                    p = msg.get("proposal") or {}
                    proposal_id = p.get("id")
                    ask_price = float(p.get("ask_price", 0) or 0)
                    spot = float(p.get("spot", 0) or 0)
                    break
            if not proposal_id:
                return OrderResult(False, None, None, None, "no proposal id")
            await ws.send(json.dumps({"buy": proposal_id, "price": ask_price, "req_id": 2}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return OrderResult(False, None, None, None, str(msg["error"]))
                if msg.get("msg_type") == "buy":
                    b = msg.get("buy") or {}
                    stake_paid = float(b.get("buy_price") or ask_price or self.bot.execution.stake)
                    entry_spot = spot if spot else float(entry_price_hint)
                    return OrderResult(True, str(b.get("contract_id")), entry_spot, stake_paid, None)

        try:
            return await self._with_ws(inner)
        except Exception as e:
            logger.exception("deriv open failed")
            return OrderResult(False, None, None, None, str(e))

    async def close(
        self,
        contract_id: str,
        side: str,
        entry_price: float,
        stake_paid: float,
        exit_price: float,
    ) -> CloseResult:
        async def inner(ws) -> CloseResult:
            # price 0 = sell at market
            await ws.send(json.dumps({"sell": contract_id, "price": 0, "req_id": 3}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return CloseResult(False, contract_id, None, None, str(msg["error"]))
                if msg.get("msg_type") == "sell":
                    s = msg.get("sell") or {}
                    sold_for = float(s.get("sold_for") or 0)
                    pnl = sold_for - float(stake_paid)
                    return CloseResult(True, contract_id, None, pnl, None)

        try:
            return await self._with_ws(inner)
        except Exception as e:
            logger.exception("deriv close failed")
            return CloseResult(False, contract_id, None, None, str(e))

    async def _proposal_check(self, ctype: str) -> tuple[bool, str]:
        async def inner(ws) -> tuple[bool, str]:
            req = {
                "proposal": 1,
                "amount": float(self.bot.execution.stake),
                "basis": "stake",
                "contract_type": ctype,
                "currency": self.bot.execution.currency,
                "multiplier": int(self.bot.execution.multiplier),
                "symbol": self.bot.deriv.symbol,
                "req_id": 90,
            }
            await ws.send(json.dumps(req))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return False, str(msg["error"])
                if msg.get("msg_type") == "proposal":
                    p = msg.get("proposal") or {}
                    if p.get("id"):
                        return True, "ok"
                    return False, "missing proposal id"

        return await self._with_ws(inner)

    async def validate_contract_setup(self) -> tuple[bool, str]:
        if not self.bot.deriv.api_token:
            return False, "missing DERIV_API_TOKEN"
        try:
            buy_ok, buy_msg = await self._proposal_check("MULTUP")
            sell_ok, sell_msg = await self._proposal_check("MULTDOWN")
            if buy_ok and sell_ok:
                return True, f"multiplier proposal validation passed (x{self.bot.execution.multiplier})"
            return False, f"multiplier proposal validation failed: MULTUP={buy_msg}; MULTDOWN={sell_msg}"
        except Exception as e:
            return False, f"proposal validation exception: {e}"

    async def get_open_contract_status(self, contract_id: str) -> dict[str, Any] | None:
        async def inner(ws) -> dict[str, Any] | None:
            await ws.send(json.dumps({"proposal_open_contract": 1, "contract_id": contract_id, "req_id": 91}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return {"error": str(msg["error"]), "contract_id": contract_id}
                if msg.get("msg_type") == "proposal_open_contract":
                    poc = msg.get("proposal_open_contract") or {}
                    if not isinstance(poc, dict):
                        return None
                    return {
                        "contract_id": str(poc.get("contract_id", contract_id)),
                        "is_sold": bool(poc.get("is_sold", False)),
                        "is_valid_to_sell": bool(poc.get("is_valid_to_sell", False)),
                        "status": str(poc.get("status", "")),
                        "sell_price": float(poc.get("sell_price", 0) or 0),
                        "buy_price": float(poc.get("buy_price", 0) or 0),
                        "profit": float(poc.get("profit", 0) or 0),
                    }

        try:
            return await self._with_ws(inner)
        except Exception as e:
            logger.exception("reconcile failed")
            return {"error": str(e), "contract_id": contract_id}


def make_execution(bot: BotConfig):
    if bot.execution.mode == "deriv":
        return DerivExecution(bot)
    return SimulatedExecution(bot.execution)
