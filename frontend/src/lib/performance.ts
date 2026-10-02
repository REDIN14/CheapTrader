// What the performance report says, in numbers and words (pure functions, so that they can be tested).
//
// One report serves the replay's paper account and the live account. Both arrive as the same figures
// (backend/app/performance.py works them out from a list of closed trades); this turns them into what
// the drawer shows: the lines of the statistics table, the account's own figures, the way a trade ended,
// and the two "views" that bring the replay's data and the broker's data to one shape.

import { formatDuration, formatInt, formatLots, formatMoney } from "./format";
import type {
  AccountFlows,
  AccountInfo,
  AccountReport,
  BacktestTrade,
  ClosedTrade,
  EquityPoint,
  PerformanceSummary,
  ReplayAccount,
  ReplayReport,
  SymbolStats,
} from "./types";

export type Tone = "pos" | "neg" | "";

export const toneOf = (value: number): Tone => (value > 0 ? "pos" : value < 0 ? "neg" : "");

const REASONS: Record<string, string> = {
  sl: "Stop loss",
  tp: "Take profit",
  so: "Stop out",
  manual: "Closed by hand",
  expert: "Closed by a program",
  session: "Replay ended",
  rewind: "Rewound",
  rollover: "Rollover",
  vmargin: "Variation margin",
  split: "Split",
};

/** Why a trade ended, in words. */
export function reasonLabel(reason: string): string {
  if (REASONS[reason]) return REASONS[reason];
  return reason ? reason[0].toUpperCase() + reason.slice(1) : "—";
}

/** The profit factor in words: "—" with no trades at all, "∞" with wins only. */
export function profitFactorText(s: Pick<PerformanceSummary, "profit_factor" | "wins" | "trades"> | null): string {
  if (!s || s.trades === 0) return "—";
  if (s.profit_factor != null) return s.profit_factor.toFixed(2);
  return s.wins > 0 ? "∞" : "—";
}

const pct = (part: number, whole: number) => (whole > 0 ? ` (${((part / whole) * 100).toFixed(1)}%)` : "");
const minus = (value: number) => (value > 0 ? formatMoney(-value) : formatMoney(0));

// -- the statistics table --------------------------------------------------------------------------------
export interface Stat {
  label: string;
  value: string;
  tone?: Tone;
  /** What the figure means, for the tooltip. */
  hint?: string;
}

export interface StatSection {
  title: string;
  rows: Stat[];
}

/**
 * The longer table of the report: every figure there is, in groups. The live account adds what its trades cost and
 * the money that moved (`flows`); the replay has neither.
 */
