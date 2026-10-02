// The drawing tools, in a small bar that floats over the chart and can be moved anywhere on it.
//
//   ⋮⋮   grip: drag to move the bar · double-click to put it back
//   ╱    trend line            ▭   rectangle
//   S    short position        ⫽   parallel channel
//   L    long position
//   👁   hide / show the drawings        🗑 remove them all        📖 how to draw with a script
//
// A tool stays armed until its drawing is finished (or Esc); then the chart is just a chart again.
// Where the bar was left is remembered (as a share of the free room, so it stays sensible when the
// window changes size).

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { drawingApi, type LockedScope } from "../lib/api";
import { TOOL_NAMES, type Tool } from "../lib/drawings";
import { useDismiss } from "../lib/hooks";
import { usePersistentState } from "../lib/persist";
import {
  BookIcon,
  ChannelIcon,
  EyeIcon,
  EyeOffIcon,
  GripIcon,
  LongPositionIcon,
  RectangleIcon,
  ShortPositionIcon,
  TrashIcon,
  TrendLineIcon,
} from "./Icons";

const TOOL_ICONS: Record<Tool, (props: { size?: number }) => JSX.Element> = {
  trendline: TrendLineIcon,
  short: ShortPositionIcon,
  long: LongPositionIcon,
  rectangle: RectangleIcon,
  channel: ChannelIcon,
};

/** The order of the tools in the bar. */
const ORDER: Tool[] = ["trendline", "short", "long", "rectangle", "channel"];

/** Room kept clear around the bar: a margin, the price scale on the right and the time scale below. */
const EDGE = { left: 8, right: 78, top: 8, bottom: 36 };

interface Spot {
  x: number;
  y: number;
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

/** A stored spot, if it is a usable one (it comes from localStorage). */
function asSpot(value: unknown): Spot | null {
  if (typeof value !== "object" || value === null) return null;
  const { x, y } = value as Record<string, unknown>;
  if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x: clamp01(x), y: clamp01(y) };
}

interface Drag {
  pointer: number;
  fromX: number;
  fromY: number;
  left: number;
  top: number;
}

interface Props {
  tool: Tool | null;
  onTool: (tool: Tool | null) => void;
  /** The tools cannot be used right now (the chart is waiting for a click of its own). */
  toolsDisabled?: boolean;
  hidden: boolean;
  onToggleHidden: () => void;
  /** The symbol on the chart (the bar offers to remove its drawings, or everyone's). */
  symbol: string | null;
  /** Remove drawings in bulk: this symbol's or everyone's; the ones not locked, or only the locked ones. */
  onRemove: (which: "symbol" | "all", locked: LockedScope) => void | Promise<void>;
  onDocs: () => void;
}

