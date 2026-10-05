// Wire types mirroring backend/app/schemas.py

import type { Drawing } from "./drawings";

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";

export const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"];

export interface Symbol {
  name: string;
  description: string;
  path: string;
  digits: number;
  point: number;
  spread: number;
  trade_mode: number;
  visible: boolean;
  trade_contract_size: number;
  /** What one price step ("tick") of one lot is worth in the account's currency, and the step itself. */
  trade_tick_value: number;
  trade_tick_size: number;
  /** Smallest, largest and step of an order's volume, in lots. */
  volume_min: number;
  volume_max: number;
  volume_step: number;
  /** How close (in points) a pending order or a stop may sit to the market. */
  trade_stops_level: number;
  /** What a profit on this instrument is paid in. */
  currency_profit: string;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread: number;
  real_volume: number;
}

export interface Tick {
  time: number;
  bid: number;
  ask: number;
  last: number;
  volume: number;
  time_msc: number;
  flags: number;
}

export interface AccountInfo {
  login: number;
  server: string;
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  margin_free: number;
  profit: number;
  leverage: number;
  name: string;
  /** What else the broker says about the account (empty or zero where it says nothing). */
  company?: string;
  credit?: number;
  /** Percent; 0 while no margin is in use. */
  margin_level?: number;
  margin_call_level?: number;
  stop_out_level?: number;
  stop_out_mode?: "percent" | "money" | "";
  trade_mode?: "demo" | "contest" | "real" | "";
  margin_mode?: "netting" | "exchange" | "hedging" | "";
  /** The most pending orders the broker allows (0: no limit). */
  limit_orders?: number;
  fifo_close?: boolean;
  currency_digits?: number;
  assets?: number;
  liabilities?: number;
  commission_blocked?: number;
}

export interface Position {
  ticket: number;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  time: number;
  comment: string;
}

/** The kinds of order that wait for a price instead of trading at once. */
export type PendingKind = "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP";

export interface OrderRequest {
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  /** Set for a limit / stop order: it waits instead of trading now. */
  order_type?: PendingKind | null;
  /** The price a pending order waits for. */
  price?: number | null;
  sl?: number | null;
  tp?: number | null;
  comment?: string;
}

/** An order waiting for the market to reach its price. */
export interface PendingOrder {
  ticket: number;
  symbol: string;
  side: "BUY" | "SELL";
  order_type: PendingKind;
  volume: number;
  price: number;
  sl: number;
  tp: number;
  /** The market price now (the ask for a buy, the bid for a sell). */
  price_current: number;
  time: number;
  comment: string;
}

export interface OrderResult {
  ok: boolean;
  retcode: number;
  order_id: number;
  deal_id: number;
  volume: number;
  price: number;
  comment: string;
  error: string | null;
  /** How long the broker took to answer, in ms (0 when the backend does not say). */
  latency_ms?: number;
}

export interface Health {
  status: string;
  version?: string;
  broker: string;
  connected: boolean;
  symbols: number;
}

/** A document in the in-app documentation. */
export interface DocInfo {
  id: string;
  title: string;
}

export interface DocPage extends DocInfo {
  markdown: string;
}

/** What the connected MetaTrader terminal says about itself, and whether it will take orders. */
export interface TerminalInfo {
  connected: boolean;
  name: string;
  company: string;
  path: string;
  exe: string;
  data_path: string;
  build: number;
  /** The terminal's own "Algo Trading" switch: off, it refuses every order the app sends. */
  algo_trading: boolean;
  api_allowed: boolean;
  account_login: number;
  account_server: string;
  account_trading: boolean;
  account_expert: boolean;
}

/** A MetaTrader terminal installed on (or running on) this PC. */
export interface TerminalCandidate {
  exe: string;
  folder: string;
  name: string;
  broker: string;
  running: boolean;
  pid: number | null;
  last_used: number;
}

