// Small shared React hooks.

import { useEffect, useRef, useState } from "react";

/** Close a popup when the user presses outside it or hits Escape. */
export function useDismiss<T extends HTMLElement>(onClose: () => void, active = true) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!active) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      // Esc closes this popup and nothing else — in particular it must not also
      // end a replay through the window-level shortcut.
      e.stopPropagation();
      onClose();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, active]);
  return ref;
}

/**
 * Runs `callback` on every animation frame while `active`. DOM overlays that
 * must stay glued to the chart's price scale use it, because the scale moves
 * without any React render (dragging the axis, autoscaling, zooming).
 */
export function useAnimationFrame(callback: () => void, active = true) {
  const latest = useRef(callback);
  latest.current = callback;
  useEffect(() => {
    if (!active) return;
    let raf = 0;
    const tick = () => {
      // Ask for the next frame first: one failed frame must not end the loop, or
      // the overlays would freeze for good.
      raf = requestAnimationFrame(tick);
      latest.current();
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active]);
}

/**
 * `flag`, but only once it has stayed true for `delayMs`. A "loading" hint that
 * would flash for a few frames on a fast load never shows at all.
 */
export function useDelayedFlag(flag: boolean, delayMs: number): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!flag) {
      setShown(false);
      return;
    }
    const id = window.setTimeout(() => setShown(true), delayMs);
    return () => window.clearTimeout(id);
  }, [flag, delayMs]);
  return shown && flag;
}

/** Current time in ms, refreshed every `intervalMs`. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
