from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def analyze(ledger: pd.DataFrame) -> dict:
    """Trade-level distribution stats: is the result broad-based or carried by outliers?"""
    if ledger.empty:
        return {"trades": 0}
    pnl = ledger["pnl_money"].astype(float)
    wins = pnl[pnl > 0].sort_values(ascending=False)
    losses = pnl[pnl < 0]
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    net = float(pnl.sum())

    def _top_share(n: int) -> float:
        return float(wins.head(n).sum() / gross_win) if gross_win > 0 else 0.0

    # longest losing streak
    streak = max_streak = 0
    for v in pnl:
        streak = streak + 1 if v < 0 else 0
        max_streak = max(max_streak, streak)

    out = {
        "trades": int(len(pnl)),
        "net_pnl": net,
        "mean": float(pnl.mean()),
        "median": float(pnl.median()),
        "std": float(pnl.std()),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "percentiles": {p: float(pnl.quantile(p / 100)) for p in (5, 25, 50, 75, 95)},
        "best_trade": float(pnl.max()),
        "worst_trade": float(pnl.min()),
        "top1_winner_share_of_gross": _top_share(1),
        "top3_winner_share_of_gross": _top_share(3),
        "top5_winner_share_of_gross": _top_share(5),
        "net_excl_top3_winners": float(net - wins.head(3).sum()),
        "net_excl_top5_winners": float(net - wins.head(5).sum()),
        "max_consecutive_losses": int(max_streak),
    }
    if "exit_reason" in ledger.columns:
        out["by_exit_reason"] = {
            str(k): {"trades": int(len(g)), "net_pnl": float(g["pnl_money"].sum())}
            for k, g in ledger.groupby("exit_reason")
        }
    if "side" in ledger.columns:
        out["by_side"] = {
            str(k): {"trades": int(len(g)), "net_pnl": float(g["pnl_money"].sum())}
            for k, g in ledger.groupby("side")
        }
    if "entry_ts" in ledger.columns:
        weekly = (
            ledger.assign(entry_ts=pd.to_datetime(ledger["entry_ts"], utc=True))
            .set_index("entry_ts")["pnl_money"]
            .resample("1W")
            .sum()
        )
        out["weekly_net_pnl"] = {str(k.date()): round(float(v), 4) for k, v in weekly.items()}
        out["positive_weeks"] = int((weekly > 0).sum())
        out["total_weeks"] = int(len(weekly))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Trade-level distribution analysis of a backtest ledger")
    ap.add_argument("--ledger", type=str, required=True, help="trade_ledger.csv from run_backtest")
    args = ap.parse_args()
    ledger = pd.read_csv(Path(args.ledger))
    print(json.dumps(analyze(ledger), indent=2))


if __name__ == "__main__":
    main()
