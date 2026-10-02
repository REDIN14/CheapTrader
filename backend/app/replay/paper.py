"""Paper-trading account for replay mode.

Simulates order execution against the replay cursor so a trader can practise
buying, selling, and managing SL/TP with realistic fills — without touching the
broker. Positions are marked to the current replay bar and closed when SL/TP is
hit or the trader closes them manually.

The account outlives a replay. It is a *profile* (see ``profiles.py``): a balance, the
history of every closed trade and a few running figures that carry on from one replay to
the next and across restarts. Only the equity curve belongs to one session (the stretch of
history being replayed). What happens to the positions still open when a session ends is
simple on purpose: a replay is a trip through time, and a position opened at one date has
no meaning at another, so they are closed where the cursor stood (``settle_all``) and the
result lands in the balance.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

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

#: A position's mark is saved to disk at most this often while the cursor moves.
_SAVE_EVERY = 2.0


@dataclass
class PaperPosition:
    ticket: int
    symbol: str
    side: str  # "BUY" | "SELL"
    volume: float
    price_open: float
    contract_size: float = 100_000.0
    #: What one price step is worth for one lot, in the account's currency (0: not known).
    tick_size: float = 0.0
    tick_value: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    time: int = 0
    comment: str = "replay"
    #: Where the position was last marked: the price and time of the newest bar it has seen. A
    #: session that is cut off (the app was closed) closes it there.
    mark_price: float = 0.0
    mark_time: int = 0

    def __post_init__(self) -> None:
        if not self.mark_price:
            self.mark_price = self.price_open
        if not self.mark_time:
            self.mark_time = self.time

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
        """Profit at ``current``, in the account's currency when the instrument's tick value is known
        (a yen pair or an index is not paid in dollars), else by contract size."""
        direction = 1.0 if self.side == "BUY" else -1.0
        move = (current - self.price_open) * direction
        if self.tick_size > 0 and self.tick_value > 0:
            return move / self.tick_size * self.tick_value * self.volume
        return move * self.volume * self.contract_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "price_open": self.price_open,
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "sl": self.sl,
            "tp": self.tp,
            "time": self.time,
            "comment": self.comment,
            "mark_price": self.mark_price,
            "mark_time": self.mark_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperPosition":
        return cls(
            ticket=int(data["ticket"]),
            symbol=str(data["symbol"]),
            side=str(data["side"]),
            volume=float(data["volume"]),
            price_open=float(data["price_open"]),
            contract_size=float(data.get("contract_size", 100_000.0)),
            tick_size=float(data.get("tick_size", 0.0)),
            tick_value=float(data.get("tick_value", 0.0)),
            sl=float(data.get("sl", 0.0)),
            tp=float(data.get("tp", 0.0)),
            time=int(data.get("time", 0)),
            comment=str(data.get("comment", "replay")),
            mark_price=float(data.get("mark_price", 0.0)),
            mark_time=int(data.get("mark_time", 0)),
        )


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


@dataclass
class PaperTradingEngine:
    """A paper account driven by the replay cursor.

    On its own (the engine's default) it lives in memory and is gone with the replay. Handed out by
    the profile store it also has an ``id`` and a ``name`` and tells the store whenever it changes
    (``on_change``), so the balance, the history and the positions survive.
    """

    symbol: str = ""
    initial_balance: float = 10_000.0
    balance: float | None = None
    contract_size: float = 100_000.0
    tick_size: float = 0.0
    tick_value: float = 0.0
    # -- which profile this is (empty for an account that is not kept)
    profile_id: str = ""
    name: str = ""
    created_at: int = 0
    updated_at: int = 0
    #: Order of creation (the profile list keeps it, even for two made in the same second).
    seq: int = 0
    positions: dict[int, PaperPosition] = field(default_factory=dict)
    closed: list[BacktestTrade] = field(default_factory=list)
    on_change: Callable[["PaperTradingEngine"], None] | None = field(default=None, repr=False, compare=False)
    _next_ticket: int = 1
    #: The equity of this session only: it starts where the replay starts.
    _equity_curve: list[dict[str, float]] = field(default_factory=list)
    # Running figures over the curves of every session (see _record); they are kept with the profile.
    _peak: float = 0.0
    _max_dd_value: float = 0.0
    _max_dd_pct: float = 0.0
    _ret_n: int = 0
    _ret_mean: float = 0.0
    _ret_m2: float = 0.0
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)
    _saved_at: float = field(default=0.0, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.balance is None:
            self.balance = self.initial_balance
        self._peak = max(self.initial_balance, self.balance)

    # -- keeping it ----------------------------------------------------------
    def _changed(self) -> None:
        """Tell whoever keeps this account that it changed (call with the lock held)."""
        self.updated_at = int(time.time())
        self._saved_at = time.monotonic()
        if self.on_change is None:
            return
        try:
            self.on_change(self)
        except Exception:  # noqa: BLE001 - a full disk must not stop the replay
            logger.exception("could not keep paper account %r", self.name or self.profile_id)

    def _changed_if_due(self) -> None:
        """A moving cursor changes the marks all the time: keep them every couple of seconds."""
        if self.positions and time.monotonic() - self._saved_at >= _SAVE_EVERY:
            self._changed()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": 1,
                "id": self.profile_id,
                "name": self.name,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "seq": self.seq,
                "initial_balance": self.initial_balance,
                "balance": self.balance,
                "next_ticket": self._next_ticket,
                "stats": {
                    "peak": self._peak,
                    "max_dd_value": self._max_dd_value,
                    "max_dd_pct": self._max_dd_pct,
                    "ret_n": self._ret_n,
                    "ret_mean": self._ret_mean,
                    "ret_m2": self._ret_m2,
                },
                "positions": [p.to_dict() for p in self.positions.values()],
                "trades": [t.model_dump() for t in self.closed],
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperTradingEngine":
        """Rebuild an account from what ``to_dict`` wrote. Raises ``ValueError`` if it makes no sense."""
        try:
            initial = float(data["initial_balance"])
            balance = float(data["balance"])
            if not (math.isfinite(initial) and math.isfinite(balance)) or initial <= 0:
                raise ValueError("the balance is not a number")
            engine = cls(
                initial_balance=initial,
                balance=balance,
                profile_id=str(data.get("id", "")),
                name=str(data.get("name", "")),
                created_at=int(data.get("created_at", 0)),
                updated_at=int(data.get("updated_at", 0)),
                seq=int(data.get("seq", 0)),
            )
            engine.positions = {
                int(p["ticket"]): PaperPosition.from_dict(p) for p in data.get("positions", [])
            }
            engine.closed = [BacktestTrade(**t) for t in data.get("trades", [])]
            highest = max([0] + list(engine.positions) + [t.ticket for t in engine.closed])
            engine._next_ticket = max(int(data.get("next_ticket", 1)), highest + 1)
            stats = data.get("stats", {}) or {}
            engine._peak = max(_finite(stats.get("peak"), initial), balance)
            engine._max_dd_value = max(0.0, _finite(stats.get("max_dd_value")))
            engine._max_dd_pct = max(0.0, _finite(stats.get("max_dd_pct")))
            engine._ret_n = max(0, int(_finite(stats.get("ret_n"))))
            engine._ret_mean = _finite(stats.get("ret_mean"))
            engine._ret_m2 = max(0.0, _finite(stats.get("ret_m2")))
            return engine
        except (KeyError, TypeError) as exc:
            raise ValueError(f"not a paper account: {exc}") from exc

    # -- helpers -----------------------------------------------------------
    def _price(self, bar: Bar, side: str) -> float:
        """Fill at the bar close (a realistic, conservative replay fill)."""
        return bar.close

    def equity(self, current: float) -> float:
        return self.balance + sum(p.pnl(current) for p in list(self.positions.values()))

    def _trade(self, pos: PaperPosition, exit_time: int, exit_price: float, pnl: float, reason: str) -> BacktestTrade:
        # A broker books profit in cents. The balance lives for good in the profile, so it is kept free
        # of the float dust that thousands of additions would otherwise pile up.
        pnl = round(pnl, 2)
        trade = BacktestTrade(
            entry_time=pos.time,
            exit_time=exit_time,
            side=pos.side,  # type: ignore[arg-type]
            entry_price=pos.price_open,
            exit_price=exit_price,
            volume=pos.volume,
            pnl=pnl,
            reason=reason,
            ticket=pos.ticket,
            symbol=pos.symbol,
        )
        self.balance = round(self.balance + pnl, 2)
        self.closed.append(trade)
        return trade

    # -- sessions ------------------------------------------------------------
    def begin_session(
        self,
        bar: Bar,
        *,
        symbol: str,
        contract_size: float | None = None,
        tick_size: float = 0.0,
        tick_value: float = 0.0,
        reason: str = "session",
    ) -> list[BacktestTrade]:
        """A replay starts (or the cursor was moved back) at ``bar``, on ``symbol``.

        The balance, the history and the running figures stay. Positions still open are closed at the
        price they were last marked at; the equity curve starts again from here.
        """
        with self._lock:
            leftovers = self.settle_all(None, reason)
            self.symbol = symbol
            if contract_size:
                self.contract_size = contract_size
            self.tick_size, self.tick_value = tick_size, tick_value
            self.restart_curve(bar)
            self._changed()
            return leftovers

    def settle_all(self, bar: Bar | None, reason: str = "session") -> list[BacktestTrade]:
        """Close every open position: at ``bar``'s close, or where each was last marked (``bar`` None)."""
        with self._lock:
            made: list[BacktestTrade] = []
            for ticket in list(self.positions):
                pos = self.positions.pop(ticket)
                if bar is not None:
                    price, when = bar.close, bar.time
                else:
                    price, when = pos.mark_price, max(pos.mark_time, pos.time)
                made.append(self._trade(pos, when, price, pos.pnl(price), reason))
            if made:
                self._changed()
            return made

    def restart_curve(self, bar: Bar) -> None:
        """Start this session's equity curve at ``bar`` (the running figures carry on)."""
        with self._lock:
            self._equity_curve.clear()
            self._record(bar)

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

        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            self.positions[ticket] = PaperPosition(
                ticket=ticket,
                symbol=request.symbol,
                side=request.side,
                volume=request.volume,
                price_open=price,
                contract_size=self.contract_size,
                tick_size=self.tick_size,
                tick_value=self.tick_value,
                sl=request.sl or 0.0,
                tp=request.tp or 0.0,
                time=bar.time,
                comment=request.comment,
                mark_price=price,
                mark_time=bar.time,
            )
            self._changed()
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
        with self._lock:
            pos = self.positions.get(ticket)
            if pos is None:
                return OrderResult(ok=False, error=f"position {ticket} not found")
            if sl is not None:
                pos.sl = sl
            if tp is not None:
                pos.tp = tp
            self._changed()
        return OrderResult(ok=True, retcode=10009, order_id=ticket)

    def close(self, ticket: int, bar: Bar) -> OrderResult:
        with self._lock:
            pos = self.positions.pop(ticket, None)
            if pos is None:
                return OrderResult(ok=False, error=f"position {ticket} not found")
            price = self._price(bar, "SELL" if pos.side == "BUY" else "BUY")
            self._trade(pos, bar.time, price, pos.pnl(price), "manual")
            # Closing by hand changes the account without the cursor moving, so the curve
            # records it here (otherwise it would lag until the next bar).
            self._record(bar)
            self._changed()
        return OrderResult(ok=True, retcode=10009, order_id=ticket, price=price)

    # -- per-bar processing ------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        """Check SL/TP against the bar's high/low and close hits."""
        with self._lock:
            closed_before = len(self.closed)
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
                    self._trade(pos, bar.time, hit_price, pos.pnl(hit_price), reason)
                else:
                    pos.mark_price, pos.mark_time = bar.close, bar.time

            self._record(bar)
            if len(self.closed) != closed_before:
                self._changed()
            else:
                self._changed_if_due()

    def mark(self, bar: Bar) -> None:
        """Note the account's equity at the bar the replay is on."""
        with self._lock:
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
        return [p.to_position(current) for p in list(self.positions.values())]

    def _drawdown(self, equity: float) -> tuple[float, float]:
        """Worst drawdown so far as (value, percent), counting the account as it is now."""
        peak = max(self._peak, equity)
        value = max(self._max_dd_value, peak - equity)
        pct = max(self._max_dd_pct, (peak - equity) / peak * 100 if peak > 0 else 0.0)
        return value, pct

    def metrics(self, current: float) -> BacktestMetrics:
        equity = self.equity(current)
        closed = list(self.closed)
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl < 0]
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
            win_rate=(len(wins) / len(closed) * 100) if closed else 0.0,
            trades=len(closed),
            profit_factor=(gross_win / gross_loss) if gross_loss > 0 else 0.0,
        )

    def account(self, current: float) -> ReplayAccount:
        """The account at the replay cursor: balance, equity, open positions, headline metrics."""
        closed = list(self.closed)
        unrealized = sum(p.pnl(current) for p in list(self.positions.values()))
        return ReplayAccount(
            initial_balance=self.initial_balance,
            balance=self.balance,
            equity=self.balance + unrealized,
            realized=round(self.balance - self.initial_balance, 2),
            unrealized=unrealized,
            positions=self.positions_view(current),
            metrics=self.metrics(current),
            trades_total=len(closed),
            wins=sum(1 for t in closed if t.pnl > 0),
            losses=sum(1 for t in closed if t.pnl < 0),
            profile_id=self.profile_id,
            profile_name=self.name,
        )

    def summary(self, current: float) -> ReplaySummary:
        """The figures of a performance report (what TradingView calls the strategy overview)."""
        trades = list(self.closed)
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
            avg_duration=int(sum(max(0, t.exit_time - t.entry_time) for t in trades) / len(trades))
            if trades
            else 0,
            max_win_streak=best_win,
            max_loss_streak=best_loss,
            max_drawdown=dd_value,
            max_drawdown_pct=dd_pct,
        )

    def equity_points(self, limit: int = 400) -> list[EquityPoint]:
        """The equity curve, thinned to about ``limit`` points without losing its peaks and troughs."""
        curve = list(self._equity_curve)
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

    def reset(self, balance: float | None = None) -> None:
        """Start the account over: no positions, no history, the balance back to what it began with
        (or to ``balance``, which then is what it begins with)."""
        with self._lock:
            if balance is not None:
                self.initial_balance = balance
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
            self._changed()
