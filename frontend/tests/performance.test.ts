import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PERIODS,
  accountSections,
  liveView,
  periodStart,
  profitFactorText,
  reasonLabel,
  replayView,
  serverNow,
  statSections,
  toneOf,
} from "../src/lib/performance.ts";
import type { AccountInfo, AccountReport, PerformanceSummary, ReplayAccount, ReplayReport } from "../src/lib/types.ts";

const summary: PerformanceSummary = {
  net_profit: 12.5,
  gross_profit: 30,
  gross_loss: 17.5,
  trades: 10,
  wins: 6,
  losses: 3,
  win_rate: 60,
  profit_factor: 30 / 17.5,
  avg_win: 5,
  avg_loss: 17.5 / 3,
  payoff_ratio: 0.857,
  largest_win: 9,
  largest_loss: -8,
  avg_trade: 1.25,
  avg_duration: 3_700,
  max_win_streak: 3,
  max_loss_streak: 2,
  max_drawdown: 11,
  max_drawdown_pct: 5.5,
  recovery_factor: 12.5 / 11,
  sharpe: 0.31,
  long_trades: 6,
  long_wins: 4,
  short_trades: 4,
  short_wins: 2,
  avg_win_streak: 1.5,
  avg_loss_streak: 1.5,
  max_win_streak_amount: 14,
  max_loss_streak_amount: -9,
  best_win_streak_amount: 14,
  best_win_streak_amount_trades: 3,
  worst_loss_streak_amount: -9,
  worst_loss_streak_amount_trades: 2,
  longest_duration: 90_000,
  shortest_duration: 12,
  total_volume: 1.35,
  commission: -3.2,
  swap: 0.4,
  fees: 0,
  drawdown_absolute: 4.5,
};

const none: PerformanceSummary = {
  ...summary,
  net_profit: 0,
  gross_profit: 0,
  gross_loss: 0,
  trades: 0,
  wins: 0,
  losses: 0,
  win_rate: 0,
  profit_factor: null,
  avg_win: 0,
  avg_loss: 0,
  payoff_ratio: null,
  largest_win: 0,
  largest_loss: 0,
  avg_trade: 0,
  avg_duration: 0,
  max_win_streak: 0,
  max_loss_streak: 0,
  max_drawdown: 0,
  max_drawdown_pct: 0,
  recovery_factor: null,
  sharpe: null,
  long_trades: 0,
  long_wins: 0,
  short_trades: 0,
  short_wins: 0,
  avg_win_streak: 0,
  avg_loss_streak: 0,
  max_win_streak_amount: 0,
  max_loss_streak_amount: 0,
  best_win_streak_amount: 0,
  best_win_streak_amount_trades: 0,
  worst_loss_streak_amount: 0,
  worst_loss_streak_amount_trades: 0,
  longest_duration: 0,
  shortest_duration: 0,
  total_volume: 0,
  commission: 0,
  swap: 0,
  fees: 0,
  drawdown_absolute: 0,
};

const row = (sections: ReturnType<typeof statSections>, title: string, label: string) =>
  sections.find((s) => s.title === title)?.rows.find((r) => r.label === label);

test("how a trade ended is told in words", () => {
  assert.equal(reasonLabel("sl"), "Stop loss");
  assert.equal(reasonLabel("tp"), "Take profit");
  assert.equal(reasonLabel("so"), "Stop out");
  assert.equal(reasonLabel("manual"), "Closed by hand");
  assert.equal(reasonLabel("session"), "Replay ended");
  assert.equal(reasonLabel("expert"), "Closed by a program");
  assert.equal(reasonLabel("corporate"), "Corporate");
  assert.equal(reasonLabel(""), "—");
});

test("the profit factor says why there is none", () => {
  assert.equal(profitFactorText(null), "—");
  assert.equal(profitFactorText({ profit_factor: null, wins: 0, trades: 0 }), "—");
  assert.equal(profitFactorText({ profit_factor: null, wins: 2, trades: 2 }), "∞");
  assert.equal(profitFactorText({ profit_factor: 1.5, wins: 2, trades: 3 }), "1.50");
});

test("the tone follows the sign", () => {
  assert.deepEqual([toneOf(1), toneOf(-1), toneOf(0)], ["pos", "neg", ""]);
});

