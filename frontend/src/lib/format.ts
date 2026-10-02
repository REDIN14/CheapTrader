// Number and time formatting shared by the chart overlays and panels.

/**
 * Split a price so its last digit can be drawn as a small raised "pipette", the
 * way TradingView prints fractional-pip quotes (1.1275⁹). Only 3- and 5-digit
 * symbols have one; everything else is returned whole.
 */
export function splitPipette(price: number, digits: number): { main: string; pip: string } {
  const text = price.toFixed(digits);
  if (digits === 3 || digits === 5) return { main: text.slice(0, -1), pip: text.slice(-1) };
  return { main: text, pip: "" };
}

/** One pip in price units: 10 points on 3/5-digit symbols, one point otherwise. */
export function pipSize(digits: number, point: number): number {
  return digits === 3 || digits === 5 ? point * 10 : point;
}

/** Spread in pips (what TradingView shows between the Sell and Buy buttons). */
export function spreadInPips(bid: number, ask: number, digits: number, point: number): number {
  const pip = pipSize(digits, point);
  return pip > 0 ? Math.max(0, (ask - bid) / pip) : 0;
}

/** "02:07" under an hour, "01:02:07" up to a day, "3d 04h" beyond that. */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86_400);
  const hours = Math.floor((s % 86_400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (days > 0) return `${days}d ${pad(hours)}h`;
  if (hours > 0) return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  return `${pad(minutes)}:${pad(seconds)}`;
}

const MINUS = "−";

/** "+12.34 USD" / "−0.02 USD" — a true minus sign, like TradingView's tags. */
export function formatMoney(value: number, currency = "", signed = false): string {
  const rounded = Math.round(value * 100) / 100;
  const sign = rounded < 0 ? MINUS : signed && rounded > 0 ? "+" : "";
  const body = Math.abs(rounded).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${sign}${body} ${currency}` : `${sign}${body}`;
}

/** A signed price/percent change using the true minus sign. */
export function formatSigned(value: number, digits: number): string {
  const sign = value < 0 ? MINUS : value > 0 ? "+" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

/** "UTC+3", "UTC-5", "UTC+5.5" */
export function formatUtcOffset(hours: number): string {
  const sign = hours < 0 ? "-" : "+";
  const abs = Math.abs(hours);
  return `UTC${sign}${Number.isInteger(abs) ? abs : abs.toFixed(1)}`;
}

/** A whole number with thousands separators, the same way in every locale: 20000 -> "20,000". */
export function formatInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** Lot size without trailing noise: 0.1 -> "0.10", 1 -> "1.00". */
export function formatLots(volume: number): string {
  return volume.toFixed(2);
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const two = (n: number) => String(n).padStart(2, "0");

/**
 * A moment on the chart's own clock: "Mon 14 Sep 2026 · 21:15". Bar times are the
 * broker's server time carried as if it were UTC, so the UTC fields are the ones
 * the time axis shows.
 */
export function formatChartTime(ts: number, withTime = true): string {
  const d = new Date(ts * 1000);
  const day = `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  return withTime ? `${day} · ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}` : day;
}

/** The short form for tables: "14 Sep 21:15" (and "14 Sep 2026" for daily bars). */
export function formatShortTime(ts: number, withTime = true): string {
  const d = new Date(ts * 1000);
  const day = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  return withTime ? `${day} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}` : `${day} ${d.getUTCFullYear()}`;
}

/** "45s", "12m", "2h 15m", "3d 4h": the two largest units that are not zero. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const days = Math.floor(s / 86_400);
  const hours = Math.floor((s % 86_400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  return `${minutes}m`;
}
