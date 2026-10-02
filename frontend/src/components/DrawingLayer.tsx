// Drawings on the chart: the sheet they are drawn on, the bar of tools, the little bar that appears over
// a selected drawing, and the menu a right-click on a drawing opens.
//
// The sheet is an SVG laid exactly over the candles. It lets everything through to the chart (pan,
// zoom, crosshair) except where a drawing is: its lines and boxes take the pointer, so a drawing
// can be selected and dragged by its body or by its handles. While a tool is armed, nothing is
// taken: the clicks go to the chart, which reports where they were, and each one places a point.
//
// Where a drawing is on the screen is worked out from (time, price) on every frame in which the
// chart's view changed (pan, zoom, a new candle, the price scale moving), so drawings stay on the
// market however the chart is moved.
//
// A locked drawing can be selected and restyled but not moved or removed. A long / short box is also a
// trade: it knows how big it is and can place itself (see lib/boxTrading.ts).

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type { ClearResult, LockedScope } from "../lib/api";
import type { ChartGeometry } from "../lib/chart";
import { enterAt, type BoxOrder } from "../lib/boxOrder";
import { notesOf, orderRequest, viewOf, type BoxTrading, type BoxView } from "../lib/boxTrading";
import { buildDrawingMenu } from "../lib/boxMenu";
import {
  TOOL_NAMES,
  TOOL_POINTS,
  averageRange,
  createDrawing,
  draft,
  drag,
  layout,
  tidy,
  type CreateContext,
  type Drawing,
  type DrawingPoint,
  type DrawingStyle,
  type Layout,
  type Mapper,
  type Pointer,
  type Prim,
  type Tool,
} from "../lib/drawings";
import { useAnimationFrame } from "../lib/hooks";
import { usePersistentState } from "../lib/persist";
import type { Bar, Position } from "../lib/types";
import { useDrawings } from "../lib/useDrawings";
import { ChartContextMenu, type ContextMenuItem } from "./ChartContextMenu";
import { StyleBar } from "./DrawingStyleBar";
import { DrawingToolbar } from "./DrawingToolbar";

interface Props {
  geometry: ChartGeometry | null;
  symbol: string | null;
  digits: number;
  /** The candles on screen (a position box is sized from their average range). */
  bars: Bar[];
  /** Seconds one candle takes. */
  barSeconds: number;
  /** Shapes that indicators draw: shown like the others, but they belong to the indicator. */
  indicatorDrawings: Drawing[];
  /** The chart is busy with something that takes the clicks (choosing where a replay starts): no tools meanwhile. */
  paused: boolean;
  /** The account and the market, for the orders a long / short box can place. */
  trading: BoxTrading;
  onDocs: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}

/** What is being dragged. */
interface Grab {
  id: string;
  handle: string;
  start: Drawing;
  from: Pointer;
  pointer: number;
  moved: boolean;
}

/** How wide the bar over a selected drawing is, for keeping it inside the chart. */
const STYLE_BAR_W = 400;
const STYLE_BAR_W_BOX = 640;
const STYLE_BAR_H = 40;

function hintFor(tool: Tool, placed: number): string {
  const steps: Record<Tool, string[]> = {
    trendline: ["Click where the line starts", "Click where it ends"],
    rectangle: ["Click one corner", "Click the opposite corner"],
    channel: ["Click where the line starts", "Click where it ends", "Click to set the width of the channel"],
    long: ["Click where you would buy"],
    short: ["Click where you would sell"],
  };
  return `${TOOL_NAMES[tool]}: ${steps[tool][Math.min(placed, steps[tool].length - 1)]} · Esc to cancel`;
}

const isTyping = (target: EventTarget | null) => {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
};

/** What a bulk removal says it did. */
function removalNotice(result: ClearResult, which: "symbol" | "all", locked: LockedScope): string {
  const n = result.removed;
  const what = locked === "only" ? "locked drawing" : "drawing";
  const where = which === "all" ? " on all symbols" : "";
  if (n === 0) return result.kept_locked > 0 ? `Nothing to remove${where}: ${result.kept_locked} locked ones stay.` : `No drawings to remove${where}.`;
  const kept = result.kept_locked > 0 ? ` · ${result.kept_locked} locked ${result.kept_locked === 1 ? "one was" : "ones were"} kept` : "";
  return `Removed ${n} ${what}${n === 1 ? "" : "s"}${where}${kept}`;
}

