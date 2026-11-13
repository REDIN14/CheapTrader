"""Optional detail for the candle that contains a preserved replay clock."""

from __future__ import annotations

import logging

from app.data.history import moment
from app.replay.engine import ReplayEngine
from app.schemas import TIMEFRAME_SECONDS, Bar, Timeframe
from app.state import get_state

logger = logging.getLogger(__name__)


def candle_details(engine: ReplayEngine, timeframe: Timeframe, first: int, last: int) -> list[Bar]:
    """Use available candle detail; a missing optional interval must not reject a switch.

    The target candles have already loaded. Older native candles often outlive
    minute/tick history in MT5, so that extra detail cannot be a prerequisite.
    Never substitute the full target candle: its future extremes are not known yet.
    """
    state = get_state()

    def load(interval: Timeframe, start: int = first, end: int = last) -> list[Bar]:
        try:
            bars = state.cache.ensure_range(state.broker.adapter, engine.symbol, interval, moment(start), moment(end))
            return [bar for bar in bars if start <= bar.time <= end]
        except Exception:  # noqa: BLE001 - the target history succeeded; finer detail is optional
            logger.debug("Optional %s replay detail unavailable for %s", interval.value, engine.symbol, exc_info=True)
            return []

    step = TIMEFRAME_SECONDS[timeframe]
    resolution = 1 if step < 60 else 60
    details = load(Timeframe.S1 if step < 60 else Timeframe.M1)
    # Reuse the source replay, including its clipped current candle, before
    # requesting a different fallback. Its finer candles are already available.
    source_step = TIMEFRAME_SECONDS[engine.timeframe]
    source = engine.visible_bars() + engine.bars[engine.index + 1:]
    source = [bar for bar in source if first <= bar.time <= last] if source_step < step else []
    if not details:
        if source:
            details, resolution = source, source_step
        else:
            for interval in (Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1, Timeframe.H4, Timeframe.D1):
                if TIMEFRAME_SECONDS[interval] >= step:
                    break
                details = load(interval)
                if details:
                    resolution = TIMEFRAME_SECONDS[interval]
                    break

    clock = engine.cursor_time
    if clock % 60 and resolution >= 60:
        minute = clock // 60 * 60
        seconds = load(Timeframe.S1, minute, min(last, minute + 59))
        if not seconds and source_step < 60:
            seconds = [bar for bar in source if minute <= bar.time < minute + 60]
        # A whole minute containing a seconds cursor would reveal future prices.
        # With no ticks, the execution price still anchors the partial candle.
        details = [bar for bar in details if not bar.time <= clock < bar.time + resolution] + seconds
    return sorted(details, key=lambda bar: bar.time)
