"""The figures of a performance report, and the broker's history put together into trades."""

from __future__ import annotations

import pytest

from app.performance import account_report, summarize, symbol_stats, thin_curve, trades_from_deals
from app.schemas import AccountInfo, BacktestTrade, ClosedTrade, Deal


# -- building history -----------------------------------------------------------------------------------
class Book:
    """A few lines of an account's history, in the order they happened."""

    def __init__(self) -> None:
        self.deals: list[Deal] = []
        self._ticket = 1000

    def _add(self, **fields) -> Deal:
        self._ticket += 1
        deal = Deal(ticket=self._ticket, **fields)
        self.deals.append(deal)
        return deal

    def deposit(self, time: int, amount: float, kind: str = "balance") -> None:
        self._add(time=time, kind=kind, profit=amount, comment="deposit")

    def op(self, time: int, kind: str, amount: float) -> None:
        self._add(time=time, kind=kind, profit=amount)

    def fill(
        self,
        time: int,
        side: str,
        entry: str,
        position: int,
        volume: float,
        price: float,
        *,
        symbol: str = "EURUSD",
        **money,
    ) -> Deal:
        return self._add(
            time=time,
            kind=side,
            entry=entry,
            position_id=position,
            volume=volume,
            price=price,
            symbol=symbol,
            **money,
        )

    def trade(
        self,
        position: int,
        side: str,
        t0: int,
        t1: int,
        volume: float,
        p0: float,
        p1: float,
        profit: float,
        *,
        symbol: str = "EURUSD",
        reason: str = "client",
        **costs,
    ) -> None:
        """A position opened and closed in one go (the closing fill goes the other way)."""
        other = "sell" if side == "buy" else "buy"
        self.fill(
            t0,
            side,
            "in",
            position,
            volume,
            p0,
            symbol=symbol,
            commission=costs.pop("entry_commission", 0.0),
        )
        self.fill(
            t1,
            other,
            "out",
            position,
            volume,
            p1,
            symbol=symbol,
            profit=profit,
            reason=reason,
            **costs,
        )


def account(balance: float, profit: float = 0.0, **fields) -> AccountInfo:
    return AccountInfo(
        login=1,
        server="Demo",
        currency="EUR",
        balance=balance,
        equity=balance + profit,
        profit=profit,
        **fields,
    )


# -- the figures --------------------------------------------------------------------------------------------
def make(
    pnl: float,
    t0: int = 0,
    t1: int = 60,
    side: str = "BUY",
    symbol: str = "EURUSD",
    volume: float = 0.1,
    **extra,
) -> ClosedTrade:
    return ClosedTrade(
        entry_time=t0,
        exit_time=t1,
        side=side,
        entry_price=1.0,
        exit_price=1.0,
        volume=volume,
        pnl=pnl,
        symbol=symbol,
        **extra,
    )


def test_the_headline_figures() -> None:
    trades = [make(10), make(-4), make(6, side="SELL"), make(0), make(-2)]
    s = summarize(trades, max_drawdown=5.0, max_drawdown_pct=2.5)
    assert (s.trades, s.wins, s.losses) == (5, 2, 2)
    assert s.net_profit == 10 and s.gross_profit == 16 and s.gross_loss == 6
    assert s.win_rate == pytest.approx(40.0)
    assert s.profit_factor == pytest.approx(16 / 6)
    assert (s.avg_win, s.avg_loss) == (8.0, 3.0) and s.payoff_ratio == pytest.approx(8 / 3)
    assert (s.largest_win, s.largest_loss) == (10, -4)
    assert s.avg_trade == 2.0 and s.avg_duration == 60
    assert (s.max_drawdown, s.max_drawdown_pct) == (5.0, 2.5)
    assert s.recovery_factor == pytest.approx(2.0)  # 10 made over a worst drawdown of 5


def test_no_trades_and_no_losses_are_told_apart_by_the_profit_factor() -> None:
    nothing = summarize([], max_drawdown=0, max_drawdown_pct=0)
    assert (
        nothing.trades == 0
        and nothing.profit_factor is None
        and nothing.win_rate == 0
        and nothing.recovery_factor is None
    )
    only_wins = summarize([make(3), make(4)], max_drawdown=0, max_drawdown_pct=0)
    assert (
        only_wins.profit_factor is None and only_wins.wins == 2 and only_wins.payoff_ratio is None
    )


