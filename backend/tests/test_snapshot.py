"""Tests for the snapshot renderer and segmenter."""

from __future__ import annotations

from app.broker.mock_adapter import MockAdapter
from app.indicators.registry import IndicatorRegistry
from app.schemas import IndicatorSpec, SnapshotRequest, Timeframe
from app.snapshot.renderer import render_chart
from app.snapshot.segmenter import segment_bars
from app.snapshot.service import build_snapshot


def _bars(count: int = 100):
    broker = MockAdapter()
    broker.connect()
    return broker.get_bars("EURUSD", Timeframe.H1, count=count)


def test_segment_bars_splits_evenly() -> None:
    bars = _bars(1000)
    segments = segment_bars(bars, max_points_per_part=400)
    assert len(segments) == 3
    assert segments[0].index == 1 and segments[0].total == 3
    assert len(segments[0].bars) == 400
    assert len(segments[1].bars) == 401  # one-bar overlap
    assert len(segments[2].bars) == 201


def test_segment_bars_empty() -> None:
    assert segment_bars([], 400) == []


def test_render_chart_returns_png() -> None:
    png = render_chart("EURUSD", "H1", _bars(50))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000


def test_render_chart_with_plots() -> None:
    bars = _bars(50)
    plots = [
        {
            "name": "SMA",
            "color": "#2962ff",
            "data": [{"time": b.time, "value": b.close} for b in bars],
        }
    ]
    png = render_chart("EURUSD", "H1", bars, plots=plots)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_snapshot_multi_part(tmp_path) -> None:
    broker = MockAdapter()
    broker.connect()
    registry = IndicatorRegistry(data_dir=tmp_path)
    request = SnapshotRequest(
        symbol="EURUSD",
        timeframe=Timeframe.H1,
        start=__import__("datetime").datetime(2024, 1, 1),
        end=__import__("datetime").datetime(2024, 6, 1),
        max_points_per_part=200,
    )
    response = build_snapshot(broker, registry, request)
    assert len(response.parts) > 1
    assert response.parts[0].total == len(response.parts)
    assert response.parts[0].image_base64
    assert "EURUSD" in response.summary


# -- drawings in the picture ------------------------------------------------------------------------------
def _shapes(bars) -> list[dict]:
    t = [b.time for b in bars]
    hi, lo = max(b.high for b in bars), min(b.low for b in bars)
    mid = (hi + lo) / 2

    def p(i, price):
        return {"time": t[i], "price": price}

    return [
        {"type": "rectangle", "points": [p(5, hi), p(20, mid)], "style": {"color": "#ff9800"}},
        {"type": "trendline", "points": [p(2, lo), p(30, hi)], "style": {"extend_right": True, "dash": "dashed"}},
        {"type": "channel", "points": [p(3, lo), p(25, mid), p(15, lo)], "style": {}},
        {"type": "long", "points": [p(30, mid), p(40, hi), p(40, lo)], "style": {}},
        {"type": "short", "points": [p(32, mid), {"time": t[-1] + 86400, "price": lo}, {"time": t[-1] + 86400, "price": hi}], "style": {}},
        {"type": "hline", "points": [{"time": 0, "price": mid}], "style": {"text": "mid"}},
        {"type": "vline", "points": [p(10, 0)], "style": {"text": "v"}},
        {"type": "polyline", "points": [p(1, lo), p(8, hi), p(12, lo)], "style": {}},
        {"type": "text", "points": [p(35, hi)], "style": {"text": "hello"}},
    ]


def plot_area(png: bytes | str) -> bytes:
    """The pixels of the chart itself (the footer carries the second it was made in, so whole files differ)."""
    import base64
    import io

    from PIL import Image

    data = base64.b64decode(png) if isinstance(png, str) else png
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    return image.crop((int(w * 0.05), int(h * 0.16), int(w * 0.88), int(h * 0.86))).tobytes()


