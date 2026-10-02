// TradingView-style chart wrapper around lightweight-charts v5.
//
// Provides: candlesticks, indicator overlays (price + sub-panes), draggable
// price lines (SL/TP), and a live OHLC legend feed. Everything that has to sit
// on top of the chart as DOM (position tags, ask/last labels) reads the chart's
// price scale through `geometry`.

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type Logical,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { barAt, canPatchTail, firstDifference, nearestIndex } from "./barMath";
import { loadPersisted, savePersisted } from "./persist";
import type { Bar } from "./types";

/**
 * What a new set of bars does to the view (the part of the series on screen):
 *
 * - `latest`: jump to the newest bars at the default zoom (a new symbol, a first load);
 * - `anchor`: another interval of the same symbol — keep the zoom and the place,
 *   i.e. stay at the newest bar if that is where you were, otherwise stay on the
 *   same date;
 * - `keep`: the same series refreshed or deepened — nothing on screen moves;
 * - `none`: leave the view alone (a replay step).
 */
export type ViewPolicy = "latest" | "anchor" | "keep" | "none";

/**
 * What the user is looking at, in terms that survive a change of interval. The
 * loader uses it to fetch enough bars to show the same place in the next interval.
 */
export interface ViewHint {
  /** The user is following the newest bar. */
  atEdge: boolean;
  /** Bars across the plot: the zoom. */
  visibleBars: number;
  /** Time of the bar at the left edge of the plot. */
  leftTime: number;
  /** Time of the newest bar. */
  newestTime: number;
}

export interface PriceLineSpec {
  id: string;
  price: number;
  color: string;
  title: string;
  /** Lines are draggable unless this is false (a position's entry never moves). */
  draggable?: boolean;
  lineStyle?: number;
  lineWidth?: number;
}

export interface IndicatorPlot {
  name: string;
  color: string;
  pane: number;
  type?: "line" | "histogram";
  data: { time: number; value: number }[];
}

export interface LegendValues {
  symbol: string;
  timeframe: string;
  open: number;
  high: number;
  low: number;
  close: number;
  change: number;
  changePct: number;
  digits: number;
}

/** What DOM overlays need to know about the chart's price scale. */
export interface ChartGeometry {
  /** Chart-local y pixel for a price, or null when it is off-scale. */
  priceToY: (price: number) => number | null;
  /** Price at a chart-local y; pair with containerTop() for client coordinates. */
  localYToPrice: (localY: number) => number | null;
  /** The container's viewport top, so callers can convert client coordinates. */
  containerTop: () => number;
  /** Signed price change per vertical pixel (negative: y grows downwards). */
  pricePerPixel: () => number;
  /** Width of the right price scale in px. */
  scaleWidth: () => number;
  /** Width of the plot area (the candles) in px, without the price scale. */
  plotWidth: () => number;
  /** Height of the main (price) pane in px, excluding the time axis. */
  paneHeight: () => number;
  /**
   * Chart-local x for a time. A time past the newest bar (or before the oldest) is placed as if the bars
   * went on at the interval's pace, so a drawing can reach into the future. Null before any bars are loaded.
   */
  timeToX: (time: number) => number | null;
  /** The time at a chart-local x: the inverse of `timeToX`. */
  xToTime: (x: number) => number | null;
  /** A short string that changes whenever time or price map to different pixels (pan, zoom, new bars, resize). */
  signature: () => string;
  /** The sub-panes below the price pane (chart-local px), in order. */
  subPanes: () => { top: number; height: number }[];
  /** Follow the pointer over the chart, in chart-local px (null once it leaves). Returns the way to stop. */
  onPointer: (handler: (at: { x: number; y: number } | null) => void) => () => void;
  /** Called with the chart-local spot of every click on the chart (a drag that pans the chart is not a click). */
  onPointClick: (handler: (at: { x: number; y: number }) => void) => () => void;
}

export type DragHandler = (id: string, price: number, delta: number) => void;
export type DragEndHandler = (id: string, price: number, delta: number) => void;
export type LegendHandler = (values: LegendValues | null) => void;
export type ClickHandler = (time: number) => void;

/** The bar under the pointer, and where the pointer is inside the chart (CSS px). */
export interface HoverInfo {
  time: number;
  x: number;
  y: number;
}
export type HoverHandler = (hover: HoverInfo | null) => void;

/** A mark on a candle, such as where a replay trade opened or closed. */
export interface ChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  color: string;
  text?: string;
}

