"""Chart drawings over REST: what the chart draws, and what a script can draw on it.

* ``GET    /api/drawings?symbol=``            the drawings of a symbol;
* ``POST   /api/drawings?symbol=``            add one (``id`` is optional; ``symbol`` may be in the body instead);
* ``PUT    /api/drawings/{id}?symbol=``       replace one;
* ``PATCH  /api/drawings/{id}?symbol=``       change its points and / or style;
* ``DELETE /api/drawings/{id}?symbol=``       remove one;
* ``DELETE /api/drawings?symbol=``            remove the symbol's drawings, or (``all_symbols=true``) everyone's.
  Locked drawings are kept unless ``locked=include``; ``locked=only`` removes just the locked ones;
* ``GET    /api/drawings/summary``            how many drawings each symbol has, and how many are locked.

A locked drawing cannot be moved, replaced or removed (HTTP 423) until ``{"locked": false}`` is patched in.

Every change is announced to the open pages, so a drawing added by a script appears on the chart at once.
See ``docs/DRAWINGS.md``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import ValidationError

from app.drawings import Drawing, DrawingPatch, LockedError, LockedScope, store
from app.state import get_state

router = APIRouter(prefix="/api/drawings", tags=["drawings"])


def _announce(symbol: str) -> None:
    hub = get_state().hub
    if hub is not None:
        hub.announce({"type": "drawings", "symbol": symbol})


def _explain(exc: ValueError) -> str:
    """An invalid drawing as one line a script can read: `points: a rectangle takes 2 point(s), not 1`."""
    if not isinstance(exc, ValidationError):
        return str(exc)
    parts = []
    for problem in exc.errors():
        where = ".".join(str(p) for p in problem["loc"])
        what = str(problem["msg"]).removeprefix("Value error, ")
        parts.append(f"{where}: {what}" if where else what)
    return "; ".join(parts)


def _symbol(query: str | None, body: dict[str, Any] | None = None) -> str:
    symbol = (query or (body or {}).get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="Say which symbol the drawing belongs to (?symbol=EURUSD).")
    return symbol


@router.get("", response_model=list[Drawing], response_model_exclude_none=True)
def list_drawings(symbol: str = Query(min_length=1)) -> list[Drawing]:
    return store.for_symbol(symbol)


@router.get("/summary")
def summary() -> dict[str, dict[str, int]]:
    """How many drawings every symbol has (``total``) and how many of them are locked (``locked``)."""
    return store.summary()


@router.post("", response_model=Drawing, status_code=201, response_model_exclude_none=True)
def add_drawing(body: dict[str, Any] = Body(...), symbol: str | None = None) -> Drawing:
    name = _symbol(symbol, body)
    try:
        drawing = Drawing.model_validate({k: v for k, v in body.items() if k != "symbol"})
        saved = store.add(name, drawing)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_explain(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc.args[0])) from exc
    _announce(name)
    return saved


@router.put("/{drawing_id}", response_model=Drawing, response_model_exclude_none=True)
def replace_drawing(drawing_id: str, body: dict[str, Any] = Body(...), symbol: str | None = None) -> Drawing:
    name = _symbol(symbol, body)
    try:
        saved = store.replace(name, drawing_id, Drawing.model_validate({k: v for k, v in body.items() if k != "symbol"}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_explain(exc)) from exc
    except LockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no drawing {drawing_id}") from exc
    _announce(name)
    return saved


@router.patch("/{drawing_id}", response_model=Drawing, response_model_exclude_none=True)
def patch_drawing(drawing_id: str, change: DrawingPatch, symbol: str = Query(min_length=1)) -> Drawing:
    try:
        saved = store.patch(symbol, drawing_id, change)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_explain(exc)) from exc
    except LockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no drawing {drawing_id}") from exc
    _announce(symbol)
    return saved


@router.delete("/{drawing_id}")
def delete_drawing(drawing_id: str, symbol: str = Query(min_length=1)) -> dict:
    try:
        gone = store.remove(symbol, drawing_id)
    except LockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    if not gone:
        raise HTTPException(status_code=404, detail=f"no drawing {drawing_id}")
    _announce(symbol)
    return {"ok": True}


@router.delete("")
def clear_drawings(
    symbol: str | None = None,
    all_symbols: bool = False,
    locked: LockedScope = "exclude",
) -> dict:
    """Remove drawings in bulk: one symbol's (``symbol=``) or everyone's (``all_symbols=true``).

    Drawings that are locked stay unless ``locked=include``; ``locked=only`` takes only the locked ones.
    """
    if all_symbols:
        by_symbol = store.clear_all(locked)
        for name in by_symbol:
            _announce(name)
        kept = sum(s["locked"] for s in store.summary().values()) if locked == "exclude" else 0
        return {"ok": True, "removed": sum(by_symbol.values()), "symbols": by_symbol, "kept_locked": kept}
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=422, detail="Say which symbol (?symbol=EURUSD), or all_symbols=true.")
    removed = store.clear(symbol, locked)
    if removed:
        _announce(symbol)
    kept = sum(1 for d in store.for_symbol(symbol) if d.locked) if locked == "exclude" else 0
    return {"ok": True, "removed": removed, "kept_locked": kept}
