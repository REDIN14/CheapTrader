"""Indicator REST routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.indicators.needs import MAX_SHOWN_BARS, bars_to_load, declared_bars
from app.indicators.sandbox import run_indicator
from app.schemas import IndicatorResult, IndicatorSpec, Timeframe
from app.state import get_state

router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.get("", response_model=list[IndicatorSpec])
def list_indicators() -> list[IndicatorSpec]:
    return get_state().indicators.list()


@router.get("/{indicator_id}", response_model=IndicatorSpec)
def get_indicator(indicator_id: str) -> IndicatorSpec:
    spec = get_state().indicators.get(indicator_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"indicator {indicator_id} not found")
    return spec


@router.post("", response_model=IndicatorSpec)
def create_indicator(spec: IndicatorSpec) -> IndicatorSpec:
    return get_state().indicators.save(spec)


@router.put("/{indicator_id}", response_model=IndicatorSpec)
def update_indicator(indicator_id: str, spec: IndicatorSpec) -> IndicatorSpec:
    registry = get_state().indicators
    if registry.is_builtin(indicator_id):
        raise HTTPException(status_code=400, detail="built-in indicators cannot be modified")
    spec.id = indicator_id
    return registry.save(spec)


@router.delete("/{indicator_id}")
def delete_indicator(indicator_id: str) -> dict:
    if not get_state().indicators.delete(indicator_id):
        raise HTTPException(status_code=404, detail=f"indicator {indicator_id} not found")
    return {"ok": True}


@router.post("/{indicator_id}/run", response_model=IndicatorResult)
def run(
    indicator_id: str,
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    count: int = Query(default=500, ge=1, le=MAX_SHOWN_BARS),
) -> IndicatorResult:
    """Run an indicator over the newest ``count`` bars; its lines come back for those bars.

    An indicator that says it needs more (``NEEDS_BARS`` at the top of its code, see ``app/indicators/needs.py``) is run
    over more, and the older bars only warm it up: no line comes back for them.
    """
    state = get_state()
    spec = state.indicators.get(indicator_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"indicator {indicator_id} not found")

    bars = state.cache.get_bars(
        state.broker.adapter, symbol, timeframe, count=bars_to_load(count, declared_bars(spec.code))
    )
    return run_indicator(
        indicator_id=spec.id,
        name=spec.name,
        code=spec.code,
        bars=bars,
        params=spec.params,
        overlay=spec.overlay,
        pane=spec.pane,
        settings=state.settings,
        show_from=bars[-count].time if len(bars) > count else None,
    )
