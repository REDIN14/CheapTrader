// Chart drawings: what they are, how each kind is laid out on the screen, and what dragging a
// handle does to it. Pure functions of numbers (no React, no DOM), so they can be tested alone.
//
// A drawing is anchored to the market, not to the screen: its points are (time, price). A `Mapper`
// turns those into pixels (and back) for whatever the chart shows right now.

export type DrawingType =
  | "trendline"
  | "rectangle"
  | "long"
  | "short"
  | "channel"
  | "hline"
  | "vline"
  | "polyline"
  | "text";

/** The tools in the drawing toolbar. (The other kinds come from scripts and indicators.) */
export type Tool = "trendline" | "short" | "long" | "rectangle" | "channel";

export interface DrawingPoint {
  time: number;
  price: number;
}

export interface DrawingStyle {
  color?: string;
  width?: number;
  dash?: "solid" | "dashed" | "dotted";
  fill?: string;
  fill_opacity?: number;
  extend_right?: boolean;
  extend_left?: boolean;
  text?: string;
  font_size?: number;
  /** How big a trade a long / short box stands for (`risk_mode` says which of the three counts). */
  risk_mode?: "percent" | "amount" | "lots";
  risk_percent?: number;
  risk_amount?: number;
  lots?: number;
}

export interface Drawing {
  id: string;
  type: DrawingType;
  points: DrawingPoint[];
  style: DrawingStyle;
  /** A locked drawing cannot be moved or removed (its look can still be changed). */
  locked?: boolean;
  created?: number;
  /** The indicator that draws it (such drawings are read-only and follow the indicator). */
  owner?: string;
}

/** Pixels <-> market, for the plot area as it is now. `x` / `y` are null while the chart has nothing to map. */
export interface Mapper {
  x: (time: number) => number | null;
  y: (price: number) => number | null;
  time: (x: number) => number | null;
  price: (y: number) => number | null;
  /** The plot area in px (the candles, without the price scale and the time axis). */
  width: number;
  height: number;
}

export const COLORS = ["#2962ff", "#089981", "#f23645", "#ff9800", "#e91e63", "#9c27b0", "#00bcd4", "#d1d4dc"];

export const GREEN = "#089981";
export const RED = "#f23645";
export const BLUE = "#2962ff";

export const TOOL_NAMES: Record<Tool, string> = {
  trendline: "Trend line",
  short: "Short position",
  long: "Long position",
  rectangle: "Rectangle",
  channel: "Parallel channel",
};

/** How many clicks (points) a tool takes before the drawing is finished. */
export const TOOL_POINTS: Record<Tool, number> = {
  trendline: 2,
  rectangle: 2,
  channel: 3,
  long: 1,
  short: 1,
};

/** Kinds whose style has an "extend to the right" option. */
export const CAN_EXTEND: DrawingType[] = ["trendline", "rectangle", "channel"];

// -- primitives (what a drawing is laid out as) ------------------------------------------------
export interface LinePrim {
  k: "line";
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  width: number;
  dash?: string;
  /** Pointer target for selecting / moving the drawing. */
  hit?: boolean;
}

export interface RectPrim {
  k: "rect";
  x: number;
  y: number;
  w: number;
  h: number;
  fill?: string;
  fillOpacity?: number;
  stroke?: string;
  width?: number;
  dash?: string;
  hit?: boolean;
}

export interface PolyPrim {
  k: "poly";
  points: [number, number][];
  fill?: string;
  fillOpacity?: number;
  stroke?: string;
  width?: number;
  dash?: string;
  closed?: boolean;
  hit?: boolean;
}

export interface TextPrim {
  k: "text";
  x: number;
  y: number;
  text: string;
  color: string;
  size: number;
  anchor?: "start" | "middle" | "end";
}

export type Prim = LinePrim | RectPrim | PolyPrim | TextPrim;

export interface HandleSpec {
  id: string;
  x: number;
  y: number;
  cursor: string;
}

export interface Layout {
  prims: Prim[];
  handles: HandleSpec[];
}

const DASH: Record<string, string | undefined> = { solid: undefined, dashed: "7 5", dotted: "2 4" };

export function dashOf(style: DrawingStyle, fallback: "solid" | "dashed" | "dotted" = "solid"): string | undefined {
  return DASH[style.dash ?? fallback];
}

