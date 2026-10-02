"""Server-side chart renderer.

Renders *only the chart* (candles, volume, indicator overlays) to a PNG — never
the application UI. A metadata header and footer bind every image to the exact
symbol, timeframe, and time window it represents.
"""

from __future__ import annotations

import io
import statistics
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import Polygon, Rectangle  # noqa: E402

from app.schemas import Bar  # noqa: E402

# TradingView dark palette.
_BG = "#131722"
_GRID = "#1e222d"
_TEXT = "#d1d4dc"
_MUTED = "#787b86"
_UP = "#089981"
_DOWN = "#f23645"

_PLOT_COLORS = ["#2962ff", "#ff9800", "#e91e63", "#00bcd4", "#8bc34a", "#9c27b0"]


def _to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


_DASH = {"solid": "-", "dashed": "--", "dotted": ":"}
_SHAPE_COLOR = "#2962ff"


class _TimeAxis:
    """Where a time falls on the picture, whose x is the bar's number: between its two bars in proportion,
    and past the newest (or before the oldest) as if the bars went on at their usual pace."""

    def __init__(self, bars: list[Bar]) -> None:
        self._times = [b.time for b in bars]
        gaps = [b - a for a, b in zip(self._times, self._times[1:]) if b > a]
        self._step = statistics.median(gaps) if gaps else 3600

    def x(self, time: int) -> float:
        times = self._times
        if time <= times[0]:
            return (time - times[0]) / self._step
        if time >= times[-1]:
            return len(times) - 1 + (time - times[-1]) / self._step
        lo, hi = 0, len(times) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if times[mid] <= time:
                lo = mid
            else:
                hi = mid
        return lo + (time - times[lo]) / (times[hi] - times[lo])


def _draw_shapes(ax, shapes: list[dict], axis: _TimeAxis) -> None:
    """The drawings of the chart (rectangles, lines, position boxes...) on the picture."""
    left, right = ax.get_xlim()
    bottom, top = ax.get_ylim()
    for shape in shapes:
        kind = shape.get("type")
        style = shape.get("style") or {}
        pts = [(axis.x(p["time"]), p["price"]) for p in shape.get("points", [])]
        color = style.get("color") or _SHAPE_COLOR
        width = style.get("width") or 1.5
        dash = _DASH.get(style.get("dash") or "solid", "-")
        fill = style.get("fill") or color

        def line(x0, y0, x1, y1, extend_left=False, extend_right=False, c=color, w=width, d=dash):
            if x1 != x0:
                slope = (y1 - y0) / (x1 - x0)
                if x1 < x0:
                    x0, y0, x1, y1 = x1, y1, x0, y0
                if extend_left:
                    x0, y0 = left - 1, y0 + slope * (left - 1 - x0)
                if extend_right:
                    x1, y1 = right + 1, y1 + slope * (right + 1 - x1)
            ax.plot([x0, x1], [y0, y1], color=c, linewidth=w, linestyle=d, zorder=5, solid_capstyle="round")

        try:
            if kind == "trendline" and len(pts) == 2:
                line(*pts[0], *pts[1], bool(style.get("extend_left")), bool(style.get("extend_right")))
            elif kind == "rectangle" and len(pts) == 2:
                x0, x1 = sorted((pts[0][0], pts[1][0]))
                lo, hi = sorted((pts[0][1], pts[1][1]))
                reach = max(x1, right + 1) if style.get("extend_right", True) else x1
                ax.add_patch(
                    Rectangle((x0, lo), reach - x0, hi - lo, zorder=4, linewidth=width, edgecolor=color,
                              facecolor=(*to_rgb(fill), style.get("fill_opacity", 0.15)))
                )
                if style.get("extend_right", True):  # the side it was drawn to stays, as a dotted line
                    ax.plot([x1, x1], [lo, hi], color=color, linewidth=1, linestyle=":", zorder=5)
            elif kind == "channel" and len(pts) == 3:
                (x0, y0), (x1, y1), (x2, y2) = pts
                slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 0.0
                shift = y2 - (y0 + slope * (x2 - x0))
                ex_l, ex_r = bool(style.get("extend_left")), bool(style.get("extend_right"))
                a, b = (x0, x1) if x0 <= x1 else (x1, x0)
                a = left - 1 if ex_l else a
                b = right + 1 if ex_r else b
                ya, yb = y0 + slope * (a - x0), y0 + slope * (b - x0)
                ax.add_patch(
                    Polygon([(a, ya), (b, yb), (b, yb + shift), (a, ya + shift)], closed=True, zorder=4,
                            facecolor=(*to_rgb(fill), style.get("fill_opacity", 0.1)), edgecolor="none")
                )
                line(a, ya, b, yb, c=color)
                line(a, ya + shift, b, yb + shift, c=color)
            elif kind in ("long", "short") and len(pts) == 3:
                (x0, entry), (x1, target), (_, stop) = pts
                x_lo, x_hi = sorted((x0, x1))
                for far, tint in ((target, "#089981"), (stop, "#f23645")):
                    ax.add_patch(
                        Rectangle((x_lo, min(entry, far)), x_hi - x_lo, abs(far - entry), zorder=4,
                                  facecolor=(*to_rgb(tint), 0.2), edgecolor=tint, linewidth=0.8)
                    )
                ax.plot([x_lo, x_hi], [entry, entry], color="#9598a1", linewidth=1, zorder=5)
                ratio = abs(target - entry) / abs(stop - entry) if stop != entry else 0.0
                ax.text(x_lo + (x_hi - x_lo) / 2, entry, f"{'Long' if kind == 'long' else 'Short'} R:R {ratio:.2f}",
                        color=_TEXT, fontsize=8, ha="center", va="bottom", zorder=6, clip_on=True)
            elif kind == "hline" and len(pts) == 1:
                ax.axhline(pts[0][1], color=color, linewidth=width, linestyle=dash, zorder=5)
                if style.get("text"):
                    ax.text(left + 0.5, pts[0][1], style["text"], color=color, fontsize=8, va="bottom", zorder=6)
            elif kind == "vline" and len(pts) == 1:
                ax.axvline(pts[0][0], color=color, linewidth=width, linestyle=dash, zorder=5)
                if style.get("text"):
                    ax.text(pts[0][0], top, style["text"], color=color, fontsize=8, va="top", ha="left", zorder=6)
            elif kind == "polyline" and len(pts) >= 2:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, linewidth=width, linestyle=dash, zorder=5)
            elif kind == "text" and len(pts) == 1:
                ax.text(pts[0][0], pts[0][1], style.get("text", ""), color=color, fontsize=style.get("font_size", 10) * 0.7,
                        zorder=6, clip_on=True)
        except Exception:  # noqa: BLE001 - a shape that cannot be drawn must not spoil the picture
            continue
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)


