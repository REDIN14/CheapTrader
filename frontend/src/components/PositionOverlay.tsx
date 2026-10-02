// On-chart position tags, modelled on TradingView's paper-trading tags.
//
//   - - - - - [TP][SL] [ 0.10 │ −0.42 USD │ ✕ ] - - - - - - -  entry line
//
// Each open position gets a tag riding its entry line: the lot size, the live
// profit or loss, and a ✕ that closes the position.
//
// While a position has no stop or target, a dotted TP / SL button sits beside the
// tag. Drag it onto the chart and let go where the level should be (a ghost line
// follows the pointer and shows what it would cost or make); or just click it to
// put the level at a sensible distance. Esc, or letting go off the chart, cancels.
//
// Every level that exists has its own tag on its own line, and the tag is a grab
// handle: drag it up or down to move the level (the line itself can be dragged
// too). Only levels the broker actually holds are ever drawn, so the chart never
// shows a stop that does not exist.
//
// Tags are DOM positioned from the chart's real price scale on every animation
// frame (see PriceTags for why), and nudged apart when two prices are close.

import { Fragment, useCallback, useMemo, useReducer, useRef, useState } from "react";
import type { ChartGeometry } from "../lib/chart";
import { formatLots, formatMoney } from "../lib/format";
import { useAnimationFrame } from "../lib/hooks";
import { levelProblem, pnlAt, type Level } from "../lib/positions";
import type { Position } from "../lib/types";
import { CloseIcon } from "./Icons";

export interface PositionLevels {
  sl: number;
  tp: number;
  slSet: boolean;
  tpSet: boolean;
}

interface Props {
  positions: Position[];
  digits: number;
  /** Account currency shown after money values; empty hides it. */
  currency: string;
  geometry: ChartGeometry | null;
  levelsFor: (position: Position) => PositionLevels;
  /** Creates a stop or target at the suggested distance (a click on TP / SL). */
  onCreateLevel: (ticket: number, level: Level) => void;
  /** Places a stop or target at the price it was dropped on. */
  onPlaceLevel: (ticket: number, level: Level, price: number) => void;
  /** Removes a stop or target on the broker. */
  onClearLevel: (ticket: number, level: Level) => void;
  /** Live preview while a level is dragged. */
  onDragLevel: (ticket: number, level: Level, price: number) => void;
  /** Persists the dragged level. */
  onCommitLevel: (ticket: number, level: Level, price: number, delta: number) => void;
  /** A drag was cut short (the window lost focus): the level goes back to `startPrice`. */
  onCancelDrag: (ticket: number, level: Level, startPrice: number) => void;
  onClosePosition: (ticket: number) => void;
  /** Positions whose close is on its way to the broker. */
  closing?: ReadonlySet<number>;
  /** Levels whose change is on its way to the broker, as "ticket:sl" / "ticket:tp". */
  pending?: ReadonlySet<string>;
}

const TAG_H = 20;
const TAG_GAP = 2;
/** Pointer travel (px) below which a press on a tag or button counts as a click. */
const DRAG_THRESHOLD = 3;

interface TagSpec {
  key: string;
  price: number;
}

/** A TP / SL button being dragged onto the chart. */
interface Placing {
  ticket: number;
  level: Level;
  price: number;
  /** Chart-local y of the pointer. */
  y: number;
}

