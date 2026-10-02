"""Paper-trading engine for replay mode.

Simulates order execution against the replay cursor so a trader can practise
buying, selling, and managing SL/TP with realistic fills — without touching the
broker. Positions are marked to the current replay bar and closed when SL/TP is
hit or the trader closes them manually.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.schemas import (
    BacktestMetrics,
    BacktestTrade,
    Bar,
    EquityPoint,
    OrderRequest,
    OrderResult,
    Position,
    ReplayAccount,
    ReplaySummary,
)

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    ticket: int
    symbol: str
    side: str  # "BUY" | "SELL"
    volume: float
    price_open: float
    contract_size: float = 100_000.0
    sl: float = 0.0
    tp: float = 0.0
    time: int = 0
    comment: str = "replay"

    def to_position(self, current: float) -> Position:
        return Position(
            ticket=self.ticket,
            symbol=self.symbol,
            side=self.side,  # type: ignore[arg-type]
            volume=self.volume,
            price_open=self.price_open,
            price_current=current,
            sl=self.sl,
            tp=self.tp,
            profit=self.pnl(current),
            time=self.time,
            comment=self.comment,
        )

    def pnl(self, current: float) -> float:
        direction = 1.0 if self.side == "BUY" else -1.0
        return (current - self.price_open) * direction * self.volume * self.contract_size


@dataclass
class PaperTradingEngine:
    """In-memory paper account driven by the replay cursor."""

    symbol: str
    initial_balance: float = 10_000.0
    balance: float = 10_000.0
    contract_size: float = 100_000.0
    positions: dict[int, PaperPosition] = field(default_factory=dict)
    closed: list[BacktestTrade] = field(default_factory=list)
    _next_ticket: int = 1
    _equity_curve: list[dict[str, float]] = field(default_factory=list)
    # Running figures over the curve (see _record).
    _peak: float = 0.0
    _max_dd_value: float = 0.0
    _max_dd_pct: float = 0.0
    _ret_n: int = 0
    _ret_mean: float = 0.0
    _ret_m2: float = 0.0

    def __post_init__(self) -> None:
        self._peak = self.initial_balance

    # -- helpers -----------------------------------------------------------
    def _price(self, bar: Bar, side: str) -> float:
        """Fill at the bar close (a realistic, conservative replay fill)."""
        return bar.close

    def equity(self, current: float) -> float:
        return self.balance + sum(p.pnl(current) for p in self.positions.values())

    # -- trading -----------------------------------------------------------
    def place(self, request: OrderRequest, bar: Bar) -> OrderResult:
        price = self._price(bar, request.side)

        # Validate SL/TP against the entry, like a real broker would.
        if request.sl:
            if request.side == "BUY" and request.sl >= price:
                return OrderResult(
                    ok=False, error="invalid SL: must be below entry for a BUY"
                )
            if request.side == "SELL" and request.sl <= price:
                return OrderResult(
                    ok=False, error="invalid SL: must be above entry for a SELL"
                )
        if request.tp:
            if request.side == "BUY" and request.tp <= price:
                return OrderResult(
                    ok=False, error="invalid TP: must be above entry for a BUY"
                )
            if request.side == "SELL" and request.tp >= price:
                return OrderResult(
                    ok=False, error="invalid TP: must be below entry for a SELL"
                )

        ticket = self._next_ticket
        self._next_ticket += 1
        self.positions[ticket] = PaperPosition(
            ticket=ticket,
            symbol=request.symbol,
            side=request.side,
            volume=request.volume,
            price_open=price,
            contract_size=self.contract_size,
            sl=request.sl or 0.0,
            tp=request.tp or 0.0,
            time=bar.time,
            comment=request.comment,
        )
        return OrderResult(
            ok=True,
            retcode=10009,
            order_id=ticket,
            deal_id=ticket,
            volume=request.volume,
            price=price,
            comment="replay fill",
        )

    def modify(self, ticket: int, sl: float | None, tp: float | None) -> OrderResult:
        pos = self.positions.get(ticket)
        if pos is None:
            return OrderResult(ok=False, error=f"position {ticket} not found")
        if sl is not None:
            pos.sl = sl
        if tp is not None:
            pos.tp = tp
        return OrderResult(ok=True, retcode=10009, order_id=ticket)

    def close(self, ticket: int, bar: Bar) -> OrderResult:
        pos = self.positions.pop(ticket, None)
        if pos is None:
            return OrderResult(ok=False, error=f"position {ticket} not found")
        price = self._price(bar, "SELL" if pos.side == "BUY" else "BUY")
        pnl = pos.pnl(price)
        self.balance += pnl
        self.closed.append(
            BacktestTrade(
                entry_time=pos.time,
                exit_time=bar.time,
                side=pos.side,  # type: ignore[arg-type]
                entry_price=pos.price_open,
                exit_price=price,
                volume=pos.volume,
                pnl=pnl,
                reason="manual",
                ticket=pos.ticket,
            )
        )
        # Closing by hand changes the account without the cursor moving, so the curve
        # records it here (otherwise it would lag until the next bar).
        self._record(bar)
        return OrderResult(ok=True, retcode=10009, order_id=ticket, price=price)

    # -- per-bar processing ------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        """Check SL/TP against the bar's high/low and close hits."""
        for ticket in list(self.positions.keys()):
            pos = self.positions[ticket]
            hit_price: float | None = None
            reason = ""

            if pos.side == "BUY":
                if pos.sl and bar.low <= pos.sl:
                    hit_price, reason = pos.sl, "sl"
                elif pos.tp and bar.high >= pos.tp:
                    hit_price, reason = pos.tp, "tp"
            else:
                if pos.sl and bar.high >= pos.sl:
                    hit_price, reason = pos.sl, "sl"
                elif pos.tp and bar.low <= pos.tp:
                    hit_price, reason = pos.tp, "tp"

            if hit_price is not None:
                self.positions.pop(ticket, None)
                pnl = pos.pnl(hit_price)
                self.balance += pnl
                self.closed.append(
                    BacktestTrade(
                        entry_time=pos.time,
                        exit_time=bar.time,
                        side=pos.side,  # type: ignore[arg-type]
                        entry_price=pos.price_open,
                        exit_price=hit_price,
                        volume=pos.volume,
                        pnl=pnl,
                        reason=reason,
                        ticket=pos.ticket,
                    )
                )

        self._record(bar)

    def mark(self, bar: Bar) -> None:
        """Start the equity curve at the bar the replay begins on."""
        self._record(bar)

    def _record(self, bar: Bar) -> None:
        """Note the account's equity at ``bar``; a second note for the same bar replaces the first.

        The running figures (peak, worst drawdown, the mean and spread of the
        per-bar returns) are kept up to date here, so asking for the metrics after
        every bar of a fast replay does not mean walking the whole curve each time.
        A replaced note never changes the equity — every fill is at the bar's close,
        so closing a position moves money from "floating" to "realised", not the
        total — which is why the running figures need no correction for it.
        """
        value = self.equity(bar.close)
        point = {"time": float(bar.time), "value": value}
        if self._equity_curve and self._equity_curve[-1]["time"] == point["time"]:
            self._equity_curve[-1] = point
            return

        if self._equity_curve:
            previous = self._equity_curve[-1]["value"]
            if previous:
                self._count_return((value - previous) / previous)
        self._equity_curve.append(point)

        self._peak = max(self._peak, value)
        drawdown = self._peak - value
        self._max_dd_value = max(self._max_dd_value, drawdown)
        if self._peak > 0:
            self._max_dd_pct = max(self._max_dd_pct, drawdown / self._peak * 100)

    def _count_return(self, r: float) -> None:
        """Welford's running mean / variance of the per-bar returns."""
        self._ret_n += 1
        delta = r - self._ret_mean
        self._ret_mean += delta / self._ret_n
        self._ret_m2 += delta * (r - self._ret_mean)

    # -- reporting ---------------------------------------------------------
    def positions_view(self, current: float) -> list[Position]:
        return [p.to_position(current) for p in self.positions.values()]

    def _drawdown(self, equity: float) -> tuple[float, float]:
        """Worst drawdown so far as (value, percent), counting the account as it is now."""
        peak = max(self._peak, equity)
        value = max(self._max_dd_value, peak - equity)
        pct = max(self._max_dd_pct, (peak - equity) / peak * 100 if peak > 0 else 0.0)
        return value, pct

    def metrics(self, current: float) -> BacktestMetrics:
        equity = self.equity(current)
        wins = [t for t in self.closed if t.pnl > 0]
        losses = [t for t in self.closed if t.pnl < 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        _, max_dd = self._drawdown(equity)

        sharpe = 0.0
        if self._ret_n > 1:
            sd = (self._ret_m2 / self._ret_n) ** 0.5
            if sd > 0:
                sharpe = (self._ret_mean / sd) * (self._ret_n**0.5)

        return BacktestMetrics(
            initial_balance=self.initial_balance,
            final_balance=equity,
            total_return_pct=(equity - self.initial_balance) / self.initial_balance * 100,
            max_drawdown_pct=max_dd,
            sharpe=sharpe,
            win_rate=(len(wins) / len(self.closed) * 100) if self.closed else 0.0,
            trades=len(self.closed),
            profit_factor=(gross_win / gross_loss) if gross_loss > 0 else 0.0,
        )

    def account(self, current: float) -> ReplayAccount:
        """The account at the replay cursor: balance, equity, open positions, headline metrics."""
        unrealized = sum(p.pnl(current) for p in self.positions.values())
        return ReplayAccount(
            initial_balance=self.initial_balance,
            balance=self.balance,
            equity=self.balance + unrealized,
            realized=self.balance - self.initial_balance,
            unrealized=unrealized,
            positions=self.positions_view(current),
            metrics=self.metrics(current),
            trades_total=len(self.closed),
            wins=sum(1 for t in self.closed if t.pnl > 0),
            losses=sum(1 for t in self.closed if t.pnl < 0),
        )

    def summary(self, current: float) -> ReplaySummary:
        """The figures of a performance report (what TradingView calls the strategy overview)."""
        trades = self.closed
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]
        gross_profit = sum(wins)
        gross_loss = -sum(losses)
        net = sum(t.pnl for t in trades)
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0

        win_streak = loss_streak = best_win = best_loss = 0
        for t in trades:
            if t.pnl > 0:
                win_streak, loss_streak = win_streak + 1, 0
            elif t.pnl < 0:
                win_streak, loss_streak = 0, loss_streak + 1
            else:
                win_streak = loss_streak = 0
            best_win = max(best_win, win_streak)
            best_loss = max(best_loss, loss_streak)

        dd_value, dd_pct = self._drawdown(self.equity(current))
        return ReplaySummary(
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
            avg_duration=int(sum(t.exit_time - t.entry_time for t in trades) / len(trades))
            if trades
            else 0,
            max_win_streak=best_win,
            max_loss_streak=best_loss,
            max_drawdown=dd_value,
            max_drawdown_pct=dd_pct,
        )

    def equity_points(self, limit: int = 400) -> list[EquityPoint]:
        """The equity curve, thinned to about ``limit`` points without losing its peaks and troughs."""
        curve = self._equity_curve
        if len(curve) <= limit or limit < 4:
            return [EquityPoint(time=int(p["time"]), value=p["value"]) for p in curve]

        # One high and one low per bucket, in time order, bracketed by the very first
        # and last points (the curve should start at the opening balance and end now).
        buckets = max(1, limit // 2)
        size = len(curve) / buckets
        picked: list[dict[str, float]] = []
        for b in range(buckets):
            chunk = curve[int(b * size) : int((b + 1) * size)] or [curve[min(int(b * size), len(curve) - 1)]]
            lo = min(chunk, key=lambda p: p["value"])
            hi = max(chunk, key=lambda p: p["value"])
            picked.extend(sorted({id(lo): lo, id(hi): hi}.values(), key=lambda p: p["time"]))
        if picked[0] is not curve[0]:
            picked.insert(0, curve[0])
        if picked[-1] is not curve[-1]:
            picked.append(curve[-1])
        return [EquityPoint(time=int(p["time"]), value=p["value"]) for p in picked]

    def reset(self) -> None:
        self.balance = self.initial_balance
        self.positions.clear()
        self.closed.clear()
        self._equity_curve.clear()
        self._next_ticket = 1
        self._peak = self.initial_balance
        self._max_dd_value = 0.0
        self._max_dd_pct = 0.0
        self._ret_n = 0
        self._ret_mean = 0.0
        self._ret_m2 = 0.0
