import assert from "node:assert/strict";
import { test } from "node:test";
import { boxOrder, planOf, sizeOf, type Market } from "../src/lib/boxOrder";
import { kindTitle, kindWords, levelsProblem, marketProblem, pendingKind, pendingProblem, sideOf } from "../src/lib/orders";
import { DEFAULTS, moneyPerLot, roundLots, sizePosition, specOf, type SizingSpec } from "../src/lib/sizing";
import type { Drawing } from "../src/lib/drawings";

const near = (a: number, b: number, tolerance = 1e-9) => Math.abs(a - b) <= tolerance;

// -- which order a price makes -----------------------------------------------------------------------------------
test("a price makes a limit or a stop order depending on which side of the market it is", () => {
  const bid = 1.1;
  const ask = 1.1002;
  assert.equal(pendingKind("BUY", 1.0990, bid, ask), "BUY_LIMIT");
  assert.equal(pendingKind("BUY", 1.1010, bid, ask), "BUY_STOP");
  assert.equal(pendingKind("BUY", ask, bid, ask), null, "at the market there is nothing to wait for");
  assert.equal(pendingKind("SELL", 1.1010, bid, ask), "SELL_LIMIT");
  assert.equal(pendingKind("SELL", 1.0990, bid, ask), "SELL_STOP");
  assert.equal(pendingKind("SELL", bid, bid, ask), null);
});

test("the kinds in words", () => {
  assert.equal(kindWords("SELL_STOP"), "sell stop");
  assert.equal(kindTitle("BUY_LIMIT"), "Buy limit");
  assert.equal(sideOf("SELL_LIMIT"), "SELL");
  assert.equal(sideOf("BUY_STOP"), "BUY");
});

test("the rules for a pending order are the server's", () => {
  const bid = 1.1;
  const ask = 1.1002;
  const fine = (kind: Parameters<typeof pendingProblem>[0], price: number) => pendingProblem(kind, price, bid, ask, 0, 4) === null;
  assert.ok(fine("BUY_LIMIT", 1.099) && !fine("BUY_LIMIT", 1.1002) && !fine("BUY_LIMIT", 1.101));
  assert.ok(fine("SELL_LIMIT", 1.101) && !fine("SELL_LIMIT", 1.1) && !fine("SELL_LIMIT", 1.099));
  assert.ok(fine("BUY_STOP", 1.101) && !fine("BUY_STOP", 1.1002) && !fine("BUY_STOP", 1.099));
  assert.ok(fine("SELL_STOP", 1.099) && !fine("SELL_STOP", 1.1) && !fine("SELL_STOP", 1.101));
  assert.equal(
    pendingProblem("BUY_LIMIT", 1.101, bid, ask, 0, 4),
    "A buy limit has to be below the current buy price 1.1002; 1.1010 is not.",
  );
});

test("a broker's minimum distance is kept, exactly at it is fine", () => {
  const msg = pendingProblem("BUY_LIMIT", 1.0999, 1.1, 1.1002, 0.001, 4);
  assert.ok(msg && msg.includes("at least 0.0010 away"), msg ?? "");
  assert.equal(pendingProblem("BUY_LIMIT", 1.0992, 1.1, 1.1002, 0.001, 4), null, "exactly the distance");
  assert.equal(pendingProblem("BUY_LIMIT", 1.0990, 1.1, 1.1002, 0.001, 4), null);
});

test("a stop and a target belong on their own sides of an entry", () => {
  assert.equal(levelsProblem("BUY", 1.1, 1.09, 1.12), null);
  assert.match(levelsProblem("BUY", 1.1, 1.11, null, 0, 2)!, /stop loss of a buy has to be below its entry 1\.10/);
  assert.match(levelsProblem("BUY", 1.1, null, 1.09, 0, 2)!, /take profit of a buy has to be above/);
  assert.equal(levelsProblem("SELL", 1.1, 1.11, 1.09), null);
  assert.match(levelsProblem("SELL", 1.1, 1.09, null, 0, 2)!, /stop loss of a sell has to be above/);
  assert.match(levelsProblem("SELL", 1.1, null, 1.11, 0, 2)!, /take profit of a sell has to be below/);
  assert.equal(levelsProblem("BUY", 1.1, 0, 0), null, "0 means none");
  assert.ok(levelsProblem("BUY", 1.1, 1.1, null), "a stop on the entry is no stop");
});