export function PositionOverlay({
  positions,
  digits,
  currency,
  geometry,
  levelsFor,
  onCreateLevel,
  onPlaceLevel,
  onClearLevel,
  onDragLevel,
  onCommitLevel,
  onCancelDrag,
  onClosePosition,
  closing,
  pending,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const elements = useRef(new Map<string, HTMLDivElement>());
  const refCache = useRef(new Map<string, (el: HTMLDivElement | null) => void>());
  const [placing, setPlacing] = useState<Placing | null>(null);

  /** A stable callback ref per tag, so React does not detach and re-attach it on every render. */
  const refFor = useCallback((key: string) => {
    let fn = refCache.current.get(key);
    if (!fn) {
      fn = (el) => {
        if (el) elements.current.set(key, el);
        else elements.current.delete(key);
      };
      refCache.current.set(key, fn);
    }
    return fn;
  }, []);

  // Everything that needs a place on the chart, with the price it belongs to.
  const specs = useMemo<TagSpec[]>(() => {
    const out: TagSpec[] = [];
    for (const p of positions) {
      const lv = levelsFor(p);
      out.push({ key: `entry-${p.ticket}`, price: p.price_open });
      if (lv.slSet) out.push({ key: `sl-${p.ticket}`, price: p.sl });
      if (lv.tpSet) out.push({ key: `tp-${p.ticket}`, price: p.tp });
    }
    return out;
  }, [positions, levelsFor]);

  useAnimationFrame(() => {
    const g = geometry;
    const root = rootRef.current;
    if (!g || !root) return;

    const scaleW = String(g.scaleWidth());
    if (root.dataset.scaleW !== scaleW) {
      root.dataset.scaleW = scaleW;
      root.style.setProperty("--ct-scale-w", `${scaleW}px`);
    }

    const paneH = g.paneHeight();
    const placed: { el: HTMLDivElement; y: number }[] = [];
    for (const spec of specs) {
      const el = elements.current.get(spec.key);
      if (!el) continue;
      const y = g.priceToY(spec.price);
      if (y == null || y < -TAG_H || y > paneH + TAG_H) {
        el.style.visibility = "hidden";
        continue;
      }
      placed.push({ el, y });
    }

    // Tags whose prices are within a tag's height of each other are spread out
    // downwards instead of stacking on top of one another.
    placed.sort((a, b) => a.y - b.y);
    let floor = Number.NEGATIVE_INFINITY;
    for (const item of placed) {
      const y = Math.max(item.y, floor + TAG_H + TAG_GAP);
      floor = y;
      item.el.style.visibility = "visible";
      item.el.style.transform = `translateY(${Math.round(y - TAG_H / 2)}px)`;
    }
  }, geometry != null && specs.length > 0);

  /**
   * Drag a level by its tag.
   *
   * The pointer's absolute position says nothing about the level (the tag may
   * have been nudged away from its line), so what matters is how far the pointer
   * travels: that distance is converted through the chart's price scale and
   * applied to the level's own starting price. Dragging down always lowers the
   * level, dragging up always raises it.
   */
  const beginDrag = useCallback(
    (e: React.PointerEvent, ticket: number, level: Level, startPrice: number) => {
      if (e.button !== 0 || !geometry) return;
      if ((e.target as HTMLElement).closest("button")) return; // the ✕ is a button, not a handle
      const perPixel = geometry.pricePerPixel();
      if (!perPixel) return;
      e.preventDefault();
      e.stopPropagation();

      const startY = e.clientY;
      // y grows downwards while price grows upwards, and pricePerPixel() is
      // signed accordingly, so pointer travel maps straight onto a price delta.
      const levelAt = (clientY: number) => startPrice + (clientY - startY) * perPixel;

      // A press that barely moves is a click on the tag, not a drag: it must not
      // nudge the level and send a modification to the broker.
      let dragged = false;
      const move = (ev: PointerEvent) => {
        if (!dragged && Math.abs(ev.clientY - startY) < DRAG_THRESHOLD) return;
        dragged = true;
        onDragLevel(ticket, level, levelAt(ev.clientY));
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", cancel);
        window.removeEventListener("blur", cancel);
      };
      const up = (ev: PointerEvent) => {
        stop();
        if (!dragged) return;
        const final = levelAt(ev.clientY);
        onCommitLevel(ticket, level, final, final - startPrice);
      };
      // Also when the window loses focus mid-drag: the release would never arrive.
      const cancel = () => {
        stop();
        if (dragged) onCancelDrag(ticket, level, startPrice); // puts the preview back
      };

      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", cancel);
      window.addEventListener("blur", cancel);
    },
    [geometry, onDragLevel, onCommitLevel, onCancelDrag],
  );

  /**
   * Drag a TP / SL button onto the chart to place that level where it is dropped.
   *
   * Nothing is sent until the pointer is released. A press that barely moves is a
   * plain click and places the level at the default distance; a drop outside the
   * chart, a pointer cancel or Esc places nothing.
   */
  const beginPlace = useCallback(
    (e: React.PointerEvent, ticket: number, level: Level) => {
      if (e.button !== 0 || !geometry) return;
      e.preventDefault();
      e.stopPropagation();

      const g = geometry;
      const startX = e.clientX;
      const startY = e.clientY;
      const bodyCursor = document.body.style.cursor;
      let dragged = false;

      const localY = (clientY: number) => clientY - g.containerTop();
      /** Chart price under the pointer, or null when it is off the price pane. */
      const priceAt = (ev: PointerEvent): number | null => {
        const rect = rootRef.current?.getBoundingClientRect();
        const y = localY(ev.clientY);
        if (!rect || ev.clientX < rect.left || ev.clientX > rect.right) return null;
        if (y < 0 || y > g.paneHeight()) return null;
        return g.localYToPrice(y);
      };

      const move = (ev: PointerEvent) => {
        if (!dragged && Math.hypot(ev.clientX - startX, ev.clientY - startY) < DRAG_THRESHOLD) return;
        dragged = true;
        document.body.style.cursor = "ns-resize";
        const price = priceAt(ev);
        setPlacing(price == null ? null : { ticket, level, price, y: localY(ev.clientY) });
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", stop);
        window.removeEventListener("blur", stop);
        window.removeEventListener("keydown", key, true);
        document.body.style.cursor = bodyCursor;
        setPlacing(null);
      };
      const up = (ev: PointerEvent) => {
        stop();
        if (!dragged) {
          onCreateLevel(ticket, level);
          return;
        }
        const price = priceAt(ev);
        if (price != null) onPlaceLevel(ticket, level, price);
      };
      const key = (ev: KeyboardEvent) => {
        if (ev.key !== "Escape") return;
        ev.stopPropagation(); // cancel the placement only, not a replay behind it
        stop();
      };

      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", stop);
      window.addEventListener("blur", stop);
      window.addEventListener("keydown", key, true);
    },
    [geometry, onCreateLevel, onPlaceLevel],
  );

  if (!positions.length) return null;

  const placingPosition = placing ? positions.find((p) => p.ticket === placing.ticket) : undefined;

  return (
    <div className="tv-ptags" ref={rootRef}>
      {positions.map((p) => {
        const lv = levelsFor(p);
        const isBuy = p.side === "BUY";
        const profit = p.profit;

        const levelTag = (level: Level, price: number) => {
          const value = pnlAt(p, price);
          const name = level === "sl" ? "stop loss" : "take profit";
          const waiting = pending?.has(`${p.ticket}:${level}`) ?? false;
          return (
            <div
              className={waiting ? `tv-ptag level ${level} busy` : `tv-ptag level ${level}`}
              ref={refFor(`${level}-${p.ticket}`)}
              title={waiting ? "Waiting for the broker…" : undefined}
            >
              <div
                className="tv-ptag-main drag"
                title={`Drag up or down to move the ${name}`}
                onPointerDown={(e) => beginDrag(e, p.ticket, level, price)}
              >
                <span className="tv-ptag-qty">{level.toUpperCase()}</span>
                <span
                  className={
                    value == null ? "tv-ptag-pl" : value >= 0 ? "tv-ptag-pl up" : "tv-ptag-pl down"
                  }
                >
                  {value == null ? price.toFixed(digits) : formatMoney(value, currency, true)}
                </span>
                <button
                  className="tv-ptag-x"
                  title={`Remove the ${name}`}
                  onClick={() => onClearLevel(p.ticket, level)}
                >
                  <CloseIcon size={18} />
                </button>
              </div>
            </div>
          );
        };

        // A pointer press places the level (see beginPlace); a click with no
        // pointer behind it is the keyboard, which gets the default distance. (So
        // does a click made before the chart has a price scale to drag over.)
        const addButton = (level: Level) => {
          const name = level === "sl" ? "stop loss" : "take profit";
          return (
            <button
              className={`tv-ptag-add ${level}`}
              title={`Drag onto the chart to place a ${name}, or click for a default distance`}
              onPointerDown={(e) => beginPlace(e, p.ticket, level)}
              onClick={(e) => {
                if (e.detail === 0 || !geometry) onCreateLevel(p.ticket, level);
              }}
            >
              {level.toUpperCase()}
            </button>
          );
        };

        const closingNow = closing?.has(p.ticket) ?? false;
        const sideClass = isBuy ? "tv-ptag buy" : "tv-ptag sell";
        return (
          <Fragment key={p.ticket}>
            <div className={closingNow ? `${sideClass} busy` : sideClass} ref={refFor(`entry-${p.ticket}`)}>
              {!lv.tpSet && addButton("tp")}
              {!lv.slSet && addButton("sl")}
              <div className="tv-ptag-main">
                <span className="tv-ptag-qty">{formatLots(p.volume)}</span>
                <span className={profit >= 0 ? "tv-ptag-pl up" : "tv-ptag-pl down"}>
                  {formatMoney(profit, currency, true)}
                </span>
                <button
                  className="tv-ptag-x"
                  title={closingNow ? "Closing…" : `Close ${p.side} ${formatLots(p.volume)} ${p.symbol}`}
                  disabled={closingNow}
                  onClick={() => onClosePosition(p.ticket)}
                >
                  {closingNow ? <span className="tv-ptag-wait" /> : <CloseIcon size={18} />}
                </button>
              </div>
            </div>
            {lv.slSet && levelTag("sl", p.sl)}
            {lv.tpSet && levelTag("tp", p.tp)}
          </Fragment>
        );
      })}

      {placing && placingPosition && geometry && (
        <PlacementGhost
          placing={placing}
          position={placingPosition}
          geometry={geometry}
          digits={digits}
          currency={currency}
        />
      )}
    </div>
  );
}

/**
 * The line, tag and price-axis label that follow the pointer while a TP / SL
 * button is being dragged. They are dimmed when the level would be on the wrong
 * side of the entry, which is what the drop would be refused for.
 */
function PlacementGhost({
  placing,
  position,
  geometry,
  digits,
  currency,
}: {
  placing: Placing;
  position: Position;
  geometry: ChartGeometry;
  digits: number;
  currency: string;
}) {
  const { level, y } = placing;
  // The pointer can hold still while the chart's scale keeps moving (live ticks
  // autoscale it), so the price under the line is read again on every frame; the
  // label then always matches the price the drop would use.
  const [, refresh] = useReducer((n: number) => n + 1, 0);
  useAnimationFrame(refresh);
  const price = geometry.localYToPrice(y) ?? placing.price;
  const rounded = Number(price.toFixed(digits));
  const invalid = levelProblem(position, level, rounded, digits) !== null;
  const value = pnlAt(position, rounded);
  const cls = `${level}${invalid ? " invalid" : ""}`;

  return (
    <>
      <div className={`tv-ghost-line ${cls}`} style={{ transform: `translateY(${y}px)` }} />
      <div
        className={`tv-ptag level ghost ${cls}`}
        style={{ visibility: "visible", transform: `translateY(${Math.round(y - TAG_H / 2)}px)` }}
      >
        <div className="tv-ptag-main">
          <span className="tv-ptag-qty">{level.toUpperCase()}</span>
          <span className={value == null ? "tv-ptag-pl" : value >= 0 ? "tv-ptag-pl up" : "tv-ptag-pl down"}>
            {value == null ? rounded.toFixed(digits) : formatMoney(value, currency, true)}
          </span>
        </div>
      </div>
      <div
        className={`tv-ghost-axis ${cls}`}
        style={{ transform: `translateY(${Math.round(y - TAG_H / 2)}px)` }}
      >
        {rounded.toFixed(digits)}
      </div>
    </>
  );
}
