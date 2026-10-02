// The performance report, in the bottom drawer TradingView keeps for its paper-trading account. One
// report for the replay's paper account and for the live MetaTrader account: the same figures (worked out
// by backend/app/performance.py from the closed trades), the same layout.
//
//   Overview   — the headline figures and the equity curve;
//   Trades     — every closed trade, newest first, with the running total;
//   Statistics — every figure there is, in groups, and what each instrument made;
//   Account    — (live) what the broker says about the account.
//
// The replay's report stays live while the replay plays; the live account's is read from the
// broker's history (see lib/useAccountReport.ts).

import { useMemo, useState } from "react";
import { formatDuration, formatInt, formatLots, formatMoney, formatShortTime } from "../lib/format";
import {
  PERIODS,
  accountSections,
  profitFactorText,
  reasonLabel,
  statSections,
  toneOf,
  type Period,
  type ReportTrade,
  type ReportView,
  type StatSection,
} from "../lib/performance";
import type { ClosedTrade } from "../lib/types";
import { CloseIcon, ResetIcon } from "./Icons";
import { EquityChart } from "./EquityChart";

interface Props {
  view: ReportView;
  intraday: boolean;
  /** The price digits of an instrument (the trades of a live account span many). */
  digitsOf: (symbol: string) => number;
  title: string;
  /** The live report is being read from the broker. */
  loading?: boolean;
  /** Why it could not be. */
  error?: string | null;
  /** Read it again (live). */
  onReload?: () => void;
  /** The period the live report is cut to, and the way to change it. */
  period?: { value: Period; onChange: (period: Period) => void };
  onClose: () => void;
}

type Tab = "overview" | "trades" | "statistics" | "account";

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

/** What a trade cost (commission, swap and fees); the replay's trades have none. */
const costsOf = (t: ReportTrade): number => ("commission" in t ? (t as ClosedTrade).commission + (t as ClosedTrade).swap + (t as ClosedTrade).fee : 0);

