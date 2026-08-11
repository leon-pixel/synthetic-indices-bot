from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from dataclasses import asdict

from sidx.config import load_bot_config, params_hash
from sidx.data.candles import m1_m5_from_ticks
from sidx.logging_utils import setup_logging
from sidx.research.simulation import simulate_backtest, stress_latency, summarize
from sidx.research.walk_forward import grid_search_rsi, masks_for_fold, time_splits
from sidx.strategy import prepare_feature_frame

logger = logging.getLogger(__name__)


def _load_ticks_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "epoch" not in df.columns or "price" not in df.columns:
        raise SystemExit("CSV must have columns: epoch,price")
    return df[["epoch", "price"]].copy()


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser(description="Backtest / walk-forward for sidx")
    ap.add_argument("--csv", type=str, default="", help="Ticks CSV (epoch,price)")
    ap.add_argument("--fetch", action="store_true", help="Fetch recent ticks from Deriv (~last 24h only)")
    ap.add_argument("--n-ticks", type=int, default=50_000)
    ap.add_argument(
        "--fetch-candles",
        action="store_true",
        help="Fetch M1 candle history from Deriv (goes back 90+ days; preferred for validation)",
    )
    ap.add_argument("--days", type=int, default=30, help="Days of M1 candles for --fetch-candles")
    ap.add_argument("--m1-csv", type=str, default="", help="Reuse a cached m1_cache.csv instead of fetching")
    ap.add_argument("--symbol", type=str, default="", help="Override DERIV_SYMBOL (e.g. R_10, R_100)")
    ap.add_argument("--walk-forward", type=int, default=0, help="Number of folds (0=disabled)")
    ap.add_argument("--latency-bars", type=int, default=0, help="Stress: shift features by N M1 bars")
    ap.add_argument("--out-dir", type=str, default="reports")
    ap.add_argument("--dotenv", type=str, default=".env")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bot = load_bot_config(args.dotenv)
    if args.symbol:
        from dataclasses import replace

        bot = replace(bot, deriv=replace(bot.deriv, symbol=args.symbol))

    n_ticks = 0
    if args.m1_csv:
        from sidx.data.candles import m5_from_m1

        m1 = pd.read_csv(Path(args.m1_csv), index_col=0, parse_dates=True)
        m1.index = pd.to_datetime(m1.index, utc=True)
        m5 = m5_from_m1(m1)
    elif args.fetch_candles:
        # Deriv history is public data; no token needed
        from sidx.data.candles import m5_from_m1
        from sidx.data.ticks_history import fetch_candles_history_paginated_sync

        m1 = fetch_candles_history_paginated_sync(bot.deriv, int(args.days) * 1440, granularity=60)
        m1.to_csv(out_dir / "m1_cache.csv")
        m5 = m5_from_m1(m1)
    else:
        ticks: pd.DataFrame
        if args.csv:
            ticks = _load_ticks_csv(Path(args.csv))
        elif args.fetch:
            from sidx.data.ticks_history import fetch_ticks_history_paginated_sync

            ticks = fetch_ticks_history_paginated_sync(bot.deriv, int(args.n_ticks))
            ticks.to_csv(out_dir / "ticks_cache.csv", index=False)
        else:
            raise SystemExit("Provide --csv ticks.csv, --fetch, or --fetch-candles")
        n_ticks = len(ticks)
        m1, m5 = m1_m5_from_ticks(ticks)

    feats = prepare_feature_frame(m1, m5, bot.strategy)
    if int(args.latency_bars) > 0:
        feats = stress_latency(feats, int(args.latency_bars))

    report: dict = {
        "symbol": bot.deriv.symbol,
        "commission_rate": bot.execution.commission_rate,
        "params_hash": params_hash(bot),
        "strategy_params_hash": params_hash(bot.strategy),
        "rows_ticks": int(n_ticks),
        "rows_m1": int(len(feats)),
    }

    if int(args.walk_forward) >= 2:
        folds = int(args.walk_forward)
        windows = time_splits(feats.index, folds)
        fold_reports = []
        for test_fold in range(len(windows)):
            train_mask, test_mask = masks_for_fold(feats.index, windows, test_fold)
            best_strat, train_sum, test_sum = grid_search_rsi(
                m1,
                m5,
                bot,
                rsi_buy_grid=(28.0, 30.0, 32.0),
                rsi_sell_grid=(68.0, 70.0, 72.0),
                train_mask=train_mask,
                test_mask=test_mask,
            )
            fold_reports.append(
                {
                    "test_fold": test_fold,
                    "best_strategy": asdict(best_strat),
                    "train": train_sum,
                    "test": test_sum,
                }
            )
        report["walk_forward"] = fold_reports
        led = pd.DataFrame()
    else:
        led = simulate_backtest(feats, bot)
        led.to_csv(out_dir / "trade_ledger.csv", index=False)
        report["summary"] = summarize(led)
        report["exit_reason_counts"] = led["exit_reason"].value_counts().to_dict() if not led.empty else {}

    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("wrote %s", out_dir / "summary.json")


if __name__ == "__main__":
    main()
