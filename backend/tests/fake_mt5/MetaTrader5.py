"""A stand-in for the ``MetaTrader5`` package, so the feed and trading *processes* can be
tested without a terminal.

Each process that imports it sees the same world, because the world lives in a JSON file
named by ``FAKE_MT5_STATE`` (written atomically):

    {"rate": 100,               ticks a second the fake market produces
     "t0": 1700000000000,       when the fake market started (ms)
     "base": 1.10000,           price of tick 0; every tick is one ``step`` higher
     "step": 0.00001,
     "order_delay": 0.3,        how long ``order_send`` waits for the "broker"
     "requotes": 0,             the next N order_send calls answer "requote"
     "bars_delay": 0.0,         extra seconds every history read (bars, the symbol list) takes
     "algo_trading": true,      the terminal's Algo Trading switch (terminal_info().trade_allowed)
     "order_retcode": 0,        when set, order_send answers this retcode and does nothing (10027: algo trading off)
     "reject_fillings": [],     fill policies a pending order is refused for with 10030 (unsupported filling)
     "orders_fail": false,      orders_get() answers None, as when the call itself failed
     "terminal_running": true,  false: initialize() fails, as when MetaTrader is not open
     "logged_in": true,         false: the terminal is open but no account is logged in (account_info() is None)
     "stops_level": 0,          symbol_info().trade_stops_level
     "deals": [...],            the account's history, as history_deals_get() gives it (one dict of TradeDeal fields each)
     "deals_fail": false,       history_deals_get() answers None, as when the call itself failed
     "positions": [...], "account": {...}, "orders": [...], "pending": [...], "next_ticket": 1}

``orders`` is the log of every request ``order_send`` was given; ``pending`` holds the pending orders that wait.

Ticks are made up from the clock, so the same instant gives the same tick in every
process.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np

COPY_TICKS_ALL = -1
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408
TIMEFRAME_W1 = 32769
TIMEFRAME_MN1 = 49153

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_PRICE_CHANGED = 10020
TRADE_RETCODE_PRICE_OFF = 10021
TRADE_RETCODE_NO_CHANGES = 10025
TRADE_RETCODE_INVALID_FILL = 10030

_TICK_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("bid", "<f8"),
        ("ask", "<f8"),
        ("last", "<f8"),
        ("volume", "<u8"),
        ("time_msc", "<i8"),
        ("flags", "<u4"),
        ("volume_real", "<f8"),
    ]
)


class _Obj:
    """What the real package returns: a record read with attributes."""

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


def _path() -> str:
    return os.environ["FAKE_MT5_STATE"]


def _busy() -> None:
    """A terminal that someone else is working hard: every read takes a while."""
    time.sleep(float(os.environ.get("FAKE_MT5_CALL_DELAY", "0")))


def _history_busy() -> None:
    """The same, for the history reads only (bars and the symbol list): from the environment, or
    from ``bars_delay`` in the shared state, which a test can change while everything runs."""
    time.sleep(float(os.environ.get("FAKE_MT5_BARS_DELAY", "0")) + float(_load().get("bars_delay", 0)))


def _load() -> dict:
    with open(_path(), encoding="utf-8") as f:
        return json.load(f)


def _save(state: dict) -> None:
    tmp = f"{_path()}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    for _ in range(200):
        try:
            os.replace(tmp, _path())
            return
        except PermissionError:  # Windows: another process has the file open right now; try again
            time.sleep(0.005)
    os.replace(tmp, _path())


def _tick_at(state: dict, index: int) -> tuple:
    msc = int(state["t0"] + index * 1000.0 / state["rate"])
    bid = round(state["base"] + index * state["step"], 5)
    return msc, bid, round(bid + 0.00002, 5)


def _latest_index(state: dict) -> int:
    return max(0, int((time.time() * 1000 - state["t0"]) * state["rate"] / 1000.0))


# -- connection ----------------------------------------------------------------
def initialize(**_kwargs) -> bool:
    time.sleep(float(os.environ.get("FAKE_MT5_INIT_DELAY", "0")))  # a terminal busy with someone else's work
    return bool(_load().get("terminal_running", True))


def shutdown() -> None:
    pass


def last_error() -> tuple:
    if not _load().get("terminal_running", True):
        return (-10003, "IPC initialize failed, MetaTrader 5 x64 not found")
    return (1, "Success")


def terminal_info():
    state = _load()
    return _Obj(
        name="Fake MetaTrader 5",
        company="Fake Broker Ltd",
        path=os.path.dirname(os.environ["FAKE_MT5_STATE"]),
        data_path=os.path.dirname(os.environ["FAKE_MT5_STATE"]),
        build=1,
        connected=bool(state.get("logged_in", True)),
        ping_last=1000,
        trade_allowed=bool(state.get("algo_trading", True)),
        tradeapi_disabled=False,
    )


# -- symbols, bars and ticks -----------------------------------------------------------
_PERIOD = {1: 60, 5: 300, 15: 900, 30: 1800, 16385: 3600, 16388: 14400, 16408: 86400, 32769: 604800, 49153: 2592000}
_RATE_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<u8"),
        ("spread", "<i4"),
        ("real_volume", "<u8"),
    ]
)


def _rate(period: int, number: int) -> tuple:
    """Bar number ``number`` since the epoch: the same bar in every process."""
    base = round(1.1 + (number % 200) * 0.0001, 5)
    return (number * period, base, round(base + 0.0004, 5), round(base - 0.0003, 5), round(base + 0.0001, 5), 100 + number % 50, 2, 0)


def _known(symbol: str) -> bool:
    return symbol in _load().get("symbols", {"EURUSD": {}})


def _specification() -> dict:
    """What the terminal says a lot of this instrument is worth, and how it may be traded."""
    state = _load()
    return {
        "trade_tick_value": float(state.get("tick_value", 1.0)),
        "trade_tick_value_loss": float(state.get("tick_value_loss", state.get("tick_value", 1.0))),
        "trade_tick_size": 0.00001,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "trade_stops_level": int(state.get("stops_level", 0)),
        "currency_profit": "USD",
    }


def symbols_get(*_args, **_kwargs):
    _history_busy()
    known = _load().get("symbols", {"EURUSD": {"visible": True}})
    return tuple(
        _Obj(
            name=name,
            description=f"{name} (fake)",
            path=f"Forex\\{name}",
            digits=5,
            point=0.00001,
            spread=2,
            trade_mode=4,
            visible=bool(info.get("visible", True)),
            trade_contract_size=100000.0,
            **_specification(),
        )
        for name, info in known.items()
    )


def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int):
    _history_busy()
    if not _known(symbol) or timeframe not in _PERIOD:
        return None
    period = _PERIOD[timeframe]
    newest = int(time.time()) // period - start_pos  # the forming bar, counted back from "now"
    return np.array([_rate(period, n) for n in range(newest - count + 1, newest + 1)], dtype=_RATE_DTYPE)


def copy_rates_range(symbol: str, timeframe: int, date_from, date_to):
    _history_busy()
    if not _known(symbol) or timeframe not in _PERIOD:
        return None
    period = _PERIOD[timeframe]
    first = -(-int(date_from.timestamp()) // period)  # the first bar that opens at or after date_from
    last = min(int(date_to.timestamp()), int(time.time())) // period
    return np.array([_rate(period, n) for n in range(first, last + 1)], dtype=_RATE_DTYPE)


def symbol_info(symbol: str):
    state = _load()
    known = state.get("symbols", {"EURUSD": {"visible": True}})
    if symbol not in known:
        return None
    return _Obj(
        name=symbol,
        description=f"{symbol} (fake)",
        path=f"Forex\\{symbol}",
        visible=bool(known[symbol].get("visible", True)),
        filling_mode=3,
        digits=5,
        point=0.00001,
        spread=2,
        trade_mode=4,
        trade_contract_size=100000.0,
        **_specification(),
    )


def symbol_select(symbol: str, enable: bool = True) -> bool:
    state = _load()
    state.setdefault("symbols", {"EURUSD": {"visible": True}}).setdefault(symbol, {})["visible"] = bool(enable)
    _save(state)
    return True


def symbol_info_tick(symbol: str):
    state = _load()
    if symbol not in state.get("symbols", {"EURUSD": {}}) or not state["symbols"].get(symbol, {}).get("visible", True):
        return None
    msc, bid, ask = _tick_at(state, _latest_index(state))
    return _Obj(time=msc // 1000, bid=bid, ask=ask, last=0.0, volume=0, time_msc=msc, flags=6)


def copy_ticks_from(symbol: str, date_from, count: int, flags: int):
    _busy()
    state = _load()
    start_ms = int(date_from.timestamp() * 1000) if hasattr(date_from, "timestamp") else int(date_from) * 1000
    last = _latest_index(state)
    first = max(0, int((start_ms - state["t0"]) * state["rate"] / 1000.0) - 1)
    rows = []
    for index in range(first, last + 1):
        msc, bid, ask = _tick_at(state, index)
        if msc >= start_ms:
            rows.append((msc // 1000, bid, ask, 0.0, 0, msc, 6, 0.0))
        if len(rows) >= count:
            break
    return np.array(rows, dtype=_TICK_DTYPE)


# -- account and trading -----------------------------------------------------------------
def positions_get(**kwargs):
    _busy()
    state = _load()
    if state.get("positions_fail"):
        return None  # the call itself failed (as against: nothing is open)
    out = []
    for p in state.get("positions", []):
        if "ticket" in kwargs and p["ticket"] != kwargs["ticket"]:
            continue
        if "symbol" in kwargs and p["symbol"] != kwargs["symbol"]:
            continue
        out.append(_Obj(**p))
    return tuple(out)


def orders_get(**kwargs):
    """The pending orders (limit / stop) that wait."""
    _busy()
    state = _load()
    if state.get("orders_fail"):
        return None  # the call itself failed (as against: nothing waits)
    out = []
    for o in state.get("pending", []):
        if "ticket" in kwargs and o["ticket"] != kwargs["ticket"]:
            continue
        if "symbol" in kwargs and o["symbol"] != kwargs["symbol"]:
            continue
        out.append(_Obj(**o))
    return tuple(out)


def history_deals_get(date_from=None, date_to=None, **kwargs):
    """The account's history: the deals in the shared state that fall in the range."""
    _busy()
    state = _load()
    if state.get("deals_fail"):
        return None  # the call itself failed (as against: no deals)
    lo = date_from.timestamp() if hasattr(date_from, "timestamp") else date_from
    hi = date_to.timestamp() if hasattr(date_to, "timestamp") else date_to
    out = []
    for d in state.get("deals", []):
        if lo is not None and d["time"] < lo or hi is not None and d["time"] > hi:
            continue
        if "position" in kwargs and d.get("position_id") != kwargs["position"]:
            continue
        out.append(_Obj(**d))
    return tuple(out)


