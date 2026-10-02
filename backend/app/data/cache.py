"""In-memory bar/tick cache with TTL, backed by the broker adapter.

Bars are delegated to the persistent incremental :class:`BarStore`; this class
keeps a short-lived in-memory layer for ticks and for repeated identical reads.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from app.broker.base import BrokerAdapter
from app.data.store import BarStore
from app.schemas import Bar, Tick, Timeframe


@dataclass
class _Entry:
    value: object
    expires_at: float


@dataclass
class DataCache:
    """Small TTL cache to avoid hammering the broker for repeated reads."""

    bar_ttl: float = 2.0
    tick_ttl: float = 0.2
    store: BarStore = field(default_factory=BarStore)
    _store: dict[str, _Entry] = field(default_factory=dict)

    def _get(self, key: str):
        entry = self._store.get(key)
        if entry is None or entry.expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return entry.value

    def _set(self, key: str, value: object, ttl: float) -> None:
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    def get_bars(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        key = f"bars:{symbol}:{timeframe.value}:{count}:{start}:{end}"
        cached = self._get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        bars = self.store.get_bars(
            broker, symbol, timeframe, count=count, start=start, end=end
        )
        self._set(key, bars, self.bar_ttl)
        return bars

    def ensure_range(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Fetch only the missing parts of [start, end] and return the full range."""
        return self.store.ensure_range(broker, symbol, timeframe, start, end)

    def get_tick(self, broker: BrokerAdapter, symbol: str) -> Tick | None:
        key = f"tick:{symbol}"
        cached = self._get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        tick = broker.get_tick(symbol)
        if tick is not None:
            self._set(key, tick, self.tick_ttl)
        return tick

    def invalidate(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._store.clear()
            return
        for key in [k for k in self._store if k.startswith(prefix)]:
            self._store.pop(key, None)
