from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import pandas as pd
import websockets

from sidx.config import DerivConnectionConfig
from sidx.data.deriv_ws import DerivWebSocket, authorize

logger = logging.getLogger(__name__)


def _history_to_df(msg: dict[str, Any]) -> pd.DataFrame:
    hist = msg.get("history") or {}
    prices = hist.get("prices") or []
    times = hist.get("times") or []
    if len(prices) != len(times):
        raise ValueError("history prices/times length mismatch")
    epochs = [int(float(t)) for t in times]
    return pd.DataFrame({"epoch": epochs, "price": [float(p) for p in prices]})


async def fetch_ticks_history_once(
    ws: DerivWebSocket,
    symbol: str,
    end: str | int,
    count: int,
    req_id: int,
) -> pd.DataFrame:
    await ws.send(
        {
            "ticks_history": symbol,
            "style": "ticks",
            "subscribe": 0,
            "end": str(end) if end != "latest" else "latest",
            "count": int(count),
            "req_id": req_id,
        }
    )
    while True:
        msg = await ws.recv()
        if msg.get("req_id") != req_id:
            continue
        if msg.get("error"):
            raise RuntimeError(str(msg["error"]))
        if msg.get("msg_type") == "history" and "history" in msg:
            return _history_to_df(msg)
        if "history" in msg and isinstance(msg["history"], dict):
            return _history_to_df(msg)


async def fetch_ticks_history_paginated(
    cfg: DerivConnectionConfig,
    total_target: int,
    page_size: int = 5000,
) -> pd.DataFrame:
    url = f"{cfg.ws_url}?app_id={cfg.app_id}"
    ws = DerivWebSocket(url)
    await ws.connect()
    try:
        await authorize(ws, cfg.api_token)
        frames: list[pd.DataFrame] = []
        remaining = total_target
        end: str | int = "latest"
        rid = 1
        while remaining > 0:
            chunk = min(page_size, remaining)
            df = await fetch_ticks_history_once(ws, cfg.symbol, end, chunk, rid)
            rid += 1
            if df.empty:
                break
            frames.append(df)
            oldest = int(df["epoch"].min())
            end = oldest - 1
            remaining -= len(df)
            if len(df) < chunk:
                break
        if not frames:
            return pd.DataFrame(columns=["epoch", "price"])
        out = pd.concat(frames, ignore_index=True)
        out = out.sort_values("epoch").drop_duplicates(subset=["epoch", "price"]).reset_index(drop=True)
        return out
    finally:
        await ws.close()


def fetch_ticks_history_paginated_sync(cfg: DerivConnectionConfig, total_target: int) -> pd.DataFrame:
    return asyncio.run(fetch_ticks_history_paginated(cfg, total_target))


async def stream_ticks(
    cfg: DerivConnectionConfig,
    on_tick: Callable[[dict[str, Any]], Awaitable[None]],
    stop: asyncio.Event,
) -> None:
    """
    Live tick subscription. Uses a dedicated connection and parses ``msg_type == "tick"``.
    """
    url = f"{cfg.ws_url}?app_id={cfg.app_id}"
    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as websocket:
        await websocket.send(json.dumps({"authorize": cfg.api_token}))
        while True:
            raw = await websocket.recv()
            msg = json.loads(raw)
            if "authorize" in msg and isinstance(msg["authorize"], dict):
                break
            if msg.get("error"):
                raise RuntimeError(str(msg["error"]))
        await websocket.send(json.dumps({"ticks": cfg.symbol, "subscribe": 1}))
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("msg_type") != "tick":
                continue
            tick = msg.get("tick") or {}
            epoch = int(tick.get("epoch", 0))
            quote = tick.get("quote")
            if not epoch or quote is None:
                continue
            await on_tick({"epoch": epoch, "price": float(quote)})