export type ChartHandle = {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  markers: ISeriesMarkersPluginApi<Time>;
  geometry: ChartGeometry;
  /**
   * Replace the series; `view` says what happens to the part on screen. `live` is
   * the candle being drawn right now, which goes in as the newest bar. A `keep`
   * refresh that only changed the newest bar(s) is applied in place without
   * re-uploading the series.
   */
  setBars: (bars: Bar[], view?: ViewPolicy, live?: Bar | null) => void;
  updateBar: (bar: Bar) => void;
  /** Where the user is looking right now, or null when the chart is empty. */
  viewHint: () => ViewHint | null;
  setPriceLines: (specs: PriceLineSpec[]) => void;
  setIndicators: (plots: IndicatorPlot[]) => void;
  setPriceFormat: (digits: number, point: number) => void;
  setLegendMeta: (meta: { symbol: string; timeframe: string; digits: number }) => void;
  /** Seconds one bar takes at the current interval (places times past the newest bar). */
  setBarSeconds: (seconds: number) => void;
  /** Squeeze every loaded bar into view. */
  fitContent: () => void;
  onClick: (handler: ClickHandler) => () => void;
  onDrag: (handler: DragHandler) => () => void;
  /** Fired once when a line drag finishes, for persisting the new level. */
  onDragEnd: (handler: DragEndHandler) => () => void;
  onLegend: (handler: LegendHandler) => () => void;
  /** Fired as the pointer moves over the candles, and with null when it leaves them. */
  onHover: (handler: HoverHandler) => () => void;
  /** Marks on candles, e.g. where a replay trade opened and closed. */
  setMarkers: (markers: ChartMarker[]) => void;
  destroy: () => void;
};

// TradingView dark palette (sampled from the reference UI).
const TV = {
  bg: "#131722",
  grid: "#20242f",
  separator: "#2e2e2e",
  separatorHover: "#3d3d3d",
  axisText: "#b2b5be",
  up: "#089981",
  down: "#f23645",
  crosshair: "#9598a1",
  crosshairLabel: "#4c525e",
};

const FONT =
  "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif";

/** Default zoom for a fresh load: about this many CSS px per candle. */
const BAR_PX = 8;
/** Empty bars kept to the right of the latest candle. */
const RIGHT_OFFSET = 8;
/** The most bars a refresh adds one by one; a bigger change replaces the series instead. */
const IN_PLACE_MAX = 300;
/** How many of the newest candles a refresh may rewrite in place (the terminal's final figures for the last few). */
const TAIL_PATCH = 8;

function toCandle(bar: Bar): CandlestickData<Time> {
  return {
    time: bar.time as UTCTimestamp,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  };
}

