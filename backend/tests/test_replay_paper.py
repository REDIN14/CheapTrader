"""The replay engine moving over a hand-made series, and the paper account behind it."""

from __future__ import annotations

import asyncio
import random
from itertools import pairwise

import pytest

from app.replay.engine import ReplayEngine
from app.replay.paper import PaperTradingEngine
from app.schemas import Bar, OrderRequest, Timeframe

START = 1_000_000
STEP = 3600


def bar(i: int, close: float, high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        time=START + i * STEP,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
    )


def flat(n: int, price: float = 1.0) -> list[Bar]:
    return [bar(i, price) for i in range(n)]


def engine_over(bars: list[Bar]) -> ReplayEngine:
    return ReplayEngine.from_bars("EURUSD", Timeframe.H1, bars, contract_size=100_000.0)


def order(side: str = "BUY", volume: float = 1.0, sl: float | None = None, tp: float | None = None) -> OrderRequest:
    return OrderRequest(symbol="EURUSD", side=side, volume=volume, sl=sl, tp=tp)  # type: ignore[arg-type]


# -- the cursor ----------------------------------------------------------------------
def test_seek_forward_checks_every_bar_on_the_way() -> None:
    """Jumping to the end must give the result of having played it."""
    bars = flat(10)
    bars[6] = bar(6, 1.0, high=1.02)  # a spike that reaches the target
    engine = engine_over(bars)
    engine.paper.place(order(tp=1.01), bars[0])

    engine.seek(9)

    assert engine.paper.positions == {}
    assert [t.reason for t in engine.paper.closed] == ["tp"]
    assert engine.paper.closed[0].exit_time == bars[6].time
    assert engine.paper.balance == pytest.approx(10_000 + 0.01 * 100_000)


def test_jump_and_step_agree() -> None:
    bars = flat(12)
    bars[4] = bar(4, 1.0, low=0.98)
    stepped, jumped = engine_over(bars), engine_over(bars)
    for e in (stepped, jumped):
        e.paper.place(order(sl=0.99), bars[0])
    for _ in range(11):
        stepped.step(1)
    jumped.seek(11)
    assert [(t.reason, t.exit_time, t.pnl) for t in stepped.paper.closed] == [
        (t.reason, t.exit_time, t.pnl) for t in jumped.paper.closed
    ]


def test_seek_backward_closes_what_is_open_and_keeps_the_account() -> None:
    """Going back in time cannot undo a trade: it is closed where it stood, and the account
    (balance, history) is not wiped. Starting the account over is the profile's reset."""
    bars = flat(10)
    bars[4:] = [bar(i, 1.01) for i in range(4, 10)]
    engine = engine_over(bars)
    engine.seek(3)
    engine.paper.place(order(), engine.bars[3])
    engine.seek(5)  # the price rose by 0.01 meanwhile
    assert len(engine.paper.positions) == 1

    engine.seek(2)

    assert engine.index == 2
    assert engine.paper.positions == {}
    assert [(t.reason, t.exit_price) for t in engine.paper.closed] == [("rewind", 1.01)]
    assert engine.paper.balance == pytest.approx(10_000 + 0.01 * 100_000)
    # only the equity curve starts again, from the new position
    curve = engine.paper._equity_curve
    assert len(curve) == 1 and curve[0]["time"] == float(engine.bars[2].time)
    assert curve[0]["value"] == pytest.approx(engine.paper.balance)


def test_begin_puts_the_cursor_and_starts_the_curve_there() -> None:
    engine = engine_over(flat(10))
    engine.seek(6)
    state = engine.begin(3)
    assert state.index == 3
    curve = engine.paper._equity_curve
    assert len(curve) == 1 and curve[0]["time"] == float(engine.bars[3].time)
    assert curve[0]["value"] == 10_000


def test_reset_goes_back_to_the_first_bar_and_keeps_the_account() -> None:
    engine = engine_over(flat(5))
    engine.paper.place(order(), engine.bars[0])
    engine.seek(3)
    engine.reset()
    assert engine.index == 0
    assert engine.paper.positions == {}  # closed where it stood...
    assert len(engine.paper.closed) == 1  # ...and kept in the history, not erased


