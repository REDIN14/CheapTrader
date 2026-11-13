"""Historical pages anchored to dates, with no limit on a series' total depth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.schemas import TIMEFRAME_SECONDS, Bar, BarPage, Timeframe

if TYPE_CHECKING:
    from app.broker.base import BrokerAdapter
    from app.data.cache import DataCache

PAGE_BARS = 1500


def moment(timestamp: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=int(timestamp))


def unique(bars: list[Bar]) -> list[Bar]:
    return sorted({b.time: b for b in bars}.values(), key=lambda b: b.time)


def before(cache: DataCache, broker: BrokerAdapter, symbol: str, timeframe: Timeframe,
           boundary: int, count: int = PAGE_BARS) -> BarPage:
    key = f"before:{symbol}:{timeframe.value}:{boundary}:{count}"
    cached = cache._get(key)
    if cached is not None:
        return cached
    bars = unique(broker.get_bars(symbol, timeframe, count=count + 1, end=moment(boundary - 1)))
    bars = [b for b in bars if b.time < boundary]
    cache.store.upsert(symbol, timeframe, bars)
    # A short page need not mean the terminal has finished synchronizing. Probe
    # again at its oldest candle; only an empty page establishes the history's end.
    result = BarPage(bars=bars[-count:], has_more=bool(bars))
    cache._set(key, result, 30.0)
    return result


def after(cache: DataCache, broker: BrokerAdapter, symbol: str, timeframe: Timeframe,
          boundary: int, count: int = PAGE_BARS) -> BarPage:
    tick = cache.get_tick(broker, symbol)
    newest = tick.time if tick else int(datetime.now(timezone.utc).timestamp())
    if boundary >= newest:
        return BarPage(bars=[], has_more=False)
    step = TIMEFRAME_SECONDS[timeframe]
    span = max(step, int((count + 1) * step * 1.6))
    end = min(newest, boundary + span)
    while True:
        bars = unique(cache.ensure_range(broker, symbol, timeframe, moment(boundary + 1), moment(end)))
        bars = [b for b in bars if boundary < b.time <= newest]
        if len(bars) > count or end >= newest:
            return BarPage(bars=bars[:count], has_more=len(bars) > count)
        # A weekend, holiday or sparse instrument needs a wider calendar window.
        span *= 2
        end = min(newest, boundary + span)
