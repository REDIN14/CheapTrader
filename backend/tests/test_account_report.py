"""The account's performance report: the broker's history read through the reader process (against the stand-in
terminal in tests/fake_mt5), what the mock broker keeps of its own, and the route that serves the report."""

from __future__ import annotations

import os
import time

os.environ["CT_BROKER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.broker.base import BrokerError  # noqa: E402
from app.broker.mock_adapter import MockAdapter  # noqa: E402
from app.broker.mt5_adapter import deal_from_mt5  # noqa: E402
from app.main import app  # noqa: E402
from app.performance import account_report  # noqa: E402
from app.schemas import OrderRequest  # noqa: E402
from tests.test_mt5_processes import adapter, world  # noqa: E402,F401


# -- MetaTrader's history ------------------------------------------------------------------------------
def deal(
    ticket: int,
    when: int,
    kind: int,
    entry: int = 0,
    position: int = 0,
    volume: float = 0.0,
    price: float = 0.0,
    **more,
) -> dict:
    """A line of the terminal's history, with the fields MetaTrader's ``TradeDeal`` has."""
    return {
        "ticket": ticket, "order": ticket, "time": when, "time_msc": when * 1000, "type": kind, "entry": entry, "magic": 0,
        "position_id": position, "reason": 0, "volume": volume, "price": price, "commission": 0.0, "swap": 0.0, "profit": 0.0,
        "fee": 0.0, "symbol": "EURUSD" if volume else "", "comment": "", "external_id": "", **more,
    }  # fmt: skip


T0 = 1_700_000_000  # a day in November 2023: the terminal is asked for everything since 2000
HISTORY = [
    deal(1, T0 + 1_000, 2, profit=100.0, comment="deposit"),
    deal(2, T0 + 2_000, 0, 0, 11, 0.10, 1.1000, commission=-0.5, comment="cheaptrader"),
    deal(
        3,
        T0 + 2_600,
        1,
        1,
        11,
        0.10,
        1.1050,
        commission=-0.5,
        profit=5.0,
        reason=5,
        comment="[tp 1.1050]",
    ),
    deal(4, T0 + 3_000, 1, 0, 12, 0.20, 1.1050, commission=-1.0),
    deal(
        5,
        T0 + 3_300,
        0,
        1,
        12,
        0.20,
        1.1070,
        commission=-1.0,
        profit=-4.0,
        reason=4,
        comment="[sl 1.1070]",
        swap=-0.1,
    ),
    deal(6, T0 + 3_400, 4, profit=-0.4, comment="fee"),
]


def test_the_terminals_history_is_read_through_the_reader_process(world, adapter) -> None:
    world.edit(deals=list(reversed(HISTORY)), account={"balance": 97.5, "equity": 97.5})
    deals = adapter.get_deals()
    assert [d.ticket for d in deals] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]  # oldest first, whatever order the terminal gave them
    assert [d.kind for d in deals] == ["balance", "buy", "sell", "sell", "buy", "charge"]
    assert [d.entry for d in deals] == ["", "in", "out", "in", "out", ""]
    assert [d.reason for d in deals] == ["client", "client", "tp", "client", "sl", "client"]
    assert (
        deals[2].commission == -0.5
        and deals[2].profit == 5.0
        and deals[4].swap == -0.1
        and deals[1].comment == "cheaptrader"
    )


def test_what_the_report_makes_of_it() -> None:
    from app.schemas import AccountInfo

    deals = [
        deal_from_mt5(type("D", (), d)) for d in HISTORY
    ]  # (what the reader process hands over, built here without it)
    report = account_report(
        deals, AccountInfo(balance=97.5, equity=97.5, profit=0.0, currency="EUR"), now=T0 + 4_000
    )
    assert report.flows.deposits == 100.0 and report.flows.charges == -0.4 and report.deals == 6
    first, second = report.trades
    assert (first.symbol, first.side, first.reason, first.pnl) == ("EURUSD", "BUY", "tp", 4.0)
    assert (second.side, second.reason, second.swap, second.pnl) == (
        "SELL",
        "sl",
        -0.1,
        pytest.approx(-6.1),
    )
    assert report.summary.net_profit == pytest.approx(
        -2.1
    ) and report.initial_balance == pytest.approx(100.0)
    assert report.equity[0].value == 100.0 and report.equity[-1].value == pytest.approx(
        97.5
    )  # the account's level, charges included
    assert report.return_pct == pytest.approx(-2.1)


def test_the_other_figures_of_the_account_come_through(world, adapter) -> None:
    world.edit(
        account={
            "company": "Acme Markets",
            "credit": 25.0,
            "margin_level": 345.6,
            "trade_mode": 2,
            "margin_mode": 0,
            "limit_orders": 500,
            "margin_so_mode": 1,
        }
    )
    a = adapter.get_account()
    assert (a.company, a.credit, a.margin_level, a.trade_mode, a.margin_mode, a.limit_orders) == (
        "Acme Markets",
        25.0,
        345.6,
        "real",
        "netting",
        500,
    )
    assert (a.stop_out_mode, a.margin_call_level, a.stop_out_level) == ("money", 70.0, 20.0)
    assert (a.leverage, a.currency) == (500, "EUR")


def test_a_terminal_that_cannot_give_its_history_says_so(world, adapter) -> None:
    world.edit(deals_fail=True)
    with pytest.raises(BrokerError, match="history_deals_get"):
        adapter.get_deals()


def test_an_account_without_history_has_an_empty_report(world, adapter) -> None:
    assert adapter.get_deals() == []
    report = account_report([], adapter.get_account())
    assert report.trades == [] and report.summary.trades == 0 and report.equity == []


# -- the mock broker's own history --------------------------------------------------------------------------
def mock() -> MockAdapter:
    adapter = MockAdapter(tick_rate=300)
    adapter.connect()
    return adapter