def test_streaks_are_counted_and_their_amounts_are_kept() -> None:
    pnls = [5, 5, -1, -1, -1, 7, 1, 1, 1, -9, 0, 2]
    s = summarize([make(p) for p in pnls], max_drawdown=0, max_drawdown_pct=0)
    # winning runs: 5+5 (2), 7+1+1+1 (4), 2 (1); losing runs: three of -1 (3), -9 (1)
    assert s.max_win_streak == 4 and s.max_win_streak_amount == 10
    assert s.max_loss_streak == 3 and s.max_loss_streak_amount == -3
    assert s.best_win_streak_amount == 10 and s.best_win_streak_amount_trades == 4
    assert s.worst_loss_streak_amount == -9 and s.worst_loss_streak_amount_trades == 1
    assert s.avg_win_streak == pytest.approx(7 / 3) and s.avg_loss_streak == pytest.approx(2.0)


def test_a_trade_that_made_nothing_ends_a_streak_without_being_in_one() -> None:
    s = summarize([make(1), make(1), make(0), make(1)], max_drawdown=0, max_drawdown_pct=0)
    assert s.max_win_streak == 2


def test_longs_shorts_durations_volume_and_costs() -> None:
    trades = [
        make(5, 0, 100, volume=0.5, commission=-0.2, swap=-0.1, fee=-0.05),
        make(-3, 0, 400, side="SELL", volume=1.0, commission=-0.4),
        make(2, 0, 25, side="SELL", volume=0.25, swap=0.3),
    ]
    s = summarize(trades, max_drawdown=0, max_drawdown_pct=0)
    assert (s.long_trades, s.long_wins, s.short_trades, s.short_wins) == (1, 1, 2, 1)
    assert (s.longest_duration, s.shortest_duration) == (400, 25) and s.avg_duration == 175
    assert s.total_volume == pytest.approx(1.75)
    assert (
        s.commission == pytest.approx(-0.6)
        and s.swap == pytest.approx(0.2)
        and s.fees == pytest.approx(-0.05)
    )


def test_the_replays_trades_have_no_costs_and_that_is_fine() -> None:
    trade = BacktestTrade(
        entry_time=0, exit_time=10, side="BUY", entry_price=1, exit_price=2, volume=1, pnl=1
    )
    s = summarize([trade], max_drawdown=0, max_drawdown_pct=0)
    assert (s.commission, s.swap, s.fees) == (0, 0, 0)


def test_the_sharpe_ratio_needs_three_trades_and_a_capital() -> None:
    assert (
        summarize([make(1), make(2)], max_drawdown=0, max_drawdown_pct=0, capital=100).sharpe
        is None
    )
    assert (
        summarize([make(1), make(2), make(-1)], max_drawdown=0, max_drawdown_pct=0).sharpe is None
    )  # nothing to measure against
    s = summarize(
        [make(1), make(2), make(-1), make(3)], max_drawdown=0, max_drawdown_pct=0, capital=100
    )
    assert s.sharpe is not None and s.sharpe > 0
    assert (
        summarize([make(1), make(1), make(1)], max_drawdown=0, max_drawdown_pct=0, capital=0).sharpe
        is None
    )


def test_each_instrument_is_reported_with_the_most_profitable_first() -> None:
    rows = symbol_stats(
        [
            make(5, symbol="EURUSD"),
            make(-2, symbol="EURUSD"),
            make(9, symbol="XAUUSD", volume=0.3),
            make(-1, symbol=""),
        ]
    )
    assert [r.symbol for r in rows] == ["XAUUSD", "EURUSD", "—"]
    eur = rows[1]
    assert (eur.trades, eur.wins, eur.losses, eur.net_profit) == (2, 1, 1, 3) and eur.win_rate == 50
    assert rows[0].volume == pytest.approx(0.3)


