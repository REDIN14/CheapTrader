// Updates: what the backend knows about newer releases, and the wait for the program to come back after an
// install. The backend does the looking (see app/updater.py); this keeps the page in step with it.
//
// While nothing is happening the status is read now and then (the backend looks at GitHub by itself a little
// after it starts and every six hours). While an update is being downloaded it is read every moment. When the
// backend says it is about to install, it closes, so the page waits for it to answer again: as the new
// version it reloads, otherwise it says what went wrong.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, updateApi } from "./api";
import type { UpdateStatus } from "./types";
import { restartOutcome } from "./updates";

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export interface Restart {
  /** The version that was running when the install began. */
  from: string;
  /** Why it did not come back as a newer one, once that is known. */
  problem: string | null;
}

export function useUpdate() {
  const [info, setInfo] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [restart, setRestart] = useState<Restart | null>(null);

  // What was last read, and how many reads in a row failed (the program is closing, or not there).
  const latest = useRef<UpdateStatus | null>(null);
  const failures = useRef(0);
  latest.current = info;

  const refresh = useCallback(async () => {
    try {
      setInfo(await updateApi.status());
      failures.current = 0;
    } catch {
      failures.current += 1;
      const last = latest.current;
      // An update was being downloaded and the program does not answer any more: it closed to install it (it can
      // be quicker about that than the page is at asking). From here the page waits for it to come back.
      const downloading = last?.phase === "downloading" || last?.phase === "verifying" || last?.phase === "installing";
      if (last && downloading && failures.current >= 2) setRestart((now) => now ?? { from: last.current, problem: null });
    }
  }, []);

  const phase = info?.phase;
  const going = phase === "downloading" || phase === "verifying" || phase === "installing";
  useEffect(() => {
    void refresh();
  }, [refresh]);
  // Quickly while an install is going, and while the first look at GitHub (a little after the program starts)
  // has not happened yet; otherwise now and then.
  const awaitingFirstLook = info?.enabled === true && info.checked_at === null;
  useEffect(() => {
    const id = window.setInterval(() => void refresh(), going ? 700 : awaitingFirstLook ? 5000 : 5 * 60_000);
    return () => window.clearInterval(id);
  }, [going, awaitingFirstLook, refresh]);

  // The backend is about to install and close: from here on the page waits for it to answer again.
  const current = info?.current ?? "";
  useEffect(() => {
    if (phase === "installing" && !restart) setRestart({ from: current, problem: null });
  }, [phase, current, restart]);

  const waitingFrom = restart && !restart.problem ? restart.from : null;
  useEffect(() => {
    if (waitingFrom === null) return;
    let alive = true;
    const began = Date.now();
    let sameSince: number | null = null;
    void (async () => {
      while (alive) {
        await sleep(800);
        if (!alive) return;
        let version: string | undefined;
        let up = false;
        try {
          version = (await api.health()).version;
          up = true;
        } catch {
          /* closed, or not open yet */
        }
        let status: UpdateStatus | null = null;
        if (up && version === waitingFrom) {
          sameSince ??= Date.now();
          try {
            status = await updateApi.status();
          } catch {
            /* try again */
          }
        } else {
          sameSince = null;
        }
        const outcome = restartOutcome(
          waitingFrom,
          { up, version, status, sameFor: sameSince === null ? 0 : (Date.now() - sameSince) / 1000 },
          (Date.now() - began) / 1000,
        );
        if (outcome.state === "done") {
          window.location.reload();
          return;
        }
        if (outcome.state === "failed") {
          if (status) setInfo(status);
          setRestart({ from: waitingFrom, problem: outcome.message });
          return;
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [waitingFrom]);

  /** Do one thing to the update state; the reply is the new state, a refusal is shown as `problem`. */
  const run = useCallback(async (call: () => Promise<UpdateStatus>) => {
    setBusy(true);
    setProblem(null);
    try {
      setInfo(await call());
    } catch (err) {
      setProblem(message(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const check = useCallback(() => run(updateApi.check), [run]);
  const install = useCallback(() => run(updateApi.install), [run]);
  const skip = useCallback((version: string) => run(() => updateApi.skip(version)), [run]);
  const setEnabled = useCallback((enabled: boolean) => run(() => updateApi.setEnabled(enabled)), [run]);
  const dismiss = useCallback(() => {
    setProblem(null);
    setRestart(null);
  }, []);

  return { info, busy, problem, restart, refresh, check, install, skip, setEnabled, dismiss };
}
