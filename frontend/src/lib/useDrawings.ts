// The drawings of the symbol on screen.
//
// They live on the server (one file per symbol), so they come back after a restart, and a script can
// add to them. Here they are loaded when the symbol changes, changed on screen at once, and saved
// behind the user's back: the chart never waits for the server. When the server says they changed
// (a script drew something) they are loaded again — except while the user is dragging one or one of
// their own changes is still on its way, which would otherwise make a drawing jump back for a moment.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, drawingApi, type ClearResult, type LockedScope } from "./api";
import { onNotice } from "./bus";
import type { Drawing } from "./drawings";

export interface DrawingStore {
  drawings: Drawing[];
  /** Put a new drawing on the chart and save it. */
  add: (drawing: Drawing) => void;
  /** Show a drawing changed (while it is being dragged); nothing is saved until `save`. */
  preview: (drawing: Drawing) => void;
  /** Save a drawing as it is now. */
  save: (id: string) => void;
  remove: (id: string) => void;
  /** Lock a drawing (it cannot be moved or removed) or unlock it. */
  lock: (id: string, locked: boolean) => void;
  /**
   * Remove drawings in bulk: those of this symbol or of every symbol; by default the ones that are not
   * locked ("only" takes just the locked ones). Resolves with what the server removed and kept.
   */
  clear: (which: "symbol" | "all", locked?: LockedScope) => Promise<ClearResult | null>;
}

export function useDrawings(symbol: string | null, onError: (message: string) => void): DrawingStore {
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const live = useRef<Drawing[]>([]);
  const symbolRef = useRef(symbol);
  const errorRef = useRef(onError);
  errorRef.current = onError;
  /** Saves that have been sent and not answered. */
  const inflight = useRef(0);
  /** A drawing is being dragged right now. */
  const held = useRef(false);
  /** The server changed while we were busy: load again when we are not. */
  const stale = useRef(false);

  const put = useCallback((next: Drawing[]) => {
    live.current = next;
    setDrawings(next);
  }, []);

  const reload = useCallback(async () => {
    const name = symbolRef.current;
    if (!name) return;
    if (inflight.current > 0 || held.current) {
      stale.current = true;
      return;
    }
    stale.current = false;
    try {
      const list = await drawingApi.list(name);
      if (symbolRef.current !== name) return; // another symbol is on screen by now
      if (inflight.current > 0 || held.current) {
        stale.current = true; // the user changed something while this was on its way
        return;
      }
      put(list);
    } catch (err) {
      if (symbolRef.current === name) errorRef.current(`Drawings: ${(err as Error).message}`);
    }
  }, [put]);

  const settle = useCallback(() => {
    inflight.current = Math.max(0, inflight.current - 1);
    if (inflight.current === 0 && !held.current && stale.current) void reload();
  }, [reload]);

  // The symbol changed: show its drawings (and nothing of the previous symbol's meanwhile).
  useEffect(() => {
    symbolRef.current = symbol;
    held.current = false;
    stale.current = false;
    put([]);
    if (symbol) void reload();
  }, [symbol, put, reload]);

  // The server says some drawings changed; and coming back to the tab is a good moment to look again.
  useEffect(() => {
    let timer = 0;
    const off = onNotice((notice) => {
      // a change of this symbol's drawings, or the live connection (re)opening: changes may have been missed
      const mine = notice.type === "drawings" && notice.symbol === symbolRef.current;
      if (!mine && notice.type !== "stream-open") return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void reload(), 80);
    });
    const visible = () => {
      if (document.visibilityState === "visible") void reload();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      off();
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload]);

  /** Send a change; if it fails, say so and load what the server really has. */
  const send = useCallback(
    (what: string, call: (symbol: string) => Promise<unknown>) => {
      const name = symbolRef.current;
      if (!name) return;
      inflight.current += 1;
      call(name)
        .catch((err: Error) => {
          errorRef.current(`Could not ${what}: ${err.message}`);
          stale.current = true;
        })
        .finally(settle);
    },
    [settle],
  );

  const add = useCallback(
    (drawing: Drawing) => {
      put([...live.current, drawing]);
      send("save the drawing", (name) => drawingApi.add(name, drawing));
    },
    [put, send],
  );

  const preview = useCallback(
    (drawing: Drawing) => {
      held.current = true;
      put(live.current.map((d) => (d.id === drawing.id ? drawing : d)));
    },
    [put],
  );

  const save = useCallback(
    (id: string) => {
      held.current = false;
      const drawing = live.current.find((d) => d.id === id);
      if (!drawing) return;
      // (a locked drawing never moves, so only its style is sent: the server refuses points for it)
      send("save the drawing", (name) =>
        drawingApi.change(name, id, drawing.locked ? { style: drawing.style } : { points: drawing.points, style: drawing.style }),
      );
    },
    [send],
  );

  const remove = useCallback(
    (id: string) => {
      put(live.current.filter((d) => d.id !== id));
      send("remove the drawing", (name) =>
        drawingApi.remove(name, id).catch((err: unknown) => {
          if (!(err instanceof ApiError && err.status === 404)) throw err; // already gone: as wanted
        }),
      );
    },
    [put, send],
  );

  const lock = useCallback(
    (id: string, locked: boolean) => {
      put(live.current.map((d) => (d.id === id ? { ...d, locked } : d)));
      send(locked ? "lock the drawing" : "unlock the drawing", (name) => drawingApi.change(name, id, { locked }));
    },
    [put, send],
  );

  const clear = useCallback(
    async (which: "symbol" | "all", locked: LockedScope = "exclude"): Promise<ClearResult | null> => {
      const name = symbolRef.current;
      if (!name) return null;
      // On screen at once: what the server will remove is known (the locked ones stay unless asked for).
      put(
        live.current.filter((d) => (locked === "include" ? false : locked === "only" ? !d.locked : !!d.locked)),
      );
      inflight.current += 1;
      try {
        return which === "all" ? await drawingApi.clearAll(locked) : await drawingApi.clear(name, locked);
      } catch (err) {
        errorRef.current(`Could not remove the drawings: ${(err as Error).message}`);
        stale.current = true;
        return null;
      } finally {
        settle();
      }
    },
    [put, settle],
  );

  return { drawings, add, preview, save, remove, lock, clear };
}
