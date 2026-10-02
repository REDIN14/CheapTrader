// In-memory copies of the bar series the chart has shown, so going back to an
// interval (or a symbol) that was already open is instant instead of another
// 2 MB download and a full redraw.
//
// A series is kept as it was asked for: `requested` is the `count` that went to
// the backend. A short window (the newest QUICK_BARS bars) is enough for the
// chart to appear at once; the full depth follows in the background and takes
// its place.

import { api } from "./api";
import { lowerBound } from "./barMath";
import type { ViewHint } from "./chart";
import type { Bar, Timeframe } from "./types";

/** Bars fetched first: the opening view plus a long scroll back. */
export const QUICK_BARS = 1_500;
/** Bars re-read when a remembered series is shown again after being away. */
export const TAIL_BARS = 400;
/** A remembered series older than this is brought up to date when it is shown. */
export const STALE_MS = 1_500;
/** Series kept in memory (a 20,000-bar series is about 3 MB)… */
const MAX_SERIES = 10;
/** …and no more than this many bars in all, however deep the history was set. */
const MAX_BARS = 400_000;

export interface Series {
  bars: Bar[];
  /** The `count` the bars were requested with; fewer bars than that means there are no more. */
  requested: number;
  /** When they were fetched (ms since the epoch). */
  fetchedAt: number;
}

const series = new Map<string, Series>();
const inflight = new Map<string, Promise<Bar[]>>();

const seriesKey = (symbol: string, timeframe: Timeframe) => `${symbol}|${timeframe}`;
const newest = (bars: Bar[]) => (bars.length ? bars[bars.length - 1].time : 0);

/** A remembered series, marked as the most recently used. */
export function recall(symbol: string, timeframe: Timeframe): Series | undefined {
  const key = seriesKey(symbol, timeframe);
  const hit = series.get(key);
  if (hit) {
    series.delete(key);
    series.set(key, hit);
  }
  return hit;
}

/** Whether a series is already in memory (does not count as a use). */
export function has(symbol: string, timeframe: Timeframe): boolean {
  return series.has(seriesKey(symbol, timeframe));
}

export function remember(
  symbol: string,
  timeframe: Timeframe,
  bars: Bar[],
  requested: number,
): Series {
  const key = seriesKey(symbol, timeframe);
  const known = series.get(key);
  // A late answer for a shorter window must not push out a deeper series we hold.
  if (known && known.bars.length > bars.length && newest(known.bars) >= newest(bars)) {
    series.delete(key);
    series.set(key, known);
    return known;
  }
  const entry: Series = { bars, requested, fetchedAt: Date.now() };
  series.delete(key);
  series.set(key, entry);

  // Forget the least recently used until both limits hold (the newest entry stays).
  let total = 0;
  for (const s of series.values()) total += s.bars.length;
  while (series.size > 1 && (series.size > MAX_SERIES || total > MAX_BARS)) {
    const oldest = series.keys().next().value;
    if (oldest === undefined) break;
    total -= series.get(oldest)?.bars.length ?? 0;
    series.delete(oldest);
  }
  return entry;
}

/** Fetch bars; identical requests that are already on their way share one answer. */
export function fetchBars(symbol: string, timeframe: Timeframe, count: number): Promise<Bar[]> {
  const key = `${seriesKey(symbol, timeframe)}|${count}`;
  let pending = inflight.get(key);
  if (!pending) {
    pending = api.bars(symbol, timeframe, count).finally(() => inflight.delete(key));
    inflight.set(key, pending);
  }
  return pending;
}

/**
 * Bring a remembered series up to date with a fresh window of its newest bars.
 *
 * The result keeps the old bars before the window (the same objects) and takes
 * the window itself, so it equals what a full re-download would give. Returns
 * null when the window does not reach back to bars we already have — something
 * in between is missing and the whole series has to be fetched again.
 */
export function mergeTail(known: Bar[], fresh: Bar[]): Bar[] | null {
  if (!fresh.length) return known;
  if (!known.length) return fresh;
  if (fresh[0].time > known[known.length - 1].time) return null;
  const cut = lowerBound(known, fresh[0].time);
  return known.slice(0, cut).concat(fresh);
}

/**
 * How many of the newest bars of an interval it takes to show what the user is
 * looking at: at least the opening window, more when they are zoomed far out or
 * have scrolled back to an older date. (Weekends have no bars, so counting the
 * whole span errs on the generous side, which is what is wanted.)
 */
export function barsNeeded(hint: ViewHint | null, stepSeconds: number): number {
  if (!hint) return QUICK_BARS;
  const margin = 300;
  const zoom = Math.ceil(hint.visibleBars);
  if (hint.atEdge) return Math.max(QUICK_BARS, zoom + margin);
  const span = Math.max(0, hint.newestTime - hint.leftTime);
  return Math.max(QUICK_BARS, Math.ceil(span / stepSeconds) + zoom + margin);
}

/** Start loading a series nobody has asked for yet (the user is about to). */
export function prefetch(symbol: string, timeframe: Timeframe, count: number): void {
  if (has(symbol, timeframe)) return;
  const first = Math.min(count, QUICK_BARS);
  fetchBars(symbol, timeframe, first)
    .then((bars) => {
      if (!has(symbol, timeframe)) remember(symbol, timeframe, bars, first);
    })
    .catch(() => undefined); // the real request reports its own failure
}
