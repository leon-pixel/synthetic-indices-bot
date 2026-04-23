from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from hashlib import sha256
from typing import Any, Mapping


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    return v


@dataclass(frozen=True)
class DerivConnectionConfig:
    api_token: str
    app_id: int = 1089
    ws_url: str = "wss://ws.derivws.com/websockets/v3"
    symbol: str = "R_75"


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.35
    max_trades_per_day: int = 8
    max_daily_loss_pct: float = 2.0
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 12
    session_start_utc_hour: int = 8
    session_end_utc_hour: int = 20


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_buy_max: float = 30.0
    rsi_sell_min: float = 70.0
    atr_period: int = 14
    atr_high_pct: float = 0.85  # skip if ATR > 85th pct of rolling window
    atr_low_pct: float = 0.15  # skip if ATR < 15th pct (dead chop)
    atr_pct_window: int = 288  # bars on M1 (~1 day)
    tp_r_multiple_min: float = 1.2
    tp_r_multiple_max: float = 1.5
    sl_atr_mult: float = 1.0
    max_hold_minutes: int = 8
    min_hold_bars_for_stall: int = 3
    stall_mfe_atr_mult: float = 0.15  # if MFE < 0.15*ATR after N bars, exit


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "sim"  # sim | deriv
    contract_duration_minutes: int = 10  # upper bound for API; TP/SL may close earlier via sell
    min_contract_minutes: int = 1
    max_contract_minutes: int = 10
    currency: str = "USD"
    stake: float = 1.0
    spread_points: float = 0.5  # sim friction
    slippage_points: float = 0.3


@dataclass(frozen=True)
class BotConfig:
    deriv: DerivConnectionConfig
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


def load_dotenv_file(path: str = ".env") -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
    except Exception:
        pass


def load_bot_config(dotenv_path: str | None = ".env") -> BotConfig:
    if dotenv_path:
        load_dotenv_file(dotenv_path)
    token = _env("DERIV_API_TOKEN", "") or ""
    app_id = int(_env("DERIV_APP_ID", "1089") or "1089")
    ws_url = _env("DERIV_WS_URL", "wss://ws.derivws.com/websockets/v3") or "wss://ws.derivws.com/websockets/v3"
    symbol = _env("DERIV_SYMBOL", "R_75") or "R_75"
    mode = (_env("EXECUTION_MODE", "sim") or "sim").lower()
    deriv = DerivConnectionConfig(api_token=token, app_id=app_id, ws_url=ws_url, symbol=symbol)
    execution = ExecutionConfig(mode=mode)
    return BotConfig(deriv=deriv, execution=execution)


def params_hash(obj: Any) -> str:
    if is_dataclass(obj):
        payload = asdict(obj)
    elif isinstance(obj, Mapping):
        payload = dict(obj)
    else:
        payload = {"repr": repr(obj)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(blob).hexdigest()[:16]
