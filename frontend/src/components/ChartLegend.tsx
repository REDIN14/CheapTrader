// TradingView-style chart legend, pinned to the chart's top-left corner.
//
//   Euro vs US Dollar · 15 · MetaTrader 5  ●  O1.12703 H1.12761 L1.12653 C1.12760 +0.00056 (+0.05%)
//   [ SELL 1.1275⁹ ]  [ 0.8 / 0.10 ]  [ BUY 1.1275⁹ ]
//   SMA · Bollinger Bands                              (one row per indicator drawn on the candles;
//                                                       an indicator with a pane of its own has its
//                                                       row at the top of that pane — see PaneLegends)
//
// The Sell / Buy pill is the app's on-chart trading control. The number above
// the lot size is the live spread in pips; the lot size is the same volume the
// order ticket uses.

import { useEffect, useState } from "react";
import type { LegendValues } from "../lib/chart";
import { formatSigned, splitPipette } from "../lib/format";
import { useNow } from "../lib/hooks";
import { SettingsIcon } from "./Icons";

/** Live prices count as flowing for this long after the last new tick. */
const LIVE_WINDOW_MS = 30_000;

/** One indicator in a legend: its name and one dot per colour it draws in. */
export interface LegendIndicator {
  id: string;
  name: string;
  colors: string[];
  /** 0: on the candles. 1, 2, ...: the pane of its own, counted from the one just under the candles. */
  pane: number;
}

export interface LegendTrade {
  /** Price on the Sell button: the bid live, the bar close in replay. */
  bid: number | null;
  /** Price on the Buy button: the ask live, the bar close in replay. */
  ask: number | null;
  digits: number;
  /** Spread in pips; null hides the figure (replay has no spread). */
  spread: number | null;
  volume: number;
  onVolumeChange: (volume: number) => void;
  disabled?: boolean;
  /** The side whose market order is on its way to the broker; its button waits for the answer. */
  busy?: "BUY" | "SELL" | null;
  onBuy: () => void;
  onSell: () => void;
}

interface Props {
  values: LegendValues | null;
  /** Instrument name, e.g. "Euro vs US Dollar" (falls back to the ticker). */
  title: string;
  /** Interval as TradingView spells it in the legend: "15", "1h", "1D". */
  interval: string;
  /** Data source shown after the interval, as TradingView shows the exchange. */
  source?: string;
  /** Wall-clock ms of the last fresh live tick; null hides the status dot (replay). */
  liveAt: number | null;
  /** MetaTrader is slow to answer: the dot turns amber, prices are a few seconds late. */
  lagging?: boolean;
  trade: LegendTrade | null;
  indicators: LegendIndicator[];
  /** Opens the indicator panel, where an indicator can be edited or removed. */
  onManageIndicators: () => void;
}

export function ChartLegend({
  values,
  title,
  interval,
  source,
  liveAt,
  lagging = false,
  trade,
  indicators,
  onManageIndicators,
}: Props) {
  const now = useNow(1000);
  if (!title) return null;

  const live = liveAt === null ? null : now - liveAt < LIVE_WINDOW_MS;
  const up = values ? values.change >= 0 : true;
  const cls = up ? "up" : "down";

  return (
    <div className="tv-legend">
      <div className="tv-legend-line">
        <span className="tv-legend-title">{title}</span>
        <span className="tv-legend-dim">· {interval}</span>
        {source && <span className="tv-legend-dim tv-legend-src">· {source}</span>}
        {live !== null && (
          <span
            className={live ? (lagging ? "tv-live on slow" : "tv-live on") : "tv-live"}
            title={
              live
                ? lagging
                  ? "MetaTrader is slow to answer: prices are a few seconds late"
                  : "Receiving live prices"
                : "No live prices"
            }
          >
            <i />
          </span>
        )}
        {values && (
          <span className="tv-legend-ohlc">
            <span className="tv-legend-key">O</span>
            <span className={cls}>{values.open.toFixed(values.digits)}</span>
            <span className="tv-legend-key">H</span>
            <span className={cls}>{values.high.toFixed(values.digits)}</span>
            <span className="tv-legend-key">L</span>
            <span className={cls}>{values.low.toFixed(values.digits)}</span>
            <span className="tv-legend-key">C</span>
            <span className={cls}>{values.close.toFixed(values.digits)}</span>
            <span className={cls}>
              {formatSigned(values.change, values.digits)} ({formatSigned(values.changePct, 2)}%)
            </span>
          </span>
        )}
      </div>

      {trade && <TradePill trade={trade} />}

      {indicators.map((ind) => (
        <IndicatorRow key={ind.id} indicator={ind} onManage={onManageIndicators} />
      ))}
    </div>
  );
}

