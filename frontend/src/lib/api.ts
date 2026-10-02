// REST API client.

import type { Drawing, DrawingPoint, DrawingStyle } from "./drawings";
import type {
  AccountInfo,
  PendingOrder,
  BacktestTrade,
  Bar,
  DataStat,
  DocInfo,
  DocPage,
  Health,
  IndicatorResult,
  IndicatorSpec,
  OrderRequest,
  OrderResult,
  Position,
  ReplayAccount,
  ReplayProfiles,
  ReplayReport,
  ReplayState,
  ReplayUpdate,
  Symbol,
  TerminalStatus,
  Tick,
  Timeframe,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

/** A request the backend answered with an error. `status` is the HTTP code. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * The text to show for a failed response. The backend explains itself in a JSON
 * `{"detail": ...}` body; that sentence is what the user should read, not the raw
 * JSON with an HTTP status in front of it.
 */
async function describeFailure(res: Response): Promise<string> {
  const body = await res.text();
  try {
    const detail = JSON.parse(body)?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
      // FastAPI validation errors: [{loc, msg, type}, ...]
      return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}${body ? `: ${body}` : ""}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // A refused connection surfaces as an opaque "Failed to fetch".
    throw new Error("Cannot reach the CheapTrader backend. Is it running? (uvicorn app.main:app --port 8000)");
  }
  if (!res.ok) throw new ApiError(await describeFailure(res), res.status);
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  // The endpoint caps a listing at 500 unless told otherwise, which would hide
  // part of a large broker's catalogue (indices, stocks, crypto…).
  symbols: (query?: string) =>
    request<Symbol[]>(
      `/api/symbols?limit=5000${query ? `&query=${encodeURIComponent(query)}` : ""}`,
    ),

  bars: (symbol: string, timeframe: Timeframe, count = 500) =>
    request<Bar[]>(`/api/bars?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&count=${count}`),

  tick: (symbol: string) => request<Tick>(`/api/tick?symbol=${encodeURIComponent(symbol)}`),

  dataStats: () => request<DataStat[]>("/api/data/stats"),

  account: () => request<AccountInfo>("/api/account"),

  positions: (symbol?: string) =>
    request<Position[]>(`/api/positions${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),

  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/orders", { method: "POST", body: JSON.stringify(order) }),

  modifyPosition: (ticket: number, sl?: number, tp?: number) =>
    request<OrderResult>("/api/positions", {
      method: "PATCH",
      body: JSON.stringify({ ticket, sl, tp }),
    }),

  closePosition: (ticket: number) =>
    request<OrderResult>(`/api/positions/${ticket}`, { method: "DELETE" }),

  // Pending (limit / stop) orders: the ones that wait for a price.
  orders: (symbol?: string) =>
    request<PendingOrder[]>(`/api/orders${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`),

  modifyOrder: (ticket: number, change: { price?: number; sl?: number; tp?: number }) =>
    request<OrderResult>("/api/orders", { method: "PATCH", body: JSON.stringify({ ticket, ...change }) }),

  cancelOrder: (ticket: number) => request<OrderResult>(`/api/orders/${ticket}`, { method: "DELETE" }),

  /** One instrument as the broker describes it now (its tick value moves with the exchange rates). */
  symbol: (name: string) => request<Symbol>(`/api/symbols/${encodeURIComponent(name)}`),

  // The MetaTrader terminal: what it is, whether it takes orders, its window.
  terminal: () => request<TerminalStatus>("/api/terminal"),

  hideTerminal: (hidden: boolean) =>
    request<TerminalStatus>("/api/terminal/window", { method: "POST", body: JSON.stringify({ hidden }) }),

  chooseTerminal: (path: string | null) =>
    request<TerminalStatus>("/api/terminal/choose", { method: "POST", body: JSON.stringify({ path }) }),

  /** Switch from made-up prices to the MetaTrader terminal that is open now. Rejects, in words, when it cannot. */
  connectTerminal: () => request<TerminalStatus>("/api/terminal/connect", { method: "POST" }),

  /** Let the app send orders to the broker, or stop it. */
  setOrders: (enabled: boolean) =>
    request<TerminalStatus>("/api/app/orders", { method: "POST", body: JSON.stringify({ enabled }) }),

  quit: () => request<{ ok: boolean }>("/api/app/quit", { method: "POST" }),
};

const sym = (symbol: string) => encodeURIComponent(symbol);

/** Which drawings a bulk removal takes: the ones not locked, only the locked ones, or all. */
export type LockedScope = "exclude" | "only" | "include";

export interface ClearResult {
  ok: boolean;
  removed: number;
  /** Locked drawings that were left alone. */
  kept_locked: number;
  /** Per symbol, for a removal across all symbols. */
  symbols?: Record<string, number>;
}

/** The shapes drawn on a symbol's chart, kept by the server (so they survive a restart and can come from scripts). */
export const drawingApi = {
  list: (symbol: string) => request<Drawing[]>(`/api/drawings?symbol=${sym(symbol)}`),

  add: (symbol: string, drawing: Drawing) =>
    request<Drawing>(`/api/drawings?symbol=${sym(symbol)}`, { method: "POST", body: JSON.stringify(drawing) }),

  change: (symbol: string, id: string, change: { points?: DrawingPoint[]; style?: DrawingStyle; locked?: boolean }) =>
    request<Drawing>(`/api/drawings/${encodeURIComponent(id)}?symbol=${sym(symbol)}`, {
      method: "PATCH",
      body: JSON.stringify(change),
    }),

  remove: (symbol: string, id: string) =>
    request<{ ok: boolean }>(`/api/drawings/${encodeURIComponent(id)}?symbol=${sym(symbol)}`, { method: "DELETE" }),

  clear: (symbol: string, locked: LockedScope = "exclude") =>
    request<ClearResult>(`/api/drawings?symbol=${sym(symbol)}&locked=${locked}`, { method: "DELETE" }),

  clearAll: (locked: LockedScope = "exclude") =>
    request<ClearResult>(`/api/drawings?all_symbols=true&locked=${locked}`, { method: "DELETE" }),

  /** How many drawings each symbol has, and how many of them are locked. */
  summary: () => request<Record<string, { total: number; locked: number }>>("/api/drawings/summary"),
};

/** The documentation, read in the app. */
export const docsApi = {
  list: () => request<DocInfo[]>("/api/docs"),
  read: (id: string) => request<DocPage>(`/api/docs/${encodeURIComponent(id)}`),
};

export const replayApi = {
  /**
   * Start a replay on the bar nearest `time` (chart time, epoch seconds). The
   * reply carries the bars up to that bar, ready to draw.
   */
  start: (symbol: string, timeframe: Timeframe, time: number, lookback = 1500) => {
    const params = new URLSearchParams({
      symbol,
      timeframe,
      time: String(Math.round(time)),
      lookback: String(lookback),
    });
    return request<ReplayUpdate>(`/api/replay/start?${params.toString()}`, { method: "POST" });
  },

  /** Move the cursor by `delta` bars; the reply holds the bars revealed and the account. */
  advance: (delta = 1) =>
    request<ReplayUpdate>(`/api/replay/advance?delta=${delta}`, { method: "POST" }),

  state: () => request<ReplayState>("/api/replay/state"),

  bars: () => request<Bar[]>("/api/replay/bars"),

  /** Balance, equity, open positions and headline metrics at the cursor. */
  account: () => request<ReplayAccount>("/api/replay/account"),

  /** The performance report: summary figures, equity curve, every closed trade. */
  report: (points = 400) => request<ReplayReport>(`/api/replay/report?points=${points}`),

  // Paper trading inside replay.
  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/replay/orders", { method: "POST", body: JSON.stringify(order) }),

  modifyPosition: (ticket: number, sl?: number, tp?: number) =>
    request<OrderResult>("/api/replay/positions", {
      method: "PATCH",
      body: JSON.stringify({ ticket, sl, tp }),
    }),

  closePosition: (ticket: number) =>
    request<OrderResult>(`/api/replay/positions/${ticket}`, { method: "DELETE" }),

  trades: () => request<BacktestTrade[]>("/api/replay/trades"),

  /** Leave the replay: what is still open is closed at the price under the cursor and kept in the profile. */
  stop: () => request<ReplayProfiles>("/api/replay/stop", { method: "POST" }),

  // Paper-trading profiles: every reply is the whole list.
  profiles: () => request<ReplayProfiles>("/api/replay/profiles"),

  createProfile: (name: string, balance: number, activate = true) =>
    request<ReplayProfiles>("/api/replay/profiles", {
      method: "POST",
      body: JSON.stringify({ name, balance, activate }),
    }),

  renameProfile: (id: string, name: string) =>
    request<ReplayProfiles>(`/api/replay/profiles/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  selectProfile: (id: string) =>
    request<ReplayProfiles>(`/api/replay/profiles/${encodeURIComponent(id)}/select`, { method: "POST" }),

  /** Begin the profile again: no history, the balance it began with, or `balance`. */
  resetProfile: (id: string, balance?: number) =>
    request<ReplayProfiles>(`/api/replay/profiles/${encodeURIComponent(id)}/reset`, {
      method: "POST",
      body: JSON.stringify(balance === undefined ? {} : { balance }),
    }),

  deleteProfile: (id: string) =>
    request<ReplayProfiles>(`/api/replay/profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export const indicatorApi = {
  list: () => request<IndicatorSpec[]>("/api/indicators"),

  get: (id: string) => request<IndicatorSpec>(`/api/indicators/${encodeURIComponent(id)}`),

  create: (spec: Partial<IndicatorSpec>) =>
    request<IndicatorSpec>("/api/indicators", { method: "POST", body: JSON.stringify(spec) }),

  update: (id: string, spec: Partial<IndicatorSpec>) =>
    request<IndicatorSpec>(`/api/indicators/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(spec),
    }),

  remove: (id: string) =>
    request<{ ok: boolean }>(`/api/indicators/${encodeURIComponent(id)}`, { method: "DELETE" }),

  run: (id: string, symbol: string, timeframe: Timeframe, count = 500) =>
    request<IndicatorResult>(
      `/api/indicators/${encodeURIComponent(id)}/run?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&count=${count}`,
      { method: "POST" },
    ),
};
