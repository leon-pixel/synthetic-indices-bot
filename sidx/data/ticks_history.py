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
    # NB: "subscribe" must be omitted for one-shot history (Deriv rejects subscribe=0)
    await ws.send(
        {
            "ticks_history": symbol,
            "style": "ticks",
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
        # ticks_history is public data; authorization is optional. Tolerate a
        # missing/invalid token so backtests work without an account.
        if cfg.api_token:
            try:
                await authorize(ws, cfg.api_token)
            except RuntimeError as e:
                logger.warning("authorize failed (%s); fetching history unauthenticated", e)
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


def _candles_to_df(msg: dict[str, Any]) -> pd.DataFrame:
    candles = msg.get("candles") or []
    return pd.DataFrame(
        {
            "epoch": [int(c["epoch"]) for c in candles],
            "open": [float(c["open"]) for c in candles],
            "high": [float(c["high"]) for c in candles],
            "low": [float(c["low"]) for c in candles],
            "close": [float(c["close"]) for c in candles],
        }
    )


async def fetch_candles_history_paginated(
    cfg: DerivConnectionConfig,
    total_candles: int,
    granularity: int = 60,
    page_size: int = 5000,
) -> pd.DataFrame:
    """
    Paginated M1 (or other granularity) candle history. Deriv keeps candle
    history far longer than tick history (~90+ days vs ~1 day), so this is the
    preferred source for validation backtests. Returns an OHLCV frame with a
    UTC DatetimeIndex (volume is not provided by the API and set to 0).
    """
    url = f"{cfg.ws_url}?app_id={cfg.app_id}"
    ws = DerivWebSocket(url)
    await ws.connect()
    try:
        frames: list[pd.DataFrame] = []
        remaining = total_candles
        end: str | int = "latest"
        rid = 1
        while remaining > 0:
            chunk = min(page_size, remaining)
            await ws.send(
                {
                    "ticks_history": cfg.symbol,
                    "style": "candles",
                    "granularity": int(granularity),
                    "end": str(end) if end != "latest" else "latest",
                    "count": int(chunk),
                    "req_id": rid,
                }
            )
            while True:
                msg = await ws.recv()
                if msg.get("req_id") != rid:
                    continue
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                if "candles" in msg:
                    df = _candles_to_df(msg)
                    break
            rid += 1
            if df.empty:
                break
            oldest = int(df["epoch"].min())
            # server clamps out-of-range requests to the latest window; stop if we're not advancing
            if frames and oldest >= int(frames[-1]["epoch"].min()):
                break
            frames.append(df)
            end = oldest - granularity
            remaining -= len(df)
            if len(df) < chunk:
                break
        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        out = pd.concat(frames, ignore_index=True)
        out = out.sort_values("epoch").drop_duplicates(subset=["epoch"]).reset_index(drop=True)
        out.index = pd.to_datetime(out["epoch"], unit="s", utc=True)
        out = out.drop(columns=["epoch"])
        out["volume"] = 0
        return out
    finally:
        await ws.close()


def fetch_candles_history_paginated_sync(
    cfg: DerivConnectionConfig, total_candles: int, granularity: int = 60
) -> pd.DataFrame:
    return asyncio.run(fetch_candles_history_paginated(cfg, total_candles, granularity))


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
