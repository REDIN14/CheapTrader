// The slim account bar at the very bottom — the place TradingView keeps its
// "Paper Trading" strip.
//
// Live: who the orders go to, and the account's balance / equity / profit, and the same figures
// the replay shows, worked out from the broker's history (return, trades, win rate, drawdown,
// profit factor). Replay: the paper account's figures. The name is a button that opens and
// closes the performance report above the strip, in both. Either way it is read-only; trading
// itself happens from the chart's Sell / Buy buttons and the Trade panel.

import { formatMoney, formatSigned } from "../lib/format";
import { profitFactorText } from "../lib/performance";
import type { AccountInfo, PerformanceSummary, ReplayAccount } from "../lib/types";
import { ChevronDown, ChevronUp } from "./Icons";
import { TerminalMenu } from "./TerminalMenu";

interface Props {
  mode: "live" | "replay";
  /** Broker adapter in use: "mt5" or "mock". */
  broker: string;
  account: AccountInfo | null;
  positionCount: number;
  /** The replay's paper account. */
  paper: ReplayAccount | null;
  reportOpen: boolean;
  onToggleReport: () => void;
  /** The live account's figures, from the broker's history (null until they are read). */
  liveSummary?: PerformanceSummary | null;
  /** Net profit as a share of the money first put in. */
  liveReturn?: number | null;
  /** MetaTrader is open but the app is still on made-up prices: the chip offers to connect. */
  canConnect?: boolean;
  /** Open the part of the tour that connects to MetaTrader. */
  onConnect?: () => void;
}

function Stat({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
  title?: string;
}) {
  return (
    <span className="tv-strip-stat" title={title}>
      <span className="tv-strip-label">{label}</span>
      <span className={tone ? `tv-strip-value ${tone}` : "tv-strip-value"}>{value}</span>
    </span>
  );
}

const toneOf = (v: number): "up" | "down" | undefined => (v > 0 ? "up" : v < 0 ? "down" : undefined);

/** The profit factor, or why there is none: "—" with no trades, "∞" with wins only. */
function profitFactor(paper: ReplayAccount): string {
  if (paper.trades_total === 0) return "—";
  if (paper.losses === 0) return paper.wins > 0 ? "∞" : "—";
  return paper.metrics.profit_factor.toFixed(2);
}

export function AccountStrip({
  mode,
  broker,
  account,
  positionCount,
  paper,
  reportOpen,
  onToggleReport,
  liveSummary = null,
  liveReturn = null,
  canConnect = false,
  onConnect,
}: Props) {
  const ccy = account?.currency ?? "";
  const brokerName = broker === "mt5" ? "MetaTrader 5" : broker === "mock" ? "Mock broker" : broker;

  if (mode === "replay") {
    const m = paper?.metrics;
    return (
      <div className="tv-strip">
        <button
          className={reportOpen ? "tv-strip-name tv-strip-toggle open" : "tv-strip-name tv-strip-toggle"}
          onClick={onToggleReport}
          aria-expanded={reportOpen}
          title={reportOpen ? "Hide the performance report" : "Show the performance report"}
        >
          <i className="tv-strip-dot replay" />
          Replay · {paper?.profile_name || "paper account"}
          {reportOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {paper && m ? (
          <div className="tv-strip-stats">
            <Stat label="Balance" value={formatMoney(paper.balance)} title="Initial balance plus closed trades" />
            <Stat label="Equity" value={formatMoney(paper.equity)} title="Balance plus the open positions' floating profit" />
            <Stat
              label="Open P&L"
              value={formatMoney(paper.unrealized, "", true)}
              tone={toneOf(paper.unrealized)}
            />
            <Stat
              label="Return"
              value={`${formatSigned(m.total_return_pct, 2)}%`}
              tone={toneOf(m.total_return_pct)}
              title="Equity against the initial balance"
            />
            <Stat
              label="Trades"
              value={paper.trades_total ? `${paper.trades_total} (${paper.wins}W ${paper.losses}L)` : "0"}
            />
            <Stat label="Win rate" value={paper.trades_total ? `${m.win_rate.toFixed(1)}%` : "—"} />
            <Stat
              label="Max drawdown"
              value={m.max_drawdown_pct > 0 ? `−${m.max_drawdown_pct.toFixed(2)}%` : "0.00%"}
              tone={m.max_drawdown_pct > 0 ? "down" : undefined}
            />
            <Stat label="Profit factor" value={profitFactor(paper)} />
          </div>
        ) : null}
      </div>
    );
  }

  const h = liveSummary;
  return (
    <div className="tv-strip">
      <button
        className={reportOpen ? "tv-strip-name tv-strip-toggle open" : "tv-strip-name tv-strip-toggle"}
        onClick={onToggleReport}
        aria-expanded={reportOpen}
        title={
          reportOpen
            ? "Hide the account report"
            : `Show the account report: the figures of the account's whole history · ${brokerName}${account ? ` · account ${account.login}` : ""}`
        }
      >
        <i className={account ? "tv-strip-dot on" : "tv-strip-dot"} />
        {account?.server || brokerName}
        {reportOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {broker === "mock" && (
        <button
          className={canConnect ? "tv-strip-warn action ready" : "tv-strip-warn action"}
          title={
            canConnect
              ? "MetaTrader is open: click to connect to it"
              : "No MetaTrader terminal is connected: prices, bars and orders are simulated. Click to see how to connect."
          }
          onClick={onConnect}
        >
          {canConnect ? "METATRADER FOUND · CONNECT" : "SYNTHETIC DATA · CONNECT METATRADER"}
        </button>
      )}
      {account ? (
        <div className="tv-strip-stats">
          <Stat label="Balance" value={formatMoney(account.balance, ccy)} />
          <Stat label="Equity" value={formatMoney(account.equity, ccy)} />
          <Stat
            label="Open P&L"
            value={formatMoney(account.profit, ccy, true)}
            tone={toneOf(account.profit)}
            title="What the open positions make right now"
          />
          <Stat
            label="Return"
            value={liveReturn == null ? "—" : `${formatSigned(liveReturn, 2)}%`}
            tone={liveReturn == null ? undefined : toneOf(liveReturn)}
            title="Net profit of the closed trades as a share of the money first put in"
          />
          <Stat
            label="Trades"
            value={h ? (h.trades ? `${h.trades} (${h.wins}W ${h.losses}L)` : "0") : "—"}
            title="Closed trades in the account's history"
          />
          <Stat label="Win rate" value={h && h.trades ? `${h.win_rate.toFixed(1)}%` : "—"} />
          <Stat
            label="Max drawdown"
            value={h ? (h.max_drawdown_pct > 0 ? `−${h.max_drawdown_pct.toFixed(2)}%` : "0.00%") : "—"}
            tone={h && h.max_drawdown_pct > 0 ? "down" : undefined}
            title="The biggest fall of the account from a peak, deposits and withdrawals left out"
          />
          <Stat label="Profit factor" value={profitFactorText(h)} title="Gross profit divided by gross loss" />
          <Stat label="Positions" value={String(positionCount)} />
        </div>
      ) : (
        <span className="tv-strip-muted">No account connected</span>
      )}
      {broker === "mt5" && (
        <span className="tv-strip-end">
          <TerminalMenu />
        </span>
      )}
    </div>
  );
}
