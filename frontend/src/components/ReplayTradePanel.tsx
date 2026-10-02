// The Trade tab while a replay is running: the paper-trading profile in use, its account at a
// glance, the order ticket, the open positions and the latest closed trades. The full list and
// the performance figures are in the report (see ReplayReport).

import { useState, type ReactNode } from "react";
import { replayApi } from "../lib/api";
import { formatLots, formatMoney, formatShortTime } from "../lib/format";
import type { BacktestTrade, ReplayAccount } from "../lib/types";
import { OrderTicket, type OrderForm } from "./OrderTicket";
import { ReportIcon } from "./Icons";

interface Props {
  symbol: string | null;
  /** Close of the bar under the replay cursor: every paper order fills at it. */
  price: number | null;
  digits: number;
  account: ReplayAccount | null;
  trades: BacktestTrade[];
  /** Show clock times (intraday bars) or just dates. */
  intraday: boolean;
  form: OrderForm;
  onFormChange: (form: OrderForm) => void;
  /** The profile menu: which paper account this is, and making / deleting / starting over profiles. */
  profileMenu: ReactNode;
  onRefresh: () => void;
  onClosePosition: (ticket: number) => void;
  onOpenReport: () => void;
}

/** How many closed trades the panel lists; the report has them all. */
const LISTED = 6;

const tone = (v: number) => (v > 0 ? "pos" : v < 0 ? "neg" : "");

const REASON: Record<string, string> = {
  sl: "Stop",
  tp: "Target",
  manual: "Closed",
  session: "Replay ended",
  rewind: "Rewound",
};

export function ReplayTradePanel({
  symbol,
  price,
  digits,
  account,
  trades,
  intraday,
  form,
  onFormChange,
  profileMenu,
  onRefresh,
  onClosePosition,
  onOpenReport,
}: Props) {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (side: "BUY" | "SELL") => {
    if (!symbol) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await replayApi.placeOrder({
        symbol,
        side,
        volume: form.volume,
        sl: form.sl ? Number(form.sl) : null,
        tp: form.tp ? Number(form.tp) : null,
      });
      setMessage(
        result.ok
          ? `Filled ${side} ${formatLots(form.volume)} @ ${result.price.toFixed(digits)}`
          : `Error: ${result.error}`,
      );
      onRefresh();
    } catch (err) {
      setMessage(`Error: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const positions = account?.positions ?? [];
  const metrics = account?.metrics;
  const recent = trades.slice(-LISTED).reverse();

  return (
    <div className="replay-trade">
      <div className="rtp-profile">
        <span className="rtp-tag">
          <i />
          Replay
        </span>
        {profileMenu}
      </div>

      {account && (
        <div className="rtp-account">
          <div className="rtp-cell">
            <span>Equity</span>
            <b>{formatMoney(account.equity)}</b>
            {metrics && (
              <small className={tone(metrics.total_return_pct)}>
                {metrics.total_return_pct > 0 ? "+" : metrics.total_return_pct < 0 ? "−" : ""}
                {Math.abs(metrics.total_return_pct).toFixed(2)}%
              </small>
            )}
          </div>
          <div className="rtp-cell">
            <span>Balance</span>
            <b>{formatMoney(account.balance)}</b>
            <small>from {formatMoney(account.initial_balance)}</small>
          </div>
          <div className="rtp-cell">
            <span>Open P&amp;L</span>
            <b className={tone(account.unrealized)}>{formatMoney(account.unrealized, "", true)}</b>
          </div>
          <div className="rtp-cell">
            <span>Closed P&amp;L</span>
            <b className={tone(account.realized)}>{formatMoney(account.realized, "", true)}</b>
          </div>
        </div>
      )}

      <div className="tv-quote">
        {price != null ? (
          <div className="tv-quote-side last">
            <span>Replay price · every order fills at it</span>
            <b>{price.toFixed(digits)}</b>
          </div>
        ) : (
          <span className="tv-quote-none">No price</span>
        )}
      </div>

      <OrderTicket
        form={form}
        onFormChange={onFormChange}
        disabled={!symbol}
        busy={busy}
        message={message}
        onSubmit={submit}
      />

      <div className="positions">
        <h3>Positions ({positions.length})</h3>
        {positions.map((p) => (
          <div key={p.ticket} className="position">
            <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
            <span className="position-main">
              <b>{formatLots(p.volume)} lots</b>
              <small>
                @ {p.price_open.toFixed(digits)}
                {p.sl > 0 ? ` · SL ${p.sl.toFixed(digits)}` : ""}
                {p.tp > 0 ? ` · TP ${p.tp.toFixed(digits)}` : ""}
              </small>
            </span>
            <span className={`position-pl ${tone(p.profit)}`}>{formatMoney(p.profit, "", true)}</span>
            <button onClick={() => onClosePosition(p.ticket)} title="Close at the replay price">
              Close
            </button>
          </div>
        ))}
        {positions.length === 0 && <p className="message">No open positions.</p>}
      </div>

      <div className="positions">
        <h3 className="rtp-head">
          <span>History ({trades.length})</span>
          <button className="rtp-link" onClick={onOpenReport} title="Open the performance report">
            <ReportIcon size={16} />
            Report
          </button>
        </h3>
        {recent.map((t) => (
          <div
            key={`${t.ticket}-${t.exit_time}`}
            className="position"
            title={`Opened ${formatShortTime(t.entry_time, intraday)} · closed ${formatShortTime(t.exit_time, intraday)}`}
          >
            <span className={t.side === "BUY" ? "side buy" : "side sell"}>{t.side}</span>
            <span className="position-main">
              <b>
                {formatLots(t.volume)} lots{t.symbol ? ` ${t.symbol}` : ""}
              </b>
              <small>
                {t.entry_price.toFixed(digits)} → {t.exit_price.toFixed(digits)}
              </small>
            </span>
            <span className={`position-pl ${tone(t.pnl)}`}>{formatMoney(t.pnl, "", true)}</span>
            <span className={`rtp-reason ${t.reason}`} title={`Closed by ${REASON[t.reason]?.toLowerCase() ?? t.reason}`}>
              {REASON[t.reason] ?? t.reason}
            </span>
          </div>
        ))}
        {trades.length === 0 && <p className="message">No closed trades yet.</p>}
        {trades.length > LISTED && (
          <button className="rtp-more" onClick={onOpenReport}>
            All {trades.length} trades in the report
          </button>
        )}
      </div>
    </div>
  );
}