def test_a_long_curve_is_thinned_but_keeps_its_ends_and_extremes() -> None:
    points = [
        (i, 100 + (i % 7) - (50 if i == 313 else 0) + (40 if i == 777 else 0)) for i in range(1000)
    ]
    thin = thin_curve(points, 100)
    assert 90 <= len(thin) <= 110
    assert (thin[0].time, thin[-1].time) == (0, 999)
    values = [p.value for p in thin]
    assert min(values) == min(v for _, v in points) and max(values) == max(v for _, v in points)
    assert [p.time for p in thin] == sorted(p.time for p in thin)
    short = [(1, 2.0), (2, 3.0)]
    assert [(p.time, p.value) for p in thin_curve(short, 100)] == short


# -- positions from fills --------------------------------------------------------------------------------------
def test_a_position_opened_and_closed_is_one_trade_with_its_costs() -> None:
    book = Book()
    book.trade(
        7,
        "buy",
        1000,
        1600,
        0.2,
        1.1000,
        1.1050,
        10.0,
        entry_commission=-0.7,
        commission=-0.7,
        swap=-0.15,
        reason="tp",
    )
    (trade,) = trades_from_deals(book.deals).trades
    assert (trade.side, trade.symbol, trade.volume, trade.ticket) == ("BUY", "EURUSD", 0.2, 7)
    assert (trade.entry_time, trade.exit_time) == (1000, 1600)
    assert trade.entry_price == pytest.approx(1.1) and trade.exit_price == pytest.approx(1.105)
    assert trade.profit == 10.0 and trade.commission == pytest.approx(-1.4) and trade.swap == -0.15
    assert trade.pnl == pytest.approx(10.0 - 1.4 - 0.15)
    assert trade.reason == "tp"


def test_a_position_closed_in_parts_is_one_trade() -> None:
    book = Book()
    book.fill(0, "sell", "in", 5, 1.0, 1.2000)
    book.fill(100, "buy", "out", 5, 0.4, 1.1900, profit=4.0, reason="tp")
    book.fill(300, "buy", "out", 5, 0.6, 1.2100, profit=-6.0, reason="client")
    (trade,) = trades_from_deals(book.deals).trades
    assert trade.side == "SELL" and trade.volume == 1.0
    assert (
        trade.exit_price == pytest.approx((0.4 * 1.19 + 0.6 * 1.21) / 1.0)
        and trade.exit_time == 300
    )
    assert trade.pnl == -2.0 and trade.reason == "manual"  # how it ended: by the last part


def test_a_position_added_to_has_the_average_entry() -> None:
    book = Book()
    book.fill(0, "buy", "in", 9, 0.5, 1.0)
    book.fill(10, "buy", "in", 9, 0.5, 1.2)
    book.fill(20, "sell", "out", 9, 1.0, 1.3, profit=20.0)
    (trade,) = trades_from_deals(book.deals).trades
    assert trade.entry_price == pytest.approx(1.1) and trade.volume == 1.0 and trade.entry_time == 0


def test_a_position_that_is_still_open_is_no_trade_but_its_costs_are_counted() -> None:
    book = Book()
    book.fill(0, "buy", "in", 3, 1.0, 1.1, commission=-3.5)
    history = trades_from_deals(book.deals)
    assert (
        history.trades == []
        and history.total_effect == -3.5
        and history.moves == [(0, -3.5, False)]
    )


def test_a_reversal_closes_one_position_and_opens_the_other() -> None:
    book = Book()
    book.fill(0, "buy", "in", 4, 1.0, 1.1000)
    book.fill(
        100, "sell", "inout", 4, 2.0, 1.1100, profit=10.0, commission=-1.0
    )  # sells 2 lots: the long is closed, a short opened
    book.fill(200, "buy", "out", 4, 1.0, 1.1050, profit=5.0)
    first, second = trades_from_deals(book.deals).trades
    assert (first.side, first.volume, first.pnl, first.exit_time) == ("BUY", 1.0, 9.0, 100)
    assert (second.side, second.volume, second.pnl, second.entry_time) == ("SELL", 1.0, 5.0, 100)
    assert second.entry_price == pytest.approx(1.11)


