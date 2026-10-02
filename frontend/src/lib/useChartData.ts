// The bars on the chart, and how a new symbol or interval gets there.
//
// A switch used to blank the chart, wait for 20,000 bars and then reset the view.
// Now the chart keeps showing what it has until the next series is ready, and the
// next series is ready quickly:
//
//   - a series already seen is shown at once, and brought up to date behind it;
//   - otherwise the newest 1,500 bars arrive first (enough to look at and scroll
//     around in), and the full depth replaces them in the background without
//     moving anything on screen;
//   - the view survives an interval change (same zoom, same place — see
//     ViewPolicy in lib/chart.ts).
//
// Everything the chart draws from one series — the candles, the interval named in
// the legend, the bar countdown — comes from one `frame`, so they change together.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { firstDifference } from "./barMath";
import {
  barsNeeded,
  fetchBars,
  mergeTail,
  prefetch,
  QUICK_BARS,
  recall,
  remember,
  STALE_MS,
  TAIL_BARS,
  type Series,
} from "./barStore";
import type { ViewHint, ViewPolicy } from "./chart";
import { TF } from "./timeframes";
import type { Bar, Timeframe } from "./types";

export interface ChartFrame {
  /** The series on screen — which is not always the one just asked for. */
  symbol: string | null;
  timeframe: Timeframe;
  bars: Bar[];
  /** What showing this frame does to the chart's view. */
  view: ViewPolicy;
  /** The bars reach as far back as was asked for (or as far back as the broker goes). */
  complete: boolean;
  source: "live" | "replay";
  /** Grows with every frame, so consumers can tell frames apart. */
  seq: number;
}

interface Options {
  symbol: string | null;
  timeframe: Timeframe;
  barCount: number;
  /** False while a replay owns the chart. */
  enabled: boolean;
  /** Where the user is looking on the chart right now (null if nothing is drawn). */
  readView?: () => ViewHint | null;
  /** A load failed; `shown` is what is still on screen. */
  onError: (message: string, shown: ChartFrame) => void;
  /** A series is on screen at the depth that was asked for. */
  onSettled?: () => void;
}

/** Candles re-read to check the newest ones against the terminal (see syncTail). */
const SYNC_BARS = 4;

/** Run `fn` when the browser has a spare moment (but within half a second). */
function whenIdle(fn: () => void): () => void {
  const w = window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    cancelIdleCallback?: (id: number) => void;
  };
  if (w.requestIdleCallback) {
    const id = w.requestIdleCallback(fn, { timeout: 500 });
    return () => w.cancelIdleCallback?.(id);
  }
  const id = window.setTimeout(fn, 30);
  return () => window.clearTimeout(id);
}

