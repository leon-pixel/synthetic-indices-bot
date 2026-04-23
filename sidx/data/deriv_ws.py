from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class DerivWebSocket:
    """Minimal Deriv WS client: background reader + queued inbound JSON."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.ws: WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task[None] | None = None
        self._inbox: asyncio.Queue[dict] = asyncio.Queue()
        self._closed = asyncio.Event()

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20)
        self._closed.clear()
        self._recv_task = asyncio.create_task(self._reader_loop())

    async def close(self) -> None:
        self._closed.set()
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
        self.ws = None

    async def _reader_loop(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._inbox.put(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("reader loop failed")

    async def send(self, payload: dict) -> None:
        if not self.ws:
            raise RuntimeError("not connected")
        await self.ws.send(json.dumps(payload))

    async def recv(self) -> dict:
        return await asyncio.wait_for(self._inbox.get(), timeout=120.0)


async def authorize(ws: DerivWebSocket, token: str) -> dict:
    await ws.send({"authorize": token})
    while True:
        msg = await ws.recv()
        if "authorize" in msg and isinstance(msg["authorize"], dict):
            return msg["authorize"]
        if msg.get("error"):
            raise RuntimeError(str(msg["error"]))