// -- defaults ---------------------------------------------------------------------------------
export const DEFAULT_STYLE: Record<DrawingType, DrawingStyle> = {
  trendline: { color: BLUE, width: 2 },
  rectangle: { color: BLUE, width: 1, fill: BLUE, fill_opacity: 0.15, extend_right: true },
  channel: { color: BLUE, width: 2, fill: BLUE, fill_opacity: 0.1 },
  long: { color: GREEN, width: 1 },
  short: { color: RED, width: 1 },
  hline: { color: BLUE, width: 1 },
  vline: { color: BLUE, width: 1 },
  polyline: { color: BLUE, width: 2 },
  text: { color: "#d1d4dc", font_size: 13 },
};

export function styleOf(d: Drawing): Required<Pick<DrawingStyle, "color" | "width">> & DrawingStyle {
  const base = DEFAULT_STYLE[d.type];
  return {
    ...base,
    ...Object.fromEntries(Object.entries(d.style).filter(([, v]) => v !== undefined && v !== null)),
    color: d.style.color ?? base.color ?? BLUE,
    width: d.style.width ?? base.width ?? 1,
  };
}

/** Average true range of the last `n` bars: what a long / short position box uses for its first stop distance. */
export function averageRange(bars: { high: number; low: number; close: number }[], n = 14): number {
  const tail = bars.slice(-(n + 1));
  if (tail.length < 2) return 0;
  let sum = 0;
  for (let i = 1; i < tail.length; i++) {
    sum += Math.max(
      tail[i].high - tail[i].low,
      Math.abs(tail[i].high - tail[i - 1].close),
      Math.abs(tail[i].low - tail[i - 1].close),
    );
  }
  return sum / (tail.length - 1);
}

/** The drawing with whole-second times and tidy prices: what is kept and sent to the server. */
export function tidy(d: Drawing): Drawing {
  return { ...d, points: d.points.map((p) => ({ time: Math.round(p.time), price: Number(p.price.toFixed(8)) })) };
}

let counter = 0;
export function newId(): string {
  counter += 1;
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 10)
      : Math.random().toString(16).slice(2, 12);
  return `${random}${counter.toString(16)}`;
}

export interface CreateContext {
  /** Seconds one bar takes (for the width of a position box). */
  barSeconds: number;
  /** Price distance for the first stop of a position box. */
  risk: number;
  /** Reward-to-risk of a new position box. */
  ratio?: number;
}

/**
 * The drawing a finished set of clicks makes. `points` are the clicks, in order; a position box takes a
 * single click (its entry) and fills in a width, a target and a stop that can be dragged afterwards.
 */
export function createDrawing(tool: Tool, points: DrawingPoint[], ctx: CreateContext): Drawing {
  const style = { ...DEFAULT_STYLE[tool] };
  if (tool === "long" || tool === "short") {
    const [entry] = points;
    const sign = tool === "long" ? 1 : -1;
    const risk = ctx.risk > 0 ? ctx.risk : Math.abs(entry.price) * 0.0025;
    const end = entry.time + ctx.barSeconds * 24;
    return {
      id: newId(),
      type: tool,
      points: [
        entry,
        { time: end, price: entry.price + sign * risk * (ctx.ratio ?? 2) },
        { time: end, price: entry.price - sign * risk },
      ],
      style,
    };
  }
  return { id: newId(), type: tool, points: points.map((p) => ({ ...p })), style };
}

// -- laying a drawing out ---------------------------------------------------------------------
const line = (x1: number, y1: number, x2: number, y2: number, color: string, width: number, extra: Partial<LinePrim> = {}): LinePrim => ({
  k: "line",
  x1,
  y1,
  x2,
  y2,
  color,
  width,
  ...extra,
});

/** Where the line through (x1,y1) and (x2,y2) meets x = `x` (null for a vertical line). */
function yAt(x1: number, y1: number, x2: number, y2: number, x: number): number | null {
  if (x1 === x2) return null;
  return y1 + ((y2 - y1) * (x - x1)) / (x2 - x1);
}

/** The two ends of a segment, pushed out to the plot's edges where the style asks for it. */
export function extendSegment(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  right: boolean,
  left: boolean,
  width: number,
): [number, number, number, number] {
  let [ax, ay, bx, by] = [x1, y1, x2, y2];
  if (ax > bx) [ax, ay, bx, by] = [bx, by, ax, ay];
  const farRight = width + 2000;
  if (right) {
    const y = yAt(ax, ay, bx, by, farRight);
    if (y != null) [bx, by] = [farRight, y];
  }
  if (left) {
    const y = yAt(ax, ay, bx, by, -2000);
    if (y != null) [ax, ay] = [-2000, y];
  }
  return [ax, ay, bx, by];
}