export function statSections(s: PerformanceSummary, opts: { live?: boolean; flows?: AccountFlows | null } = {}): StatSection[] {
  const none = s.trades === 0;
  const runs = (count: number, amount: number) => (count ? `${count} (${formatMoney(amount, "", true)})` : "—");
  const money = (value: number) => (none ? "—" : formatMoney(value, "", true));
  const sections: StatSection[] = [
    {
      title: "Results",
      rows: [
        { label: "Net profit", value: formatMoney(s.net_profit, "", true), tone: toneOf(s.net_profit), hint: "What the closed trades made, after their costs" },
        { label: "Gross profit", value: formatMoney(s.gross_profit), tone: s.gross_profit ? "pos" : "" },
        { label: "Gross loss", value: minus(s.gross_loss), tone: s.gross_loss ? "neg" : "" },
        { label: "Profit factor", value: profitFactorText(s), hint: "Gross profit divided by gross loss" },
        { label: "Expected payoff", value: money(s.avg_trade), tone: none ? "" : toneOf(s.avg_trade), hint: "What a trade makes on average" },
        { label: "Recovery factor", value: s.recovery_factor != null ? s.recovery_factor.toFixed(2) : "—", hint: "Net profit divided by the largest drawdown" },
        { label: "Sharpe ratio", value: s.sharpe != null ? s.sharpe.toFixed(2) : "—", hint: "The mean of the trades' returns over their spread (three trades or more)" },
        { label: "Largest drawdown", value: s.max_drawdown > 0 ? `−${formatMoney(s.max_drawdown)}` : "0.00", tone: s.max_drawdown > 0 ? "neg" : "", hint: "The biggest fall from a peak" },
        { label: "Largest drawdown, %", value: `${s.max_drawdown_pct.toFixed(2)}%`, tone: s.max_drawdown_pct > 0 ? "neg" : "", hint: "The biggest fall from a peak, as a share of the peak" },
        ...(opts.live
          ? [{ label: "Absolute drawdown", value: s.drawdown_absolute > 0 ? `−${formatMoney(s.drawdown_absolute)}` : "0.00", tone: (s.drawdown_absolute > 0 ? "neg" : "") as Tone, hint: "How far the account stood below the money first put in, at the most" }]
          : []),
      ],
    },
    {
      title: "Trades",
      rows: [
        { label: "Closed trades", value: formatInt(s.trades) },
        { label: "Winning trades", value: `${s.wins}${pct(s.wins, s.trades)}` },
        { label: "Losing trades", value: `${s.losses}${pct(s.losses, s.trades)}` },
        { label: "Long trades won", value: s.long_trades ? `${s.long_wins} of ${s.long_trades}${pct(s.long_wins, s.long_trades)}` : "—" },
        { label: "Short trades won", value: s.short_trades ? `${s.short_wins} of ${s.short_trades}${pct(s.short_wins, s.short_trades)}` : "—" },
        { label: "Volume traded", value: none ? "—" : `${formatLots(s.total_volume)} lots` },
        { label: "Average time held", value: none ? "—" : formatDuration(s.avg_duration) },
        { label: "Longest / shortest", value: none ? "—" : `${formatDuration(s.longest_duration)} / ${formatDuration(s.shortest_duration)}` },
      ],
    },
    {
      title: "Wins and losses",
      rows: [
        { label: "Largest win", value: s.wins ? formatMoney(s.largest_win, "", true) : "—", tone: s.wins ? "pos" : "" },
        { label: "Largest loss", value: s.losses ? formatMoney(s.largest_loss, "", true) : "—", tone: s.losses ? "neg" : "" },
        { label: "Average win", value: s.wins ? formatMoney(s.avg_win, "", true) : "—", tone: s.wins ? "pos" : "" },
        { label: "Average loss", value: s.losses ? formatMoney(-s.avg_loss, "", true) : "—", tone: s.losses ? "neg" : "" },
        { label: "Win / loss ratio", value: s.payoff_ratio != null ? s.payoff_ratio.toFixed(2) : "—", hint: "Average win divided by average loss" },
        { label: "Most wins in a row", value: runs(s.max_win_streak, s.max_win_streak_amount), hint: "The longest winning streak, and what it made" },
        { label: "Most losses in a row", value: runs(s.max_loss_streak, s.max_loss_streak_amount), hint: "The longest losing streak, and what it lost" },
        { label: "Best winning streak", value: runs(s.best_win_streak_amount_trades, s.best_win_streak_amount), hint: "The streak that made the most (trades in it, and what it made)" },
        { label: "Worst losing streak", value: runs(s.worst_loss_streak_amount_trades, s.worst_loss_streak_amount), hint: "The streak that lost the most (trades in it, and what it lost)" },
        { label: "Average streaks", value: s.avg_win_streak || s.avg_loss_streak ? `+${s.avg_win_streak.toFixed(1)} / −${s.avg_loss_streak.toFixed(1)}` : "—", hint: "How many trades a winning / losing streak has, on average" },
      ],
    },
  ];
  if (opts.live) {
    const f = opts.flows;
    sections.push({
      title: "Costs and money moved",
      rows: [
        { label: "Commission", value: formatMoney(s.commission, "", true), tone: toneOf(s.commission), hint: "What the closed trades paid in commission" },
        { label: "Swap", value: formatMoney(s.swap, "", true), tone: toneOf(s.swap), hint: "What holding positions overnight cost or paid" },
        { label: "Fees", value: formatMoney(s.fees, "", true), tone: toneOf(s.fees) },
        ...(f
          ? [
              { label: "Deposits", value: formatMoney(f.deposits), hint: "Money put in (not part of the figures)" },
              { label: "Withdrawals", value: f.withdrawals ? `−${formatMoney(f.withdrawals)}` : "0.00", hint: "Money taken out (not part of the figures)" },
              ...(f.credit ? [{ label: "Credit", value: formatMoney(f.credit) }] : []),
              ...(f.bonus ? [{ label: "Bonus", value: formatMoney(f.bonus, "", true) }] : []),
              ...(f.corrections ? [{ label: "Corrections", value: formatMoney(f.corrections, "", true) }] : []),
              { label: "Charges, interest, taxes", value: formatMoney(f.charges, "", true), tone: toneOf(f.charges), hint: "Fees, interest, dividends and taxes booked to the account apart from the trades; they are in the curve" },
            ]
          : []),
      ],
    });
  }
  return sections;
}

