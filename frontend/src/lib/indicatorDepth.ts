// How many bars an indicator is run over, and which of its points belong on the chart.
//
// An indicator used to be run over the newest 500 bars whatever the chart showed, so on a chart of 20,000 candles its
// lines covered the last 2.5 % of them, and a replay that began a week back had none at all. Now it is run over as many
// bars as the chart has (its history depth) and, during a replay, over every bar back to the replay's first candle.
// (An indicator that needs more says so in its code, and the server gives it that: see app/indicators/needs.py.)

import { lowerBound } from "./barMath";

/** The most bars the server runs an indicator's lines over: the deepest chart there is (see GET /api/bars). */
export const MAX_INDICATOR_BARS = 100_000;

/**
 * Bars beyond the span of a replay: the broker's clock and this PC's differ by a few hours, and
 * the first candles of a replay window should not be the ones that are left out.
 */
const REPLAY_MARGIN = 300;

/**
 * How many of the newest bars to run an indicator over.
 *
 * With the chart live that is its history depth. During a replay the candles are not the newest ones: the
 * indicator is run over every bar from the replay's first candle (`replayFirst`, epoch seconds, 0 when no replay
 * is on) to now. Weekends and holidays have no bars, so counting the whole span errs on the generous side,
 * which is what is wanted.
 */
export function indicatorCount(depth: number, replayFirst: number, now: number, stepSeconds: number): number {
  const wanted =
    replayFirst > 0 && stepSeconds > 0 ? Math.ceil(Math.max(0, now - replayFirst) / stepSeconds) + REPLAY_MARGIN : depth;
  return Math.max(1, Math.min(MAX_INDICATOR_BARS, Math.floor(wanted)));
}

/** A line of an indicator. */
interface Line {
  data: { time: number; value: number }[];
}

/**
 * The lines with only the points from `time` on (the points are in time order). The candles may reach back
 * less far than the indicator was run (the chart shows its newest 1,500 bars first and the rest a moment
 * later), and a point before the first candle would stretch the time axis over a stretch with no candles.
 * A line that loses nothing is returned as it is.
 */
export function plotsFrom<T extends Line>(plots: T[], time: number): T[] {
  if (!(time > 0)) return plots;
  let changed = false;
  const cut = plots.map((plot) => {
    const at = lowerBound(plot.data, time);
    if (at === 0) return plot;
    changed = true;
    return { ...plot, data: plot.data.slice(at) };
  });
  return changed ? cut : plots;
}
