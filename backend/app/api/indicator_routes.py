"""Indicator REST routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data.history import moment
from app.indicators.needs import MAX_SHOWN_BARS, bars_to_load, declared_bars
from app.indicators.registry import IndicatorError
from app.indicators.sandbox import run_indicator
from app.schemas import IndicatorResult, IndicatorSpec, IndicatorUpdate, Timeframe
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
    try:
        return get_state().indicators.save(spec)
    except IndicatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{indicator_id}", response_model=IndicatorSpec)
def update_indicator(indicator_id: str, change: IndicatorUpdate) -> IndicatorSpec:
    """Change an indicator: the fields that are given (the id is the one in the address). A built-in takes new
    parameters, kept in the data folder; its code, name and kind cannot be changed (a copy of it can)."""
    try:
        spec = get_state().indicators.update(indicator_id, change)
    except IndicatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec is None:
        raise HTTPException(status_code=404, detail=f"indicator {indicator_id} not found")
    return spec


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
    start: int | None = None,
    end: int | None = None,
) -> IndicatorResult:
    """Run over a historical start/end window, or the newest ``count`` bars.

    An indicator that says it needs more (``NEEDS_BARS`` at the top of its code, see ``app/indicators/needs.py``) is run
    over more, and the older bars only warm it up: no line comes back for them.
    """
    state = get_state()
    spec = state.indicators.get(indicator_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"indicator {indicator_id} not found")

    show_from = None
    if start is not None and end is not None:
        if end < start:
            raise HTTPException(status_code=422, detail="The indicator window ends before it starts.")
        bars = state.cache.ensure_range(state.broker.adapter, symbol, timeframe, moment(start), moment(end))
        needed = declared_bars(spec.code) or 0
        if bars and len(bars) < needed:
            warmup = state.cache.history_before(state.broker.adapter, symbol, timeframe, bars[0].time, needed - len(bars))
            bars = warmup.bars + bars
        show_from = start
    else:
        bars = state.cache.get_bars(
            state.broker.adapter, symbol, timeframe, count=bars_to_load(count, declared_bars(spec.code))
        )
        show_from = bars[-count].time if len(bars) > count else None
    result = run_indicator(
        indicator_id=spec.id,
        name=spec.name,
        code=spec.code,
        bars=bars,
        params=spec.params,
        overlay=spec.overlay,
        pane=spec.pane,
        settings=state.settings,
        show_from=show_from,
    )
    result.params = dict(spec.params)  # the legend shows them after the name
    return result
