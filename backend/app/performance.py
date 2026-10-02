"""Performance figures worked out from closed trades.

The replay's paper account and the broker's own history are reported in one way: both end up as a
list of closed trades, and the figures below are worked out from that list. So the live report says
the same things in the same words as the replay's, and a figure means the same in both.

* ``summarize`` the headline figures and the longer table (``PerformanceSummary``);
* ``symbol_stats`` what each instrument made;
* ``thin_curve`` an equity curve cut down to a few hundred points without losing its peaks and troughs;
* ``trades_from_deals`` and ``account_report`` the broker's history (``Deal`` lines) as closed trades,
  money that moved without being trading, and the report that goes with them.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.schemas import (
    AccountFlows,
    AccountInfo,
    AccountReport,
    BacktestTrade,
    ClosedTrade,
    Deal,
    EquityPoint,
    PerformanceSummary,
    SymbolStats,
)

#: Volumes below this are nothing (floating-point dust left over from adding and subtracting lots).
_EPS = 1e-9
#: Closed trades the report lists; ``trades_total`` says how many there are.
TRADE_LIMIT = 2000


# -- the figures ----------------------------------------------------------------------------------
def _streaks(pnls: Sequence[float]) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """The runs of winning and of losing trades, as ``(how many, what they made)``, in order."""
    wins: list[tuple[int, float]] = []
    losses: list[tuple[int, float]] = []
    run_kind = 0  # 1 winning, -1 losing, 0 none
    count, amount = 0, 0.0
    for pnl in pnls:
        kind = 1 if pnl > 0 else -1 if pnl < 0 else 0
        if kind != run_kind:
            if run_kind == 1:
                wins.append((count, amount))
            elif run_kind == -1:
                losses.append((count, amount))
            run_kind, count, amount = kind, 0, 0.0
        if kind:
            count, amount = count + 1, amount + pnl
    if run_kind == 1:
        wins.append((count, amount))
    elif run_kind == -1:
        losses.append((count, amount))
    return wins, losses


def _sharpe(pnls: Sequence[float], capital: float | None) -> float | None:
    """The mean of the trades' returns over their spread, each return measured against the account at the time."""
    if capital is None or capital <= 0 or len(pnls) < 3:
        return None
    level, returns = capital, []
    for pnl in pnls:
        if level <= 0:
            return None
        returns.append(pnl / level)
        level += pnl
    mean = sum(returns) / len(returns)
    spread = math.sqrt(sum((r - mean) ** 2 for r in returns) / len(returns))
    return mean / spread if spread > 0 else None


def summarize(
    trades: Sequence[BacktestTrade],
    *,
    max_drawdown: float,
    max_drawdown_pct: float,
    drawdown_absolute: float = 0.0,
    capital: float | None = None,
) -> PerformanceSummary:
    """The figures of a performance report, worked out from the closed trades (oldest first).

    The drawdown is the account's business, not the trades': the replay measures it on its equity curve and
    the broker's report on the account's level, so it is handed in. ``capital`` is what the account held
    when the first of the trades was opened; it is only needed for the Sharpe ratio.
    """
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    net = sum(pnls)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0

    win_runs, loss_runs = _streaks(pnls)
    longest_win = max(win_runs, key=lambda r: (r[0], r[1]), default=(0, 0.0))
    longest_loss = max(loss_runs, key=lambda r: (r[0], -r[1]), default=(0, 0.0))
    richest_win = max(win_runs, key=lambda r: (r[1], r[0]), default=(0, 0.0))
    deepest_loss = min(loss_runs, key=lambda r: (r[1], -r[0]), default=(0, 0.0))

    durations = [max(0, t.exit_time - t.entry_time) for t in trades]
    longs = [t for t in trades if t.side == "BUY"]
    shorts = [t for t in trades if t.side == "SELL"]
    return PerformanceSummary(
        net_profit=net,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / len(trades) * 100) if trades else 0.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else None,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=(avg_win / avg_loss) if avg_loss > 0 and avg_win > 0 else None,
        largest_win=max(wins, default=0.0),
        largest_loss=min(losses, default=0.0),
        avg_trade=(net / len(trades)) if trades else 0.0,
        avg_duration=int(sum(durations) / len(trades)) if trades else 0,
        max_win_streak=longest_win[0],
        max_loss_streak=longest_loss[0],
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        recovery_factor=(net / max_drawdown) if max_drawdown > 0 else None,
        sharpe=_sharpe(pnls, capital),
        long_trades=len(longs),
        long_wins=sum(1 for t in longs if t.pnl > 0),
        short_trades=len(shorts),
        short_wins=sum(1 for t in shorts if t.pnl > 0),
        avg_win_streak=(sum(r[0] for r in win_runs) / len(win_runs)) if win_runs else 0.0,
        avg_loss_streak=(sum(r[0] for r in loss_runs) / len(loss_runs)) if loss_runs else 0.0,
        max_win_streak_amount=longest_win[1],
        max_loss_streak_amount=longest_loss[1],
        best_win_streak_amount=richest_win[1],
        best_win_streak_amount_trades=richest_win[0],
        worst_loss_streak_amount=deepest_loss[1],
        worst_loss_streak_amount_trades=deepest_loss[0],
        longest_duration=max(durations, default=0),
        shortest_duration=min(durations, default=0),
        total_volume=sum(t.volume for t in trades),
        commission=sum(getattr(t, "commission", 0.0) for t in trades),
        swap=sum(getattr(t, "swap", 0.0) for t in trades),
        fees=sum(getattr(t, "fee", 0.0) for t in trades),
        drawdown_absolute=drawdown_absolute,
    )


