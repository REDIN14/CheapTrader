// The slim account bar at the very bottom — the place TradingView keeps its
// "Paper Trading" strip.
//
// Live: who the orders go to, and the account's balance / equity / profit.
// Replay: the paper account's figures. The name is a button that opens and closes
// the performance report above the strip. Either way it is read-only; trading
// itself happens from the chart's Sell / Buy buttons and the Trade panel.

import { formatMoney, formatSigned } from "../lib/format";
import type { AccountInfo, ReplayAccount } from "../lib/types";
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
          Replay · paper account
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

  return (
    <div className="tv-strip">
      <span className="tv-strip-name" title={account ? `${brokerName} · account ${account.login}` : brokerName}>
        <i className={account ? "tv-strip-dot on" : "tv-strip-dot"} />
        {account?.server || brokerName}
      </span>
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
            label="Profit"
            value={formatMoney(account.profit, ccy, true)}
            tone={toneOf(account.profit)}
          />
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