def test_a_close_whose_opening_is_not_in_the_history_is_still_a_trade() -> None:
    book = Book()
    book.fill(
        500, "sell", "out", 99, 0.5, 1.3, profit=12.0
    )  # a long, opened before the history begins
    (trade,) = trades_from_deals(book.deals).trades
    assert (
        trade.side == "BUY" and trade.volume == 0.5 and trade.pnl == 12.0 and trade.exit_time == 500
    )


def test_the_order_the_deals_come_in_does_not_matter() -> None:
    book = Book()
    book.trade(1, "buy", 0, 100, 1.0, 1.0, 1.1, 5.0)
    book.trade(2, "sell", 200, 300, 1.0, 1.1, 1.2, -4.0)
    forward = trades_from_deals(book.deals).trades
    backward = trades_from_deals(reversed(book.deals)).trades
    assert [t.pnl for t in forward] == [t.pnl for t in backward] == [5.0, -4.0]


@pytest.mark.parametrize(
    "reason,comment,expected",
    [
        ("sl", "[sl 1.1]", "sl"),
        ("tp", "", "tp"),
        ("so", "", "so"),
        ("client", "", "manual"),
        ("mobile", "", "manual"),
        ("web", "", "manual"),
        (
            "expert",
            "cheaptrader close",
            "manual",
        ),  # a click in this program arrives as an "expert" deal
        ("expert", "my robot", "expert"),
        ("", "", "manual"),
        ("rollover", "", "rollover"),
    ],
)
def test_why_a_position_ended_is_told_in_the_replays_words(
    reason: str, comment: str, expected: str
) -> None:
    book = Book()
    book.fill(0, "buy", "in", 1, 1.0, 1.0)
    book.fill(10, "sell", "out", 1, 1.0, 1.0, reason=reason, comment=comment)
    assert trades_from_deals(book.deals).trades[0].reason == expected


def test_money_that_moves_is_kept_apart_from_trading() -> None:
    book = Book()
    book.deposit(0, 1000.0)
    book.deposit(10, 500.0, kind="bonus")
    book.deposit(20, -200.0)  # a withdrawal
    book.op(30, "credit", 300.0)  # credit is no part of the balance
    book.op(40, "charge", -1.5)
    book.op(50, "interest", -0.5)
    book.op(60, "correction", 2.0)
    book.fill(70, "buy", "in", 1, 1.0, 1.0)
    h = trades_from_deals(book.deals)
    f = h.flows
    assert (f.deposits, f.withdrawals, f.credit, f.bonus, f.corrections, f.charges) == (
        1000.0,
        200.0,
        300.0,
        500.0,
        2.0,
        -2.0,
    )
    assert f.operations == 7
    assert h.total_effect == pytest.approx(
        1000 + 500 - 200 - 1.5 - 0.5 + 2.0
    )  # credit is not in it
    assert [money for _, _, money in h.moves] == [True, True, True, False, False, True]


def test_a_cancelled_deal_is_nothing() -> None:
    book = Book()
    book.fill(0, "buy", "in", 1, 1.0, 1.0)
    book._add(time=5, kind="canceled", position_id=1, volume=1.0, profit=0.0)
    assert trades_from_deals(book.deals).moves == []


# -- the report ---------------------------------------------------------------------------------------------------
def demo_book() -> Book:
    book = Book()
    book.deposit(1000, 100.0)
    book.trade(
        1, "buy", 2000, 2600, 0.1, 1.0, 1.05, 5.0, entry_commission=-0.5, commission=-0.5
    )  # +4
    book.trade(
        2, "sell", 3000, 3300, 0.1, 1.05, 1.07, -2.0, entry_commission=-0.5, commission=-0.5
    )  # -3
    return book


