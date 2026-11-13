// Choosing where a replay starts — TradingView's "select bar" step.
//
// Replaces the old two-step dialog (pick a date window, apply it, then pick a
// bar), which covered the very chart the bar was to be picked from. The chart
// stays fully visible here: click any bar on it and the replay begins there. Or
// jump back a day / week / month… in one click, type an exact date, or let chance
// choose. Nothing has to be "applied" first.
//
// Dates outside the visible candles are fetched on demand. The chart's current
// window is context for random starts, not a limit on a requested date.

import { useState, type ReactNode } from "react";
import { useDismiss } from "../lib/hooks";
import { TF } from "../lib/timeframes";
import { replayDate } from "../lib/replayDate";
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

  const requested = replayDate(day, clock, intraday);
  const dateValid = requested != null && newestTime != null && requested <= newestTime;
  const startOnDate = (form: HTMLFormElement) => {
    // Read the submitted fields as well as keeping React's preview state: native
    // date widgets can commit their final edit as focus leaves the field.
    const data = new FormData(form);
    const selected = replayDate(String(data.get("date") ?? ""), String(data.get("time") ?? "00:00"), intraday);
    if (selected == null || newestTime == null || selected > newestTime) return;
    setDateOpen(false);
    onStartAt(selected);
  };

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
            title={b.title}
            disabled={!ready}
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
                startOnDate(e.currentTarget);
              }}
            >
              <label>
                Date
                <input
                  type="date"
                  name="date"
                  defaultValue={day}
                  required
                  max={newestTime != null ? isoDay(newestTime) : undefined}
                  onChange={(e) => setDay(e.target.value)}
                  autoFocus
                />
              </label>
              {intraday && (
                <label>
                  Time
                  <input type="time" name="time" step={TF[timeframe].seconds < 60 ? 1 : 60} defaultValue={clock} onChange={(e) => setClock(e.target.value)} />
                </label>
              )}
              {oldestTime != null && newestTime != null && (
                <small className={day !== "" && !dateValid ? "rp-date-note warn" : "rp-date-note"}>
                  {day !== "" && !dateValid ? "Choose a past date and time." : requested != null && requested < oldestTime
                    ? "Older history will load when you start."
                    : "Choose any past date. History loads automatically."}
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
