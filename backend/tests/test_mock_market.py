"""The mock broker's market ticks like a real one: a stream of ticks, positions marked to it,
stops and targets that close positions on their own."""

from __future__ import annotations

import itertools
import time

from app.broker.mock_adapter import MockAdapter
from app.schemas import ModifyRequest, OrderRequest


def adapter(rate: float = 400.0, volatility: float = 1.0) -> MockAdapter:
    broker = MockAdapter(tick_rate=rate, volatility=volatility)
    broker.connect()
    return broker


def test_ticks_arrive_in_order_none_twice_and_at_about_the_set_rate() -> None:
    broker = adapter(rate=200.0)
    first = broker.get_tick("EURUSD")
    assert first is not None
    time.sleep(0.5)
    ticks = broker.ticks_since("EURUSD", first.time_msc)
    assert all(a.time_msc < b.time_msc for a, b in itertools.pairwise(ticks))
    assert ticks[0].time_msc > first.time_msc
    assert 50 < len(ticks) < 200  # 200 a second for half a second, give or take chance
    again = broker.ticks_since("EURUSD", ticks[-1].time_msc)
    assert all(t.time_msc > ticks[-1].time_msc for t in again)


def test_the_price_walks_instead_of_jumping_about() -> None:
    broker = adapter(rate=300.0)
    broker.get_tick("EURUSD")
    time.sleep(0.4)
    ticks = broker.ticks_since("EURUSD", 0)
    steps = [abs(b.bid - a.bid) for a, b in itertools.pairwise(ticks)]
    assert max(steps) < 0.002  # a few pips at most between neighbours
    assert all(t.ask > t.bid for t in ticks)


def test_volatility_widens_the_moves() -> None:
    def spread_of_moves(volatility: float) -> float:
        broker = adapter(rate=500.0, volatility=volatility)
        broker.get_tick("XAUUSD")
        time.sleep(0.4)
        ticks = broker.ticks_since("XAUUSD", 0)
        moves = [abs(b.bid - a.bid) for a, b in itertools.pairwise(ticks)]
        return sum(moves) / len(moves)

    assert spread_of_moves(8.0) > 2 * spread_of_moves(1.0)


def test_an_open_position_follows_the_market() -> None:
    broker = adapter(rate=400.0)
    result = broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0))
    assert result.ok
    time.sleep(0.3)
    (position,) = broker.get_positions()
    quote = broker.get_tick("EURUSD")
    assert position.price_current == quote.bid or position.price_current != position.price_open
    expected = round((position.price_current - position.price_open) * 1.0 * 100_000, 2)
    assert position.profit == expected
    account = broker.get_account()
    assert account.profit == position.profit
    assert account.equity == round(account.balance + position.profit, 2)


def test_a_stop_closes_the_position_by_itself_and_the_loss_reaches_the_balance() -> None:
    broker = adapter(rate=400.0)
    broker.get_tick("EURUSD")
    tick = broker.get_tick("EURUSD")
    sl = round(tick.bid - 0.0005, 5)
    result = broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, sl=sl))
    assert result.ok
    broker._markets["EURUSD"]._mid = sl - 0.01  # the market falls through the stop
    time.sleep(0.05)
    assert broker.get_positions() == []
    account = broker.get_account()
    assert account.balance < 10_000.0
    assert account.profit == 0.0


def test_a_target_closes_a_sell_in_profit() -> None:
    broker = adapter(rate=400.0)
    tick = broker.get_tick("EURUSD")
    tp = round(tick.ask - 0.0005, 5)
    assert broker.place_order(OrderRequest(symbol="EURUSD", side="SELL", volume=1.0, tp=tp)).ok
    broker._markets["EURUSD"]._mid = tp - 0.01
    time.sleep(0.05)
    assert broker.get_positions() == []
    assert broker.get_account().balance > 10_000.0


def test_stops_on_the_wrong_side_are_refused_like_a_broker_does() -> None:
    broker = adapter()
    tick = broker.get_tick("EURUSD")
    refused = broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, sl=tick.bid + 0.01))
    assert not refused.ok and refused.error == "Invalid stops"
    assert broker.get_positions() == []

    assert broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0)).ok
    (position,) = broker.get_positions()
    moved = broker.modify_position(ModifyRequest(ticket=position.ticket, tp=tick.bid - 0.01))
    assert not moved.ok
    assert broker.get_positions()[0].tp == 0.0
    fine = broker.modify_position(ModifyRequest(ticket=position.ticket, sl=tick.bid - 0.01))
    assert fine.ok and broker.get_positions()[0].sl == tick.bid - 0.01


def test_modifying_one_level_leaves_the_other() -> None:
    broker = adapter()
    tick = broker.get_tick("EURUSD")
    assert broker.place_order(
        OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, tp=round(tick.bid + 0.02, 5))
    ).ok
    (position,) = broker.get_positions()
    assert broker.modify_position(ModifyRequest(ticket=position.ticket, sl=round(tick.bid - 0.02, 5))).ok
    after = broker.get_positions()[0]
    assert after.tp == round(tick.bid + 0.02, 5) and after.sl == round(tick.bid - 0.02, 5)


def test_closing_books_the_profit() -> None:
    broker = adapter()
    assert broker.place_order(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0)).ok
    (position,) = broker.get_positions()
    time.sleep(0.2)
    closed = broker.close_position(position.ticket)
    assert closed.ok
    assert broker.get_positions() == []
    assert not broker.close_position(position.ticket).ok
    account = broker.get_account()
    assert account.profit == 0.0 and account.equity == account.balance


def test_a_market_left_alone_does_not_replay_the_hours_it_missed() -> None:
    broker = adapter(rate=50.0)
    broker.get_tick("EURUSD")
    market = broker._markets["EURUSD"]
    market._next_ms -= 3_600_000  # an hour with nobody looking
    ticks = broker.ticks_since("EURUSD", 0)
    assert len(ticks) < 400
