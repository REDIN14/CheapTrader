"""Tests for the replay engine."""

from __future__ import annotations

import pytest

from app.broker.mock_adapter import MockAdapter
from app.replay.engine import ReplayEngine
from app.schemas import Timeframe


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
