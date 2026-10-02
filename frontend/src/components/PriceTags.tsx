// The two labels TradingView draws on the price scale beside the live price:
//
//   [ 1.12761 ]            ask, accent blue
//   [ 1.12760 ]            last price, green / red like the latest candle
//   [  06:08  ]            time left in the current bar
//
// They are DOM, not chart labels, because the chart cannot draw a second line in
// a label (the countdown) or a second price (the ask). The chart's own
// last-value label is switched off in lib/chart.ts so nothing is drawn twice.
//
// Positions are read from the chart's real price scale on every animation frame,
// so the labels stay glued to their prices while the axis is dragged, zoomed or
// autoscaled — none of which cause a React render.

import { useRef } from "react";
import type { ChartGeometry } from "../lib/chart";
import { formatCountdown } from "../lib/format";
import { useAnimationFrame, useNow } from "../lib/hooks";

/** Height of the one-line price part of a label. */
const LABEL_H = 20;

interface Props {
  geometry: ChartGeometry | null;
  digits: number;
  /** Last traded price: the bid live, the bar close in replay. */
  last: number | null;
  /** Colours the last-price label: true when the latest candle closed up. */
  up: boolean;
  ask: number | null;
  /** Server-time epoch second at which the current bar closes; null hides the countdown. */
  barClose: number | null;
  /** Seconds the broker's clock runs ahead of this machine's; needed for the countdown. */
  serverSkew: number | null;
}

export function PriceTags({ geometry, digits, last, up, ask, barClose, serverSkew }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const askRef = useRef<HTMLDivElement>(null);
  const lastRef = useRef<HTMLDivElement>(null);

  const now = useNow(1000);
  let countdown =
    barClose != null && serverSkew != null ? barClose - (now / 1000 + serverSkew) : null;
  // A bar that should have closed a while ago and has not been replaced means no
  // new ticks are arriving (market closed), so a countdown would only mislead.
  if (countdown != null && countdown < -2) countdown = null;

  useAnimationFrame(() => {
    const g = geometry;
    const root = rootRef.current;
    if (!g || !root) return;

    const paneH = g.paneHeight();
    root.style.width = `${g.scaleWidth()}px`;
    root.style.height = `${paneH}px`;

    const place = (el: HTMLDivElement | null, price: number | null, top?: number) => {
      if (!el) return null;
      const y = price == null ? null : g.priceToY(price);
      if (y == null || y < -LABEL_H || y > paneH + LABEL_H) {
        el.style.visibility = "hidden";
        return null;
      }
      const t = top ?? y - LABEL_H / 2;
      el.style.visibility = "visible";
      el.style.transform = `translateY(${Math.round(t)}px)`;
      return t;
    };

    const lastTop = place(lastRef.current, last);
    // The ask sits directly above the last-price label when the two would collide.
    const askY = ask == null ? null : g.priceToY(ask);
    let askTop = askY == null ? undefined : askY - LABEL_H / 2;
    if (askTop != null && lastTop != null && askTop + LABEL_H > lastTop) askTop = lastTop - LABEL_H;
    place(askRef.current, ask, askTop);
  }, geometry != null);

  return (
    <div className="tv-pricetags" ref={rootRef} aria-hidden="true">
      {ask != null && (
        <div className="tv-pricetag ask" ref={askRef}>
          {ask.toFixed(digits)}
        </div>
      )}
      {last != null && (
        <div className={up ? "tv-pricetag last up" : "tv-pricetag last down"} ref={lastRef}>
          <span>{last.toFixed(digits)}</span>
          {countdown != null && (
            <span className="tv-pricetag-time">{formatCountdown(Math.max(0, countdown))}</span>
          )}
        </div>
      )}
    </div>
  );
}
