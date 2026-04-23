from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import websockets

from sidx.config import BotConfig, DerivConnectionConfig, ExecutionConfig

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    ok: bool
    contract_id: str | None
    buy_price: float | None
    error: str | None = None


class SimulatedExecution:
    def __init__(self, cfg: ExecutionConfig) -> None:
        self.cfg = cfg
        self._i = 0

    async def open(self, side: str, entry_price: float) -> OrderResult:
        self._i += 1
        slip = self.cfg.slippage_points if side == "BUY" else -self.cfg.slippage_points
        fill = entry_price + slip + (self.cfg.spread_points / 2 if side == "BUY" else -self.cfg.spread_points / 2)
        return OrderResult(ok=True, contract_id=f"sim-{self._i}", buy_price=float(fill), error=None)

    async def close(self, contract_id: str, bid: float, ask: float, side: str) -> OrderResult:
        # exit at adverse side
        slip = self.cfg.slippage_points if side == "BUY" else -self.cfg.slippage_points
        if side == "BUY":
            fill = bid - self.cfg.spread_points / 2 - slip
        else:
            fill = ask + self.cfg.spread_points / 2 - slip
        return OrderResult(ok=True, contract_id=contract_id, buy_price=float(fill), error=None)


class DerivExecution:
    """
    Minimal proposal → buy → sell flow. Contract availability is symbol-specific; errors surface to logs.
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

    async def open(self, side: str, entry_price_hint: float) -> OrderResult:
        if not self.bot.deriv.api_token:
            return OrderResult(False, None, None, "missing DERIV_API_TOKEN")

        ctype = "CALL" if side == "BUY" else "PUT"
        dur = int(
            max(
                self.bot.execution.min_contract_minutes,
                min(self.bot.execution.contract_duration_minutes, self.bot.execution.max_contract_minutes),
            )
        )

        async def inner(ws) -> OrderResult:
            req = {
                "proposal": 1,
                "amount": float(self.bot.execution.stake),
                "basis": "stake",
                "contract_type": ctype,
                "currency": self.bot.execution.currency,
                "duration": dur,
                "duration_unit": "m",
                "req_id": 1,
                "symbol": self.bot.deriv.symbol,
            }
            await ws.send(json.dumps(req))
            proposal_id = None
            ask_price = None
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return OrderResult(False, None, None, str(msg["error"]))
                if msg.get("msg_type") == "proposal":
                    p = msg.get("proposal") or {}
                    proposal_id = p.get("id")
                    ask_price = float(p.get("ask_price", 0) or 0)
                    break
            if not proposal_id:
                return OrderResult(False, None, None, "no proposal id")
            await ws.send(json.dumps({"buy": proposal_id, "price": ask_price, "req_id": 2}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return OrderResult(False, None, None, str(msg["error"]))
                if msg.get("msg_type") == "buy":
                    b = msg.get("buy") or {}
                    return OrderResult(True, str(b.get("contract_id")), float(b.get("buy_price") or ask_price), None)
            return OrderResult(False, None, None, "buy timeout")

        try:
            return await self._with_ws(inner)
        except Exception as e:
            logger.exception("deriv open failed")
            return OrderResult(False, None, None, str(e))

    async def close(self, contract_id: str, bid: float, ask: float, side: str) -> OrderResult:
        async def inner(ws) -> OrderResult:
            await ws.send(json.dumps({"sell": contract_id, "req_id": 3}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("error"):
                    return OrderResult(False, contract_id, None, str(msg["error"]))
                if msg.get("msg_type") == "sell":
                    s = msg.get("sell") or {}
                    return OrderResult(True, contract_id, float(s.get("sold_for") or 0), None)
            return OrderResult(False, contract_id, None, "sell timeout")

        try:
            return await self._with_ws(inner)
        except Exception as e:
            logger.exception("deriv close failed")
            return OrderResult(False, contract_id, None, str(e))


def make_execution(bot: BotConfig):
    if bot.execution.mode == "deriv":
        return DerivExecution(bot)
    return SimulatedExecution(bot.execution)
