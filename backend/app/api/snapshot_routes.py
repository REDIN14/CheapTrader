"""Snapshot REST routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import SnapshotRequest, SnapshotResponse
from app.snapshot.service import build_snapshot
from app.state import get_state

router = APIRouter(prefix="/api/snapshot", tags=["snapshot"])


@router.post("", response_model=SnapshotResponse)
def create_snapshot(request: SnapshotRequest) -> SnapshotResponse:
    state = get_state()
    try:
        return build_snapshot(state.broker.adapter, state.indicators, request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
