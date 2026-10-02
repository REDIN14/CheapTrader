// The replay's performance report, in the bottom drawer TradingView keeps for its
// paper-trading account:
//
//   Overview — the headline figures and the equity curve;
//   Trades   — every closed trade, newest first, with the running total.
//
// It reads the paper account as it is now (so it stays live while the replay
// plays) and the closed trades and curve from the backend's report.

import { useMemo, useState } from "react";
import { formatDuration, formatInt, formatLots, formatMoney, formatShortTime } from "../lib/format";
import type { ReplayAccount, ReplayReport as Report } from "../lib/types";
import { CloseIcon } from "./Icons";
import { EquityChart } from "./EquityChart";

interface Props {
  report: Report | null;
  /** The account as of the cursor; fresher than the report's own copy. */
  account: ReplayAccount | null;
  /** Epoch second of the replay cursor. */
  cursorTime: number;
  intraday: boolean;
  digits: number;
  title: string;
  onClose: () => void;
}

type Tab = "overview" | "trades";

const tone = (v: number) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const REASON: Record<string, string> = {
  sl: "Stop loss",
  tp: "Take profit",
  manual: "Closed by hand",
  session: "Replay ended",
  rewind: "Rewound",
};

/**
 * One headline figure. `sub` is the small line under it (hidden when the drawer is narrow,
 * so the card's tooltip carries it); `hint` spells it out where `sub` is short for room.
 */
