"""REST API routes."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query

from app import __version__
from app.schemas import (
    AccountInfo,
    Bar,
    ModifyOrderRequest,
    ModifyRequest,
    OrderRequest,
    OrderResult,
    PendingOrder,
    Position,
    Symbol,
    Tick,
    Timeframe,
)
from app.state import get_state
from app.trading import is_pending, name_of, side_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["market"])


def _sync(state) -> None:
    """After a trade call: have the live feed read the positions and the account now.

    The screens hear about the new position (or the closed one, or the moved stop)
    from the feed within a few milliseconds, instead of at its next look.
    """
    if state.hub is not None:
        state.hub.kick()


def _log_trade(what: str, started: float, result: OrderResult) -> None:
    """One line per trade: what it was, how it ended, how long the broker and the whole call took."""
    total = round((time.perf_counter() - started) * 1000)
    outcome = "ok" if result.ok else f"REFUSED ({result.error})"
    logger.info("%s -> %s; broker %d ms, whole call %d ms", what, outcome, result.latency_ms, total)


@router.get("/health")
def health() -> dict:
    state = get_state()
    return {
        "status": "ok",
        "version": __version__,
        "broker": state.broker.adapter.name,
        "connected": state.broker.adapter.connected,
        "symbols": len(state.symbols),
        # "up" | "slow" | "restarting" | "down" | "starting": the live price feed from the terminal
        "feed": state.hub.feed_status if state.hub is not None else "off",
    }


@router.get("/data/stats")
def data_stats() -> list[dict]:
    """Coverage of the persistent bar store (per symbol/timeframe)."""
    return get_state().cache.store.stats()


@router.get("/symbols", response_model=list[Symbol])
def list_symbols(
    query: str | None = None,
    limit: int = Query(default=500, le=5000),
) -> list[Symbol]:
    state = get_state()
    if query:
        return state.symbols.search(query, limit=limit)
    return state.symbols.all()[:limit]


@router.get("/symbols/{name}", response_model=Symbol)
def get_symbol(name: str) -> Symbol:
    """One instrument as the broker describes it right now: its tick value moves with the exchange
    rates, so a position sized by its risk asks for this instead of the list read at start-up."""
    state = get_state()
    try:
        symbol = state.broker.adapter.get_symbol(name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"no symbol {name}")
    return symbol


@router.get("/bars", response_model=list[Bar])
def get_bars(
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    count: int = Query(default=500, le=100_000),
) -> list[Bar]:
    state = get_state()
    try:
        return state.cache.get_bars(state.broker.adapter, symbol, timeframe, count=count)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/tick", response_model=Tick)
def get_tick(symbol: str) -> Tick:
    state = get_state()
    tick = state.cache.get_tick(state.broker.adapter, symbol)
    if tick is None:
        raise HTTPException(status_code=404, detail=f"no tick for {symbol}")
    return tick


@router.get("/account", response_model=AccountInfo)
def get_account() -> AccountInfo:
    state = get_state()
    try:
        return state.broker.adapter.get_account()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/positions", response_model=list[Position])
def get_positions(symbol: str | None = None) -> list[Position]:
    state = get_state()
    return state.broker.adapter.get_positions(symbol)


def order_problem(request: OrderRequest) -> str | None:
    """What is wrong with the shape of an order before any market is looked at, in words."""
    kind = request.order_type
    if kind is None:
        return None
    if side_of(kind) != request.side:
        return f"A {name_of(kind)} is a {side_of(kind).lower()} order; the request says {request.side.lower()}."
    if is_pending(kind) and not (request.price and request.price > 0):
        return f"A {name_of(kind)} needs the price it waits for."
    return None


@router.post("/orders", response_model=OrderResult)
def place_order(request: OrderRequest) -> OrderResult:
    state = get_state()
    if not state.orders_allowed() and state.broker.adapter.name == "mt5":
        raise HTTPException(
            status_code=403,
            detail=(
                "Live orders are disabled: switch them on in the MetaTrader menu at the bottom right "
                "(or set CT_ALLOW_LIVE_ORDERS=true)."
            ),
        )
    problem = order_problem(request)
    if problem:
        return OrderResult(ok=False, retcode=10015, error=problem, comment=problem)
    started = time.perf_counter()
    result = state.broker.adapter.place_order(request)
    _sync(state)
    kind = name_of(request.order_type) if request.order_type else request.side
    _log_trade(f"{kind} {request.volume} {request.symbol}", started, result)
    return result


@router.get("/orders", response_model=list[PendingOrder])
def get_orders(symbol: str | None = None) -> list[PendingOrder]:
    """The pending (limit / stop) orders that are waiting."""
    return get_state().broker.adapter.get_orders(symbol)


@router.patch("/orders", response_model=OrderResult)
def modify_order(request: ModifyOrderRequest) -> OrderResult:
    """Move a pending order, or change its stop and target."""
    state = get_state()
    started = time.perf_counter()
    result = state.broker.adapter.modify_order(request)
    _sync(state)
    _log_trade(f"modify order {request.ticket} price={request.price} sl={request.sl} tp={request.tp}", started, result)
    return result


@router.delete("/orders/{ticket}", response_model=OrderResult)
def cancel_order(ticket: int) -> OrderResult:
    """Take a pending order back."""
    state = get_state()
    started = time.perf_counter()
    result = state.broker.adapter.cancel_order(ticket)
    _sync(state)
    _log_trade(f"cancel order {ticket}", started, result)
    return result


@router.patch("/positions", response_model=OrderResult)
def modify_position(request: ModifyRequest) -> OrderResult:
    state = get_state()
    started = time.perf_counter()
    result = state.broker.adapter.modify_position(request)
    _sync(state)
    _log_trade(f"modify {request.ticket} sl={request.sl} tp={request.tp}", started, result)
    return result


@router.delete("/positions/{ticket}", response_model=OrderResult)
def close_position(ticket: int) -> OrderResult:
    state = get_state()
    started = time.perf_counter()
    result = state.broker.adapter.close_position(ticket)
    _sync(state)
    _log_trade(f"close {ticket}", started, result)
    return result
