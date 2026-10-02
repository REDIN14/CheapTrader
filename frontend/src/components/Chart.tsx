import { useEffect, useLayoutEffect, useRef, type MutableRefObject } from "react";
import {
  createChartHandle,
  type ChartGeometry,
  type ChartHandle,
  type ChartMarker,
  type HoverInfo,
  type IndicatorPlot,
  type LegendValues,
  type PriceLineSpec,
  type ViewHint,
  type ViewPolicy,
} from "../lib/chart";
import type { Bar } from "../lib/types";

interface Props {
  bars: Bar[];
  liveBar: Bar | null;
  priceLines: PriceLineSpec[];
  /** Marks on candles (a replay trade's entry and exit). */
  markers?: ChartMarker[];
  indicatorPlots: IndicatorPlot[];
  digits?: number;
  point?: number;
  symbol?: string;
  timeframe?: string;
  /** Seconds one candle takes (so drawings can be placed past the newest one). */
  barSeconds?: number;
  /** What replacing `bars` does to the view; see ViewPolicy. */
  view?: ViewPolicy;
  /** The candles on screen are about to be replaced: show them dimmed meanwhile. */
  loading?: boolean;
  /** Bump to squeeze every loaded bar into view. */
  fitSignal?: number;
  /** Filled with a function that reads where the user is looking (for the loader). */
  viewHintRef?: MutableRefObject<(() => ViewHint | null) | null>;
  onLineDrag?: (id: string, price: number, delta: number) => void;
  onLineDragEnd?: (id: string, price: number, delta: number) => void;
  /** Hands out the price scale mapping for the DOM overlays. */
  onGeometry?: (geometry: ChartGeometry) => void;
  onLegend?: (values: LegendValues | null) => void;
  onBarClick?: (time: number) => void;
  /** The bar under the pointer, or null once it leaves the candles. */
  onHover?: (hover: HoverInfo | null) => void;
}

/** How far the candles dim while the next ones load (keep in step with .chart.is-loading). */
const DIMMED = 0.5;
/** Where a fresh set of candles starts when nothing was dimmed, and how long the fade-in takes. */
const FADE_FROM = 0.86;
const FADE_MS = 150;

/** The new candles ease in instead of cutting in. */
function fadeIn(el: HTMLElement | null, from: number) {
  if (!el || typeof el.animate !== "function") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  el.animate([{ opacity: from }, { opacity: 1 }], { duration: FADE_MS, easing: "ease-out" });
}

export function Chart({
  bars,
  liveBar,
  priceLines,
  markers,
  indicatorPlots,
  digits,
  point,
  symbol,
  timeframe,
  barSeconds,
  view = "latest",
  loading = false,
  fitSignal,
  viewHintRef,
  onLineDrag,
  onLineDragEnd,
  onGeometry,
  onLegend,
  onBarClick,
  onHover,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<ChartHandle | null>(null);
  const dragRef = useRef(onLineDrag);
  const dragEndRef = useRef(onLineDragEnd);
  const geometryRef = useRef(onGeometry);
  const legendRef = useRef(onLegend);
  const clickRef = useRef(onBarClick);
  const hoverRef = useRef(onHover);
  dragRef.current = onLineDrag;
  dragEndRef.current = onLineDragEnd;
  geometryRef.current = onGeometry;
  legendRef.current = onLegend;
  clickRef.current = onBarClick;
  hoverRef.current = onHover;

  // Everything that feeds the chart runs as a layout effect, in this order, so a
  // new set of candles, its legend text, its price format and its fade-in all land
  // before the browser paints: there is never a frame with half of them.
  useLayoutEffect(() => {
    if (!containerRef.current) return;
    const handle = createChartHandle(containerRef.current);
    handleRef.current = handle;
    geometryRef.current?.(handle.geometry);
    if (viewHintRef) viewHintRef.current = () => handle.viewHint();
    const offDrag = handle.onDrag((id, price, delta) => dragRef.current?.(id, price, delta));
    const offDragEnd = handle.onDragEnd((id, price, delta) =>
      dragEndRef.current?.(id, price, delta),
    );
    const offLegend = handle.onLegend((values) => legendRef.current?.(values));
    const offClick = handle.onClick((time) => clickRef.current?.(time));
    const offHover = handle.onHover((hover) => hoverRef.current?.(hover));
    return () => {
      offDrag();
      offDragEnd();
      offLegend();
      offClick();
      offHover();
      handle.destroy();
      handleRef.current = null;
      if (viewHintRef) viewHintRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The symbol / digits metadata must be in place before the bars, so the first
  // legend emitted for a fresh series already carries the right symbol.
  useLayoutEffect(() => {
    if (symbol) {
      handleRef.current?.setLegendMeta({ symbol, timeframe: timeframe ?? "", digits: digits ?? 5 });
    }
  }, [symbol, timeframe, digits]);

  useLayoutEffect(() => {
    if (barSeconds) handleRef.current?.setBarSeconds(barSeconds);
  }, [barSeconds]);

  useLayoutEffect(() => {
    if (digits != null && point != null) {
      handleRef.current?.setPriceFormat(digits, point);
    }
  }, [digits, point]);

  // Whether the candles were dimmed just before this render (see the effect below).
  const wasDimmed = useRef(false);
  // The live candle that belongs to these very bars; it goes on with them, so the
  // newest candle never disappears for a frame while the series is swapped.
  const liveRef = useRef(liveBar);
  liveRef.current = liveBar;

  useLayoutEffect(() => {
    const handle = handleRef.current;
    if (!handle) return;
    handle.setBars(bars, view, liveRef.current);
    if (bars.length && (view === "latest" || view === "anchor")) {
      fadeIn(containerRef.current, wasDimmed.current ? DIMMED : FADE_FROM);
    }
  }, [bars, view]);

  useLayoutEffect(() => {
    wasDimmed.current = loading;
  }, [loading]);

  useLayoutEffect(() => {
    if (liveBar) handleRef.current?.updateBar(liveBar);
  }, [liveBar]);

  useEffect(() => {
    handleRef.current?.setPriceLines(priceLines);
  }, [priceLines]);

  useEffect(() => {
    handleRef.current?.setIndicators(indicatorPlots);
  }, [indicatorPlots]);

  useEffect(() => {
    handleRef.current?.setMarkers(markers ?? []);
  }, [markers]);

  useEffect(() => {
    if (fitSignal !== undefined) handleRef.current?.fitContent();
  }, [fitSignal]);

  return (
    <div
      ref={containerRef}
      className={loading ? "chart is-loading" : "chart"}
      aria-busy={loading}
      data-testid="chart-canvas"
    />
  );
}
