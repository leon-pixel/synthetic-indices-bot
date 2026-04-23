from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


class JsonlLogger:
    """Append-only JSONL for audit trail."""

    def __init__(self, path: Path | str, strategy_version: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.strategy_version = strategy_version
        self._subscribers: list[Any] = []

    def subscribe(self, callback: Any) -> None:
        """
        Register a callback(record_dict). Used for alerts/dashboard fan-out.
        """
        self._subscribers.append(callback)

    def _write(self, fp: TextIO, record: dict[str, Any]) -> None:
        record.setdefault("ts", utc_now_iso())
        record.setdefault("strategy_version", self.strategy_version)
        fp.write(json.dumps(record, default=str) + "\n")

    def log(self, record: dict[str, Any]) -> None:
        normalized = dict(record)
        normalized.setdefault("ts", utc_now_iso())
        normalized.setdefault("strategy_version", self.strategy_version)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(normalized, default=str) + "\n")
        for cb in self._subscribers:
            try:
                cb(dict(normalized))
            except Exception:
                logging.getLogger(__name__).exception("log subscriber failed")

    def log_dataclass(self, obj: Any, extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any]
        if is_dataclass(obj):
            payload = asdict(obj)
        elif isinstance(obj, dict):
            payload = dict(obj)
        else:
            payload = {"value": repr(obj)}
        if extra:
            payload.update(extra)
        self.log(payload)
