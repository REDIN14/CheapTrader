import assert from "node:assert/strict";
import { test } from "node:test";
import { snapToCandle } from "../src/lib/magnet";
import { TF, TIMEFRAME_GROUPS } from "../src/lib/timeframes";
import { formatChartTime } from "../src/lib/format";
import type { Bar, Timeframe } from "../src/lib/types";

const bars: Bar[] = [{ time: 60, open: 100, high: 110, low: 90, close: 105, tick_volume: 1, spread: 0, real_volume: 0 }];
const geometry = { timeToX: (time: number) => time, priceToY: (price: number) => 220 - price * 2 };

test("magnet snaps exactly to each OHLC price and candle time", () => {
  for (const price of [100, 110, 90, 105]) {
    assert.deepEqual(snapToCandle({ time: 63, price, x: 63, y: geometry.priceToY(price) + 1 }, bars, geometry), { time: 60, price });
  }
});

test("the magnet leaves distant points and empty charts free", () => {
  assert.equal(snapToCandle({ time: 100, price: 100, x: 100, y: 20 }, bars, geometry), null);
  assert.equal(snapToCandle({ time: 60, price: 10, x: 60, y: 200 }, bars, geometry), null);
  assert.equal(snapToCandle({ time: 60, price: 100, x: 60, y: 20 }, [], geometry), null);
});

test("snapping uses screen distance and ignores points outside the chart mapping", () => {
  assert.equal(snapToCandle({ time: 60, price: 100, x: 60, y: 120 }, bars, { ...geometry, timeToX: () => null }), null);
  const close = { ...bars[0], time: 75, high: 112 };
  assert.deepEqual(snapToCandle({ time: 67, price: 112, x: 67, y: -4 }, [bars[0], close], geometry), { time: 75, price: 112 });
});

test("all five seconds intervals have consistent menu labels and timing", () => {
  assert.equal(TIMEFRAME_GROUPS[0], "SECONDS");
  for (const seconds of [1, 5, 10, 15, 30]) {
    const tf = TF[`S${seconds}` as Timeframe];
    assert.equal(tf.seconds, seconds);
    assert.equal(tf.short, `${seconds}s`);
    assert.equal(tf.group, "SECONDS");
  }
  assert.match(formatChartTime(Date.UTC(2026, 0, 1, 12, 34, 56) / 1000, true, true), /12:34:56$/);
});
