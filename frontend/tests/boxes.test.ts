import assert from "node:assert/strict";
import { test } from "node:test";
import type { ContextMenuItem } from "../src/components/ChartContextMenu";
import { buildDrawingMenu, RISK_PRESETS, type MenuActions } from "../src/lib/boxMenu";
import { enterAt, type BoxOrder } from "../src/lib/boxOrder";
import { marketOf, notesOf, orderRequest, viewOf, type BoxTrading } from "../src/lib/boxTrading";
import type { Drawing } from "../src/lib/drawings";
import type { Position, Symbol } from "../src/lib/types";

// EURUSD as a broker describes it: a step of 0.00001 is worth 1 USD per lot.
const eurusd = {
  name: "EURUSD",
  digits: 5,
  point: 0.00001,
  trade_contract_size: 100_000,
  trade_tick_size: 0.00001,
  trade_tick_value: 1,
  volume_min: 0.01,
  volume_max: 100,
  volume_step: 0.01,
  trade_stops_level: 0,
} as Symbol;

const trading = (change: Partial<BoxTrading> = {}): BoxTrading => ({
  enabled: true,
  paper: false,
  symbol: eurusd,
  digits: 5,
  bid: 1.1,
  ask: 1.1002,
  balance: 10_000,
  currency: "USD",
  positions: [],
  place: async () => true,
  setLevels: () => undefined,
  ...change,
});

const box = (type: "long" | "short", entry: number, target: number, stop: number, style: Drawing["style"] = {}, locked = false): Drawing => ({
  id: "b1",
  type,
  points: [{ time: 100, price: entry }, { time: 200, price: target }, { time: 200, price: stop }],
  style,
  locked,
});

// a long below the market: entry 1.0990, stop 1.0970 (20 pips), target 1.1030
const long = box("long", 1.099, 1.103, 1.097);

const position = (ticket: number, side: "BUY" | "SELL", volume = 0.1): Position => ({
  ticket,
  symbol: "EURUSD",
  side,
  volume,
  price_open: 1.1,
  price_current: 1.1,
  sl: 0,
  tp: 0,
  profit: 0,
  time: 0,
  comment: "",
});

const actions = () => {
  const calls: string[] = [];
  const act: MenuActions = {
    order: (o: BoxOrder) => calls.push(`order ${o.how} ${o.side} ${o.volume}`),
    applyTo: (p: Position) => calls.push(`apply ${p.ticket}`),
    setSize: (s) => calls.push(`size ${JSON.stringify(s)}`),
    editSize: () => calls.push("edit"),
    lock: (l) => calls.push(`lock ${l}`),
    remove: () => calls.push("remove"),
  };
  return { act, calls };
};
const menu = (d: Drawing, t: BoxTrading) => buildDrawingMenu(d, viewOf(d, t), t, actions().act);
const find = (items: ContextMenuItem[], key: string) => items.find((i) => i.key === key);

// -- what the box knows about its trade --------------------------------------------------------------------------
test("a box is sized from the balance, 1% by default, and its orders are worked out with that size", () => {
  const view = viewOf(long, trading())!;
  assert.equal(view.size!.ok, true);
  assert.equal(view.size!.lots, 0.5, "100 USD over a stop 20 pips (200 USD per lot) away");
  assert.equal(view.now!.volume, 0.5);
  assert.equal(view.now!.problem, null);
  assert.equal(view.wait!.kind, "BUY_LIMIT", "the entry is below the market");
  assert.equal(view.wait!.problem, null);
});

test("a replay trades the paper account: no waiting order, and the size follows what the paper account pays", () => {
  const view = viewOf(long, trading({ paper: true, symbol: { ...eurusd, trade_tick_value: 0.5 } as Symbol }))!;
  assert.equal(view.wait, null);
  assert.equal(view.size!.lots, 1, "100 USD over a stop 20 pips away, a lot paying 100 USD for it: the tick value counts in a replay too");
});

test("without the instrument's details the box cannot be traded, and says so", () => {
  const view = viewOf(long, trading({ symbol: null }))!;
  assert.equal(view.size, null);
  assert.match(view.now!.problem!, /not known yet/);
  assert.match(view.wait!.problem!, /not known yet/);
});

test("a stop on the wrong side of the market cannot be sent now, but can still wait", () => {
  // the market stands below this box's stop 1.0970? no: it stands at 1.0960, so a buy now with that stop is impossible
  const view = viewOf(long, trading({ bid: 1.096, ask: 1.0962 }))!;
  assert.match(view.now!.problem!, /stop loss of a buy has to be below the current sell price 1\.09600/);
  assert.equal(view.wait!.kind, "BUY_STOP", "the market fell under the entry: a buy there is a stop order");
});

test("a size that cannot be worked out blocks the orders", () => {
  const view = viewOf(long, trading({ balance: 0 }))!;
  assert.equal(view.size!.ok, false);
  assert.ok(view.now!.problem);
  assert.ok(view.wait!.problem);
});

