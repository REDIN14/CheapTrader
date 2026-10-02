// Paper-trading profiles: the small amount of logic behind the profile menu — names, the balance
// somebody types, and how a profile is described. Kept apart from the component so it can be tested.

import type { ReplayProfile } from "./types";

export const NAME_MAX = 40;
export const BALANCE_MIN = 1;
export const BALANCE_MAX = 1_000_000_000;
export const DEFAULT_BALANCE = 10_000;
const BASE_NAME = "Paper account";

/** "Paper account", then "Paper account 2", "Paper account 3"…: the first name nobody has taken. */
export function nextProfileName(taken: string[]): string {
  const used = new Set(taken.map((name) => name.trim().toLowerCase()));
  if (!used.has(BASE_NAME.toLowerCase())) return BASE_NAME;
  for (let n = 2; ; n++) {
    const name = `${BASE_NAME} ${n}`;
    if (!used.has(name.toLowerCase())) return name;
  }
}

/** A name as it is kept: spaces at the ends dropped, runs of spaces made one. */
export const tidyName = (name: string): string => name.trim().replace(/\s+/g, " ");

/** Why `name` cannot be a profile's name, or null when it can. `own` is the profile being renamed. */
export function nameProblem(name: string, profiles: ReplayProfile[], own?: string): string | null {
  const tidy = tidyName(name);
  if (!tidy) return "Give the profile a name.";
  if (tidy.length > NAME_MAX) return `A name can have up to ${NAME_MAX} characters.`;
  const clash = profiles.find((p) => p.id !== own && p.name.trim().toLowerCase() === tidy.toLowerCase());
  return clash ? `There already is a profile called “${clash.name}”.` : null;
}

/**
 * What was typed in a balance box, as a number, or null when it is not one. People write
 * 10000, 10 000, 10,000, 10'000, 10,000.50 and 10.000,50: the last separator is the decimal
 * one when both kinds appear, a lone comma is a decimal comma only with one or two digits after
 * it, and "10.000" (a dot and exactly three digits after a short whole part) is ten thousand,
 * because a balance is never written with three decimals.
 */
export function parseBalance(text: string): number | null {
  const s = text.replace(/[\s'’\u00a0]/g, "");
  if (!s || !/^[\d.,]+$/.test(s)) return null;

  /** "1", "234", "567": a whole part of up to three digits, then groups of exactly three. */
  const grouped = (parts: string[]) =>
    parts.length > 1 && parts[0].length >= 1 && parts[0].length <= 3 && parts.slice(1).every((p) => p.length === 3);

  let whole = s;
  let fraction = "";
  const hasDot = s.includes(".");
  const hasComma = s.includes(",");
  if (hasDot && hasComma) {
    // both kinds: the last one is the decimal separator, the other groups thousands
    const at = Math.max(s.lastIndexOf("."), s.lastIndexOf(","));
    const decimal = s[at];
    const thousands = decimal === "." ? "," : ".";
    whole = s.slice(0, at);
    fraction = s.slice(at + 1);
    if (whole.includes(decimal) || fraction.includes(thousands) || !grouped(whole.split(thousands))) return null;
    whole = whole.split(thousands).join("");
  } else if (hasDot || hasComma) {
    const sep = hasDot ? "." : ",";
    const parts = s.split(sep);
    const decimal =
      parts.length === 2 &&
      (sep === "."
        ? !(parts[1].length === 3 && parts[0].length >= 1 && parts[0].length <= 3) // "10.000" groups thousands
        : parts[1].length >= 1 && parts[1].length <= 2); // "10,000" groups, "10,5" is a decimal comma
    if (decimal) [whole, fraction] = parts;
    else if (grouped(parts)) whole = parts.join("");
    else return null;
  }
  if (!/^\d+$/.test(whole) || (fraction !== "" && !/^\d+$/.test(fraction))) return null;
  const value = Number(fraction ? `${whole}.${fraction}` : whole);
  return Number.isFinite(value) ? value : null;
}

/** Why the typed balance cannot be used, or null when it can. */
export function balanceProblem(text: string): string | null {
  const value = parseBalance(text);
  if (value === null) return "Type the starting balance as a number, e.g. 10000.";
  if (value < BALANCE_MIN) return `The starting balance has to be at least ${BALANCE_MIN}.`;
  if (value > BALANCE_MAX) return "That is more than the balance can be (1,000,000,000).";
  return null;
}

/** "+2.50 %", "−1.20 %", "0.00 %". */
export function returnLabel(pct: number): string {
  const sign = pct > 0.005 ? "+" : pct < -0.005 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(2)} %`;
}

/** "14 trades · 8 won, 6 lost", "no trades yet". */
export function historyLabel(p: Pick<ReplayProfile, "trades" | "wins" | "losses" | "open_positions">): string {
  const parts: string[] = [];
  if (p.trades === 0) parts.push("no trades yet");
  else parts.push(`${p.trades} ${p.trades === 1 ? "trade" : "trades"} · ${p.wins} won, ${p.losses} lost`);
  if (p.open_positions > 0) parts.push(`${p.open_positions} open`);
  return parts.join(" · ");
}
