"""MetaTrader 5 broker adapter.

Wraps the official ``MetaTrader5`` Python package. The package is Windows-only
and requires a running, logged-in MT5 terminal. Import is deferred so the rest
of the app can run without it installed.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.broker.base import BrokerAdapter, BrokerError
from app.config import Settings
from app.schemas import (
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
    TerminalInfo,
    Tick,
    Timeframe,
)
from app.trading import levels_problem, price_problem, side_of

logger = logging.getLogger(__name__)

#: Order refusals a person can do something about, in words that say what.
REFUSALS = {
    10027: (
        "Algo trading is switched off in the MetaTrader terminal. Click the Algo Trading button in "
        "its toolbar so that it turns green (or tick Tools > Options > Expert Advisors > Allow "
        "algorithmic trading), then try again."
    ),
    10026: "The broker has switched off automated trading for this account.",
}

#: A market order the broker re-quotes is asked for again at the new price, this many times in all.
MAX_ATTEMPTS = 3

# What MetaTrader's numbers mean (the values its documentation gives for DEAL_TYPE_*, DEAL_ENTRY_*, DEAL_REASON_*
# and the ACCOUNT_* modes), as the words the rest of the program uses.
_DEAL_TYPES = {
    0: "buy", 1: "sell", 2: "balance", 3: "credit", 4: "charge", 5: "correction", 6: "bonus",
    7: "commission", 8: "commission", 9: "commission", 10: "commission", 11: "commission",
    12: "interest", 13: "canceled", 14: "canceled", 15: "dividend", 16: "dividend", 17: "tax",
}  # fmt: skip
_DEAL_ENTRIES = {0: "in", 1: "out", 2: "inout", 3: "out_by"}
_DEAL_REASONS = {0: "client", 1: "mobile", 2: "web", 3: "expert", 4: "sl", 5: "tp", 6: "so", 7: "rollover", 8: "vmargin", 9: "split"}
_TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}
_MARGIN_MODES = {0: "netting", 1: "exchange", 2: "hedging"}
_STOP_OUT_MODES = {0: "percent", 1: "money"}
#: How far back the history is asked for (the terminal gives what it holds), and how far ahead of now: the broker's
#: clock may be hours ahead of UTC, and the answer must not stop short of the latest deal.
HISTORY_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)
HISTORY_AHEAD = timedelta(days=2)


def deal_from_mt5(d) -> Deal:
    """One line of MetaTrader's history (a ``TradeDeal``) as a ``Deal``."""
    kind = _DEAL_TYPES.get(int(d.type), "other")
    return Deal(
        ticket=int(d.ticket),
        position_id=int(getattr(d, "position_id", 0) or 0),
        order=int(getattr(d, "order", 0) or 0),
        time=int(d.time),
        time_msc=int(getattr(d, "time_msc", 0) or 0),
        kind=kind,
        entry=_DEAL_ENTRIES.get(int(getattr(d, "entry", 0) or 0), "") if kind in ("buy", "sell") else "",
        symbol=str(getattr(d, "symbol", "") or ""),
        volume=float(getattr(d, "volume", 0.0) or 0.0),
        price=float(getattr(d, "price", 0.0) or 0.0),
        profit=float(getattr(d, "profit", 0.0) or 0.0),
        commission=float(getattr(d, "commission", 0.0) or 0.0),
        swap=float(getattr(d, "swap", 0.0) or 0.0),
        fee=float(getattr(d, "fee", 0.0) or 0.0),
        reason=_DEAL_REASONS.get(int(getattr(d, "reason", 0) or 0), ""),
        comment=str(getattr(d, "comment", "") or ""),
        magic=int(getattr(d, "magic", 0) or 0),
    )

# MT5 timeframe constants, resolved lazily once the package is imported.
_TF_NAMES = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
    Timeframe.D1: "TIMEFRAME_D1",
    Timeframe.W1: "TIMEFRAME_W1",
    Timeframe.MN1: "TIMEFRAME_MN1",
}


