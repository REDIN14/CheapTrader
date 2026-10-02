import { useState } from "react";
import { api } from "../lib/api";
import { formatLots, formatMoney } from "../lib/format";
import { kindTitle } from "../lib/orders";
import type { PendingOrder, Position, Tick } from "../lib/types";
import { OrderTicket, type OrderForm } from "./OrderTicket";

interface Props {
  symbol: string | null;
  tick: Tick | null;
  positions: Position[];
  /** Positions with a close on its way to the broker. */
  closing?: ReadonlySet<number>;
  /** The limit / stop orders that wait. */
  orders: PendingOrder[];
  /** Orders with a cancel on its way to the broker. */
  cancelling?: ReadonlySet<number>;
  form: OrderForm;
  digits?: number;
  onFormChange: (form: OrderForm) => void;
  onRefresh: () => void;
  onClosePosition: (ticket: number) => void;
  /** Leave an order waiting at the price in the form. */
  onSubmitPending: (side: "BUY" | "SELL") => void;
  onCancelOrder: (ticket: number) => void;
}

export function OrderPanel({
  symbol,
  tick,
  positions,
  closing,
  orders,
  cancelling,
  form,
  digits = 5,
  onFormChange,
  onRefresh,
  onClosePosition,
  onSubmitPending,
  onCancelOrder,
}: Props) {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (side: "BUY" | "SELL") => {
    if (!symbol) return;
    setBusy(true);
    setMessage(null);
    const started = performance.now();
    try {
      const result = await api.placeOrder({
        symbol,
        side,
        volume: form.volume,
        sl: form.sl ? Number(form.sl) : null,
        tp: form.tp ? Number(form.tp) : null,
      });
      setMessage(
        result.ok
          ? `Filled ${side} ${formatLots(form.volume)} @ ${result.price} · ${Math.round(performance.now() - started)} ms`
          : `Error: ${result.error}`,
      );
      onRefresh();
    } catch (err) {
      setMessage(`Error: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="order-panel">
      <div className="tv-quote">
        {tick ? (
          <>
            <div className="tv-quote-side sell">
              <span>Sell</span>
              <b>{tick.bid.toFixed(digits)}</b>
            </div>
            <div className="tv-quote-side buy">
              <span>Buy</span>
              <b>{tick.ask.toFixed(digits)}</b>
            </div>
          </>
        ) : (
          <span className="tv-quote-none">No quote</span>
        )}
      </div>

      <OrderTicket
        form={form}
        onFormChange={onFormChange}
        disabled={!symbol}
        busy={busy}
        message={message}
        onSubmit={submit}
        pending={{ bid: tick?.bid ?? null, ask: tick?.ask ?? null, onSubmit: onSubmitPending }}
      />

      <div className="positions">
        <h3>Positions ({positions.length})</h3>
        {positions.map((p) => (
          <div key={p.ticket} className="position">
            <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
            <span className="position-main">
              <b title={p.symbol}>{p.symbol}</b>
              <small>
                {formatLots(p.volume)} lots @ {p.price_open}
              </small>
            </span>
            <span className={p.profit >= 0 ? "position-pl pos" : "position-pl neg"}>
              {formatMoney(p.profit, "", true)}
            </span>
            <button disabled={closing?.has(p.ticket)} onClick={() => onClosePosition(p.ticket)}>
              {closing?.has(p.ticket) ? "Closing…" : "Close"}
            </button>
          </div>
        ))}
        {positions.length === 0 && <p className="message">No open positions.</p>}
      </div>

      <div className="positions">
        <h3>Pending orders ({orders.length})</h3>
        {orders.map((o) => (
          <div key={o.ticket} className="position order">
            <span className={o.side === "BUY" ? "side buy" : "side sell"}>{o.side}</span>
            <span className="position-main">
              <b title={o.symbol}>
                {kindTitle(o.order_type)} · {o.symbol}
              </b>
              <small>
                {formatLots(o.volume)} lots @ {o.price.toFixed(digits)}
                {o.sl > 0 ? ` · SL ${o.sl.toFixed(digits)}` : ""}
                {o.tp > 0 ? ` · TP ${o.tp.toFixed(digits)}` : ""}
              </small>
            </span>
            <button
              disabled={cancelling?.has(o.ticket)}
              title="Take this order back"
              onClick={() => onCancelOrder(o.ticket)}
            >
              {cancelling?.has(o.ticket) ? "Cancelling…" : "Cancel"}
            </button>
          </div>
        ))}
        {orders.length === 0 && <p className="message">No pending orders.</p>}
      </div>
    </section>
  );
}