export interface TerminalStatus {
  /** The market in use: "mt5" (a MetaTrader terminal) or "mock" (made-up prices). */
  broker: string;
  /** What the settings ask for: "auto" (MetaTrader when there is one), "mt5" or "mock". */
  mode: string;
  info: TerminalInfo;
  window: { found: boolean; hidden: boolean | null; minimized: boolean; hide_preference: boolean };
  /** The MetaTrader terminals installed on this PC (also while the app is on made-up prices). */
  terminals: TerminalCandidate[];
  /** The app is on made-up prices only because no terminal was ready at the start, and one is open now. */
  can_connect: boolean;
  chosen: string | null;
  /** May the app send orders to the broker (by the settings file, or by the switch in the app)? */
  orders: { allowed: boolean; by_settings: boolean };
  app: { packaged: boolean; can_quit: boolean; version: string };
}

export interface DataStat {
  symbol: string;
  timeframe: string;
  count: number;
  oldest: number | null;
  newest: number | null;
}

export interface ReplayState {
  symbol: string;
  timeframe: Timeframe;
  playing: boolean;
  index: number;
  total: number;
  speed: number;
  cursor_time: number;
  /** First and last bar of the loaded window (0 when it is empty). */
  first_time: number;
  last_time: number;
}

export interface BacktestMetrics {
  initial_balance: number;
  final_balance: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  win_rate: number;
  trades: number;
  profit_factor: number;
}

export interface BacktestTrade {
  entry_time: number;
  exit_time: number;
  side: "BUY" | "SELL";
  entry_price: number;
  exit_price: number;
  volume: number;
  pnl: number;
  /** "sl", "tp", "manual", or "session" / "rewind" for a position closed when its replay ended or was rewound. */
  reason: string;
  /** The paper position this trade closed. */
  ticket: number;
  /** The instrument: a profile's history spans every symbol it was used on. */
  symbol: string;
}

/** The paper account as of the replay cursor. */
export interface ReplayAccount {
  initial_balance: number;
  /** Initial balance plus the profit of the trades closed so far. */
  balance: number;
  /** Balance plus the floating profit of the open positions. */
  equity: number;
  realized: number;
  unrealized: number;
  positions: Position[];
  metrics: BacktestMetrics;
  trades_total: number;
  /** Closed trades that made / lost money (the rest closed even). */
  wins: number;
  losses: number;
  /** The profile this account is (see ReplayProfile); empty for an account that is not kept. */
  profile_id: string;
  profile_name: string;
}

/** A paper-trading profile: a named paper account that keeps its balance and history for good. */
export interface ReplayProfile {
  id: string;
  name: string;
  initial_balance: number;
  balance: number;
  /** Balance minus what it began with, and as a percentage of it. */
  realized: number;
  return_pct: number;
  trades: number;
  wins: number;
  losses: number;
  open_positions: number;
  created_at: number;
  updated_at: number;
}

/** Every profile, and the one the replay trades on. */
export interface ReplayProfiles {
  active: string;
  profiles: ReplayProfile[];
}

/** How the last attempt to install an update ended (told once, by the version that started afterwards). */
export interface UpdateResult {
  version: string;
  ok: boolean;
  message: string;
}

/** Whether a newer release exists on GitHub, and how installing it is going (the backend: app/updater.py). */
export interface UpdateStatus {
  /** The program looks for updates by itself. */
  enabled: boolean;
  current: string;
  /** The newest release GitHub told about, newer or not; null before the first look. */
  latest: string | null;
  available: boolean;
  /** The user chose not to be told about the one that is available. */
  skipped: boolean;
  /** This copy can install the release by itself (it was set up by the installer, and the release has what it needs). */
  can_install: boolean;
  installable_here: boolean;
  /** The release page's text. */
  notes: string;
  /** The release page on GitHub. */
  page: string;
  published: string;
  /** Bytes of the installer. */
  size: number;
  /** Seconds since 1970 of the last look. */
  checked_at: number | null;
  error: string | null;
  phase: "idle" | "downloading" | "verifying" | "installing" | "failed";
  message: string;
  done: number;
  total: number;
  result: UpdateResult | null;
}

/** Everything that changed when the replay cursor moved. */
export interface ReplayUpdate {
  state: ReplayState;
  /** Bars the cursor revealed, oldest first (everything up to it after a start). */
  bars: Bar[];
  account: ReplayAccount;
  /** Trades closed by a stop or target while the cursor moved. */
  closed: BacktestTrade[];
  /** The cursor went backwards or the replay just started: `bars` replaces what is held. */
  reset: boolean;
}