def test_the_mock_account_begins_with_its_deposit() -> None:
    (opening,) = mock().get_deals()
    assert (opening.kind, opening.profit) == ("balance", 10_000.0)


def test_the_mock_broker_notes_every_fill() -> None:
    a = mock()
    opened = a.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.2))
    assert opened.ok
    assert a.close_position(opened.order_id).ok
    _, entry, exit_ = a.get_deals()
    assert (entry.kind, entry.entry, entry.position_id, entry.volume, entry.symbol) == (
        "buy",
        "in",
        opened.order_id,
        0.2,
        "EURUSD",
    )
    assert (exit_.kind, exit_.entry, exit_.position_id, exit_.reason) == (
        "sell",
        "out",
        opened.order_id,
        "client",
    )
    assert exit_.price > 0 and exit_.time >= entry.time
    report = account_report(a.get_deals(), a.get_account())
    (trade,) = report.trades
    assert trade.ticket == opened.order_id and trade.pnl == pytest.approx(exit_.profit)
    assert report.initial_balance == 10_000.0 and report.summary.net_profit == pytest.approx(
        a.get_account().balance - 10_000.0
    )


def test_a_stop_that_is_hit_is_a_stop_in_the_history() -> None:
    a = mock()
    tick = a.get_tick("EURUSD")
    assert tick is not None
    placed = a.place_order(
        OrderRequest(
            symbol="EURUSD",
            side="BUY",
            volume=0.1,
            sl=round(tick.bid - 0.0010, 5),
            tp=round(tick.bid + 0.0100, 5),
        )
    )
    assert placed.ok
    with a._lock:
        a._market("EURUSD")._mid -= 0.0030  # the market falls through the stop
    time.sleep(0.06)
    a.get_account()
    assert a.get_positions() == []
    assert a.get_deals()[-1].reason == "sl" and a.get_deals()[-1].profit < 0


def test_a_pending_order_that_fills_is_a_fill_in_the_history() -> None:
    a = mock()
    tick = a.get_tick("EURUSD")
    assert tick is not None
    placed = a.place_order(
        OrderRequest(
            symbol="EURUSD",
            side="BUY",
            order_type="BUY_LIMIT",
            price=round(tick.ask - 0.0020, 5),
            volume=0.1,
        )
    )  # type: ignore[arg-type]
    assert placed.ok and len(a.get_deals()) == 1  # it waits: nothing has been traded yet
    with a._lock:
        a._market("EURUSD")._mid -= 0.0040
    time.sleep(0.06)
    a.get_account()
    assert [d.kind for d in a.get_deals()] == ["balance", "buy"] and a.get_deals()[
        -1
    ].position_id == placed.order_id


# -- the route --------------------------------------------------------------------------------------------------------
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def trade_once(client: TestClient) -> int:
    placed = client.post(
        "/api/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1}
    ).json()
    assert placed["ok"], placed
    closed = client.delete(f"/api/positions/{placed['order_id']}").json()
    assert closed["ok"], closed
    return placed["order_id"]


def test_the_route_serves_the_report_of_the_account(client) -> None:
    ticket = trade_once(client)
    r = client.get("/api/account/report").json()
    assert r["account"]["server"] == "Mock-Demo" and r["account"]["trade_mode"] == "demo"
    assert r["flows"]["deposits"] == 10_000.0 and r["initial_balance"] == 10_000.0
    assert r["trades_total"] == 1 and [t["ticket"] for t in r["trades"]] == [ticket]
    assert (
        r["trades"][0]["symbol"] == "EURUSD" and r["trades"][0]["reason"] == "manual"
    )  # a close made from the program
    assert r["summary"]["trades"] == 1 and r["symbols"][0]["symbol"] == "EURUSD"
    assert r["deals"] == 3 and r["equity"][0]["value"] == 10_000.0
    assert r["summary"]["net_profit"] == pytest.approx(r["account"]["balance"] - 10_000.0, abs=0.01)


def test_the_route_lists_as_many_trades_as_asked_for_and_says_how_many_there_are(client) -> None:
    for _ in range(3):
        trade_once(client)
    r = client.get("/api/account/report", params={"trades": 2}).json()
    assert len(r["trades"]) == 2 and r["trades_total"] == 3 and r["summary"]["trades"] == 3
    assert client.get("/api/account/report", params={"trades": 0}).json()["trades"] == []
    assert client.get("/api/account/report", params={"points": 2}).status_code == 422


def test_the_route_ends_the_curve_where_it_is_told_to(client) -> None:
    trade_once(client)
    now = int(time.time()) + 100_000
    r = client.get("/api/account/report", params={"now": now}).json()
    assert r["equity"][-1]["time"] == now


def test_a_broker_that_cannot_give_its_history_is_a_bad_gateway(client, monkeypatch) -> None:
    from app.state import get_state

    adapter = get_state().broker.adapter

    def broken():
        raise BrokerError("MetaTrader did not answer within 30 s.")

    monkeypatch.setattr(adapter, "get_deals", broken)
    reply = client.get("/api/account/report")
    assert reply.status_code == 502 and "did not answer" in reply.json()["detail"]


def test_the_route_reports_a_period(client) -> None:
    trade_once(client)
    whole = client.get("/api/account/report").json()
    later = client.get("/api/account/report", params={"since": int(time.time()) + 100_000}).json()
    assert whole["summary"]["trades"] == 1 and whole["trades_total"] == 1
    assert later["summary"]["trades"] == 0 and later["trades"] == [] and later["trades_total"] == 0
    assert later["deals"] == whole["deals"]  # the history itself is all of it
    assert client.get("/api/account/report", params={"since": -5}).status_code == 422
