"""The feed loop: new ticks once and in order, state only when it changes, errors survived."""

from __future__ import annotations

import pytest

from app.stream.loop import FeedLoop


class FakeSource:
    def __init__(self) -> None:
        self.incoming: dict[str, list[dict]] = {}
        self.current: dict[str, dict | None] = {}
        self.account = {"balance": 100.0}
        self.positions: list[dict] = []
        self.failing: set[str] = set()
        self.prepared: list[str] = []
        self.forgotten: list[str] = []
        self.state_reads = 0

    def prepare(self, symbol: str):
        if symbol == "BAD":
            raise ValueError("unknown symbol")
        self.prepared.append(symbol)
        return self.current.get(symbol)

    def forget(self, symbol: str) -> None:
        self.forgotten.append(symbol)

    def ticks(self, symbol: str) -> list[dict]:
        if symbol in self.failing:
            raise RuntimeError("terminal hiccup")
        out, self.incoming[symbol] = self.incoming.get(symbol, []), []
        return out

    def state(self) -> dict:
        self.state_reads += 1
        return {"positions": list(self.positions), "account": dict(self.account)}


def tick(msc: int, bid: float = 1.0) -> dict:
    return {"time": msc // 1000, "bid": bid, "ask": bid + 0.0001, "last": 0.0, "volume": 0.0, "time_msc": msc, "flags": 0}


class Rig:
    def __init__(self, **kw) -> None:
        self.source = FakeSource()
        self.events: list[dict] = []
        self.now = 1000.0
        self.loop = FeedLoop(
            self.source, self.events.append, clock=lambda: self.now, sleep=lambda _s: None, **kw
        )

    def step(self, advance: float = 0.01) -> list[dict]:
        self.now += advance
        before = len(self.events)
        self.loop.step()
        return self.events[before:]


def kinds(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def test_ticks_are_sent_as_they_come_and_never_twice() -> None:
    rig = Rig()
    rig.loop.subscribe("EURUSD")
    rig.step()
    rig.source.incoming["EURUSD"] = [tick(1000), tick(1010), tick(1020)]
    first = [e for e in rig.step() if e["type"] == "ticks"]
    assert [t["time_msc"] for t in first[0]["data"]] == [1000, 1010, 1020]
    assert [e for e in rig.step() if e["type"] == "ticks"] == []
    rig.source.incoming["EURUSD"] = [tick(1030)]
    second = [e for e in rig.step() if e["type"] == "ticks"]
    assert [t["time_msc"] for t in second[0]["data"]] == [1030]


def test_a_new_subscriber_gets_the_current_quote_straight_away() -> None:
    rig = Rig()
    rig.source.current["EURUSD"] = tick(5000, 1.2)
    rig.loop.subscribe("EURUSD")
    events = rig.step()
    snapshot = next(e for e in events if e["type"] == "ticks")
    assert snapshot["symbol"] == "EURUSD"
    assert snapshot["data"][0]["bid"] == 1.2
    assert snapshot.get("snapshot") is True


def test_only_subscribed_symbols_are_read() -> None:
    rig = Rig()
    rig.source.incoming["GBPUSD"] = [tick(1)]
    rig.step()
    assert rig.source.incoming["GBPUSD"] == [tick(1)]  # nobody asked, so nothing was taken
    rig.loop.subscribe("GBPUSD")
    assert any(e["type"] == "ticks" for e in rig.step())
    rig.loop.unsubscribe("GBPUSD")
    rig.step()
    assert rig.source.forgotten == ["GBPUSD"]
    rig.source.incoming["GBPUSD"] = [tick(2)]
    assert [e for e in rig.step() if e["type"] == "ticks"] == []


def test_state_is_sent_once_and_again_only_when_it_changes() -> None:
    rig = Rig(state_interval=0.05)
    first = [e for e in rig.step() if e["type"] == "state"]
    assert len(first) == 1 and first[0]["account"] == {"balance": 100.0}
    assert [e for e in rig.step(0.06) if e["type"] == "state"] == []  # looked, nothing new
    rig.source.positions = [{"ticket": 1}]
    changed = [e for e in rig.step(0.06) if e["type"] == "state"]
    assert changed[0]["positions"] == [{"ticket": 1}]


def test_state_is_read_at_the_set_pace_not_on_every_look() -> None:
    rig = Rig(state_interval=0.05)
    rig.step(0.0)
    reads = rig.source.state_reads
    for _ in range(4):
        rig.step(0.01)  # 40 ms in all: too soon
    assert rig.source.state_reads == reads
    rig.step(0.02)
    assert rig.source.state_reads == reads + 1


def test_a_kick_reads_the_state_at_once() -> None:
    rig = Rig(state_interval=10.0)
    rig.step()
    rig.source.positions = [{"ticket": 7}]
    assert [e for e in rig.step(0.01) if e["type"] == "state"] == []
    rig.loop.kick()
    kicked = [e for e in rig.step(0.001) if e["type"] == "state"]
    assert kicked[0]["positions"] == [{"ticket": 7}]


def test_an_unknown_symbol_is_reported_and_the_rest_carry_on() -> None:
    rig = Rig()
    rig.loop.subscribe("BAD")
    rig.loop.subscribe("EURUSD")
    events = rig.step()
    assert any(e["type"] == "error" and e["where"] == "prepare:BAD" for e in events)
    rig.source.incoming["EURUSD"] = [tick(1)]
    assert any(e["type"] == "ticks" for e in rig.step())


def test_a_failing_read_is_reported_rarely_and_recovers() -> None:
    rig = Rig()
    rig.loop.subscribe("EURUSD")
    rig.step()
    rig.source.failing.add("EURUSD")
    errors = []
    for _ in range(50):  # 0.5 s of looks
        errors += [e for e in rig.step(0.01) if e["type"] == "error"]
    assert len(errors) == 1  # not one per look
    rig.source.failing.clear()
    rig.source.incoming["EURUSD"] = [tick(9)]
    assert any(e["type"] == "ticks" for e in rig.step())


def test_a_heartbeat_comes_every_second() -> None:
    rig = Rig(heartbeat=1.0)
    beats = 0
    for _ in range(250):
        beats += sum(1 for e in rig.step(0.01) if e["type"] == "hb")
    assert beats == 3  # at 0 s, 1 s and 2 s


def test_a_slow_terminal_is_given_room() -> None:
    """When a look takes long (someone else is working the terminal), the loop rests as long again."""
    rig = Rig(interval=0.005)
    rests: list[float] = []
    state = rig.source.state

    def slow_state() -> dict:
        rig.now += 0.12  # the terminal took 120 ms to answer
        return state()

    rig.source.state = slow_state  # type: ignore[method-assign]

    def sleep(seconds: float) -> None:
        rests.append(seconds)
        if len(rests) == 3:
            rig.loop.stop()

    rig.loop._sleep = sleep
    rig.loop.run()
    assert rests[0] == pytest.approx(0.12)  # not 5 ms: as long as the look took
    assert all(r > 0.1 for r in rests)

    quick = Rig(interval=0.005)
    quick_rests: list[float] = []

    def quick_sleep(seconds: float) -> None:
        quick_rests.append(seconds)
        quick.loop.stop()

    quick.loop._sleep = quick_sleep
    quick.loop.run()
    assert quick_rests == [0.005]  # a fast terminal: back to the usual rhythm


def test_the_rest_is_never_longer_than_a_quarter_second() -> None:
    rig = Rig(interval=0.005)
    rests: list[float] = []
    state = rig.source.state

    def very_slow_state() -> dict:
        rig.now += 5.0
        return state()

    rig.source.state = very_slow_state  # type: ignore[method-assign]

    def sleep(seconds: float) -> None:
        rests.append(seconds)
        rig.loop.stop()

    rig.loop._sleep = sleep
    rig.loop.run()
    assert rests == [0.25]


def test_run_announces_itself_and_stops_on_request() -> None:
    rig = Rig()
    calls = []

    def sleep(_seconds: float) -> None:
        calls.append(1)
        if len(calls) == 3:
            rig.loop.stop()

    rig.loop._sleep = sleep
    rig.loop.run()
    assert rig.events[0] == {"type": "ready"}
    assert len(calls) == 3