test("a market order's stop is checked against the price it would be closed at", () => {
  // a buy is closed at the bid; a sell at the ask
  assert.equal(marketProblem("BUY", 1.09, 1.12, 1.1, 1.1002), null);
  assert.match(marketProblem("BUY", 1.1001, null, 1.1, 1.1002, 0, 4)!, /stop loss of a buy has to be below the current sell price 1\.1000/);
  assert.match(marketProblem("BUY", null, 1.0999, 1.1, 1.1002, 0, 4)!, /take profit of a buy has to be above the current sell price/);
  assert.equal(marketProblem("SELL", 1.12, 1.09, 1.1, 1.1002), null);
  assert.match(marketProblem("SELL", 1.1001, null, 1.1, 1.1002, 0, 4)!, /stop loss of a sell has to be above the current buy price 1\.1002/);
  assert.match(marketProblem("SELL", null, 1.1005, 1.1, 1.1002, 0, 4)!, /take profit of a sell has to be below the current buy price/);
});

// -- sizing ---------------------------------------------------------------------------------------------------------
const eurusd: SizingSpec = { tickSize: 0.00001, tickValue: 1, min: 0.01, max: 100, step: 0.01 };

test("a lot loses (tick value) per step of price", () => {
  assert.equal(moneyPerLot(eurusd, 0.002), 200); // 20 pips of one lot
  assert.equal(moneyPerLot(eurusd, -0.002), 200, "the direction does not matter");
  // USDJPY: a step of 0.001 is worth 0.65 USD
  assert.ok(Math.abs(moneyPerLot({ ...eurusd, tickSize: 0.001, tickValue: 0.65 }, 0.2) - 130) < 1e-9);
});

test("the volume that makes the stop cost 1% of the balance", () => {
  const size = sizePosition(eurusd, { mode: "percent", percent: 1, amount: 0, lots: 0, balance: 10_000, distance: 0.002 });
  assert.equal(size.ok, true);
  assert.equal(size.lots, 0.5);
  assert.ok(near(size.risk, 100) && near(size.riskPercent, 1));
  assert.equal(size.capped, null);
});

test("the volume is rounded down to what the broker accepts, so the risk is never more than asked", () => {
  const size = sizePosition(eurusd, { mode: "percent", percent: 1, amount: 0, lots: 0, balance: 10_000, distance: 0.00333 });
  assert.equal(size.lots, 0.3); // 100 / 333 = 0.3003...
  assert.ok(size.risk <= 100 && size.risk > 99);
  assert.equal(sizePosition(eurusd, { mode: "amount", percent: 0, amount: 50, lots: 0, balance: 10_000, distance: 0.0025 }).lots, 0.2);
});

test("a number of lots is taken as it is, and the risk is worked out from it", () => {
  const size = sizePosition(eurusd, { mode: "lots", percent: 0, amount: 0, lots: 0.35, balance: 5_000, distance: 0.002 });
  assert.equal(size.lots, 0.35);
  assert.ok(near(size.risk, 70) && near(size.riskPercent, 1.4));
  assert.equal(sizePosition(eurusd, { mode: "lots", percent: 0, amount: 0, lots: 0.004, balance: 5_000, distance: 0.002 }).lots, 0.01, "no less than the smallest");
  assert.equal(sizePosition(eurusd, { mode: "lots", percent: 0, amount: 0, lots: 0, balance: 5_000, distance: 0.002 }).ok, false);
});