function Sections({ sections }: { sections: StatSection[] }) {
  return (
    <>
      {sections.map((section) => (
        <div className="rp-statcard" key={section.title}>
          <h4>{section.title}</h4>
          <dl>
            {section.rows.map((row) => (
              <div className="rp-statrow" key={row.label} title={row.hint}>
                <dt>{row.label}</dt>
                <dd className={row.tone}>{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </>
  );
}

export function PerformanceReport({ view, intraday, digitsOf, title, loading = false, error = null, onReload, period, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const live = view.kind === "live";
  const s = view.summary;
  const trades = view.trades;

  // Running total of the closed trades, oldest first, then shown newest first. (When only the newest are listed
  // it starts from what the older ones made, which the figures know.)
  const rows = useMemo(() => {
    let total = s ? s.net_profit - trades.reduce((sum, t) => sum + t.pnl, 0) : 0;
    return trades
      .map((t, i) => {
        total += t.pnl;
        return { t, n: view.tradesTotal - trades.length + i + 1, total };
      })
      .reverse();
  }, [trades, view.tradesTotal, s]);
  const showCosts = useMemo(() => trades.some((t) => costsOf(t) !== 0), [trades]);

  const sections = useMemo(() => (s ? statSections(s, { live, flows: view.flows }) : []), [s, live, view.flows]);
  const accountRows = useMemo(() => (view.account ? accountSections(view.account) : []), [view.account]);

  // The live report is read from the broker: until it is in, there is nothing to show but that.
  const reading = live && !s;
  const emptyCurve = live ? "The curve appears once the account has traded." : "The curve appears once the replay has moved.";

  return (
    <section className={tab === "statistics" || tab === "account" ? "rp-report tall" : "rp-report"} aria-label={live ? "Account report" : "Replay report"}>
      <header className="rp-report-head">
        <div className="tv-tabs">
          <button className={tab === "overview" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("overview")}>
            Overview
          </button>
          <button className={tab === "trades" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("trades")}>
            Trades{view.tradesTotal ? ` (${formatInt(view.tradesTotal)})` : ""}
          </button>
          <button className={tab === "statistics" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("statistics")}>
            Statistics
          </button>
          {live && (
            <button className={tab === "account" ? "tv-tab active" : "tv-tab"} onClick={() => setTab("account")}>
              Account
            </button>
          )}
        </div>
        {live && period && (
          <select
            className="rp-period"
            value={period.value}
            onChange={(e) => period.onChange(e.target.value as Period)}
            aria-label="Period"
            title="The period the report covers"
          >
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        )}
        <span className="rp-report-title">{title}</span>
        {live && onReload && (
          <button className={loading ? "tv-icon-btn spinning" : "tv-icon-btn"} onClick={onReload} title="Read the account's history again" aria-label="Read the history again">
            <ResetIcon size={18} />
          </button>
        )}
        <button className="tv-icon-btn" onClick={onClose} title="Hide the report">
          <CloseIcon size={20} />
        </button>
      </header>

      {reading ? (
        <div className="rp-report-body">
          {error ? (
            <p className="rp-empty" role="alert">
              The account&apos;s history could not be read: {error}
              {onReload && (
                <>
                  {" "}
                  <button className="rp-link" onClick={onReload}>
                    Try again
                  </button>
                </>
              )}
            </p>
          ) : (
            <p className="rp-empty">Reading the account&apos;s history from MetaTrader…</p>
          )}
        </div>
      ) : tab === "overview" ? (
        <div className="rp-report-body overview">
          <div className="rp-kpis">
            <Kpi label="Net profit" value={formatMoney(s?.net_profit ?? 0, "", true)} cls={toneOf(s?.net_profit ?? 0)} sub={view.netSub} />
            <Kpi
              label="Profit factor"
              value={profitFactorText(s)}
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
            <Kpi label="Average trade" value={s && s.trades ? formatMoney(s.avg_trade, "", true) : "—"} cls={s && s.trades ? toneOf(s.avg_trade) : undefined} sub={s && s.trades ? `held ${formatDuration(s.avg_duration)}` : undefined} />
          </div>

          <div className="rp-curve">
            <div className="rp-curve-head">
              <span>
                {live ? "Account" : "Equity"}
                {live && <small className="rp-curve-note"> · deposits and withdrawals left out</small>}
              </span>
              {view.curveNow != null && <b className={toneOf(view.curveNow - view.baseline)}>{formatMoney(view.curveNow)}</b>}
            </div>
            <EquityChart points={view.curve} baseline={view.baseline} intraday={intraday} empty={emptyCurve} />
          </div>
        </div>
      ) : tab === "trades" ? (
        <div className="rp-report-body trades">
          {rows.length === 0 ? (
            <p className="rp-empty">
              {live
                ? "No closed trades in the account's history yet."
                : "No closed trades yet. Open a position and close it — or let its stop or target do it — and it is listed here."}
            </p>
          ) : (
            <>
              {view.tradesTotal > trades.length && (
                <p className="rp-note">
                  The newest {formatInt(trades.length)} of {formatInt(view.tradesTotal)} closed trades are listed; all of them are in the figures.
                </p>
              )}
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
                    {showCosts && <th className="num">Costs</th>}
                    <th className="num">P&amp;L</th>
                    <th className="num">Total</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ t, n, total }) => {
                    const digits = digitsOf(t.symbol);
                    const costs = costsOf(t);
                    const closed = t as ClosedTrade;
                    return (
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
                        {showCosts && (
                          <td
                            className={`num ${toneOf(costs)}`}
                            title={`Commission ${formatMoney(closed.commission ?? 0, "", true)} · swap ${formatMoney(closed.swap ?? 0, "", true)} · fees ${formatMoney(closed.fee ?? 0, "", true)}`}
                          >
                            {formatMoney(costs, "", true)}
                          </td>
                        )}
                        <td className={`num ${toneOf(t.pnl)}`} title={live ? "After the costs" : undefined}>
                          {formatMoney(t.pnl, "", true)}
                        </td>
                        <td className={`num ${toneOf(total)}`}>{formatMoney(total, "", true)}</td>
                        <td>
                          <span className={`rtp-reason ${t.reason}`}>{reasonLabel(t.reason)}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>
      ) : tab === "statistics" ? (
        <div className="rp-report-body stats">
          <div className="rp-stats">
            <Sections sections={sections} />
          </div>
          {view.symbols.length > 0 && (
            <div className="rp-symbols">
              <h4>By instrument</h4>
              <table className="rp-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th className="num">Trades</th>
                    <th className="num">Win rate</th>
                    <th className="num">Lots</th>
                    <th className="num">Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {view.symbols.map((row) => (
                    <tr key={row.symbol}>
                      <td>{row.symbol}</td>
                      <td className="num">{formatInt(row.trades)}</td>
                      <td className="num">{row.win_rate.toFixed(1)}%</td>
                      <td className="num muted">{formatLots(row.volume)}</td>
                      <td className={`num ${toneOf(row.net_profit)}`}>{formatMoney(row.net_profit, "", true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <div className="rp-report-body stats">
          <div className="rp-stats">
            <Sections sections={accountRows} />
            {view.history && (
              <div className="rp-statcard">
                <h4>History</h4>
                <dl>
                  <div className="rp-statrow">
                    <dt>Deals</dt>
                    <dd>{formatInt(view.history.deals)}</dd>
                  </div>
                  {view.history.deals > 0 && (
                    <>
                      <div className="rp-statrow">
                        <dt>From</dt>
                        <dd>{formatShortTime(view.history.first, false)}</dd>
                      </div>
                      <div className="rp-statrow">
                        <dt>To</dt>
                        <dd>{formatShortTime(view.history.last, false)}</dd>
                      </div>
                    </>
                  )}
                </dl>
                <p className="rp-note">
                  This is what MetaTrader holds. To load older history, open the History tab in the terminal and choose All history.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
