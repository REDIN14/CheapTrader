"""Seconds candles use real ticks and the same adapter path as the isolated reader."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.broker.base import BrokerError
from app.broker.mt5_adapter import MT5Adapter
from app.config import Settings
from app.data.seconds import tick_rows
from app.schemas import TIMEFRAME_SECONDS, Timeframe


def tick(ms: int, bid: float, **changes) -> dict:
    return {"time": ms // 1000, "time_msc": ms, "bid": bid, "ask": bid + 0.02,
            "last": 0, "volume": 0, "flags": 0, **changes}


def adapter(ticks: list[dict]):
    calls = []

    def copy(symbol, start, end, flags):
        assert start.tzinfo == end.tzinfo == timezone.utc
        calls.append((start.timestamp(), end.timestamp()))
        return [t for t in ticks if start.timestamp() * 1000 <= t["time_msc"] <= end.timestamp() * 1000]

    broker = MT5Adapter(Settings(broker="mock"))
    broker._connected = True
    broker._mt5 = SimpleNamespace(
        COPY_TICKS_ALL=0, copy_ticks_range=copy, last_error=lambda: (1, "missing history"),
        symbol_info=lambda _: SimpleNamespace(point=0.01),
        symbol_info_tick=lambda _: SimpleNamespace(time=ticks[-1]["time"] if ticks else 0),
    )
    return broker, calls


def date(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def test_ticks_make_aligned_ohlc_without_fabricating_empty_candles() -> None:
    rows = tick_rows([tick(1200, 10), tick(1800, 12), tick(1500, 9), tick(1999, 11), tick(5500, 14)], 1, 0.01)
    assert rows == [[1, 10, 12, 9, 11, 4, 2, 0], [5, 14, 14, 14, 14, 1, 2, 0]]
    assert tick_rows([tick(1000, 0), tick(2000, float("nan"))], 1) == []


def test_exchange_last_price_and_volume_match_the_live_chart() -> None:
    row, = tick_rows([
        tick(1000, 9, last=10, volume=3, flags=32),
        tick(1500, 9, last=11, volume=2, flags=64),
        tick(1800, 9, last=11, volume=2, flags=2),  # a quote repeats the previous trade's volume
    ], 5)
    assert row[1:6] == [10, 11, 10, 11, 3]
    assert row[7] == 5


@pytest.mark.parametrize("timeframe", [Timeframe.S1, Timeframe.S5, Timeframe.S10, Timeframe.S15, Timeframe.S30])
def test_seconds_history_is_supported_without_native_mt5_timeframe_constants(timeframe) -> None:
    step = TIMEFRAME_SECONDS[timeframe]
    ticks = [tick(i * step * 1000, 100 + i) for i in range(30)]
    broker, _ = adapter(ticks)
    bars = broker.get_bars("EURUSD", timeframe, count=20)
    assert len(bars) == 20
    assert bars[0].time == 10 * step and bars[-1].time == 29 * step
    assert bars[-1].close == 129
    assert all(b.time % step == 0 for b in bars)


def test_tick_pages_have_no_duplicates_at_an_inclusive_range_boundary() -> None:
    ticks = [tick(0, 10), tick(3_600_000, 11), tick(3_600_500, 12), tick(7_200_000, 13)]
    broker, calls = adapter(ticks)
    bars = broker.get_bars("EURUSD", Timeframe.S5, start=date(0), end=date(7200))
    assert [b.time for b in bars] == [0, 3600, 7200]
    assert [b.tick_volume for b in bars] == [1, 2, 1]
    assert len(calls) == 3 and all(b - a <= 3600 for a, b in calls)


def test_sparse_tick_history_extends_backwards_to_get_the_requested_candle_count() -> None:
    broker, calls = adapter([tick(0, 10), tick(180_000, 11)])
    bars = broker.get_bars("EURUSD", Timeframe.S30, count=2)
    assert [b.time for b in bars] == [0, 180]
    assert len(calls) > 1


def test_missing_tick_history_reports_the_broker_error() -> None:
    broker, _ = adapter([])
    broker._mt5.copy_ticks_range = lambda *args: None
    with pytest.raises(BrokerError, match="Tick history failed"):
        broker.get_bars("EURUSD", Timeframe.S1, start=date(1), end=date(5))


def test_an_empty_live_seconds_chart_explains_that_tick_history_is_unavailable() -> None:
    broker, _ = adapter([])
    with pytest.raises(BrokerError, match="No tick history is available"):
        broker.get_bars("EURUSD", Timeframe.S1, count=20)
