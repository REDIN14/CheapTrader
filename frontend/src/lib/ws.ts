// The live stream from the server: every tick of the symbol being watched, and the
// account and positions as they change (see backend app/api/ws.py).
//
// It reconnects by itself, quickly at first (a restarted server is back within a
// second or two), and asks for the symbol again every time it does.

import { postNotice, type Notice } from "./bus";
import type { AccountInfo, PendingOrder, Position, Tick } from "./types";

export interface StreamState {
  positions: Position[];
  account: AccountInfo;
  /** The limit / stop orders that wait. */
  orders: PendingOrder[];
}

export interface StreamHandlers {
  /** The ticks the terminal received since the previous message, oldest first. */
  onTicks: (symbol: string, ticks: Tick[]) => void;
  /** The account or a position changed (whoever caused it). */
  onState: (state: StreamState) => void;
  /** The connection came up (true) or went down (false). */
  onStatus?: (connected: boolean) => void;
  /** The server's own feed from MetaTrader is "up", "slow" (late, but coming), "restarting" or "down". */
  onFeed?: (status: string) => void;
}

/** Waits (ms) before each successive attempt to reconnect; the last one repeats. */
const RECONNECT_MS = [250, 500, 1000, 2000];

export class StreamClient {
  private ws: WebSocket | null = null;
  private symbol: string | null = null;
  private handlers: StreamHandlers | null = null;
  private reconnectTimer: number | null = null;
  private attempts = 0;
  private closed = false;

  constructor(private readonly url: string) {}

  connect(symbol: string, handlers: StreamHandlers): void {
    this.symbol = symbol;
    this.handlers = handlers;
    this.closed = false;
    this.open();
  }

  private open(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const base = this.url || `${proto}://${location.host}`;
    const ws = new WebSocket(`${base}/ws/stream`);
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      if (this.symbol) ws.send(JSON.stringify({ type: "subscribe", symbol: this.symbol }));
      this.handlers?.onStatus?.(true);
      // whatever was announced while the connection was down is lost: whoever cares can look again
      postNotice({ type: "stream-open" });
    };

    ws.onmessage = (event) => {
      const handlers = this.handlers;
      if (!handlers) return;
      let msg: {
        type?: string;
        symbol?: string;
        data?: Tick[];
        positions?: Position[];
        account?: AccountInfo;
        orders?: PendingOrder[];
        status?: string;
      };
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === "ticks" && msg.symbol && msg.data) {
        handlers.onTicks(msg.symbol, msg.data);
      } else if (msg.type === "state" && msg.positions && msg.account) {
        handlers.onState({ positions: msg.positions, account: msg.account, orders: msg.orders ?? [] });
      } else if (msg.type === "feed" && msg.status) {
        handlers.onFeed?.(msg.status);
      } else if (msg.type === "drawings") {
        postNotice(msg as Notice);
      }
    };

    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.handlers?.onStatus?.(false);
      if (this.closed) return;
      const wait = RECONNECT_MS[Math.min(this.attempts, RECONNECT_MS.length - 1)];
      this.attempts++;
      this.reconnectTimer = window.setTimeout(() => this.open(), wait);
    };

    ws.onerror = () => ws.close();
  }

  subscribe(symbol: string): void {
    this.symbol = symbol;
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "subscribe", symbol }));
    }
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onclose = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.close();
    }
  }
}