/** Digits a price is written with in a drawing's labels. */
export function formatPrice(price: number, digits: number): string {
  return price.toFixed(Math.max(0, Math.min(8, digits)));
}

function rectParts(d: Drawing) {
  const [a, b] = d.points;
  return {
    t0: Math.min(a.time, b.time),
    t1: Math.max(a.time, b.time),
    hi: Math.max(a.price, b.price),
    lo: Math.min(a.price, b.price),
  };
}

/**
 * What a drawing is laid out as. `notes` are extra lines of words for the drawing (a position box shows how
 * big its trade is) that only the caller can work out.
 */
export function layout(d: Drawing, m: Mapper, digits = 5, notes: string[] = []): Layout {
  const s = styleOf(d);
  const color = s.color;
  const width = s.width;
  const dash = dashOf(s);
  const prims: Prim[] = [];
  const handles: HandleSpec[] = [];
  const px = d.points.map((p) => ({ x: m.x(p.time), y: m.y(p.price) }));

  switch (d.type) {
    case "trendline": {
      const [a, b] = px;
      if (a.x == null || a.y == null || b.x == null || b.y == null) break;
      const [x1, y1, x2, y2] = extendSegment(a.x, a.y, b.x, b.y, !!s.extend_right, !!s.extend_left, m.width);
      prims.push(line(x1, y1, x2, y2, color, width, { dash, hit: true }));
      handles.push({ id: "p0", x: a.x, y: a.y, cursor: "move" }, { id: "p1", x: b.x, y: b.y, cursor: "move" });
      break;
    }

    case "rectangle": {
      const { t0, t1, hi, lo } = rectParts(d);
      const xl = m.x(t0);
      const xr = m.x(t1);
      const yt = m.y(hi);
      const yb = m.y(lo);
      if (xl == null || xr == null || yt == null || yb == null) break;
      const reach = s.extend_right ? Math.max(xr, m.width + 2) : xr;
      const fill = s.fill ?? color;
      prims.push({ k: "rect", x: xl, y: yt, w: Math.max(0, reach - xl), h: yb - yt, fill, fillOpacity: s.fill_opacity ?? 0.15, hit: true });
      prims.push(line(xl, yt, reach, yt, color, width, { dash, hit: true }));
      prims.push(line(xl, yb, reach, yb, color, width, { dash, hit: true }));
      prims.push(line(xl, yt, xl, yb, color, width, { dash, hit: true }));
      // with the box extended, the right side stays where it was drawn, as a quieter line
      prims.push(line(xr, yt, xr, yb, color, width, { dash: s.extend_right ? "3 4" : dash, hit: true }));
      const xm = (xl + xr) / 2;
      const ym = (yt + yb) / 2;
      handles.push(
        { id: "tl", x: xl, y: yt, cursor: "nwse-resize" },
        { id: "tr", x: xr, y: yt, cursor: "nesw-resize" },
        { id: "bl", x: xl, y: yb, cursor: "nesw-resize" },
        { id: "br", x: xr, y: yb, cursor: "nwse-resize" },
        { id: "t", x: xm, y: yt, cursor: "ns-resize" },
        { id: "b", x: xm, y: yb, cursor: "ns-resize" },
        { id: "l", x: xl, y: ym, cursor: "ew-resize" },
        { id: "r", x: xr, y: ym, cursor: "ew-resize" },
      );
      break;
    }

    case "channel": {
      const [a, b, c] = px;
      if (a.x == null || a.y == null || b.x == null || b.y == null || c.x == null || c.y == null) break;
      // the second line is the first one shifted by the height of the third point above / below it
      const base = yAt(a.x, a.y, b.x, b.y, c.x);
      const shift = base == null ? c.y - a.y : c.y - base;
      const [x1, y1, x2, y2] = extendSegment(a.x, a.y, b.x, b.y, !!s.extend_right, !!s.extend_left, m.width);
      const fill = s.fill ?? color;
      prims.push({
        k: "poly",
        points: [
          [x1, y1],
          [x2, y2],
          [x2, y2 + shift],
          [x1, y1 + shift],
        ],
        fill,
        fillOpacity: s.fill_opacity ?? 0.1,
        closed: true,
      });
      prims.push(line(x1, y1, x2, y2, color, width, { dash, hit: true }));
      prims.push(line(x1, y1 + shift, x2, y2 + shift, color, width, { dash, hit: true }));
      prims.push(line(x1, y1 + shift / 2, x2, y2 + shift / 2, color, 1, { dash: "5 5" }));
      handles.push(
        { id: "p0", x: a.x, y: a.y, cursor: "move" },
        { id: "p1", x: b.x, y: b.y, cursor: "move" },
        { id: "p2", x: c.x, y: c.y, cursor: "move" },
      );
      break;
    }

    case "long":
    case "short": {
      const [entry, target, stop] = d.points;
      const x0 = m.x(entry.time);
      const x1 = m.x(target.time);
      const yEntry = m.y(entry.price);
      const yTp = m.y(target.price);
      const ySl = m.y(stop.price);
      if (x0 == null || x1 == null || yEntry == null || yTp == null || ySl == null) break;
      const left = Math.min(x0, x1);
      const w = Math.abs(x1 - x0);
      const tpColor = GREEN;
      const slColor = RED;
      // the words sit on the tinted boxes, so they are lighter than the lines
      prims.push({ k: "rect", x: left, y: Math.min(yEntry, yTp), w, h: Math.abs(yTp - yEntry), fill: tpColor, fillOpacity: 0.18, hit: true });
      prims.push({ k: "rect", x: left, y: Math.min(yEntry, ySl), w, h: Math.abs(ySl - yEntry), fill: slColor, fillOpacity: 0.18, hit: true });
      prims.push(line(left, yTp, left + w, yTp, tpColor, 1, { hit: true }));
      prims.push(line(left, ySl, left + w, ySl, slColor, 1, { hit: true }));
      prims.push(line(left, yEntry, left + w, yEntry, "#9598a1", 1, { hit: true }));
      prims.push(line(left, Math.min(yTp, ySl), left, Math.max(yTp, ySl), "#9598a1", 1, { hit: true }));
      prims.push(line(left + w, Math.min(yTp, ySl), left + w, Math.max(yTp, ySl), "#9598a1", 1, { hit: true }));
      const pct = (p: number) => `${((p - entry.price) / (entry.price || 1) * 100).toFixed(2)}%`;
      const risk = Math.abs(entry.price - stop.price);
      const reward = Math.abs(target.price - entry.price);
      const ratio = risk > 0 ? reward / risk : 0;
      const fs = 12;
      const tpUp = yTp < yEntry;
      prims.push({
        k: "text", x: left + 6, y: tpUp ? yTp + 15 : yTp - 6, color: "#5ee6cb", size: fs,
        text: `Target ${formatPrice(target.price, digits)} (${pct(target.price)})`,
      });
      prims.push({
        k: "text", x: left + 6, y: ySl > yEntry ? ySl - 6 : ySl + 15, color: "#ff8f99", size: fs,
        text: `Stop ${formatPrice(stop.price, digits)} (${pct(stop.price)})`,
      });
      prims.push({
        k: "text", x: left + w / 2, y: yEntry - 5, anchor: "middle", color: "#d1d4dc", size: fs,
        text: `${d.type === "long" ? "Long" : "Short"} · R:R ${ratio.toFixed(2)}`,
      });
      notes.forEach((line, i) => {
        prims.push({ k: "text", x: left + w / 2, y: yEntry + 14 + i * 14, anchor: "middle", color: "#b2b5be", size: 11, text: line });
      });
      handles.push(
        { id: "move", x: left, y: yEntry, cursor: "move" },
        { id: "w", x: left + w, y: yEntry, cursor: "ew-resize" },
        { id: "tp", x: left + w, y: yTp, cursor: "ns-resize" },
        { id: "sl", x: left + w, y: ySl, cursor: "ns-resize" },
      );
      break;
    }

    case "hline": {
      const y = m.y(d.points[0].price);
      if (y == null) break;
      prims.push(line(0, y, m.width, y, color, width, { dash, hit: true }));
      if (s.text) prims.push({ k: "text", x: 6, y: y - 4, text: s.text, color, size: s.font_size ?? 12 });
      handles.push({ id: "move", x: Math.min(40, m.width / 2), y, cursor: "ns-resize" });
      break;
    }

    case "vline": {
      const x = m.x(d.points[0].time);
      if (x == null) break;
      prims.push(line(x, 0, x, m.height, color, width, { dash, hit: true }));
      if (s.text) prims.push({ k: "text", x: x + 4, y: 14, text: s.text, color, size: s.font_size ?? 12 });
      handles.push({ id: "move", x, y: Math.min(40, m.height / 2), cursor: "ew-resize" });
      break;
    }

    case "polyline": {
      const pts = px.filter((p): p is { x: number; y: number } => p.x != null && p.y != null).map((p) => [p.x, p.y] as [number, number]);
      if (pts.length < 2) break;
      prims.push({ k: "poly", points: pts, stroke: color, width, dash, closed: false, hit: true });
      handles.push({ id: "move", x: pts[0][0], y: pts[0][1], cursor: "move" });
      break;
    }

    case "text": {
      const [p] = px;
      if (p.x == null || p.y == null) break;
      prims.push({ k: "text", x: p.x, y: p.y, text: s.text ?? "", color, size: s.font_size ?? 13 });
      handles.push({ id: "move", x: p.x, y: p.y, cursor: "move" });
      break;
    }
  }
  return { prims, handles };
}

