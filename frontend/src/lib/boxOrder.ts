// What a long / short box can do as an order: buy or sell now with its stop and target, or have an order
// wait at its entry. Pure functions of the drawing and the market, so the rules can be tested alone.

import type { Drawing } from "./drawings";
import { levelsProblem, marketProblem, pendingKind, pendingProblem, type Side } from "./orders";
import { DEFAULTS, sizePosition, type Size, type SizingSpec } from "./sizing";
import type { PendingKind } from "./types";

/** The three prices of a box. */
export interface Plan {
  side: Side;
  entry: number;
  stop: number;
  target: number;
  /** Price distance from the entry to the stop: what a lot risks per unit of price. */
  distance: number;
  /** Reward over risk. */
  ratio: number;
}

export function planOf(d: Drawing): Plan | null {
  if (d.type !== "long" && d.type !== "short") return null;
  const [entry, target, stop] = d.points;
  if (!entry || !target || !stop) return null;
  const distance = Math.abs(entry.price - stop.price);
  const reward = Math.abs(target.price - entry.price);
  return {
    side: d.type === "long" ? "BUY" : "SELL",
    entry: entry.price,
    stop: stop.price,
    target: target.price,
    distance,
    ratio: distance > 0 ? reward / distance : 0,
  };
}

/**
 * The box once its trade is open: the entry line moves to where the trade really opened (the price it was
 * filled at) and, as long as that is before the end of the box, to the candle it opened in. The stop and the
 * target stay where they are. Null when that would not leave a box (the fill is not between the stop and the
 * target), or for a drawing that is no box.
 */
export function enterAt(d: Drawing, price: number, time: number | null): Drawing | null {
  const plan = planOf(d);
  if (!plan || !(price > 0)) return null;
  const between = plan.side === "BUY" ? plan.stop < price && price < plan.target : plan.target < price && price < plan.stop;
  if (!between) return null;
  const [entry, target, stop] = d.points;
  const opened = time != null && time < target.time ? time : entry.time;
  return { ...d, points: [{ time: opened, price }, target, stop] };
}

/** How the box says its trade is sized (or the defaults), turned into the figures `sizePosition` takes. */
export function sizeOf(d: Drawing, plan: Plan, spec: SizingSpec, balance: number): Size {
  const style = d.style;
  return sizePosition(spec, {
    mode: style.risk_mode ?? "percent",
    percent: style.risk_percent ?? DEFAULTS.percent,
    amount: style.risk_amount ?? DEFAULTS.amount,
    lots: style.lots ?? DEFAULTS.lots,
    balance,
    distance: plan.distance,
  });
}

/** The market a box order meets. */
export interface Market {
  bid: number;
  ask: number;
  /** The broker's minimum distance from the market, in price units. */
  minDistance: number;
  digits: number;
}

export interface BoxOrder {
  /** Now, or waiting at the box's entry. */
  how: "market" | "pending";
  side: Side;
  /** The kind of pending order the entry makes (null for a market order). */
  kind: PendingKind | null;
  volume: number;
  /** The price a pending order waits for. */
  price: number | null;
  sl: number;
  tp: number;
  /** Why the order cannot be placed, or null. */
  problem: string | null;
}

/** An order from a box. `market` may be null (no price yet), which makes the order a problem. */
export function boxOrder(plan: Plan, volume: number, how: "market" | "pending", market: Market | null): BoxOrder {
  const order: BoxOrder = {
    how,
    side: plan.side,
    kind: null,
    volume,
    price: how === "pending" ? plan.entry : null,
    sl: plan.stop,
    tp: plan.target,
    problem: null,
  };
  if (!market) return { ...order, problem: "There is no price yet." };
  const { bid, ask, minDistance, digits } = market;

  // A box whose stop or target has been dragged to the wrong side of its entry is not a trade at all.
  const shape = levelsProblem(plan.side, plan.entry, plan.stop, plan.target, 0, digits);
  if (shape) return { ...order, problem: shape.replace("its entry", "the entry of the box") };

  if (how === "market") {
    return { ...order, problem: marketProblem(plan.side, plan.stop, plan.target, bid, ask, minDistance, digits) };
  }
  const kind = pendingKind(plan.side, plan.entry, bid, ask);
  if (!kind) {
    return { ...order, problem: "The entry is at the market price: place the order now instead of waiting." };
  }
  return {
    ...order,
    kind,
    problem:
      pendingProblem(kind, plan.entry, bid, ask, minDistance, digits) ??
      levelsProblem(plan.side, plan.entry, plan.stop, plan.target, minDistance, digits),
  };
}
