"""Snapshot segmentation.

Splits a large date range into multiple, evenly-scaled chart parts so no single
image is over-compressed. Each part overlaps its neighbour by one bar so the
series stays visually continuous.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import Bar


@dataclass
class Segment:
    index: int
    total: int
    bars: list[Bar]


def segment_bars(bars: list[Bar], max_points_per_part: int = 400) -> list[Segment]:
    """Split ``bars`` into segments of at most ``max_points_per_part`` bars."""
    if not bars:
        return []
    if max_points_per_part <= 0:
        max_points_per_part = 400

    total = (len(bars) + max_points_per_part - 1) // max_points_per_part
    segments: list[Segment] = []
    for i in range(total):
        start = i * max_points_per_part
        end = min(start + max_points_per_part, len(bars))
        # Overlap by one bar with the previous segment for continuity.
        chunk_start = max(0, start - 1) if i > 0 else start
        segments.append(Segment(index=i + 1, total=total, bars=bars[chunk_start:end]))
    return segments
