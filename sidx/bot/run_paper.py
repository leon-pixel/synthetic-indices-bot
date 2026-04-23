from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

from sidx.alerts import TelegramNotifier, parse_bool
from sidx import __version__
from sidx.config import load_bot_config, params_hash
from sidx.data.candles import m1_m5_from_ticks
from sidx.data.live_buffer import TickRingBuffer
from sidx.data.ticks_history import stream_ticks
from sidx.execution import make_execution
from sidx.logging_utils import JsonlLogger, setup_logging
from sidx.risk import RiskManager
from sidx.strategy import Side, evaluate_signal, prepare_feature_frame
from sidx.trade_manager import TradeManager

logger = logging.getLogger(__name__)


async def _runner(
    stop: asyncio.Event,
    log_path: Path,
    dotenv: str,
    telegram_enabled: bool,
    telegram_token: str,
    telegram_chat_id: str,
) -> None:
    cfg = load_bot_config(dotenv)
    if not cfg.deriv.api_token:
        raise SystemExit("DERIV_API_TOKEN is required for paper streaming")

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    buf = TickRingBuffer()
    strat_hash = params_hash(cfg.strategy)
    jlog = JsonlLogger(log_path, strategy_version=f"{__version__}:{strat_hash}")
    notifier = TelegramNotifier(
        bot_token=telegram_token,
        chat_id=telegram_chat_id,
        enabled=telegram_enabled,
    )
    jlog.subscribe(notifier.callback)
    risk = RiskManager(cfg.risk, starting_equity=10_000.0)
    execution = make_execution(cfg)
    tm = TradeManager(cfg, jlog, execution)

    last_closed_ts = None
    bars_since_entry = 0

    async def on_tick(tick: dict) -> None:
        nonlocal last_closed_ts, bars_since_entry
        buf.push(int(tick["epoch"]), float(tick["price"]))
        df = buf.to_dataframe()
        if len(df) < 500:
            return
        m1, m5 = m1_m5_from_ticks(df)
        feats = prepare_feature_frame(m1, m5, cfg.strategy)
        if len(feats) < 5:
            return
        closed_ts = feats.index[-2]
        if last_closed_ts == closed_ts:
            return
        last_closed_ts = closed_ts
        loc = feats.index.get_loc(closed_ts)
        if loc == 0:
            return
        prev_ts = feats.index[loc - 1]
        row = feats.loc[closed_ts]
        o, h, l, c = float(row.open), float(row.high), float(row.low), float(row.close)
        ts = closed_ts.to_pydatetime()

        if tm.has_position():
            bars_since_entry += 1
            pnl = await tm.on_bar(ts, o, h, l, c, bars_since_entry)
            if pnl is not None:
                risk.register_exit(ts, float(pnl))
                bars_since_entry = 0

        if tm.has_position():
            return

        prev = feats.loc[prev_ts]
        sig = evaluate_signal(prev, cfg.strategy)
        if sig.side == Side.NONE:
            return
        ok, why = risk.can_trade(ts)
        if not ok:
            jlog.log({"event": "blocked", "why": why, "ts": ts.isoformat()})
            return
        side = "BUY" if sig.side == Side.BUY else "SELL"
        atr_entry = float(prev["atr14"])
        opened = await tm.try_open(side, o, atr_entry, ts)
        if opened:
            risk.register_entry(ts)
            bars_since_entry = 0

    await stream_ticks(cfg.deriv, on_tick, stop)


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser(description="Paper / demo streaming loop")
    ap.add_argument("--dotenv", type=str, default=".env")
    ap.add_argument("--log", type=str, default="logs/paper.jsonl")
    ap.add_argument(
        "--telegram",
        action="store_true",
        default=parse_bool(os.environ.get("TELEGRAM_ENABLED"), default=False),
        help="Enable Telegram alerts from env TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID",
    )
    ap.add_argument("--telegram-token", type=str, default=os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    ap.add_argument("--telegram-chat-id", type=str, default=os.environ.get("TELEGRAM_CHAT_ID", ""))
    args = ap.parse_args()
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)

    stop = asyncio.Event()

    async def _wrap() -> None:
        try:
            await _runner(
                stop=stop,
                log_path=Path(args.log),
                dotenv=args.dotenv,
                telegram_enabled=bool(args.telegram),
                telegram_token=args.telegram_token,
                telegram_chat_id=args.telegram_chat_id,
            )
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_wrap())
    except KeyboardInterrupt:
        stop.set()
        logger.info("stopped")


if __name__ == "__main__":
    main()
