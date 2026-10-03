"""The MetaTrader terminal as the app sees it, and the few things a user can do about it.

* ``GET  /api/terminal``          what is connected, whether it will take orders, its window, the terminals found
  (installed, running) and whether the app could connect to one right now;
* ``POST /api/terminal/connect``  the app began without MetaTrader (on the synthetic market) and a terminal is
  ready now: connect to it, without restarting;
* ``POST /api/terminal/window``   hide or show the terminal's window (remembered);
* ``POST /api/terminal/choose``   pick which installed terminal to use the next time the app starts;
* ``POST /api/app/orders``        switch on (or off) sending orders to the broker from the app (remembered);
* ``POST /api/app/window``        a second start of the program says a window is about to open on this copy (it
  stays for it, and says no when it is already ending);
* ``POST /api/app/quit``          stop the packaged program (``CheapTrader.exe``), and close its window.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app import __version__, paths, terminals
from app.preferences import preferences
from app.schemas import TerminalInfo
from app.state import get_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["terminal"])

#: Set by the packaged program: stops it. None while developing.
quit_hook: Callable[[], None] | None = None
#: Set by the packaged program: closes its window (Quit ends the program, so its window goes too).
window_closer: Callable[[], None] | None = None
#: Set by the packaged program: a window is about to open on this copy. True: it stays for it; False: it is ending.
window_hook: Callable[[], bool] | None = None

_scan: tuple[float, list[terminals.Terminal]] = (0.0, [])
SCAN_TTL = 10.0


def _detected() -> list[terminals.Terminal]:
    """The terminals installed or running (looked up at most every few seconds)."""
    global _scan
    if time.monotonic() - _scan[0] > SCAN_TTL:
        _scan = (time.monotonic(), terminals.detect())
    return _scan[1]


class WindowRequest(BaseModel):
    hidden: bool


class ChooseRequest(BaseModel):
    path: str | None = None


class OrdersRequest(BaseModel):
    enabled: bool


def _status() -> dict:
    state = get_state()
    adapter = state.broker.adapter
    try:
        info = adapter.get_terminal()
    except Exception:  # noqa: BLE001 - the panel should still open when the terminal does not answer
        logger.debug("terminal info unavailable", exc_info=True)
        info = TerminalInfo(name=adapter.name)
    real = adapter.name == "mt5"
    mode = state.settings.broker.lower()
    window = state.terminal_window.state() if real else {"found": False, "hidden": None, "minimized": False}
    found = [t.as_dict() for t in _detected()]
    return {
        "broker": adapter.name,
        # what the settings ask for: "auto" (MetaTrader when there is one), "mt5" or "mock"
        "mode": mode,
        "info": info.model_dump(),
        "window": {**window, "hide_preference": bool(preferences.get("hide_terminal"))},
        "terminals": found,
        # the app is on the synthetic market only because no terminal was ready when it started, and one
        # is running now: it can switch over by itself (POST /api/terminal/connect)
        "can_connect": (not real) and mode == "auto" and any(t["running"] for t in found),
        "chosen": preferences.get("terminal_path"),
        "orders": {"allowed": state.orders_allowed(), "by_settings": bool(state.settings.allow_live_orders)},
        "app": {"packaged": paths.frozen(), "can_quit": quit_hook is not None, "version": __version__},
    }


@router.get("/terminal")
def terminal_status() -> dict:
    return _status()


@router.post("/terminal/connect")
async def terminal_connect() -> dict:
    """Connect to a MetaTrader terminal that is ready now. 409, with the reason in words, when it is not."""
    state = get_state()
    async with state.switch_lock:
        try:
            prepared = await asyncio.to_thread(state.prepare_metatrader)
        except Exception as exc:  # noqa: BLE001 - whatever stopped it, the user is told
            logger.info("could not connect to MetaTrader: %s", exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if prepared is not None:
            state.commit_metatrader(prepared)
    return await asyncio.to_thread(_status)


@router.post("/app/orders")
def set_orders(request: OrdersRequest) -> dict:
    """Let the app send orders to the broker, or stop it. Off is how a fresh install starts."""
    state = get_state()
    if not request.enabled and state.settings.allow_live_orders:
        raise HTTPException(
            status_code=409,
            detail="Orders are switched on in the settings file (CT_ALLOW_LIVE_ORDERS=true): remove that line to be able to switch them off here.",
        )
    preferences.set("allow_live_orders", request.enabled)
    logger.warning("sending orders to the broker is now %s", "ON" if request.enabled else "off")
    return _status()


@router.post("/terminal/window")
def terminal_window(request: WindowRequest) -> dict:
    state = get_state()
    if state.broker.adapter.name != "mt5":
        raise HTTPException(status_code=409, detail="There is no MetaTrader terminal to hide: the app is on the mock broker.")
    state.terminal_window.set_hidden(request.hidden)
    return _status()


@router.post("/terminal/choose")
def terminal_choose(request: ChooseRequest) -> dict:
    if request.path is not None:
        known = {str(Path(t.exe)).lower() for t in _detected()}
        if str(Path(request.path)).lower() not in known:
            raise HTTPException(status_code=400, detail="That is not a MetaTrader terminal found on this PC.")
    preferences.set("terminal_path", request.path)
    return _status()


@router.post("/app/window")
def window_expected() -> dict:
    """A second start of the program found this copy running and is about to open a window on it. ``ok`` false: this copy
    is ending, so no window may be opened on it (the second start waits for it to end and starts afresh)."""
    return {"ok": True if window_hook is None else bool(window_hook())}


@router.post("/app/quit")
def quit_app(background: BackgroundTasks) -> dict:
    if quit_hook is None:
        raise HTTPException(status_code=409, detail="CheapTrader was not started as the packaged program: stop it where it was started.")
    if window_closer is not None:
        background.add_task(window_closer)  # after the answer has gone out: the window first, then the program
    background.add_task(quit_hook)
    return {"ok": True}
