"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__, paths
from app.api import (
    api_router,
    docs_router,
    drawing_router,
    indicator_router,
    profile_router,
    replay_router,
    snapshot_router,
    terminal_router,
    ws_router,
)
from app.security import LocalOnly, allowed_origins
from app.state import get_state

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = get_state()
    state.startup()
    if state.hub is not None:
        state.hub.start(asyncio.get_running_loop())
    yield
    state.shutdown()


app = FastAPI(title="CheapTrader", version=__version__, lifespan=lifespan)

# The page is served from the same address as the API (the packaged program) or through the development
# server's proxy, so no other site needs to be let in. Pages the user names (CT_ALLOWED_ORIGINS) are.
if allowed_origins():
    app.add_middleware(
        CORSMiddleware, allow_origins=sorted(allowed_origins()), allow_methods=["*"], allow_headers=["*"]
    )
# (last added = outermost) refuses other sites and host names before anything else sees the request
app.add_middleware(LocalOnly)

app.include_router(api_router)
app.include_router(profile_router)
app.include_router(replay_router)
app.include_router(indicator_router)
app.include_router(snapshot_router)
app.include_router(terminal_router)
app.include_router(drawing_router)
app.include_router(docs_router)
app.include_router(ws_router)


def mount_ui(application: FastAPI, folder: Path) -> None:
    """Serve the built page (`frontend/dist`) from the same port as the API.

    The built program does this, so one process is the whole app. It goes last: the API
    and the stream were added first and keep their paths.
    """
    application.mount("/", StaticFiles(directory=folder, html=True), name="ui")


_ui = paths.ui_dir()
if _ui is not None:
    mount_ui(app, _ui)
else:

    @app.get("/")
    def root() -> dict:
        return {"name": "CheapTrader", "version": __version__, "docs": "/docs"}
