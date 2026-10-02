"""Tests for the incremental persistent bar store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.broker.mock_adapter import MockAdapter
from app.data.store import BarStore
from app.schemas import Bar, Timeframe


def _broker() -> MockAdapter:
    b = MockAdapter()
    b.connect()
    return b


def test_upsert_and_read(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()
    bars = broker.get_bars("EURUSD", Timeframe.H1, count=100)
    assert store.upsert("EURUSD", Timeframe.H1, bars) == 100

    cov = store.coverage("EURUSD", Timeframe.H1)
    assert cov.count == 100

    read = store.read("EURUSD", Timeframe.H1, count=50)
    assert len(read) == 50
    assert read[-1].time == bars[-1].time


def test_upsert_is_idempotent(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()
    bars = broker.get_bars("EURUSD", Timeframe.H1, count=50)
    store.upsert("EURUSD", Timeframe.H1, bars)
    store.upsert("EURUSD", Timeframe.H1, bars)
    assert store.coverage("EURUSD", Timeframe.H1).count == 50


def test_get_bars_fetches_only_missing(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()

    # First call populates.
    first = store.get_bars(broker, "EURUSD", Timeframe.H1, count=200)
    assert len(first) == 200
    cov1 = store.coverage("EURUSD", Timeframe.H1)

    # Second call with the same count must not grow the store much.
    second = store.get_bars(broker, "EURUSD", Timeframe.H1, count=200)
    assert len(second) == 200
    cov2 = store.coverage("EURUSD", Timeframe.H1)
    assert cov2.count <= cov1.count + 5  # only the recent refresh


def test_backfill_extends_history(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()
    store.get_bars(broker, "EURUSD", Timeframe.H1, count=100)
    cov_small = store.coverage("EURUSD", Timeframe.H1)

    # Request well beyond what the first page fetched to force a backfill.
    store.get_bars(broker, "EURUSD", Timeframe.H1, count=cov_small.count + 500)
    cov_big = store.coverage("EURUSD", Timeframe.H1)
    assert cov_big.count > cov_small.count
    assert cov_big.oldest < cov_small.oldest


def test_range_fetch(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    bars = store.get_bars(broker, "EURUSD", Timeframe.H1, start=start, end=end)
    assert len(bars) > 0
    assert bars[0].time >= int(start.timestamp())
    assert bars[-1].time <= int(end.timestamp())


def test_stats(tmp_path) -> None:
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = _broker()
    store.get_bars(broker, "EURUSD", Timeframe.H1, count=50)
    store.get_bars(broker, "GBPUSD", Timeframe.M15, count=50)
    stats = store.stats()
    assert len(stats) == 2
    assert {s["symbol"] for s in stats} == {"EURUSD", "GBPUSD"}


# -- gaps and stale tails -----------------------------------------------------

DAY = 86_400
HOUR = 3_600
FIRST = 1_700_000_000 - (1_700_000_000 % HOUR)  # an hour boundary


class GridBroker(MockAdapter):
    """A broker with clean, hour-aligned H1 bars from ``first`` to ``last``.

    ``hole`` (inclusive epoch bounds) is a stretch it has no bars for, so the
    same class plays both the broker that has the data and one that does not.
    """

    def __init__(self, first: int, last: int, hole: tuple[int, int] | None = None) -> None:
        super().__init__()
        self.first, self.last, self.hole = first, last, hole
        # Every [from, to] window asked for, so a test can tell a gap fill from the
        # ordinary history backfill.
        self.range_requests: list[tuple[int, int]] = []

    def _times(self) -> list[int]:
        times = range(self.first, self.last + 1, HOUR)
        if self.hole:
            return [t for t in times if not (self.hole[0] <= t <= self.hole[1])]
        return list(times)

    def get_bars(self, symbol, timeframe, count=500, start=None, end=None):
        times = self._times()
        if start is not None and end is not None:
            lo, hi = int(start.timestamp()), int(end.timestamp())
            self.range_requests.append((lo, hi))
            times = [t for t in times if lo <= t <= hi]
        else:
            times = times[-count:]
        return [Bar(time=t, open=1.0, high=1.1, low=0.9, close=1.0) for t in times]


def _continuous(bars: list[Bar], step: int = HOUR) -> bool:
    return all(b.time - a.time == step for a, b in zip(bars, bars[1:]))


def _seed(store: BarStore, broker: GridBroker) -> None:
    store.upsert("EURUSD", Timeframe.H1, broker.get_bars("EURUSD", Timeframe.H1, count=10_000))


def _hole_window(hole: tuple[int, int]) -> tuple[int, int]:
    """The request a gap fill makes: from the last bar before the hole to the first after."""
    return hole[0] - HOUR, hole[1] + HOUR


def test_hole_in_stored_history_is_refetched(tmp_path) -> None:
    """Bars that were removed from the middle of a series come back from the broker."""
    last = FIRST + 40 * DAY
    hole = (FIRST + 10 * DAY, FIRST + 25 * DAY)
    store = BarStore(db_path=tmp_path / "bars.db")
    _seed(store, GridBroker(FIRST, last, hole=hole))  # what is stored: full of holes
    complete = GridBroker(FIRST, last)  # what the broker really has

    bars = store.get_bars(complete, "EURUSD", Timeframe.H1, count=5000)

    assert _continuous(bars)
    assert bars[0].time == FIRST and bars[-1].time == last
    assert complete.range_requests.count(_hole_window(hole)) == 1


def test_hole_the_broker_cannot_fill_is_asked_about_once(tmp_path) -> None:
    last = FIRST + 40 * DAY
    hole = (FIRST + 10 * DAY, FIRST + 25 * DAY)
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = GridBroker(FIRST, last, hole=hole)
    _seed(store, broker)

    for _ in range(3):
        store.get_bars(broker, "EURUSD", Timeframe.H1, count=5000)

    assert broker.range_requests.count(_hole_window(hole)) == 1  # not once per request


def test_weekend_sized_gap_is_left_alone(tmp_path) -> None:
    last = FIRST + 20 * DAY
    weekend = (FIRST + 5 * DAY, FIRST + 7 * DAY)
    store = BarStore(db_path=tmp_path / "bars.db")
    broker = GridBroker(FIRST, last, hole=weekend)
    _seed(store, broker)

    store.get_bars(broker, "EURUSD", Timeframe.H1, count=5000)

    assert _hole_window(weekend) not in broker.range_requests


def test_stale_store_catches_up_to_the_broker(tmp_path) -> None:
    """A store last used days ago must not keep serving its old tail."""
    store = BarStore(db_path=tmp_path / "bars.db")
    _seed(store, GridBroker(FIRST, FIRST + 10 * DAY))  # stored up to day 10
    broker = GridBroker(FIRST, FIRST + 30 * DAY)  # the broker is at day 30

    bars = store.get_bars(broker, "EURUSD", Timeframe.H1, count=5000)

    assert bars[-1].time == FIRST + 30 * DAY
    assert _continuous(bars)


def test_a_single_missing_bar_at_the_tail_is_caught_up(tmp_path) -> None:
    """Stored up to T, broker's newest two bars are T+2h and T+3h: T+1h must be fetched."""
    store = BarStore(db_path=tmp_path / "bars.db")
    _seed(store, GridBroker(FIRST, FIRST + 10 * DAY))
    broker = GridBroker(FIRST, FIRST + 10 * DAY + 3 * HOUR)

    bars = store.get_bars(broker, "EURUSD", Timeframe.H1, count=5000)

    assert bars[-1].time == FIRST + 10 * DAY + 3 * HOUR
    assert _continuous(bars)


def test_range_request_fills_a_hole_inside_the_window(tmp_path) -> None:
    last = FIRST + 40 * DAY
    store = BarStore(db_path=tmp_path / "bars.db")
    _seed(store, GridBroker(FIRST, last, hole=(FIRST + 10 * DAY, FIRST + 25 * DAY)))
    complete = GridBroker(FIRST, last)

    start = datetime.fromtimestamp(FIRST + 5 * DAY, tz=timezone.utc)
    end = datetime.fromtimestamp(FIRST + 35 * DAY, tz=timezone.utc)
    bars = store.get_bars(complete, "EURUSD", Timeframe.H1, start=start, end=end)

    assert _continuous(bars)
    assert bars[0].time == FIRST + 5 * DAY and bars[-1].time == FIRST + 35 * DAY