// -- dragging ---------------------------------------------------------------------------------
export interface Pointer {
  time: number;
  price: number;
  /** Where that is on the screen (needed to carry a drawing across a weekend gap, which has no width). */
  x?: number;
  y?: number;
}

/**
 * Carry every point by what the pointer moved. Prices move by the same amount; times move by the same number
 * of *pixels* (not seconds), because the chart has no room for the hours the market is closed: a box dragged
 * over a weekend must follow the pointer, not drift by two days.
 */
function carry(d: Drawing, from: Pointer, now: Pointer, m: Mapper | undefined, { time = true, price = true } = {}): Drawing {
  const dp = now.price - from.price;
  const dt = now.time - from.time;
  const dx = from.x != null && now.x != null ? now.x - from.x : null;
  const moved = (t: number): number => {
    if (m && dx != null) {
      const x = m.x(t);
      const shifted = x == null ? null : m.time(x + dx);
      if (shifted != null) return shifted;
    }
    return t + dt;
  };
  return {
    ...d,
    points: d.points.map((p) => ({ time: time ? moved(p.time) : p.time, price: price ? p.price + dp : p.price })),
  };
}

/**
 * The drawing after the pointer has moved from `from` to `now` while holding `handle` of `start`.
 * "move" carries the whole drawing; the other ids belong to the kind (see `layout`).
 */
