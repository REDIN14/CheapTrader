// Marks on the chart for a replay's trades: an arrow where each position was
// opened and a dot where it was closed (green if it made money, red if it lost).

import type { ChartMarker } from "./chart";
import { formatLots, formatMoney } from "./format";
import type { BacktestTrade, Position } from "./types";

const BUY = "#2962ff";
const SELL = "#f23645";
const UP = "#089981";
const DOWN = "#f23645";

/** Past this many trades the labels would crowd each other, so only the shapes are drawn. */
const MAX_LABELLED = 40;

export function replayMarkers(trades: BacktestTrade[], open: Position[]): ChartMarker[] {
  const labels = trades.length + open.length <= MAX_LABELLED;
  const out: ChartMarker[] = [];

  const opened = (time: number, side: "BUY" | "SELL", volume: number): ChartMarker => ({
    time,
    position: side === "BUY" ? "belowBar" : "aboveBar",
    shape: side === "BUY" ? "arrowUp" : "arrowDown",
    color: side === "BUY" ? BUY : SELL,
    text: labels ? formatLots(volume) : "",
  });

  for (const t of trades) {
    out.push(opened(t.entry_time, t.side, t.volume));
    out.push({
      time: t.exit_time,
      // On the side the price travelled to: above the bar for a buy, below for a sell.
      position: t.side === "BUY" ? "aboveBar" : "belowBar",
      shape: "circle",
      color: t.pnl >= 0 ? UP : DOWN,
      text: labels ? formatMoney(t.pnl, "", true) : "",
    });
  }
  for (const p of open) out.push(opened(p.time, p.side, p.volume));
  return out;
}