export function createChartHandle(container: HTMLElement): ChartHandle {
  const chart = createChart(container, {
    layout: {
      background: { color: TV.bg },
      textColor: TV.axisText,
      fontFamily: FONT,
      fontSize: 12,
      attributionLogo: false,
      panes: {
        separatorColor: TV.separator,
        separatorHoverColor: TV.separatorHover,
        enableResize: true,
      },
    },
    localization: { locale: "en-US" },
    grid: {
      vertLines: { color: TV.grid },
      horzLines: { color: TV.grid },
    },
    rightPriceScale: {
      borderVisible: false,
      scaleMargins: { top: 0.1, bottom: 0.1 },
      entireTextOnly: true,
      // A steady width keeps the DOM labels that sit on the scale from jumping
      // when the visible prices gain or lose a digit.
      minimumWidth: 64,
    },
    leftPriceScale: { visible: false },
    timeScale: {
      borderVisible: false,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: RIGHT_OFFSET,
      barSpacing: BAR_PX,
      fixLeftEdge: false,
    },
    crosshair: {
      mode: 0,
      vertLine: {
        color: TV.crosshair,
        width: 1,
        style: 2,
        labelBackgroundColor: TV.crosshairLabel,
      },
      horzLine: {
        color: TV.crosshair,
        width: 1,
        style: 2,
        labelBackgroundColor: TV.crosshairLabel,
      },
    },
    handleScroll: { mouseWheel: true, pressedMouseMove: true },
    handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    autoSize: true,
  });

  // -- main series -------------------------------------------------------
  const series = chart.addSeries(CandlestickSeries, {
    upColor: TV.up,
    downColor: TV.down,
    borderUpColor: TV.up,
    borderDownColor: TV.down,
    wickUpColor: TV.up,
    wickDownColor: TV.down,
    // The dotted last-price line follows the last candle's colour; its label is
    // drawn by <PriceTags>, which can also show the ask and the bar countdown.
    priceLineVisible: true,
    priceLineColor: "",
    priceLineStyle: 1,
    priceLineWidth: 1,
    lastValueVisible: false,
  });

  const markers = createSeriesMarkers(series, []);

  // -- time <-> bar index --------------------------------------------------
  // The chart is indexed by bar, not by time (weekends and holidays have no bars). A time inside the
  // history sits between its two neighbouring bars, in proportion; one outside it is placed as if the
  // bars went on at the interval's pace, so drawings can reach into the future.
  let barSeconds = 0;
  const step = () => {
    if (barSeconds > 0) return barSeconds;
    const n = lastBars.length;
    return (n > 1 ? lastBars[n - 1].time - lastBars[n - 2].time : 60) || 60;
  };
  function timeToLogical(time: number): number | null {
    const n = lastBars.length;
    if (!n) return null;
    if (time <= lastBars[0].time) return (time - lastBars[0].time) / step();
    if (time >= lastBars[n - 1].time) return n - 1 + (time - lastBars[n - 1].time) / step();
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (lastBars[mid].time <= time) lo = mid;
      else hi = mid;
    }
    return lo + (time - lastBars[lo].time) / (lastBars[hi].time - lastBars[lo].time);
  }
  function logicalToTime(logical: number): number | null {
    const n = lastBars.length;
    if (!n) return null;
    if (logical <= 0) return lastBars[0].time + logical * step();
    if (logical >= n - 1) return lastBars[n - 1].time + (logical - (n - 1)) * step();
    const i = Math.floor(logical);
    return lastBars[i].time + (logical - i) * (lastBars[i + 1].time - lastBars[i].time);
  }

  // -- the pointer, for the drawing layer ---------------------------------
  const pointerHandlers = new Set<(at: { x: number; y: number } | null) => void>();
  const pointClickHandlers = new Set<(at: { x: number; y: number }) => void>();
  chart.subscribeCrosshairMove((param) => {
    if (!pointerHandlers.size) return;
    const at = param.point ? { x: param.point.x, y: param.point.y } : null;
    for (const h of pointerHandlers) h(at);
  });

  // The library converts between x and a bar index only in whole bars (logicalToCoordinate answers 0 for
  // a fractional index, coordinateToLogical rounds to the nearest bar). A drawing sits between bars, so
  // the conversions below interpolate: the scale is linear from one bar to the next.
  function xOfLogical(logical: number): number | null {
    const scale = chart.timeScale();
    const whole = Math.floor(logical);
    const a = scale.logicalToCoordinate(whole as Logical);
    if (a == null) return null;
    const part = logical - whole;
    if (part === 0) return Number(a);
    const b = scale.logicalToCoordinate((whole + 1) as Logical);
    return b == null ? Number(a) : Number(a) + (Number(b) - Number(a)) * part;
  }
  function logicalAtX(x: number): number | null {
    const scale = chart.timeScale();
    const near = scale.coordinateToLogical(x);
    if (near == null) return null;
    const n = Number(near);
    const a = scale.logicalToCoordinate(n as Logical);
    const b = scale.logicalToCoordinate((n + 1) as Logical);
    if (a == null || b == null || Number(b) === Number(a)) return n;
    return n + (x - Number(a)) / (Number(b) - Number(a));
  }

  // -- geometry for DOM overlays ----------------------------------------
  const geometry: ChartGeometry = {
    timeToX(time) {
      try {
        const logical = timeToLogical(time);
        return logical == null ? null : xOfLogical(logical);
      } catch {
        return null;
      }
    },
    xToTime(x) {
      try {
        const logical = logicalAtX(x);
        return logical == null ? null : logicalToTime(logical);
      } catch {
        return null;
      }
    },
    signature() {
      try {
        const range = chart.timeScale().getVisibleLogicalRange();
        const n = lastBars.length;
        return [
          range ? `${range.from.toFixed(3)}:${range.to.toFixed(3)}` : "-",
          n ? `${n}:${lastBars[0].time}:${lastBars[n - 1].time}` : "0",
          series.coordinateToPrice(0),
          series.coordinateToPrice(200),
          chart.timeScale().width(),
          chart.paneSize(0).height,
          barSeconds,
        ].join("|");
      } catch {
        return "-";
      }
    },
    onPointer(handler) {
      pointerHandlers.add(handler);
      return () => {
        pointerHandlers.delete(handler);
      };
    },
    onPointClick(handler) {
      pointClickHandlers.add(handler);
      return () => {
        pointClickHandlers.delete(handler);
      };
    },
    subPanes() {
      const out: { top: number; height: number }[] = [];
      try {
        const top = container.getBoundingClientRect().top;
        const panes = chart.panes();
        for (let i = 1; i < panes.length; i++) {
          const box = panes[i].getHTMLElement()?.getBoundingClientRect();
          if (box) out.push({ top: box.top - top, height: box.height });
        }
      } catch {
        /* not laid out yet */
      }
      return out;
    },
    priceToY(price) {
      const y = series.priceToCoordinate(price);
      return y == null ? null : Number(y);
    },
    localYToPrice(localY) {
      // Takes a LOCAL y. Callers holding a viewport coordinate must subtract
      // the container's top first, or the price reads one header too high.
      const price = series.coordinateToPrice(localY);
      return price == null ? null : Number(price);
    },
    containerTop() {
      return container.getBoundingClientRect().top;
    },
    pricePerPixel() {
      // Two probes one pixel apart give the chart's current price scale, so a
      // drag can convert pointer travel into a price change. The result is
      // SIGNED and negative: y grows downwards while price grows upwards, so
      // `price + dy * pricePerPixel()` lowers the price as the pointer moves
      // down. Callers must keep the sign.
      const a = series.coordinateToPrice(0);
      const b = series.coordinateToPrice(1);
      if (a == null || b == null) return 0;
      return Number(b) - Number(a);
    },
    // Both throw while the chart has not laid itself out yet (the first frame after
    // it is created); the overlays read them every frame, so that reads as "nothing yet".
    scaleWidth() {
      try {
        return chart.priceScale("right").width();
      } catch {
        return 0;
      }
    },
    plotWidth() {
      try {
        return chart.timeScale().width();
      } catch {
        return 0;
      }
    },
    paneHeight() {
      try {
        return chart.paneSize(0).height;
      } catch {
        return 0;
      }
    },
  };

  // -- price lines -------------------------------------------------------
  let lines: { spec: PriceLineSpec; line: IPriceLine }[] = [];
  // While a line is being dragged, the specs on screen belong to the drag. React
  // state updates are ignored until the pointer is released, otherwise the line
  // objects would be rebuilt mid-drag and the drag would lose its references.
  let dragging = false;

  function setPriceLines(specs: PriceLineSpec[]) {
    if (dragging) return;
    for (const { line } of lines) series.removePriceLine(line);
    lines = specs.map((spec) => ({
      spec,
      line: series.createPriceLine({
        price: spec.price,
        color: spec.color,
        lineWidth: (spec.lineWidth ?? 1) as 1 | 2 | 3 | 4,
        lineStyle: spec.lineStyle ?? 0,
        axisLabelVisible: true,
        title: spec.title,
      }),
    }));
  }

  // -- pointing at price lines -------------------------------------------
  // How close (in px) the pointer must be to grab a line.
  const DRAG_RADIUS = 8;

  /** Stops and targets beat a draft line when both are in reach. */
  function rank(spec: PriceLineSpec): number {
    return spec.id.startsWith("sl-") || spec.id.startsWith("tp-") ? 2 : 1;
  }

  function nearestLine(y: number): { spec: PriceLineSpec; line: IPriceLine } | null {
    let best: { spec: PriceLineSpec; line: IPriceLine } | null = null;
    let bestDist = Number.POSITIVE_INFINITY;
    for (const entry of lines) {
      if (entry.spec.draggable === false) continue;
      const coord = series.priceToCoordinate(entry.spec.price);
      if (coord == null) continue;
      const dist = Math.abs(coord - y);
      if (dist > DRAG_RADIUS) continue;
      if (
        dist < bestDist ||
        (dist === bestDist && best && rank(entry.spec) > rank(best.spec))
      ) {
        bestDist = dist;
        best = entry;
      }
    }
    return best;
  }

  // -- indicator series --------------------------------------------------
  // Overlay plots (pane 0) share the price scale. Pane plots (pane >= 1) each
  // get their own pane below the chart so they never distort the price scale.
  // -- the size of the panes, remembered --------------------------------------
  // The user drags the dividers between the panes; where they were left is kept (as stretch factors, which
  // do not depend on the window's size) for the next time there are as many panes.
  const LAYOUT_KEY = "paneLayouts";
  let lastLayout: number[] = [];

  function savedLayout(panes: number): number[] | null {
    const factors = loadPersisted<Record<string, unknown>>(LAYOUT_KEY, {})[String(panes)];
    if (!Array.isArray(factors) || factors.length !== panes + 1) return null;
    if (!factors.every((f) => typeof f === "number" && Number.isFinite(f) && f > 0)) return null;
    const total = (factors as number[]).reduce((a, b) => a + b, 0);
    return (factors as number[])[0] / total < 0.2 ? null : (factors as number[]); // candles squeezed away: not kept
  }

  function readLayout(): number[] {
    return chart.panes().map((p) => p.getStretchFactor());
  }

  function rememberLayout() {
    const factors = readLayout();
    if (factors.length < 2) return;
    if (factors.length === lastLayout.length && factors.every((f, i) => Math.abs(f - lastLayout[i]) < 1e-6)) return;
    lastLayout = factors;
    const all = loadPersisted<Record<string, number[]>>(LAYOUT_KEY, {});
    all[String(factors.length - 1)] = factors;
    savePersisted(LAYOUT_KEY, all);
  }
  window.addEventListener("pointerup", rememberLayout);

  let indicatorSeries: ISeriesApi<"Line" | "Histogram">[] = [];
  // What each series above was built as (type, pane, colour). New values for the
  // same set of plots go into the existing series, so the sub-panes keep their
  // place and size instead of being torn down and rebuilt.
  let indicatorShape: string[] = [];
  let priceFormat: { type: "price"; precision: number; minMove: number } | null = null;

  const plotShape = (p: IndicatorPlot) => `${p.type ?? "line"}|${p.pane ?? 0}|${p.color}`;
  const plotData = (p: IndicatorPlot) =>
    p.data.map((d) => ({ time: d.time as UTCTimestamp, value: d.value }) as LineData<Time>);

  function setIndicators(plots: IndicatorPlot[]) {
    const shape = plots.map(plotShape);
    if (
      indicatorSeries.length === shape.length &&
      shape.every((s, i) => s === indicatorShape[i])
    ) {
      plots.forEach((plot, i) => indicatorSeries[i].setData(plotData(plot)));
      return;
    }
    indicatorShape = shape;

    for (const s of indicatorSeries) chart.removeSeries(s);
    indicatorSeries = [];

    // Drop any sub-panes, then recreate only the ones we need.
    const existing = chart.panes();
    for (let i = existing.length - 1; i >= 1; i--) {
      chart.removePane(i);
    }

    const paneIndex = new Map<number, number>(); // logical pane -> chart pane index
    let nextPane = 1;

    for (const plot of plots) {
      const logical = plot.pane ?? 0;
      let targetPane = 0;
      if (logical >= 1) {
        if (!paneIndex.has(logical)) {
          paneIndex.set(logical, nextPane);
          nextPane += 1;
        }
        targetPane = paneIndex.get(logical)!;
      }

      // No series title: the legend names every plotted indicator, and a title
      // would also draw a stray tag on the price scale.
      const isHistogram = plot.type === "histogram";
      const s = chart.addSeries(
        isHistogram ? HistogramSeries : LineSeries,
        isHistogram
          ? {
              color: plot.color,
              priceLineVisible: false,
              lastValueVisible: false,
              base: 0,
            }
          : {
              color: plot.color,
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
            },
        targetPane,
      );
      if (priceFormat && targetPane === 0) s.applyOptions({ priceFormat });
      s.setData(plotData(plot));
      indicatorSeries.push(s);
    }

    // Give each sub-pane a sensible height: a fifth of the chart or so, but all of them together
    // never take more than 60% of it, so the candles keep most of the room however many panes there are.
    // The panes are sized by their stretch factors, not with setHeight(): setting the heights one after
    // the other makes each take its room from its neighbour and squashes the first ones to a sliver.
    // (Stretch factors also keep the proportions when the window is resized.)
    const panesAfter = chart.panes();
    const subs = panesAfter.length - 1;
    if (subs > 0) {
      const saved = savedLayout(subs);
      if (saved) {
        saved.forEach((factor, i) => panesAfter[i].setStretchFactor(factor));
      } else {
        const room = Math.max(1, container.clientHeight - 30); // without the time axis
        const each = Math.max(70, Math.min(Math.max(90, Math.round(room * 0.18)), Math.floor((room * 0.6) / subs)));
        panesAfter[0].setStretchFactor(Math.max(1, (room - subs * each) / each));
        for (let i = 1; i < panesAfter.length; i++) panesAfter[i].setStretchFactor(1);
      }
    }
    lastLayout = readLayout();
  }

  // -- price format ------------------------------------------------------
  // Match the symbol's digits/point so the price axis shows every pip-level
  // price (like MQL5) instead of the default 2-decimal scale.
  function setPriceFormat(digits: number, point: number) {
    const precision = Math.max(0, Math.min(8, digits));
    const minMove = point > 0 ? point : Math.pow(10, -precision);
    priceFormat = { type: "price", precision, minMove };
    series.applyOptions({ priceFormat });
    for (const s of indicatorSeries) s.applyOptions({ priceFormat });
  }

  // -- legend ------------------------------------------------------------
  const legendHandlers = new Set<LegendHandler>();
  // The bars on screen. This is the caller's own array until the first live
  // update, which copies it first: a series kept in memory is never changed behind
  // its owner's back.
  let lastBars: Bar[] = [];
  let ownsBars = false;
  let legendMeta = { symbol: "", timeframe: "", digits: 5 };

  function emitLegend(bar: Bar | null) {
    if (!bar) {
      for (const h of legendHandlers) h(null);
      return;
    }
    const change = bar.close - bar.open;
    const changePct = bar.open ? (change / bar.open) * 100 : 0;
    const values: LegendValues = {
      symbol: legendMeta.symbol,
      timeframe: legendMeta.timeframe,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      change,
      changePct,
      digits: legendMeta.digits,
    };
    for (const h of legendHandlers) h(values);
  }

  chart.subscribeCrosshairMove((param) => {
    if (!param.time || !lastBars.length) {
      emitLegend(lastBars.length ? lastBars[lastBars.length - 1] : null);
      return;
    }
    // 20k-bar series are normal here: a binary search, not a scan, on every mouse move.
    const bar = barAt(lastBars, param.time as number);
    emitLegend(bar ?? lastBars[lastBars.length - 1]);
  });

  // -- hover ---------------------------------------------------------------
  const hoverHandlers = new Set<HoverHandler>();
  chart.subscribeCrosshairMove((param) => {
    if (!hoverHandlers.size) return;
    const hover: HoverInfo | null =
      param.time != null && param.point
        ? { time: param.time as number, x: param.point.x, y: param.point.y }
        : null;
    for (const h of hoverHandlers) h(hover);
  });

  // -- markers -------------------------------------------------------------
  function setMarkers(list: ChartMarker[]) {
    // The plugin wants them in time order.
    const sorted = [...list].sort((a, b) => a.time - b.time);
    markers.setMarkers(
      sorted.map((m) => ({
        time: m.time as UTCTimestamp,
        position: m.position,
        shape: m.shape,
        color: m.color,
        text: m.text ?? "",
        size: 1,
      })),
    );
  }

  // -- dragging ----------------------------------------------------------
  const dragHandlers = new Set<DragHandler>();
  const dragEndHandlers = new Set<DragEndHandler>();
  // The grabbed line is captured on pointer-down and its price is applied
  // directly, so a drag never depends on React having re-rendered. Exactly one
  // line moves per drag.
  let grabbed: { spec: PriceLineSpec; line: IPriceLine } | null = null;
  let dragStartPrice = 0;

  function localY(event: PointerEvent): number {
    const rect = container.getBoundingClientRect();
    return event.clientY - rect.top;
  }

  function onPointerDown(event: PointerEvent) {
    if (event.button !== 0) return;
    const hit = nearestLine(localY(event));
    if (!hit) return;
    grabbed = hit;
    dragStartPrice = hit.spec.price;
    dragging = true;
    container.style.cursor = "ns-resize";
    hit.line.applyOptions({ lineWidth: ((hit.spec.lineWidth ?? 1) + 1) as 1 | 2 | 3 | 4 });
    // Cancelling the pointer-down also suppresses the compatibility mouse events,
    // which is what stops the chart from starting to pan under the drag.
    event.preventDefault();
    event.stopPropagation();
  }

  function onPointerMove(event: PointerEvent) {
    const y = localY(event);

    if (!grabbed) {
      container.style.cursor = nearestLine(y) ? "ns-resize" : "";
      return;
    }

    const price = series.coordinateToPrice(y);
    if (price == null) return;
    const value = Number(price);
    const delta = value - grabbed.spec.price;

    grabbed.spec.price = value;
    grabbed.line.applyOptions({ price: value });

    for (const h of dragHandlers) h(grabbed.spec.id, value, delta);
  }

  function onPointerUp() {
    if (!grabbed) return;
    const finished = { id: grabbed.spec.id, price: grabbed.spec.price };
    grabbed.line.applyOptions({ lineWidth: (grabbed.spec.lineWidth ?? 1) as 1 | 2 | 3 | 4 });
    grabbed = null;
    dragging = false;
    container.style.cursor = "";
    for (const h of dragEndHandlers) {
      h(finished.id, finished.price, finished.price - dragStartPrice);
    }
  }

  container.addEventListener("pointerdown", onPointerDown);
  container.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);

  // Clicks for the drawing tools come from the page's own pointer events. The library's click
  // (subscribeClick) is dropped when it follows another click within half a second, as it takes the pair
  // for a double click, and that would lose the second point of a line placed in a hurry. A press that
  // moved (a pan) is no click.
  let press: { x: number; y: number; id: number } | null = null;
  function onPressStart(event: PointerEvent) {
    press = event.button === 0 ? { x: event.clientX, y: event.clientY, id: event.pointerId } : null;
  }
  function onPressEnd(event: PointerEvent) {
    const down = press;
    press = null;
    if (!down || event.button !== 0 || down.id !== event.pointerId || grabbed) return;
    if (Math.abs(event.clientX - down.x) + Math.abs(event.clientY - down.y) > 5) return;
    if (!pointClickHandlers.size) return;
    const box = container.getBoundingClientRect();
    const at = { x: event.clientX - box.left, y: event.clientY - box.top };
    for (const h of pointClickHandlers) h(at);
  }
  container.addEventListener("pointerdown", onPressStart);
  container.addEventListener("pointerup", onPressEnd);

  // -- view --------------------------------------------------------------
  /** The most recent bars at a readable zoom, like a fresh TradingView chart. */
  function showLatest() {
    const n = lastBars.length;
    if (!n) return;
    const width = container.clientWidth || 800;
    const visible = Math.min(n, Math.max(60, Math.round(width / BAR_PX)));
    chart.timeScale().setVisibleLogicalRange({
      from: n - visible,
      to: n - 1 + RIGHT_OFFSET,
    });
  }

  /** Let the price scale follow the visible candles again (dragging the axis had switched that off). */
  function autoScalePrices() {
    chart.priceScale("right").applyOptions({ autoScale: true });
  }

  /** Squeeze every loaded bar into view. */
  function fit() {
    chart.timeScale().fitContent();
    autoScalePrices();
  }

  // Double-click resets the view to fit the loaded data, which is why the shell
  // needs no dedicated zoom buttons.
  function onDoubleClick() {
    fit();
  }
  container.addEventListener("dblclick", onDoubleClick);

  // -- keeping the view across a new set of bars ----------------------------
  /** Where the user is looking, in terms that survive a change of interval. */
  interface ViewSnapshot {
    /** Logical range on screen. */
    from: number;
    to: number;
    /** Bars across the plot: the zoom. */
    count: number;
    /** The newest bar is on screen, i.e. the user is following the live edge. */
    atEdge: boolean;
    /** Empty bars to the right of the newest one. */
    rightOffset: number;
    /** The bar at the left edge and its index. */
    anchorIndex: number;
    anchorTime: number;
    /** The bar in the middle of the plot. */
    centerTime: number;
  }

  function snapshotView(): ViewSnapshot | null {
    const n = lastBars.length;
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!n || !range) return null;
    const clamp = (i: number) => Math.min(n - 1, Math.max(0, Math.round(i)));
    const anchorIndex = clamp(range.from);
    return {
      from: range.from,
      to: range.to,
      count: range.to - range.from,
      atEdge: range.to >= n - 1.5,
      rightOffset: Math.max(0, range.to - (n - 1)),
      anchorIndex,
      anchorTime: lastBars[anchorIndex].time,
      centerTime: lastBars[clamp((range.from + range.to) / 2)].time,
    };
  }

  /** Put the view described by `snap` onto the bars now on screen. */
  function restoreView(snap: ViewSnapshot, view: "anchor" | "keep") {
    const n = lastBars.length;
    if (!n) return;
    const scale = chart.timeScale();

    if (snap.atEdge) {
      // Still following the newest bar: same zoom, same gap to the right of it.
      const gap = Math.min(snap.rightOffset, Math.max(RIGHT_OFFSET, snap.count / 2));
      const count = Math.min(snap.count, n + gap);
      const to = n - 1 + gap;
      scale.setVisibleLogicalRange({ from: to - count, to });
      return;
    }

    if (view === "keep") {
      // The same series with more or fewer bars before it: slide the window so the
      // bar at its left edge stays where it was.
      const shift = nearestIndex(lastBars, snap.anchorTime) - snap.anchorIndex;
      scale.setVisibleLogicalRange({ from: snap.from + shift, to: snap.to + shift });
      return;
    }

    // Another interval: stay on the date in the middle of the screen, at the same zoom.
    const centre = nearestIndex(lastBars, snap.centerTime);
    const count = Math.min(snap.count, n + RIGHT_OFFSET);
    scale.setVisibleLogicalRange({ from: centre - count / 2, to: centre + count / 2 });
  }

  // -- click -------------------------------------------------------------
  const clickHandlers = new Set<ClickHandler>();
  chart.subscribeClick((param) => {
    if (param.time == null) return;
    for (const h of clickHandlers) h(param.time as number);
  });

  return {
    chart,
    series,
    markers,
    geometry,
    setBars(stored: Bar[], view: ViewPolicy = "latest", live: Bar | null = null) {
      // The candle being drawn right now goes in with the series, not after it: the
      // newest bar is then in place before the view is worked out, and nothing has
      // to be appended (and the view nudged) a moment later.
      let bars = stored;
      let fresh = false; // `bars` is our own array, not the caller's
      if (live && (!stored.length || live.time >= stored[stored.length - 1].time)) {
        bars = stored.slice();
        if (stored.length && live.time === stored[stored.length - 1].time) bars[bars.length - 1] = live;
        else bars.push(live);
        fresh = true;
      }

      const before = lastBars;

      // A refresh of the series on screen that only touched its newest few bars goes
      // in place: nothing is re-uploaded and nothing on screen moves.
      if (view === "keep" && before.length && bars.length >= before.length) {
        const first = firstDifference(before, bars);
        if (
          first >= before.length - TAIL_PATCH &&
          bars.length - first <= IN_PLACE_MAX &&
          canPatchTail(before, bars, first)
        ) {
          try {
            // A candle older than the newest is a historical update to the chart.
            for (let i = first; i < bars.length; i++) series.update(toCandle(bars[i]), i < before.length - 1);
            lastBars = bars;
            ownsBars = fresh;
            emitLegend(bars[bars.length - 1]);
            return;
          } catch {
            // The chart refused (it holds something other than we think): replace it all below.
          }
        }
      }

      // Read where the user is looking before the series (and with it the time
      // scale) is replaced.
      const snap = view === "anchor" || view === "keep" ? snapshotView() : null;

      lastBars = bars;
      ownsBars = fresh;
      series.setData(bars.map(toCandle));

      if (view !== "none") {
        if (snap && bars.length && view !== "latest") restoreView(snap, view);
        else showLatest();
        // A manually stretched price axis belongs to the old data; so does a leftover
        // range after a new symbol or interval. A refresh keeps whatever the user set.
        if (view !== "keep") autoScalePrices();
      }
      emitLegend(bars.length ? bars[bars.length - 1] : null);
    },
    updateBar(bar: Bar) {
      // lightweight-charts rejects updates older than the last bar; ignore
      // stale live bars (e.g. a tick that arrived before new history loaded).
      const last = lastBars.length ? lastBars[lastBars.length - 1] : null;
      if (last && bar.time < last.time) return;
      if (!ownsBars) {
        lastBars = lastBars.slice();
        ownsBars = true;
      }
      if (last && bar.time === last.time) lastBars[lastBars.length - 1] = bar;
      else lastBars.push(bar);
      series.update(toCandle(bar));
      emitLegend(bar);
    },
    viewHint() {
      const snap = snapshotView();
      if (!snap) return null;
      return {
        atEdge: snap.atEdge,
        visibleBars: snap.count,
        leftTime: snap.anchorTime,
        newestTime: lastBars[lastBars.length - 1].time,
      };
    },
    setPriceLines,
    setIndicators,
    setPriceFormat,
    setLegendMeta(meta) {
      legendMeta = meta;
    },
    setBarSeconds(seconds) {
      barSeconds = seconds;
    },
    fitContent: fit,
    onClick(handler: ClickHandler) {
      clickHandlers.add(handler);
      return () => clickHandlers.delete(handler);
    },
    onDrag(handler: DragHandler) {
      dragHandlers.add(handler);
      return () => dragHandlers.delete(handler);
    },
    onDragEnd(handler: DragEndHandler) {
      dragEndHandlers.add(handler);
      return () => dragEndHandlers.delete(handler);
    },
    onLegend(handler: LegendHandler) {
      legendHandlers.add(handler);
      return () => legendHandlers.delete(handler);
    },
    onHover(handler: HoverHandler) {
      hoverHandlers.add(handler);
      return () => hoverHandlers.delete(handler);
    },
    setMarkers,
    destroy() {
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("dblclick", onDoubleClick);
      container.removeEventListener("pointerdown", onPressStart);
      container.removeEventListener("pointerup", onPressEnd);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointerup", rememberLayout);
      chart.remove();
    },
  };
}
