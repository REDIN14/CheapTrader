// The candle that is being drawn right now: the newest stored bar with the live
// ticks folded into it.

import type { Bar, Tick } from "./types";

/** A tick further than this from the last close belongs to another instrument. */
const MAX_JUMP = 0.05;

/**
 * Fold one tick into the live candle and return the result.
 *
 * `prev` is the live candle built so far (it carries the highs and lows of every
 * tick seen since the page opened); `bars` are the stored candles, whose newest may
 * be the same candle as the terminal has it; `step` is the length of one bar in
 * seconds. The result is the *widest* of the two views of that candle: the terminal's
 * own open (it saw the bar start), and the highest high and lowest low of what either
 * side has seen, so a spike the stream missed (a reconnect) or one the stored bar
 * predates (the page was opened mid-candle) is not lost. Folding the same tick twice
 * gives the same candle, so this is safe to call while rendering. An unusable tick
 * returns `prev` unchanged.
 */
export function foldTick(prev: Bar | null, bars: Bar[], tick: Tick, step: number): Bar | null {
  const price = tick.last || tick.bid || tick.ask;
  if (!price) return prev;

  const bucket = Math.floor(tick.time / step) * step;
  const last = bars.length ? bars[bars.length - 1] : null;

  // A stale tick from another symbol can never be far from the last known close.
  if (last && Math.abs(price - last.close) > last.close * MAX_JUMP) return prev;

  // The terminal returns the forming bar as the final stored one.
  const stored = last && last.time === bucket ? last : null;
  const mine = prev && prev.time === bucket ? prev : null;
  if (mine || stored) {
    const base = mine ?? (stored as Bar);
    return {
      ...base,
      open: stored ? stored.open : base.open,
      high: Math.max(mine ? mine.high : -Infinity, stored ? stored.high : -Infinity, price),
      low: Math.min(mine ? mine.low : Infinity, stored ? stored.low : Infinity, price),
      close: price,
      tick_volume: Math.max(mine ? mine.tick_volume : 0, stored ? stored.tick_volume : 0),
    };
  }
  return {
    time: bucket,
    open: price,
    high: price,
    low: price,
    close: price,
    tick_volume: 0,
    spread: 0,
    real_volume: 0,
  };
}

/** Fold a batch of ticks, oldest first, into the live candle. */
export function foldTicks(prev: Bar | null, bars: Bar[], ticks: Tick[], step: number): Bar | null {
  let bar = prev;
  for (const tick of ticks) bar = foldTick(bar, bars, tick, step);
  return bar;
}
