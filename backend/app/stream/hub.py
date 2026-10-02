"""From the feed to every open screen.

The feed produces events on a thread of its own; the hub receives them on the
server's event loop and gives each connected screen (a ``Channel``) what it asked
for: the ticks of its symbol, and the account and positions. A screen that cannot
keep up is not allowed to hold anything back or to make the server's memory grow:
what it has not been sent yet is merged (ticks are joined into one longer batch, a
newer account replaces an older one), and only the very oldest ticks are dropped
once a backlog gets absurd.
"""

from __future__ import annotations

import asyncio
import logging

from app.stream.feed import Feed

logger = logging.getLogger(__name__)

#: A screen that is this far behind loses its oldest ticks (about two minutes of a busy market).
MAX_PENDING_TICKS = 5000


class Channel:
    """What one connected screen is waiting to be sent."""

    def __init__(self) -> None:
        self.symbol: str | None = None
        self._ticks: list[dict] = []
        self._state: dict | None = None
        self._other: list[dict] = []
        self._wake = asyncio.Event()

    # -- filled by the hub ------------------------------------------------------
    def push_ticks(self, symbol: str, ticks: list[dict]) -> None:
        if symbol != self.symbol:
            return
        self._ticks.extend(ticks)
        if len(self._ticks) > MAX_PENDING_TICKS:
            del self._ticks[: len(self._ticks) - MAX_PENDING_TICKS]
        self._wake.set()

    def push_state(self, state: dict) -> None:
        self._state = state
        self._wake.set()

    def push_other(self, message: dict) -> None:
        self._other.append(message)
        self._wake.set()

    def reset_ticks(self) -> None:
        """The screen moved to another symbol: ticks of the old one are of no use."""
        self._ticks = []

    # -- read by the connection -------------------------------------------------
    async def get(self) -> list[dict]:
        """Wait until there is something to send, then take all of it."""
        await self._wake.wait()
        self._wake.clear()
        return self.take()

    def take(self) -> list[dict]:
        out: list[dict] = self._other
        self._other = []
        if self._ticks and self.symbol:
            out.append({"type": "ticks", "symbol": self.symbol, "data": self._ticks})
            self._ticks = []
        if self._state is not None:
            out.append({"type": "state", **self._state})
            self._state = None
        return out


class MarketHub:
    """Fans the feed out to the screens. All methods run on the server's event loop,
    except ``kick`` (and ``on_event``, which is how the feed's thread hands things over)."""

    def __init__(self, feed: Feed) -> None:
        self._feed = feed
        self._loop: asyncio.AbstractEventLoop | None = None
        self._channels: set[Channel] = set()
        self._refs: dict[str, int] = {}
        self._latest_tick: dict[str, dict] = {}
        self._latest_state: dict | None = None
        self.feed_status = "starting"
        # Which feed is followed. A feed that was let go of may still have events on their way
        # to the loop; they carry the number of the feed they came from and are dropped.
        self._generation = 0

    # -- lifecycle ----------------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._feed.start(self._sink(self._generation))

    def stop(self) -> None:
        self._feed.stop()

    def swap_feed(self, feed: Feed) -> None:
        """Follow another feed from now on (on the event loop): the broker changed, e.g. the app began on
        the synthetic market and a MetaTrader terminal has become ready. The screens stay connected. The
        prices, account and positions of the old feed are of no use any more: they are dropped, the
        symbols the screens look at are followed in the new feed, and each screen is told (a "broker"
        message) so that it can look at everything again."""
        old, self._feed = self._feed, feed
        self._generation += 1
        old.stop()
        self._latest_tick.clear()
        self._latest_state = None
        self.feed_status = "starting"
        feed.start(self._sink(self._generation))
        for symbol in self._refs:
            feed.subscribe(symbol)
        for channel in self._channels:
            channel.reset_ticks()
            channel.push_other({"type": "feed", "status": self.feed_status})
            channel.push_other({"type": "broker"})

    def _sink(self, generation: int):
        """What a feed is given to report to: its events are tagged with its number."""

        def sink(event: dict) -> None:
            loop = self._loop
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(self._arrive, generation, event)

        return sink

    def _arrive(self, generation: int, event: dict) -> None:
        if generation == self._generation:
            self._dispatch(event)

    def on_event(self, event: dict) -> None:
        """Called from any thread: something to tell the screens (not from a feed; see _sink)."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._dispatch, event)

    def announce(self, message: dict) -> None:
        """Tell every connected screen something (any thread): e.g. that its drawings changed."""
        self.on_event({"type": "notice", "message": message})

    def kick(self) -> None:
        """Read the account and the positions now. Safe from any thread (after a trade)."""
        self._feed.kick()

    # -- screens --------------------------------------------------------------------
    def attach(self) -> Channel:
        channel = Channel()
        self._channels.add(channel)
        if self.feed_status in ("slow", "restarting", "down"):
            # A screen that opens while the feed has trouble must not assume all is well.
            channel.push_other({"type": "feed", "status": self.feed_status})
        if self._latest_state is not None:
            channel.push_state(self._latest_state)
        return channel

    def detach(self, channel: Channel) -> None:
        self._channels.discard(channel)
        self._release(channel.symbol)
        channel.symbol = None

    def subscribe(self, channel: Channel, symbol: str) -> None:
        if channel.symbol == symbol:
            return
        self._release(channel.symbol)
        channel.reset_ticks()
        channel.symbol = symbol
        count = self._refs.get(symbol, 0)
        self._refs[symbol] = count + 1
        if count == 0:
            self._latest_tick.pop(symbol, None)  # whatever is cached has gone stale
            self._feed.subscribe(symbol)
        else:
            latest = self._latest_tick.get(symbol)
            if latest is not None:
                channel.push_ticks(symbol, [latest])
        if self._latest_state is not None:
            channel.push_state(self._latest_state)

    def _release(self, symbol: str | None) -> None:
        if symbol is None:
            return
        left = self._refs.get(symbol, 0) - 1
        if left > 0:
            self._refs[symbol] = left
            return
        self._refs.pop(symbol, None)
        self._latest_tick.pop(symbol, None)
        self._feed.unsubscribe(symbol)

    # -- events from the feed -----------------------------------------------------------
    def _dispatch(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "ticks":
            symbol = event["symbol"]
            data = event["data"]
            if data:
                self._latest_tick[symbol] = data[-1]
            for channel in self._channels:
                channel.push_ticks(symbol, data)
        elif kind == "state":
            # positions and account, and the pending orders when the feed knows about them
            self._latest_state = {k: event[k] for k in ("positions", "account", "orders") if k in event}
            for channel in self._channels:
                channel.push_state(self._latest_state)
        elif kind == "feed":
            self.feed_status = event.get("status", self.feed_status)
            for channel in self._channels:
                channel.push_other({"type": "feed", "status": self.feed_status})
        elif kind == "notice":
            for channel in self._channels:
                channel.push_other(event["message"])
        elif kind == "error":
            logger.warning("feed error in %s: %s", event.get("where"), event.get("error"))
