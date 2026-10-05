// Small pure helpers on sorted bar arrays, shared by the chart and the bar store.

import type { Bar } from "./types";

/** Index of the first bar (or other point in time order) whose time is >= `time` (`bars.length` when there is none). */
export function lowerBound(bars: readonly { time: number }[], time: number): number {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time < time) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Index of the bar closest in time to `time` (0 for an empty array). */
export function nearestIndex(bars: Bar[], time: number): number {
  const i = lowerBound(bars, time);
  if (i <= 0) return 0;
  if (i >= bars.length) return bars.length - 1;
  return time - bars[i - 1].time <= bars[i].time - time ? i - 1 : i;
}

/** The bar at exactly `time`, if there is one. */
export function barAt(bars: Bar[], time: number): Bar | undefined {
  const bar = bars[lowerBound(bars, time)];
  return bar && bar.time === time ? bar : undefined;
}

/** True when two bars draw the same candle. */
export function sameCandle(a: Bar, b: Bar): boolean {
  return (
    a === b ||
    (a.time === b.time &&
      a.open === b.open &&
      a.high === b.high &&
      a.low === b.low &&
      a.close === b.close)
  );
}

/**
 * Whether the chart can go from `before` to `bars` by rewriting candles it already has
 * and adding newer ones at the end, which is all an in-place update can do. `first` is
 * where the two start to differ. A candle that appears *between* two the chart holds
 * (the terminal has one the page never saw) cannot be put there that way and needs
 * the whole series replaced.
 */
export function canPatchTail(before: Bar[], bars: Bar[], first: number): boolean {
  for (let i = first; i < before.length; i++) {
    if (bars[i].time !== before[i].time) return false; // not the same candle: one was inserted or dropped
  }
  for (let i = Math.max(first, before.length); i < bars.length; i++) {
    if (bars[i].time <= bars[i - 1].time) return false; // not in time order
  }
  return true;
}

/** Index of the first position where the two arrays draw different candles. */
export function firstDifference(a: Bar[], b: Bar[]): number {
  const shared = Math.min(a.length, b.length);
  let i = 0;
  while (i < shared && sameCandle(a[i], b[i])) i++;
  return i;
}
