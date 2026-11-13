"""Tests for the replay engine."""

from __future__ import annotations

import pytest

from app.broker.mock_adapter import MockAdapter
from app.replay.engine import ReplayEngine
from app.schemas import Bar, OrderRequest, Timeframe


@pytest.fixture
def engine() -> ReplayEngine:
    broker = MockAdapter()
    broker.connect()
    return ReplayEngine.load(broker, "EURUSD", Timeframe.H1, count=200)


def test_load_and_state(engine: ReplayEngine) -> None:
    assert engine.total == 200
    assert engine.index == 0
    assert engine.cursor_time == engine.bars[0].time
    assert len(engine.visible_bars()) == 1


def test_state_reports_the_whole_window(engine: ReplayEngine) -> None:
    """The window's extent is in the state, not just what the cursor has revealed."""
    state = engine.state()
    assert state.total == 200
    assert state.first_time == engine.bars[0].time
    assert state.last_time == engine.bars[-1].time
    engine.step(5)
    assert engine.state().last_time == engine.bars[-1].time  # unchanged by the cursor


def test_step_and_seek(engine: ReplayEngine) -> None:
    engine.step(5)
    assert engine.index == 5
    assert len(engine.visible_bars()) == 6

    engine.seek(1000)  # clamps to last
    assert engine.index == engine.total - 1

    engine.seek(-10)  # clamps to first
    assert engine.index == 0


def test_speed_clamped(engine: ReplayEngine) -> None:
    engine.set_speed(0.001)
    assert engine.speed == 0.1
    engine.set_speed(9999)
    assert engine.speed == 100.0


def test_seek_time(engine: ReplayEngine) -> None:
    target = engine.bars[50].time
    state = engine.seek_time(target)
    assert state.index == 50
    # A timestamp between bars snaps to the nearest one.
    state = engine.seek_time(engine.bars[50].time + 1)
    assert state.index == 50


def test_reset(engine: ReplayEngine) -> None:
    engine.step(10)
    engine.play()
    state = engine.reset()
    assert state.index == 0
    assert state.playing is False


@pytest.mark.asyncio
async def test_run_advances_and_notifies(engine: ReplayEngine) -> None:
    seen: list[int] = []
    engine.add_listener(lambda s: seen.append(s.index))
    engine.seek(engine.total - 4)
    engine.play()
    await engine.run(base_interval=0.001)
    assert engine.index == engine.total - 1
    assert engine.playing is False
    assert seen  # listener fired


def test_interval_change_hides_future_prices_and_only_checks_remaining_stops() -> None:
    original = Bar(time=3600, open=100, high=105, low=95, close=100)
    engine = ReplayEngine.from_bars("EURUSD", Timeframe.H1, [original])
    engine.begin(0)
    paper = engine.paper
    placed = paper.place(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1, sl=90), original)
    assert placed.ok
    bars = [
        Bar(time=0, open=100, high=999, low=1, close=102),
        Bar(time=14400, open=102, high=111, low=100, close=110),
    ]
    minutes = [
        Bar(time=0, open=100, high=105, low=10, close=99),
        Bar(time=3600, open=99, high=102, low=95, close=100),
        Bar(time=3660, open=100, high=999, low=89, close=101),
    ]
    engine.change_timeframe(Timeframe.H4, bars, 0, minutes)
    assert engine.cursor_time == 3600
    assert engine.current_bar.close == 100
    assert engine.visible_bars()[-1].high == 105  # not the future spike
    assert engine.visible_bars()[-1].low == 10  # earlier history did not execute the stop
    assert not paper.closed and len(paper.positions) == 1
    moved = engine.advance()
    assert len(moved.closed) == 1
    assert moved.closed[0].reason == "sl" and moved.closed[0].exit_time == 3660
    assert not engine.partial_candle
    assert engine.visible_bars()[0].high == 999
