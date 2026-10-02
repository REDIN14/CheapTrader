// Bar replay: starting on a bar, playing, stepping, and the paper account that
// trades along with the cursor.
//
// The browser sets the pace. Every tick it asks the backend to move the cursor
// ("advance") and gets back, in one reply, the bars that were revealed, the
// positions marked to the new price, the headline numbers and any trade a stop or
// target closed on the way. Nothing is polled, nothing is downloaded twice, and
// pausing is immediate because there is no loop on the server to stop.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, replayApi } from "./api";
import type { ViewPolicy } from "./chart";
import { usePersistentState } from "./persist";
import type {
  BacktestTrade,
  Bar,
  Position,
  ReplayAccount,
  ReplayReport,
  ReplayState,
  ReplayUpdate,
  Timeframe,
} from "./types";

/**
 * - `off`: no replay;
 * - `picking`: choosing the bar to start on (the chart shows the live candles);
 * - `starting`: the backend is loading that window;
 * - `running`: the replay owns the chart.
 */
export type ReplayMode = "off" | "picking" | "starting" | "running";

/** Playback speeds in bars per second. */
export const REPLAY_SPEEDS = [0.5, 1, 2, 5, 10, 25, 50];
const DEFAULT_SPEED = 2;

/** At most this many requests per second; faster speeds move several bars per request. */
const MAX_TICKS_PER_SECOND = 10;

interface Snapshot {
  mode: ReplayMode;
  state: ReplayState | null;
  account: ReplayAccount | null;
  trades: BacktestTrade[];
}

const IDLE: Snapshot = { mode: "off", state: null, account: null, trades: [] };

interface Options {
  symbol: string | null;
  timeframe: Timeframe;
  /** Put a whole new set of candles on the chart. */
  showBars: (bars: Bar[], view: ViewPolicy) => void;
  /** Add candles after the ones on the chart. */
  appendBars: (bars: Bar[]) => void;
  onError: (message: string) => void;
  /** Stops and targets that closed a position while the cursor moved. */
  onClosed: (trades: BacktestTrade[]) => void;
  /** The backend has settled the paper account at the end of a replay: its profile has new numbers. */
  onEnded?: () => void;
}