// -- the account's own figures -----------------------------------------------------------------------------
const TRADE_MODE: Record<string, string> = { demo: "Demo", contest: "Contest", real: "Real" };
const MARGIN_MODE: Record<string, string> = {
  netting: "Netting (one position per instrument)",
  exchange: "Exchange",
  hedging: "Hedging (positions side by side)",
};

/** What the broker says about the account: who and what it is, and where it stands now. */
export function accountSections(a: AccountInfo): StatSection[] {
  const ccy = a.currency;
  const level = (value: number | undefined) => {
    if (!value) return null;
    return a.stop_out_mode === "money" ? formatMoney(value, ccy) : `${value}%`;
  };
  const who: Stat[] = [
    ...(a.name ? [{ label: "Name", value: a.name }] : []),
    { label: "Login", value: String(a.login) },
    { label: "Server", value: a.server || "—" },
    ...(a.company ? [{ label: "Broker", value: a.company }] : []),
    ...(a.trade_mode ? [{ label: "Type", value: TRADE_MODE[a.trade_mode] ?? a.trade_mode }] : []),
    ...(a.margin_mode ? [{ label: "Margin mode", value: MARGIN_MODE[a.margin_mode] ?? a.margin_mode }] : []),
    { label: "Leverage", value: a.leverage ? `1:${a.leverage}` : "—" },
    { label: "Currency", value: ccy },
    ...(a.limit_orders ? [{ label: "Pending orders allowed", value: String(a.limit_orders) }] : []),
  ];
  const now: Stat[] = [
    { label: "Balance", value: formatMoney(a.balance, ccy) },
    ...(a.credit ? [{ label: "Credit", value: formatMoney(a.credit, ccy) }] : []),
    { label: "Floating profit", value: formatMoney(a.profit, ccy, true), tone: toneOf(a.profit), hint: "What the open positions make right now" },
    { label: "Equity", value: formatMoney(a.equity, ccy) },
    { label: "Margin used", value: formatMoney(a.margin, ccy) },
    { label: "Free margin", value: formatMoney(a.margin_free, ccy) },
    ...(a.margin > 0 && a.margin_level ? [{ label: "Margin level", value: `${a.margin_level.toFixed(2)}%`, hint: "Equity as a share of the margin in use" }] : []),
  ];
  const limits: Stat[] = [
    ...(level(a.margin_call_level) ? [{ label: "Margin call at", value: level(a.margin_call_level) as string }] : []),
    ...(level(a.stop_out_level) ? [{ label: "Stop out at", value: level(a.stop_out_level) as string, hint: "The broker closes positions when the margin level falls to this" }] : []),
    ...(a.assets ? [{ label: "Assets", value: formatMoney(a.assets, ccy) }] : []),
    ...(a.liabilities ? [{ label: "Liabilities", value: formatMoney(a.liabilities, ccy) }] : []),
    ...(a.commission_blocked ? [{ label: "Commission blocked", value: formatMoney(a.commission_blocked, ccy) }] : []),
  ];
  return [
    { title: "Account", rows: who },
    { title: "Right now", rows: now },
    ...(limits.length ? [{ title: "Margin limits", rows: limits }] : []),
  ];
}

