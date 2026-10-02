"""The MetaTrader feed and trading *processes*, run for real against a stand-in terminal
(tests/fake_mt5). What matters here is what no unit test of the loop can show:

* every tick reaches the server, none twice, even at 100 a second;
* a trade that waits for the broker does not make the price wait too (the whole reason
  the trading calls live in a process of their own);
* a position changed "in the terminal" is reported at once;
* a feed process that dies comes back by itself.
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import subprocess
import sys
import threading
import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.broker.base import BrokerError
from app.broker.isolated import IsolatedMT5Adapter, TradeProcess, backend_root
from app.config import Settings
from app.schemas import ModifyRequest, OrderRequest, Timeframe
from app.stream.feed import ProcessFeed

FAKE = Path(__file__).parent / "fake_mt5"


@pytest.fixture
def world(tmp_path):
    """A fake terminal whose state every process shares through one file."""
    path = tmp_path / "terminal.json"
    state = {
        "rate": 100,
        "t0": int(time.time() * 1000) - 3000,
        "base": 1.1,
        "step": 0.00001,
        "order_delay": 0.0,
        "requotes": 0,
        "positions": [],
        "orders": [],
        "next_ticket": 1,
        "symbols": {"EURUSD": {"visible": True}, "GBPUSD": {"visible": False}},
    }
    path.write_text(json.dumps(state))

    def read() -> dict:
        return json.loads(path.read_text())

    def edit(**changes) -> None:
        state = read()
        state.update(changes)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, path)

    return types.SimpleNamespace(
        env={"FAKE_MT5_STATE": str(path), "PYTHONPATH": str(FAKE)}, read=read, edit=edit
    )


def start_feed(world, command=None, env=None, **options) -> tuple[ProcessFeed, queue.Queue]:
    events: queue.Queue = queue.Queue()
    init = options.pop("init", {})
    feed = ProcessFeed(
        command or [sys.executable, "-m", "app.stream.mt5_feed"],
        {"settings": {}, "interval": 0.005, "state_interval": 0.02, **init},
        cwd=backend_root(),
        env={**world.env, **(env or {})},
        **{"stale_after": 3.0, "first_delay": 0.2, **options},
    )
    feed.start(events.put)
    return feed, events


def drain(events: queue.Queue, seconds: float) -> list[dict]:
    out: list[dict] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            out.append(events.get(timeout=0.05))
        except queue.Empty:
            pass
    return out


def wait_for(events: queue.Queue, predicate, timeout: float = 8.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            event = events.get(timeout=0.05)
        except queue.Empty:
            continue
        if predicate(event):
            return event
    raise AssertionError("the event never came")


def tick_times(events: list[dict], symbol: str = "EURUSD") -> list[int]:
    return [t["time_msc"] for e in events if e["type"] == "ticks" and e["symbol"] == symbol for t in e["data"]]


@pytest.fixture
def feed(world):
    feed, events = start_feed(world)
    wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up")
    yield feed, events
    feed.stop()


def make_trader(world, role: str = "trader") -> TradeProcess:
    return TradeProcess(
        Settings(_env_file=None),
        command=[sys.executable, "-m", "app.broker.trade_worker", "--role", role],
        env=world.env,
        role=role,
    )


@pytest.fixture
def trader(world):
    trader = make_trader(world)
    trader.start()
    yield trader
    trader.stop()


# -- the feed process ---------------------------------------------------------------
def test_every_tick_arrives_exactly_once_and_in_order(feed) -> None:
    feed, events = feed
    feed.subscribe("EURUSD")
    got = drain(events, 1.5)
    times = tick_times(got)
    assert len(times) > 100  # a 100-a-second market for 1.5 seconds
    # the fake market ticks every 10 ms exactly: if the feed missed or doubled one it shows here
    assert {b - a for a, b in itertools.pairwise(times)} == {10}


def test_a_new_subscriber_starts_with_the_current_quote(feed) -> None:
    feed, events = feed
    feed.subscribe("EURUSD")
    first = wait_for(events, lambda e: e.get("type") == "ticks")
    assert first["snapshot"] is True and len(first["data"]) == 1


def test_a_position_changed_in_the_terminal_is_reported_at_once(world, feed) -> None:
    feed, events = feed
    wait_for(events, lambda e: e.get("type") == "state")
    changed = time.monotonic()
    world.edit(
        positions=[
            {"ticket": 5, "symbol": "EURUSD", "type": 0, "volume": 0.1, "price_open": 1.1, "price_current": 1.1,
             "sl": 0.0, "tp": 0.0, "profit": 0.0, "time": 1, "comment": ""}
        ]
    )
    state = wait_for(events, lambda e: e.get("type") == "state" and e["positions"])
    assert state["positions"][0]["ticket"] == 5 and state["positions"][0]["side"] == "BUY"
    assert time.monotonic() - changed < 0.5


def test_a_failed_read_is_not_mistaken_for_no_positions(world, feed) -> None:
    feed, events = feed
    world.edit(
        positions=[
            {"ticket": 3, "symbol": "EURUSD", "type": 0, "volume": 0.1, "price_open": 1.1, "price_current": 1.1,
             "sl": 0.0, "tp": 0.0, "profit": 0.0, "time": 1, "comment": ""}
        ]
    )
    wait_for(events, lambda e: e.get("type") == "state" and e["positions"])
    world.edit(positions_fail=True)
    during = drain(events, 0.6)
    assert not any(e.get("type") == "state" for e in during)  # nothing claims the position is gone
    assert any(e.get("type") == "error" and e["where"] == "state" for e in during)
    world.edit(positions_fail=False, positions=[])
    wait_for(events, lambda e: e.get("type") == "state" and e["positions"] == [])  # an empty list is believed


def test_a_kick_reads_the_positions_without_waiting_for_the_next_look(world) -> None:
    feed, events = start_feed(world, init={"state_interval": 30.0})
    try:
        wait_for(events, lambda e: e.get("type") == "state")  # the first look
        world.edit(positions=[
            {"ticket": 9, "symbol": "EURUSD", "type": 1, "volume": 0.2, "price_open": 1.1, "price_current": 1.1,
             "sl": 0.0, "tp": 0.0, "profit": 0.0, "time": 1, "comment": ""}
        ])
        started = time.monotonic()
        feed.kick()
        state = wait_for(events, lambda e: e.get("type") == "state" and e["positions"], timeout=2.0)
        assert state["positions"][0]["ticket"] == 9
        assert time.monotonic() - started < 0.5
    finally:
        feed.stop()


def test_leaving_a_symbol_stops_its_ticks(feed) -> None:
    feed, events = feed
    feed.subscribe("EURUSD")
    wait_for(events, lambda e: e.get("type") == "ticks")
    feed.unsubscribe("EURUSD")
    drain(events, 0.3)  # whatever was already on its way
    assert tick_times(drain(events, 0.5)) == []


def test_a_symbol_outside_the_market_watch_is_added_so_it_can_stream(world, feed) -> None:
    feed, events = feed
    feed.subscribe("GBPUSD")
    wait_for(events, lambda e: e.get("type") == "ticks" and e["symbol"] == "GBPUSD")
    assert world.read()["symbols"]["GBPUSD"]["visible"] is True


def test_a_symbol_the_terminal_does_not_know_is_reported_and_the_rest_carry_on(feed) -> None:
    feed, events = feed
    feed.subscribe("NOPE")
    error = wait_for(events, lambda e: e.get("type") == "error")
    assert "NOPE" in error["where"]
    feed.subscribe("EURUSD")
    wait_for(events, lambda e: e.get("type") == "ticks" and e["symbol"] == "EURUSD")


def test_a_feed_process_that_dies_comes_back_and_carries_on_following(world) -> None:
    feed, events = start_feed(world)
    try:
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up")
        feed.subscribe("EURUSD")
        wait_for(events, lambda e: e.get("type") == "ticks")
        feed._proc.kill()
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "restarting", timeout=5)
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=8)
        wait_for(events, lambda e: e.get("type") == "ticks" and e["symbol"] == "EURUSD", timeout=5)
    finally:
        feed.stop()


# -- a busy terminal, and a watchdog that keeps its head ---------------------------------------
def count_processes(tag: str) -> int:
    """How many processes have `tag` on their command line (Windows)."""
    script = (
        "(Get-CimInstance Win32_Process | Where-Object "
        f"{{ $_.CommandLine -like '*{tag}*' -and $_.ProcessId -ne $PID }} | Measure-Object).Count"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=30)
    return int(out.stdout.strip() or 0)


def test_a_slow_start_is_waited_for_not_restarted(world) -> None:
    """The terminal takes 2.5 s to accept a connection: the silence is not a dead child."""
    feed, events = start_feed(world, env={"FAKE_MT5_INIT_DELAY": "2.5"}, stale_after=1.0, start_grace=20.0)
    try:
        seen = []
        end = time.monotonic() + 8
        while time.monotonic() < end:
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                continue
            seen.append(event)
            if event.get("type") == "feed" and event.get("status") == "up":
                break
        statuses = [e.get("status") for e in seen if e.get("type") == "feed"]
        assert "up" in statuses, "it never came up"
        assert "restarting" not in statuses
    finally:
        feed.stop()


def test_a_slow_terminal_loses_no_tick(world) -> None:
    """Every read takes 120 ms (another program is working the terminal): later, but all of them, once."""
    feed, events = start_feed(world, env={"FAKE_MT5_CALL_DELAY": "0.12"}, stale_after=5.0)
    try:
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=10)
        feed.subscribe("EURUSD")
        got = drain(events, 4.0)
        times = tick_times(got)
        assert len(times) > 150  # a 100-a-second market: still a good share of 4 s of it
        assert {b - a for a, b in zip(times, times[1:], strict=False)} == {10}  # none missing, none twice
        assert not any(e.get("status") == "restarting" for e in got if e.get("type") == "feed")
    finally:
        feed.stop()


STUCK_AFTER_READY = (
    "import sys, time\n"
    "sys.stdout.write('{\"type\":\"ready\"}' + chr(10)); sys.stdout.flush()\n"
    "time.sleep(300)  # TAG\n"
)


SLOW_THEN_ALIVE = (
    "import sys, time\n"
    "def say(s):\n"
    "    sys.stdout.write(s + chr(10)); sys.stdout.flush()\n"
    "say('{\"type\":\"ready\"}')\n"
    "time.sleep(2.2)  # MetaTrader is slow to answer\n"
    "for _ in range(60):\n"
    "    say('{\"type\":\"hb\"}'); time.sleep(0.1)\n"
    "time.sleep(60)\n"
)


def test_a_child_that_is_slow_to_answer_is_called_slow_and_then_well_again(world) -> None:
    feed, events = start_feed(
        world,
        command=[sys.executable, "-c", SLOW_THEN_ALIVE],
        stale_after=20.0,  # slow is not dead: no restart
        start_grace=20.0,
        poll_every=0.1,
        slow_after=1.0,
    )
    try:
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=8)
        began = time.monotonic()
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "slow", timeout=5)
        assert 0.8 < time.monotonic() - began < 2.1  # after the limit, before the child spoke again
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=5)
        after = drain(events, 0.6)
        assert not any(e.get("status") in ("slow", "restarting") for e in after if e.get("type") == "feed")
    finally:
        feed.stop()


def test_a_busy_terminal_makes_the_feed_slow_not_dead(world) -> None:
    """Every read takes 1.6 s: the real feed process looks slow, says so, and keeps its ticks."""
    feed, events = start_feed(
        world, env={"FAKE_MT5_CALL_DELAY": "1.6"}, stale_after=20.0, start_grace=20.0, poll_every=0.1, slow_after=1.2
    )
    try:
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=10)
        feed.subscribe("EURUSD")
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "slow", timeout=8)
        got = drain(events, 6.0)
        statuses = [e.get("status") for e in got if e.get("type") == "feed"]
        assert "restarting" not in statuses
        assert tick_times(got)  # what the terminal did produce arrived, late
    finally:
        feed.stop()


def test_a_child_that_goes_silent_is_replaced_after_the_limit(world) -> None:
    """Ready, then nothing for good (stuck inside a terminal call): replaced, the old one gone."""
    tag = f"silent-{os.getpid()}-{time.monotonic_ns()}"
    feed, events = start_feed(
        world,
        command=[sys.executable, "-c", STUCK_AFTER_READY.replace("TAG", tag)],
        stale_after=1.5,
        start_grace=5.0,
        first_delay=0.2,
        poll_every=0.1,
    )
    try:
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=8)
        began = time.monotonic()
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "restarting", timeout=8)
        assert 1.2 < time.monotonic() - began < 5  # after the limit, not before
        wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=8)  # the new one
    finally:
        feed.stop()
    if os.name == "nt":
        time.sleep(1.0)
        assert count_processes(tag) == 0, "an old child is still running"


def test_restarts_back_off_while_the_child_keeps_failing(world) -> None:
    feed, events = start_feed(
        world,
        command=[sys.executable, "-c", "import sys; sys.exit(3)"],
        first_delay=0.5,
        max_delay=4.0,
        poll_every=0.05,
    )
    try:
        stamps = []
        end = time.monotonic() + 15
        while time.monotonic() < end and len(stamps) < 4:
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if event.get("type") == "feed" and event.get("status") == "restarting":
                stamps.append(time.monotonic())
        assert len(stamps) >= 4, f"only {len(stamps)} restarts"
        gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
        # 0.5, 1.0, 2.0 … plus the time each start takes, which varies on a busy machine
        assert gaps[0] < gaps[1] < gaps[2] and gaps[2] > gaps[0] * 1.6, gaps
    finally:
        feed.stop()


def test_the_watchdog_judges_patiently() -> None:
    feed = ProcessFeed(["x"], {}, stale_after=30.0, start_grace=90.0)
    feed._heard = 100.0
    # dead is dead
    assert feed.judge(101.0, 100.5, dead=True) == "restart"
    # a thread that was not running (the server held Python's lock) decides nothing
    assert feed.judge(140.0, 100.0, dead=False) == "wait"
    # still starting: 60 s of silence is within the grace period
    feed._ready = False
    assert feed.judge(160.0, 159.5, dead=False) == "ok"
    assert feed.judge(200.0, 199.5, dead=False) == "restart"
    # up and running: 20 s is a quiet moment, 40 s is not
    feed._ready = True
    feed._heard = 100.0
    assert feed.judge(120.0, 119.5, dead=False) == "ok"
    assert feed.judge(140.0, 139.5, dead=False) == "restart"


@pytest.mark.skipif(os.name != "nt", reason="the launcher / interpreter pair is a Windows thing")
def test_no_process_is_left_behind_when_the_feed_restarts_or_stops(world) -> None:
    tag = f"orphans-{os.getpid()}-{time.monotonic_ns()}"
    feed, events = start_feed(
        world,
        command=[sys.executable, "-m", "app.stream.mt5_feed", "--tag", tag],
        stale_after=3.0,
        poll_every=0.1,
    )
    wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up")
    assert count_processes(tag) >= 1
    feed._proc.kill()  # only the launcher: the interpreter behind it is orphaned unless cleaned up
    wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "restarting", timeout=8)
    wait_for(events, lambda e: e.get("type") == "feed" and e.get("status") == "up", timeout=10)
    time.sleep(1.5)
    # one child (a launcher and its interpreter), not two generations of them
    assert count_processes(tag) <= 2, f"{count_processes(tag)} processes carry the tag"
    feed.stop()
    time.sleep(1.5)
    assert count_processes(tag) == 0, "the feed left a process behind"


# -- the trading process ---------------------------------------------------------------
def order(**kw) -> dict:
    return OrderRequest(symbol="EURUSD", side="BUY", volume=0.1, **kw).model_dump(mode="json")


def test_a_market_order_goes_through_and_says_how_long_the_broker_took(world, trader) -> None:
    world.edit(order_delay=0.25)
    result = trader.call("place_order", order())
    assert result["ok"] and result["retcode"] == 10009
    assert result["latency_ms"] >= 200
    (position,) = world.read()["positions"]
    assert position["symbol"] == "EURUSD" and position["volume"] == 0.1


def test_a_requote_is_asked_again_at_the_new_price(world, trader) -> None:
    world.edit(requotes=2, order_delay=0.05)  # the market ticks on while "the broker" answers
    result = trader.call("place_order", order())
    assert result["ok"]
    sent = world.read()["orders"]
    assert len(sent) == 3
    assert sent[2]["price"] > sent[0]["price"]  # the market moved on and the retry followed it


def test_it_gives_up_after_three_requotes(world, trader) -> None:
    world.edit(requotes=10)
    result = trader.call("place_order", order())
    assert not result["ok"] and result["retcode"] == 10004
    assert len(world.read()["orders"]) == 3


def test_changing_the_stop_keeps_the_target(world, trader) -> None:
    trader.call("place_order", order(tp=1.3))
    (position,) = world.read()["positions"]
    result = trader.call("modify_position", ModifyRequest(ticket=position["ticket"], sl=1.0).model_dump(mode="json"))
    assert result["ok"]
    sent = world.read()["orders"][-1]
    assert sent["sl"] == 1.0 and sent["tp"] == 1.3  # not mentioned, not removed
    assert world.read()["positions"][0]["tp"] == 1.3


def test_closing_a_position(world, trader) -> None:
    trader.call("place_order", order())
    (position,) = world.read()["positions"]
    result = trader.call("close_position", {"ticket": position["ticket"]})
    assert result["ok"] and world.read()["positions"] == []
    assert not trader.call("close_position", {"ticket": position["ticket"]})["ok"]


def test_the_trading_process_can_start_in_the_background_and_trades_wait_for_it(world) -> None:
    trader = make_trader(world)
    trader._env = {**world.env, "FAKE_MT5_INIT_DELAY": "1.5"}
    began = time.monotonic()
    trader.start_in_background()
    assert time.monotonic() - began < 0.5  # the server does not wait for a slow terminal
    result = trader.call("place_order", order())  # …but a trade does, and then goes through
    assert result["ok"]
    assert time.monotonic() - began >= 1.4
    trader.stop()


def test_a_dead_trading_process_is_replaced_on_the_next_call(world, trader) -> None:
    trader._proc.kill()
    trader._proc.wait()
    time.sleep(0.2)
    result = trader.call("place_order", order())
    assert result["ok"]


def test_a_call_that_dies_midway_says_so_instead_of_hanging(world, trader) -> None:
    world.edit(order_delay=5.0)
    threading.Timer(0.4, lambda: trader._proc.kill()).start()
    started = time.monotonic()
    with pytest.raises(BrokerError, match="before it answered"):
        trader.call("place_order", order())
    assert time.monotonic() - started < 3


# -- the two together -------------------------------------------------------------------------
def test_the_price_keeps_moving_while_an_order_waits_for_the_broker(world, feed, trader) -> None:
    """The reason for the whole design."""
    feed, events = feed
    feed.subscribe("EURUSD")
    drain(events, 0.3)
    world.edit(order_delay=0.8)

    done = threading.Event()
    result: dict = {}

    def place() -> None:
        result.update(trader.call("place_order", order()))
        done.set()

    began = time.monotonic()
    threading.Thread(target=place).start()
    arrivals: list[float] = []
    while not done.is_set():
        try:
            event = events.get(timeout=0.02)
        except queue.Empty:
            continue
        if event.get("type") == "ticks":
            arrivals.append(time.monotonic())
    took = time.monotonic() - began

    assert result["ok"] and took >= 0.75  # the order really did wait
    gaps = [b - a for a, b in itertools.pairwise(arrivals)]
    assert len(arrivals) > 40  # ticks kept coming the whole time
    assert max(gaps) < 0.2  # and never stopped for the 800 ms the broker took


def test_a_trade_made_here_shows_up_in_the_feed_after_a_kick(world, feed, trader) -> None:
    feed, events = feed
    wait_for(events, lambda e: e.get("type") == "state")
    trader.call("place_order", order())
    feed.kick()
    state = wait_for(events, lambda e: e.get("type") == "state" and e["positions"], timeout=2.0)
    assert state["positions"][0]["volume"] == 0.1


# -- the reader process: the server makes no terminal call of its own ----------------------------
def make_adapter(world, **reader_env) -> IsolatedMT5Adapter:
    reader = make_trader(world, "reader")
    reader._env = {**world.env, **reader_env}
    return IsolatedMT5Adapter(Settings(_env_file=None), trader=make_trader(world), reader=reader)


@pytest.fixture
def adapter(world):
    adapter = make_adapter(world)
    adapter.connect()
    yield adapter
    adapter.disconnect()


def test_the_adapter_the_server_uses_trades_through_the_process(adapter) -> None:
    assert adapter._mt5 is None  # it never loaded the terminal's package into the server
    assert adapter.get_tick("EURUSD") is not None
    result = adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1))
    assert result.ok and result.latency_ms >= 0
    (position,) = adapter.get_positions()
    assert position.ticket == result.order_id
    assert adapter.close_position(position.ticket).ok
    assert adapter.get_positions() == []


def test_bars_symbols_ticks_and_the_account_come_from_the_reader(adapter) -> None:
    bars = adapter.get_bars("EURUSD", Timeframe.M1, count=50)
    assert len(bars) == 50
    assert [b.time for b in bars] == sorted(b.time for b in bars)
    assert all(b.time % 60 == 0 for b in bars)
    assert abs(bars[-1].time - time.time()) < 61  # the bar that is forming now
    assert bars[0].high > bars[0].low > 0 and isinstance(bars[0].tick_volume, int)

    start = datetime(2026, 9, 1, tzinfo=UTC)
    day = adapter.get_bars("EURUSD", Timeframe.H1, start=start, end=start + timedelta(hours=23))
    assert day[0].time == int(start.timestamp()) and len(day) == 24

    ticks = adapter.get_ticks("EURUSD", datetime.fromtimestamp(time.time() - 2, UTC), 50)
    assert 0 < len(ticks) <= 50 and all(t.bid > 0 for t in ticks)

    names = {s.name: s for s in adapter.list_symbols()}
    assert {"EURUSD", "GBPUSD"} <= set(names) and names["EURUSD"].digits == 5
    assert adapter.get_account().currency == "EUR"
    assert adapter.get_tick("NOPE") is None


def test_without_processes_the_adapter_still_reads_the_terminal_itself(world) -> None:
    """CT_MT5_ISOLATE=false (for debugging): the same answers, from this very process."""
    from app.broker.mt5_adapter import MT5Adapter

    os.environ.update(world.env)
    sys.path.insert(0, str(FAKE))
    try:
        plain = MT5Adapter(Settings(_env_file=None))
        plain.connect()
        bars = plain.get_bars("EURUSD", Timeframe.M1, count=20)
        assert len(bars) == 20 and bars[-1].time % 60 == 0
        assert plain.bar_rows("EURUSD", Timeframe.M1, count=3)[-1][0] == bars[-1].time
        assert plain.get_account().currency == "EUR"
        assert plain.get_tick("EURUSD") is not None
        plain.disconnect()
    finally:
        sys.path.remove(str(FAKE))
        sys.modules.pop("MetaTrader5", None)
        for key in world.env:
            os.environ.pop(key, None)


def test_the_reader_tells_what_the_terminal_says_about_itself(world, adapter) -> None:
    info = adapter.get_terminal()
    assert info.connected and info.company == "Fake Broker Ltd" and info.name == "Fake MetaTrader 5"
    assert info.algo_trading and info.api_allowed and info.account_trading and info.account_expert
    assert info.account_login == 1 and info.account_server == "Fake-Demo"
    world.edit(algo_trading=False)
    assert not adapter.get_terminal().algo_trading  # Algo Trading switched off in the terminal


def test_a_refused_order_says_what_to_switch_on(world, adapter) -> None:
    world.edit(order_retcode=10027)  # AutoTrading disabled by client
    result = adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1))
    assert not result.ok and result.retcode == 10027
    assert "Algo Trading" in (result.error or "") and "green" in (result.error or "")
    world.edit(order_retcode=10026)
    assert "broker" in (adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1)).error or "")
    world.edit(order_retcode=0)
    assert adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1)).ok


def test_a_read_that_fails_says_so(adapter) -> None:
    with pytest.raises(BrokerError, match="copy_rates failed for NOPE"):
        adapter.get_bars("NOPE", Timeframe.H1, count=10)


def test_requests_for_the_same_thing_share_one_trip_to_the_terminal(world) -> None:
    """The terminal needs half a second per bar read; six screens asking at once get one answer."""
    adapter = make_adapter(world, FAKE_MT5_BARS_DELAY="0.5")
    adapter.connect()
    try:
        answers: list = []
        threads = [
            threading.Thread(target=lambda: answers.append(adapter.get_bars("EURUSD", Timeframe.H1, count=5)))
            for _ in range(6)
        ]
        began = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        took = time.monotonic() - began
        assert len(answers) == 6 and all(a == answers[0] for a in answers)
        assert took < 1.4  # one trip (0.5 s), not six in a row (3 s)
    finally:
        adapter.disconnect()


def test_a_slow_read_does_not_hold_an_order_up(world) -> None:
    adapter = make_adapter(world, FAKE_MT5_BARS_DELAY="1.5")
    adapter.connect()
    try:
        adapter.get_tick("EURUSD")  # (a quick read) so the trading process has certainly started too
        threading.Thread(target=lambda: adapter.get_bars("EURUSD", Timeframe.H1, count=5), daemon=True).start()
        time.sleep(0.2)  # the reader is now stuck in the terminal for 1.3 s more
        began = time.monotonic()
        result = adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1))
        assert result.ok
        assert time.monotonic() - began < 0.8
    finally:
        adapter.disconnect()


def test_a_dead_reader_is_replaced_on_the_next_read(adapter) -> None:
    assert adapter.get_account().currency == "EUR"
    adapter._reader._proc.kill()
    adapter._reader._proc.wait()
    time.sleep(0.2)
    assert adapter.get_account().currency == "EUR"


def test_connect_fails_loudly_when_the_reader_cannot_reach_the_terminal(world) -> None:
    dead = TradeProcess(
        Settings(_env_file=None),
        command=[sys.executable, "-c", "print('{\"type\":\"fatal\",\"error\":\"no terminal\"}', flush=True)"],
        role="reader",
    )
    adapter = IsolatedMT5Adapter(Settings(_env_file=None), trader=make_trader(world), reader=dead)
    with pytest.raises(BrokerError, match="no terminal"):
        adapter.connect()  # so that CT_BROKER=auto can fall back to the mock
    assert not adapter.connected
    with pytest.raises(BrokerError, match="not connected"):
        adapter.get_account()
