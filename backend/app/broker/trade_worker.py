"""The MetaTrader worker: ``python -m app.broker.trade_worker [--role trader|reader]``.

Every call into MetaTrader's Python package holds Python's global lock for as long as
the terminal takes to answer. For an order that is the broker's time (the demo's ping
alone is 100 ms); for a read it is normally microseconds, but when something else is
working the terminal hard (another program pulling history through it) a read can take
seconds, and in the server that would freeze every price on every screen meanwhile.
Here it freezes nothing but this process, which has no other job.

The server runs two of these. The *trader* makes the orders; the *reader* answers
everything else the server asks the terminal (bars, symbols, ticks, the account, the
positions). They are separate so that a slow chart read never holds an order up.

The conversation with the server is JSON lines:

* the server's first line to us: ``{"settings": {...}}``; we answer ``{"type": "ready"}``
  once our own terminal session is up (or ``{"type": "fatal", "error": ...}``)
* requests: ``{"id": 7, "m": "place_order", "a": {...an OrderRequest...}}``; also
  ``modify_position`` (a ModifyRequest), ``close_position`` (``{"ticket": n}``),
  ``cancel_order`` (``{"ticket": n}``), ``modify_order`` (a ModifyOrderRequest), and the
  reads ``list_symbols``, ``get_symbol``, ``get_bars``, ``get_tick``, ``get_ticks``, ``get_account``,
  ``get_positions``, ``get_orders``, ``get_deals`` (the account's history), plus ``ping``
* answers: ``{"id": 7, "ok": true, "r": ...}`` or ``{"id": 7, "ok": false, "error": "..."}``

Requests are handled one at a time, in the order they arrive. When the server goes
away, its end of our stdin closes and we stop.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime


def when(value: str | None) -> datetime | None:
    """A moment sent as ISO text (the reads that take a range or a start)."""
    return datetime.fromisoformat(value) if value else None


def answer(adapter, method: str, args: dict):
    """Run one request on ``adapter``; what it returns is sent back (it has to be JSON)."""
    from app.schemas import ModifyOrderRequest, ModifyRequest, OrderRequest, Timeframe

    if method == "place_order":
        return adapter.place_order(OrderRequest(**args)).model_dump()
    if method == "modify_position":
        return adapter.modify_position(ModifyRequest(**args)).model_dump()
    if method == "close_position":
        return adapter.close_position(int(args["ticket"])).model_dump()
    if method == "cancel_order":
        return adapter.cancel_order(int(args["ticket"])).model_dump()
    if method == "modify_order":
        return adapter.modify_order(ModifyOrderRequest(**args)).model_dump()
    if method == "ping":
        return {}

    if method == "list_symbols":
        return [s.model_dump() for s in adapter.list_symbols()]
    if method == "get_bars":
        return adapter.bar_rows(
            args["symbol"],
            Timeframe(args["timeframe"]),
            count=int(args.get("count", 500)),
            start=when(args.get("start")),
            end=when(args.get("end")),
        )
    if method == "get_tick":
        tick = adapter.get_tick(args["symbol"])
        return None if tick is None else tick.model_dump()
    if method == "get_ticks":
        ticks = adapter.get_ticks(args["symbol"], when(args["start"]), int(args.get("count", 1000)))
        return [t.model_dump() for t in ticks]
    if method == "get_terminal":
        return adapter.get_terminal().model_dump()
    if method == "get_account":
        return adapter.get_account().model_dump()
    if method == "get_deals":
        return [d.model_dump() for d in adapter.get_deals()]
    if method == "get_positions":
        positions = adapter.get_positions(args.get("symbol"), strict=bool(args.get("strict")))
        return [p.model_dump() for p in positions]
    if method == "get_orders":
        orders = adapter.get_orders(args.get("symbol"), strict=bool(args.get("strict")))
        return [o.model_dump(mode="json") for o in orders]
    if method == "get_symbol":
        symbol = adapter.get_symbol(args["symbol"])
        return None if symbol is None else symbol.model_dump()
    raise ValueError(f"unknown request {method!r}")


def main() -> int:
    protocol = sys.stdout
    sys.stdout = sys.stderr  # anything printed by accident must not corrupt the protocol
    write_lock = threading.Lock()

    def emit(message: dict) -> None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        with write_lock:
            protocol.write(line)
            protocol.flush()

    try:
        init = json.loads(sys.stdin.readline())
        from app.broker.mt5_adapter import MT5Adapter
        from app.config import Settings

        adapter = MT5Adapter(Settings(_env_file=None, **init.get("settings", {})))
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        emit({"type": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        return 2

    emit({"type": "ready"})
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        ident = request.get("id")
        try:
            emit({"id": ident, "ok": True, "r": answer(adapter, request.get("m"), request.get("a") or {})})
        except Exception as exc:  # noqa: BLE001 - the server is waiting for an answer
            emit({"id": ident, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    adapter.disconnect()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
