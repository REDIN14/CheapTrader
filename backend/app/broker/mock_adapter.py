"""Mock broker adapter.

Generates synthetic market data so the whole application can run without a
MetaTrader terminal. Useful for development, tests, and CI.

Its market *ticks* like a real one: ticks arrive at random (about ``tick_rate`` a
second), the price walks, and open positions are marked to it, so the live feed, the
floating profit and stops and targets that close positions all behave the way they do
against a broker. ``mock_tick_rate`` and ``mock_volatility`` in the settings turn it
into a quiet afternoon or a news spike.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from datetime import datetime, timezone

from app.broker.base import BrokerAdapter
from app.schemas import (
    TIMEFRAME_SECONDS,
    AccountInfo,
    Bar,
    Deal,
    ModifyOrderRequest,
    ModifyRequest,
    OrderRequest,
    OrderResult,
    OrderType,
    PendingOrder,
    Position,
    Symbol,
    Tick,
    Timeframe,
)
from app.trading import is_pending, levels_problem, price_problem, side_of

_TF_SECONDS = TIMEFRAME_SECONDS

_DEFAULT_SYMBOLS = [
    ("EURUSD", "Euro vs US Dollar", 5, 0.00001, 1.0850, 100_000.0),
    ("GBPUSD", "Great Britain Pound vs US Dollar", 5, 0.00001, 1.2650, 100_000.0),
    ("USDJPY", "US Dollar vs Japanese Yen", 3, 0.001, 149.50, 100_000.0),
    ("AUDUSD", "Australian Dollar vs US Dollar", 5, 0.00001, 0.6550, 100_000.0),
    ("USDCAD", "US Dollar vs Canadian Dollar", 5, 0.00001, 1.3600, 100_000.0),
    ("XAUUSD", "Gold vs US Dollar", 2, 0.01, 2350.0, 100.0),
    ("BTCUSD", "Bitcoin vs US Dollar", 2, 0.01, 63000.0, 1.0),
    ("US500", "S&P 500 Index", 2, 0.01, 5200.0, 1.0),
]

#: The spread of every mock instrument, in points.
_SPREAD_POINTS = 10
#: Price step per tick, as a share of the price, at volatility 1.
_STEP = 1.5e-5
#: A market left alone for longer than this does not replay the time it missed tick for tick.
_CATCH_UP_MS = 2000


class _Market:
    """The ticking price of one symbol.

    Not driven by a thread: it is brought up to date whenever somebody asks, from
    where it stood to now, so it costs nothing while nobody is looking.
    """

    def __init__(
        self, start: float, digits: int, point: float, rate: float, volatility: float, seed: int
    ) -> None:
        self._rng = random.Random(seed)
        self._digits = digits
        self._spread = _SPREAD_POINTS * point
        self._sigma = start * _STEP * volatility
        self._gap_ms = 1000.0 / max(rate, 0.1)
        self._mid = start
        self._point = point
        self._next_ms = 0.0
        self.ticks: deque[Tick] = deque(maxlen=20_000)

    def advance(self, now_ms: int) -> list[Tick]:
        """Make the ticks that happened up to ``now_ms``; returns the new ones."""
        if self._next_ms == 0.0:
            self._next_ms = float(now_ms)
        elif now_ms - self._next_ms > _CATCH_UP_MS:
            self._next_ms = float(now_ms - _CATCH_UP_MS)
        made: list[Tick] = []
        while self._next_ms <= now_ms:
            at = int(self._next_ms)
            if self.ticks and at <= self.ticks[-1].time_msc:
                at = self.ticks[-1].time_msc + 1
            self._mid = max(self._point, self._mid + self._rng.gauss(0, self._sigma))
            tick = Tick(
                time=at // 1000,
                bid=round(self._mid, self._digits),
                ask=round(self._mid + self._spread, self._digits),
                last=0.0,
                volume=0.0,
                time_msc=at,
            )
            self.ticks.append(tick)
            made.append(tick)
            self._next_ms += self._rng.expovariate(1.0 / self._gap_ms)
        return made

    def since(self, msc: int) -> list[Tick]:
        out: list[Tick] = []
        for tick in reversed(self.ticks):
            if tick.time_msc <= msc:
                break
            out.append(tick)
        out.reverse()
        return out


class MockAdapter(BrokerAdapter):
    name = "mock"

    def __init__(self, seed: int = 42, tick_rate: float = 8.0, volatility: float = 1.0) -> None:
        self._connected = False
        self._seed = seed
        self._rng = random.Random(seed)
        self._tick_rate = tick_rate
        self._volatility = volatility
        self._lock = threading.RLock()
        self._markets: dict[str, _Market] = {}
        self._anchors: dict[str, float] = {}
        self._positions: dict[int, Position] = {}
        self._orders: dict[int, PendingOrder] = {}
        self._next_ticket = 1000
        self._balance = 10_000.0
        #: The account's history: the money it was opened with, and every fill since (see get_deals).
        self._deals: list[Deal] = []
        self._deal_ticket = 0
        self._journal(kind="balance", profit=self._balance, comment="deposit")

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # -- market data -------------------------------------------------------
    def list_symbols(self) -> list[Symbol]:
        return [
            Symbol(
                name=name,
                description=desc,
                path="Mock",
                digits=digits,
                point=point,
                spread=_SPREAD_POINTS,
                trade_mode=4,
                visible=True,
                trade_contract_size=contract,
                # The mock pays every profit in dollars: one price step of one lot is worth step * contract.
                trade_tick_value=round(point * contract, 8),
                trade_tick_size=point,
                volume_min=0.01,
                volume_max=100.0,
                volume_step=0.01,
                trade_stops_level=0,
                currency_profit="USD",
            )
            for name, desc, digits, point, _, contract in _DEFAULT_SYMBOLS
        ]

    def _spec(self, symbol: str) -> tuple[int, float, float, float]:
        """(digits, point, base price, contract size) of a symbol."""
        for name, _, digits, point, price, contract in _DEFAULT_SYMBOLS:
            if name == symbol:
                return digits, point, price, contract
        return 5, 0.00001, 100.0, 100_000.0

    def _base_price(self, symbol: str) -> float:
        return self._spec(symbol)[2]

    def _digits(self, symbol: str) -> int:
        return self._spec(symbol)[0]

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        step = _TF_SECONDS[timeframe]
        base = self._base_price(symbol)
        digits = self._digits(symbol)

        if start is not None and end is not None:
            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())
            n = max(1, (end_ts - start_ts) // step)
            first_ts = start_ts
        else:
            end_ts = int(datetime.now(timezone.utc).timestamp())
            first_ts = end_ts - count * step
            n = count

        rng = random.Random(hash((symbol, timeframe.value, first_ts)) & 0xFFFFFFFF)
        bars: list[Bar] = []
        price = base
        for i in range(n):
            t = first_ts + i * step
            drift = math.sin(i / 40.0) * base * 0.0008
            change = rng.gauss(0, base * 0.0015) + drift
            open_ = price
            close = max(0.0001, open_ + change)
            high = max(open_, close) + abs(rng.gauss(0, base * 0.0006))
            low = min(open_, close) - abs(rng.gauss(0, base * 0.0006))
            bars.append(
                Bar(
                    time=t,
                    open=round(open_, digits),
                    high=round(high, digits),
                    low=round(low, digits),
                    close=round(close, digits),
                    tick_volume=rng.randint(50, 5000),
                    spread=10,
                )
            )
            price = close
        if bars and start is None:
            # The live price carries on from where the newest candles end.
            with self._lock:
                self._anchors.setdefault(symbol, bars[-1].close)
        return bars

    # -- the ticking market -------------------------------------------------
    def _market(self, symbol: str) -> _Market:
        market = self._markets.get(symbol)
        if market is None:
            digits, point, base, _ = self._spec(symbol)
            start = self._anchors.get(symbol, base)
            seed = (self._seed * 7919 + sum(map(ord, symbol))) & 0xFFFFFFFF
            market = _Market(start, digits, point, self._tick_rate, self._volatility, seed)
            self._markets[symbol] = market
        return market

    def _advance(self, symbol: str) -> _Market:
        """Bring one market up to date; stops and targets get their chance on every tick."""
        market = self._market(symbol)
        made = market.advance(int(time.time() * 1000))
        for tick in made:
            self._trigger_levels(symbol, tick)
        return market

    @staticmethod
    def _reached(order: PendingOrder, tick: Tick) -> bool:
        """A pending order fills when the market gets to its price."""
        if order.order_type is OrderType.BUY_LIMIT:
            return tick.ask <= order.price
        if order.order_type is OrderType.SELL_LIMIT:
            return tick.bid >= order.price
        if order.order_type is OrderType.BUY_STOP:
            return tick.ask >= order.price
        return tick.bid <= order.price

    def _journal(self, **fields) -> None:
        """Note a deal in the account's history (what the report is made from)."""
        self._deal_ticket += 1
        self._deals.append(Deal(ticket=self._deal_ticket, time=int(datetime.now(timezone.utc).timestamp()), **fields))

    def get_deals(self) -> list[Deal]:
        with self._lock:
            return [d.model_copy() for d in self._deals]

    def _fill(self, order: PendingOrder, tick: Tick) -> None:
        """The order becomes a position (with the order's number, as on MetaTrader). A limit order
        fills at its price, a stop order at whatever the market is by then."""
        self._orders.pop(order.ticket, None)
        is_buy = order.side == "BUY"
        market = tick.ask if is_buy else tick.bid
        limit = order.order_type in (OrderType.BUY_LIMIT, OrderType.SELL_LIMIT)
        self._positions[order.ticket] = Position(
            ticket=order.ticket,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            price_open=order.price if limit else market,
            price_current=tick.bid if is_buy else tick.ask,
            sl=order.sl,
            tp=order.tp,
            profit=0.0,
            time=int(datetime.now(timezone.utc).timestamp()),
            comment=order.comment,
        )
        position = self._positions[order.ticket]
        self._journal(
            kind=order.side.lower(), entry="in", position_id=order.ticket, order=order.ticket, symbol=order.symbol,
            volume=order.volume, price=position.price_open, comment=order.comment,
        )  # fmt: skip

    def _trigger_levels(self, symbol: str, tick: Tick) -> None:
        """What a broker's server does: fill a pending order when the market reaches its price, and
        close a position the moment its stop or target is touched."""
        for order in [o for o in self._orders.values() if o.symbol == symbol]:
            if self._reached(order, tick):
                self._fill(order, tick)
        for position in [p for p in self._positions.values() if p.symbol == symbol]:
            price = tick.bid if position.side == "BUY" else tick.ask
            if position.side == "BUY":
                sl_hit, tp_hit = bool(position.sl and price <= position.sl), bool(position.tp and price >= position.tp)
            else:
                sl_hit, tp_hit = bool(position.sl and price >= position.sl), bool(position.tp and price <= position.tp)
            if sl_hit or tp_hit:
                self._settle(position, price, "sl" if sl_hit else "tp")

    def _profit(self, position: Position, price: float) -> float:
        contract = self._spec(position.symbol)[3]
        direction = 1 if position.side == "BUY" else -1
        return round(direction * (price - position.price_open) * position.volume * contract, 2)

    def _settle(self, position: Position, price: float, reason: str = "client") -> None:
        self._positions.pop(position.ticket, None)
        profit = self._profit(position, price)
        self._balance += profit
        self._journal(
            kind="sell" if position.side == "BUY" else "buy", entry="out", position_id=position.ticket,
            order=position.ticket, symbol=position.symbol, volume=position.volume, price=price, profit=profit,
            reason=reason, comment="cheaptrader close" if reason == "client" else f"[{reason}]",
        )  # fmt: skip

    def _mark(self) -> None:
        """Value every open position at the current quote (and let waiting orders see the market)."""
        for symbol in {p.symbol for p in self._positions.values()} | {o.symbol for o in self._orders.values()}:
            self._advance(symbol)
        for order in self._orders.values():
            ticks = self._market(order.symbol).ticks
            if ticks:
                order.price_current = ticks[-1].ask if order.side == "BUY" else ticks[-1].bid
        for position in self._positions.values():
            ticks = self._market(position.symbol).ticks
            if not ticks:
                continue
            price = ticks[-1].bid if position.side == "BUY" else ticks[-1].ask
            position.price_current = price
            position.profit = self._profit(position, price)

    @staticmethod
    def _stops_problem(side: str, sl: float | None, tp: float | None, tick: Tick) -> str | None:
        """The broker's "Invalid stops": a stop sits on the losing side of the price, a target on the winning side."""
        if side == "BUY":
            if sl and sl >= tick.bid:
                return "Invalid stops"
            if tp and tp <= tick.bid:
                return "Invalid stops"
        else:
            if sl and sl <= tick.ask:
                return "Invalid stops"
            if tp and tp >= tick.ask:
                return "Invalid stops"
        return None

    def get_tick(self, symbol: str) -> Tick | None:
        with self._lock:
            market = self._advance(symbol)
            return market.ticks[-1] if market.ticks else None

    def ticks_since(self, symbol: str, msc: int) -> list[Tick]:
        """Every tick after ``msc`` (a millisecond timestamp), oldest first."""
        with self._lock:
            return self._advance(symbol).since(msc)

    def get_ticks(self, symbol: str, start: datetime, count: int = 1000) -> list[Tick]:
        base = self._base_price(symbol)
        digits = self._digits(symbol)
        rng = random.Random(hash((symbol, int(start.timestamp()))) & 0xFFFFFFFF)
        out: list[Tick] = []
        ts = int(start.timestamp())
        for i in range(count):
            mid = base + rng.gauss(0, base * 0.0004)
            half = base * 0.00005
            out.append(
                Tick(
                    time=ts + i,
                    bid=round(mid - half, digits),
                    ask=round(mid + half, digits),
                    last=round(mid, digits),
                    volume=1.0,
                    time_msc=(ts + i) * 1000,
                )
            )
        return out

    # -- account -----------------------------------------------------------
    def get_account(self) -> AccountInfo:
        with self._lock:
            self._mark()
            floating = round(sum(p.profit for p in self._positions.values()), 2)
            equity = round(self._balance + floating, 2)
            return AccountInfo(
                login=999999,
                server="Mock-Demo",
                currency="USD",
                balance=round(self._balance, 2),
                equity=equity,
                margin=0.0,
                margin_free=equity,
                profit=floating,
                leverage=100,
                name="Mock Trader",
                company="Mock Broker",
                trade_mode="demo",
                margin_mode="hedging",
                stop_out_mode="percent",
            )

    def get_positions(self, symbol: str | None = None) -> list[Position]:
        with self._lock:
            self._mark()
            positions = [p.model_copy() for p in self._positions.values()]
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    def get_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        with self._lock:
            self._mark()
            orders = [o.model_copy() for o in self._orders.values()]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    # -- trading -----------------------------------------------------------
    def _place_pending(self, request: OrderRequest, tick: Tick) -> OrderResult:
        """A limit or stop order: it waits, and fills when the market gets to its price."""
        assert request.order_type is not None
        if not request.price:
            return OrderResult(ok=False, retcode=10015, error="A pending order needs the price it waits for.")
        digits = self._digits(request.symbol)
        problem = price_problem(request.order_type, request.price, tick.bid, tick.ask, 0.0, digits) or levels_problem(
            side_of(request.order_type), request.price, request.sl, request.tp, 0.0, digits
        )
        if problem:
            return OrderResult(ok=False, retcode=10015, error=problem, comment=problem)
        ticket = self._next_ticket
        self._next_ticket += 1
        self._orders[ticket] = PendingOrder(
            ticket=ticket,
            symbol=request.symbol,
            side=side_of(request.order_type),  # type: ignore[arg-type]
            order_type=request.order_type,
            volume=request.volume,
            price=request.price,
            sl=request.sl or 0.0,
            tp=request.tp or 0.0,
            price_current=tick.ask if request.side == "BUY" else tick.bid,
            time=int(datetime.now(timezone.utc).timestamp()),
            comment=request.comment,
        )
        return OrderResult(
            ok=True, retcode=10009, order_id=ticket, volume=request.volume, price=request.price, comment="mock order placed"
        )

    def cancel_order(self, ticket: int) -> OrderResult:
        with self._lock:
            self._mark()  # it may have been filled a moment ago
            if self._orders.pop(ticket, None) is None:
                return OrderResult(ok=False, error=f"order {ticket} not found (it may just have been filled)")
            return OrderResult(ok=True, retcode=10009, order_id=ticket, comment="mock order removed")

    def modify_order(self, request: ModifyOrderRequest) -> OrderResult:
        with self._lock:
            self._mark()
            order = self._orders.get(request.ticket)
            if order is None:
                return OrderResult(ok=False, error=f"order {request.ticket} not found (it may just have been filled)")
            tick = self.get_tick(order.symbol)
            price = request.price or order.price
            sl = order.sl if request.sl is None else request.sl
            tp = order.tp if request.tp is None else request.tp
            if tick is not None:
                digits = self._digits(order.symbol)
                problem = price_problem(order.order_type, price, tick.bid, tick.ask, 0.0, digits) or levels_problem(
                    order.side, price, sl, tp, 0.0, digits
                )
                if problem:
                    return OrderResult(ok=False, retcode=10015, error=problem, comment=problem)
            order.price, order.sl, order.tp = price, sl, tp
            return OrderResult(ok=True, retcode=10009, order_id=order.ticket, price=price, comment="mock order changed")

    def place_order(self, request: OrderRequest) -> OrderResult:
        with self._lock:
            tick = self.get_tick(request.symbol)
            if tick is None:
                return OrderResult(ok=False, error=f"no tick for {request.symbol}")
            if is_pending(request.order_type):
                return self._place_pending(request, tick)
            problem = self._stops_problem(request.side, request.sl, request.tp, tick)
            if problem:
                return OrderResult(ok=False, retcode=10016, error=problem, comment=problem)
            price = request.price or (tick.ask if request.side == "BUY" else tick.bid)
            ticket = self._next_ticket
            self._next_ticket += 1
            self._positions[ticket] = Position(
                ticket=ticket,
                symbol=request.symbol,
                side=request.side,
                volume=request.volume,
                price_open=price,
                price_current=tick.bid if request.side == "BUY" else tick.ask,
                sl=request.sl or 0.0,
                tp=request.tp or 0.0,
                profit=0.0,
                time=int(datetime.now(timezone.utc).timestamp()),
                comment=request.comment,
            )
            self._journal(
                kind=request.side.lower(), entry="in", position_id=ticket, order=ticket, symbol=request.symbol,
                volume=request.volume, price=price, comment=request.comment,
            )  # fmt: skip
            self._mark()
            return OrderResult(
                ok=True,
                retcode=10009,
                order_id=ticket,
                deal_id=ticket,
                volume=request.volume,
                price=price,
                comment="mock fill",
            )

    def modify_position(self, request: ModifyRequest) -> OrderResult:
        with self._lock:
            pos = self._positions.get(request.ticket)
            if pos is None:
                return OrderResult(ok=False, error=f"position {request.ticket} not found")
            sl = pos.sl if request.sl is None else request.sl
            tp = pos.tp if request.tp is None else request.tp
            tick = self.get_tick(pos.symbol)
            problem = self._stops_problem(pos.side, sl, tp, tick) if tick else None
            if problem:
                return OrderResult(ok=False, retcode=10016, error=problem, comment=problem)
            pos.sl, pos.tp = sl, tp
            return OrderResult(ok=True, retcode=10009, order_id=request.ticket)

    def close_position(self, ticket: int) -> OrderResult:
        with self._lock:
            self._mark()
            pos = self._positions.get(ticket)
            if pos is None:
                return OrderResult(ok=False, error=f"position {ticket} not found")
            self._settle(pos, pos.price_current)
            return OrderResult(ok=True, retcode=10009, order_id=ticket, price=pos.price_current)
