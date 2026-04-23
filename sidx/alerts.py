from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any


class TelegramNotifier:
    """
    Minimal Telegram sender using Bot API.
    No external dependency required.
    """

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled and bool(self.bot_token) and bool(self.chat_id)

    async def send_text(self, text: str) -> None:
        if not self.enabled:
            return
        payload = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        def _send() -> None:
            req = urllib.request.Request(url=url, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=10) as resp:
                _ = resp.read()

        await asyncio.to_thread(_send)

    def build_text(self, record: dict[str, Any]) -> str | None:
        event = str(record.get("event", ""))
        ts = str(record.get("ts", ""))
        if event == "opened":
            return (
                "Opened trade\n"
                f"Side: {record.get('side')}\n"
                f"Entry: {record.get('entry')}\n"
                f"TP: {record.get('tp')}  SL: {record.get('sl')}\n"
                f"Contract: {record.get('contract_id')}\n"
                f"Time: {ts}"
            )
        if event == "closed":
            return (
                "Closed trade\n"
                f"Side: {record.get('side')}\n"
                f"Entry: {record.get('entry')}  Exit: {record.get('exit')}\n"
                f"PnL: {record.get('pnl_money')}  Reason: {record.get('reason')}\n"
                f"Time: {ts}"
            )
        if event == "blocked":
            return f"Trade blocked: {record.get('why')} @ {ts}"
        if event == "open_failed":
            return f"Open failed: {record.get('error')} @ {ts}"
        if event == "close_failed":
            return f"Close failed: {record.get('error')} @ {ts}"
        return None

    def callback(self, record: dict[str, Any]) -> None:
        text = self.build_text(record)
        if not text:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.send_text(text))
        except RuntimeError:
            pass


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

