"""Build seconds candles from actual ticks; empty intervals stay empty."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

_TRADE_FLAGS = 8 | 16 | 32 | 64  # Last, volume, buy or sell; quote ticks repeat the last volume.


def tick_rows(ticks: Iterable[Any], seconds: int, point: float = 0.0) -> list[list]:
    """OHLC rows in the same shape as MT5 rates, using last (bid when no last exists).

    Millisecond ordering matters for open/close; several ticks may share a second.
    No prices are interpolated across a gap or a market closure.
    """
    buckets: dict[int, tuple[list, int, int]] = {}
    for tick in ticks:
        stamp = int(tick["time_msc"]) or int(tick["time"]) * 1000
        bid, ask, last = float(tick["bid"]), float(tick["ask"]), float(tick["last"])
        price = last if last > 0 else bid
        if not math.isfinite(price) or price <= 0:
            continue
        time = stamp // (seconds * 1000) * seconds
        spread = max(0, round((ask - bid) / point)) if point > 0 and ask > 0 and bid > 0 else 0
        volume = float(tick["volume"])
        volume = int(volume) if math.isfinite(volume) and volume > 0 and int(tick["flags"]) & _TRADE_FLAGS else 0
        saved = buckets.get(time)
        if saved is None:
            buckets[time] = ([time, price, price, price, price, 1, spread, volume], stamp, stamp)
            continue
        row, first, newest = saved
        row[2], row[3] = max(row[2], price), min(row[3], price)
        row[5] += 1
        row[7] += volume
        if stamp < first:
            row[1], first = price, stamp
        if stamp >= newest:
            row[4], row[6], newest = price, spread, stamp
        buckets[time] = (row, first, newest)
    return [buckets[time][0] for time in sorted(buckets)]