export function DrawingToolbar({ tool, onTool, toolsDisabled = false, hidden, onToggleHidden, symbol, onRemove, onDocs }: Props) {
  const barRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [stored, setStored] = usePersistentState<unknown>("drawToolbarSpot", null);
  const [dragging, setDragging] = useState(false);
  const spot = asSpot(stored);
  // plain numbers, so that the effects below only run when the bar is actually moved
  const spotX = spot?.x ?? null;
  const spotY = spot?.y ?? null;

  /** Put the bar where it belongs: where the user left it, or under the legend. */
  const place = useCallback(() => {
    const bar = barRef.current;
    const host = bar?.offsetParent as HTMLElement | null;
    if (!bar || !host) return;
    const freeW = host.clientWidth - EDGE.left - EDGE.right - bar.offsetWidth;
    const freeH = host.clientHeight - EDGE.top - EDGE.bottom - bar.offsetHeight;
    let top: number;
    if (spotX !== null && spotY !== null) {
      top = EDGE.top + (freeH > 0 ? spotY * freeH : 0);
    } else {
      // never moved: just below the legend, so the two do not sit on each other
      const legend = host.parentElement?.querySelector<HTMLElement>(".tv-legend");
      const below = legend ? legend.getBoundingClientRect().bottom - host.getBoundingClientRect().top + 8 : EDGE.top;
      top = Math.max(EDGE.top, Math.min(below, EDGE.top + Math.max(0, freeH)));
    }
    bar.style.left = `${EDGE.left + (spotX !== null && freeW > 0 ? spotX * freeW : 0)}px`;
    bar.style.top = `${Math.round(top)}px`;
  }, [spotX, spotY]);

  useLayoutEffect(() => {
    place();
    const host = barRef.current?.offsetParent;
    if (!host || typeof ResizeObserver === "undefined") return;
    const watcher = new ResizeObserver(place);
    watcher.observe(host);
    return () => watcher.disconnect();
  }, [place]);

  // Until the user moves it, the bar keeps just under the legend, which grows and shrinks on its own
  // (the first prices add the quote line, an indicator adds a row).
  useEffect(() => {
    if (spotX !== null) return;
    const id = window.setInterval(place, 300);
    return () => window.clearInterval(id);
  }, [spotX, place]);

  const beginDrag = (e: ReactPointerEvent<HTMLSpanElement>) => {
    const bar = barRef.current;
    const host = bar?.offsetParent;
    if (!bar || !host || e.button !== 0) return;
    const b = bar.getBoundingClientRect();
    const h = host.getBoundingClientRect();
    drag.current = { pointer: e.pointerId, fromX: e.clientX, fromY: e.clientY, left: b.left - h.left, top: b.top - h.top };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    e.preventDefault();
  };

  const moveDrag = (e: ReactPointerEvent<HTMLSpanElement>) => {
    const d = drag.current;
    const bar = barRef.current;
    const host = bar?.offsetParent;
    if (!d || d.pointer !== e.pointerId || !bar || !host) return;
    const freeW = host.clientWidth - EDGE.left - EDGE.right - bar.offsetWidth;
    const freeH = host.clientHeight - EDGE.top - EDGE.bottom - bar.offsetHeight;
    setStored({
      x: freeW > 0 ? clamp01((d.left + e.clientX - d.fromX - EDGE.left) / freeW) : 0,
      y: freeH > 0 ? clamp01((d.top + e.clientY - d.fromY - EDGE.top) / freeH) : 0,
    });
  };

  const endDrag = (e: ReactPointerEvent<HTMLSpanElement>) => {
    if (drag.current?.pointer !== e.pointerId) return;
    drag.current = null;
    setDragging(false);
  };

  return (
    <div
      ref={barRef}
      className={dragging ? "dr-bar dragging" : "dr-bar"}
      role="toolbar"
      aria-label="Drawing tools"
      aria-orientation="vertical"
    >
      <span
        className="dr-grip"
        title="Drag to move the bar · double-click to put it back"
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => setStored(null)}
      >
        <GripIcon size={22} />
      </span>

      {ORDER.map((t) => {
        const Glyph = TOOL_ICONS[t];
        return (
          <button
            key={t}
            className={tool === t ? "dr-btn active" : "dr-btn"}
            title={toolsDisabled ? "Choose where the replay starts first" : tool === t ? `${TOOL_NAMES[t]} — press Esc to stop` : TOOL_NAMES[t]}
            aria-label={TOOL_NAMES[t]}
            aria-pressed={tool === t}
            disabled={toolsDisabled}
            onClick={() => onTool(tool === t ? null : t)}
          >
            <Glyph size={28} />
          </button>
        );
      })}

      <span className="dr-sep" />

      <button
        className={hidden ? "dr-btn small active" : "dr-btn small"}
        title={hidden ? "Show the drawings" : "Hide the drawings"}
        aria-label={hidden ? "Show the drawings" : "Hide the drawings"}
        aria-pressed={hidden}
        onClick={onToggleHidden}
      >
        {hidden ? <EyeOffIcon size={24} /> : <EyeIcon size={24} />}
      </button>
      <RemoveMenu symbol={symbol} onRemove={onRemove} />
      <button
        className="dr-btn small"
        title="Documentation: drawing tools, and how to draw from a script"
        aria-label="Documentation"
        onClick={onDocs}
      >
        <BookIcon size={24} />
      </button>
    </div>
  );
}

type Summary = Record<string, { total: number; locked: number }>;

/** About how big the menu is, to open it on the side that has the room. */
const POPUP = { width: 280, height: 250 };

/**
 * The trash: a small menu of what can be removed — the drawings of this symbol or of every symbol, and
 * the locked ones, which the others leave alone. Each entry says how many it would remove and asks twice.
 */
