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

export interface ReplayReport {
  account: ReplayAccount;
  summary: ReplaySummary;
  equity: EquityPoint[];
  trades: BacktestTrade[];
}

export interface IndicatorSpec {
  id: string;
  name: string;
  code: string;
  overlay: boolean;
  pane: number;
  params: Record<string, unknown>;
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
  plots: IndicatorPlot[];
  /** Shapes the indicator draws on the chart (see docs/DRAWINGS.md). */
  drawings?: Drawing[];
  error: string | null;
}