test("the statistics hold every figure, in groups", () => {
  const sections = statSections(summary);
  assert.deepEqual(
    sections.map((s) => s.title),
    ["Results", "Trades", "Wins and losses"],
  );
  assert.equal(row(sections, "Results", "Net profit")?.value, "+12.50");
  assert.equal(row(sections, "Results", "Gross loss")?.value, "−17.50");
  assert.equal(row(sections, "Results", "Profit factor")?.value, "1.71");
  assert.equal(row(sections, "Results", "Recovery factor")?.value, "1.14");
  assert.equal(row(sections, "Results", "Sharpe ratio")?.value, "0.31");
  assert.equal(row(sections, "Results", "Largest drawdown")?.value, "−11.00");
  assert.equal(row(sections, "Results", "Largest drawdown, %")?.value, "5.50%");
  assert.equal(row(sections, "Trades", "Winning trades")?.value, "6 (60.0%)");
  assert.equal(row(sections, "Trades", "Long trades won")?.value, "4 of 6 (66.7%)");
  assert.equal(row(sections, "Trades", "Short trades won")?.value, "2 of 4 (50.0%)");
  assert.equal(row(sections, "Trades", "Average time held")?.value, "1h 1m");
  assert.equal(row(sections, "Wins and losses", "Most wins in a row")?.value, "3 (+14.00)");
  assert.equal(row(sections, "Wins and losses", "Worst losing streak")?.value, "2 (−9.00)");
  assert.equal(row(sections, "Wins and losses", "Average streaks")?.value, "+1.5 / −1.5");
  assert.equal(row(sections, "Results", "Absolute drawdown"), undefined); // that one is the broker's
});

test("an account with no trades has dashes, not zeros that look like results", () => {
  const sections = statSections(none);
  assert.equal(row(sections, "Results", "Profit factor")?.value, "—");
  assert.equal(row(sections, "Results", "Expected payoff")?.value, "—");
  assert.equal(row(sections, "Results", "Recovery factor")?.value, "—");
  assert.equal(row(sections, "Trades", "Volume traded")?.value, "—");
  assert.equal(row(sections, "Trades", "Long trades won")?.value, "—");
  assert.equal(row(sections, "Wins and losses", "Most wins in a row")?.value, "—");
  assert.equal(row(sections, "Wins and losses", "Average streaks")?.value, "—");
  assert.equal(row(sections, "Results", "Largest drawdown")?.value, "0.00");
});

test("the live account adds what its trades cost and the money that moved", () => {
  const flows = { deposits: 100, withdrawals: 20, credit: 0, bonus: 0, corrections: 0, charges: -1.5, operations: 3 };
  const sections = statSections(summary, { live: true, flows });
  assert.deepEqual(
    sections.map((s) => s.title),
    ["Results", "Trades", "Wins and losses", "Costs and money moved"],
  );
  assert.equal(row(sections, "Results", "Absolute drawdown")?.value, "−4.50");
  assert.equal(row(sections, "Costs and money moved", "Commission")?.value, "−3.20");
  assert.equal(row(sections, "Costs and money moved", "Swap")?.value, "+0.40");
  assert.equal(row(sections, "Costs and money moved", "Deposits")?.value, "100.00");
  assert.equal(row(sections, "Costs and money moved", "Withdrawals")?.value, "−20.00");
  assert.equal(row(sections, "Costs and money moved", "Charges, interest, taxes")?.value, "−1.50");
  assert.equal(row(sections, "Costs and money moved", "Credit"), undefined); // nothing to say: not listed
  // without the money moved (a broker that gave no history of it) only the costs are there
  assert.equal(statSections(summary, { live: true }).at(-1)?.rows.length, 3);
});

const account: AccountInfo = {
  login: 123456,
  server: "Broker-Demo",
  currency: "EUR",
  balance: 100.99,
  equity: 100.26,
  margin: 75.13,
  margin_free: 25.13,
  profit: -0.73,
  leverage: 500,
  name: "A. Trader",
  company: "Broker Ltd",
  credit: 0,
  margin_level: 133.449,
  margin_call_level: 90,
  stop_out_level: 20,
  stop_out_mode: "percent",
  trade_mode: "demo",
  margin_mode: "hedging",
  limit_orders: 200,
};

test("the account says who it is and where it stands", () => {
  const sections = accountSections(account);
  assert.deepEqual(
    sections.map((s) => s.title),
    ["Account", "Right now", "Margin limits"],
  );
  const get = (title: string, label: string) => sections.find((s) => s.title === title)?.rows.find((r) => r.label === label)?.value;
  assert.equal(get("Account", "Type"), "Demo");
  assert.equal(get("Account", "Margin mode"), "Hedging (positions side by side)");
  assert.equal(get("Account", "Leverage"), "1:500");
  assert.equal(get("Account", "Broker"), "Broker Ltd");
  assert.equal(get("Right now", "Balance"), "100.99 EUR");
  assert.equal(get("Right now", "Floating profit"), "−0.73 EUR");
  assert.equal(get("Right now", "Margin level"), "133.45%");
  assert.equal(get("Margin limits", "Stop out at"), "20%");
  assert.equal(get("Right now", "Credit"), undefined);
});

test("what the broker leaves empty is not listed", () => {
  const bare: AccountInfo = { login: 1, server: "", currency: "USD", balance: 10, equity: 10, margin: 0, margin_free: 10, profit: 0, leverage: 0, name: "" };
  const sections = accountSections(bare);
  assert.deepEqual(sections.map((s) => s.title), ["Account", "Right now"]);
  const labels = sections.flatMap((s) => s.rows.map((r) => r.label));
  assert.ok(!labels.includes("Margin level") && !labels.includes("Broker") && !labels.includes("Name") && !labels.includes("Type"));
  assert.equal(sections[0].rows.find((r) => r.label === "Leverage")?.value, "—");
  // a stop out given in money is read as money
  const money = accountSections({ ...account, stop_out_mode: "money", stop_out_level: 50, margin_call_level: 0 });
  assert.equal(money[2].rows[0].value, "50.00 EUR");
});

