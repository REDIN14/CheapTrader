// The replay controls, floating at the top of the chart like TradingView's:
//
//   ⠿ │ [ ✂ Select bar ] │ [ ▶ ] [ ⏭ ] [ 2x ▾ ] │ [ ⏩ ] │ Mon 14 Sep 2026 · 21:15   2,833 / 2,975 │ [ ✕ ]
//
// A thin line along its lower edge shows how far through the loaded window the
// cursor is. Every control has a tooltip that names its key.
//
// The grip at the left end moves the bar. It starts top-centre, which is where a
// position's TP / SL buttons can end up underneath it on a small screen; dragging
// it away puts them in reach again. Where it was left is remembered, as a share of
// the chart's free space, so it stays on screen if the window is resized. Double-
// click the grip to send it back.

import { useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { formatChartTime, formatInt } from "../lib/format";
import { useDismiss } from "../lib/hooks";
import { usePersistentState } from "../lib/persist";
import type { ReplayState } from "../lib/types";
import {
  CheckIcon,
  ChevronDown,
  CloseIcon,
  GripIcon,
  PauseIcon,
  PlayIcon,
  ScissorsIcon,
  SkipEndIcon,
  StepIcon,
} from "./Icons";

interface Props {
  state: ReplayState;
  playing: boolean;
  /** Bars per second. */
  speed: number;
  speeds: number[];
  /** Show the clock time (intraday bars) or just the date. */
  intraday: boolean;
  onToggle: () => void;
  onStep: () => void;
  onSpeed: (value: number) => void;
  onJumpToEnd: () => void;
  onPickAgain: () => void;
  onExit: () => void;
}

/** Where the bar was left: 0 is the left / top of the free space, 1 the right / bottom. */
interface Spot {
  x: number;
  y: number;
}

/**
 * Space kept clear around the bar when it is moved: a margin, and the price scale
 * on the right and the time scale at the bottom. styles.css (.rp-bar.moved) uses
 * the same numbers.
 */
const EDGE = { left: 8, right: 78, top: 8, bottom: 36 };

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

/** A stored spot, if it is a usable one (the value comes from localStorage). */
function asSpot(value: unknown): Spot | null {
  if (typeof value !== "object" || value === null) return null;
  const { x, y } = value as Record<string, unknown>;
  if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x: clamp01(x), y: clamp01(y) };
}

interface Drag {
  pointer: number;
  /** Pointer position and the bar's top-left corner (in the chart's box) when it began. */
  fromX: number;
  fromY: number;
  left: number;
  top: number;
}

export function ReplayToolbar({
  state,
  playing,
  speed,
  speeds,
  intraday,
  onToggle,
  onStep,
  onSpeed,
  onJumpToEnd,
  onPickAgain,
  onExit,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismiss<HTMLSpanElement>(() => setMenuOpen(false), menuOpen);
  const atEnd = state.index >= state.total - 1;
  const done = state.total > 1 ? (state.index / (state.total - 1)) * 100 : 100;

  const barRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [stored, setStored] = usePersistentState<unknown>("replayBarSpot", null);
  const [dragging, setDragging] = useState(false);
  const spot = asSpot(stored);

  const beginDrag = (e: ReactPointerEvent<HTMLSpanElement>) => {
    const bar = barRef.current;
    const host = bar?.offsetParent;
    if (!bar || !host || e.button !== 0) return;
    const b = bar.getBoundingClientRect();
    const h = host.getBoundingClientRect();
    drag.current = { pointer: e.pointerId, fromX: e.clientX, fromY: e.clientY, left: b.left - h.left, top: b.top - h.top };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    setMenuOpen(false);
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

  const classes = ["rp-bar", spot ? "moved" : "", dragging ? "dragging" : ""].filter(Boolean).join(" ");
  const style = spot ? ({ "--fx": spot.x, "--fy": spot.y } as CSSProperties) : undefined;

  return (
    <div className={classes} style={style} ref={barRef} role="toolbar" aria-label="Replay controls">
      <span
        className="rp-grip"
        title="Drag to move the bar · double-click to put it back"
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => setStored(null)}
      >
        <GripIcon size={20} />
      </span>

      <button className="rp-btn text" onClick={onPickAgain} title="Pick a new starting bar (the profile keeps its balance and history)">
        <ScissorsIcon size={20} />
        <span>Select bar</span>
      </button>

      <span className="rp-sep" />

      <button
        className="rp-btn play"
        onClick={onToggle}
        disabled={atEnd && !playing}
        title={playing ? "Pause (Space)" : "Play (Space)"}
        aria-pressed={playing}
      >
        {playing ? <PauseIcon size={24} /> : <PlayIcon size={24} />}
      </button>
      <button className="rp-btn" onClick={onStep} disabled={atEnd} title="Forward one bar (→)">
        <StepIcon size={24} />
      </button>

      <span className="rp-anchor" ref={menuRef}>
        <button
          className={menuOpen ? "rp-btn text speed active" : "rp-btn text speed"}
          onClick={() => setMenuOpen((v) => !v)}
          title="Replay speed, in bars per second"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <span>{speed}x</span>
          <ChevronDown size={16} />
        </button>
        {menuOpen && (
          // Opens upward when the bar has been moved to the lower half of the chart.
          <div className={spot && spot.y > 0.5 ? "rp-menu up" : "rp-menu"} role="menu">
            <div className="rp-menu-title">BARS PER SECOND</div>
            {speeds.map((s) => (
              <button
                key={s}
                role="menuitemradio"
                aria-checked={s === speed}
                className={s === speed ? "rp-menu-item active" : "rp-menu-item"}
                onClick={() => {
                  onSpeed(s);
                  setMenuOpen(false);
                }}
              >
                <span>{s}x</span>
                {s === speed && <CheckIcon size={16} />}
              </button>
            ))}
          </div>
        )}
      </span>

      <span className="rp-sep" />

      <button className="rp-btn" onClick={onJumpToEnd} disabled={atEnd} title="Jump to the last bar">
        <SkipEndIcon size={24} />
      </button>

      <span className="rp-sep" />

      <span className="rp-clock" title="Where the replay is now">
        <b>{formatChartTime(state.cursor_time, intraday)}</b>
        <small>
          {atEnd ? "End · " : ""}
          {formatInt(state.index + 1)} / {formatInt(state.total)}
        </small>
      </span>

      <button className="rp-btn close" onClick={onExit} title="Exit replay (Esc)">
        <CloseIcon size={22} />
      </button>

      <span className="rp-progress" aria-hidden="true">
        <i style={{ width: `${done}%` }} />
      </span>
    </div>
  );
}
