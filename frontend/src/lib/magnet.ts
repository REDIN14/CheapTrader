import { nearestIndex } from "./barMath";
import type { DrawingPoint } from "./drawings";
import type { Bar } from "./types";

interface Geometry {
  timeToX: (time: number) => number | null;
  priceToY: (price: number) => number | null;
}

/** Snap to a nearby candle's OHLC in screen pixels, so zoom never changes the strength. */
export function snapToCandle(
  point: DrawingPoint & { x: number; y: number }, bars: Bar[], geometry: Geometry, radius = 12,
): DrawingPoint | null {
  if (!bars.length) return null;
  const center = nearestIndex(bars, point.time);
  let best: DrawingPoint | null = null;
  let distance = radius * radius;
  for (let i = Math.max(0, center - 1); i <= Math.min(bars.length - 1, center + 1); i++) {
    const candle = bars[i];
    const x = geometry.timeToX(candle.time);
    if (x == null || Math.abs(x - point.x) > radius) continue;
    for (const price of [candle.open, candle.high, candle.low, candle.close]) {
      const y = geometry.priceToY(price);
      if (y == null) continue;
      const d = (point.x - x) ** 2 + (point.y - y) ** 2;
      if (d <= distance) {
        distance = d;
        best = { time: candle.time, price };
      }
    }
  }
  return best;
}