const paper: ReplayAccount = {
  initial_balance: 10_000,
  balance: 10_050,
  equity: 10_080,
  realized: 50,
  unrealized: 30,
  positions: [],
  metrics: { initial_balance: 10_000, final_balance: 10_080, total_return_pct: 0.8, max_drawdown_pct: 1, sharpe: 0, win_rate: 50, trades: 2, profit_factor: 2 },
  trades_total: 2,
  wins: 1,
  losses: 1,
  profile_id: "p",
  profile_name: "Practice",
};

test("the replay's report is brought up to the cursor with the account as it is", () => {
  const report: ReplayReport = {
    account: paper,
    summary,
    equity: [
      { time: 100, value: 10_000 },
      { time: 200, value: 10_050 },
    ],
    trades: [{ entry_time: 100, exit_time: 200, side: "BUY", entry_price: 1, exit_price: 1.1, volume: 0.1, pnl: 50, reason: "tp", ticket: 1, symbol: "EURUSD" }],
    symbols: [],
  };
  const view = replayView(report, paper, 300);
  assert.equal(view.kind, "replay");
  assert.deepEqual(view.curve.at(-1), { time: 300, value: 10_080 });
  assert.equal(view.baseline, 10_000);
  assert.equal(view.curveNow, 10_080);
  assert.equal(view.netSub, "+0.80% incl. open");
  assert.equal(view.tradesTotal, 1);
  assert.equal(view.account, null);
  // a cursor that has not moved past the curve adds nothing; no report yet is an empty view
  assert.equal(replayView(report, paper, 150).curve.length, 2);
  const empty = replayView(null, null, 0);
  assert.deepEqual([empty.summary, empty.curve, empty.trades, empty.curveNow, empty.netSub], [null, [], [], null, undefined]);
});

test("the live report is the same kind of view", () => {
  const live: AccountReport = {
    account,
    summary,
    equity: [
      { time: 100, value: 100 },
      { time: 400, value: 100.26 },
    ],
    trades: [],
    trades_total: 95,
    symbols: [],
    flows: { deposits: 100, withdrawals: 0, credit: 0, bonus: 0, corrections: 0, charges: 0, operations: 1 },
    initial_balance: 100,
    return_pct: 0.99,
    open_profit: -0.73,
    deals: 192,
    first_time: 100,
    last_time: 400,
  };
  const view = liveView(live);
  assert.equal(view.kind, "live");
  assert.equal(view.baseline, 100);
  assert.equal(view.curveNow, 100.26);
  assert.equal(view.netSub, "+0.99% of 100.00");
  assert.equal(view.tradesTotal, 95);
  assert.deepEqual(view.history, { deals: 192, first: 100, last: 400 });
  assert.equal(view.account?.server, "Broker-Demo");
  assert.equal(liveView({ ...live, return_pct: null }).netSub, undefined);
  const before = liveView(null);
  assert.deepEqual([before.summary, before.curveNow, before.history, before.tradesTotal], [null, null, null, 0]);
});

test("the broker's clock is this machine's plus the skew, when it is known", () => {
  assert.equal(serverNow(null), undefined);
  assert.equal(serverNow(7200, 1_700_000_000_500), 1_700_007_200);
  assert.equal(serverNow(-3600, 1_700_000_000_000), 1_699_996_400);
});

test("a period begins at the start of the day, week, month or year of the broker's clock", () => {
  const at = (iso: string) => Date.parse(iso) / 1000;
  const saturday = at("2026-10-03T15:30:45Z");
  assert.equal(periodStart("all", saturday), 0);
  assert.equal(periodStart("day", saturday), at("2026-10-03T00:00:00Z"));
  assert.equal(periodStart("week", saturday), at("2026-09-28T00:00:00Z")); // the Monday before
  assert.equal(periodStart("month", saturday), at("2026-10-01T00:00:00Z"));
  assert.equal(periodStart("year", saturday), at("2026-01-01T00:00:00Z"));
  // a Monday is the start of its own week, a Sunday belongs to the week before
  assert.equal(periodStart("week", at("2026-09-28T09:00:00Z")), at("2026-09-28T00:00:00Z"));
  assert.equal(periodStart("week", at("2026-10-04T23:59:59Z")), at("2026-09-28T00:00:00Z"));
  // a week that began in the month before
  assert.equal(periodStart("week", at("2026-10-01T12:00:00Z")), at("2026-09-28T00:00:00Z"));
  assert.deepEqual(PERIODS.map((p) => p.id), ["all", "year", "month", "week", "day"]);
});