export function DrawingController({
  geometry,
  symbol,
  digits,
  bars,
  barSeconds,
  indicatorDrawings,
  paused,
  trading,
  onDocs,
  onError,
  onNotice,
}: Props) {
  const store = useDrawings(symbol, onError);
  const [hidden, setHidden] = usePersistentState("drawingsHidden", false);
  const [tool, setTool] = useState<Tool | null>(null);
  const [placed, setPlaced] = useState<DrawingPoint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; id: number; items: ContextMenuItem[] } | null>(null);
  const [, redraw] = useState(0);

  const svgRef = useRef<SVGSVGElement>(null);
  const sizeInput = useRef<HTMLInputElement>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const pointerSeq = useRef(0);
  const grab = useRef<Grab | null>(null);
  const lastSig = useRef("");
  const menuCount = useRef(0);
  /** An order from a box is on its way: a second press waits for the answer. */
  const sending = useRef(false);

  // The newest of everything, for the handlers that outlive a render.
  const now = useRef({ geometry, tool, placed, selectedId, bars, barSeconds, store, paused, trading, mapper: null as Mapper | null });
  now.current.paused = paused;
  now.current.geometry = geometry;
  now.current.tool = tool;
  now.current.placed = placed;
  now.current.selectedId = selectedId;
  now.current.bars = bars;
  now.current.barSeconds = barSeconds;
  now.current.store = store;
  now.current.trading = trading;

  // Another symbol: its own drawings, and nothing half done. (Choosing a replay start also cancels a tool.)
  useEffect(() => {
    setTool(null);
    setPlaced([]);
    setSelectedId(null);
    setMenu(null);
  }, [symbol, paused]);

  const pickTool = useCallback(
    (next: Tool | null) => {
      setTool(next);
      setPlaced([]);
      setSelectedId(null);
      setMenu(null);
      if (next) setHidden(false);
    },
    [setHidden],
  );

  /** A click on the chart while a tool is armed: one more point. */
  const place = useCallback((at: { x: number; y: number }) => {
    const s = now.current;
    const g = s.geometry;
    if (!g || !s.tool || s.paused) return;
    // the price scale, the time scale and the indicator panes are not part of the drawing area
    if (at.x < 0 || at.y < 0 || at.x > g.plotWidth() || at.y > g.paneHeight()) return;
    const time = g.xToTime(at.x);
    const price = g.localYToPrice(at.y);
    if (time == null || price == null) return;
    const points = [...s.placed, { time, price }];
    if (points.length < TOOL_POINTS[s.tool]) {
      setPlaced(points);
      return;
    }
    const made = tidy(createDrawing(s.tool, points, { barSeconds: s.barSeconds, risk: averageRange(s.bars) }));
    s.store.add(made);
    setSelectedId(made.id);
    setTool(null);
    setPlaced([]);
  }, []);

  useEffect(() => {
    if (!geometry) return;
    const offMove = geometry.onPointer((at) => {
      pointer.current = at;
      pointerSeq.current += 1;
    });
    const offClick = geometry.onPointClick((at) => {
      if (now.current.tool) place(at);
      else setSelectedId(null);
    });
    return () => {
      offMove();
      offClick();
    };
  }, [geometry, place]);

  // Esc backs out one step at a time; Delete removes the selected drawing (unless it is locked).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      // a dialog or a menu is open: it owns the keys
      if (document.querySelector('[aria-modal="true"], .tv-ctxmenu')) return;
      const s = now.current;
      if (e.key === "Escape") {
        if (s.placed.length) setPlaced([]);
        else if (s.tool) setTool(null);
        else if (s.selectedId) setSelectedId(null);
        else return;
        e.stopPropagation(); // that was all Esc was for; it must not also end a replay
      } else if ((e.key === "Delete" || e.key === "Backspace") && s.selectedId && !s.tool) {
        const d = s.store.drawings.find((x) => x.id === s.selectedId);
        if (!d) return;
        e.preventDefault();
        if (d.locked) {
          onNotice("That drawing is locked: unlock it (the padlock above it) to delete it.");
          return;
        }
        s.store.remove(d.id);
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onNotice]);

  // A selected drawing that is gone (removed by a script, or by another tab) is no longer selected.
  useEffect(() => {
    if (selectedId && !store.drawings.some((d) => d.id === selectedId)) setSelectedId(null);
  }, [store.drawings, selectedId]);

  // -- the view ------------------------------------------------------------------------
  const userDrawings = hidden ? [] : store.drawings;
  const everything = [...indicatorDrawings, ...userDrawings];

  // Re-draw when the chart shows something else (or the pointer moved while a shape is being placed).
  useAnimationFrame(() => {
    const g = now.current.geometry;
    if (!g) return;
    const sig = `${g.signature()}|${now.current.tool && now.current.placed.length ? pointerSeq.current : 0}`;
    if (sig === lastSig.current) return;
    lastSig.current = sig;
    redraw((n) => n + 1);
  }, geometry != null && (everything.length > 0 || tool != null));

  const g = geometry;
  const width = g ? Math.max(0, Math.round(g.plotWidth())) : 0;
  const height = g ? Math.max(0, Math.round(g.paneHeight())) : 0;
  const mapper: Mapper | null =
    g && width > 0 && height > 0
      ? { x: g.timeToX, y: g.priceToY, time: g.xToTime, price: g.localYToPrice, width, height }
      : null;
  now.current.mapper = mapper;

  const ctx: CreateContext = { barSeconds, risk: averageRange(bars) };

  const toPointer = (clientX: number, clientY: number): Pointer | null => {
    const geo = now.current.geometry;
    const svg = svgRef.current;
    if (!geo || !svg) return null;
    const box = svg.getBoundingClientRect();
    const x = clientX - box.left;
    const y = clientY - box.top;
    const time = geo.xToTime(x);
    const price = geo.localYToPrice(y);
    return time == null || price == null ? null : { time, price, x, y };
  };

  // -- grabbing, dragging ----------------------------------------------------------------
  const begin = (e: ReactPointerEvent, id: string, handle: string) => {
    if (e.button !== 0 || now.current.tool) return;
    const start = now.current.store.drawings.find((d) => d.id === id);
    e.stopPropagation();
    e.preventDefault();
    if (!start) return;
    setMenu(null);
    setSelectedId(id);
    if (start.locked) return; // it can be selected, to unlock it or restyle it, but not moved
    const from = toPointer(e.clientX, e.clientY);
    if (!from) return;
    grab.current = { id, handle, start, from, pointer: e.pointerId, moved: false };
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  };

  const move = (e: ReactPointerEvent) => {
    const hold = grab.current;
    if (!hold || hold.pointer !== e.pointerId) return;
    const at = toPointer(e.clientX, e.clientY);
    if (!at) return;
    hold.moved = true;
    now.current.store.preview(
      tidy(drag(hold.start, hold.handle, hold.from, at, now.current.mapper ?? undefined, now.current.barSeconds)),
    );
  };

  const release = (e: ReactPointerEvent) => {
    const hold = grab.current;
    if (!hold || hold.pointer !== e.pointerId) return;
    grab.current = null;
    if (hold.moved) now.current.store.save(hold.id);
  };

  /** The wheel over a drawing zooms the chart, as it does anywhere else on it. */
  const wheel = (e: ReactWheelEvent) => {
    const svg = svgRef.current;
    if (!svg) return;
    const below = document.elementsFromPoint(e.clientX, e.clientY).find((el) => !svg.contains(el));
    below?.dispatchEvent(
      new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        clientX: e.clientX,
        clientY: e.clientY,
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        deltaMode: e.deltaMode,
        ctrlKey: e.ctrlKey,
        shiftKey: e.shiftKey,
      }),
    );
  };

  const restyle = (id: string, change: DrawingStyle) => {
    const d = now.current.store.drawings.find((x) => x.id === id);
    if (!d) return;
    now.current.store.preview({ ...d, style: { ...d.style, ...change } });
    now.current.store.save(id);
  };

  // -- orders from a long / short box ----------------------------------------------------------
  const sendOrder = async (order: BoxOrder, id: string) => {
    if (sending.current || !symbol) return;
    sending.current = true;
    try {
      const result = await now.current.trading.place(orderRequest(symbol, order, digits));
      // A trade made at the market starts where it really opened: the box's entry line goes there.
      if (result && order.how === "market") enterWhereOpened(id, result.price);
    } finally {
      sending.current = false;
    }
  };

  /** Move a box's entry line to the price its trade was filled at (and to the candle it opened in). */
  const enterWhereOpened = (id: string, price: number) => {
    const s = now.current;
    const d = s.store.drawings.find((x) => x.id === id);
    // (a locked box stays as it was drawn, and one that is being dragged right now is the user's)
    if (!d || d.locked || grab.current?.id === id) return;
    const last = s.bars.length ? s.bars[s.bars.length - 1].time : null;
    const moved = enterAt(d, Number(price.toFixed(digits)), last);
    if (!moved) return;
    s.store.preview(moved);
    s.store.save(id);
  };

  const applyLevels = (position: Position, view: BoxView) => {
    const round = (v: number) => Number(v.toFixed(digits));
    now.current.trading.setLevels(position.ticket, round(view.plan.stop), round(view.plan.target));
  };

  const removeDrawing = (d: Drawing) => {
    if (d.locked) {
      onNotice("That drawing is locked: unlock it to delete it.");
      return;
    }
    store.remove(d.id);
    setSelectedId(null);
  };

  /** The menu of a right-click on a drawing (or one of its handles). */
  const openMenu = (e: ReactMouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation(); // the chart's own menu is for the chart
    const d = now.current.store.drawings.find((x) => x.id === id);
    if (!d || now.current.tool) return;
    setSelectedId(id);
    const view = viewOf(d, now.current.trading);
    menuCount.current += 1;
    setMenu({
      x: e.clientX,
      y: e.clientY,
      id: menuCount.current,
      items: buildDrawingMenu(d, view, now.current.trading, {
        order: (order) => void sendOrder(order, d.id),
        applyTo: (position) => view && applyLevels(position, view),
        setSize: (change) => restyle(d.id, change),
        editSize: () => window.requestAnimationFrame(() => {
          sizeInput.current?.focus();
          sizeInput.current?.select();
        }),
        lock: (locked) => now.current.store.lock(d.id, locked),
        remove: () => removeDrawing(d),
      }),
    });
  };

  const removeMany = async (which: "symbol" | "all", locked: LockedScope) => {
    const result = await store.clear(which, locked);
    setSelectedId(null);
    if (result) onNotice(removalNotice(result, which, locked));
  };

  // -- what to draw ----------------------------------------------------------------------
  const volumeStep = trading.symbol?.volume_step ?? 0.01;
  const shapes = mapper
    ? everything.map((d) => {
        const readonly = !!d.owner;
        // a box of the user's says how big its trade is; one an indicator draws is only a picture
        const view = !readonly && (d.type === "long" || d.type === "short") ? viewOf(d, trading) : null;
        return { drawing: d, lay: layout(d, mapper, digits, notesOf(view, trading.currency, volumeStep)), readonly, view };
      })
    : [];

  let ghost: Layout | null = null;
  if (mapper && tool && placed.length && pointer.current) {
    const time = mapper.time(pointer.current.x);
    const price = mapper.price(pointer.current.y);
    const sketch = time != null && price != null ? draft(tool, placed, { time, price }, ctx) : null;
    if (sketch) ghost = layout(sketch, mapper, digits);
  }

  const selected = shapes.find((s) => s.drawing.id === selectedId && !s.readonly) ?? null;

  let styleBar: { left: number; top: number } | null = null;
  if (selected && mapper && selected.lay.handles.length) {
    const barWidth = selected.view ? STYLE_BAR_W_BOX : STYLE_BAR_W;
    const xs = selected.lay.handles.map((h) => h.x);
    const ys = selected.lay.handles.map((h) => h.y);
    const middle = (Math.min(...xs) + Math.max(...xs)) / 2;
    styleBar = {
      left: Math.round(Math.max(8, Math.min(middle - barWidth / 2, mapper.width - barWidth - 8))),
      top: Math.round(Math.max(8, Math.min(Math.min(...ys) - STYLE_BAR_H - 14, mapper.height - STYLE_BAR_H - 8))),
    };
  }

  return (
    <div className="dr-root" data-armed={tool ? "true" : "false"}>
      {mapper && (
        <svg
          ref={svgRef}
          className="dr-svg"
          width={width}
          height={height}
          onPointerMove={move}
          onPointerUp={release}
          onPointerCancel={release}
          onWheel={wheel}
        >
          {shapes.map(({ drawing, lay, readonly }) => (
            <g key={drawing.id} className={drawing.id === selectedId && !readonly ? "dr-shape selected" : "dr-shape"}>
              {lay.prims.map((p, i) => (
                <PrimShape
                  key={i}
                  prim={p}
                  onDown={!readonly && p.k !== "text" && p.hit ? (e) => begin(e, drawing.id, "move") : undefined}
                  onMenu={!readonly && p.k !== "text" && p.hit ? (e) => openMenu(e, drawing.id) : undefined}
                />
              ))}
              {drawing.locked && !readonly && lay.handles[0] && <LockMark x={lay.handles[0].x + 8} y={lay.handles[0].y - 20} />}
            </g>
          ))}

          {ghost && (
            <g className="dr-shape ghost">
              {ghost.prims.map((p, i) => (
                <PrimShape key={i} prim={p} />
              ))}
            </g>
          )}

          {selected &&
            !selected.drawing.locked &&
            selected.lay.handles.map((h) => (
              <circle
                key={h.id}
                className="dr-handle"
                cx={h.x}
                cy={h.y}
                r={5}
                style={{ cursor: h.cursor }}
                onPointerDown={(e) => begin(e, selected.drawing.id, h.id)}
                onContextMenu={(e) => openMenu(e, selected.drawing.id)}
              />
            ))}
        </svg>
      )}

      {selected && styleBar && (
        <div className="dr-style" style={{ left: styleBar.left, top: styleBar.top }} role="toolbar" aria-label="Drawing style">
          <StyleBar
            drawing={selected.drawing}
            view={selected.view}
            trading={trading}
            sizeInput={sizeInput}
            onStyle={(change) => restyle(selected.drawing.id, change)}
            onLock={(locked) => store.lock(selected.drawing.id, locked)}
            onDelete={() => removeDrawing(selected.drawing)}
            onOrder={(order) => void sendOrder(order, selected.drawing.id)}
          />
        </div>
      )}

      {tool && (
        <div className="dr-hint" style={{ top: Math.max(8, height - 44) }}>
          {hintFor(tool, placed.length)}
        </div>
      )}

      <DrawingToolbar
        tool={tool}
        onTool={pickTool}
        toolsDisabled={paused}
        hidden={hidden}
        onToggleHidden={() => {
          setHidden((v) => !v);
          setSelectedId(null);
          setTool(null);
          setPlaced([]);
        }}
        symbol={symbol}
        onRemove={removeMany}
        onDocs={onDocs}
      />

      {menu && <ChartContextMenu key={menu.id} x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />}
    </div>
  );
}