def render_chart(
    symbol: str,
    timeframe: str,
    bars: list[Bar],
    plots: list[dict] | None = None,
    drawings: list[dict] | None = None,
    width: int = 1600,
    height: int = 900,
    part_index: int = 1,
    part_total: int = 1,
    digits: int = 5,
) -> bytes:
    """Render a single chart image and return PNG bytes.

    ``plots`` is a list of ``{"name", "color", "data": [{"time","value"}]}``; ``drawings`` a list of
    shapes as the chart draws them (see ``docs/DRAWINGS.md``).
    """
    if not bars:
        raise ValueError("no bars to render")

    plots = plots or []
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=_BG)
    ax = fig.add_axes([0.045, 0.16, 0.84, 0.70])
    ax.set_facecolor(_BG)

    times = [_to_dt(b.time) for b in bars]
    x = list(range(len(bars)))

    # -- candles -----------------------------------------------------------
    for i, b in enumerate(bars):
        color = _UP if b.close >= b.open else _DOWN
        ax.plot([i, i], [b.low, b.high], color=color, linewidth=0.8, zorder=2)
        body_low = min(b.open, b.close)
        body_height = abs(b.close - b.open) or (b.high - b.low) * 0.001
        ax.add_patch(
            Rectangle(
                (i - 0.32, body_low),
                0.64,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
                zorder=3,
            )
        )

    # -- indicator overlays ------------------------------------------------
    time_to_x = {b.time: i for i, b in enumerate(bars)}
    for idx, plot in enumerate(plots):
        color = plot.get("color") or _PLOT_COLORS[idx % len(_PLOT_COLORS)]
        xs, ys = [], []
        for point in plot.get("data", []):
            xi = time_to_x.get(point["time"])
            if xi is None:
                continue
            xs.append(xi)
            ys.append(point["value"])
        if xs:
            ax.plot(xs, ys, color=color, linewidth=1.4, label=plot.get("name", "plot"), zorder=4)

    # -- axes --------------------------------------------------------------
    ax.set_xlim(-1, len(bars))

    # -- drawings (the limits are fixed first: a shape must not stretch the picture) ----------------
    if drawings:
        ax.set_ylim(*ax.get_ylim())
        ax.set_autoscale_on(False)
        _draw_shapes(ax, drawings, _TimeAxis(bars))

    ax.grid(True, color=_GRID, linewidth=0.6, zorder=0)
    ax.tick_params(colors=_MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(_GRID)

    step = max(1, len(bars) // 10)
    ticks = list(range(0, len(bars), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([times[i].strftime("%Y-%m-%d %H:%M") for i in ticks], rotation=0)
    ax.set_xlim(-1, len(bars))
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.{digits}f}"))

    if plots:
        legend = ax.legend(
            loc="upper left",
            facecolor=_BG,
            edgecolor=_GRID,
            labelcolor=_TEXT,
            fontsize=9,
            framealpha=0.85,
        )
        legend.get_frame().set_linewidth(0.6)

    # -- metadata header (bound to symbol + time) --------------------------
    start = times[0]
    end = times[-1]
    last = bars[-1]
    change = last.close - bars[0].open
    change_pct = (change / bars[0].open * 100) if bars[0].open else 0.0
    change_color = _UP if change >= 0 else _DOWN

    fig.text(
        0.045,
        0.945,
        f"{symbol}  ·  {timeframe}",
        color=_TEXT,
        fontsize=17,
        fontweight="bold",
        va="center",
    )
    fig.text(
        0.045,
        0.905,
        f"{start.strftime('%Y-%m-%d %H:%M')}  →  {end.strftime('%Y-%m-%d %H:%M')} UTC",
        color=_MUTED,
        fontsize=11,
        va="center",
    )
    fig.text(
        0.955,
        0.945,
        f"{last.close:.{digits}f}",
        color=change_color,
        fontsize=17,
        fontweight="bold",
        ha="right",
        va="center",
    )
    fig.text(
        0.955,
        0.905,
        f"{'+' if change >= 0 else ''}{change:.{digits}f} ({'+' if change >= 0 else ''}{change_pct:.2f}%)",
        color=change_color,
        fontsize=11,
        ha="right",
        va="center",
    )

    # -- footer ------------------------------------------------------------
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    fig.text(
        0.045,
        0.045,
        f"CheapTrader snapshot · {symbol} {timeframe} · part {part_index}/{part_total} · "
        f"{len(bars)} bars · generated {generated}",
        color=_MUTED,
        fontsize=9,
        va="center",
    )

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=_BG)
    plt.close(fig)
    return buffer.getvalue()