def account_info():
    state = _load()
    if not state.get("logged_in", True):
        return None
    acc = {"login": 1, "server": "Fake-Demo", "currency": "EUR", "balance": 1000.0, "equity": 1000.0,
           "margin": 0.0, "margin_free": 1000.0, "profit": 0.0, "leverage": 500, "name": "Fake",
           "trade_allowed": True, "trade_expert": True, "company": "Fake Broker Ltd", "credit": 0.0,
           "margin_level": 0.0, "margin_so_call": 70.0, "margin_so_so": 20.0, "margin_so_mode": 0,
           "trade_mode": 0, "margin_mode": 2, "limit_orders": 200, "fifo_close": False, "currency_digits": 2}
    acc.update(state.get("account", {}))
    return _Obj(**acc)


def order_send(request: dict):
    state = _load()
    time.sleep(float(state.get("order_delay", 0.0)))
    state = _load()  # the world may have moved on while "the broker" thought
    if state.get("order_retcode"):  # the terminal or the broker refuses, e.g. 10027: Algo Trading is off
        return _Obj(retcode=int(state["order_retcode"]), order=0, deal=0, volume=0.0, price=0.0, comment="refused")
    state.setdefault("orders", []).append(dict(request))
    if state.get("requotes", 0) > 0:
        state["requotes"] -= 1
        _save(state)
        return _Obj(retcode=TRADE_RETCODE_REQUOTE, order=0, deal=0, volume=0.0, price=0.0, comment="Requote")

    price = float(request.get("price", 0.0))
    action = request["action"]
    ticket = state.get("next_ticket", 1)
    if action == TRADE_ACTION_PENDING and request.get("type_filling") in state.get("reject_fillings", []):
        state["orders"].pop()  # a refused request is not a request that was carried out
        _save(state)
        return _Obj(retcode=TRADE_RETCODE_INVALID_FILL, order=0, deal=0, volume=0.0, price=0.0, comment="Unsupported filling mode")
    if action == TRADE_ACTION_PENDING:
        msc, bid, ask = _tick_at(state, _latest_index(state))
        state.setdefault("pending", []).append(
            {
                "ticket": ticket,
                "symbol": request["symbol"],
                "type": int(request["type"]),
                "volume_initial": float(request["volume"]),
                "volume_current": float(request["volume"]),
                "price_open": price,
                "price_current": ask if int(request["type"]) in (ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_BUY_STOP) else bid,
                "sl": float(request.get("sl", 0.0)),
                "tp": float(request.get("tp", 0.0)),
                "time_setup": msc // 1000,
                "comment": request.get("comment", ""),
            }
        )
        state["next_ticket"] = ticket + 1
    elif action == TRADE_ACTION_REMOVE:
        state["pending"] = [o for o in state.get("pending", []) if o["ticket"] != request["order"]]
    elif action == TRADE_ACTION_MODIFY:
        for o in state.get("pending", []):
            if o["ticket"] == request["order"]:
                o["price_open"] = float(request.get("price", o["price_open"]))
                o["sl"], o["tp"] = float(request.get("sl", 0.0)), float(request.get("tp", 0.0))
    elif action == TRADE_ACTION_SLTP:
        for p in state.get("positions", []):
            if p["ticket"] == request["position"]:
                p["sl"], p["tp"] = float(request.get("sl", 0.0)), float(request.get("tp", 0.0))
    elif action == TRADE_ACTION_DEAL and request.get("position"):
        state["positions"] = [p for p in state.get("positions", []) if p["ticket"] != request["position"]]
    else:
        msc, bid, _ask = _tick_at(state, _latest_index(state))
        state.setdefault("positions", []).append(
            {
                "ticket": ticket,
                "symbol": request["symbol"],
                "type": int(request["type"]),
                "volume": float(request["volume"]),
                "price_open": price,
                "price_current": bid,
                "sl": float(request.get("sl", 0.0)),
                "tp": float(request.get("tp", 0.0)),
                "profit": 0.0,
                "time": msc // 1000,
                "comment": request.get("comment", ""),
            }
        )
        state["next_ticket"] = ticket + 1
    _save(state)
    return _Obj(
        retcode=TRADE_RETCODE_DONE,
        order=ticket,
        deal=ticket,
        volume=float(request.get("volume", 0.0)),
        price=price,
        comment="Request executed",
    )
