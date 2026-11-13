import type { Bar } from "./types";

/** Prefetch before the user runs out of candles on the left, at any zoom. */
export function needsHistory(range: { from: number; to: number } | null, count: number): boolean {
  return !!range && count > 0 && range.from < Math.max(100, (range.to - range.from) / 2);
}

/** Prepend a page without duplicates, replacing neither the live candle nor replay's cursor. */
export function prependBars(current: Bar[], page: Bar[]): Bar[] {
  const boundary = current[0]?.time ?? Infinity;
  const older = [...new Map(page.filter(b => b.time < boundary).map(b => [b.time, b])).values()]
    .sort((a, b) => a.time - b.time);
  return older.length ? older.concat(current) : current;
}