test("the market a box meets keeps the broker's minimum distance, except in a replay", () => {
  const strict = { ...eurusd, trade_stops_level: 30 } as Symbol;
  assert.equal(marketOf(trading({ symbol: strict }))!.minDistance, 30 * 0.00001);
  assert.equal(marketOf(trading({ symbol: strict, paper: true }))!.minDistance, 0);
  assert.equal(marketOf(trading({ bid: null })), null, "no quote, no market");
});

test("the words under a box's title say how big the trade is", () => {
  assert.deepEqual(notesOf(viewOf(long, trading())!, "USD"), ["0.50 lots · risk 100.00 USD (1.00%)"]);
  assert.deepEqual(notesOf(null, "USD"), []);
  const tiny = viewOf(long, trading({ balance: 100 }))!;
  assert.match(notesOf(tiny, "USD")[0], /\(the smallest\)/, "the account is too small for what was asked: say so");
});

test("an order request is rounded to the price digits and carries the kind only when it waits", () => {
  const view = viewOf(long, trading())!;
  assert.deepEqual(orderRequest("EURUSD", view.now!, 5), {
    symbol: "EURUSD",
    side: "BUY",
    volume: 0.5,
    order_type: null,
    price: null,
    sl: 1.097,
    tp: 1.103,
  });
  const waiting = orderRequest("EURUSD", { ...view.wait!, price: 1.0990000000001, sl: 1.0970000000002 }, 5);
  assert.equal(waiting.order_type, "BUY_LIMIT");
  assert.equal(waiting.price, 1.099);
  assert.equal(waiting.sl, 1.097);
});

// -- the right-click menu ---------------------------------------------------------------------------------------------
test("a box's menu leads with its trade, then sizes, then lock and delete", () => {
  const items = menu(long, trading());
  assert.deepEqual(
    items.map((i) => i.key),
    ["title", "now", "wait", "size-title", ...RISK_PRESETS.map((p) => `risk-${p}`), "risk-custom", "lock", "delete"],
  );
  assert.match(find(items, "title")!.label, /^Long · 0\.50 lots · risk 100\.00 USD \(1\.00%\)$/);
  assert.equal(find(items, "now")!.label, "Buy 0.50 lots now");
  assert.match(find(items, "now")!.note!, /at the market · stop 1\.09700 · target 1\.10300/);
  assert.equal(find(items, "now")!.tone, "buy");
  assert.equal(find(items, "wait")!.label, "Buy limit 0.50 lots at 1.09900");
  assert.equal(find(items, "now")!.disabled, false);
});

test("the heading says when the broker's smallest volume risks more than was asked", () => {
  const items = menu(long, trading({ balance: 100 }));
  assert.match(find(items, "title")!.label, /^Long · 0\.01 lots \(the smallest\) · risk 2\.00 USD \(2\.00%\)$/);
});

test("a short box offers selling, in the sell colour", () => {
  const items = menu(box("short", 1.101, 1.097, 1.103), trading());
  assert.equal(find(items, "now")!.label, "Sell 0.50 lots now");
  assert.equal(find(items, "now")!.tone, "sell");
  assert.equal(find(items, "wait")!.label, "Sell limit 0.50 lots at 1.10100", "the entry is above the market");
});

test("choosing an entry sends exactly the order it showed", () => {
  const { act, calls } = actions();
  const t = trading();
  const items = buildDrawingMenu(long, viewOf(long, t), t, act);
  find(items, "now")!.onSelect();
  find(items, "wait")!.onSelect();
  find(items, "risk-2")!.onSelect();
  find(items, "risk-custom")!.onSelect();
  find(items, "lock")!.onSelect();
  find(items, "delete")!.onSelect();
  assert.deepEqual(calls, [
    "order market BUY 0.5",
    "order pending BUY 0.5",
    `size ${JSON.stringify({ risk_mode: "percent", risk_percent: 2 })}`,
    "edit",
    "lock true",
    "remove",
  ]);
});

test("an entry that breaks a rule is greyed out and says why", () => {
  const items = menu(long, trading({ bid: 1.096, ask: 1.0962 }));
  assert.equal(find(items, "now")!.disabled, true);
  assert.match(find(items, "now")!.note!, /stop loss of a buy has to be below the current sell price/);
  assert.equal(find(items, "wait")!.disabled, false);
  assert.equal(find(items, "wait")!.label, "Buy stop 0.50 lots at 1.09900");
});

test("nothing can be sent while orders are not enabled", () => {
  const items = menu(long, trading({ enabled: false }));
  assert.equal(find(items, "now")!.disabled, true);
  assert.equal(find(items, "wait")!.disabled, true);
  assert.match(find(items, "now")!.note!, /cannot be sent right now/);
});

test("a replay's menu has no waiting order", () => {
  const items = menu(long, trading({ paper: true }));
  assert.equal(find(items, "wait"), undefined);
  assert.ok(find(items, "now"));
});

