// The live account's performance report: what the backend works out from the broker's history
// (GET /api/account/report). Two screens use it, each with a hook of its own:
//
//   * the bar at the bottom shows the figures of the whole history (`detail` off: a few hundred bytes);
//   * the report drawer shows the trades and the curve of the period that was chosen (`detail` on, and only while
//     the drawer is open).
//
// It is read again a moment after a trade is made (a position opens or closes: the number of open positions and
// the balance move), when the period changes, and now and then otherwise (a stop that was hit while the page was
// asleep, a deposit).

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AccountReport } from "./types";

interface Options {
  /** Read it at all (a replay has its own report; the drawer's hook reads while the drawer is open). */
  enabled: boolean;
  /** The trades and the curve are wanted, not only the figures. */
  detail: boolean;
  /** Names the period: when it changes the report is read again. */
  period?: string;
  /** Where the period begins, in the broker's time (seconds); 0: the whole history. Asked at each read, so "today" moves on at midnight. */
  since?: () => number;
  /** What changes when a trade is made: the balance and the number of open positions. */
  balance: number | null;
  positions: number;
  /** The broker's clock now, when known: where the curve ends. */
  now: () => number | undefined;
}

/** How often the report is read again when nothing has told the page to. */
const EVERY = 5 * 60_000;

export function useAccountReport({ enabled, detail, period = "all", since, balance, positions, now }: Options) {
  const [report, setReport] = useState<AccountReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nowRef = useRef(now);
  nowRef.current = now;
  const sinceRef = useRef(since);
  sinceRef.current = since;
  /** The newest read that was asked for: an older one that arrives later is dropped. */
  const latest = useRef(0);
  const firstRead = useRef(true);

  const read = useCallback(async () => {
    const mine = ++latest.current;
    setLoading(true);
    try {
      const r = await api.accountReport({
        now: nowRef.current(),
        since: sinceRef.current?.() || undefined,
        trades: detail ? 2000 : 0,
        points: detail ? 400 : 4,
      });
      if (mine !== latest.current) return;
      setReport(r);
      setError(null);
    } catch (err) {
      if (mine !== latest.current) return;
      setError(err instanceof Error ? err.message : String(err));
      if (detail) setReport(null); // the drawer says what went wrong instead of showing what is no longer so
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, [detail]);

  // Once the page is up, a moment after a position opens or closes, and as soon as the period is another one.
  useEffect(() => {
    if (!enabled) return;
    // the first read at once when the drawer is opened (a moment after the page is up for the bar); later ones a
    // moment after the change, so that a burst of them (a position opened and closed) is read once
    const wait = firstRead.current ? (detail ? 0 : 400) : 300;
    firstRead.current = false;
    const id = window.setTimeout(() => void read(), wait);
    return () => window.clearTimeout(id);
  }, [enabled, detail, period, balance, positions, read]);

  // And now and then, so that a page left open does not go stale.
  useEffect(() => {
    if (!enabled) return;
    const again = () => {
      if (!document.hidden) void read();
    };
    const id = window.setInterval(again, EVERY);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", again);
    };
  }, [enabled, read]);

  return { report, loading, error, reload: read };
}
