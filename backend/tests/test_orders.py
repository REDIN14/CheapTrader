"""Pending (limit / stop) orders: the rules, the mock broker's market, the REST API, the live feed, and
MetaTrader itself (against the stand-in terminal in tests/fake_mt5)."""

from __future__ import annotations

import os
import time

os.environ["CT_BROKER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.broker.mock_adapter import MockAdapter  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import ModifyOrderRequest, OrderRequest, OrderType, PendingOrder  # noqa: E402
from app.trading import is_pending, levels_problem, name_of, price_problem, side_of  # noqa: E402
from tests.test_mt5_processes import adapter, drain, feed, wait_for, world  # noqa: E402,F401

BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP = OrderType.BUY_LIMIT, OrderType.SELL_LIMIT, OrderType.BUY_STOP, OrderType.SELL_STOP


# -- the rules ----------------------------------------------------------------------------------------
def test_the_kinds_of_order_in_words() -> None:
    assert [is_pending(t) for t in (OrderType.BUY, OrderType.SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, None)] == [
        False, False, True, True, True, True, False,
    ]
    assert [side_of(t) for t in (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP)] == ["BUY", "SELL", "BUY", "SELL"]
    assert name_of(SELL_STOP) == "sell stop" and name_of(OrderType.BUY) == "buy"


@pytest.mark.parametrize(
    "kind,price,fine",
    [
        (BUY_LIMIT, 1.0990, True), (BUY_LIMIT, 1.1002, False), (BUY_LIMIT, 1.1010, False),  # below the ask (1.1002)
        (SELL_LIMIT, 1.1010, True), (SELL_LIMIT, 1.1000, False), (SELL_LIMIT, 1.0990, False),  # above the bid (1.1000)
        (BUY_STOP, 1.1010, True), (BUY_STOP, 1.1002, False), (BUY_STOP, 1.0990, False),  # above the ask
        (SELL_STOP, 1.0990, True), (SELL_STOP, 1.1000, False), (SELL_STOP, 1.1010, False),  # below the bid
    ],
)
def test_which_side_of_the_market_a_pending_order_may_wait_on(kind, price, fine) -> None:
    problem = price_problem(kind, price, bid=1.1000, ask=1.1002, digits=4)
    assert (problem is None) is fine, problem
    if not fine:
        assert name_of(kind) in problem and f"{price:.4f}" in problem


def test_the_broker_keeps_a_minimum_distance_from_the_market() -> None:
    assert price_problem(BUY_LIMIT, 1.0999, 1.1000, 1.1002, min_distance=0.0010, digits=4) is not None
    assert "at least 0.0010 away" in price_problem(BUY_LIMIT, 1.0999, 1.1000, 1.1002, min_distance=0.0010, digits=4)
    assert price_problem(BUY_LIMIT, 1.0990, 1.1000, 1.1002, min_distance=0.0010, digits=4) is None


def test_a_stop_and_a_target_belong_on_their_own_sides_of_the_entry() -> None:
    assert levels_problem("BUY", 1.1, sl=1.09, tp=1.12) is None
    assert "stop loss of a buy" in levels_problem("BUY", 1.1, sl=1.11, tp=None, digits=2)
    assert "take profit of a buy" in levels_problem("BUY", 1.1, sl=None, tp=1.09, digits=2)
    assert levels_problem("SELL", 1.1, sl=1.11, tp=1.09) is None
    assert "stop loss of a sell" in levels_problem("SELL", 1.1, sl=1.09, tp=None, digits=2)
    assert "take profit of a sell" in levels_problem("SELL", 1.1, sl=None, tp=1.11, digits=2)
    assert levels_problem("BUY", 1.1, sl=None, tp=None) is None and levels_problem("BUY", 1.1, sl=0, tp=0) is None


# -- the mock broker's market -------------------------------------------------------------------------
def mock() -> MockAdapter:
    adapter = MockAdapter(tick_rate=300)
    adapter.connect()
    return adapter


def jump(adapter: MockAdapter, delta: float, symbol: str = "EURUSD") -> None:
    """The market moves by ``delta`` in one go; the next ticks are the ones waiting orders see."""
    with adapter._lock:
        adapter._market(symbol)._mid += delta
    time.sleep(0.06)
    adapter.get_account()


def pending(adapter: MockAdapter, kind: OrderType, away: float, **kw) -> tuple[OrderRequest, float]:
    """A pending order ``away`` from the market (positive: above it)."""
    tick = adapter.get_tick("EURUSD")
    assert tick is not None
    price = round((tick.ask if side_of(kind) == "BUY" else tick.bid) + away, 5)
    return OrderRequest(symbol="EURUSD", side=side_of(kind), order_type=kind, price=price, volume=0.1, **kw), price  # type: ignore[arg-type]


def test_a_buy_limit_waits_below_the_market_and_fills_when_it_comes_down() -> None:
    a = mock()
    request, price = pending(a, BUY_LIMIT, -0.0020)
    request = request.model_copy(update={"sl": round(price - 0.002, 5), "tp": round(price + 0.004, 5)})
    result = a.place_order(request)
    assert result.ok and result.price == price and result.order_id
    (order,) = a.get_orders()
    assert isinstance(order, PendingOrder) and order.order_type is BUY_LIMIT and order.side == "BUY"
    assert order.price == price and order.volume == 0.1 and order.sl == request.sl and order.tp == request.tp
    assert a.get_positions() == []  # nothing has been traded yet

    jump(a, -0.0025)
    assert a.get_orders() == []
    (position,) = a.get_positions()
    assert position.ticket == result.order_id  # the order's number lives on in the position, as on MetaTrader
    assert position.side == "BUY" and position.price_open == price and position.sl == request.sl and position.tp == request.tp


def test_the_other_three_kinds_fill_the_way_a_broker_fills_them() -> None:
    for kind, away, moves, at_price in (
        (SELL_LIMIT, +0.0020, +0.0025, True),
        (BUY_STOP, +0.0020, +0.0025, False),
        (SELL_STOP, -0.0020, -0.0025, False),
    ):
        a = mock()
        request, price = pending(a, kind, away)
        result = a.place_order(request)
        assert result.ok, (kind, result.error)
        assert len(a.get_orders()) == 1
        jump(a, moves * 0.5)  # not there yet
        assert len(a.get_orders()) == 1 and a.get_positions() == []
        jump(a, moves)
        assert a.get_orders() == [], kind
        (position,) = a.get_positions()
        assert position.side == side_of(kind)
        if at_price:  # a limit order fills at the price asked for ...
            assert position.price_open == price
        else:  # ... a stop order at whatever the market is when it gets there
            assert (position.price_open >= price) if side_of(kind) == "BUY" else (position.price_open <= price)


def test_a_pending_order_on_the_wrong_side_of_the_market_is_refused_and_says_why() -> None:
    a = mock()
    for kind, away in ((BUY_LIMIT, +0.0020), (SELL_LIMIT, -0.0020), (BUY_STOP, -0.0020), (SELL_STOP, +0.0020)):
        request, _ = pending(a, kind, away)
        result = a.place_order(request)
        assert not result.ok and result.retcode == 10015 and name_of(kind) in (result.error or ""), (kind, result.error)
    assert a.get_orders() == []


def test_a_stop_loss_on_the_wrong_side_of_a_pending_order_is_refused() -> None:
    a = mock()
    request, price = pending(a, BUY_LIMIT, -0.0020)
    bad = a.place_order(request.model_copy(update={"sl": round(price + 0.001, 5)}))
    assert not bad.ok and "stop loss of a buy" in (bad.error or "")
    bad = a.place_order(request.model_copy(update={"tp": round(price - 0.001, 5)}))
    assert not bad.ok and "take profit of a buy" in (bad.error or "")
    assert a.get_orders() == []


def test_a_pending_order_needs_a_price() -> None:
    a = mock()
    request, _ = pending(a, BUY_LIMIT, -0.0020)
    result = a.place_order(request.model_copy(update={"price": None}))
    assert not result.ok and "price" in (result.error or "")


def test_a_pending_order_can_be_taken_back_once() -> None:
    a = mock()
    request, _ = pending(a, BUY_LIMIT, -0.0020)
    ticket = a.place_order(request).order_id
    assert a.cancel_order(ticket).ok
    assert a.get_orders() == []
    again = a.cancel_order(ticket)
    assert not again.ok and "not found" in (again.error or "")


def test_an_order_that_has_just_been_filled_cannot_be_cancelled() -> None:
    a = mock()
    request, _ = pending(a, BUY_LIMIT, -0.0020)
    ticket = a.place_order(request).order_id
    jump(a, -0.0030)
    result = a.cancel_order(ticket)
    assert not result.ok and "filled" in (result.error or "")
    assert len(a.get_positions()) == 1


def test_a_pending_order_can_be_moved_and_its_levels_changed() -> None:
    a = mock()
    request, price = pending(a, BUY_LIMIT, -0.0020, sl=None, tp=None)
    ticket = a.place_order(request).order_id
    lower = round(price - 0.001, 5)
    assert a.modify_order(ModifyOrderRequest(ticket=ticket, price=lower)).ok
    (order,) = a.get_orders()
    assert order.price == lower and order.sl == 0.0
    assert a.modify_order(ModifyOrderRequest(ticket=ticket, sl=round(lower - 0.002, 5), tp=round(lower + 0.004, 5))).ok
    (order,) = a.get_orders()
    assert order.price == lower and order.sl == round(lower - 0.002, 5)  # the price stayed
    assert a.modify_order(ModifyOrderRequest(ticket=ticket, sl=0)).ok
    assert a.get_orders()[0].sl == 0.0 and a.get_orders()[0].tp == round(lower + 0.004, 5)  # 0 removes it, others stay


def test_moving_an_order_to_the_wrong_side_of_the_market_is_refused() -> None:
    a = mock()
    request, price = pending(a, BUY_LIMIT, -0.0020)
    ticket = a.place_order(request).order_id
    above = a.get_tick("EURUSD").ask + 0.001
    result = a.modify_order(ModifyOrderRequest(ticket=ticket, price=above))
    assert not result.ok and "buy limit" in (result.error or "")
    assert a.get_orders()[0].price == price
    assert not a.modify_order(ModifyOrderRequest(ticket=999999, price=1.0)).ok


def test_orders_can_be_listed_by_symbol() -> None:
    a = mock()
    request, _ = pending(a, BUY_LIMIT, -0.0020)
    a.place_order(request)
    other = a.get_tick("GBPUSD")
    a.place_order(
        OrderRequest(symbol="GBPUSD", side="SELL", order_type=SELL_LIMIT, price=round(other.bid + 0.003, 5), volume=0.1)
    )
    assert {o.symbol for o in a.get_orders()} == {"EURUSD", "GBPUSD"}
    assert [o.symbol for o in a.get_orders("GBPUSD")] == ["GBPUSD"]


def test_the_mock_says_what_a_lot_of_each_instrument_is_worth() -> None:
    a = mock()
    eur = a.get_symbol("EURUSD")
    assert eur is not None and eur.trade_tick_size == 0.00001 and eur.volume_min == 0.01 and eur.volume_step == 0.01
    assert eur.trade_tick_value == pytest.approx(1.0)  # one price step of one lot: 100,000 x 0.00001
    gold = a.get_symbol("XAUUSD")
    assert gold is not None and gold.trade_tick_value == pytest.approx(1.0)  # 100 x 0.01
    assert a.get_symbol("NOPE") is None


# -- REST -------------------------------------------------------------------------------------------------
def price_now(client: TestClient, side: str, away: float) -> float:
    tick = client.get("/api/tick", params={"symbol": "EURUSD"}).json()
    return round((tick["ask"] if side == "BUY" else tick["bid"]) + away, 5)


def test_a_limit_order_is_placed_listed_moved_and_cancelled_over_rest() -> None:
    with TestClient(app) as client:
        price = price_now(client, "BUY", -0.003)
        placed = client.post(
            "/api/orders",
            json={"symbol": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT", "price": price, "volume": 0.2,
                  "sl": round(price - 0.002, 5), "tp": round(price + 0.004, 5)},
        ).json()
        assert placed["ok"], placed
        ticket = placed["order_id"]

        (order,) = client.get("/api/orders").json()
        assert order["ticket"] == ticket and order["order_type"] == "BUY_LIMIT" and order["price"] == price
        assert client.get("/api/orders", params={"symbol": "GBPUSD"}).json() == []
        assert client.get("/api/positions").json() == []  # nothing is open

        moved = client.patch("/api/orders", json={"ticket": ticket, "price": round(price - 0.001, 5)}).json()
        assert moved["ok"], moved
        assert client.get("/api/orders").json()[0]["price"] == round(price - 0.001, 5)

        gone = client.delete(f"/api/orders/{ticket}").json()
        assert gone["ok"]
        assert client.get("/api/orders").json() == []
        assert not client.delete(f"/api/orders/{ticket}").json()["ok"]


def test_the_rest_api_refuses_a_malformed_pending_order_in_words() -> None:
    with TestClient(app) as client:
        no_price = client.post(
            "/api/orders", json={"symbol": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT", "volume": 0.1}
        ).json()
        assert not no_price["ok"] and "needs the price" in no_price["error"]

        crossed = client.post(
            "/api/orders", json={"symbol": "EURUSD", "side": "SELL", "order_type": "BUY_LIMIT", "price": 1.0, "volume": 0.1}
        ).json()
        assert not crossed["ok"] and "buy" in crossed["error"]

        wrong_side = client.post(
            "/api/orders",
            json={"symbol": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT", "price": price_now(client, "BUY", +0.01), "volume": 0.1},
        ).json()
        assert not wrong_side["ok"] and "buy limit has to be below" in wrong_side["error"]
        assert client.get("/api/orders").json() == []


def test_a_replay_has_no_pending_orders() -> None:
    class Engine:
        paper = object()  # (never reached: the refusal comes first)

    with TestClient(app) as client:
        from app.state import get_state

        get_state().replay = Engine()  # type: ignore[assignment]
        result = client.post(
            "/api/replay/orders",
            json={"symbol": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT", "price": 1.0, "volume": 0.1},
        ).json()
        assert not result["ok"] and "replay" in result["error"]


def test_one_symbol_can_be_read_with_its_trading_specification() -> None:
    with TestClient(app) as client:
        eur = client.get("/api/symbols/EURUSD").json()
        assert eur["name"] == "EURUSD" and eur["trade_tick_value"] > 0 and eur["volume_step"] == 0.01
        assert client.get("/api/symbols/NOPE").status_code == 404
        listed = {s["name"]: s for s in client.get("/api/symbols").json()}
        assert listed["EURUSD"]["trade_tick_size"] == eur["trade_tick_size"]


def test_the_live_stream_tells_screens_about_orders_that_wait_and_when_they_fill() -> None:
    def receive_until(ws, predicate, limit: float = 8.0) -> list[dict]:
        seen: list[dict] = []
        end = time.monotonic() + limit
        while time.monotonic() < end:
            seen.append(ws.receive_json())
            if predicate(seen):
                return seen
        raise AssertionError(f"gave up waiting; saw {[m['type'] for m in seen][-8:]}")

    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        receive_until(ws, lambda m: any(x["type"] == "state" for x in m))
        price = price_now(client, "BUY", -0.003)
        placed = client.post(
            "/api/orders", json={"symbol": "EURUSD", "side": "BUY", "order_type": "BUY_LIMIT", "price": price, "volume": 0.1}
        ).json()
        assert placed["ok"]
        seen = receive_until(ws, lambda m: any(x["type"] == "state" and x.get("orders") for x in m))
        state = next(x for x in seen if x["type"] == "state" and x.get("orders"))
        assert state["orders"][0]["ticket"] == placed["order_id"] and state["orders"][0]["order_type"] == "BUY_LIMIT"
        assert state["positions"] == []

        client.delete(f"/api/orders/{placed['order_id']}")
        receive_until(ws, lambda m: any(x["type"] == "state" and x.get("orders") == [] for x in m))


# -- MetaTrader (the stand-in terminal) ---------------------------------------------------------------------
def pend(kind: OrderType, price: float, **kw) -> OrderRequest:
    return OrderRequest(symbol="EURUSD", side=side_of(kind), order_type=kind, price=price, volume=0.1, **kw)  # type: ignore[arg-type]


def test_a_limit_order_goes_to_the_terminal_as_a_pending_order_not_a_trade(world, adapter) -> None:
    result = adapter.place_order(pend(BUY_LIMIT, 1.0500, sl=1.0400, tp=1.0700))
    assert result.ok and result.retcode == 10009
    sent = world.read()["orders"][-1]
    assert sent["action"] == 5 and sent["type"] == 2 and sent["price"] == 1.05  # TRADE_ACTION_PENDING, ORDER_TYPE_BUY_LIMIT
    assert sent["type_filling"] == 2 and sent["type_time"] == 0  # "return" fill, good till cancelled
    assert world.read()["positions"] == []
    (order,) = adapter.get_orders()
    assert order.ticket == result.order_id and order.order_type is BUY_LIMIT and order.side == "BUY"
    assert order.price == 1.05 and order.sl == 1.04 and order.tp == 1.07 and order.volume == 0.1
    assert adapter.get_positions() == []


def test_every_kind_of_pending_order_is_understood(world, adapter) -> None:
    for kind, price in ((BUY_LIMIT, 1.0500), (SELL_LIMIT, 1.9000), (BUY_STOP, 1.9100), (SELL_STOP, 1.0400)):
        assert adapter.place_order(pend(kind, price)).ok, kind
    got = {o.order_type: o for o in adapter.get_orders()}
    assert set(got) == {BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP}
    assert got[SELL_STOP].side == "SELL" and got[BUY_STOP].side == "BUY"
    assert [o.symbol for o in adapter.get_orders("GBPUSD")] == []


def test_the_terminal_is_not_bothered_with_an_order_it_would_refuse(world, adapter) -> None:
    wrong = adapter.place_order(pend(BUY_LIMIT, 1.9000))  # a buy limit far above the market
    assert not wrong.ok and "buy limit has to be below" in (wrong.error or "")
    assert world.read()["orders"] == []  # nothing was sent
    bad_stop = adapter.place_order(pend(BUY_LIMIT, 1.0500, sl=1.0600))
    assert not bad_stop.ok and "stop loss of a buy" in (bad_stop.error or "")
    assert not adapter.place_order(OrderRequest(symbol="EURUSD", side="BUY", order_type=BUY_LIMIT, volume=0.1)).ok


def test_the_brokers_minimum_distance_is_kept(world, adapter) -> None:
    world.edit(stops_level=500)  # 500 points = 0.005
    tick = adapter.get_tick("EURUSD")
    near = adapter.place_order(pend(BUY_LIMIT, round(tick.ask - 0.002, 5)))
    assert not near.ok and "at least" in (near.error or "")
    assert adapter.place_order(pend(BUY_LIMIT, round(tick.ask - 0.02, 5))).ok


def test_a_fill_policy_the_instrument_refuses_is_swapped_for_one_it_takes(world, adapter) -> None:
    world.edit(reject_fillings=[2])  # "return" is refused with 10030
    result = adapter.place_order(pend(BUY_LIMIT, 1.0500))
    assert result.ok
    assert len(adapter.get_orders()) == 1
    assert world.read()["orders"][-1]["type_filling"] in (0, 1)
    world.edit(reject_fillings=[0, 1, 2])
    refused = adapter.place_order(pend(SELL_STOP, 1.0400))
    assert not refused.ok and refused.retcode == 10030


def test_a_pending_order_is_cancelled_in_the_terminal(world, adapter) -> None:
    ticket = adapter.place_order(pend(BUY_LIMIT, 1.0500)).order_id
    assert adapter.cancel_order(ticket).ok
    assert adapter.get_orders() == [] and world.read()["pending"] == []
    gone = adapter.cancel_order(ticket)
    assert not gone.ok and "not found" in (gone.error or "")


def test_moving_a_pending_order_keeps_what_was_not_mentioned(world, adapter) -> None:
    ticket = adapter.place_order(pend(BUY_LIMIT, 1.0500, sl=1.0400, tp=1.0700)).order_id
    assert adapter.modify_order(ModifyOrderRequest(ticket=ticket, price=1.0450)).ok
    (order,) = adapter.get_orders()
    assert order.price == 1.045 and order.sl == 1.04 and order.tp == 1.07  # not mentioned, not removed
    assert adapter.modify_order(ModifyOrderRequest(ticket=ticket, sl=1.03)).ok
    (order,) = adapter.get_orders()
    assert order.price == 1.045 and order.sl == 1.03 and order.tp == 1.07
    assert adapter.modify_order(ModifyOrderRequest(ticket=ticket, tp=0)).ok
    assert adapter.get_orders()[0].tp == 0.0
    # nothing to change is not a failure
    assert adapter.modify_order(ModifyOrderRequest(ticket=ticket, price=1.045)).ok
    wrong = adapter.modify_order(ModifyOrderRequest(ticket=ticket, price=1.9))
    assert not wrong.ok and "buy limit" in (wrong.error or "")
    assert not adapter.modify_order(ModifyOrderRequest(ticket=424242, price=1.04)).ok


def test_the_reader_tells_what_a_lot_of_the_instrument_is_worth(world, adapter) -> None:
    world.edit(tick_value=0.85, tick_value_loss=0.9, stops_level=20)
    spec = adapter.get_symbol("EURUSD")
    assert spec is not None
    assert spec.trade_tick_value == pytest.approx(0.9)  # what a losing tick costs is what sizing needs
    assert spec.trade_tick_size == pytest.approx(0.00001) and spec.volume_min == 0.01 and spec.volume_step == 0.01
    assert spec.trade_stops_level == 20 and spec.currency_profit == "USD"
    assert adapter.get_symbol("NOPE") is None
    listed = {s.name: s for s in adapter.list_symbols()}
    assert listed["EURUSD"].trade_tick_value == pytest.approx(0.9) and listed["EURUSD"].volume_max == 100.0


def test_a_failed_read_of_the_orders_is_not_mistaken_for_no_orders(world, adapter) -> None:
    from app.broker.base import BrokerError

    adapter.place_order(pend(BUY_LIMIT, 1.0500))
    world.edit(orders_fail=True)
    assert adapter.get_orders() == []  # (a plain read says "none")
    with pytest.raises(BrokerError, match="orders_get"):
        adapter.get_orders(strict=True)  # the live feed asks this way, so it can tell the difference


def test_the_feed_reports_the_pending_orders_with_the_positions(world, feed, adapter) -> None:
    feed, events = feed
    wait_for(events, lambda e: e.get("type") == "state")
    result = adapter.place_order(pend(BUY_LIMIT, 1.0500))
    feed.kick()
    state = wait_for(events, lambda e: e.get("type") == "state" and e.get("orders"), timeout=3.0)
    assert state["orders"][0]["ticket"] == result.order_id and state["orders"][0]["order_type"] == "BUY_LIMIT"
    assert state["positions"] == []
    adapter.cancel_order(result.order_id)
    feed.kick()
    wait_for(events, lambda e: e.get("type") == "state" and e.get("orders") == [], timeout=3.0)


def test_a_failing_order_read_leaves_the_last_known_state_standing(world, feed) -> None:
    feed, events = feed
    wait_for(events, lambda e: e.get("type") == "state")
    world.edit(orders_fail=True)
    got = drain(events, 1.5)
    assert any(e.get("type") == "error" and e.get("where") == "state" for e in got)  # said so ...
    assert not [e for e in got if e.get("type") == "state"]  # ... and did not announce "nothing waits"
