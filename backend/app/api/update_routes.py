"""Updates: is there a newer CheapTrader on GitHub, and install it (see ``app/updater.py``).

* ``GET  /api/update``          what is known: the newest release, whether it is newer, how an install is going;
* ``POST /api/update/check``    look at GitHub now;
* ``POST /api/update/install``  download the newest release, check it and install it (the program closes and opens again);
* ``POST /api/update/skip``     do not offer this version again;
* ``POST /api/update/enabled``  look for updates by itself, or not (remembered).
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api import terminal_routes
from app.schemas import UpdateStatus
from app.state import get_state
from app.updater import UpdateError

router = APIRouter(prefix="/api/update", tags=["update"])


class SkipRequest(BaseModel):
    version: str


class EnabledRequest(BaseModel):
    enabled: bool


@router.get("", response_model=UpdateStatus)
def update_status() -> dict:
    return get_state().updater.status()


@router.post("/check", response_model=UpdateStatus)
def update_check() -> dict:
    return get_state().updater.check()


@router.post("/install", response_model=UpdateStatus)
def update_install() -> dict:
    """Start installing. The answer comes at once; the page follows the progress with ``GET /api/update``."""
    try:
        return get_state().updater.install(terminal_routes.update_hook or terminal_routes.quit_hook)
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/skip", response_model=UpdateStatus)
def update_skip(request: SkipRequest) -> dict:
    updater = get_state().updater
    updater.skip(request.version)
    return updater.status()


@router.post("/enabled", response_model=UpdateStatus)
def update_enabled(request: EnabledRequest) -> dict:
    updater = get_state().updater
    updater.set_enabled(request.enabled)
    if request.enabled and updater.status()["checked_at"] is None:
        threading.Thread(target=updater.check, name="update-check-now", daemon=True).start()
    return updater.status()