/** A little padlock beside a locked drawing. */
function LockMark({ x, y }: { x: number; y: number }) {
  return (
    <g className="dr-lock" transform={`translate(${x} ${y})`}>
      <rect x="1.5" y="6" width="9" height="6.5" rx="1.4" />
      <path d="M3.4 6V4.3a2.6 2.6 0 0 1 5.2 0V6" fill="none" />
    </g>
  );
}

/** One piece of a drawing; with `onDown` it also takes the pointer, over a wider area than it is drawn in. */
function PrimShape({
  prim: p,
  onDown,
  onMenu,
}: {
  prim: Prim;
  onDown?: (e: ReactPointerEvent) => void;
  onMenu?: (e: ReactMouseEvent) => void;
}) {
  switch (p.k) {
    case "line":
      return (
        <>
          <line
            x1={p.x1}
            y1={p.y1}
            x2={p.x2}
            y2={p.y2}
            stroke={p.color}
            strokeWidth={p.width}
            strokeDasharray={p.dash}
            strokeLinecap="round"
          />
          {onDown && (
            <line
              className="dr-hit"
              x1={p.x1}
              y1={p.y1}
              x2={p.x2}
              y2={p.y2}
              stroke="transparent"
              strokeWidth={Math.max(12, p.width + 8)}
              onPointerDown={onDown}
              onContextMenu={onMenu}
            />
          )}
        </>
      );

    case "rect":
      return (
        <rect
          className={onDown ? "dr-hit-fill" : undefined}
          x={p.x}
          y={p.y}
          width={Math.max(0, p.w)}
          height={Math.max(0, p.h)}
          fill={p.fill ?? "none"}
          fillOpacity={p.fillOpacity}
          stroke={p.stroke}
          strokeWidth={p.stroke ? p.width : undefined}
          strokeDasharray={p.dash}
          onPointerDown={onDown}
          onContextMenu={onMenu}
        />
      );

    case "poly": {
      const points = p.points.map(([x, y]) => `${x},${y}`).join(" ");
      return (
        <>
          {p.closed ? (
            <polygon points={points} fill={p.fill ?? "none"} fillOpacity={p.fillOpacity} stroke={p.stroke} strokeWidth={p.width} />
          ) : (
            <polyline
              points={points}
              fill="none"
              stroke={p.stroke}
              strokeWidth={p.width}
              strokeDasharray={p.dash}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {onDown && (
            <polyline
              className="dr-hit"
              points={points}
              fill="none"
              stroke="transparent"
              strokeWidth={12}
              onPointerDown={onDown}
              onContextMenu={onMenu}
            />
          )}
        </>
      );
    }

    case "text":
      return (
        <text className="dr-text" x={p.x} y={p.y} fontSize={p.size} fill={p.color} textAnchor={p.anchor ?? "start"}>
          {p.text}
        </text>
      );
  }
}
