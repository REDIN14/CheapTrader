// The legend row of each indicator that has a pane of its own, at the top-left of that pane.
//
// The panes are the chart's, and the user can drag their dividers, so the rows are placed from the
// chart's real layout on every animation frame (no React render is involved while a divider moves).

import { useRef } from "react";
import type { ChartGeometry } from "../lib/chart";
import { useAnimationFrame } from "../lib/hooks";
import { IndicatorRow, type LegendIndicator } from "./ChartLegend";

interface Props {
  geometry: ChartGeometry | null;
  /** The indicators with a pane of their own; `pane` counts from 1, the pane just under the candles. */
  rows: LegendIndicator[];
  onManage: () => void;
}

export function PaneLegends({ geometry, rows, onManage }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);

  useAnimationFrame(() => {
    const root = rootRef.current;
    if (!geometry || !root) return;
    const panes = geometry.subPanes();
    for (const el of Array.from(root.children) as HTMLElement[]) {
      const box = panes[Number(el.dataset.pane) - 1];
      if (!box) {
        el.style.visibility = "hidden";
        continue;
      }
      el.style.visibility = "visible";
      el.style.transform = `translateY(${Math.round(box.top + 4)}px)`;
    }
  }, geometry != null && rows.length > 0);

  if (!rows.length) return null;
  return (
    <div className="tv-panelegends" ref={rootRef}>
      {rows.map((row) => (
        <div key={row.id} className="tv-panelegend" data-pane={row.pane} style={{ visibility: "hidden" }}>
          <IndicatorRow indicator={row} onManage={onManage} />
        </div>
      ))}
    </div>
  );
}
