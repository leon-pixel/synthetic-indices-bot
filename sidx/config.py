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


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


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
    rsi_buy_max: float = 35.0
    rsi_sell_min: float = 65.0
    atr_period: int = 14
    atr_high_pct: float = 0.85
    atr_low_pct: float = 0.15
    atr_pct_window: int = 288
    tp_r_multiple_min: float = 2.0
    tp_r_multiple_max: float = 3.0
    sl_atr_mult: float = 0.5
    max_hold_minutes: int = 8
    min_hold_bars_for_stall: int = 3
    stall_mfe_atr_mult: float = 0.15
    use_trailing_stop: bool = True
    trailing_atr_mult: float = 2.0


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "sim"
    contract_duration_minutes: int = 10
    min_contract_minutes: int = 1
    max_contract_minutes: int = 10
    currency: str = "USD"
    stake: float = 1.0
    spread_points: float = 0.5
    slippage_points: float = 0.3
    use_kelly: bool = False
    kelly_fraction: float = 0.25


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
    app_id = _env_int("DERIV_APP_ID", 1089)
    ws_url = _env("DERIV_WS_URL", "wss://ws.derivws.com/websockets/v3") or "wss://ws.derivws.com/websockets/v3"
    symbol = _env("DERIV_SYMBOL", "R_75") or "R_75"
    mode = (_env("EXECUTION_MODE", "sim") or "sim").lower()
    deriv = DerivConnectionConfig(api_token=token, app_id=app_id, ws_url=ws_url, symbol=symbol)

    risk = RiskConfig(
        risk_per_trade_pct=_env_float("RISK_PER_TRADE_PCT", 0.35),
        max_trades_per_day=_env_int("MAX_TRADES_PER_DAY", 8),
        max_daily_loss_pct=_env_float("MAX_DAILY_LOSS_PCT", 2.0),
        max_consecutive_losses=_env_int("MAX_CONSECUTIVE_LOSSES", 3),
        cooldown_minutes=_env_int("COOLDOWN_MINUTES", 12),
        session_start_utc_hour=_env_int("SESSION_START_UTC_HOUR", 8),
        session_end_utc_hour=_env_int("SESSION_END_UTC_HOUR", 20),
    )

    strategy = StrategyConfig(
        ema_fast=_env_int("EMA_FAST", 20),
        ema_slow=_env_int("EMA_SLOW", 50),
        rsi_period=_env_int("RSI_PERIOD", 14),
        rsi_buy_max=_env_float("RSI_BUY_MAX", 35.0),
        rsi_sell_min=_env_float("RSI_SELL_MIN", 65.0),
        atr_period=_env_int("ATR_PERIOD", 14),
        atr_high_pct=_env_float("ATR_HIGH_PCT", 0.85),
        atr_low_pct=_env_float("ATR_LOW_PCT", 0.15),
        atr_pct_window=_env_int("ATR_PCT_WINDOW", 288),
        tp_r_multiple_min=_env_float("TP_R_MULTIPLE_MIN", 2.0),
        tp_r_multiple_max=_env_float("TP_R_MULTIPLE_MAX", 3.0),
        sl_atr_mult=_env_float("SL_ATR_MULT", 0.5),
        max_hold_minutes=_env_int("MAX_HOLD_MINUTES", 8),
        min_hold_bars_for_stall=_env_int("MIN_HOLD_BARS_FOR_STALL", 3),
        stall_mfe_atr_mult=_env_float("STALL_MFE_ATR_MULT", 0.15),
    )

    execution = ExecutionConfig(
        mode=mode,
        contract_duration_minutes=_env_int("CONTRACT_DURATION_MINUTES", 10),
        min_contract_minutes=_env_int("MIN_CONTRACT_MINUTES", 1),
        max_contract_minutes=_env_int("MAX_CONTRACT_MINUTES", 10),
        currency=_env("CURRENCY", "USD") or "USD",
        stake=_env_float("STAKE", 1.0),
        spread_points=_env_float("SPREAD_POINTS", 0.5),
        slippage_points=_env_float("SLIPPAGE_POINTS", 0.3),
        use_kelly=_env("USE_KELLY", "false").lower() == "true",
        kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
    )

    return BotConfig(deriv=deriv, risk=risk, strategy=strategy, execution=execution)


def params_hash(obj: Any) -> str:
    if is_dataclass(obj):
        payload = asdict(obj)
    elif isinstance(obj, Mapping):
        payload = dict(obj)
    else:
        payload = {"repr": repr(obj)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(blob).hexdigest()[:16]