// -- one shape for the replay's report and the broker's ----------------------------------------------------------
export type ReportTrade = BacktestTrade | ClosedTrade;

/** What the drawer needs, whichever account it is showing. */
export interface ReportView {
  kind: "replay" | "live";
  summary: PerformanceSummary | null;
  trades: ReportTrade[];
  /** How many closed trades there are (the list may hold only the newest). */
  tradesTotal: number;
  curve: EquityPoint[];
  /** What the curve is measured from (the shading is green above it, red below). */
  baseline: number;
  /** Where the curve stands now, or null before there is one. */
  curveNow: number | null;
  /** The small line under "Net profit". */
  netSub: string | undefined;
  returnPct: number | null;
  symbols: SymbolStats[];
  flows: AccountFlows | null;
  account: AccountInfo | null;
  /** The live account's history: how many deals, and from when to when. */
  history: { deals: number; first: number; last: number } | null;
}

export const signedPercent = (value: number) => `${formatMoney(value, "", true)}%`;

/** The replay's report, brought up to the cursor with the account as it is now. */
export function replayView(report: ReplayReport | null, account: ReplayAccount | null, cursorTime: number): ReportView {
  let curve = report?.equity ?? [];
  if (account && curve.length) {
    const last = curve[curve.length - 1];
    if (cursorTime > last.time) curve = [...curve, { time: cursorTime, value: account.equity }];
  }
  return {
    kind: "replay",
    summary: report?.summary ?? null,
    trades: report?.trades ?? [],
    tradesTotal: report?.trades.length ?? 0,
    curve,
    baseline: account?.initial_balance ?? 0,
    curveNow: account ? account.equity : null,
    netSub: account ? `${signedPercent(account.metrics.total_return_pct)} incl. open` : undefined,
    returnPct: account ? account.metrics.total_return_pct : null,
    symbols: report?.symbols ?? [],
    flows: null,
    account: null,
    history: null,
  };
}

/** The live account's report: the broker's history as the same kind of report. */
export function liveView(report: AccountReport | null): ReportView {
  const curve = report?.equity ?? [];
  return {
    kind: "live",
    summary: report?.summary ?? null,
    trades: report?.trades ?? [],
    tradesTotal: report?.trades_total ?? 0,
    curve,
    baseline: report?.initial_balance ?? 0,
    curveNow: curve.length ? curve[curve.length - 1].value : null,
    netSub:
      report && report.return_pct != null
        ? `${signedPercent(report.return_pct)} of ${formatMoney(report.initial_balance)}`
        : undefined,
    returnPct: report?.return_pct ?? null,
    symbols: report?.symbols ?? [],
    flows: report?.flows ?? null,
    account: report?.account ?? null,
    history: report ? { deals: report.deals, first: report.first_time, last: report.last_time } : null,
  };
}

/** The periods the live report can be cut to. */
export type Period = "all" | "year" | "month" | "week" | "day";

export const PERIODS: { id: Period; label: string }[] = [
  { id: "all", label: "All time" },
  { id: "year", label: "This year" },
  { id: "month", label: "This month" },
  { id: "week", label: "This week" },
  { id: "day", label: "Today" },
];

/**
 * Where a period begins, in the broker's time (seconds): its wall clock written as if it were UTC, as everywhere
 * here. A week begins on Monday. 0 is the whole history.
 */
export function periodStart(period: Period, serverNowSeconds: number): number {
  if (period === "all") return 0;
  const d = new Date(serverNowSeconds * 1000);
  const [y, m, day] = [d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()];
  if (period === "year") return Date.UTC(y, 0, 1) / 1000;
  if (period === "month") return Date.UTC(y, m, 1) / 1000;
  if (period === "day") return Date.UTC(y, m, day) / 1000;
  const sinceMonday = (d.getUTCDay() + 6) % 7;
  return Date.UTC(y, m, day - sinceMonday) / 1000;
}

/** The broker's clock now, in seconds, when it is known (see serverClock.ts): where the live curve should end. */
export function serverNow(skew: number | null, nowMs = Date.now()): number | undefined {
  return skew == null ? undefined : Math.floor(nowMs / 1000 + skew);
}
