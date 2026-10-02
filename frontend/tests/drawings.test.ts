import assert from "node:assert/strict";
import { test } from "node:test";
import {
  averageRange,
  createDrawing,
  distToSegment,
  draft,
  drag,
  extendSegment,
  layout,
  styleOf,
  tidy,
  type Drawing,
  type LinePrim,
  type Mapper,
  type RectPrim,
  type TextPrim,
} from "../src/lib/drawings";

const near = (a: number, b: number, tolerance = 1e-6) => Math.abs(a - b) <= tolerance;
const nearAll = (a: number[], b: number[]) => a.length === b.length && a.every((v, i) => near(v, b[i]));

/** A chart 1000 x 500 px where 1 second is 0.01 px and price 2.0 is the top, 1.0 the bottom. */
const flat: Mapper = {
  x: (t) => t * 0.01,
  y: (p) => (2 - p) * 500,
  time: (x) => x / 0.01,
  price: (y) => 2 - y / 500,
  width: 1000,
  height: 500,
};

/** The same, but with a weekend: the 100 seconds from t=5000 to t=5100 have no width at all. */
const gap = (t: number) => (t <= 5000 ? t : t >= 5100 ? t - 100 : 5000);
const withGap: Mapper = {
  ...flat,
  x: (t) => gap(t) * 0.01,
  time: (x) => (x / 0.01 <= 5000 ? x / 0.01 : x / 0.01 + 100),
};

const trend = (extra = {}): Drawing => ({
  id: "a",
  type: "trendline",
  points: [{ time: 1000, price: 1.8 }, { time: 3000, price: 1.4 }],
  style: extra,
});
const rect = (extra = {}): Drawing => ({
  id: "r",
  type: "rectangle",
  points: [{ time: 2000, price: 1.8 }, { time: 4000, price: 1.2 }],
  style: extra,
});
const lines = (d: Drawing, m = flat) => layout(d, m).prims.filter((p): p is LinePrim => p.k === "line");
const rects = (d: Drawing, m = flat) => layout(d, m).prims.filter((p): p is RectPrim => p.k === "rect");

test("a trend line runs between its two points and has a handle on each", () => {
  const l = layout(trend(), flat);
  const line = l.prims[0] as LinePrim;
  assert.ok(nearAll([line.x1, line.y1, line.x2, line.y2], [10, 100, 30, 300]));
  assert.deepEqual(l.handles.map((h) => h.id), ["p0", "p1"]);
});

test("a trend line can go on to the right, and to the left", () => {
  const right = lines(trend({ extend_right: true }))[0];
  assert.ok(right.x2 >= 1000 + 2000, "reaches far past the plot");
  assert.ok(Math.abs((right.y2 - right.y1) / (right.x2 - right.x1) - 10) < 1e-9, "the slope stays the same");
  const both = lines(trend({ extend_left: true, extend_right: true }))[0];
  assert.ok(both.x1 <= -2000 && both.x2 >= 3000);
});

test("a rectangle is extended to the right unless told otherwise", () => {
  const extended = rects(rect())[0];
  assert.equal(extended.x, 20);
  assert.ok(extended.x + extended.w >= flat.width, "its fill reaches the right edge of the plot");
  const top = lines(rect()).find((p) => p.y1 === p.y2 && near(p.y1, 100))!;
  assert.ok(top.x2 >= flat.width, "so do its top and bottom");
  const side = lines(rect()).find((p) => p.x1 === p.x2 && near(p.x1, 40))!;
  assert.ok(side, "the right side stays where it was drawn");
  assert.equal(side.dash, "3 4", "...as a quiet dotted line");

  const closed = rects(rect({ extend_right: false }))[0];
  assert.equal(closed.x + closed.w, 40, "it ends at its right side");
  assert.equal(lines(rect({ extend_right: false })).find((p) => p.x1 === p.x2 && near(p.x1, 40))!.dash, undefined);
});

