"""Bar replay engine.

Loads a historical bar series and exposes a virtual clock that can be played,
paused, stepped, and rewound. The engine never touches the broker after the
initial load, so replay is fully deterministic and offline.
"""

from __future__ import annotations

import asyncio
import logging
from bisect import bisect_left
from dataclasses import dataclass, field

from app.broker.base import BrokerAdapter
from app.replay.paper import PaperTradingEngine
from app.schemas import BacktestTrade, Bar, ReplayState, Timeframe

logger = logging.getLogger(__name__)


@dataclass
class Advance:
    """What a cursor move revealed and did."""

    state: ReplayState
    #: Bars the cursor moved over, oldest first.
    bars: list[Bar]
    #: Trades closed by a stop or target on the way.
    closed: list[BacktestTrade]


@dataclass
class ReplayEngine:
    """Virtual-clock bar replay over a fixed bar series."""

    symbol: str
    timeframe: Timeframe
    bars: list[Bar]
    index: int = 0
    speed: float = 1.0
    playing: bool = False
    contract_size: float = 100_000.0
    paper: PaperTradingEngine | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)
    _listeners: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.paper is None:
            self.paper = PaperTradingEngine(
                symbol=self.symbol, contract_size=self.contract_size
            )
        if self.bars:
            # The equity curve starts on the bar the replay begins on.
            self.paper.mark(self.bars[min(self.index, len(self.bars) - 1)])

    # -- construction ------------------------------------------------------
    @classmethod
    def load(
        cls,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        count: int = 2000,
        contract_size: float = 100_000.0,
    ) -> "ReplayEngine":
        bars = broker.get_bars(symbol, timeframe, count=count)
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            contract_size=contract_size,
        )

    @classmethod
    def from_bars(
        cls,
        symbol: str,
        timeframe: Timeframe,
        bars: list[Bar],
        contract_size: float = 100_000.0,
    ) -> "ReplayEngine":
        """Build a replay engine from an already-resolved bar series."""
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            contract_size=contract_size,
        )

    # -- state -------------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.bars)

    @property
    def cursor_time(self) -> int:
        if not self.bars:
            return 0
        return self.bars[min(self.index, self.total - 1)].time

    def visible_bars(self) -> list[Bar]:
        """Bars up to and including the cursor (what the chart should show)."""
        return self.bars[: self.index + 1]

    def state(self) -> ReplayState:
        return ReplayState(
            symbol=self.symbol,
            timeframe=self.timeframe,
            playing=self.playing,
            index=self.index,
            total=self.total,
            speed=self.speed,
            cursor_time=self.cursor_time,
            first_time=self.bars[0].time if self.bars else 0,
            last_time=self.bars[-1].time if self.bars else 0,
        )

    # -- controls ----------------------------------------------------------
    def begin(self, index: int = 0) -> ReplayState:
        """Put the cursor on its first bar and start the paper account's equity curve there."""
        self.index = max(0, min(index, self.total - 1)) if self.bars else 0
        if self.paper is not None and self.bars:
            self.paper.reset()
            self.paper.mark(self.bars[self.index])
        return self.state()

    def seek(self, index: int) -> ReplayState:
        """Move the cursor anywhere.

        Moving forward is the same as stepping: every bar on the way is checked
        against the open positions' stops and targets, so jumping to the end gives
        the result of having played it. Moving backward cannot undo trades, so it
        starts the paper account again from the new position.
        """
        if not self.bars:
            return self.state()
        target = max(0, min(index, self.total - 1))
        if target > self.index:
            self._play_bars(self.index + 1, target)
        elif target < self.index:
            self.begin(target)
        self.index = target
        return self.state()

    def _play_bars(self, first: int, last: int) -> None:
        """Let the paper account see bars ``first`` … ``last`` (both included)."""
        if self.paper is None:
            return
        for i in range(first, last + 1):
            self.paper.on_bar(self.bars[i])

    def step(self, delta: int = 1) -> ReplayState:
        """Advance the cursor, processing each bar for SL/TP hits."""
        return self.seek(self.index + delta)

    def advance(self, delta: int = 1) -> Advance:
        """Move the cursor and report the bars it revealed and the trades it closed."""
        before = self.index
        closed_before = len(self.paper.closed) if self.paper is not None else 0
        state = self.step(delta)
        revealed = self.bars[before + 1 : self.index + 1]
        closed = self.paper.closed[closed_before:] if self.paper is not None else []
        return Advance(state=state, bars=revealed, closed=list(closed))

    def seek_time(self, timestamp: int) -> ReplayState:
        """Seek to the bar whose time is closest to ``timestamp``."""
        if not self.bars:
            return self.state()
        return self.seek(self.nearest_index(timestamp))

    def nearest_index(self, timestamp: int) -> int:
        """Index of the bar whose time is closest to ``timestamp`` (the earlier one on a tie)."""
        times = [b.time for b in self.bars]
        i = bisect_left(times, timestamp)
        if i <= 0:
            return 0
        if i >= len(times):
            return len(times) - 1
        return i - 1 if timestamp - times[i - 1] <= times[i] - timestamp else i

    def set_speed(self, speed: float) -> ReplayState:
        self.speed = max(0.1, min(speed, 100.0))
        return self.state()

    def play(self) -> ReplayState:
        self.playing = True
        return self.state()

    def pause(self) -> ReplayState:
        self.playing = False
        return self.state()

    def reset(self) -> ReplayState:
        """Back to the first bar with a fresh paper account."""
        self.playing = False
        return self.begin(0)

    # -- async playback ----------------------------------------------------
    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def ensure_running(self, base_interval: float = 0.5) -> None:
        """Start the playback loop unless one is already running.

        Pressing play, pause, play quickly used to start a second loop while the
        first was still asleep, and two loops advance the cursor twice as fast.
        """
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(self.run(base_interval))

    async def run(self, base_interval: float = 0.5) -> None:
        """Advance the cursor while ``playing`` is True, notifying listeners."""
        while self.playing and self.index < self.total - 1:
            self.step(1)
            for cb in list(self._listeners):
                try:
                    cb(self.state())
                except Exception:  # noqa: BLE001
                    logger.exception("Replay listener failed")
            await asyncio.sleep(base_interval / self.speed)
        self.playing = False
        for cb in list(self._listeners):
            try:
                cb(self.state())
            except Exception:  # noqa: BLE001
                logger.exception("Replay listener failed")
