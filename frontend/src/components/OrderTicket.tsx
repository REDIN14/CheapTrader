// The order form shared by the live ticket and the replay paper ticket: lot size, optional stop loss /
// take profit, and the Sell / Buy buttons. The live ticket can also leave an order waiting at a price
// (a limit order, or a stop order when the price is on the other side of the market).
//
// Both tickets read and write the same values, as do the chart's own Sell / Buy buttons and the dashed
// draft lines drawn on the chart.

import { kindTitle, pendingKind } from "../lib/orders";

export interface OrderForm {
  volume: number;
  sl: string;
  tp: string;
  /** "market" trades at once; "limit" waits at `price`. (Older saved forms have neither.) */
  type?: "market" | "limit";
  price?: string;
}

interface Props {
  form: OrderForm;
  onFormChange: (form: OrderForm) => void;
  /** No symbol is open, so nothing can be traded. */
  disabled: boolean;
  busy: boolean;
  message: string | null;
  onSubmit: (side: "BUY" | "SELL") => void;
  /** Offer orders that wait at a price (live trading; a replay fills everything at the bar close). */
  pending?: {
    bid: number | null;
    ask: number | null;
    onSubmit: (side: "BUY" | "SELL") => void;
  };
}

export function OrderTicket({ form, onFormChange, disabled, busy, message, onSubmit, pending }: Props) {
  const invalidVolume = !(form.volume > 0);
  const blocked = busy || disabled || invalidVolume;
  const waiting = !!pending && form.type === "limit";

  const price = Number(form.price);
  const havePrice = !!form.price && Number.isFinite(price) && price > 0;
  /** What the typed price makes of an order on this side: "Buy limit", or "Buy stop" on the other side of the market. */
  const waitingLabel = (side: "BUY" | "SELL") => {
    const kind = havePrice && pending && pending.bid != null && pending.ask != null ? pendingKind(side, price, pending.bid, pending.ask) : null;
    return kind ? kindTitle(kind) : `${side === "BUY" ? "Buy" : "Sell"} limit`;
  };

  return (
    <div className="order-form">
      {pending && (
        <div className="seg" role="tablist" aria-label="Order type">
          <button
            role="tab"
            aria-selected={!waiting}
            className={!waiting ? "on" : undefined}
            onClick={() => onFormChange({ ...form, type: "market" })}
          >
            Market
          </button>
          <button
            role="tab"
            aria-selected={waiting}
            className={waiting ? "on" : undefined}
            onClick={() => onFormChange({ ...form, type: "limit" })}
          >
            Limit
          </button>
        </div>
      )}
      <label>
        Volume (lots)
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={form.volume}
          onChange={(e) => onFormChange({ ...form, volume: Number(e.target.value) })}
        />
      </label>
      {waiting && (
        <label>
          Price it waits for
          <input
            type="number"
            step="any"
            placeholder="Where the order waits"
            value={form.price ?? ""}
            onChange={(e) => onFormChange({ ...form, price: e.target.value })}
          />
        </label>
      )}
      <label>
        Stop loss
        <input
          type="number"
          step="0.00001"
          placeholder="None"
          value={form.sl}
          onChange={(e) => onFormChange({ ...form, sl: e.target.value })}
        />
      </label>
      <label>
        Take profit
        <input
          type="number"
          step="0.00001"
          placeholder="None"
          value={form.tp}
          onChange={(e) => onFormChange({ ...form, tp: e.target.value })}
        />
      </label>
      {waiting && pending ? (
        <>
          <div className="tv-order-btns">
            <button className="sell" disabled={blocked || !havePrice} onClick={() => pending.onSubmit("SELL")}>
              {waitingLabel("SELL")}
            </button>
            <button className="buy" disabled={blocked || !havePrice} onClick={() => pending.onSubmit("BUY")}>
              {waitingLabel("BUY")}
            </button>
          </div>
          <p className="message">
            The order waits until the market reaches the price. A buy below the market (or a sell above it) is a
            limit order; on the other side it is a stop order.
          </p>
        </>
      ) : (
        <div className="tv-order-btns">
          <button className="sell" disabled={blocked} onClick={() => onSubmit("SELL")}>
            Sell
          </button>
          <button className="buy" disabled={blocked} onClick={() => onSubmit("BUY")}>
            Buy
          </button>
        </div>
      )}
      {invalidVolume && <p className="message warn">Enter a lot size above zero.</p>}
      {message && <p className="message">{message}</p>}
    </div>
  );
}
