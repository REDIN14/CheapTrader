"""Snapshot service: fetch bars, run indicators, render multi-part images."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from app.broker.base import BrokerAdapter
from app.drawings import store as drawing_store
from app.indicators.needs import MAX_INDICATOR_BARS, declared_bars
from app.indicators.registry import IndicatorRegistry
from app.indicators.sandbox import run_indicator
from app.schemas import TIMEFRAME_SECONDS, Bar, SnapshotPart, SnapshotRequest, SnapshotResponse, Timeframe
from app.snapshot.renderer import render_chart
from app.snapshot.segmenter import segment_bars


def _warm_up_bars(broker: BrokerAdapter, symbol: str, timeframe: Timeframe, first: int, extra: int) -> list[Bar]:
    """Up to ``extra`` bars that end just before the bar at ``first`` (the one the snapshot starts with): they warm up
    an indicator that says it needs more bars than the snapshot shows (see ``app/indicators/needs.py``)."""
    step = TIMEFRAME_SECONDS[timeframe]
    end = datetime.fromtimestamp(first, tz=timezone.utc)
    older: list[Bar] = []
    # Markets close at weekends and overnight, so the bars take more time than their number says: look further back
    # until there are enough (or the broker has no more).
    for slack in (1.6, 6, 30):
        start = datetime.fromtimestamp(max(0, first - int(extra * step * slack)), tz=timezone.utc)
        older = [b for b in broker.get_bars(symbol, timeframe, start=start, end=end) if b.time < first]
        if len(older) >= extra:
            break
    return older[-extra:]


def build_snapshot(
    broker: BrokerAdapter,
    registry: IndicatorRegistry,
    request: SnapshotRequest,
) -> SnapshotResponse:
    """Render a chart-only snapshot, split into scaled parts."""
    bars = broker.get_bars(
        request.symbol,
        request.timeframe,
        start=request.start,
        end=request.end,
    )
    if not bars:
        return SnapshotResponse(
            symbol=request.symbol,
            timeframe=request.timeframe,
            parts=[],
            summary="No bars in the requested range.",
        )

    # Run requested indicators over the full range once.
    plots: list[dict] = []
    drawings: list[dict] = []
    if request.include_drawings:
        drawings += [d.model_dump(exclude_none=True) for d in drawing_store.for_symbol(request.symbol)]
    for indicator_id in request.indicators:
        spec = registry.get(indicator_id)
        if spec is None:
            continue
        run_over, show_from = bars, None
        extra = min(declared_bars(spec.code) or 0, MAX_INDICATOR_BARS) - len(bars)
        if extra > 0:  # it says it needs more bars than the picture shows: the ones before it warm it up
            warm = _warm_up_bars(broker, request.symbol, request.timeframe, bars[0].time, extra)
            if warm:
                run_over, show_from = warm + bars, bars[0].time
        result = run_indicator(
            indicator_id=spec.id,
            name=spec.name,
            code=spec.code,
            bars=run_over,
            params=spec.params,
            overlay=spec.overlay,
            pane=spec.pane,
            show_from=show_from,
        )
        if result.error:
            continue
        for p in result.plots:
            plots.append({"name": p["name"], "color": p.get("color"), "data": p["data"]})
        drawings += result.drawings

    digits = 5
    symbol_info = None
    try:
        symbol_info = next((s for s in broker.list_symbols() if s.name == request.symbol), None)
    except Exception:  # noqa: BLE001
        symbol_info = None
    if symbol_info is not None:
        digits = symbol_info.digits

    segments = segment_bars(bars, request.max_points_per_part)
    parts: list[SnapshotPart] = []
    for seg in segments:
        png = render_chart(
            symbol=request.symbol,
            timeframe=request.timeframe.value,
            bars=seg.bars,
            plots=plots,
            drawings=drawings,
            width=request.width,
            height=request.height,
            part_index=seg.index,
            part_total=seg.total,
            digits=digits,
        )
        parts.append(
            SnapshotPart(
                index=seg.index,
                total=seg.total,
                start=_dt(seg.bars[0].time),
                end=_dt(seg.bars[-1].time),
                image_base64=base64.b64encode(png).decode("ascii"),
            )
        )

    summary = (
        f"{request.symbol} {request.timeframe.value}: {len(bars)} bars from "
        f"{_dt(bars[0].time):%Y-%m-%d %H:%M} to {_dt(bars[-1].time):%Y-%m-%d %H:%M} UTC, "
        f"rendered as {len(parts)} part(s)."
    )
    return SnapshotResponse(
        symbol=request.symbol,
        timeframe=request.timeframe,
        parts=parts,
        summary=summary,
    )


def _dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts)