def test_every_kind_of_drawing_can_be_put_in_the_picture() -> None:
    bars = _bars(60)
    plain = plot_area(render_chart("EURUSD", "H1", bars))
    with_shapes = render_chart("EURUSD", "H1", bars, drawings=_shapes(bars))
    assert with_shapes[:8] == b"\x89PNG\r\n\x1a\n"
    assert plot_area(with_shapes) != plain
    assert plot_area(render_chart("EURUSD", "H1", bars)) == plain  # (the comparison itself is steady)
    for shape in _shapes(bars):  # each one on its own changes the picture
        assert plot_area(render_chart("EURUSD", "H1", bars, drawings=[shape])) != plain, shape["type"]


def test_a_shape_that_cannot_be_drawn_does_not_spoil_the_picture() -> None:
    bars = _bars(40)
    broken = [
        {"type": "rectangle", "points": [], "style": {}},
        {"type": "rectangle", "points": [{"time": bars[0].time, "price": 1.0}, {"time": bars[5].time, "price": 1.1}], "style": {"color": "not-a-colour"}},
        {"type": "mystery", "points": [{"time": 1, "price": 1.0}], "style": {}},
        {"type": "trendline", "points": [{"time": bars[3].time, "price": 1.0}, {"time": bars[3].time, "price": 1.1}], "style": {"extend_right": True}},  # vertical
    ]
    assert render_chart("EURUSD", "H1", bars, drawings=broken)[:4] == b"\x89PNG"


def test_a_shape_does_not_stretch_the_price_axis() -> None:
    from app.snapshot.renderer import render_chart as render

    bars = _bars(40)
    far = [{"type": "hline", "points": [{"time": 0, "price": 1000.0}], "style": {}}]  # far above anything on the chart
    # drawn clipped: the axis still fits the candles, so the labels (and so the image) stay that of the candles
    import io

    from PIL import Image

    def axis_strip(png: bytes):
        image = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = image.size
        return image.crop((int(w * 0.885), int(h * 0.15), w, int(h * 0.80))).tobytes()

    assert axis_strip(render("EURUSD", "H1", bars, drawings=far)) == axis_strip(render("EURUSD", "H1", bars))
    # ...and the hline, which is off the chart, left the chart as it was
    assert plot_area(render("EURUSD", "H1", bars, drawings=far)) == plot_area(render("EURUSD", "H1", bars))


def test_a_snapshot_shows_the_drawings_of_the_chart_and_of_the_indicators(tmp_path) -> None:
    import datetime

    from app.drawings import Drawing, store

    broker = MockAdapter()
    broker.connect()
    registry = IndicatorRegistry(data_dir=tmp_path)
    painter = registry.save(
        IndicatorSpec(
            id="",
            name="Painter",
            overlay=True,
            code=(
                "from ct_draw import hline\n\n"
                "def compute(df, params):\n"
                "    return {'drawings': [hline(float(df['close'].mean()), color='#ff9800', width=3)]}\n"
            ),
        )
    )
    bars = broker.get_bars("EURUSD", Timeframe.H1, count=60)
    start = datetime.datetime.fromtimestamp(bars[0].time)
    end = datetime.datetime.fromtimestamp(bars[-1].time + 3600)

    def snapshot(**extra):
        request = SnapshotRequest(symbol="EURUSD", timeframe=Timeframe.H1, start=start, end=end, **extra)
        return build_snapshot(broker, registry, request).parts[0].image_base64

    base = plot_area(snapshot())
    assert plot_area(snapshot()) == base
    assert plot_area(snapshot(indicators=[painter.id])) != base  # the indicator's own shape

    store.add("EURUSD", Drawing.model_validate({"type": "rectangle", "points": [{"time": bars[10].time, "price": 1.2}, {"time": bars[30].time, "price": 0.9}], "style": {}}))
    assert plot_area(snapshot()) != base  # the user's drawing is on the chart, so it is in the picture
    assert plot_area(snapshot(include_drawings=False)) == base  # unless the caller wants the chart bare
