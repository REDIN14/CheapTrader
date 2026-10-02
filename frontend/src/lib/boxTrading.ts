// What a long / short box needs to know about trading to be of use as an order, worked out in one place:
// how big its trade is, what an order from it would be, and the lines of words it shows about it.
// (Pure functions: the components only draw what is decided here.)

import { boxOrder, planOf, sizeOf, type BoxOrder, type Market, type Plan } from "./boxOrder";
import type { Drawing } from "./drawings";
import { formatMoney } from "./format";
import { formatVolume, specOf, type Size, type SizingSpec } from "./sizing";
import type { OrderRequest, OrderResult, Position, Symbol } from "./types";

/** Everything about the account and the market that an order from a drawing depends on. */
export interface BoxTrading {
  /** Orders can be sent (an instrument is open and nothing else owns the chart's clicks). */
  enabled: boolean;
  /** A replay: one price, a paper account, no pending orders. */
  paper: boolean;
  /** The instrument as the broker describes it, if known. */
  symbol: Symbol | null;
  digits: number;
  bid: number | null;
  ask: number | null;
  /** The account's balance, if known. */
  balance: number | null;
  currency: string;
  /** The open positions of this instrument. */
  positions: Position[];
  /** Send an order; resolves with what the broker answered (the price it was filled at), or null when it was refused. */
  place: (order: OrderRequest) => Promise<OrderResult | null>;
  /** Put a stop and a target on an open position. */
  setLevels: (ticket: number, sl: number, tp: number) => void;
}

/** One box with everything worked out for it. */
export interface BoxView {
  plan: Plan;
  spec: SizingSpec | null;
  size: Size | null;
  /** The order that trades at once, or null when it cannot be worked out (no size yet). */
  now: BoxOrder | null;
  /** The order that waits at the box's entry; null in a replay, which has no pending orders. */
  wait: BoxOrder | null;
}

export function marketOf(trading: BoxTrading): Market | null {
  if (trading.bid == null || trading.ask == null) return null;
  const point = trading.symbol?.point ?? 0;
  return {
    bid: trading.bid,
    ask: trading.ask,
    // a replay has no broker rules; live, the broker keeps its distance from the market
    minDistance: trading.paper ? 0 : (trading.symbol?.trade_stops_level ?? 0) * point,
    digits: trading.digits,
  };
}

export function viewOf(d: Drawing, trading: BoxTrading): BoxView | null {
  const plan = planOf(d);
  if (!plan) return null;
  const spec = trading.symbol ? specOf(trading.symbol) : null;
  const size = spec ? sizeOf(d, plan, spec, trading.balance ?? 0) : null;
  const market = marketOf(trading);
  const volume = size?.ok ? size.lots : 0;
  const hold = (how: "market" | "pending"): BoxOrder => {
    const order = boxOrder(plan, volume, how, market);
    if (!size) return { ...order, problem: order.problem ?? "The instrument's details are not known yet." };
    if (!size.ok) return { ...order, problem: size.problem ?? "The size of the trade cannot be worked out." };
    return order;
  };
  return { plan, spec, size, now: hold("market"), wait: trading.paper ? null : hold("pending") };
}

/** The lines of words a box shows under its title: how big its trade is. */
export function notesOf(view: BoxView | null, currency: string, step = 0.01): string[] {
  const size = view?.size;
  if (!size) return [];
  if (!size.ok) return size.problem && size.problem.length < 60 ? [size.problem] : [];
  const lots = `${formatVolume(size.lots, step)} lots`;
  const risk = `risk ${formatMoney(size.risk, currency)}${size.riskPercent > 0 ? ` (${size.riskPercent.toFixed(2)}%)` : ""}`;
  if (size.capped === "min") return [`${lots} (the smallest) · ${risk}`];
  if (size.capped === "max") return [`${lots} (the largest) · ${risk}`];
  return [`${lots} · ${risk}`];
}

/** The order to send for a box. */
export function orderRequest(symbol: string, order: BoxOrder, digits: number): OrderRequest {
  const round = (value: number) => Number(value.toFixed(digits));
  return {
    symbol,
    side: order.side,
    volume: order.volume,
    order_type: order.kind,
    price: order.price == null ? null : round(order.price),
    sl: round(order.sl),
    tp: round(order.tp),
  };
}
