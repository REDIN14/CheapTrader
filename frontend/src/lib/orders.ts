// What kind of order a price makes, and which side of the market it may wait on. The same rules the
// server keeps (backend/app/trading.py), checked here first so the answer is a plain sentence and not a
// broker's "Invalid price".

import type { PendingKind } from "./types";

export type Side = "BUY" | "SELL";

/** Prices are compared to this much: float noise must not turn "exactly the minimum distance" into a refusal. */
const EPS = 1e-9;

const WORDS: Record<PendingKind, string> = {
  BUY_LIMIT: "buy limit",
  SELL_LIMIT: "sell limit",
  BUY_STOP: "buy stop",
  SELL_STOP: "sell stop",
};

/** "buy limit". */
export const kindWords = (kind: PendingKind): string => WORDS[kind];

/** "Buy limit" for a title. */
export const kindTitle = (kind: PendingKind): string => {
  const words = WORDS[kind];
  return words[0].toUpperCase() + words.slice(1);
};

export const sideOf = (kind: PendingKind): Side => (kind.startsWith("BUY") ? "BUY" : "SELL");

/**
 * The pending order a price makes for a side: a buy below the price you would pay (the ask) waits as a
 * limit order, above it as a stop order; a sell above the price you would get (the bid) is a limit, below
 * it a stop. Null exactly at the market, where there is nothing to wait for.
 */
export function pendingKind(side: Side, price: number, bid: number, ask: number): PendingKind | null {
  if (side === "BUY") return price < ask ? "BUY_LIMIT" : price > ask ? "BUY_STOP" : null;
  return price > bid ? "SELL_LIMIT" : price < bid ? "SELL_STOP" : null;
}

/** A level is too close to the price it is measured from (or on the wrong side of it). */
const tooClose = (gap: number, minDistance: number) => gap <= 0 || gap < minDistance - EPS;

const fixed = (value: number, digits: number) => value.toFixed(digits);

const away = (minDistance: number, digits: number) => (minDistance > 0 ? `, at least ${fixed(minDistance, digits)} away` : "");

/**
 * Why a pending order cannot wait at `price` while the market is `bid` / `ask`, or null. A buy limit waits
 * below the price you would buy at, a sell limit above the price you would sell at; stops are the other
 * way round; brokers keep a minimum distance (`minDistance`, in price units) from the market.
 */
export function pendingProblem(
  kind: PendingKind,
  price: number,
  bid: number,
  ask: number,
  minDistance = 0,
  digits = 5,
): string | null {
  const [gap, where, which, market] =
    kind === "BUY_LIMIT"
      ? [ask - price, "below", "buy price", ask]
      : kind === "SELL_LIMIT"
        ? [price - bid, "above", "sell price", bid]
        : kind === "BUY_STOP"
          ? [price - ask, "above", "buy price", ask]
          : [bid - price, "below", "sell price", bid];
  if (!tooClose(gap as number, minDistance)) return null;
  return (
    `A ${kindWords(kind)} has to be ${where} the current ${which} ${fixed(market as number, digits)}` +
    `${away(minDistance, digits)}; ${fixed(price, digits)} is not.`
  );
}

/**
 * Why a stop loss / take profit cannot go with an order that enters at `entry`, or null. A buy's stop is
 * below its entry and its target above; a sell's the other way round. Levels of 0 (or null) are "none".
 */
export function levelsProblem(
  side: Side,
  entry: number,
  sl: number | null | undefined,
  tp: number | null | undefined,
  minDistance = 0,
  digits = 5,
): string | null {
  const buy = side === "BUY";
  const kept = minDistance > 0 ? ` by at least ${fixed(minDistance, digits)}` : "";
  if (sl && tooClose(buy ? entry - sl : sl - entry, minDistance)) {
    return `The stop loss of a ${side.toLowerCase()} has to be ${buy ? "below" : "above"} its entry ${fixed(entry, digits)}${kept}; ${fixed(sl, digits)} is not.`;
  }
  if (tp && tooClose(buy ? tp - entry : entry - tp, minDistance)) {
    return `The take profit of a ${side.toLowerCase()} has to be ${buy ? "above" : "below"} its entry ${fixed(entry, digits)}${kept}; ${fixed(tp, digits)} is not.`;
  }
  return null;
}

/**
 * Which level a price on the chart would be for an order that waits at `entry`: on the losing side of it a
 * stop loss, on the winning side a take profit. Null exactly on the entry.
 */
export function orderLevelKindAt(side: Side, entry: number, price: number): "sl" | "tp" | null {
  if (price === entry) return null;
  return (side === "BUY") === price > entry ? "tp" : "sl";
}

/**
 * Why a market order with this stop and target would be refused now, or null. A position is closed at the
 * price the other side of the market quotes: a buy at the bid, a sell at the ask, so a buy's stop has to be
 * below the bid and its target above it, and a sell's stop above the ask and its target below it.
 */
export function marketProblem(
  side: Side,
  sl: number | null | undefined,
  tp: number | null | undefined,
  bid: number,
  ask: number,
  minDistance = 0,
  digits = 5,
): string | null {
  const buy = side === "BUY";
  const closing = buy ? bid : ask;
  const where = buy ? "the current sell price" : "the current buy price";
  const kept = minDistance > 0 ? ` by at least ${fixed(minDistance, digits)}` : "";
  if (sl && tooClose(buy ? closing - sl : sl - closing, minDistance)) {
    return `The stop loss of a ${side.toLowerCase()} has to be ${buy ? "below" : "above"} ${where} ${fixed(closing, digits)}${kept}; ${fixed(sl, digits)} is not.`;
  }
  if (tp && tooClose(buy ? tp - closing : closing - tp, minDistance)) {
    return `The take profit of a ${side.toLowerCase()} has to be ${buy ? "above" : "below"} ${where} ${fixed(closing, digits)}${kept}; ${fixed(tp, digits)} is not.`;
  }
  return null;
}
