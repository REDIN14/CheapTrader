"""WebSocket endpoint streaming the live market to a screen.

A screen connects once and sends ``{"type": "subscribe", "symbol": "EURUSD"}``. From
then on the server pushes, as soon as the feed has them:

* ``{"type": "ticks", "symbol": "EURUSD", "data": [tick, ...]}``: every tick the
  terminal received since the last message, oldest first (a quiet market sends nothing,
  a busy one sends several at a time);
* ``{"type": "state", "positions": [...], "account": {...}, "orders": [...]}``: whenever a
  position, a pending order or the account changes, whoever caused it (this app, the terminal,
  a stop being hit, a limit order being filled);
* ``{"type": "feed", "status": "up" | "slow" | "restarting" | "down"}`` when the feed
  process has trouble (``slow``: MetaTrader is taking seconds to answer, prices are late);
* ``{"type": "pong", "t": ...}`` for a ``{"type": "ping", "t": ...}``, so a screen can
  measure the round trip.

See ``app/stream`` for where these come from.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.state import get_state
from app.stream.hub import MarketHub

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    hub: MarketHub | None = get_state().hub
    if hub is None:
        await websocket.close(code=1013)  # try again later: the server is still starting
        return
    channel = hub.attach()

    async def reader() -> None:
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")
            if kind == "subscribe" and msg.get("symbol"):
                symbol = str(msg["symbol"])
                channel.push_other({"type": "subscribed", "symbol": symbol})
                hub.subscribe(channel, symbol)
            elif kind == "ping":
                channel.push_other({"type": "pong", "t": msg.get("t")})

    async def writer() -> None:
        while True:
            for message in await channel.get():
                await websocket.send_text(json.dumps(message, separators=(",", ":")))

    def ended(task: asyncio.Task) -> None:
        # The reader is the half that usually observes a hang-up first. A client simply
        # leaving must not surface as an ASGI application error; anything else is logged.
        if task.cancelled():
            return
        outcome = task.exception()
        leaving = isinstance(outcome, (WebSocketDisconnect, ConnectionError))
        if outcome is not None and not leaving and not isinstance(outcome, RuntimeError):
            logger.warning("stream connection ended with %r", outcome)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    for task in tasks:
        task.add_done_callback(ended)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Nothing here awaits: if this handler is itself being cancelled (the server shutting
        # down), an await would raise again before the screen's subscription was let go,
        # leaving the feed following a symbol for nobody.
        hub.detach(channel)
        for task in tasks:
            task.cancel()
