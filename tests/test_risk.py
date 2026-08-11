from datetime import datetime, timedelta, timezone

from sidx.config import RiskConfig
from sidx.risk import RiskManager

CFG = RiskConfig(
    max_trades_per_day=8,
    max_daily_loss_pct=2.0,
    max_consecutive_losses=3,
    cooldown_minutes=12,
    session_start_utc_hour=8,
    session_end_utc_hour=20,
)

T0 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def test_outside_session():
    rm = RiskManager(CFG)
    ok, why = rm.can_trade(T0.replace(hour=6))
    assert not ok and why == "outside_session"


def test_cooldown():
    rm = RiskManager(CFG)
    rm.register_entry(T0)
    ok, why = rm.can_trade(T0 + timedelta(minutes=5))
    assert not ok and why == "cooldown"
    ok, _ = rm.can_trade(T0 + timedelta(minutes=13))
    assert ok


def test_max_trades_per_day():
    rm = RiskManager(CFG)
    for i in range(CFG.max_trades_per_day):
        rm.register_entry(T0 + timedelta(minutes=15 * i))
    ok, why = rm.can_trade(T0 + timedelta(hours=4))
    assert not ok and why == "max_trades_day"


def test_consecutive_losses_halt_and_next_day_reset():
    rm = RiskManager(CFG)
    for i in range(CFG.max_consecutive_losses):
        rm.register_exit(T0 + timedelta(minutes=i), -1.0)
    ok, why = rm.can_trade(T0 + timedelta(hours=1))
    assert not ok and why in ("kill_switch_active", "max_consecutive_losses")
    ok, _ = rm.can_trade(T0 + timedelta(days=1))
    assert ok


def test_daily_loss_halt():
    rm = RiskManager(CFG, starting_equity=10_000.0)
    rm.register_exit(T0, -250.0)  # cap is -200 (2% of 10k)
    ok, why = rm.can_trade(T0 + timedelta(minutes=30))
    assert not ok and why in ("kill_switch_active", "max_daily_loss")
    ok, _ = rm.can_trade(T0 + timedelta(days=1))
    assert ok


def test_state_roundtrip():
    rm = RiskManager(CFG)
    rm.register_entry(T0)
    rm.register_exit(T0 + timedelta(minutes=3), -5.0)
    payload = rm.to_dict()
    rm2 = RiskManager(CFG)
    rm2.load_dict(payload)
    assert rm2.to_dict() == payload
