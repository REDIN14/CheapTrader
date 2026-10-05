import assert from "node:assert/strict";
import { test } from "node:test";
import { indicatorCount, MAX_INDICATOR_BARS, plotsFrom } from "../src/lib/indicatorDepth";

const H1 = 3600;
const NOW = 1_800_000_000;

test("a live chart runs its indicators over as many bars as it shows", () => {
  assert.equal(indicatorCount(20_000, 0, NOW, H1), 20_000);
  assert.equal(indicatorCount(5_000, 0, NOW, H1), 5_000);
  assert.equal(indicatorCount(100_000, 0, NOW, H1), 100_000);
});

test("a replay runs them over every bar back to its first candle", () => {
  const weekAgo = NOW - 7 * 86_400;
  // 168 hourly bars in a week, and a margin on top
  assert.equal(indicatorCount(20_000, weekAgo, NOW, H1), 168 + 300);
  // the same week on a five-minute chart
  assert.equal(indicatorCount(20_000, weekAgo, NOW, 300), 7 * 288 + 300);
  // the depth of the live chart plays no part during a replay
  assert.equal(indicatorCount(5_000, weekAgo, NOW, H1), 168 + 300);
});

test("a replay that began in the future of this clock still gets a bar", () => {
  assert.equal(indicatorCount(20_000, NOW + 5 * H1, NOW, H1), 300);
});

test("no indicator is asked to cover more than the server will give", () => {
  assert.equal(indicatorCount(20_000, NOW - 3 * 365 * 86_400, NOW, 60), MAX_INDICATOR_BARS);
  assert.equal(indicatorCount(500_000, 0, NOW, H1), MAX_INDICATOR_BARS);
  assert.equal(indicatorCount(0, 0, NOW, H1), 1);
});

const line = (times: number[]) => ({ name: "x", data: times.map((time) => ({ time, value: time / 10 })) });

test("lines are cut at the first candle", () => {
  const [cut] = plotsFrom([line([10, 20, 30, 40])], 25);
  assert.deepEqual(
    cut.data.map((d) => d.time),
    [30, 40],
  );
  assert.equal(cut.name, "x"); // the rest of the line is kept
});

test("a point on the first candle stays", () => {
  const [cut] = plotsFrom([line([10, 20, 30])], 20);
  assert.deepEqual(
    cut.data.map((d) => d.time),
    [20, 30],
  );
});

test("lines that lose nothing are handed back as they were", () => {
  const plots = [line([10, 20]), line([15, 25])];
  assert.equal(plotsFrom(plots, 10), plots);
  assert.equal(plotsFrom(plots, 0), plots); // no candles yet: nothing to cut at
  const first = plots[0];
  const mixed = plotsFrom(plots, 15);
  assert.notEqual(mixed, plots);
  assert.equal(mixed[1], plots[1]); // the line that lost nothing is the same object
  assert.notEqual(mixed[0], first);
});

test("a line that ends before the first candle is empty", () => {
  const [cut] = plotsFrom([line([10, 20])], 100);
  assert.deepEqual(cut.data, []);
});
