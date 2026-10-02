"""Running a feed loop: in a process of its own (MetaTrader) or in a thread (the mock).

Both present the same few methods to the hub. Events arrive on ``on_event`` from a
thread of the feed's own, so whoever receives them has to hand them over to the
server's event loop (the hub does).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Protocol

from app.procutil import child_log, kill_tree
from app.stream.loop import FeedLoop, Source

logger = logging.getLogger(__name__)

OnEvent = Callable[[dict], None]


class Feed(Protocol):
    def start(self, on_event: OnEvent) -> None: ...

    def stop(self) -> None: ...

    def subscribe(self, symbol: str) -> None: ...

    def unsubscribe(self, symbol: str) -> None: ...

    def kick(self) -> None: ...


class ThreadFeed:
    """A feed loop on a thread of this process."""

    def __init__(self, source: Source, *, interval: float = 0.005, state_interval: float = 0.05) -> None:
        self._source = source
        self._interval = interval
        self._state_interval = state_interval
        self._loop: FeedLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self, on_event: OnEvent) -> None:
        self._loop = FeedLoop(
            self._source, on_event, interval=self._interval, state_interval=self._state_interval
        )
        self._thread = threading.Thread(target=self._loop.run, name="feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def subscribe(self, symbol: str) -> None:
        if self._loop is not None:
            self._loop.subscribe(symbol)

    def unsubscribe(self, symbol: str) -> None:
        if self._loop is not None:
            self._loop.unsubscribe(symbol)

    def kick(self) -> None:
        if self._loop is not None:
            self._loop.kick()


class ProcessFeed:
    """A feed loop in a child process, spoken to in JSON lines (see ``mt5_feed``).

    The child is watched: if it dies, or goes quiet (it sends a heartbeat every
    second), it is started again and told what to follow, so a hiccup in the
    terminal connection heals itself. The hub is told with ``{"type": "feed"}``.

    The watch is deliberately patient. A child that is merely *slow* is not a child
    that is *dead*: when something else on the machine is working the terminal hard
    (another program downloading history through the same MetaTrader), every API call
    takes seconds, a fresh connection can take twenty, and a child that is killed for
    it only starts another connection and makes the terminal busier still. So:

    * silence is judged against a long limit (``stale_after``), a longer one while the
      child is still starting (``start_grace``);
    * if the watching thread itself was kept from running (the server held Python's
      lock, e.g. in a long MetaTrader call of its own), what the child said meanwhile
      has simply not been read yet, and nothing is decided that round;
    * restarts back off (0.5 s, 1 s, 2 s … up to ``max_delay``) and the back-off only
      resets after the child has stayed healthy for ``healthy_after``;
    * a child that is stopped is stopped with everything it started (``kill_tree``).

    A child that is slow is still *said* to be slow: when it has been silent for
    ``slow_after`` seconds the hub is told ``{"type": "feed", "status": "slow"}`` (and
    ``"up"`` again at its next word), so the screen can show that prices are late
    because MetaTrader is slow to answer, rather than leave the trader guessing.
    """

    def __init__(
        self,
        command: list[str],
        init: dict,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stale_after: float = 30.0,
        start_grace: float = 90.0,
        healthy_after: float = 30.0,
        first_delay: float = 0.5,
        max_delay: float = 15.0,
        poll_every: float = 0.5,
        slow_after: float = 2.5,
    ) -> None:
        self._command = command
        self._init = init
        self._cwd = cwd
        self._env = env
        self._stale_after = stale_after
        self._start_grace = start_grace
        self._healthy_after = healthy_after
        self._first_delay = first_delay
        self._max_delay = max_delay
        self._poll_every = poll_every
        self._slow_after = slow_after

        self._on_event: OnEvent = lambda _event: None
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._symbols: set[str] = set()
        self._symbols_lock = threading.Lock()
        self._heard = time.monotonic()
        self._ready = False
        self._slow = False
        self._slow_lock = threading.Lock()
        self._closing = threading.Event()
        self._watcher: threading.Thread | None = None
        self._generation = 0

    # -- the Feed interface ---------------------------------------------------
    def start(self, on_event: OnEvent) -> None:
        self._on_event = on_event
        self._closing.clear()
        self._spawn()
        self._watcher = threading.Thread(target=self._watch, name="feed-watch", daemon=True)
        self._watcher.start()

    def stop(self) -> None:
        self._closing.set()
        proc = self._proc
        if proc is None:
            return
        self._send({"c": "quit"})
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        kill_tree(proc)  # also the interpreter behind a launcher, should it still be there

    def subscribe(self, symbol: str) -> None:
        with self._symbols_lock:
            self._symbols.add(symbol)
        self._send({"c": "sub", "s": symbol})

    def unsubscribe(self, symbol: str) -> None:
        with self._symbols_lock:
            self._symbols.discard(symbol)
        self._send({"c": "unsub", "s": symbol})

    def kick(self) -> None:
        self._send({"c": "kick"})

    # -- the child ------------------------------------------------------------
    def _spawn(self) -> None:
        flags = 0
        if os.name == "nt":  # no console window, and Ctrl+C in ours must not hit the child
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(self._env or {})}
        proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=child_log(),  # its log lines go where ours go (the terminal, or logs/workers.log when built)
            cwd=self._cwd,
            env=env,
            creationflags=flags,
        )
        self._proc = proc
        self._generation += 1
        self._ready = False
        self._slow = False
        self._heard = time.monotonic()
        threading.Thread(
            target=self._read, args=(proc, self._generation), name="feed-read", daemon=True
        ).start()
        self._send(self._init)
        with self._symbols_lock:
            symbols = tuple(self._symbols)
        for symbol in symbols:
            self._send({"c": "sub", "s": symbol})

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                proc.stdin.write(data)
                proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass  # it is gone; the watcher notices and starts a new one

    def _read(self, proc: subprocess.Popen, generation: int) -> None:
        assert proc.stdout is not None
        try:
            for raw in iter(proc.stdout.readline, b""):
                try:
                    event = json.loads(raw)
                except ValueError:
                    logger.warning("feed process printed %r", raw[:200])
                    continue
                if generation != self._generation:
                    return  # an old child's last words
                now = time.monotonic()
                with self._slow_lock:
                    if self._slow:
                        self._slow = False
                        logger.info("the feed is answering again after %.1f s of silence", now - self._heard)
                        self._on_event({"type": "feed", "status": "up"})
                    self._heard = now
                if event.get("type") == "ready":
                    self._ready = True
                    self._on_event({"type": "feed", "status": "up"})
                    continue
                if event.get("type") == "fatal":
                    self._on_event({"type": "feed", "status": "down", "error": event.get("error")})
                    continue
                self._on_event(event)
        except (OSError, ValueError):
            pass  # the pipe was closed under us (the child was stopped)

    def judge(self, now: float, round_began: float, *, dead: bool) -> str:
        """What to do about the child this round: ``"ok"``, ``"wait"`` or ``"restart"``."""
        if dead:
            return "restart"
        if now - round_began > 3.0:
            return "wait"  # this thread was not running; the child's words are unread, not missing
        limit = self._stale_after if self._ready else self._start_grace
        return "restart" if now - self._heard > limit else "ok"

    def _check_slow(self, now: float) -> None:
        """Say so, once, when a running child has gone quiet for longer than it should."""
        with self._slow_lock:
            if self._ready and not self._slow and now - self._heard > self._slow_after:
                self._slow = True
                logger.warning(
                    "MetaTrader has not answered the feed for %.1f s; it may be busy with another program",
                    now - self._heard,
                )
                self._on_event({"type": "feed", "status": "slow"})

    def _watch(self) -> None:
        delay = self._first_delay
        healthy_since: float | None = None
        last_round = time.monotonic()
        while not self._closing.wait(self._poll_every):
            now = time.monotonic()
            proc = self._proc
            dead = proc is None or proc.poll() is not None
            verdict = self.judge(now, last_round, dead=dead)
            round_gap = now - last_round
            last_round = now
            if verdict == "wait":
                continue
            if verdict == "ok":
                if healthy_since is None:
                    healthy_since = now
                elif now - healthy_since >= self._healthy_after:
                    delay = self._first_delay  # it has been well for a while: forgive the past
                if round_gap < 1.0:  # (if this thread was kept from running, what the child said is just unread)
                    self._check_slow(now)
                continue

            healthy_since = None
            reason = "exited" if dead else "stopped answering"
            logger.warning("feed process %s; starting a new one in %.1fs", reason, delay)
            self._on_event({"type": "feed", "status": "restarting", "reason": reason})
            if proc is not None:
                kill_tree(proc)
            if self._closing.wait(delay):
                return
            delay = min(self._max_delay, delay * 2)
            try:
                self._spawn()
            except OSError as exc:
                logger.error("could not start the feed process: %s", exc)
