import assert from "node:assert/strict";
import { test } from "node:test";
import { needsHistory, prependBars } from "../src/lib/history";
import { replayDate } from "../src/lib/replayDate";
import type { Bar } from "../src/lib/types";

const bar = (time: number): Bar => ({ time, open: 1, high: 2, low: 0, close: 1, tick_volume: 1, spread: 0, real_volume: 0 });

test("older pages preserve every existing candle and reject overlapping/future data", () => {
  const current = [bar(30), bar(40)];
  const merged = prependBars(current, [bar(20), bar(10), bar(20), { ...bar(40), close: 99 }, bar(50)]);
  assert.deepEqual(merged.map(b => b.time), [10, 20, 30, 40]);
  assert.equal(merged[2], current[0]);
  assert.equal(merged[3], current[1]);
  assert.equal(prependBars(current, []), current);
});

test("a series keeps growing past the old 100,000 candle ceiling", () => {
  let bars = [bar(150_000)];
  for (let page = 0; page < 11; page++) {
    const first = bars[0].time;
    bars = prependBars(bars, Array.from({ length: 10_000 }, (_, i) => bar(first - 10_000 + i)));
  }
  assert.equal(bars.length, 110_001);
  assert.equal(bars.at(-1)?.time, 150_000);
});

test("left-edge loading follows both panning and zooming without a total depth cap", () => {
  assert.equal(needsHistory({ from: 50, to: 200 }, 1500), true);
  assert.equal(needsHistory({ from: -5000, to: -4800 }, 1500), true);
  assert.equal(needsHistory({ from: 500, to: 2500 }, 2_000_000), true);
  assert.equal(needsHistory({ from: 1400, to: 1500 }, 1500), false);
  assert.equal(needsHistory(null, 1500), false);
});

test("replay dates can be older than every loaded candle, including the date in the reported screenshot", () => {
  assert.equal(replayDate("2025-11-06", "00:00", true), Date.UTC(2025, 10, 6) / 1000);
  assert.equal(replayDate("2000-01-01", "12:34:56", true), Date.UTC(2000, 0, 1, 12, 34, 56) / 1000);
  assert.equal(replayDate("2025-02-30", "00:00", true), null);
  assert.equal(replayDate("", "00:00", true), null);
});
