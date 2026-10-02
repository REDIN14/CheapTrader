"""API layer."""

from app.api.docs_routes import router as docs_router
from app.api.drawing_routes import router as drawing_router
from app.api.indicator_routes import router as indicator_router
from app.api.replay_routes import router as replay_router
from app.api.routes import router as api_router
from app.api.snapshot_routes import router as snapshot_router
from app.api.terminal_routes import router as terminal_router
from app.api.ws import router as ws_router

__all__ = [
    "docs_router",
    "drawing_router",
    "api_router",
    "indicator_router",
    "replay_router",
    "snapshot_router",
    "terminal_router",
    "ws_router",
]
