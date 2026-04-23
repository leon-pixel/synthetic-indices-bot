from __future__ import annotations

from collections import deque
from typing import Deque, Iterable

import pandas as pd


class TickRingBuffer:
    """
    In-memory tick buffer for live aggregation. Same rows feed ``ticks_to_ohlcv``.
    """

    def __init__(self, maxlen: int = 200_000) -> None:
        self._rows: Deque[tuple[int, float]] = deque(maxlen=maxlen)

    def extend(self, rows: Iterable[tuple[int, float]]) -> None:
        for e, p in rows:
            self._rows.append((int(e), float(p)))

    def push(self, epoch: int, price: float) -> None:
        self._rows.append((int(epoch), float(price)))

    def to_dataframe(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=["epoch", "price"])
        epochs, prices = zip(*self._rows)
        return pd.DataFrame({"epoch": list(epochs), "price": list(prices)})
