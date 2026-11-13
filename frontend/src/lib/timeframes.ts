// Timeframe metadata shared by the header, legend, replay dialog and the
// bar-close countdown, so every place spells an interval the same way.

import type { Timeframe } from "./types";

export type TimeframeGroup = "SECONDS" | "MINUTES" | "HOURS" | "DAYS" | "WEEKS" | "MONTHS";

export interface TimeframeInfo {
  /** Seconds one bar covers (MN1 is a 30-day approximation). */
  seconds: number;
  /** Header button label, e.g. "15m". */
  short: string;
  /** Chart legend label: bare minutes ("15") like TradingView, otherwise "1h" / "1D". */
  legend: string;
  /** Name used in the interval menu. */
  long: string;
  group: TimeframeGroup;
}

export const TF: Record<Timeframe, TimeframeInfo> = {
  S1: { seconds: 1, short: "1s", legend: "1s", long: "1 second", group: "SECONDS" },
  S5: { seconds: 5, short: "5s", legend: "5s", long: "5 seconds", group: "SECONDS" },
  S10: { seconds: 10, short: "10s", legend: "10s", long: "10 seconds", group: "SECONDS" },
  S15: { seconds: 15, short: "15s", legend: "15s", long: "15 seconds", group: "SECONDS" },
  S30: { seconds: 30, short: "30s", legend: "30s", long: "30 seconds", group: "SECONDS" },
  M1: { seconds: 60, short: "1m", legend: "1", long: "1 minute", group: "MINUTES" },
  M5: { seconds: 300, short: "5m", legend: "5", long: "5 minutes", group: "MINUTES" },
  M15: { seconds: 900, short: "15m", legend: "15", long: "15 minutes", group: "MINUTES" },
  M30: { seconds: 1800, short: "30m", legend: "30", long: "30 minutes", group: "MINUTES" },
  H1: { seconds: 3600, short: "1h", legend: "1h", long: "1 hour", group: "HOURS" },
  H4: { seconds: 14400, short: "4h", legend: "4h", long: "4 hours", group: "HOURS" },
  D1: { seconds: 86400, short: "D", legend: "1D", long: "1 day", group: "DAYS" },
  W1: { seconds: 604800, short: "W", legend: "1W", long: "1 week", group: "WEEKS" },
  MN1: { seconds: 2592000, short: "M", legend: "1M", long: "1 month", group: "MONTHS" },
};

/** The intervals pinned in the header (TradingView's default favourites). */
export const QUICK_TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "H1", "H4", "D1"];

export const TIMEFRAME_GROUPS: TimeframeGroup[] = ["SECONDS", "MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS"];