function RemoveMenu({ symbol, onRemove }: { symbol: string | null; onRemove: Props["onRemove"] }) {
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [armed, setArmed] = useState<string | null>(null);
  const [flip, setFlip] = useState({ left: false, up: false });
  const ref = useDismiss<HTMLSpanElement>(() => setOpen(false), open);

  // What there is to remove is read when the menu opens (a script or another tab may have added to it).
  useEffect(() => {
    if (!open) {
      setArmed(null);
      return;
    }
    let live = true;
    drawingApi
      .summary()
      .then((all) => live && setSummary(all))
      .catch(() => live && setSummary({}));
    return () => {
      live = false;
    };
  }, [open]);

  // Open on the side of the button that has the room.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = ref.current;
    const host = anchor?.closest(".dr-root");
    if (!anchor || !host) return;
    const a = anchor.getBoundingClientRect();
    const h = host.getBoundingClientRect();
    setFlip({ left: a.right + 12 + POPUP.width > h.right, up: a.top + POPUP.height > h.bottom });
  }, [open, ref]);

  useEffect(() => {
    if (!armed) return;
    const id = window.setTimeout(() => setArmed(null), 3000);
    return () => window.clearTimeout(id);
  }, [armed]);

  const here = symbol && summary ? summary[symbol] : undefined;
  const everywhere = Object.values(summary ?? {});
  const hereLocked = here?.locked ?? 0;
  const hereLoose = (here?.total ?? 0) - hereLocked;
  const allLocked = everywhere.reduce((n, s) => n + s.locked, 0);
  const allLoose = everywhere.reduce((n, s) => n + s.total, 0) - allLocked;
  const name = symbol ?? "this symbol";

  const rows: { key: string; label: string; count: number; which: "symbol" | "all"; locked: LockedScope }[] = [
    { key: "here", label: `On ${name}`, count: hereLoose, which: "symbol", locked: "exclude" },
    { key: "all", label: "On all symbols", count: allLoose, which: "all", locked: "exclude" },
    { key: "here-locked", label: `Locked ones on ${name}`, count: hereLocked, which: "symbol", locked: "only" },
    { key: "all-locked", label: "Locked ones on all symbols", count: allLocked, which: "all", locked: "only" },
  ];

  const press = (row: (typeof rows)[number]) => {
    if (armed !== row.key) {
      setArmed(row.key);
      return;
    }
    setArmed(null);
    setOpen(false);
    void onRemove(row.which, row.locked);
  };

  return (
    <span className="dr-anchor" ref={ref}>
      <button
        className={open ? "dr-btn small active" : "dr-btn small"}
        title="Remove drawings…"
        aria-label="Remove drawings"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <TrashIcon size={24} />
      </button>
      {open && (
        <div className={`dr-pop${flip.left ? " left" : ""}${flip.up ? " up" : ""}`} role="menu" aria-label="Remove drawings">
          <div className="dr-pop-title">Remove drawings</div>
          {rows.slice(0, 2).map((row) => (
            <RemoveRow key={row.key} row={row} armed={armed === row.key} loading={summary === null} onPress={() => press(row)} />
          ))}
          <div className="dr-pop-sep" />
          <div className="dr-pop-title">Locked drawings</div>
          {rows.slice(2).map((row) => (
            <RemoveRow key={row.key} row={row} armed={armed === row.key} loading={summary === null} onPress={() => press(row)} />
          ))}
          <p className="dr-pop-note">A locked drawing stays when the others are removed. Remove it here, or unlock it first.</p>
        </div>
      )}
    </span>
  );
}

function RemoveRow({
  row,
  armed,
  loading,
  onPress,
}: {
  row: { key: string; label: string; count: number };
  armed: boolean;
  loading: boolean;
  onPress: () => void;
}) {
  const none = !loading && row.count === 0;
  return (
    <button
      className={armed ? "dr-pop-row armed" : "dr-pop-row"}
      role="menuitem"
      data-key={row.key}
      disabled={loading || none}
      onClick={onPress}
    >
      <span>{armed ? `Click again to remove ${row.count}` : row.label}</span>
      <b>{loading ? "…" : row.count}</b>
    </button>
  );
}
