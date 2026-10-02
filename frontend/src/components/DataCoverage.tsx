import { formatInt } from "../lib/format";
import type { DataStat } from "../lib/types";

interface Props {
  stats: DataStat[];
  symbol: string | null;
  timeframe: string;
}

function fmt(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

// Shows how much history is stored locally for the active symbol, per timeframe.
export function DataCoverage({ stats, symbol, timeframe }: Props) {
  const rows = stats.filter((s) => s.symbol === symbol);
  const current = rows.find((s) => s.timeframe === timeframe);

  return (
    <div className="data-coverage">
      <div className="dc-title">Stored history</div>
      {current ? (
        <div className="dc-current">
          <span className="dc-count">{formatInt(current.count)} bars</span>
          <span className="dc-range">
            {fmt(current.oldest)} → {fmt(current.newest)}
          </span>
        </div>
      ) : (
        <div className="dc-current muted">No data cached yet</div>
      )}
      {rows.length > 1 && (
        <ul className="dc-list">
          {rows.map((r) => (
            <li key={r.timeframe} className={r.timeframe === timeframe ? "active" : ""}>
              <span>{r.timeframe}</span>
              <span>{formatInt(r.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
