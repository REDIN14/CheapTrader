"""Where the feed loop reads from: the MetaTrader terminal, or any other adapter.

``Mt5Source`` is what makes the app keep up with MetaTrader. The terminal knows every
tick it has received, not just the latest one, so instead of sampling the price now
and then (and losing whatever happened in between) it reads *all* the ticks since the
last read. A fast market then reaches the screen tick for tick, and a candle's high
and low are the real ones.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.broker.base import BrokerAdapter
    from app.broker.mt5_adapter import MT5Adapter


@dataclass
class _Cursor:
    """The newest tick already handed out for one symbol."""

    #: Its time in whole seconds: where the next read starts (MetaTrader reads from a second).
    second: int
    #: Its time in milliseconds: what separates the new ticks from the old ones in that second.
    msc: int
    #: What the ticks sharing exactly that millisecond looked like, so none is sent twice
    #: and none is dropped for happening in the same millisecond as another.
    seen: set[tuple] = field(default_factory=set)


def _signature(tick: dict) -> tuple:
    return (tick["bid"], tick["ask"], tick["last"], tick["volume"], tick["flags"])


class Mt5Source:
    """Ticks, positions, pending orders and account from a connected ``MT5Adapter``."""

    #: Ticks asked for per read. A read that comes back full means there are more.
    BATCH = 5000
    #: Reads in a row before the loop gets a turn again (the next look carries on).
    MAX_READS = 4

    def __init__(self, adapter: MT5Adapter) -> None:
        self._adapter = adapter
        self._cursors: dict[str, _Cursor] = {}

    def prepare(self, symbol: str) -> dict | None:
        mt5 = self._adapter.module
        info = mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"MetaTrader does not know the symbol {symbol}")
        # A symbol outside the Market Watch gets no quotes at all, so it has to be added.
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise ValueError(f"{symbol} could not be added to the Market Watch")
        self._cursors.pop(symbol, None)
        return self._start(symbol)  # None until a quote exists; the first one starts the cursor

    def forget(self, symbol: str) -> None:
        self._cursors.pop(symbol, None)

    def ticks(self, symbol: str) -> list[dict]:
        cursor = self._cursors.get(symbol)
        if cursor is None:
            first = self._start(symbol)
            return [first] if first else []

        mt5 = self._adapter.module
        out: list[dict] = []
        for _ in range(self.MAX_READS):
            raw = mt5.copy_ticks_from(symbol, cursor.second, self.BATCH, mt5.COPY_TICKS_ALL)
            if raw is None or len(raw) == 0:
                break
            for r in raw:
                msc = int(r["time_msc"])
                if msc < cursor.msc:
                    continue
                row = {
                    "time": int(r["time"]),
                    "bid": float(r["bid"]),
                    "ask": float(r["ask"]),
                    "last": float(r["last"]),
                    "volume": float(r["volume"]),
                    "time_msc": msc,
                    "flags": int(r["flags"]),
                }
                sig = _signature(row)
                if msc == cursor.msc:
                    if sig in cursor.seen:
                        continue
                    cursor.seen.add(sig)
                else:
                    cursor.msc = msc
                    cursor.second = row["time"]
                    cursor.seen = {sig}
                out.append(row)
            if len(raw) < self.BATCH:
                break

        if not out:
            # The terminal's tick history can lag its newest quote by a moment (and a
            # symbol that was only just added has none): the quote itself is the answer.
            tick = self._adapter.get_tick(symbol)
            if tick is not None and tick.time_msc > cursor.msc:
                row = tick.model_dump()
                cursor.msc, cursor.second, cursor.seen = row["time_msc"], row["time"], {_signature(row)}
                out.append(row)
        return out

    def _start(self, symbol: str) -> dict | None:
        """Take the symbol's current quote as the starting point, and hand it out."""
        tick = self._adapter.get_tick(symbol)
        if tick is None:
            return None
        row = tick.model_dump()
        self._cursors[symbol] = _Cursor(row["time"], row["time_msc"], {_signature(row)})
        return row

    def state(self) -> dict:
        # A failed read must not look like "nothing is open": it raises, the loop keeps
        # what it last sent and says so, and the next look tries again.
        return {
            "positions": [p.model_dump() for p in self._adapter.get_positions(strict=True)],
            "account": self._adapter.get_account().model_dump(),
            "orders": [o.model_dump(mode="json") for o in self._adapter.get_orders(strict=True)],
        }


class AdapterSource:
    """Any adapter at all: the latest tick, noticed when it changes.

    The mock broker has a cheaper and exact way (``ticks_since``) and uses it; an
    adapter without one is still followed, one tick per look.
    """

    def __init__(self, adapter: BrokerAdapter) -> None:
        self._adapter = adapter
        self._last: dict[str, int] = {}

    def _since(self, symbol: str, msc: int) -> list[dict]:
        since: Any = getattr(self._adapter, "ticks_since", None)
        if since is not None:
            return [t.model_dump() for t in since(symbol, msc)]
        tick = self._adapter.get_tick(symbol)
        if tick is None:
            return []
        stamp = tick.time_msc or int(time.time() * 1000)
        return [tick.model_dump()] if stamp > msc else []

    def prepare(self, symbol: str) -> dict | None:
        tick = self._adapter.get_tick(symbol)
        if tick is None:
            self._last[symbol] = 0
            return None
        row = tick.model_dump()
        self._last[symbol] = row["time_msc"]
        return row

    def forget(self, symbol: str) -> None:
        self._last.pop(symbol, None)

    def ticks(self, symbol: str) -> list[dict]:
        out = self._since(symbol, self._last.get(symbol, 0))
        if out:
            self._last[symbol] = out[-1]["time_msc"]
        return out

    def state(self) -> dict:
        return {
            "positions": [p.model_dump() for p in self._adapter.get_positions()],
            "account": self._adapter.get_account().model_dump(),
            "orders": [o.model_dump(mode="json") for o in self._adapter.get_orders()],
        }