def test_the_report_of_a_small_demo_account() -> None:
    book = demo_book()
    r = account_report(book.deals, account(101.0), now=4000)
    assert (
        r.initial_balance == 100.0
        and r.summary.net_profit == 1.0
        and r.return_pct == pytest.approx(1.0)
    )
    assert r.summary.trades == 2 and r.trades_total == 2 and [t.ticket for t in r.trades] == [1, 2]
    # the level it started from, what each deal did to it, and where it stands at the time asked for
    assert [(p.time, p.value) for p in r.equity] == [
        (2000, 100.0),
        (2000, 99.5),
        (2600, 104.0),
        (3000, 103.5),
        (3300, 101.0),
        (4000, 101.0),
    ]
    assert r.summary.max_drawdown == pytest.approx(
        3.0
    ) and r.summary.max_drawdown_pct == pytest.approx(3.0 / 104.0 * 100)
    assert (
        r.flows.deposits == 100.0 and r.deals == 5 and (r.first_time, r.last_time) == (1000, 3300)
    )


def test_a_deposit_after_trading_began_is_no_part_of_the_curve_or_the_percentages() -> None:
    book = demo_book()
    book.deposit(3100, 900.0)  # between the two trades
    r = account_report(book.deals, account(1001.0), now=4000)
    assert r.initial_balance == 100.0 and r.return_pct == pytest.approx(1.0)
    assert max(p.value for p in r.equity) == pytest.approx(104.0) and r.equity[
        -1
    ].value == pytest.approx(101.0)
    assert r.summary.max_drawdown == pytest.approx(3.0)  # the deposit did not lift the peak


def test_a_withdrawal_is_not_a_drawdown() -> None:
    book = demo_book()
    book.deposit(3100, -50.0)
    r = account_report(book.deals, account(51.0), now=4000)
    assert r.summary.max_drawdown == pytest.approx(3.0) and r.equity[-1].value == pytest.approx(
        101.0
    )
    assert r.flows.withdrawals == 50.0


def test_a_history_that_does_not_reach_back_to_the_first_deposit_still_adds_up() -> None:
    book = Book()
    book.trade(1, "buy", 2000, 2600, 0.1, 1.0, 1.05, 5.0)
    book.trade(2, "buy", 3000, 3300, 0.1, 1.0, 0.98, -2.0)
    r = account_report(
        book.deals, account(250.0), now=3300
    )  # the balance was 247 before the first deal
    assert r.initial_balance == pytest.approx(247.0) and r.equity[0].value == pytest.approx(247.0)
    assert r.equity[-1].value == pytest.approx(250.0) and r.return_pct == pytest.approx(
        3 / 247 * 100
    )


def test_the_open_positions_move_the_end_of_the_curve_and_can_be_a_drawdown() -> None:
    book = demo_book()
    r = account_report(book.deals, account(101.0, profit=-6.0), now=5000)
    assert r.equity[-1].value == pytest.approx(95.0) and r.equity[-1].time == 5000
    assert r.open_profit == -6.0
    assert r.summary.max_drawdown == pytest.approx(
        104.0 - 95.0
    )  # as it stands now, it is the worst
    assert r.summary.drawdown_absolute == pytest.approx(5.0)  # five below the 100 that was put in


def test_charges_lower_the_curve_but_are_no_trade() -> None:
    book = demo_book()
    book.op(3400, "charge", -1.0)
    r = account_report(book.deals, account(100.0), now=3500)
    assert r.summary.trades == 2 and r.summary.net_profit == 1.0
    assert r.equity[-1].value == pytest.approx(100.0) and r.flows.charges == -1.0


def test_an_account_that_never_traded_has_no_curve_and_no_figures() -> None:
    book = Book()
    book.deposit(1000, 100.0)
    r = account_report(book.deals, account(100.0))
    assert (
        r.equity == []
        and r.trades == []
        and r.summary.trades == 0
        and r.return_pct == 0.0
        and r.initial_balance == 100.0
    )
    empty = account_report([], account(0.0))
    assert (
        empty.deals == 0
        and empty.return_pct is None
        and empty.equity == []
        and empty.first_time == 0
    )


def test_the_list_of_trades_is_cut_but_the_figures_are_not() -> None:
    book = Book()
    book.deposit(0, 100.0)
    for i in range(30):
        book.trade(i + 1, "buy", 100 + i * 10, 105 + i * 10, 0.1, 1.0, 1.1, 1.0 if i % 3 else -0.5)
    r = account_report(
        book.deals, account(100.0 + sum(1.0 if i % 3 else -0.5 for i in range(30))), trade_limit=10
    )
    assert len(r.trades) == 10 and r.trades_total == 30 and r.summary.trades == 30
    assert [t.ticket for t in r.trades] == list(range(21, 31))  # the newest
    assert (
        len(account_report(book.deals, account(100.0), points=8).equity) <= 10
    )  # thinned to about what was asked for


