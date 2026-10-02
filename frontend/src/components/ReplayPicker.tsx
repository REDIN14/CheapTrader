// Choosing where a replay starts — TradingView's "select bar" step.
//
// Replaces the old two-step dialog (pick a date window, apply it, then pick a
// bar), which covered the very chart the bar was to be picked from. The chart
// stays fully visible here: click any bar on it and the replay begins there. Or
// jump back a day / week / month… in one click, type an exact date, or let chance
// choose. Nothing has to be "applied" first.
//
// A replay can start anywhere in the history the chart has loaded (the bar count
// at the bottom left says how far back that is): those bars are already stored, so
// starting never turns into a long download from the broker. Starts older than
// that are switched off here and say why.

import { useState, type ReactNode } from "react";
import { useDismiss } from "../lib/hooks";
import { TF } from "../lib/timeframes";
import type { Timeframe } from "../lib/types";
import { CalendarIcon, CloseIcon, DiceIcon, ReplayIcon, ScissorsIcon } from "./Icons";

interface Props {
  symbol: string;
  timeframe: Timeframe;
  /** Newest / oldest bar of the live chart: what "a week ago" and "random" are measured against. */
  newestTime: number | null;
  oldestTime: number | null;
  /** The backend is loading the window for the bar just chosen. */
  starting: boolean;
  /** Which paper-trading profile the replay will trade on (the profile menu). */
  profileMenu?: ReactNode;
  onStartAt: (time: number) => void;
  onCancel: () => void;
}

const DAY = 86_400;

const BACK: { label: string; title: string; seconds: number }[] = [
  { label: "1D", title: "Start a day back", seconds: DAY },
  { label: "1W", title: "Start a week back", seconds: 7 * DAY },
  { label: "1M", title: "Start a month back", seconds: 30 * DAY },
  { label: "3M", title: "Start three months back", seconds: 90 * DAY },
  { label: "1Y", title: "Start a year back", seconds: 365 * DAY },
];

/** "2026-09-14" for the date input, from a chart time (server time carried as UTC). */
const isoDay = (ts: number) => new Date(ts * 1000).toISOString().slice(0, 10);

const TOO_OLD = "Older than the history loaded on the chart — raise the bar count at the bottom left";

export function ReplayPicker({ symbol, timeframe, newestTime, oldestTime, starting, profileMenu, onStartAt, onCancel }: Props) {
  const [dateOpen, setDateOpen] = useState(false);
  const popRef = useDismiss<HTMLDivElement>(() => setDateOpen(false), dateOpen);
  const [day, setDay] = useState("");
  const [clock, setClock] = useState("00:00");

  const ready = newestTime != null && !starting;
  const intraday = TF[timeframe].seconds < DAY;

  const openDate = () => {
    if (!dateOpen && !day && newestTime != null) setDay(isoDay(newestTime - 7 * DAY));
    setDateOpen((v) => !v);
  };

  const dateValid =
    day !== "" &&
    newestTime != null &&
    oldestTime != null &&
    day <= isoDay(newestTime) &&
    day >= isoDay(oldestTime);
  const startOnDate = () => {
    if (!dateValid) return;
    const [h, m] = (intraday ? clock : "00:00").split(":").map(Number);
    const [y, mo, d] = day.split("-").map(Number);
    setDateOpen(false);
    onStartAt(Date.UTC(y, mo - 1, d, h || 0, m || 0) / 1000);
  };

  /** Whether a start this far back still lies inside the loaded history. */
  const reachable = (seconds: number) =>
    newestTime != null && oldestTime != null && newestTime - seconds >= oldestTime;

  const random = () => {
    if (newestTime == null || oldestTime == null || newestTime <= oldestTime) return;
    // Anywhere but the very beginning and the last stretch, so there is context to
    // look at before and something to play after.
    const span = newestTime - oldestTime;
    onStartAt(oldestTime + span * (0.05 + Math.random() * 0.85));
  };

  return (
    <div className={starting ? "rp-picker busy" : "rp-picker"} role="toolbar" aria-label="Start a replay">
      <span className="rp-title">
        <ReplayIcon size={22} />
        <b>Replay</b>
        <span className="rp-title-sub">
          {symbol} · {TF[timeframe].short}
        </span>
      </span>

      <span className="rp-sep rp-sep-hint" />

      <span className="rp-hint">
        <ScissorsIcon size={18} />
        {starting ? "Loading the replay…" : "Click a bar on the chart to start there"}
      </span>

      <span className="rp-sep rp-sep-hint" />

      <span className="rp-group" role="group" aria-label="Start further back">
        {BACK.map((b) => (
          <button
            key={b.label}
            className="rp-chip"
            title={reachable(b.seconds) ? b.title : TOO_OLD}
            disabled={!ready || !reachable(b.seconds)}
            onClick={() => newestTime != null && onStartAt(newestTime - b.seconds)}
          >
            {b.label}
          </button>
        ))}
        <span className="rp-anchor" ref={popRef}>
          <button className={dateOpen ? "rp-chip wide active" : "rp-chip wide"} title="Start on an exact date" disabled={!ready} onClick={openDate}>
            <CalendarIcon size={16} />
            Date
          </button>
          {dateOpen && (
            <form
              className="rp-date"
              onSubmit={(e) => {
                e.preventDefault();
                startOnDate();
              }}
            >
              <label>
                Date
                <input
                  type="date"
                  value={day}
                  min={oldestTime != null ? isoDay(oldestTime) : undefined}
                  max={newestTime != null ? isoDay(newestTime) : undefined}
                  onChange={(e) => setDay(e.target.value)}
                  autoFocus
                />
              </label>
              {intraday && (
                <label>
                  Time
                  <input type="time" value={clock} onChange={(e) => setClock(e.target.value)} />
                </label>
              )}
              {oldestTime != null && newestTime != null && (
                <small className={day !== "" && !dateValid ? "rp-date-note warn" : "rp-date-note"}>
                  History loaded: {isoDay(oldestTime)} → {isoDay(newestTime)}
                </small>
              )}
              <button type="submit" className="rp-go" disabled={!dateValid}>
                Start
              </button>
            </form>
          )}
        </span>
      </span>

      <span className="rp-sep" />

      <button className="rp-chip wide" title="Start on a random bar" disabled={!ready || oldestTime == null} onClick={random}>
        <DiceIcon size={16} />
        Random
      </button>

      {profileMenu && (
        <>
          <span className="rp-sep" />
          {profileMenu}
        </>
      )}

      <span className="rp-sep" />

      <button className="rp-icon" title="Cancel (Esc)" onClick={onCancel}>
        <CloseIcon size={20} />
      </button>
    </div>
  );
}