export function drag(start: Drawing, handle: string, from: Pointer, now: Pointer, m?: Mapper, minWidth = 1): Drawing {
  if (handle === "move") {
    if (start.type === "hline") return carry(start, from, now, m, { time: false });
    if (start.type === "vline") return carry(start, from, now, m, { price: false });
    return carry(start, from, now, m);
  }
  const pts = start.points.map((p) => ({ ...p }));

  switch (start.type) {
    case "trendline":
      if (handle === "p0") pts[0] = { time: now.time, price: now.price };
      if (handle === "p1") pts[1] = { time: now.time, price: now.price };
      break;

    case "channel": {
      const i = handle === "p0" ? 0 : handle === "p1" ? 1 : handle === "p2" ? 2 : -1;
      if (i >= 0) pts[i] = { time: now.time, price: now.price };
      break;
    }

    case "rectangle": {
      let { t0, t1, hi, lo } = rectParts(start);
      if (handle.includes("l")) t0 = now.time;
      if (handle.includes("r")) t1 = now.time;
      if (handle === "tl" || handle === "tr" || handle === "t") hi = now.price;
      if (handle === "bl" || handle === "br" || handle === "b") lo = now.price;
      return {
        ...start,
        points: [
          { time: Math.min(t0, t1), price: Math.max(hi, lo) },
          { time: Math.max(t0, t1), price: Math.min(hi, lo) },
        ],
      };
    }

    case "long":
    case "short": {
      if (handle === "w") {
        const t = Math.max(pts[0].time + minWidth, now.time);
        pts[1] = { ...pts[1], time: t };
        pts[2] = { ...pts[2], time: t };
      } else if (handle === "tp") pts[1] = { ...pts[1], price: now.price };
      else if (handle === "sl") pts[2] = { ...pts[2], price: now.price };
      break;
    }
  }
  return { ...start, points: pts };
}

/** Rough distance from point (px, py) to the segment — used to decide what a click on empty space is near. */
export function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len2));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

/** What a drawing draft looks like while the next click is still to come: the clicks so far plus the pointer. */
export function draft(tool: Tool, placed: DrawingPoint[], pointer: DrawingPoint, ctx: CreateContext): Drawing | null {
  if (!placed.length) return null;
  if (tool === "long" || tool === "short") return null;
  const points = [...placed, pointer];
  if (tool === "channel" && points.length === 2) {
    // until the third click, the channel is its base line
    return { id: "draft", type: "trendline", points, style: { ...DEFAULT_STYLE.channel } };
  }
  return { ...createDrawing(tool, points.slice(0, TOOL_POINTS[tool]), ctx), id: "draft" };
}
