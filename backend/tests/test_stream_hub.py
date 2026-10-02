"""The hub: who is subscribed to what, what a slow screen is spared, what a new one is told."""

from __future__ import annotations

import asyncio

from app.stream.hub import MAX_PENDING_TICKS, MarketHub


class FakeFeed:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.on_event = None

    def start(self, on_event) -> None:
        self.on_event = on_event

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def subscribe(self, symbol: str) -> None:
        self.calls.append(("sub", symbol))

    def unsubscribe(self, symbol: str) -> None:
        self.calls.append(("unsub", symbol))

    def kick(self) -> None:
        self.calls.append(("kick", None))


def tick(msc: int) -> dict:
    return {"time": msc // 1000, "bid": 1.0, "ask": 1.1, "last": 0.0, "volume": 0.0, "time_msc": msc, "flags": 0}


def ticks_event(symbol: str, *msc: int) -> dict:
    return {"type": "ticks", "symbol": symbol, "data": [tick(m) for m in msc]}


STATE = {"type": "state", "positions": [{"ticket": 1}], "account": {"balance": 5.0}}


async def test_ticks_reach_only_the_screens_that_follow_that_symbol() -> None:
    feed = FakeFeed()
    hub = MarketHub(feed)
    a, b = hub.attach(), hub.attach()
    hub.subscribe(a, "EURUSD")
    hub.subscribe(b, "GBPUSD")
    hub._dispatch(ticks_event("EURUSD", 1, 2))
    hub._dispatch(ticks_event("GBPUSD", 3))
    assert [t["time_msc"] for t in a.take()[0]["data"]] == [1, 2]
    assert [t["time_msc"] for t in b.take()[0]["data"]] == [3]


async def test_the_feed_follows_a_symbol_once_however_many_screens_look_at_it() -> None:
    feed = FakeFeed()
    hub = MarketHub(feed)
    a, b = hub.attach(), hub.attach()
    hub.subscribe(a, "EURUSD")
    hub.subscribe(b, "EURUSD")
    assert feed.calls == [("sub", "EURUSD")]
    hub.detach(a)
    assert ("unsub", "EURUSD") not in feed.calls  # b still looks
    hub.detach(b)
    assert feed.calls[-1] == ("unsub", "EURUSD")


async def test_switching_symbol_lets_go_of_the_old_one() -> None:
    feed = FakeFeed()
    hub = MarketHub(feed)
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    hub._dispatch(ticks_event("EURUSD", 1))
    hub.subscribe(a, "GBPUSD")
    assert feed.calls == [("sub", "EURUSD"), ("unsub", "EURUSD"), ("sub", "GBPUSD")]
    assert a.take() == []  # the old symbol's ticks are no use to it
    hub._dispatch(ticks_event("EURUSD", 2))
    assert a.take() == []


async def test_a_second_screen_is_given_the_quote_the_first_one_already_has() -> None:
    feed = FakeFeed()
    hub = MarketHub(feed)
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    hub._dispatch(ticks_event("EURUSD", 10, 20))
    b = hub.attach()
    hub.subscribe(b, "EURUSD")
    assert [t["time_msc"] for t in b.take()[0]["data"]] == [20]


async def test_state_goes_to_everyone_and_a_new_screen_starts_with_the_latest() -> None:
    hub = MarketHub(FakeFeed())
    a = hub.attach()
    hub._dispatch(STATE)
    assert a.take() == [{"type": "state", "positions": [{"ticket": 1}], "account": {"balance": 5.0}}]
    late = hub.attach()
    assert late.take()[0]["positions"] == [{"ticket": 1}]


async def test_a_screen_that_is_behind_gets_one_longer_batch_and_the_newest_state() -> None:
    hub = MarketHub(FakeFeed())
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    hub._dispatch(ticks_event("EURUSD", 1, 2))
    hub._dispatch(ticks_event("EURUSD", 3))
    hub._dispatch({"type": "state", "positions": [], "account": {"balance": 1.0}})
    hub._dispatch({"type": "state", "positions": [], "account": {"balance": 2.0}})
    out = a.take()
    assert [t["time_msc"] for t in out[0]["data"]] == [1, 2, 3]
    assert [m["account"]["balance"] for m in out if m["type"] == "state"] == [2.0]


async def test_a_hopelessly_slow_screen_loses_only_its_oldest_ticks() -> None:
    hub = MarketHub(FakeFeed())
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    for start in range(0, MAX_PENDING_TICKS + 500, 500):
        hub._dispatch(ticks_event("EURUSD", *range(start, start + 500)))
    data = a.take()[0]["data"]
    assert len(data) == MAX_PENDING_TICKS
    assert data[-1]["time_msc"] == MAX_PENDING_TICKS + 499  # the newest survived


async def test_a_waiting_connection_wakes_when_something_arrives() -> None:
    hub = MarketHub(FakeFeed())
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    waiter = asyncio.create_task(a.get())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    hub._dispatch(ticks_event("EURUSD", 1))
    out = await asyncio.wait_for(waiter, 1)
    assert out[0]["type"] == "ticks"


async def test_events_from_the_feeds_thread_are_handed_to_the_event_loop() -> None:
    feed = FakeFeed()
    hub = MarketHub(feed)
    hub.start(asyncio.get_running_loop())
    a = hub.attach()
    hub.subscribe(a, "EURUSD")
    await asyncio.to_thread(feed.on_event, ticks_event("EURUSD", 42))  # as if from another thread
    out = await asyncio.wait_for(a.get(), 1)
    assert out[0]["data"][0]["time_msc"] == 42


async def test_feed_trouble_is_passed_on() -> None:
    hub = MarketHub(FakeFeed())
    a = hub.attach()
    hub._dispatch({"type": "feed", "status": "restarting", "reason": "exited"})
    assert a.take() == [{"type": "feed", "status": "restarting"}]
    assert hub.feed_status == "restarting"


async def test_a_screen_that_opens_while_the_feed_has_trouble_is_told() -> None:
    hub = MarketHub(FakeFeed())
    hub._dispatch({"type": "feed", "status": "slow"})
    assert hub.feed_status == "slow"
    late = hub.attach()
    assert late.take() == [{"type": "feed", "status": "slow"}]
    hub._dispatch({"type": "feed", "status": "up"})
    assert hub.attach().take() == []  # nothing to say once all is well again


async def test_a_connection_torn_down_in_a_hurry_still_lets_go_of_its_symbol(monkeypatch) -> None:
    """Cancelled again at every await (as when the server goes down), the handler must not skip the clean-up."""
    import types

    import anyio

    from app.api import ws

    feed = FakeFeed()
    hub = MarketHub(feed)
    monkeypatch.setattr(ws, "get_state", lambda: types.SimpleNamespace(hub=hub))

    class Socket:
        def __init__(self) -> None:
            self.inbox: asyncio.Queue = asyncio.Queue()

        async def accept(self) -> None:
            pass

        async def receive_json(self) -> dict:
            return await self.inbox.get()

        async def send_text(self, _text: str) -> None:
            pass

        async def close(self, code: int = 1000) -> None:
            pass

    sock = Socket()
    with anyio.CancelScope() as scope:
        runner = asyncio.create_task(asyncio.sleep(0))  # (just to have a loop turn before the handler starts)
        await runner
        await sock.inbox.put({"type": "subscribe", "symbol": "EURUSD"})
        asyncio.get_running_loop().call_later(0.1, scope.cancel)
        await ws.stream(sock)  # runs until the scope is cancelled
    assert scope.cancelled_caught
    assert hub._refs == {}
    assert ("unsub", "EURUSD") in feed.calls


async def test_kick_is_forwarded() -> None:
    feed = FakeFeed()
    MarketHub(feed).kick()
    assert feed.calls == [("kick", None)]


async def test_a_notice_reaches_every_screen_whatever_it_follows() -> None:
    """Something the server wants every open page to know (a script drew on the chart)."""
    hub = MarketHub(FakeFeed())
    hub.start(asyncio.get_running_loop())
    a, b = hub.attach(), hub.attach()
    hub.subscribe(a, "EURUSD")  # b follows nothing
    await asyncio.to_thread(hub.announce, {"type": "drawings", "symbol": "GBPUSD"})  # from a request's thread
    first = await asyncio.wait_for(a.get(), 1)
    second = await asyncio.wait_for(b.get(), 1)
    assert first == second == [{"type": "drawings", "symbol": "GBPUSD"}]


# -- the broker changes under the screens ------------------------------------------------------------------------------
async def test_swapping_the_feed_moves_the_open_screens_over_to_the_new_one() -> None:
    old, new = FakeFeed(), FakeFeed()
    hub = MarketHub(old)
    hub.start(asyncio.get_running_loop())
    screen = hub.attach()
    hub.subscribe(screen, "EURUSD")
    hub._dispatch(ticks_event("EURUSD", 1))
    hub._dispatch(STATE)
    screen.take()

    hub.swap_feed(new)
    assert ("stop", None) in old.calls
    assert ("sub", "EURUSD") in new.calls  # the screen still looks at it

    # something of the old feed is still on its way when the new one reports: only the new one counts
    old.on_event(ticks_event("EURUSD", 2))
    new.on_event(ticks_event("EURUSD", 3))
    await asyncio.sleep(0.05)
    told = screen.take()
    assert {"type": "broker"} in told
    assert [t["time_msc"] for m in told if m["type"] == "ticks" for t in m["data"]] == [3]


async def test_a_screen_that_opens_after_the_swap_is_not_given_what_the_old_feed_knew() -> None:
    old, new = FakeFeed(), FakeFeed()
    hub = MarketHub(old)
    hub.start(asyncio.get_running_loop())
    watcher = hub.attach()
    hub.subscribe(watcher, "EURUSD")
    hub._dispatch(ticks_event("EURUSD", 1))
    hub._dispatch(STATE)

    hub.swap_feed(new)
    late = hub.attach()
    hub.subscribe(late, "EURUSD")
    assert late.take() == []  # no price of the old market, no account of the old one
    new.on_event(STATE)
    await asyncio.sleep(0.05)
    assert [m["type"] for m in late.take()] == ["state"]


async def test_the_new_feed_reports_its_own_health() -> None:
    old, new = FakeFeed(), FakeFeed()
    hub = MarketHub(old)
    hub.start(asyncio.get_running_loop())
    old.on_event({"type": "feed", "status": "up"})
    await asyncio.sleep(0.02)
    assert hub.feed_status == "up"
    hub.swap_feed(new)
    assert hub.feed_status == "starting"
    new.on_event({"type": "feed", "status": "up"})
    await asyncio.sleep(0.02)
    assert hub.feed_status == "up"
