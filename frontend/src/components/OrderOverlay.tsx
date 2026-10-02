// On-chart tags for the orders that wait (limit and stop orders), in the manner of the position tags:
//
//   - - - - - [ BUY LIMIT │ 0.10 │ ✕ ] - - - - -     the price it waits for (drag to move it; ✕ takes it back)
//   - - - - - [ SL │ 1.08350 │ ✕ ]                  its stop loss and take profit, once it has them
//
// Tags are DOM positioned from the chart's real price scale on every animation frame (see PriceTags for
// why) and nudged apart when two prices are close. A tag is a grab handle: drag it up or down to move
// that price. Only what the broker really holds is drawn, so the chart never shows an order that is gone.

import { useCallback, useMemo, useRef } from "react";
import type { ChartGeometry } from "../lib/chart";
import { formatLots } from "../lib/format";
import { useAnimationFrame } from "../lib/hooks";
import { kindTitle } from "../lib/orders";
import type { PendingOrder } from "../lib/types";
import { CloseIcon } from "./Icons";

/** The prices of an order that can be moved. */
export type OrderPart = "price" | "sl" | "tp";

interface Props {
  orders: PendingOrder[];
  digits: number;
  geometry: ChartGeometry | null;
  /** Live preview while a price is dragged. */
  onDrag: (ticket: number, part: OrderPart, price: number) => void;
  /** Persists the dragged price (`delta` is how far it travelled). */
  onCommit: (ticket: number, part: OrderPart, price: number, delta: number) => void;
  /** A drag was cut short (the window lost focus): the price goes back to `startPrice`. */
  onCancelDrag: (ticket: number, part: OrderPart, startPrice: number) => void;
  /** Take the order back. */
  onCancel: (ticket: number) => void;
  /** Remove its stop loss or take profit. */
  onClearLevel: (ticket: number, part: "sl" | "tp") => void;
  /** Orders whose cancelling or changing is on its way to the broker. */
  busy?: ReadonlySet<number>;
}

const TAG_H = 20;
const TAG_GAP = 2;
/** Pointer travel (px) below which a press on a tag counts as a click. */
const DRAG_THRESHOLD = 3;