def test_the_curve_keeps_one_point_for_deals_in_the_same_second() -> None:
    book = Book()
    book.deposit(0, 100.0)
    book.fill(10, "buy", "in", 1, 1.0, 1.0, commission=-1.0)
    book.fill(10, "buy", "in", 2, 1.0, 1.0, commission=-1.0)
    book.fill(20, "sell", "out", 1, 1.0, 1.1, profit=5.0)
    r = account_report(book.deals, account(103.0), now=20)
    assert [(p.time, p.value) for p in r.equity] == [
        (10, 100.0),
        (10, 98.0),
        (20, 103.0),
    ]  # the start, then one point for that second


# -- a period --------------------------------------------------------------------------------------------------------
def test_a_period_starts_from_where_the_account_stood_then() -> None:
    book = demo_book()
    r = account_report(
        book.deals, account(101.0), now=4000, since=2800
    )  # after the first trade, before the second
    assert r.initial_balance == pytest.approx(104.0)  # what the first trade left
    assert [t.ticket for t in r.trades] == [2] and r.trades_total == 1 and r.summary.trades == 1
    assert r.summary.net_profit == pytest.approx(-3.0) and r.return_pct == pytest.approx(
        -3.0 / 104.0 * 100
    )
    assert [(p.time, p.value) for p in r.equity] == [
        (2800, 104.0),
        (3000, 103.5),
        (3300, 101.0),
        (4000, 101.0),
    ]
    assert r.summary.max_drawdown == pytest.approx(
        3.0
    ) and r.summary.drawdown_absolute == pytest.approx(3.0)
    assert r.flows.deposits == 0.0 and r.flows.operations == 0  # the deposit was before the period
    assert (r.deals, r.first_time, r.last_time) == (
        5,
        1000,
        3300,
    )  # the history itself is all of it


def test_a_drawdown_before_the_period_is_not_one_in_it() -> None:
    book = Book()
    book.deposit(0, 1000.0)
    book.trade(1, "buy", 100, 200, 1.0, 1.0, 0.9, -300.0)  # a bad start
    book.trade(2, "buy", 300, 400, 1.0, 1.0, 1.1, 120.0)
    book.trade(3, "buy", 500, 600, 1.0, 1.0, 1.1, 30.0)
    r = account_report(book.deals, account(850.0), now=700, since=250)
    assert r.summary.trades == 2 and r.summary.max_drawdown == 0.0 and r.summary.net_profit == 150.0
    assert r.initial_balance == pytest.approx(700.0) and r.return_pct == pytest.approx(
        150 / 700 * 100
    )
    everything = account_report(book.deals, account(850.0), now=700)
    assert everything.summary.max_drawdown == pytest.approx(300.0)


def test_a_period_before_the_history_is_the_whole_history() -> None:
    book = demo_book()
    whole = account_report(book.deals, account(101.0), now=4000)
    early = account_report(book.deals, account(101.0), now=4000, since=1)
    assert early.model_dump() == whole.model_dump()


def test_a_period_with_no_trading_in_it_has_nothing_but_where_the_account_stands() -> None:
    book = demo_book()
    r = account_report(book.deals, account(101.0), now=9000, since=5000)
    assert r.summary.trades == 0 and r.trades == [] and r.equity == [] and r.symbols == []
    assert r.initial_balance == pytest.approx(101.0) and r.return_pct == 0.0


def test_the_money_that_moved_is_counted_within_the_period() -> None:
    book = demo_book()
    book.deposit(3100, 900.0)
    r = account_report(book.deals, account(1001.0), now=4000, since=3050)
    assert r.flows.deposits == 900.0 and r.flows.operations == 1
    assert account_report(book.deals, account(1001.0), now=4000, since=3200).flows.operations == 0
