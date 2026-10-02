"""Rules about orders that every broker adapter shares.

Which side of the market a pending order may sit on, and which side of its entry price a
stop and a target may sit on. A broker refuses anything else ("Invalid price", "Invalid
stops") in words that say little; checking first lets the app say what is wrong in plain
language, and the mock broker behaves like the real one.
"""

from __future__ import annotations

from app.schemas import OrderType

#: The kinds of order that wait for a price instead of trading at once.
PENDING = frozenset({OrderType.BUY_LIMIT, OrderType.SELL_LIMIT, OrderType.BUY_STOP, OrderType.SELL_STOP})

_NAMES = {
    OrderType.BUY: "buy",
    OrderType.SELL: "sell",
    OrderType.BUY_LIMIT: "buy limit",
    OrderType.SELL_LIMIT: "sell limit",
    OrderType.BUY_STOP: "buy stop",
    OrderType.SELL_STOP: "sell stop",
}


#: Prices are compared to this much: float noise must not turn "exactly the minimum distance" into a refusal.
_EPS = 1e-9


def is_pending(order_type: OrderType | None) -> bool:
    return order_type in PENDING


def side_of(order_type: OrderType) -> str:
    """"BUY" or "SELL"."""
    return "BUY" if order_type.value.startswith("BUY") else "SELL"


def name_of(order_type: OrderType) -> str:
    """The order in words: "buy limit"."""
    return _NAMES[order_type]


def price_problem(
    order_type: OrderType,
    price: float,
    bid: float,
    ask: float,
    min_distance: float = 0.0,
    digits: int = 5,
) -> str | None:
    """Why a pending order cannot wait at ``price`` while the market is ``bid`` / ``ask``, or None.

    A buy limit waits below the price you would buy at (the ask), a sell limit above the price
    you would sell at (the bid); stops are the other way round. Brokers also keep a minimum
    distance (``min_distance``, in price units) between the market and the order.
    """
    f = f"{{:.{digits}f}}"
    here = f.format(price)
    wording = name_of(order_type)
    # How far the order sits from the market, on the side it must be on (<= 0: at it or through it,
    # where it would simply trade, which is what a market order is for).
    if order_type is OrderType.BUY_LIMIT:
        gap, where, which, market = ask - price, "below", "buy price", ask
    elif order_type is OrderType.SELL_LIMIT:
        gap, where, which, market = price - bid, "above", "sell price", bid
    elif order_type is OrderType.BUY_STOP:
        gap, where, which, market = price - ask, "above", "buy price", ask
    elif order_type is OrderType.SELL_STOP:
        gap, where, which, market = bid - price, "below", "sell price", bid
    else:
        return None
    if _bad_gap(gap, min_distance):
        return _too_close(wording, where, which, f.format(market), here, min_distance, digits)
    return None


def _too_close(wording: str, where: str, which: str, market: str, here: str, min_distance: float, digits: int) -> str:
    kept = f", at least {min_distance:.{digits}f} away" if min_distance > 0 else ""
    return f"A {wording} has to be {where} the current {which} {market}{kept}; {here} is not."


def levels_problem(
    side: str,
    entry: float,
    sl: float | None,
    tp: float | None,
    min_distance: float = 0.0,
    digits: int = 5,
) -> str | None:
    """Why a stop loss / take profit cannot go with an order that enters at ``entry``, or None.

    A buy's stop is below its entry and its target above; a sell's the other way round.
    """
    f = f"{{:.{digits}f}}"
    here = f.format(entry)
    buy = side == "BUY"
    # The distance from the entry on the side each level belongs on (<= 0: on the wrong side or on it).
    if sl and _bad_gap((entry - sl) if buy else (sl - entry), min_distance):
        where = "below" if buy else "above"
        return f"The stop loss of a {side.lower()} has to be {where} its entry {here}{_kept(min_distance, digits)}; {f.format(sl)} is not."
    if tp and _bad_gap((tp - entry) if buy else (entry - tp), min_distance):
        where = "above" if buy else "below"
        return f"The take profit of a {side.lower()} has to be {where} its entry {here}{_kept(min_distance, digits)}; {f.format(tp)} is not."
    return None


def _bad_gap(gap: float, min_distance: float) -> bool:
    """A level is too close to the price it is measured from (or on the wrong side of it)."""
    return gap <= 0 or gap < min_distance - _EPS


def _kept(min_distance: float, digits: int) -> str:
    return f" by at least {min_distance:.{digits}f}" if min_distance > 0 else ""