test("a rectangle has a handle on each corner and side, whichever way round it was drawn", () => {
  const flipped: Drawing = { ...rect(), points: [{ time: 4000, price: 1.2 }, { time: 2000, price: 1.8 }] };
  for (const d of [rect(), flipped]) {
    const handles = layout(d, flat).handles;
    assert.deepEqual(handles.map((h) => h.id), ["tl", "tr", "bl", "br", "t", "b", "l", "r"]);
    const tl = handles.find((h) => h.id === "tl")!;
    assert.ok(nearAll([tl.x, tl.y], [20, 100]));
    const br = handles.find((h) => h.id === "br")!;
    assert.ok(nearAll([br.x, br.y], [40, 400]));
  }
});

test("a channel's second line is the first one shifted by the third point", () => {
  const d: Drawing = {
    id: "c",
    type: "channel",
    points: [{ time: 1000, price: 1.8 }, { time: 3000, price: 1.6 }, { time: 2000, price: 1.3 }],
    style: {},
  };
  const l = layout(d, flat);
  const [first, second, middle] = l.prims.filter((p): p is LinePrim => p.k === "line");
  // at x=20 (t=2000) the base line is at y=150 and the third point at y=350: the second line is 200 px lower
  assert.ok(near(second.y1 - first.y1, 200), "the second line is shifted by the vertical distance of the third point");
  assert.ok(near(second.y2 - first.y2, second.y1 - first.y1), "...and is parallel");
  assert.ok(near(middle.y1, first.y1 + (second.y1 - first.y1) / 2), "the dashed middle line is halfway");
  assert.deepEqual(l.handles.map((h) => h.id), ["p0", "p1", "p2"]);
});

test("a long position has its target above and its stop below; a short is the other way", () => {
  const long = createDrawing("long", [{ time: 1000, price: 1.5 }], { barSeconds: 100, risk: 0.1 });
  assert.equal(long.points.length, 3);
  assert.ok(long.points[1].price > long.points[0].price && long.points[2].price < long.points[0].price);
  assert.equal(long.points[1].time, long.points[2].time, "target and stop end together");
  assert.ok(Math.abs(long.points[1].price - 1.7) < 1e-9 && Math.abs(long.points[2].price - 1.4) < 1e-9, "target at twice the stop distance");
  const short = createDrawing("short", [{ time: 1000, price: 1.5 }], { barSeconds: 100, risk: 0.1 });
  assert.ok(short.points[1].price < short.points[0].price && short.points[2].price > short.points[0].price);

  const texts = layout(long, flat).prims.filter((p): p is TextPrim => p.k === "text").map((t) => t.text);
  assert.ok(texts.some((t) => t.startsWith("Target 1.70000")) && texts.some((t) => t.startsWith("Stop 1.40000")));
  assert.ok(texts.some((t) => t.includes("Long") && t.includes("R:R 2.00")));
  assert.deepEqual(layout(long, flat).handles.map((h) => h.id), ["move", "w", "tp", "sl"]);
});

test("a position box with no average range to go by still gets a stop", () => {
  const d = createDrawing("long", [{ time: 1000, price: 2 }], { barSeconds: 60, risk: 0 });
  assert.ok(d.points[2].price < 2 && d.points[1].price > 2);
});

test("horizontal and vertical lines cross the whole plot", () => {
  const h: Drawing = { id: "h", type: "hline", points: [{ time: 0, price: 1.5 }], style: { text: "mid" } };
  const hl = layout(h, flat);
  const line = hl.prims[0] as LinePrim;
  assert.deepEqual([line.x1, line.x2, line.y1], [0, 1000, 250]);
  assert.ok(hl.prims.some((p) => p.k === "text" && p.text === "mid"));
  const v: Drawing = { id: "v", type: "vline", points: [{ time: 3000, price: 0 }], style: {} };
  const vl = layout(v, flat).prims[0] as LinePrim;
  assert.deepEqual([vl.x1, vl.x2, vl.y1, vl.y2], [30, 30, 0, 500]);
});

test("a drawing the chart cannot place yet draws nothing", () => {
  const nothing: Mapper = { ...flat, x: () => null };
  for (const d of [trend(), rect()]) assert.deepEqual(layout(d, nothing), { prims: [], handles: [] });
});

test("styles fall back to the defaults of their kind", () => {
  assert.equal(styleOf(trend()).width, 2);
  assert.equal(styleOf(rect()).extend_right, true);
  assert.equal(styleOf(rect({ extend_right: false })).extend_right, false);
  assert.equal(styleOf({ ...trend(), style: { color: null as unknown as string } }).color, "#2962ff", "a null from the server is no choice");
});