test("an account too small for the smallest volume says the risk is more than asked", () => {
  const size = sizePosition(eurusd, { mode: "percent", percent: 1, amount: 0, lots: 0, balance: 100, distance: 0.005 });
  assert.equal(size.lots, 0.01);
  assert.equal(size.capped, "min");
  assert.equal(size.wanted, 1);
  assert.ok(near(size.risk, 5), "the smallest volume risks 5, not the 1 that was asked");
});

test("a volume beyond the broker's largest is cut", () => {
  const size = sizePosition({ ...eurusd, max: 5 }, { mode: "percent", percent: 10, amount: 0, lots: 0, balance: 1_000_000, distance: 0.001 });
  assert.equal(size.lots, 5);
  assert.equal(size.capped, "max");
});

test("with no distance there is nothing to size by", () => {
  const size = sizePosition(eurusd, { mode: "percent", percent: 1, amount: 0, lots: 0, balance: 10_000, distance: 0 });
  assert.equal(size.ok, false);
  assert.ok(size.problem);
  assert.equal(sizePosition(eurusd, { mode: "percent", percent: 1, amount: 0, lots: 0, balance: 0, distance: 0.002 }).ok, false, "no balance, no share of it");
});

test("lots are rounded to the step the instrument is traded in", () => {
  assert.equal(roundLots(0.3003, eurusd), 0.3);
  assert.equal(roundLots(0.29999999999, eurusd), 0.3, "float noise is not a lost step");
  assert.equal(roundLots(0.349, eurusd, "nearest"), 0.35);
  assert.equal(roundLots(2.7, { ...eurusd, step: 0.5, min: 0.5 }), 2.5);
  assert.equal(roundLots(7.9, { ...eurusd, step: 1, min: 1 }), 7);
  assert.equal(roundLots(0.0001, eurusd), 0.01, "at least the smallest");
  assert.equal(roundLots(500, eurusd), 100, "at most the largest");
  assert.equal(roundLots(0, eurusd), 0);
});

const symbol = {
  point: 0.00001,
  trade_contract_size: 100_000,
  trade_tick_size: 0.00001,
  trade_tick_value: 0.92,
  volume_min: 0.01,
  volume_max: 50,
  volume_step: 0.01,
};

test("the broker's tick value is used live, and plain arithmetic in a replay", () => {
  const live = specOf(symbol);
  assert.equal(live.tickValue, 0.92);
  assert.equal(live.max, 50);
  const paper = specOf(symbol, true);
  assert.ok(Math.abs(paper.tickValue - 1) < 1e-9, "100,000 x 0.00001: what the paper account pays");
});

test("an instrument the broker has told nothing about falls back to its point and contract size", () => {
  const bare = specOf({ ...symbol, trade_tick_size: 0, trade_tick_value: 0, volume_min: 0, volume_max: 0, volume_step: 0 });
  assert.ok(Math.abs(bare.tickValue - 1) < 1e-9 && bare.tickSize === 0.00001);
  assert.deepEqual([bare.min, bare.max, bare.step], [0.01, 100, 0.01]);
});

// -- a box as an order ----------------------------------------------------------------------------------------------
const box = (type: "long" | "short", entry: number, target: number, stop: number, style: Drawing["style"] = {}): Drawing => ({
  id: "b",
  type,
  points: [{ time: 100, price: entry }, { time: 200, price: target }, { time: 200, price: stop }],
  style,
});
// the box in the screenshot that started this: a sell at 0.98900, stop 0.99167, target 0.98507
const short = box("short", 0.989, 0.98507, 0.99167);
const market: Market = { bid: 0.9885, ask: 0.9886, minDistance: 0, digits: 5 };

test("a box's three prices and its reward over risk", () => {
  const plan = planOf(short)!;
  assert.equal(plan.side, "SELL");
  assert.ok(Math.abs(plan.distance - 0.00267) < 1e-9);
  assert.ok(Math.abs(plan.ratio - 0.00393 / 0.00267) < 1e-6);
  assert.equal(planOf(box("long", 1.1, 1.12, 1.09))!.side, "BUY");
  assert.equal(planOf({ id: "t", type: "trendline", points: [], style: {} }), null);
});

