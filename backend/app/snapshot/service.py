"""Snapshot service: fetch bars, run indicators, render multi-part images."""

from __future__ import annotations

import base64
from datetime import datetime

from app.broker.base import BrokerAdapter
from app.drawings import store as drawing_store
from app.indicators.registry import IndicatorRegistry
from app.indicators.sandbox import run_indicator
from app.schemas import SnapshotPart, SnapshotRequest, SnapshotResponse
from app.snapshot.renderer import render_chart
from app.snapshot.segmenter import segment_bars


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
        result = run_indicator(
            indicator_id=spec.id,
            name=spec.name,
            code=spec.code,
            bars=bars,
            params=spec.params,
            overlay=spec.overlay,
            pane=spec.pane,
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