export interface EquityPoint {
  time: number;
  value: number;
}

export interface ReplaySummary {
  net_profit: number;
  gross_profit: number;
  gross_loss: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  /** null while there is no losing trade. */
  profit_factor: number | null;
  avg_win: number;
  avg_loss: number;
  payoff_ratio: number | null;
  largest_win: number;
  largest_loss: number;
  avg_trade: number;
  /** Seconds a trade stayed open, on average. */
  avg_duration: number;
  max_win_streak: number;
  max_loss_streak: number;
  max_drawdown: number;
  max_drawdown_pct: number;
}

/** The replay's figures and what a broker's own report adds to them (the same for the replay and the live account). */
export interface PerformanceSummary extends ReplaySummary {
  /** Net profit over the largest drawdown; null without a drawdown. */
  recovery_factor: number | null;
  /** The mean of the trades' returns over their spread; null below three trades. */
  sharpe: number | null;
  long_trades: number;
  long_wins: number;
  short_trades: number;
  short_wins: number;
  avg_win_streak: number;
  avg_loss_streak: number;
  /** What the longest winning / losing streak made / lost. */
  max_win_streak_amount: number;
  max_loss_streak_amount: number;
  /** The winning streak that made the most / the losing streak that lost the most, and how many trades each had. */
  best_win_streak_amount: number;
  best_win_streak_amount_trades: number;
  worst_loss_streak_amount: number;
  worst_loss_streak_amount_trades: number;
  longest_duration: number;
  shortest_duration: number;
  /** Lots traded. */
  total_volume: number;
  /** What the closed trades cost (zero or negative). */
  commission: number;
  swap: number;
  fees: number;
  /** How far the balance stood below the money put in, at the most. */
  drawdown_absolute: number;
}

/** What the closed trades of one instrument made. */
export interface SymbolStats {
  symbol: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_profit: number;
  volume: number;
}

export interface ReplayReport {
  account: ReplayAccount;
  summary: PerformanceSummary;
  equity: EquityPoint[];
  trades: BacktestTrade[];
  symbols: SymbolStats[];
}

/** A position of the broker's account that is closed: its fills put together. `pnl` is after its costs. */
export interface ClosedTrade extends BacktestTrade {
  /** The price result alone, before the costs. */
  profit: number;
  commission: number;
  swap: number;
  fee: number;
  comment: string;
}

/** Money that moved without being trading. */
export interface AccountFlows {
  deposits: number;
  /** A positive number. */
  withdrawals: number;
  credit: number;
  bonus: number;
  corrections: number;
  /** Fees, interest, dividends and taxes booked to the account (negative: it paid). */
  charges: number;
  operations: number;
}

/** The live account's performance report, worked out from the broker's own history (see backend/app/performance.py). */
export interface AccountReport {
  account: AccountInfo;
  summary: PerformanceSummary;
  /** The account's level after each deal that moved it (deposits and withdrawals left out), then as it is now. */
  equity: EquityPoint[];
  /** The newest closed trades, oldest first. */
  trades: ClosedTrade[];
  trades_total: number;
  symbols: SymbolStats[];
  flows: AccountFlows;
  /** The level the curve starts from: the money first put in. */
  initial_balance: number;
  /** Net profit as a share of that; null when there is nothing to measure it by. */
  return_pct: number | null;
  open_profit: number;
  deals: number;
  first_time: number;
  last_time: number;
}

export interface IndicatorSpec {
  id: string;
  name: string;
  code: string;
  overlay: boolean;
  pane: number;
  params: Record<string, unknown>;
  /** A built-in's own parameters (`params` are what the user set them to); null for the user's own indicators. */
  defaults?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface IndicatorPlot {
  name: string;
  type: string;
  color: string | null;
  data: { time: number; value: number }[];
}

export interface IndicatorResult {
  id: string;
  name: string;
  overlay: boolean;
  pane: number;
  /** The parameters it was run with. */
  params?: Record<string, unknown>;
  plots: IndicatorPlot[];
  /** Shapes the indicator draws on the chart (see docs/DRAWINGS.md). */
  drawings?: Drawing[];
  error: string | null;
}