test("a box can sell now, with its stop and target, even though the market has not reached the entry", () => {
  const order = boxOrder(planOf(short)!, 0.45, "market", market);
  assert.equal(order.problem, null);
  assert.deepEqual([order.how, order.side, order.volume, order.sl, order.tp, order.price, order.kind], ["market", "SELL", 0.45, 0.99167, 0.98507, null, null]);
});

test("...or leave a limit order at the entry", () => {
  const order = boxOrder(planOf(short)!, 0.45, "pending", market);
  assert.equal(order.problem, null);
  assert.equal(order.kind, "SELL_LIMIT", "the market is below the entry, so a sell there is a limit order");
  assert.equal(order.price, 0.989);
  assert.equal(order.sl, 0.99167);
});

test("an entry the market has already passed makes a stop order instead", () => {
  const order = boxOrder(planOf(short)!, 0.45, "pending", { ...market, bid: 0.9905, ask: 0.9906 });
  assert.equal(order.kind, "SELL_STOP");
  assert.equal(order.problem, null);
  // (the stop of this short, 0.99167, is still above the entry)
  assert.equal(boxOrder(planOf(box("long", 1.105, 1.12, 1.09))!, 0.1, "pending", { bid: 1.1, ask: 1.1002, minDistance: 0, digits: 4 }).kind, "BUY_STOP");
});

test("an entry at the market is not something to wait for", () => {
  const order = boxOrder(planOf(box("short", 0.9885, 0.98, 0.995))!, 0.1, "pending", market);
  assert.equal(order.kind, null);
  assert.match(order.problem!, /at the market/);
});

test("a target the market has already gone past cannot be traded now", () => {
  const order = boxOrder(planOf(short)!, 0.45, "market", { ...market, bid: 0.984, ask: 0.9841 });
  assert.match(order.problem!, /take profit of a sell has to be below the current buy price 0\.98410/);
});

test("a box whose stop was dragged to the wrong side of its entry is not a trade", () => {
  const inverted = box("short", 0.989, 0.98507, 0.9875); // the "stop" is below the entry of a sell
  for (const how of ["market", "pending"] as const) {
    const order = boxOrder(planOf(inverted)!, 0.1, how, market);
    assert.match(order.problem!, /stop loss of a sell has to be above the entry of the box/, how);
  }
});

test("the broker's minimum distance applies to the entry and to the levels", () => {
  const close = boxOrder(planOf(short)!, 0.1, "pending", { ...market, minDistance: 0.0006 });
  assert.match(close.problem!, /sell limit has to be above the current sell price 0\.98850, at least 0\.00060 away/);
  assert.equal(boxOrder(planOf(short)!, 0.1, "pending", { ...market, minDistance: 0.0001 }).problem, null);
});

test("no price, no order", () => {
  assert.match(boxOrder(planOf(short)!, 0.1, "market", null).problem!, /no price/i);
});

test("a box carries how big its trade is, and falls back to 1% of the balance", () => {
  const plan = planOf(box("long", 1.1, 1.104, 1.098))!; // stop 20 pips away
  assert.equal(sizeOf(box("long", 1.1, 1.104, 1.098), plan, eurusd, 10_000).lots, 0.5, "the default: 1% = 100");
  assert.equal(DEFAULTS.percent, 1);
  assert.equal(sizeOf(box("long", 1.1, 1.104, 1.098, { risk_mode: "percent", risk_percent: 0.5 }), plan, eurusd, 10_000).lots, 0.25);
  assert.equal(sizeOf(box("long", 1.1, 1.104, 1.098, { risk_mode: "amount", risk_amount: 40 }), plan, eurusd, 10_000).lots, 0.2);
  assert.equal(sizeOf(box("long", 1.1, 1.104, 1.098, { risk_mode: "lots", lots: 0.07 }), plan, eurusd, 10_000).lots, 0.07);
});