export function OrderOverlay({ orders, digits, geometry, onDrag, onCommit, onCancelDrag, onCancel, onClearLevel, busy }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const elements = useRef(new Map<string, HTMLDivElement>());
  const refCache = useRef(new Map<string, (el: HTMLDivElement | null) => void>());

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

  const specs = useMemo(() => {
    const out: { key: string; price: number }[] = [];
    for (const o of orders) {
      out.push({ key: `price-${o.ticket}`, price: o.price });
      if (o.sl > 0) out.push({ key: `sl-${o.ticket}`, price: o.sl });
      if (o.tp > 0) out.push({ key: `tp-${o.ticket}`, price: o.tp });
    }
    return out;
  }, [orders]);

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
    // The tags of open positions sit in the same column and are laid out by their own overlay: an order
    // tag keeps clear of them (a position and an order often share a price, e.g. the box's stop).
    const taken: number[] = [];
    for (const other of root.parentElement?.querySelectorAll<HTMLElement>(".tv-ptags:not(.tv-otags) .tv-ptag") ?? []) {
      if (other.style.visibility !== "visible") continue;
      const shift = /translateY\((-?[\d.]+)px\)/.exec(other.style.transform);
      if (shift) taken.push(Number(shift[1]) + TAG_H / 2);
    }
    taken.sort((a, b) => a - b);

    // Tags whose prices are within a tag's height of each other are spread out downwards.
    placed.sort((a, b) => a.y - b.y);
    let floor = Number.NEGATIVE_INFINITY;
    for (const item of placed) {
      let y = Math.max(item.y, floor + TAG_H + TAG_GAP);
      for (const t of taken) {
        if (Math.abs(t - y) < TAG_H + TAG_GAP) y = t + TAG_H + TAG_GAP;
      }
      floor = y;
      item.el.style.visibility = "visible";
      item.el.style.transform = `translateY(${Math.round(y - TAG_H / 2)}px)`;
    }
  }, geometry != null && specs.length > 0);

  /**
   * Drag a price by its tag. The pointer's absolute position says nothing about the price (the tag may
   * have been nudged away from its line), so what matters is how far the pointer travels: that distance
   * is converted through the chart's price scale and applied to the price the drag began at.
   */
  const beginDrag = useCallback(
    (e: React.PointerEvent, ticket: number, part: OrderPart, startPrice: number) => {
      if (e.button !== 0 || !geometry) return;
      if ((e.target as HTMLElement).closest("button")) return; // the ✕ is a button, not a handle
      if (busy?.has(ticket)) return; // the broker is still changing it: wait for its answer
      const perPixel = geometry.pricePerPixel();
      if (!perPixel) return;
      e.preventDefault();
      e.stopPropagation();

      const startY = e.clientY;
      const priceAt = (clientY: number) => startPrice + (clientY - startY) * perPixel;
      let dragged = false;
      const move = (ev: PointerEvent) => {
        if (!dragged && Math.abs(ev.clientY - startY) < DRAG_THRESHOLD) return;
        dragged = true;
        onDrag(ticket, part, priceAt(ev.clientY));
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
        const final = priceAt(ev.clientY);
        onCommit(ticket, part, final, final - startPrice);
      };
      const cancel = () => {
        stop();
        if (dragged) onCancelDrag(ticket, part, startPrice);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", cancel);
      window.addEventListener("blur", cancel);
    },
    [geometry, busy, onDrag, onCommit, onCancelDrag],
  );

  if (!orders.length) return null;

  return (
    <div className="tv-ptags tv-otags" ref={rootRef}>
      {orders.map((o) => {
        const waiting = busy?.has(o.ticket) ?? false;
        const sideClass = o.side === "BUY" ? "tv-ptag buy" : "tv-ptag sell";
        const level = (part: "sl" | "tp", price: number) => {
          const name = part === "sl" ? "stop loss" : "take profit";
          return (
            <div className={waiting ? `tv-ptag level ${part} busy` : `tv-ptag level ${part}`} ref={refFor(`${part}-${o.ticket}`)}>
              <div
                className="tv-ptag-main drag"
                title={`Drag up or down to move the ${name} of this order`}
                onPointerDown={(e) => beginDrag(e, o.ticket, part, price)}
              >
                <span className="tv-ptag-qty">{part.toUpperCase()}</span>
                <span className="tv-ptag-pl">{price.toFixed(digits)}</span>
                <button className="tv-ptag-x" title={`Remove the ${name} of this order`} onClick={() => onClearLevel(o.ticket, part)}>
                  <CloseIcon size={18} />
                </button>
              </div>
            </div>
          );
        };
        return (
          <div key={o.ticket} className="tv-order">
            <div className={waiting ? `${sideClass} order busy` : `${sideClass} order`} ref={refFor(`price-${o.ticket}`)}>
              <div
                className="tv-ptag-main drag"
                title={`${kindTitle(o.order_type)} at ${o.price.toFixed(digits)}: drag up or down to move it`}
                onPointerDown={(e) => beginDrag(e, o.ticket, "price", o.price)}
              >
                <span className="tv-ptag-qty">{kindTitle(o.order_type).toUpperCase()}</span>
                <span className="tv-ptag-pl">{formatLots(o.volume)}</span>
                <button
                  className="tv-ptag-x"
                  title={`Take this ${kindTitle(o.order_type).toLowerCase()} back`}
                  disabled={waiting}
                  onClick={() => onCancel(o.ticket)}
                >
                  {waiting ? <span className="tv-ptag-wait" /> : <CloseIcon size={18} />}
                </button>
              </div>
            </div>
            {o.sl > 0 && level("sl", o.sl)}
            {o.tp > 0 && level("tp", o.tp)}
          </div>
        );
      })}
    </div>
  );
}