test("an open position in the same direction can take the box's stop and target; the other direction cannot", () => {
  const items = menu(long, trading({ positions: [position(7, "BUY", 0.2), position(8, "SELL", 0.2)] }));
  const apply = items.filter((i) => i.key.startsWith("apply-"));
  assert.deepEqual(apply.map((i) => i.key), ["apply-7"]);
  assert.equal(apply[0].label, "Set stop and target of the open buy 0.20");
  assert.match(apply[0].note!, /stop 1\.09700 · target 1\.10300 from this box/);
  const { act, calls } = actions();
  const t = trading({ positions: [position(7, "BUY")] });
  find(buildDrawingMenu(long, viewOf(long, t), t, act), "apply-7")!.onSelect();
  assert.deepEqual(calls, ["apply 7"]);
});

test("with several positions each is named by its ticket", () => {
  const items = menu(long, trading({ positions: [position(7, "BUY"), position(9, "BUY", 0.3)] }));
  assert.deepEqual(items.filter((i) => i.key.startsWith("apply-")).map((i) => i.label), [
    "Set stop and target of the open buy 0.10 (#7)",
    "Set stop and target of the open buy 0.30 (#9)",
  ]);
});

test("the size the box has is the one ticked", () => {
  const ticked = (d: Drawing) => menu(d, trading()).filter((i) => i.checked).map((i) => i.key);
  assert.deepEqual(ticked(long), ["risk-1"], "the default");
  assert.deepEqual(ticked(box("long", 1.099, 1.103, 1.097, { risk_mode: "percent", risk_percent: 5 })), ["risk-5"]);
  assert.deepEqual(ticked(box("long", 1.099, 1.103, 1.097, { risk_mode: "amount", risk_amount: 50 })), [], "an amount is none of the shares");
  assert.equal(find(menu(box("long", 1.099, 1.103, 1.097, { risk_mode: "lots", lots: 0.2 }), trading()), "risk-custom")!.label, "Lots (set), or a share or amount…");
});

test("any drawing can be locked, and a locked one cannot be deleted from its menu", () => {
  const line: Drawing = { id: "t", type: "trendline", points: [{ time: 1, price: 1 }, { time: 2, price: 2 }], style: {} };
  const items = menu(line, trading());
  assert.deepEqual(items.map((i) => i.key), ["lock", "delete"], "a line is not a trade: no orders, no sizes");
  assert.equal(find(items, "lock")!.label, "Lock");
  assert.equal(find(items, "delete")!.disabled, false);

  const locked = menu({ ...line, locked: true }, trading());
  assert.equal(find(locked, "lock")!.label, "Unlock");
  assert.equal(find(locked, "delete")!.disabled, true);
  assert.match(find(locked, "delete")!.note!, /unlock it first/i);

  const { act, calls } = actions();
  find(buildDrawingMenu({ ...line, locked: true }, null, trading(), act), "lock")!.onSelect();
  assert.deepEqual(calls, ["lock false"]);
});

test("a locked box can still be traded and sized", () => {
  const items = menu({ ...long, locked: true }, trading());
  assert.equal(find(items, "now")!.disabled, false);
  assert.equal(find(items, "lock")!.label, "Unlock");
  assert.equal(find(items, "delete")!.disabled, true);
});

// -- the entry line follows the trade that was opened ------------------------------------------------------------

test("after a sell at the market the short box's entry is where the trade opened, its stop and target stay", () => {
  const short = box("short", 0.9878, 0.9864, 0.99363);
  const moved = enterAt(short, 0.9886, 150)!;
  assert.deepEqual(moved.points[0], { time: 150, price: 0.9886 });
  assert.deepEqual(moved.points.slice(1), short.points.slice(1), "the target and the stop do not move");
  assert.equal(moved.type, "short");
  assert.deepEqual(short.points[0], { time: 100, price: 0.9878 }, "the box that was passed in is left alone");
});

test("a long box moves the same way", () => {
  const moved = enterAt(long, 1.1002, 120)!;
  assert.deepEqual(moved.points[0], { time: 120, price: 1.1002 });
});

test("the candle the trade opened in is used only while it is before the end of the box", () => {
  assert.equal(enterAt(long, 1.1, 250)!.points[0].time, 100, "the box ends at 200: it keeps its own start");
  assert.equal(enterAt(long, 1.1, 200)!.points[0].time, 100, "...also exactly at its end");
  assert.equal(enterAt(long, 1.1, null)!.points[0].time, 100, "no candle known: the start stays");
  assert.equal(enterAt(long, 1.1, 50)!.points[0].time, 50, "earlier is fine too");
});

test("a fill outside the stop and target leaves no box, so the box stays as it was", () => {
  assert.equal(enterAt(long, 1.097, 120), null, "on the stop");
  assert.equal(enterAt(long, 1.103, 120), null, "on the target");
  assert.equal(enterAt(long, 1.09, 120), null, "beyond the stop");
  assert.equal(enterAt(box("short", 1.101, 1.097, 1.103), 1.104, 120), null);
  assert.equal(enterAt(box("short", 1.101, 1.097, 1.103), 1.096, 120), null);
  assert.equal(enterAt(long, 0, 120), null, "no price, no move");
  const line: Drawing = { id: "t", type: "trendline", points: [{ time: 1, price: 1 }, { time: 2, price: 2 }], style: {} };
  assert.equal(enterAt(line, 1.5, 1), null, "only boxes have an entry");
});
