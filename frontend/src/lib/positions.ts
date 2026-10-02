// Helpers for reading a position's money value at a price, and for deciding where
// its stop and target may sit.

import type { Position } from "./types";

export type Level = "sl" | "tp";

/**
 * Why a stop or target may not sit at `price`, or null when it may. A stop has to
 * lie on the losing side of the entry and a target on the winning side; the broker
 * would reject anything else as "Invalid stops", so it is caught up front with a
 * message that names the side that is needed.
 */
export function levelProblem(
  position: Position,
  level: Level,
  price: number,
  digits: number,
): string | null {
  const isBuy = position.side === "BUY";
  const wrongSide =
    level === "sl"
      ? isBuy
        ? price >= position.price_open
        : price <= position.price_open
      : isBuy
        ? price <= position.price_open
        : price >= position.price_open;
  if (!wrongSide) return null;
  const needed = level === "sl" ? (isBuy ? "below" : "above") : isBuy ? "above" : "below";
  return (
    `Invalid ${level.toUpperCase()} for this ${position.side}: it must be ${needed} the entry ` +
    `price ${position.price_open.toFixed(digits)}.`
  );
}

/**
 * Which level a price on the chart would be for this position: below a buy's entry
 * (or above a sell's) is a stop, the other side is a target. Null exactly on the entry.
 */
export function levelKindAt(position: Position, price: number): Level | null {
  if (price === position.price_open) return null;
  return (position.side === "BUY") === price > position.price_open ? "tp" : "sl";
}

/**
 * Profit or loss the position would show if the market stood at `price`, in the
 * account currency.
 *
 * The conversion factor is derived from the broker's own P/L on the position, so
 * the figure is right without knowing the quote currency or any contract
 * details. It needs the position to have moved a little (the ratio of two
 * rounded numbers is noise otherwise), so this returns null for a position that
 * is still sitting on its entry.
 */
export function pnlAt(position: Position, price: number): number | null {
  const isBuy = position.side === "BUY";
  const moved = isBuy
    ? position.price_current - position.price_open
    : position.price_open - position.price_current;
  if (Math.abs(moved) < position.price_open * 2e-5) return null;
  const perUnit = position.profit / moved;
  const diff = isBuy ? price - position.price_open : position.price_open - price;
  return diff * perUnit;
}
