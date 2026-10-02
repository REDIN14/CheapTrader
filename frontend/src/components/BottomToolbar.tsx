// The strip under the chart, in the place TradingView puts its range buttons.
//
//   [ 20,000 bars ▾ ]  | 2023-08-01 → 2026-10-01                         ↔  12:08:52 UTC+3
//
// * the bar count is how much history is loaded (the one history control);
// * the dates are the window actually on the chart;
// * the clock runs in the same time zone as the chart's time axis — the broker's
//   server time — so the two always agree;
// * the arrows fit every loaded bar into view (same as the F key).

import { useMemo, useState } from "react";
import { formatInt, formatUtcOffset } from "../lib/format";
import { useDismiss, useNow } from "../lib/hooks";
import { CalendarIcon, ChevronDown, FitIcon } from "./Icons";

export interface RangeInfo {
  from: number | null;
  to: number | null;
  bars: number | null;
}

interface Props {
  range: RangeInfo;
  /** History depth currently requested. */
  barCount: number;
  barSteps: number[];
  onBarCount: (count: number) => void;
  /** Replay loads its own window, so the depth cannot be changed during it. */
  depthLocked: boolean;
  /** Hours the chart's clock is ahead of UTC (broker server time); null = this machine's offset. */
  utcOffsetHours: number | null;
  onFit: () => void;
}

function fmtDate(ts: number | null): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${d.getUTCFullYear()}-${m}-${day}`;
}

export function BottomToolbar({
  range,
  barCount,
  barSteps,
  onBarCount,
  depthLocked,
  utcOffsetHours,
  onFit,
}: Props) {
  const now = useNow(1000);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismiss<HTMLDivElement>(() => setMenuOpen(false), menuOpen);

  const offset = utcOffsetHours ?? -new Date(now).getTimezoneOffset() / 60;

  const clock = useMemo(() => {
    const shifted = new Date(now + offset * 3_600_000);
    const hh = String(shifted.getUTCHours()).padStart(2, "0");
    const mm = String(shifted.getUTCMinutes()).padStart(2, "0");
    const ss = String(shifted.getUTCSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss} ${formatUtcOffset(offset)}`;
  }, [now, offset]);

  const loaded = range.bars ?? barCount;

  return (
    <div className="tv-range">
      <div className="tv-range-left">
        <div className="tv-anchor" ref={menuRef}>
          <button
            className={menuOpen ? "tv-rbtn active" : "tv-rbtn"}
            title={depthLocked ? "Replay uses the dates you picked" : "How much history to load"}
            disabled={depthLocked}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span>{formatInt(loaded)} bars</span>
            {!depthLocked && <ChevronDown size={16} />}
          </button>
          {menuOpen && (
            <div className="tv-menu up" role="menu">
              <div className="tv-menu-title">HISTORY DEPTH</div>
              {barSteps.map((n) => (
                <button
                  key={n}
                  role="menuitem"
                  className={n === barCount ? "tv-menu-item active" : "tv-menu-item"}
                  onClick={() => {
                    onBarCount(n);
                    setMenuOpen(false);
                  }}
                >
                  {formatInt(n)} bars
                </button>
              ))}
            </div>
          )}
        </div>

        <span className="tv-sep" />

        <span className="tv-range-dates" title="Window on the chart">
          <CalendarIcon size={20} />
          {fmtDate(range.from)} → {fmtDate(range.to)}
        </span>
      </div>

      <div className="tv-range-right">
        <button className="tv-rbtn icon" title="Fit chart to screen (F)" onClick={onFit}>
          <FitIcon size={22} />
        </button>
        <span className="tv-clock">{clock}</span>
      </div>
    </div>
  );
}
