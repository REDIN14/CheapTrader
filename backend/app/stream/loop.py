"""The polling loop behind the live feed.

For every symbol somebody is looking at, the loop asks its ``Source`` for the ticks
that came since the last time, and it watches the account and the open positions for
any change. What it finds is handed to ``emit`` straight away, as plain dicts:

    {"type": "ticks", "symbol": "XAUUSD", "data": [tick, ...]}   oldest first, none twice
    {"type": "state", "positions": [...], "account": {...}, "orders": [...]}   only when something changed
    {"type": "hb"}                                               once a second: still alive

It is the same loop whether the data comes from MetaTrader (in a process of its own,
see ``mt5_feed.py``, so that nothing else in the server can ever make it wait) or from
the mock broker (in a thread of the server, see ``feed.py``). It knows nothing about
either: that is what a ``Source`` is for.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

Emit = Callable[[dict], None]

#: One failing call is reported this often at most, however often the loop retries it.
ERROR_EVERY = 5.0
#: The longest the loop rests between two looks because the terminal was slow to answer.
MAX_PAUSE = 0.25


class Source(Protocol):
    """Where the loop reads from."""

    def prepare(self, symbol: str) -> dict | None:
        """Start following ``symbol``; returns the tick it stands at now, if it has one.

        Ticks returned by ``ticks`` afterwards are the ones that come after that.
        """

    def forget(self, symbol: str) -> None:
        """Stop following ``symbol``."""

    def ticks(self, symbol: str) -> list[dict]:
        """The ticks since the previous call for this symbol, oldest first."""

    def state(self) -> dict:
        """``{"positions": [...], "account": {...}, "orders": [...]}`` as the broker has them right now."""


class FeedLoop:
    """Polls a source and emits what is new. ``run`` blocks; the rest may be called from any thread."""

    def __init__(
        self,
        source: Source,
        emit: Emit,
        *,
        interval: float = 0.005,
        state_interval: float = 0.05,
        heartbeat: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._source = source
        self._emit = emit
        self._interval = interval
        self._state_interval = state_interval
        self._heartbeat = heartbeat
        self._clock = clock
        self._sleep = sleep

        # Commands from other threads are queued and carried out by the loop itself,
        # so the set of symbols and the source are only ever touched from one thread.
        self._commands: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()
        self._stopped = threading.Event()
        self._symbols: set[str] = set()
        self._last_state: dict | None = None
        self._next_state = 0.0
        self._next_beat = 0.0
        self._kicked = False
        self._reported: dict[str, float] = {}

    # -- any thread -----------------------------------------------------------
    def subscribe(self, symbol: str) -> None:
        self._commands.put(("sub", symbol))

    def unsubscribe(self, symbol: str) -> None:
        self._commands.put(("unsub", symbol))

    def kick(self) -> None:
        """Read the account and the positions now instead of at the next look (after a trade)."""
        self._commands.put(("kick", None))

    def stop(self) -> None:
        self._stopped.set()

    # -- the loop -------------------------------------------------------------
    def run(self) -> None:
        self._emit({"type": "ready"})
        while not self._stopped.is_set():
            began = self._clock()
            self.step()
            # Normally a look takes a fraction of a millisecond and the loop rests for
            # its interval. When the terminal is busy with someone else's work a look
            # takes much longer; resting at least as long as the look took leaves the
            # terminal half its time for them instead of competing for all of it.
            took = self._clock() - began
            self._sleep(max(self._interval, min(MAX_PAUSE, took)))

    def step(self) -> None:
        """One look at everything. (Public so tests can drive the loop by hand.)"""
        self._drain()
        for symbol in tuple(self._symbols):
            self._poll_ticks(symbol)
        now = self._clock()
        if self._kicked or now >= self._next_state:
            self._kicked = False
            self._next_state = now + self._state_interval
            self._poll_state()
        if now >= self._next_beat:
            self._next_beat = now + self._heartbeat
            self._emit({"type": "hb", "t": time.time()})

    def _drain(self) -> None:
        while True:
            try:
                command, symbol = self._commands.get_nowait()
            except queue.Empty:
                return
            if command == "sub" and symbol:
                self._follow(symbol)
            elif command == "unsub" and symbol:
                if symbol in self._symbols:
                    self._symbols.discard(symbol)
                    self._guard(f"forget:{symbol}", self._source.forget, symbol)
            elif command == "kick":
                self._kicked = True

    def _follow(self, symbol: str) -> None:
        if symbol in self._symbols:
            return
        try:
            snapshot = self._source.prepare(symbol)
        except Exception as exc:  # noqa: BLE001 - an unknown symbol must not stop the feed
            self._report(f"prepare:{symbol}", exc, force=True)
            return
        self._symbols.add(symbol)
        if snapshot:
            self._emit({"type": "ticks", "symbol": symbol, "data": [snapshot], "snapshot": True})

    def _poll_ticks(self, symbol: str) -> None:
        try:
            ticks = self._source.ticks(symbol)
        except Exception as exc:  # noqa: BLE001
            self._report(f"ticks:{symbol}", exc)
            return
        if ticks:
            self._emit({"type": "ticks", "symbol": symbol, "data": ticks})

    def _poll_state(self) -> None:
        try:
            state = self._source.state()
        except Exception as exc:  # noqa: BLE001
            self._report("state", exc)
            return
        if state != self._last_state:
            self._last_state = state
            self._emit({"type": "state", **state})

    def _guard(self, key: str, fn: Callable[..., object], *args: object) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            self._report(key, exc)

    def _report(self, key: str, exc: BaseException, force: bool = False) -> None:
        """Say what went wrong, but not on every one of the 200 looks a second."""
        now = self._clock()
        if not force and now - self._reported.get(key, -ERROR_EVERY) < ERROR_EVERY:
            return
        self._reported[key] = now
        logger.warning("feed %s: %s", key, exc)
        self._emit({"type": "error", "where": key, "error": str(exc)})