def symbol_stats(trades: Iterable[BacktestTrade]) -> list[SymbolStats]:
    """What each instrument made, the most profitable first."""
    by_symbol: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        by_symbol.setdefault(trade.symbol or "—", []).append(trade)
    rows = [
        SymbolStats(
            symbol=symbol,
            trades=len(group),
            wins=sum(1 for t in group if t.pnl > 0),
            losses=sum(1 for t in group if t.pnl < 0),
            win_rate=sum(1 for t in group if t.pnl > 0) / len(group) * 100,
            net_profit=sum(t.pnl for t in group),
            volume=sum(t.volume for t in group),
        )
        for symbol, group in by_symbol.items()
    ]
    return sorted(rows, key=lambda r: (-r.net_profit, r.symbol))


def thin_curve(points: Sequence[tuple[float, float]], limit: int = 400) -> list[EquityPoint]:
    """A curve (``(time, value)`` in time order) cut down to about ``limit`` points without losing its peaks and troughs."""
    if len(points) <= limit or limit < 4:
        return [EquityPoint(time=int(t), value=v) for t, v in points]

    # One high and one low per bucket, in time order, bracketed by the very first
    # and last points (the curve should start at the opening balance and end now).
    buckets = max(1, limit // 2)
    size = len(points) / buckets
    picked: list[tuple[float, float]] = []
    for b in range(buckets):
        chunk = list(points[int(b * size) : int((b + 1) * size)]) or [
            points[min(int(b * size), len(points) - 1)]
        ]
        lo = min(chunk, key=lambda p: p[1])
        hi = max(chunk, key=lambda p: p[1])
        picked.extend(sorted({id(lo): lo, id(hi): hi}.values(), key=lambda p: p[0]))
    if picked[0] is not points[0]:
        picked.insert(0, points[0])
    if picked[-1] is not points[-1]:
        picked.append(points[-1])
    return [EquityPoint(time=int(t), value=v) for t, v in picked]


# -- the broker's history -----------------------------------------------------------------------------
#: Deal kinds that are fills of orders.
_FILLS = {"buy", "sell"}
#: Operations on the balance that are money put in or taken out (or given), not trading and not its costs.
_MONEY_IN_OUT = {"balance", "credit", "bonus", "correction"}


@dataclass
class _Position:
    """A position being put together from its fills."""

    side: str
    symbol: str
    entry_time: int
    opened: float = 0.0
    open_volume: float = 0.0
    in_value: float = 0.0
    closed: float = 0.0
    out_value: float = 0.0
    exit_time: int = 0
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    comment: str = ""
    reason: str = ""
    exit_comment: str = ""

    def add_costs(self, deal: Deal) -> None:
        self.profit += deal.profit
        self.commission += deal.commission
        self.swap += deal.swap
        self.fee += deal.fee

    def close(self, ticket: int) -> ClosedTrade:
        entry = self.in_value / self.opened if self.opened > 0 else 0.0
        exit_ = self.out_value / self.closed if self.closed > 0 else entry
        return ClosedTrade(
            entry_time=self.entry_time,
            exit_time=self.exit_time or self.entry_time,
            side=self.side,  # type: ignore[arg-type]
            entry_price=entry,
            exit_price=exit_,
            volume=self.opened if self.opened > 0 else self.closed,
            pnl=self.profit + self.commission + self.swap + self.fee,
            reason=_reason(self.reason, self.exit_comment),
            ticket=ticket,
            symbol=self.symbol,
            profit=self.profit,
            commission=self.commission,
            swap=self.swap,
            fee=self.fee,
            comment=self.comment,
        )


def _reason(reason: str, comment: str) -> str:
    """Why a position ended, in the replay's words: ``sl``, ``tp``, ``manual`` ..., plus ``so`` (stopped out)."""
    if reason in ("sl", "tp", "so"):
        return reason
    # Orders sent through the program (and so everything its buttons do) come as the "expert" kind, with a comment of its own
    if reason in ("client", "mobile", "web") or (
        reason == "expert" and "cheaptrader" in comment.lower()
    ):
        return "manual"
    return reason or "manual"


def _effect(deal: Deal) -> float:
    """What a deal did to the balance (credit is separate money: it is not the balance)."""
    if deal.kind in ("credit", "canceled"):
        return 0.0
    return deal.profit + deal.commission + deal.swap + deal.fee


@dataclass
class History:
    """The broker's deals put together."""

    trades: list[ClosedTrade] = field(default_factory=list)
    #: Every deal that moved the balance, in time order: ``(time, what it did, whether it was money moved in or out)``.
    moves: list[tuple[int, float, bool]] = field(default_factory=list)
    flows: AccountFlows = field(default_factory=AccountFlows)
    #: What all of them did to the balance together.
    total_effect: float = 0.0
    deals: int = 0
    first_time: int = 0
    last_time: int = 0


def _ordered(deals: Iterable[Deal]) -> list[Deal]:
    return sorted(deals, key=lambda d: (d.time, d.time_msc, d.ticket))


def trades_from_deals(deals: Iterable[Deal], since: int = 0) -> History:
    """Put the broker's deals together: positions that are closed become trades, and every deal that moved the
    balance is noted, so that what it did can be followed (deposits and withdrawals apart from the rest).
    Money moved (``flows``) is counted from ``since`` on; everything else is the whole history, because a trade
    that closed in a period was opened before it, and the balance is only worked out right from all of it.

    A position's fills share its ``position_id``. It is opened by "in" deals and closed by "out" deals (a
    partial close and the rest of it are one position; so is a position that was added to). A position that
    still has volume is open and no trade yet: only what it has cost so far is counted. The fill that reverses a
    position on a netting account ("inout") closes the old one and opens the new one in a single deal.
    """
    history = History()
    open_positions: dict[int, _Position] = {}
    for deal in _ordered(deals):
        history.deals += 1
        history.first_time = history.first_time or deal.time
        history.last_time = max(history.last_time, deal.time)

        effect = _effect(deal)
        if deal.kind == "canceled":
            continue
        if deal.kind not in _FILLS:
            _note_operation(history, deal, effect, since)
            continue
        if effect:
            history.moves.append((deal.time, effect, False))
            history.total_effect += effect

        key = deal.position_id or deal.ticket
        volume = deal.volume
        side = "BUY" if deal.kind == "buy" else "SELL"
        position = open_positions.get(key)
        if deal.entry in ("out", "out_by", "inout"):
            if position is None:
                # Its opening is not in what the broker gave: all that is known is how it ended
                closes = "SELL" if side == "BUY" else "BUY"
                position = _Position(
                    side=closes,
                    symbol=deal.symbol,
                    entry_time=deal.time,
                    opened=volume,
                    open_volume=volume,
                    in_value=volume * deal.price,
                )
                open_positions[key] = position
            closing = min(volume, position.open_volume) if deal.entry == "inout" else volume
            position.add_costs(deal)
            position.closed += closing
            position.out_value += closing * deal.price
            position.open_volume -= closing
            position.exit_time = deal.time
            position.reason = deal.reason
            position.exit_comment = deal.comment
            if position.open_volume <= _EPS:
                history.trades.append(position.close(key))
                del open_positions[key]
                remainder = volume - closing
                if deal.entry == "inout" and remainder > _EPS:
                    # the reversal opens the other way with what is left
                    open_positions[key] = _Position(
                        side=side,
                        symbol=deal.symbol,
                        entry_time=deal.time,
                        opened=remainder,
                        open_volume=remainder,
                        in_value=remainder * deal.price,
                        comment=deal.comment,
                    )
        else:
            if position is None:
                position = open_positions[key] = _Position(
                    side=side, symbol=deal.symbol, entry_time=deal.time, comment=deal.comment
                )
            position.opened += volume
            position.open_volume += volume
            position.in_value += volume * deal.price
            position.add_costs(deal)
    history.trades.sort(key=lambda t: (t.exit_time, t.entry_time, t.ticket))
    return history


def _note_operation(history: History, deal: Deal, effect: float, since: int = 0) -> None:
    """An operation on the balance that is no fill: a deposit, a charge, a correction ..."""
    flows = history.flows
    if deal.time >= since:
        flows.operations += 1
        if deal.kind == "credit":
            flows.credit += deal.profit
        elif deal.kind == "balance":
            if deal.profit >= 0:
                flows.deposits += deal.profit
            else:
                flows.withdrawals += -deal.profit
        elif deal.kind == "bonus":
            flows.bonus += effect
        elif deal.kind == "correction":
            flows.corrections += effect
        else:  # fees, interest, dividends, taxes: what it costs to have the account
            flows.charges += effect
    if deal.kind == "credit":
        return
    if effect:
        history.moves.append((deal.time, effect, deal.kind in _MONEY_IN_OUT))
        history.total_effect += effect


def account_report(
    deals: Sequence[Deal],
    account: AccountInfo,
    *,
    now: int | None = None,
    points: int = 400,
    trade_limit: int = TRADE_LIMIT,
    since: int = 0,
) -> AccountReport:
    """The report of an account: its closed trades, the level of the account over time and the figures of both.

    Deposits and withdrawals are no part of the performance, so the curve, the drawdowns and the percentages
    leave them out. The curve starts at what the account held when it first began to trade (the money first
    put in), follows what trading did to it (fills, their costs and what the broker charged) and ends at where
    the open positions have it now. The history is what the terminal holds; the balance before it is worked out
    from the balance now, so a history that does not reach back to the first deposit still adds up.

    ``since`` (seconds, the broker's time) reports a period: the trades that closed from then on, the curve from the
    level the account stood at then, the drawdowns and percentages within the period, and the money that moved in it.
    """
    history = trades_from_deals(deals, since)
    # what the balance was before the first deal there is
    before = account.balance - history.total_effect

    # What the account held when trading began: the balance before the history, and the money put in before the first fill
    level = before
    first_trade_at: int | None = None
    start_time = history.first_time
    steps: list[tuple[int, float]] = []
    for moment, effect, money in history.moves:
        if first_trade_at is None and money:
            level += effect
            continue
        if first_trade_at is None:
            first_trade_at = moment
            start_time = moment
        if not money:
            steps.append((moment, effect))
    open_profit = account.profit

    # A period starts from where the account stood then: what happened before it has happened
    if since > 0 and steps:
        for moment, effect in steps:
            if moment >= since:
                break
            level += effect
        steps = [(moment, effect) for moment, effect in steps if moment >= since]
        start_time = max(start_time, since)
    start_level = level

    # The curve, and the drawdowns along it (a peak that a deposit would lift is never counted: deposits are left out)
    curve: list[tuple[float, float]] = []
    peak = level
    lowest = level
    worst, worst_pct = 0.0, 0.0
    if steps:
        curve.append((start_time, level))
    for moment, effect in steps:
        level += effect
        peak = max(peak, level)
        lowest = min(lowest, level)
        worst = max(worst, peak - level)
        if peak > 0:
            worst_pct = max(worst_pct, (peak - level) / peak * 100)
        if len(curve) > 1 and curve[-1][0] == moment:
            # several deals in one second: one point (the start stays)
            curve[-1] = (moment, level)
        else:
            curve.append((moment, level))
    final = level + open_profit
    if steps:
        end_time = max(now or 0, curve[-1][0])
        peak = max(peak, final)
        lowest = min(lowest, final)
        worst = max(worst, peak - final)
        if peak > 0:
            worst_pct = max(worst_pct, (peak - final) / peak * 100)
        if end_time > curve[-1][0] or open_profit:
            curve.append((end_time, final))

    trades = [t for t in history.trades if t.exit_time >= since] if since > 0 else history.trades
    summary = summarize(
        trades,
        max_drawdown=worst,
        max_drawdown_pct=worst_pct,
        drawdown_absolute=max(0.0, start_level - lowest),
        capital=start_level if start_level > 0 else None,
    )
    shown = trades[-trade_limit:] if trade_limit > 0 else []
    return AccountReport(
        account=account,
        summary=summary,
        equity=thin_curve(curve, points),
        trades=shown,
        trades_total=len(trades),
        symbols=symbol_stats(trades),
        flows=history.flows,
        initial_balance=start_level,
        return_pct=(summary.net_profit / start_level * 100) if start_level > 0 else None,
        open_profit=open_profit,
        deals=history.deals,
        first_time=history.first_time,
        last_time=history.last_time,
    )