def test_advance_reports_the_bars_and_trades_of_the_move() -> None:
    bars = flat(10)
    bars[3] = bar(3, 1.0, high=1.05)
    engine = engine_over(bars)
    engine.paper.place(order(tp=1.04), bars[0])

    first = engine.advance(2)
    assert [b.time for b in first.bars] == [bars[1].time, bars[2].time]
    assert first.closed == []

    second = engine.advance(3)
    assert [b.time for b in second.bars] == [bars[3].time, bars[4].time, bars[5].time]
    assert [t.reason for t in second.closed] == ["tp"]
    assert second.state.index == 5


def test_advance_stops_at_the_last_bar() -> None:
    engine = engine_over(flat(4))
    moved = engine.advance(50)
    assert engine.index == 3
    assert len(moved.bars) == 3


def test_nearest_index_snaps_and_clamps() -> None:
    engine = engine_over(flat(10))
    assert engine.nearest_index(START + 4 * STEP) == 4
    assert engine.nearest_index(START + 4 * STEP + 1) == 4
    assert engine.nearest_index(START + 5 * STEP - 1) == 5
    assert engine.nearest_index(START + 4 * STEP + STEP // 2) == 4  # a tie goes to the earlier bar
    assert engine.nearest_index(0) == 0
    assert engine.nearest_index(START + 99 * STEP) == 9


@pytest.mark.asyncio
async def test_pressing_play_twice_runs_one_loop() -> None:
    engine = engine_over(flat(50))
    engine.play()
    engine.ensure_running(0.5)
    first = engine._task
    engine.pause()
    engine.play()
    engine.ensure_running(0.5)  # the first loop is still asleep
    assert engine._task is first
    engine.pause()
    await asyncio.sleep(0)  # let the cancelled sleep settle
    first.cancel()


# -- the paper account ---------------------------------------------------------------
def test_account_splits_balance_and_floating_profit() -> None:
    engine = engine_over(flat(5))
    paper = engine.paper
    paper.place(order(volume=1.0), engine.bars[0])  # BUY 1 lot at 1.0000
    acct = paper.account(1.001)  # 10 pips up
    assert acct.balance == 10_000
    assert acct.unrealized == pytest.approx(100.0)
    assert acct.equity == pytest.approx(10_100.0)
    assert acct.realized == 0
    assert acct.initial_balance == 10_000
    assert len(acct.positions) == 1 and acct.positions[0].profit == pytest.approx(100.0)
    assert acct.trades_total == 0
    assert (acct.wins, acct.losses) == (0, 0)


def test_account_counts_winning_and_losing_trades() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    for exit_price in (1.002, 0.999, 1.0):  # a win, a loss, an even trade
        paper.place(order(volume=1.0), bar(0, 1.0))
        paper.close(paper._next_ticket - 1, bar(1, exit_price))
    acct = paper.account(1.0)
    assert (acct.trades_total, acct.wins, acct.losses) == (3, 1, 1)


def test_manual_close_moves_money_from_floating_to_realised() -> None:
    engine = engine_over(flat(5))
    paper = engine.paper
    paper.place(order(volume=1.0), engine.bars[0])
    engine.seek(1)
    closing = bar(1, 1.002)
    result = paper.close(1, closing)
    assert result.ok
    acct = paper.account(1.002)
    assert acct.realized == pytest.approx(200.0) and acct.unrealized == 0
    assert acct.equity == pytest.approx(10_200.0)
    assert paper.closed[0].ticket == 1 and paper.closed[0].reason == "manual"
    # the curve has one point per bar: closing on a bar the curve already has changes nothing
    times = [p["time"] for p in paper._equity_curve]
    assert times == sorted(set(times))


def test_summary_of_a_few_trades() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    # BUY +200, SELL -50, BUY +100, BUY +100, SELL -80
    spec = [("BUY", 1.0, 1.002), ("SELL", 1.0, 1.0005), ("BUY", 1.0, 1.001), ("BUY", 1.0, 1.001), ("SELL", 1.0, 1.0008)]
    t = 0
    for side, entry, exit_price in spec:
        paper.place(order(side=side), bar(t, entry))
        paper.close(paper._next_ticket - 1, bar(t + 2, exit_price))
        t += 3
    s = paper.summary(1.0)

    assert s.trades == 5 and s.wins == 3 and s.losses == 2
    assert s.net_profit == pytest.approx(200 - 50 + 100 + 100 - 80)
    assert s.gross_profit == pytest.approx(400) and s.gross_loss == pytest.approx(130)
    assert s.win_rate == pytest.approx(60)
    assert s.profit_factor == pytest.approx(400 / 130)
    assert s.avg_win == pytest.approx(400 / 3) and s.avg_loss == pytest.approx(65)
    assert s.payoff_ratio == pytest.approx((400 / 3) / 65)
    assert s.largest_win == pytest.approx(200) and s.largest_loss == pytest.approx(-80)
    assert s.avg_trade == pytest.approx(270 / 5)
    assert s.avg_duration == 2 * STEP
    assert s.max_win_streak == 2 and s.max_loss_streak == 1


def test_summary_with_no_losses_has_no_profit_factor() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    paper.place(order(), bar(0, 1.0))
    paper.close(1, bar(1, 1.001))
    s = paper.summary(1.001)
    assert s.profit_factor is None and s.payoff_ratio is None
    assert s.wins == 1 and s.losses == 0 and s.avg_loss == 0 and s.largest_loss == 0


def test_summary_with_no_trades_is_all_zeros() -> None:
    s = PaperTradingEngine(symbol="EURUSD").summary(1.0)
    assert (s.trades, s.net_profit, s.win_rate, s.avg_duration, s.max_drawdown) == (0, 0, 0, 0, 0)
    assert s.profit_factor is None


def test_running_drawdown_matches_a_brute_force_walk() -> None:
    rng = random.Random(7)
    paper = PaperTradingEngine(symbol="EURUSD")
    price = 1.0
    paper.place(order(volume=2.0), bar(0, price))
    paper.mark(bar(0, price))
    for i in range(1, 400):
        price += rng.gauss(0, 0.0004)
        paper.on_bar(bar(i, price))

    values = [p["value"] for p in paper._equity_curve]
    peak, worst_value, worst_pct = paper.initial_balance, 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        worst_value = max(worst_value, peak - v)
        worst_pct = max(worst_pct, (peak - v) / peak * 100)

    metrics = paper.metrics(price)
    summary = paper.summary(price)
    assert metrics.max_drawdown_pct == pytest.approx(worst_pct)
    assert summary.max_drawdown == pytest.approx(worst_value)
    assert summary.max_drawdown_pct == pytest.approx(worst_pct)

    # and the Sharpe figure still matches the textbook computation
    returns = [(b - a) / a for a, b in pairwise(values) if a]
    mean = sum(returns) / len(returns)
    sd = (sum((r - mean) ** 2 for r in returns) / len(returns)) ** 0.5
    assert metrics.sharpe == pytest.approx(mean / sd * len(returns) ** 0.5)


def test_drawdown_counts_the_account_as_it_is_now() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    paper.place(order(volume=1.0), bar(0, 1.0))
    # no bar has been processed since the position opened, but the market is 100 pips against it
    assert paper.summary(0.99).max_drawdown == pytest.approx(1000.0)
    assert paper.metrics(0.99).max_drawdown_pct == pytest.approx(10.0)


def test_equity_points_are_thinned_but_keep_the_extremes() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    paper.place(order(volume=1.0), bar(0, 1.0))
    paper.mark(bar(0, 1.0))
    prices = [1.0 + 0.0001 * ((i * 37) % 101 - 50) for i in range(1, 3000)]
    for i, p in enumerate(prices, start=1):
        paper.on_bar(bar(i, p))
    pts = paper.equity_points(200)

    assert len(pts) <= 203
    assert pts[0].time == START and pts[-1].time == bar(2999, 1).time
    assert [p.time for p in pts] == sorted(p.time for p in pts)
    values = [p["value"] for p in paper._equity_curve]
    assert max(p.value for p in pts) == pytest.approx(max(values))
    assert min(p.value for p in pts) == pytest.approx(min(values))
    # a short curve is returned whole
    assert len(paper.equity_points(5000)) == len(paper._equity_curve)


def test_reset_clears_the_running_figures() -> None:
    paper = PaperTradingEngine(symbol="EURUSD")
    paper.place(order(volume=1.0), bar(0, 1.0))
    paper.on_bar(bar(1, 0.98))
    assert paper.summary(0.98).max_drawdown > 0
    paper.reset()
    paper.mark(bar(2, 1.0))
    assert paper.summary(1.0).max_drawdown == 0
    assert paper.metrics(1.0).max_drawdown_pct == 0
    assert paper.positions == {} and paper.closed == []