export function useReplay({ symbol, timeframe, showBars, appendBars, onError, onClosed, onEnded }: Options) {
  const [snap, setSnap] = useState<Snapshot>(IDLE);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = usePersistentState<number>("replaySpeed", DEFAULT_SPEED);
  const [report, setReport] = useState<ReplayReport | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  // What the async code below needs to see as of now, not as of the render that
  // created it.
  const snapRef = useRef(snap);
  snapRef.current = snap;
  const calls = useRef({ showBars, appendBars, onError, onClosed, onEnded });
  calls.current = { showBars, appendBars, onError, onClosed, onEnded };
  // Bumped whenever a replay ends or starts over, so a reply that was still on its
  // way for the old one is thrown away instead of landing in the new one.
  const run = useRef(0);
  const moving = useRef(false);
  // Steps and jumps asked for while a move was still on its way: they are not lost,
  // they are done as soon as it lands (five quick clicks on "forward" are five bars).
  const wanted = useRef({ steps: 0, end: false });
  const draining = useRef(false);
  // The request that ends a replay on the server. A start waits for it, so it cannot end the new replay.
  const ending = useRef<Promise<unknown>>(Promise.resolve());

  const commit = useCallback((next: Snapshot) => {
    snapRef.current = next;
    setSnap(next);
  }, []);

  /** Take in what a cursor move reported. */
  const apply = useCallback(
    (up: ReplayUpdate, token: number) => {
      const prev = snapRef.current;
      const starting = prev.mode !== "running";
      let trades = prev.trades;
      if (up.reset) trades = [];
      else if (up.closed.length) trades = prev.trades.concat(up.closed);

      if (up.reset) calls.current.showBars(up.bars, starting ? "latest" : "keep");
      else if (up.bars.length) calls.current.appendBars(up.bars);

      commit({ mode: "running", state: up.state, account: up.account, trades });

      const byStop = up.closed.filter((t) => t.reason !== "manual");
      if (byStop.length) calls.current.onClosed(byStop);

      // The history is kept by adding what each move closed; if the count does not
      // add up (a rewind, a missed reply) read it again.
      if (trades.length !== up.account.trades_total) {
        replayApi
          .trades()
          .then((list) => {
            if (token === run.current) commit({ ...snapRef.current, trades: list });
          })
          .catch(() => undefined);
      }
    },
    [commit],
  );

  // -- entering and leaving ------------------------------------------------------
  const open = useCallback(() => {
    if (snapRef.current.mode !== "off") return;
    run.current++;
    commit({ ...IDLE, mode: "picking" });
  }, [commit]);

  /**
   * Tell the backend this replay is over: the paper account closes what is still open at the price
   * under the cursor and the profile keeps the result. (If this does not get through, the next replay
   * or the next start of the program does the same.)
   */
  const endOnServer = useCallback(() => {
    ending.current = replayApi
      .stop()
      .catch(() => undefined)
      .then(() => calls.current.onEnded?.());
  }, []);

  /** Leave the replay altogether; the chart goes back to the live candles. */
  const exit = useCallback(() => {
    if (snapRef.current.mode !== "off") endOnServer();
    run.current++;
    moving.current = false;
    wanted.current = { steps: 0, end: false };
    setPlaying(false);
    setReport(null);
    setReportOpen(false);
    commit(IDLE);
  }, [commit, endOnServer]);

  /** Back to choosing a bar; the live candles return so any bar can be picked. */
  const pickAgain = useCallback(() => {
    // This session is over (the next bar chosen begins another one on the same profile).
    if (snapRef.current.mode === "running") endOnServer();
    run.current++;
    moving.current = false;
    wanted.current = { steps: 0, end: false };
    setPlaying(false);
    setReport(null);
    commit({ ...IDLE, mode: "picking" });
  }, [commit, endOnServer]);

  const start = useCallback(
    async (time: number) => {
      if (!symbol || snapRef.current.mode !== "picking") return;
      const token = ++run.current;
      commit({ ...snapRef.current, mode: "starting" });
      try {
        await ending.current;
        if (token !== run.current) return;
        const up = await replayApi.start(symbol, timeframe, time);
        if (token !== run.current) {
          // Left while it was loading: the replay that has just been made is over before it began.
          if ((snapRef.current.mode as ReplayMode) === "off") endOnServer(); // (the guard above has narrowed the type)
          return;
        }
        apply(up, token);
      } catch (err) {
        if (token !== run.current) return;
        commit({ ...snapRef.current, mode: "picking" });
        calls.current.onError((err as Error).message);
      }
    },
    [symbol, timeframe, apply, commit, endOnServer],
  );

  // -- moving the cursor ---------------------------------------------------------
  /** Move the cursor; resolves to the reply, or null if it failed or was overtaken. */
  const advance = useCallback(
    async (delta: number): Promise<ReplayUpdate | null> => {
      const token = run.current;
      moving.current = true;
      try {
        const up = await replayApi.advance(delta);
        if (token !== run.current) return null;
        apply(up, token);
        return up;
      } catch (err) {
        if (token === run.current) {
          setPlaying(false);
          if (err instanceof ApiError && err.status === 409) {
            // The backend has no replay any more — it was restarted under us. There is
            // nothing to carry on with, so go back to choosing where to start.
            run.current++;
            moving.current = false;
            commit({ ...IDLE, mode: "picking" });
            calls.current.onError("The backend lost this replay (it was probably restarted). Choose a bar to start again.");
          } else {
            calls.current.onError((err as Error).message);
          }
        }
        return null;
      } finally {
        if (token === run.current) moving.current = false;
      }
    },
    [apply],
  );

  /** Do what the user asked for, one move at a time, as soon as the cursor is free. */
  const drain = useCallback(async () => {
    if (draining.current) return; // the loop that is running will take the new request too
    draining.current = true;
    try {
      while (snapRef.current.mode === "running" && (wanted.current.steps > 0 || wanted.current.end)) {
        if (moving.current) {
          // playback's request is on its way; let it land first
          await new Promise((resolve) => window.setTimeout(resolve, 8));
          continue;
        }
        const { steps, end } = wanted.current;
        wanted.current = { steps: 0, end: false };
        const st = snapRef.current.state;
        let moved: ReplayUpdate | null;
        if (end && st) {
          setPlaying(false);
          moved = await advance(st.total - 1 - st.index);
        } else {
          moved = await advance(steps);
        }
        if (!moved) {
          wanted.current = { steps: 0, end: false }; // it failed; what piled up behind it would be stale
          break;
        }
      }
    } finally {
      draining.current = false;
      if (snapRef.current.mode !== "running") wanted.current = { steps: 0, end: false };
    }
  }, [advance]);

  const step = useCallback(
    async (n = 1) => {
      if (snapRef.current.mode !== "running") return;
      wanted.current.steps += n;
      await drain();
    },
    [drain],
  );

  const jumpToEnd = useCallback(async () => {
    if (snapRef.current.mode !== "running" || !snapRef.current.state) return;
    wanted.current.end = true;
    await drain();
  }, [drain]);

  const play = useCallback(() => {
    const st = snapRef.current.state;
    if (snapRef.current.mode === "running" && st && st.index < st.total - 1) setPlaying(true);
  }, []);
  const pause = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => {
    if (playing) setPlaying(false);
    else play();
  }, [playing, play]);

  // The pace: one request per tick, several bars per tick at the top speeds.
  useEffect(() => {
    if (!playing || snap.mode !== "running") return;
    let alive = true;
    let timer = 0;
    const perTick = Math.max(1, Math.ceil(speed / MAX_TICKS_PER_SECOND));
    const gap = (1000 * perTick) / speed;

    const tick = async () => {
      if (moving.current) {
        // A step the user asked for is still on its way; let it land first.
        timer = window.setTimeout(tick, 25);
        return;
      }
      const began = performance.now();
      const up = await advance(perTick);
      if (!alive) return;
      if (!up || up.state.index >= up.state.total - 1) {
        setPlaying(false); // the end of the window (or a failure)
        return;
      }
      timer = window.setTimeout(tick, Math.max(0, gap - (performance.now() - began)));
    };
    timer = window.setTimeout(tick, 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [playing, speed, snap.mode, advance]);

  // -- the paper account -----------------------------------------------------------
  /** Re-read the account after an order, a close or a stop change. */
  const refreshAccount = useCallback(async () => {
    const token = run.current;
    try {
      const account = await replayApi.account();
      if (token !== run.current || snapRef.current.mode !== "running") return;
      commit({ ...snapRef.current, account });
      if (account.trades_total !== snapRef.current.trades.length) {
        const trades = await replayApi.trades();
        if (token === run.current) commit({ ...snapRef.current, trades });
      }
    } catch {
      /* the next move brings the account along anyway */
    }
  }, [commit]);

  /** Change the open positions shown, ahead of the broker's answer (a stop being dragged). */
  const patchPositions = useCallback(
    (change: (list: Position[]) => Position[]) => {
      const s = snapRef.current;
      if (!s.account) return;
      commit({ ...s, account: { ...s.account, positions: change(s.account.positions) } });
    },
    [commit],
  );

  /** The replay trades on another account now (a profile was chosen, started over or deleted): read it and its history again. */
  const reloadAccount = useCallback(async () => {
    const token = run.current;
    try {
      const [account, trades] = await Promise.all([replayApi.account(), replayApi.trades()]);
      if (token !== run.current || snapRef.current.mode !== "running") return;
      commit({ ...snapRef.current, account, trades });
    } catch {
      /* the next move brings the account along anyway */
    }
  }, [commit]);

  // -- the report ---------------------------------------------------------------------
  // Read while it is open: straight away, then at most about once a second however
  // fast the replay runs, and again whenever a trade closes.
  const lastRead = useRef(0);
  const index = snap.state?.index;
  const tradesTotal = snap.account?.trades_total;
  useEffect(() => {
    if (!reportOpen || snap.mode !== "running") return;
    const token = run.current;
    const wait = Math.max(0, lastRead.current + 900 - Date.now());
    const timer = window.setTimeout(() => {
      lastRead.current = Date.now();
      replayApi
        .report()
        .then((r) => {
          if (token === run.current) setReport(r);
        })
        .catch(() => undefined);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [reportOpen, snap.mode, index, tradesTotal]);

  const toggleReport = useCallback(() => setReportOpen((v) => !v), []);

  return useMemo(
    () => ({
      mode: snap.mode,
      state: snap.state,
      account: snap.account,
      trades: snap.trades,
      playing,
      speed,
      report,
      reportOpen,
      open,
      exit,
      pickAgain,
      start,
      step,
      jumpToEnd,
      play,
      pause,
      toggle,
      setSpeed,
      refreshAccount,
      reloadAccount,
      patchPositions,
      toggleReport,
    }),
    [
      snap,
      playing,
      speed,
      report,
      reportOpen,
      open,
      exit,
      pickAgain,
      start,
      step,
      jumpToEnd,
      play,
      pause,
      toggle,
      setSpeed,
      refreshAccount,
      reloadAccount,
      patchPositions,
      toggleReport,
    ],
  );
}