// -- dragging ----------------------------------------------------------------------------------------------------
const at = (x: number, y: number, m = flat) => ({ time: m.time(x)!, price: m.price(y)!, x, y });

test("a handle takes the point to where the pointer is", () => {
  const moved = drag(trend(), "p1", at(30, 300), at(50, 250), flat);
  assert.deepEqual(moved.points[0], trend().points[0]);
  assert.ok(Math.abs(moved.points[1].time - 5000) < 1e-6 && Math.abs(moved.points[1].price - 1.5) < 1e-9);
});

test("dragging the body carries every point by what the pointer moved", () => {
  const moved = drag(trend(), "move", at(20, 200), at(70, 150), flat);
  assert.ok(Math.abs(moved.points[0].time - 6000) < 1e-6 && Math.abs(moved.points[1].time - 8000) < 1e-6);
  assert.ok(near(moved.points[0].price, 1.9) && near(moved.points[1].price, 1.5), "the pointer went up 0.1");
});

test("a drawing dragged over a weekend follows the pointer, not the clock", () => {
  // a line from t=4000 to t=4500, dragged 1 px per 100 s of chart: across the 100 s gap in the chart
  const d: Drawing = { id: "w", type: "trendline", points: [{ time: 4900, price: 1.5 }, { time: 5200, price: 1.5 }], style: {} };
  const before = [withGap.x(4900)!, withGap.x(5200)!];
  const moved = drag(d, "move", at(49, 250, withGap), at(59, 250, withGap), withGap);
  const after = [withGap.x(moved.points[0].time)!, withGap.x(moved.points[1].time)!];
  assert.ok(Math.abs(after[0] - before[0] - 10) < 1e-6 && Math.abs(after[1] - before[1] - 10) < 1e-6, `${before} -> ${after}`);
});

test("a horizontal line only moves up and down, a vertical one only sideways", () => {
  const h: Drawing = { id: "h", type: "hline", points: [{ time: 7, price: 1.5 }], style: {} };
  const hm = drag(h, "move", at(10, 250), at(90, 300), flat);
  assert.equal(hm.points[0].time, 7);
  assert.ok(Math.abs(hm.points[0].price - 1.4) < 1e-9);
  const v: Drawing = { id: "v", type: "vline", points: [{ time: 3000, price: 9 }], style: {} };
  const vm = drag(v, "move", at(30, 100), at(50, 400), flat);
  assert.equal(vm.points[0].price, 9);
  assert.ok(Math.abs(vm.points[0].time - 5000) < 1e-6);
});

test("the sides and corners of a rectangle move only what they hold, and it stays the right way round", () => {
  const right = drag(rect(), "r", at(40, 250), at(60, 250), flat);
  assert.ok(Math.abs(right.points[1].time - 6000) < 1e-6 && right.points[0].time === 2000);
  const top = drag(rect(), "t", at(30, 100), at(30, 50), flat);
  assert.ok(Math.abs(top.points[0].price - 1.9) < 1e-9 && Math.abs(top.points[1].price - 1.2) < 1e-9);
  const bl = drag(rect(), "bl", at(20, 400), at(10, 450), flat);
  assert.ok(Math.abs(bl.points[0].time - 1000) < 1e-6 && Math.abs(bl.points[1].price - 1.1) < 1e-9);
  // dragging the left side past the right one turns the rectangle over instead of giving it a negative width
  const over = drag(rect(), "l", at(20, 250), at(60, 250), flat);
  assert.ok(over.points[0].time <= over.points[1].time);
  assert.ok(Math.abs(over.points[0].time - 4000) < 1e-6 && Math.abs(over.points[1].time - 6000) < 1e-6);
});