export function useChartData({
  symbol,
  timeframe,
  barCount,
  enabled,
  readView,
  onError,
  onSettled,
}: Options) {
  const [frame, setFrame] = useState<ChartFrame>(() => ({
    symbol,
    timeframe,
    bars: [],
    view: "latest",
    complete: true,
    source: "live",
    seq: 0,
  }));
  // True from the request until the first candles of the new series are on screen.
  const [loading, setLoading] = useState(false);

  // The frame on screen as of the last commit; the loader reads it to decide what
  // the next frame should do to the view.
  const shown = useRef(frame);
  const latest = useRef({ symbol, timeframe, barCount, readView, onError, onSettled });
  latest.current = { symbol, timeframe, barCount, readView, onError, onSettled };

  const put = useCallback((next: ChartFrame) => {
    shown.current = next;
    setFrame(next);
  }, []);

  useEffect(() => {
    if (!enabled || !symbol) {
      setLoading(false);
      return;
    }

    const sym = symbol;
    const tf = timeframe;
    const want = barCount;
    let cancelled = false;
    const idle: Array<() => void> = [];

    /** Show a series; a refresh of the one on screen leaves the view alone. */
    const show = (bars: Bar[], complete: boolean, view?: ViewPolicy) => {
      const now = shown.current;
      const sameSeries = now.source === "live" && now.symbol === sym && now.bars.length > 0;
      const policy: ViewPolicy =
        view ?? (!sameSeries ? "latest" : now.timeframe === tf ? "keep" : "anchor");
      put({
        symbol: sym,
        timeframe: tf,
        bars,
        view: policy,
        complete,
        source: "live",
        seq: now.seq + 1,
      });
    };

    const settle = () => latest.current.onSettled?.();
    const fail = (err: unknown) => {
      if (cancelled) return;
      setLoading(false);
      latest.current.onError((err as Error).message, shown.current);
    };

    /** Swap in the full-depth series once the browser is idle: one big upload, no hurry. */
    const deepen = (full: Bar[]) => {
      remember(sym, tf, full, want);
      if (cancelled) return;
      idle.push(
        whenIdle(() => {
          if (cancelled) return;
          show(full, true, "keep");
          settle();
        }),
      );
    };

    // What the new series has to reach for the view to carry over: the same zoom, and
    // the same date if the user has scrolled back. Only an interval change keeps the
    // place, so only then is the view read (before anything on screen changes).
    const onScreen = shown.current;
    const sameSeries = onScreen.source === "live" && onScreen.symbol === sym && onScreen.bars.length > 0;
    const hint =
      sameSeries && onScreen.timeframe !== tf ? (latest.current.readView?.() ?? null) : null;
    const need = Math.min(want, barsNeeded(hint, TF[tf].seconds));

    // A remembered series is only good enough if it reaches that far back (or
    // reaches back as far as the broker goes).
    const covers = (s: Series) =>
      s.bars.length >= need || s.requested >= want || s.bars.length < s.requested;
    // The series in memory may be deeper than the depth asked for now.
    const newest = (bars: Bar[]) => (bars.length > want ? bars.slice(bars.length - want) : bars);

    const known = recall(sym, tf);
    if (known && covers(known)) {
      showRemembered(known);
    } else {
      showFresh();
    }

    // -- a series seen before: on screen at once, then brought up to date ---------
    function showRemembered(series: Series) {
      const complete = series.requested >= want || series.bars.length < series.requested;
      show(newest(series.bars), complete);
      setLoading(false);
      if (complete) settle();

      void (async () => {
        try {
          if (!complete) {
            deepen(await fetchBars(sym, tf, want));
            return;
          }
          if (Date.now() - series.fetchedAt <= STALE_MS) return;
          const merged = mergeTail(series.bars, await fetchBars(sym, tf, TAIL_BARS));
          if (!merged) {
            deepen(await fetchBars(sym, tf, want)); // the gap is too big to patch
            return;
          }
          const kept = remember(sym, tf, merged, series.requested);
          if (!cancelled) show(newest(kept.bars), true, "keep");
        } catch {
          // What is on screen stays; the next visit tries again.
        }
      })();
    }

    // -- a new series: the newest bars first, the rest behind them -----------------
    function showFresh() {
      const now = shown.current;
      if (!(now.source === "live" && now.symbol === sym && now.bars.length > 0)) {
        // A different symbol (or the replay's candles) must not linger under the new
        // name. The same symbol keeps its candles until the new interval is ready.
        put({ symbol: sym, timeframe: tf, bars: [], view: "latest", complete: false, source: "live", seq: now.seq + 1 });
      }
      setLoading(true);

      const first = Math.min(want, Math.max(QUICK_BARS, need));
      fetchBars(sym, tf, first)
        .then((bars) => {
          remember(sym, tf, bars, first);
          if (cancelled) return undefined;
          const done = first >= want || bars.length < first;
          show(bars, done);
          setLoading(false);
          if (done) {
            settle();
            return undefined;
          }
          return fetchBars(sym, tf, want).then(deepen);
        })
        .catch(fail);
    }

    return () => {
      cancelled = true;
      for (const cancel of idle) cancel();
    };
  }, [symbol, timeframe, barCount, enabled, put]);

  /**
   * The replay's own candles take over the chart. A new replay opens on its latest
   * bars at a readable zoom ("latest"); a rewind keeps the view ("keep").
   */
  const showReplayBars = useCallback(
    (bars: Bar[], view: ViewPolicy = "latest") => {
      const now = shown.current;
      put({
        symbol: latest.current.symbol,
        timeframe: latest.current.timeframe,
        bars,
        view,
        complete: true,
        source: "replay",
        seq: now.seq + 1,
      });
    },
    [put],
  );

  /**
   * The replay moved on: more candles after the ones already shown. The chart adds
   * them in place, so a long replay never re-uploads its history, and the view
   * follows the newest bar for as long as it was on it.
   */
  const appendReplayBars = useCallback(
    (more: Bar[]) => {
      const now = shown.current;
      if (now.source !== "replay" || !more.length) return;
      put({ ...now, bars: now.bars.concat(more), view: "keep", seq: now.seq + 1 });
    },
    [put],
  );

  /**
   * Bring the newest few candles in line with the terminal's own.
   *
   * The candles formed while the page is open are built from the ticks that were
   * folded into them, and the stream delivers every one. But the page can have missed
   * some (it was opened in the middle of a candle, the connection dropped for a
   * moment, the tab slept), and the terminal's figures are the reference, so this
   * reads the last few candles again and lets the terminal's high, low and open stand.
   * Only the newest candles change, in place: nothing re-uploads and nothing moves.
   */
  const syncing = useRef(false);
  const syncTail = useCallback(async () => {
    const at = shown.current;
    if (syncing.current || at.source !== "live" || !at.symbol || !at.bars.length) return;
    syncing.current = true;
    const { symbol: sym, timeframe: tf } = at;
    try {
      let fresh = await api.bars(sym, tf, SYNC_BARS);
      let current = shown.current;
      if (current.source !== "live" || current.symbol !== sym || current.timeframe !== tf) return;
      let merged = mergeTail(current.bars, fresh);
      if (!merged) {
        // Longer than a few candles since the last look (a sleeping laptop): read more.
        fresh = await api.bars(sym, tf, TAIL_BARS);
        current = shown.current;
        if (current.source !== "live" || current.symbol !== sym || current.timeframe !== tf) return;
        merged = mergeTail(current.bars, fresh);
      }
      if (!merged || firstDifference(current.bars, merged) >= Math.max(current.bars.length, merged.length)) return;
      const known = recall(sym, tf);
      remember(sym, tf, merged, known?.requested ?? merged.length);
      put({ ...current, bars: merged, view: "keep", seq: current.seq + 1 });
    } catch {
      // The next look tries again.
    } finally {
      syncing.current = false;
    }
  }, [put]);

  /** Start fetching an interval the pointer is hovering over, before it is clicked. */
  const prefetchInterval = useCallback((tf: Timeframe) => {
    const { symbol: sym, barCount: depth } = latest.current;
    if (sym) prefetch(sym, tf, depth);
  }, []);

  return { frame, loading, showReplayBars, appendReplayBars, prefetchInterval, syncTail };
}
