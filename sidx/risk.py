from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sidx.config import RiskConfig


@dataclass
class RiskState:
    trading_halted_until: datetime | None = None
    current_day: date | None = None
    trades_today: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    last_trade_ts: datetime | None = None
    starting_equity: float = 10_000.0


class RiskManager:
    def __init__(self, cfg: RiskConfig, starting_equity: float = 10_000.0) -> None:
        self.cfg = cfg
        self.state = RiskState(starting_equity=starting_equity)

    def _roll_day(self, ts: datetime) -> None:
        d = ts.astimezone(timezone.utc).date()
        if self.state.current_day != d:
            self.state.current_day = d
            self.state.trades_today = 0
            self.state.daily_pnl = 0.0
            self.state.consecutive_losses = 0
            if self.state.trading_halted_until and ts >= self.state.trading_halted_until:
                self.state.trading_halted_until = None

    def can_trade(self, ts: datetime) -> tuple[bool, str]:
        self._roll_day(ts)
        if self.state.trading_halted_until and ts < self.state.trading_halted_until:
            return False, "kill_switch_active"
        h = ts.astimezone(timezone.utc).hour
        if not (self.cfg.session_start_utc_hour <= h < self.cfg.session_end_utc_hour):
            return False, "outside_session"
        if self.state.trades_today >= self.cfg.max_trades_per_day:
            return False, "max_trades_day"
        if self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
            self._halt_until_next_day(ts)
            return False, "max_consecutive_losses"
        loss_cap = -self.cfg.max_daily_loss_pct / 100.0 * self.state.starting_equity
        if self.state.daily_pnl <= loss_cap:
            self._halt_until_next_day(ts)
            return False, "max_daily_loss"
        if self.state.last_trade_ts is not None:
            delta = ts - self.state.last_trade_ts
            if delta < timedelta(minutes=self.cfg.cooldown_minutes):
                return False, "cooldown"
        return True, "ok"

    def _halt_until_next_day(self, ts: datetime) -> None:
        d = ts.astimezone(timezone.utc).date()
        next_day = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
        self.state.trading_halted_until = next_day

    def register_entry(self, ts: datetime) -> None:
        self._roll_day(ts)
        self.state.trades_today += 1
        self.state.last_trade_ts = ts

    def register_exit(self, ts: datetime, pnl_money: float) -> None:
        self.state.daily_pnl += pnl_money
        if pnl_money < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        loss_cap = -self.cfg.max_daily_loss_pct / 100.0 * self.state.starting_equity
        if self.state.daily_pnl <= loss_cap:
            self._halt_until_next_day(ts)
        if self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
            self._halt_until_next_day(ts)