function Kpi({ label, value, sub, hint, cls }: { label: string; value: string; sub?: string; hint?: string; cls?: string }) {
  return (
    <div className="rp-kpi" title={sub ? `${label}: ${hint ?? sub}` : undefined}>
      <span>{label}</span>
      <b className={cls}>{value}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

export function ReplayReport({ report, account, cursorTime, intraday, digits, title, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const s = report?.summary;
  const trades = report?.trades ?? [];

  // The curve from the report, brought up to the cursor with the account as it is now.
  const curve = useMemo(() => {
    const pts = report?.equity ?? [];
    if (!account || !pts.length) return pts;
    const last = pts[pts.length - 1];
    return cursorTime > last.time ? [...pts, { time: cursorTime, value: account.equity }] : pts;
  }, [report?.equity, account, cursorTime]);

  // Running total of the closed trades, oldest first, then shown newest first.
  const rows = useMemo(() => {
    let total = 0;
    return trades
      .map((t, i) => {
        total += t.pnl;
        return { t, n: i + 1, total };
      })
      .reverse();
  }, [trades]);

  return (
    <section className="rp-report" aria-label="Replay report">
      <header className="rp-report-head">
        <div className="tv-tabs">
          <button className={tab === "overview" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("overview")}>
            Overview
          </button>
          <button className={tab === "trades" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("trades")}>
            Trades{trades.length ? ` (${trades.length})` : ""}
          </button>
        </div>
        <span className="rp-report-title">{title}</span>
        <button className="tv-icon-btn" onClick={onClose} title="Hide the report">
          <CloseIcon size={20} />
        </button>
      </header>

      {tab === "overview" ? (
        <div className="rp-report-body overview">
          <div className="rp-kpis">
            <Kpi
              label="Net profit"
              value={formatMoney(s?.net_profit ?? 0, "", true)}
              cls={tone(s?.net_profit ?? 0)}
              sub={account ? `${formatMoney(account.metrics.total_return_pct, "", true)}% incl. open` : undefined}
            />
            <Kpi
              label="Profit factor"
              value={s ? (s.profit_factor != null ? s.profit_factor.toFixed(2) : s.wins > 0 ? "∞" : "—") : "—"}
              sub={s ? `${formatMoney(s.gross_profit)} / ${formatMoney(s.gross_loss)}` : undefined}
              hint={s ? `Gross profit ${formatMoney(s.gross_profit)} · gross loss ${formatMoney(s.gross_loss)}` : undefined}
            />
            <Kpi
              label="Win rate"
              value={s && s.trades ? `${s.win_rate.toFixed(1)}%` : "—"}
              sub={s ? `${s.wins} won · ${s.losses} lost${s.trades - s.wins - s.losses ? ` · ${s.trades - s.wins - s.losses} even` : ""}` : undefined}
            />
            <Kpi label="Trades" value={s ? formatInt(s.trades) : "0"} sub={s && s.trades ? `streaks +${s.max_win_streak} / −${s.max_loss_streak}` : undefined} />
            <Kpi
              label="Max drawdown"
              value={s && s.max_drawdown > 0 ? `−${formatMoney(s.max_drawdown)}` : "0.00"}
              cls={s && s.max_drawdown > 0 ? "neg" : undefined}
              sub={s ? `${s.max_drawdown_pct.toFixed(2)}% of the peak` : undefined}
            />
            <Kpi label="Average win" value={s && s.wins ? formatMoney(s.avg_win, "", true) : "—"} cls={s && s.wins ? "pos" : undefined} />
            <Kpi label="Average loss" value={s && s.losses ? formatMoney(-s.avg_loss, "", true) : "—"} cls={s && s.losses ? "neg" : undefined} sub={s?.payoff_ratio != null ? `win / loss ${s.payoff_ratio.toFixed(2)}` : undefined} />
            <Kpi label="Best trade" value={s && s.wins ? formatMoney(s.largest_win, "", true) : "—"} cls={s && s.wins ? "pos" : undefined} />
            <Kpi label="Worst trade" value={s && s.losses ? formatMoney(s.largest_loss, "", true) : "—"} cls={s && s.losses ? "neg" : undefined} />
            <Kpi label="Average trade" value={s && s.trades ? formatMoney(s.avg_trade, "", true) : "—"} cls={s && s.trades ? tone(s.avg_trade) : undefined} sub={s && s.trades ? `held ${formatDuration(s.avg_duration)}` : undefined} />
          </div>

          <div className="rp-curve">
            <div className="rp-curve-head">
              <span>Equity</span>
              {account && (
                <b className={tone(account.equity - account.initial_balance)}>
                  {formatMoney(account.equity)}
                </b>
              )}
            </div>
            <EquityChart points={curve} baseline={account?.initial_balance ?? 0} intraday={intraday} />
          </div>
        </div>
      ) : (
        <div className="rp-report-body trades">
          {rows.length === 0 ? (
            <p className="rp-empty">
              No closed trades yet. Open a position and close it — or let its stop or target do it — and it is listed here.
            </p>
          ) : (
            <table className="rp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="num">Lots</th>
                  <th>Opened</th>
                  <th className="num">Entry</th>
                  <th>Closed</th>
                  <th className="num">Exit</th>
                  <th className="num">Held</th>
                  <th className="num">P&amp;L</th>
                  <th className="num">Total</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ t, n, total }) => (
                  <tr key={`${t.ticket}-${t.exit_time}-${n}`}>
                    <td className="muted">{n}</td>
                    <td>{t.symbol || "—"}</td>
                    <td className={t.side === "BUY" ? "side buy" : "side sell"}>{t.side}</td>
                    <td className="num">{formatLots(t.volume)}</td>
                    <td>{formatShortTime(t.entry_time, intraday)}</td>
                    <td className="num">{t.entry_price.toFixed(digits)}</td>
                    <td>{formatShortTime(t.exit_time, intraday)}</td>
                    <td className="num">{t.exit_price.toFixed(digits)}</td>
                    <td className="num muted">{formatDuration(t.exit_time - t.entry_time)}</td>
                    <td className={`num ${tone(t.pnl)}`}>{formatMoney(t.pnl, "", true)}</td>
                    <td className={`num ${tone(total)}`}>{formatMoney(total, "", true)}</td>
                    <td>
                      <span className={`rtp-reason ${t.reason}`}>{REASON[t.reason] ?? t.reason}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
