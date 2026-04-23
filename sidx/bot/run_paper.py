from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sidx.alerts import TelegramNotifier, parse_bool
from sidx import __version__
from sidx.config import load_bot_config, params_hash
from sidx.data.candles import m1_m5_from_ticks
from sidx.data.live_buffer import TickRingBuffer
from sidx.data.ticks_history import stream_ticks
from sidx.execution import make_execution
from sidx.logging_utils import JsonlLogger, setup_logging
from sidx.risk import RiskManager
from sidx.state_store import load_state, save_state
from sidx.strategy import Side, evaluate_signal, prepare_feature_frame
from sidx.trade_manager import TradeManager

logger = logging.getLogger(__name__)


class DaySummary:
    def __init__(self) -> None:
        self.day: str | None = None
        self.opened = 0
        self.closed = 0
        self.blocked = 0
        self.wins = 0
        self.losses = 0
        self.net_pnl = 0.0
        self.block_reasons: dict[str, int] = {}

    def on_event(self, rec: dict[str, Any]) -> None:
        ts = str(rec.get("ts", ""))
        day = ts[:10] if len(ts) >= 10 else None
        if not day:
            return
        if self.day is None:
            self.day = day
        event = str(rec.get("event", ""))
        if event == "opened":
            self.opened += 1
        elif event == "closed":
            self.closed += 1
            pnl = float(rec.get("pnl_money", 0.0) or 0.0)
            self.net_pnl += pnl
            if pnl > 0:
                self.wins += 1
            elif pnl < 0:
                self.losses += 1
        elif event == "blocked":
            self.blocked += 1
            why = str(rec.get("why", "unknown"))
            self.block_reasons[why] = self.block_reasons.get(why, 0) + 1

    def maybe_rollover(self, now_day: str) -> dict[str, Any] | None:
        if self.day is None:
            self.day = now_day
            return None
        if now_day == self.day:
            return None
        summary = {
            "event": "daily_summary",
            "day": self.day,
            "opened": self.opened,
            "closed": self.closed,
            "wins": self.wins,
            "losses": self.losses,
            "blocked": self.blocked,
            "net_pnl": round(self.net_pnl, 8),
            "block_reasons": dict(self.block_reasons),
        }
        self.day = now_day
        self.opened = 0
        self.closed = 0
        self.blocked = 0
        self.wins = 0
        self.losses = 0
        self.net_pnl = 0.0
        self.block_reasons = {}
        return summary


async def _runner(
    stop: asyncio.Event,
    log_path: Path,
    dotenv: str,
    telegram_enabled: bool,
    telegram_token: str,
    telegram_chat_id: str,
    state_path: Path,
    validate_startup: bool,
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
    summary = DaySummary()

    # Restore persisted runtime state on restart.
    persisted = load_state(state_path)
    if isinstance(persisted, dict):
        try:
            if isinstance(persisted.get("risk"), dict):
                risk.load_dict(persisted["risk"])
            if isinstance(persisted.get("trade"), dict):
                tm.load_state(persisted["trade"])
            jlog.log({"event": "state_restored", "state_path": str(state_path)})
        except Exception as e:
            jlog.log({"event": "state_restore_failed", "error": str(e), "state_path": str(state_path)})

    if validate_startup:
        validator = getattr(execution, "validate_contract_setup", None)
        if callable(validator):
            ok, msg = await validator()
            jlog.log({"event": "startup_validation", "ok": bool(ok), "message": msg})
            if not ok:
                raise SystemExit(f"startup validation failed: {msg}")

    last_closed_ts = None
    bars_since_entry = 0
    last_reconcile_epoch = 0.0

    def persist_runtime_state() -> None:
        payload = {
            "risk": risk.to_dict(),
            "trade": tm.dump_state(),
        }
        save_state(state_path, payload)

    async def on_tick(tick: dict) -> None:
        nonlocal last_closed_ts, bars_since_entry, last_reconcile_epoch
        buf.push(int(tick["epoch"]), float(tick["price"]))
        # periodic reconciliation (e.g., restarted process, externally closed contract)
        now_epoch = float(tick["epoch"])
        if tm.has_position() and (now_epoch - last_reconcile_epoch) >= 60:
            last_reconcile_epoch = now_epoch
            pnl_rec = await tm.reconcile_open_position(datetime.now(timezone.utc))
            if pnl_rec is not None:
                risk.register_exit(datetime.now(timezone.utc), float(pnl_rec))
                persist_runtime_state()
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
        today = ts.astimezone(timezone.utc).date().isoformat()
        rolled = summary.maybe_rollover(today)
        if rolled:
            jlog.log(rolled)

        if tm.has_position():
            bars_since_entry += 1
            pnl = await tm.on_bar(ts, o, h, l, c, bars_since_entry)
            if pnl is not None:
                risk.register_exit(ts, float(pnl))
                bars_since_entry = 0
                persist_runtime_state()

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
            persist_runtime_state()

    jlog.subscribe(summary.on_event)

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
    ap.add_argument("--state", type=str, default="logs/runtime_state.json", help="Persistent runtime state JSON path")
    ap.add_argument(
        "--validate-startup",
        action=argparse.BooleanOptionalAction,
        default=parse_bool(os.environ.get("VALIDATE_STARTUP"), default=True),
        help="Validate contract proposals at startup; fail fast if unsupported.",
    )
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
                state_path=Path(args.state),
                validate_startup=bool(args.validate_startup),
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