test("a position box: width, target and stop are separate handles", () => {
  const d = createDrawing("long", [{ time: 1000, price: 1.5 }], { barSeconds: 100, risk: 0.1 });
  const end = d.points[1].time;
  const wider = drag(d, "w", at(0, 0), at((end + 500) * 0.01, 0), flat, 100);
  assert.ok(Math.abs(wider.points[1].time - (end + 500)) < 1e-6 && wider.points[2].time === wider.points[1].time);
  const tooNarrow = drag(d, "w", at(0, 0), at(0, 0), flat, 100);
  assert.equal(tooNarrow.points[1].time, 1100, "never narrower than one bar, never before the entry");
  const tp = drag(d, "tp", at(0, 0), at(0, 100), flat);
  assert.ok(Math.abs(tp.points[1].price - 1.8) < 1e-9 && tp.points[2].price === d.points[2].price);
  const sl = drag(d, "sl", at(0, 0), at(0, 400), flat);
  assert.ok(Math.abs(sl.points[2].price - 1.2) < 1e-9 && sl.points[1].price === d.points[1].price);
});

// -- the rest -----------------------------------------------------------------------------------------------------------
test("what is being drawn is previewed with the pointer as its next point", () => {
  const ctx = { barSeconds: 60, risk: 0.1 };
  assert.equal(draft("trendline", [], { time: 1, price: 1 }, ctx), null);
  const line = draft("trendline", [{ time: 1, price: 1 }], { time: 5, price: 2 }, ctx)!;
  assert.deepEqual(line.points, [{ time: 1, price: 1 }, { time: 5, price: 2 }]);
  assert.equal(line.id, "draft");
  const box = draft("rectangle", [{ time: 1, price: 1 }], { time: 5, price: 2 }, ctx)!;
  assert.equal(box.type, "rectangle");
  assert.equal(box.style.extend_right, true, "the preview already looks like the result");
  const base = draft("channel", [{ time: 1, price: 1 }, { time: 5, price: 2 }], { time: 9, price: 3 }, ctx)!;
  assert.equal(base.type, "channel");
  const half = draft("channel", [{ time: 1, price: 1 }], { time: 5, price: 2 }, ctx)!;
  assert.equal(half.type, "trendline", "until the third click the channel is its base line");
  assert.equal(draft("long", [{ time: 1, price: 1 }], { time: 5, price: 2 }, ctx), null, "a position box takes one click");
});

test("the average range is the mean true range of the last bars", () => {
  const bars = [
    { high: 10, low: 8, close: 9 },
    { high: 11, low: 9, close: 10 },
    { high: 13, low: 10, close: 12 },
  ];
  assert.equal(averageRange(bars, 14), (2 + 3) / 2);
  assert.equal(averageRange(bars.slice(0, 1)), 0);
  assert.equal(averageRange([]), 0);
});

test("a segment is extended to the edges the style asks for", () => {
  assert.deepEqual(extendSegment(10, 100, 30, 300, false, false, 1000), [10, 100, 30, 300]);
  const [, , bx, by] = extendSegment(10, 100, 30, 300, true, false, 1000);
  assert.equal(bx, 3000);
  assert.equal(by, 100 + 10 * (3000 - 10));
  const turned = extendSegment(30, 300, 10, 100, true, false, 1000);
  assert.deepEqual([turned[0], turned[1]], [10, 100], "the left end comes first");
  assert.deepEqual(extendSegment(5, 0, 5, 100, true, true, 1000), [5, 0, 5, 100], "a vertical line cannot be extended sideways");
});

test("tidy keeps whole seconds and tidy prices", () => {
  const d = tidy({ ...trend(), points: [{ time: 1000.6, price: 1.123456789012 }, { time: 2000.2, price: 1.5 }] });
  assert.deepEqual(d.points, [{ time: 1001, price: 1.12345679 }, { time: 2000, price: 1.5 }]);
});

test("the distance to a segment is measured to its nearest point", () => {
  assert.equal(distToSegment(5, 5, 0, 0, 10, 0), 5);
  assert.equal(distToSegment(-3, 4, 0, 0, 10, 0), 5, "past the end it is the distance to the end");
  assert.equal(distToSegment(3, 4, 0, 0, 0, 0), 5, "a segment that is a point");
});

test("each new drawing gets an id of its own", () => {
  const ids = new Set(Array.from({ length: 200 }, () => createDrawing("trendline", [{ time: 1, price: 1 }, { time: 2, price: 2 }], { barSeconds: 1, risk: 1 }).id));
  assert.equal(ids.size, 200);
});