/** A line of the legend for one indicator: coloured dots, its name, and (on hover) its settings button. */
export function IndicatorRow({ indicator, onManage }: { indicator: LegendIndicator; onManage: () => void }) {
  // an indicator that only draws shapes has no line colour: a neutral dot
  const colours = indicator.colors.length ? [...new Set(indicator.colors)].slice(0, 4) : ["#787b86"];
  return (
    <div className="tv-legend-ind">
      {colours.map((c) => (
        <span key={c} className="tv-legend-dot" style={{ background: c }} />
      ))}
      <span className="tv-legend-ind-name">{indicator.name}</span>
      <button
        className="tv-legend-ind-btn"
        title={`${indicator.name} — open indicator settings`}
        onClick={onManage}
      >
        <SettingsIcon size={18} />
      </button>
    </div>
  );
}

function PillPrice({ price, digits }: { price: number | null; digits: number }) {
  if (price == null) return <span className="tv-pill-price">—</span>;
  const { main, pip } = splitPipette(price, digits);
  return (
    <span className="tv-pill-price">
      {main}
      {pip && <sup>{pip}</sup>}
    </span>
  );
}

function TradePill({ trade }: { trade: LegendTrade }) {
  const { bid, ask, digits, spread, volume, disabled, busy } = trade;
  const noQuote = bid == null || ask == null;
  return (
    <div className="tv-trade-pill">
      <button
        className={busy === "SELL" ? "tv-pill-btn sell busy" : "tv-pill-btn sell"}
        disabled={disabled || noQuote || busy === "SELL"}
        onClick={trade.onSell}
        title={busy === "SELL" ? "Waiting for the broker…" : "Sell at market"}
      >
        <PillPrice price={bid} digits={digits} />
        <span className="tv-pill-side">{busy === "SELL" ? "SENDING…" : "SELL"}</span>
      </button>

      <div className="tv-pill-mid">
        <span className="tv-pill-spread" title="Spread in pips">
          {spread != null ? spread.toFixed(1) : ""}
        </span>
        <LotInput volume={volume} onChange={trade.onVolumeChange} />
      </div>

      <button
        className={busy === "BUY" ? "tv-pill-btn buy busy" : "tv-pill-btn buy"}
        disabled={disabled || noQuote || busy === "BUY"}
        onClick={trade.onBuy}
        title={busy === "BUY" ? "Waiting for the broker…" : "Buy at market"}
      >
        <PillPrice price={ask} digits={digits} />
        <span className="tv-pill-side">{busy === "BUY" ? "SENDING…" : "BUY"}</span>
      </button>
    </div>
  );
}

/**
 * Lot-size box between the Sell and Buy buttons. It keeps its own text while
 * being edited, so half-typed values like "0." survive, and only commits a
 * positive number.
 */
function LotInput({ volume, onChange }: { volume: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(String(volume));

  // Follow outside changes (the order ticket edits the same volume).
  useEffect(() => {
    setText((current) => (Number(current) === volume ? current : String(volume)));
  }, [volume]);

  return (
    <input
      className="tv-pill-qty"
      inputMode="decimal"
      value={text}
      title="Lot size"
      aria-label="Lot size"
      onChange={(e) => {
        const next = e.target.value.replace(",", ".");
        if (!/^\d*\.?\d{0,2}$/.test(next)) return;
        setText(next);
        const n = Number(next);
        if (n > 0) onChange(n);
      }}
      onBlur={() => setText(String(volume))}
    />
  );
}