def bars_from_rows(rows: list[list]) -> list[Bar]:
    """The bars ``MT5Adapter.bar_rows`` describes."""
    return [
        Bar(
            time=r[0],
            open=r[1],
            high=r[2],
            low=r[3],
            close=r[4],
            tick_volume=r[5],
            spread=r[6],
            real_volume=r[7],
        )
        for r in rows
    ]


class MT5Adapter(BrokerAdapter):
    name = "mt5"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mt5 = None
        self._connected = False

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise BrokerError(
                "MetaTrader5 package is not installed. Install with "
                "`uv sync --extra mt5` on Windows."
            ) from exc

        self._mt5 = mt5
        kwargs: dict = {}
        if self._settings.mt5_path:
            kwargs["path"] = self._settings.mt5_path
        if self._settings.mt5_login:
            kwargs["login"] = self._settings.mt5_login
            kwargs["password"] = self._settings.mt5_password
            kwargs["server"] = self._settings.mt5_server

        if not mt5.initialize(**kwargs):
            code, msg = mt5.last_error()
            raise BrokerError(f"MT5 initialize() failed: [{code}] {msg}")
        self._connected = True
        logger.info("Connected to MT5: %s", mt5.terminal_info())

    def disconnect(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def module(self):
        """The MetaTrader5 package itself, for the live feed's own calls."""
        self._require()
        return self._mt5

    # -- helpers -----------------------------------------------------------
    def _tf(self, timeframe: Timeframe):
        return getattr(self._mt5, _TF_NAMES[timeframe])

    def _require(self) -> None:
        if not self._connected or self._mt5 is None:
            raise BrokerError("MT5 adapter is not connected")

    # -- market data -------------------------------------------------------
    def list_symbols(self) -> list[Symbol]:
        self._require()
        raw = self._mt5.symbols_get()
        if raw is None:
            raise BrokerError(f"symbols_get() failed: {self._mt5.last_error()}")
        return [self._symbol(s) for s in raw]

    @staticmethod
    def _symbol(s) -> Symbol:
        """One of MetaTrader's symbol records as ours."""
        # What a losing tick costs is what sizing a position by its risk needs; fall back to the plain figure.
        tick_value = float(getattr(s, "trade_tick_value_loss", 0.0) or getattr(s, "trade_tick_value", 0.0) or 0.0)
        return Symbol(
            name=s.name,
            description=getattr(s, "description", "") or "",
            path=getattr(s, "path", "") or "",
            digits=int(getattr(s, "digits", 5)),
            point=float(getattr(s, "point", 0.00001)),
            spread=int(getattr(s, "spread", 0)),
            trade_mode=int(getattr(s, "trade_mode", 0)),
            visible=bool(getattr(s, "visible", True)),
            trade_contract_size=float(getattr(s, "trade_contract_size", 100_000.0)),
            trade_tick_value=tick_value,
            trade_tick_size=float(getattr(s, "trade_tick_size", 0.0) or 0.0),
            volume_min=float(getattr(s, "volume_min", 0.01) or 0.01),
            volume_max=float(getattr(s, "volume_max", 100.0) or 100.0),
            volume_step=float(getattr(s, "volume_step", 0.01) or 0.01),
            trade_stops_level=int(getattr(s, "trade_stops_level", 0) or 0),
            currency_profit=str(getattr(s, "currency_profit", "") or ""),
        )

    def get_symbol(self, name: str) -> Symbol | None:
        self._require()
        info = self._mt5.symbol_info(name)
        return None if info is None else self._symbol(info)

    def bar_rows(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[list]:
        """The bars as plain rows ``[time, open, high, low, close, tick_volume, spread, real_volume]``,
        oldest first. (What the reader process sends over its pipe: numbers are much cheaper to
        ship than a model each.)"""
        self._require()
        tf = self._tf(timeframe)
        if start is not None and end is not None:
            rates = self._mt5.copy_rates_range(symbol, tf, start, end)
        else:
            rates = self._mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None:
            raise BrokerError(f"copy_rates failed for {symbol}: {self._mt5.last_error()}")
        return [
            [
                int(r["time"]),
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
                int(r["tick_volume"]),
                int(r["spread"]),
                int(r["real_volume"]),
            ]
            for r in rates
        ]

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        return bars_from_rows(self.bar_rows(symbol, timeframe, count, start, end))

    def get_tick(self, symbol: str) -> Tick | None:
        self._require()
        t = self._mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        return Tick(
            time=int(t.time),
            bid=float(t.bid),
            ask=float(t.ask),
            last=float(getattr(t, "last", 0.0)),
            volume=float(getattr(t, "volume", 0.0)),
            time_msc=int(getattr(t, "time_msc", 0)),
            flags=int(getattr(t, "flags", 0)),
        )

    def get_ticks(self, symbol: str, start: datetime, count: int = 1000) -> list[Tick]:
        self._require()
        ticks = self._mt5.copy_ticks_from(symbol, start, count, self._mt5.COPY_TICKS_ALL)
        if ticks is None:
            raise BrokerError(f"copy_ticks_from failed for {symbol}: {self._mt5.last_error()}")
        return [
            Tick(
                time=int(t["time"]),
                bid=float(t["bid"]),
                ask=float(t["ask"]),
                last=float(t["last"]),
                volume=float(t["volume"]),
                time_msc=int(t["time_msc"]),
                flags=int(t["flags"]),
            )
            for t in ticks
        ]

    # -- account -----------------------------------------------------------
    def get_terminal(self) -> TerminalInfo:
        self._require()
        t = self._mt5.terminal_info()
        if t is None:
            raise BrokerError(f"terminal_info() failed: {self._mt5.last_error()}")
        a = self._mt5.account_info()
        folder = str(getattr(t, "path", "") or "")
        exe = ""
        for program in ("terminal64.exe", "terminal.exe"):
            if folder and os.path.isfile(os.path.join(folder, program)):
                exe = os.path.join(folder, program)
                break
        return TerminalInfo(
            connected=bool(t.connected),
            name=str(getattr(t, "name", "") or ""),
            company=str(getattr(t, "company", "") or ""),
            path=folder,
            exe=exe,
            data_path=str(getattr(t, "data_path", "") or ""),
            build=int(getattr(t, "build", 0) or 0),
            algo_trading=bool(getattr(t, "trade_allowed", True)),
            api_allowed=not bool(getattr(t, "tradeapi_disabled", False)),
            account_login=int(a.login) if a is not None else 0,
            account_server=str(a.server) if a is not None else "",
            account_trading=bool(a.trade_allowed) if a is not None else True,
            account_expert=bool(a.trade_expert) if a is not None else True,
        )

    def get_account(self) -> AccountInfo:
        self._require()
        a = self._mt5.account_info()
        if a is None:
            raise BrokerError(f"account_info() failed: {self._mt5.last_error()}")
        return AccountInfo(
            login=int(a.login),
            server=str(a.server),
            currency=str(a.currency),
            balance=float(a.balance),
            equity=float(a.equity),
            margin=float(a.margin),
            margin_free=float(a.margin_free),
            profit=float(a.profit),
            leverage=int(a.leverage),
            name=str(getattr(a, "name", "")),
            company=str(getattr(a, "company", "") or ""),
            credit=float(getattr(a, "credit", 0.0) or 0.0),
            margin_level=float(getattr(a, "margin_level", 0.0) or 0.0),
            margin_call_level=float(getattr(a, "margin_so_call", 0.0) or 0.0),
            stop_out_level=float(getattr(a, "margin_so_so", 0.0) or 0.0),
            stop_out_mode=_STOP_OUT_MODES.get(int(getattr(a, "margin_so_mode", 0) or 0), ""),
            trade_mode=_TRADE_MODES.get(int(getattr(a, "trade_mode", 0) or 0), ""),
            margin_mode=_MARGIN_MODES.get(int(getattr(a, "margin_mode", 0) or 0), ""),
            limit_orders=int(getattr(a, "limit_orders", 0) or 0),
            fifo_close=bool(getattr(a, "fifo_close", False)),
            currency_digits=int(getattr(a, "currency_digits", 2) or 2),
            assets=float(getattr(a, "assets", 0.0) or 0.0),
            liabilities=float(getattr(a, "liabilities", 0.0) or 0.0),
            commission_blocked=float(getattr(a, "commission_blocked", 0.0) or 0.0),
        )

    def get_deals(self) -> list[Deal]:
        """Every deal the terminal holds for the account, oldest first. (It holds what has been loaded into its
        History tab; choosing "All history" there makes it fetch the rest from the broker.)"""
        self._require()
        raw = self._mt5.history_deals_get(HISTORY_FROM, utcnow() + HISTORY_AHEAD)
        if raw is None:
            raise BrokerError(f"history_deals_get() failed: {self._mt5.last_error()}")
        return sorted((deal_from_mt5(d) for d in raw), key=lambda d: (d.time, d.time_msc, d.ticket))

    def get_positions(self, symbol: str | None = None, *, strict: bool = False) -> list[Position]:
        """Open positions. MetaTrader answers ``None`` when the call itself failed (as against an
        empty list when nothing is open); that reads as "no positions" unless ``strict``, which
        raises instead so a caller that acts on the difference (the live feed) can tell."""
        self._require()
        raw = self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()
        if raw is None:
            if strict:
                raise BrokerError(f"positions_get() failed: {self._mt5.last_error()}")
            return []
        out: list[Position] = []
        for p in raw:
            out.append(
                Position(
                    ticket=int(p.ticket),
                    symbol=str(p.symbol),
                    side="BUY" if int(p.type) == 0 else "SELL",
                    volume=float(p.volume),
                    price_open=float(p.price_open),
                    price_current=float(p.price_current),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    profit=float(p.profit),
                    time=int(p.time),
                    comment=str(getattr(p, "comment", "")),
                )
            )
        return out

    def _pending_kinds(self) -> dict[int, OrderType]:
        """MetaTrader's numbers for the kinds of pending order, as ours."""
        mt5 = self._mt5
        return {
            int(mt5.ORDER_TYPE_BUY_LIMIT): OrderType.BUY_LIMIT,
            int(mt5.ORDER_TYPE_SELL_LIMIT): OrderType.SELL_LIMIT,
            int(mt5.ORDER_TYPE_BUY_STOP): OrderType.BUY_STOP,
            int(mt5.ORDER_TYPE_SELL_STOP): OrderType.SELL_STOP,
        }

    def get_orders(self, symbol: str | None = None, *, strict: bool = False) -> list[PendingOrder]:
        """The pending (limit / stop) orders. As with the positions, MetaTrader answers ``None`` when the
        call itself failed (as against an empty list when nothing waits); ``strict`` raises on that."""
        self._require()
        raw = self._mt5.orders_get(symbol=symbol) if symbol else self._mt5.orders_get()
        if raw is None:
            if strict:
                raise BrokerError(f"orders_get() failed: {self._mt5.last_error()}")
            return []
        kinds = self._pending_kinds()
        out: list[PendingOrder] = []
        for o in raw:
            kind = kinds.get(int(o.type))
            if kind is None:
                continue  # stop-limit orders and the like are not something this app places or shows
            out.append(
                PendingOrder(
                    ticket=int(o.ticket),
                    symbol=str(o.symbol),
                    side=side_of(kind),  # type: ignore[arg-type]
                    order_type=kind,
                    volume=float(getattr(o, "volume_current", getattr(o, "volume_initial", 0.0))),
                    price=float(o.price_open),
                    sl=float(o.sl),
                    tp=float(o.tp),
                    price_current=float(getattr(o, "price_current", 0.0)),
                    time=int(getattr(o, "time_setup", 0)),
                    comment=str(getattr(o, "comment", "")),
                )
            )
        return out

    # -- trading -----------------------------------------------------------
    def _order_type(self, request: OrderRequest) -> int:
        mt5 = self._mt5
        if request.order_type is not None:
            mapping = {
                "BUY": mt5.ORDER_TYPE_BUY,
                "SELL": mt5.ORDER_TYPE_SELL,
                "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
                "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
                "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
                "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
            }
            return mapping[request.order_type.value]
        return mt5.ORDER_TYPE_BUY if request.side == "BUY" else mt5.ORDER_TYPE_SELL

    def _filling(self, symbol: str, market: bool = True) -> int:
        """The fill policy this instrument accepts: IOC if it can, else FOK, else return."""
        mt5 = self._mt5
        if not market:
            return mt5.ORDER_FILLING_RETURN
        info = mt5.symbol_info(symbol)
        allowed = int(getattr(info, "filling_mode", 0)) if info is not None else 0
        if allowed & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        if allowed & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _send(self, payload: dict, fresh_price: Callable[[], float | None] | None = None) -> OrderResult:
        """``order_send`` with the bookkeeping every trade call needs.

        A fast market answers some requests with "requote" or "price changed": the
        price asked for is gone. The terminal's own one-click trading asks again at
        the new price, and so does this, a couple of times, before giving up.
        Also reports how long the broker took, which is what a trader means by "slow".
        """
        mt5 = self._mt5
        retry_codes = {
            int(getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004)),
            int(getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020)),
            int(getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10021)),
        }
        started = time.perf_counter()
        result = None
        for attempt in range(MAX_ATTEMPTS):
            result = mt5.order_send(payload)
            if result is None or int(result.retcode) not in retry_codes or fresh_price is None:
                break
            price = fresh_price()
            if price is None or attempt == MAX_ATTEMPTS - 1:
                break
            payload["price"] = float(price)
        if (
            result is not None
            and payload.get("action") == mt5.TRADE_ACTION_PENDING
            and int(result.retcode) == int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030))
        ):
            # This instrument does not take the fill policy that was asked for: try the others.
            for fill in (mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC):
                if fill == payload.get("type_filling"):
                    continue
                payload["type_filling"] = fill
                result = mt5.order_send(payload)
                if result is None or int(result.retcode) != int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030)):
                    break
        latency = round((time.perf_counter() - started) * 1000)
        if result is None:
            return OrderResult(ok=False, error=str(mt5.last_error()), latency_ms=latency)
        good = {int(mt5.TRADE_RETCODE_DONE)}
        if payload.get("action") in (mt5.TRADE_ACTION_SLTP, getattr(mt5, "TRADE_ACTION_MODIFY", 7)):
            # Asking for the stop and target the position (or the order) already has is not a failure.
            good.add(int(getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)))
        ok = int(result.retcode) in good
        return OrderResult(
            ok=ok,
            retcode=int(result.retcode),
            order_id=int(getattr(result, "order", 0)),
            deal_id=int(getattr(result, "deal", 0)),
            volume=float(getattr(result, "volume", 0.0)),
            price=float(getattr(result, "price", 0.0)),
            comment=str(getattr(result, "comment", "")),
            error=None if ok else REFUSALS.get(int(result.retcode)) or str(getattr(result, "comment", "") or "order failed"),
            latency_ms=latency,
        )

    def place_order(self, request: OrderRequest) -> OrderResult:
        self._require()
        mt5 = self._mt5
        tick = mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return OrderResult(ok=False, error=f"no tick for {request.symbol}")

        order_type = self._order_type(request)
        is_market = order_type in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL)
        is_buy = order_type in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
        price = request.price
        if not is_market:
            if price is None:
                return OrderResult(ok=False, retcode=10015, error="A pending order needs the price it waits for.")
            problem = self._pending_problem(request.symbol, request.order_type, float(price), request.sl, request.tp)
            if problem:
                return OrderResult(ok=False, retcode=10015, error=problem, comment=problem)
        if price is None:
            price = tick.ask if is_buy else tick.bid

        payload = {
            "action": mt5.TRADE_ACTION_DEAL if is_market else mt5.TRADE_ACTION_PENDING,
            "symbol": request.symbol,
            "volume": request.volume,
            "type": order_type,
            "price": float(price),
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(request.symbol, is_market),
        }
        if request.sl:
            payload["sl"] = float(request.sl)
        if request.tp:
            payload["tp"] = float(request.tp)

        def fresh() -> float | None:
            # Only a market order takes whatever the price is now; a pending order
            # keeps the price it was asked for.
            if not is_market or request.price is not None:
                return None
            latest = mt5.symbol_info_tick(request.symbol)
            return None if latest is None else (latest.ask if is_buy else latest.bid)

        return self._send(payload, fresh)

    def modify_position(self, request: ModifyRequest) -> OrderResult:
        self._require()
        mt5 = self._mt5
        # A stop or target that is not mentioned keeps the value the position has:
        # left out of the request, MetaTrader would read it as "remove it".
        held = mt5.positions_get(ticket=request.ticket)
        if not held:
            return OrderResult(ok=False, error=f"position {request.ticket} not found")
        pos = held[0]
        payload = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": request.ticket,
            "symbol": pos.symbol,
            "sl": float(request.sl if request.sl is not None else pos.sl),
            "tp": float(request.tp if request.tp is not None else pos.tp),
        }
        return self._send(payload)

    def close_position(self, ticket: int) -> OrderResult:
        self._require()
        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return OrderResult(ok=False, error=f"position {ticket} not found")
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return OrderResult(ok=False, error=f"no tick for {pos.symbol}")
        is_buy = int(pos.type) == 0
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": float(pos.volume),
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if is_buy else tick.ask),
            "deviation": 20,
            "magic": 20261001,
            "comment": "cheaptrader close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(pos.symbol),
        }

        def fresh() -> float | None:
            latest = mt5.symbol_info_tick(pos.symbol)
            return None if latest is None else (latest.bid if is_buy else latest.ask)

        return self._send(payload, fresh)

    # -- pending orders ------------------------------------------------------
    def _pending_problem(
        self, symbol: str, order_type: OrderType | None, price: float, sl: float | None, tp: float | None
    ) -> str | None:
        """Why the broker would refuse this pending order (or its stop / target), in words, or None."""
        mt5 = self._mt5
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or order_type is None:
            return None  # the broker will say what is wrong
        info = mt5.symbol_info(symbol)
        digits = int(getattr(info, "digits", 5)) if info is not None else 5
        point = float(getattr(info, "point", 0.0) or 0.0) if info is not None else 0.0
        keep = int(getattr(info, "trade_stops_level", 0) or 0) * point if info is not None else 0.0
        return price_problem(order_type, price, float(tick.bid), float(tick.ask), keep, digits) or levels_problem(
            side_of(order_type), price, sl, tp, keep, digits
        )

    def cancel_order(self, ticket: int) -> OrderResult:
        self._require()
        mt5 = self._mt5
        if not mt5.orders_get(ticket=ticket):
            return OrderResult(ok=False, error=f"order {ticket} not found (it may just have been filled)")
        return self._send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})

    def modify_order(self, request: ModifyOrderRequest) -> OrderResult:
        self._require()
        mt5 = self._mt5
        held = mt5.orders_get(ticket=request.ticket)
        if not held:
            return OrderResult(ok=False, error=f"order {request.ticket} not found (it may just have been filled)")
        order = held[0]
        # What is not mentioned keeps the value the order has: left out of the request, MetaTrader
        # would read a stop or a target as "remove it".
        price = float(request.price) if request.price else float(order.price_open)
        sl = float(request.sl if request.sl is not None else order.sl)
        tp = float(request.tp if request.tp is not None else order.tp)
        problem = self._pending_problem(str(order.symbol), self._pending_kinds().get(int(order.type)), price, sl, tp)
        if problem:
            return OrderResult(ok=False, retcode=10015, error=problem, comment=problem)
        payload = {
            "action": getattr(mt5, "TRADE_ACTION_MODIFY", 7),
            "order": request.ticket,
            "symbol": str(order.symbol),
            "price": price,
            "sl": sl,
            "tp": tp,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        return self._send(payload)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
