// How many lots to trade so that a stop costs a chosen amount: position sizing.
//
// What a lot loses when the price moves a given distance comes from the instrument: one price step
// ("tick") of one lot is worth `tickValue` in the account's currency, and a step is `tickSize` of price.
// The broker gives both; the paper account of a replay pays in the plain way (price distance x contract
// size), so it has its own reading of the same figures.

import type { Symbol } from "./types";

export interface SizingSpec {
  /** Price distance of one step. */
  tickSize: number;
  /** Money one step of one lot is worth, in the account's currency. */
  tickValue: number;
  /** Smallest, largest and step of an order's volume, in lots. */
  min: number;
  max: number;
  step: number;
}

/**
 * The sizing figures of an instrument. In a replay (`paper`) the account is plain arithmetic: a distance
 * of `d` costs `d x contract size` per lot, whatever the broker says a tick is worth.
 */
export function specOf(symbol: Pick<Symbol, "point" | "trade_contract_size" | "trade_tick_size" | "trade_tick_value" | "volume_min" | "volume_max" | "volume_step">, paper = false): SizingSpec {
  const tickSize = symbol.trade_tick_size > 0 ? symbol.trade_tick_size : symbol.point;
  const live = symbol.trade_tick_value > 0 && symbol.trade_tick_size > 0 && !paper;
  return {
    tickSize,
    tickValue: live ? symbol.trade_tick_value : tickSize * symbol.trade_contract_size,
    min: symbol.volume_min > 0 ? symbol.volume_min : 0.01,
    max: symbol.volume_max > 0 ? symbol.volume_max : 100,
    step: symbol.volume_step > 0 ? symbol.volume_step : 0.01,
  };
}

/** Money one lot loses (or makes) when the price moves `distance`. */
export function moneyPerLot(spec: SizingSpec, distance: number): number {
  return spec.tickSize > 0 ? (Math.abs(distance) / spec.tickSize) * spec.tickValue : 0;
}

/** Decimal places a step is written with: 0.01 -> 2, 0.5 -> 1, 1 -> 0. */
const decimals = (step: number) => {
  const text = String(step);
  return text.includes(".") ? text.length - text.indexOf(".") - 1 : 0;
};

/** A volume written the way its instrument is traded in: two decimals at least (0.50), more for a finer step. */
export function formatVolume(lots: number, step = 0.01): string {
  return lots.toFixed(Math.max(2, decimals(step)));
}

/** `lots` rounded to the instrument's volume step, down or to the nearest, and no further than its limits. */
export function roundLots(lots: number, spec: SizingSpec, mode: "down" | "nearest" = "down"): number {
  if (!(lots > 0)) return 0;
  const steps = lots / spec.step;
  const whole = mode === "down" ? Math.floor(steps + 1e-9) : Math.round(steps);
  const rounded = Number((whole * spec.step).toFixed(decimals(spec.step)));
  return Math.min(spec.max, Math.max(spec.min, rounded));
}

export type RiskMode = "percent" | "amount" | "lots";

export interface SizeInput {
  mode: RiskMode;
  /** Share of the balance to risk (mode "percent"). */
  percent: number;
  /** Money to risk (mode "amount"). */
  amount: number;
  /** Lots to trade (mode "lots"). */
  lots: number;
  /** The account's balance. */
  balance: number;
  /** Price distance from the entry to the stop. */
  distance: number;
}

export interface Size {
  /** The volume to trade. 0 when it cannot be worked out. */
  lots: number;
  /** What the stop costs at that volume, in the account's currency. */
  risk: number;
  /** That, as a share of the balance (0 when the balance is not known). */
  riskPercent: number;
  /** What was asked to be risked, before the volume was rounded to what the broker accepts. */
  wanted: number;
  /** The volume had to be raised to the smallest the broker takes ("min") or cut to the largest ("max"). */
  capped: "min" | "max" | null;
  ok: boolean;
  /** Why it cannot be worked out. */
  problem?: string;
}

export const DEFAULTS = { percent: 1, amount: 100, lots: 0.1 } as const;

/** The volume that makes a stop at `distance` cost what was asked (or the volume asked for, and what it costs). */
export function sizePosition(spec: SizingSpec, input: SizeInput): Size {
  const perLot = moneyPerLot(spec, input.distance);
  const none = (problem: string): Size => ({ lots: 0, risk: 0, riskPercent: 0, wanted: 0, capped: null, ok: false, problem });
  if (!(perLot > 0)) return none("The stop is on the entry, so there is no distance to size by.");

  const percentOf = (money: number) => (input.balance > 0 ? (money / input.balance) * 100 : 0);

  if (input.mode === "lots") {
    const lots = roundLots(input.lots, spec, "nearest");
    if (!(lots > 0)) return none("Enter a number of lots above zero.");
    const risk = perLot * lots;
    return { lots, risk, riskPercent: percentOf(risk), wanted: risk, capped: null, ok: true };
  }

  const wanted = input.mode === "amount" ? input.amount : (input.balance * input.percent) / 100;
  if (!(wanted > 0)) {
    return none(input.mode === "amount" ? "Enter an amount to risk above zero." : input.balance > 0 ? "Enter a share to risk above zero." : "The balance is not known yet.");
  }
  const raw = wanted / perLot;
  let lots = roundLots(raw, spec, "down");
  let capped: Size["capped"] = null;
  if (raw < spec.min) capped = "min"; // even the smallest volume risks more than was asked
  if (raw > spec.max) capped = "max";
  if (!(lots > 0)) lots = spec.min;
  const risk = perLot * lots;
  return { lots, risk, riskPercent: percentOf(risk), wanted, capped, ok: true };
}
