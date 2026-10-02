"""Tests for the mock broker adapter."""

from __future__ import annotations

from app.broker.mock_adapter import MockAdapter
from app.schemas import ModifyRequest, OrderRequest, Timeframe


def test_symbols_and_bars() -> None:
    broker = MockAdapter()
    broker.connect()
    symbols = broker.list_symbols()
    assert any(s.name == "EURUSD" for s in symbols)

    bars = broker.get_bars("EURUSD", Timeframe.H1, count=100)
    assert len(bars) == 100
    assert all(b.high >= b.low for b in bars)
    assert bars[0].time < bars[-1].time


def test_tick_and_order_lifecycle() -> None:
    broker = MockAdapter()
    broker.connect()
    tick = broker.get_tick("EURUSD")
    assert tick is not None
    assert tick.ask >= tick.bid

    result = broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1))
    assert result.ok
    positions = broker.get_positions("EURUSD")
    assert len(positions) == 1

    ticket = positions[0].ticket
    modified = broker.modify_position(ModifyRequest(ticket=ticket, sl=1.0, tp=2.0))
    assert modified.ok
    assert broker.get_positions()[0].sl == 1.0

    closed = broker.close_position(ticket)
    assert closed.ok
    assert broker.get_positions() == []


def test_account() -> None:
    broker = MockAdapter()
    broker.connect()
    account = broker.get_account()
    assert account.currency == "USD"
    assert account.balance > 0
