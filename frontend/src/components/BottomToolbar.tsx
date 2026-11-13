// The strip under the chart, in the place TradingView puts its range buttons.
//
//   [ 20,000 bars ]  | 2023-08-01 → 2026-10-01                         ↔  12:08:52 UTC+3
//
// * the bar count grows as older history is loaded while scrolling;
// * the dates are the window actually on the chart;
// * the clock runs in the same time zone as the chart's time axis — the broker's
//   server time — so the two always agree;
// * the arrows fit every loaded bar into view (same as the F key).

import { useMemo } from "react";
import { formatInt, formatUtcOffset } from "../lib/format";
import { useNow } from "../lib/hooks";
import { CalendarIcon, FitIcon } from "./Icons";

export interface RangeInfo {
  from: number | null;
  to: number | null;
  bars: number | null;
}

interface Props {
  range: RangeInfo;
  historyLoading: boolean;
  hasMoreHistory: boolean;
  onLoadOlder: () => void;
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
  historyLoading,
  hasMoreHistory,
  onLoadOlder,
  utcOffsetHours,
  onFit,
}: Props) {
  const now = useNow(1000);

  const offset = utcOffsetHours ?? -new Date(now).getTimezoneOffset() / 60;

  const clock = useMemo(() => {
    const shifted = new Date(now + offset * 3_600_000);
    const hh = String(shifted.getUTCHours()).padStart(2, "0");
    const mm = String(shifted.getUTCMinutes()).padStart(2, "0");
    const ss = String(shifted.getUTCSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss} ${formatUtcOffset(offset)}`;
  }, [now, offset]);

  const loaded = range.bars ?? 0;

  return (
    <div className="tv-range">
      <div className="tv-range-left">
        <button className="tv-rbtn" onClick={onLoadOlder} disabled={historyLoading || !hasMoreHistory}
          title="Load older candles — also loaded automatically as you scroll left" aria-live="polite">
          {formatInt(loaded)} bars{historyLoading ? " · Loading older…" : !hasMoreHistory ? " · Start of available history" : ""}
        </button>

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
