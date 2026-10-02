// The broker's clock, learned from its ticks.
//
// Bar and tick times from MetaTrader are "server time": the broker's wall clock
// written as if it were UTC. The chart's time axis therefore reads in server
// time, and anything that compares a bar to "now" — the bar-close countdown, the
// clock under the chart — has to use the same clock to agree with it.
//
// A new tick's timestamp minus this machine's clock gives the skew. Two things
// make it tricky:
//
//  * A closed market keeps streaming its last tick, frozen at the final trade
//    (hours or days old). That would give a nonsense skew, so a tick that merely
//    repeats the previous one is ignored, and a sample is only trusted when it is
//    within two minutes of a whole number of hours (real offsets are whole hours)
//    and no more than 14 hours away.
//  * The offset can change while the app is open (daylight saving). A sample that
//    disagrees with the known skew is adopted only when the tick before it agrees
//    with it: a live stream gives consecutive ticks with the same skew, whereas
//    stale ticks drift apart by however long they were apart.

import { useEffect, useRef, useState } from "react";
import type { Tick } from "./types";

const TOLERANCE_S = 120;
const MAX_OFFSET_H = 14;
/** Consecutive new ticks from a live stream agree on the skew to within this. */
const STREAM_AGREE_S = 5;

export interface ServerClock {
  /** Seconds the broker's clock is ahead of this machine's; null until a fresh tick arrives. */
  skew: number | null;
  /** The skew as whole hours (the broker's UTC offset); null until known. */
  offsetHours: number | null;
  /** Wall-clock ms of the last new tick that proved the feed is live; 0 if none yet. */
  freshAt: number;
}

export function useServerClock(tick: Tick | null): ServerClock {
  const trusted = useRef<number | null>(null);
  const previous = useRef<{ time: number; skew: number } | null>(null);
  const [state, setState] = useState<ServerClock>({ skew: null, offsetHours: null, freshAt: 0 });

  useEffect(() => {
    if (!tick) return;
    const tickTime = tick.time_msc ? tick.time_msc / 1000 : tick.time;
    const before = previous.current;
    // The stream re-sends the latest tick until a newer one exists; a repeat says
    // nothing about the clock and must not keep the feed looking alive.
    if (before && before.time === tickTime) return;

    const skew = tickTime - Date.now() / 1000;
    previous.current = { time: tickTime, skew };

    const hours = Math.round(skew / 3600);
    const plausible = Math.abs(hours) <= MAX_OFFSET_H && Math.abs(skew - hours * 3600) <= TOLERANCE_S;
    const known = trusted.current;

    if (known !== null && Math.abs(skew - known) <= TOLERANCE_S) {
      // Agrees with what we know, so the feed is live. A tick is stamped before it
      // arrives, so samples only ever read low: keep the largest for the best fit.
      if (skew > known) {
        trusted.current = skew;
        setState({ skew, offsetHours: hours, freshAt: Date.now() });
      } else {
        // "Fresh" only has to be right to within a second (the dot goes grey after 30 s
        // without one), so a busy feed does not cost a render for every tick.
        const now = Date.now();
        setState((s) => (now - s.freshAt < 500 ? s : { ...s, freshAt: now }));
      }
      return;
    }

    if (!plausible) return;
    const liveStream = before !== null && Math.abs(skew - before.skew) <= STREAM_AGREE_S;
    if (known === null || liveStream) {
      // First sample, or a live stream whose clock moved (daylight saving).
      trusted.current = skew;
      setState({ skew, offsetHours: hours, freshAt: Date.now() });
    }
  }, [tick]);

  return state;
}
