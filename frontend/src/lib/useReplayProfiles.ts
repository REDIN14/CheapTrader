// The paper-trading profiles: the list, which one the replay trades on, and making, switching,
// renaming, starting over and deleting them. The backend keeps them (see profile_routes.py); every
// reply is the whole list, so this only has to show what it got.

import { useCallback, useRef, useState } from "react";
import { replayApi } from "./api";
import type { ReplayProfiles } from "./types";

export function useReplayProfiles(onAccountChanged: () => void) {
  const [view, setView] = useState<ReplayProfiles | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A running replay trades on whichever profile is active: when one is switched, started over or
  // deleted the screen has to read the account again.
  const changed = useRef(onAccountChanged);
  changed.current = onAccountChanged;

  const reload = useCallback(async () => {
    try {
      setView(await replayApi.profiles());
    } catch {
      /* keep what was shown: the next look tries again */
    }
  }, []);

  /** Do one thing to the profiles; true if it worked, else the reason is in `error`. */
  const run = useCallback(async (call: () => Promise<ReplayProfiles>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      setView(await call());
      changed.current();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const create = useCallback((name: string, balance: number) => run(() => replayApi.createProfile(name, balance)), [run]);
  const select = useCallback((id: string) => run(() => replayApi.selectProfile(id)), [run]);
  const rename = useCallback((id: string, name: string) => run(() => replayApi.renameProfile(id, name)), [run]);
  const reset = useCallback((id: string, balance?: number) => run(() => replayApi.resetProfile(id, balance)), [run]);
  const remove = useCallback((id: string) => run(() => replayApi.deleteProfile(id)), [run]);
  const clearError = useCallback(() => setError(null), []);

  return { view, busy, error, clearError, reload, create, select, rename, reset, remove };
}
