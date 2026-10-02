import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, indicatorApi, replayApi } from "./lib/api";
import { useLiveFeed } from "./lib/useLiveFeed";
import type { StreamState } from "./lib/ws";
import { usePersistentState } from "./lib/persist";
import { copyText } from "./lib/clipboard";
import { formatLots, formatMoney, spreadInPips } from "./lib/format";
import { levelKindAt, levelProblem, type Level } from "./lib/positions";
import { kindTitle, levelsProblem, orderLevelKindAt, pendingKind, pendingProblem } from "./lib/orders";
import type { BoxTrading } from "./lib/boxTrading";
import { useDelayedFlag } from "./lib/hooks";
import { foldTicks } from "./lib/liveBar";
import { useServerClock } from "./lib/serverClock";
import { METATRADER_STEP, RESUME_KEY, resumeStep } from "./lib/tour";
import { TF } from "./lib/timeframes";
import type { Drawing } from "./lib/drawings";
import { replayMarkers } from "./lib/replayMarkers";
import { useChartData, type ChartFrame } from "./lib/useChartData";
import { REPLAY_SPEEDS, useReplay } from "./lib/useReplay";
import { useReplayProfiles } from "./lib/useReplayProfiles";
import { useUpdate } from "./lib/useUpdate";
import { updateChip } from "./lib/updates";
import type {
  ChartGeometry,
  HoverInfo,
  IndicatorPlot,
  LegendValues,
  PriceLineSpec,
  ViewHint,
  ViewPolicy,
} from "./lib/chart";
import { Chart } from "./components/Chart";
import { ChartBoundary } from "./components/ChartBoundary";
import { ChartContextMenu, type ContextMenuItem } from "./components/ChartContextMenu";
import { ChartLegend, type LegendIndicator, type LegendTrade } from "./components/ChartLegend";
import { AboutDialog } from "./components/AboutDialog";
import { UpdateDialog } from "./components/UpdateDialog";
import { DocsDialog } from "./components/DocsDialog";
import { DrawingController } from "./components/DrawingLayer";
import { PaneLegends } from "./components/PaneLegends";
import { PriceTags } from "./components/PriceTags";
import { PositionOverlay } from "./components/PositionOverlay";
import { OrderOverlay, type OrderPart } from "./components/OrderOverlay";
import { TopNav } from "./components/TopNav";
import { Dock, type DockTab } from "./components/Dock";
import { RightPanel } from "./components/RightPanel";
import { RightRail } from "./components/RightRail";
import { WelcomeTour } from "./components/WelcomeTour";
import { BottomToolbar, type RangeInfo } from "./components/BottomToolbar";
import { AccountStrip } from "./components/AccountStrip";
import { OrderPanel } from "./components/OrderPanel";
import type { OrderForm } from "./components/OrderTicket";
import { ReplayTradePanel } from "./components/ReplayTradePanel";
import { ReplayCut } from "./components/ReplayCut";
import { ReplayPicker } from "./components/ReplayPicker";
import { ProfileMenu } from "./components/ProfileMenu";
import { ReplayReport } from "./components/ReplayReport";
import { ReplayToolbar } from "./components/ReplayToolbar";
import { DataCoverage } from "./components/DataCoverage";
import { IndicatorManager } from "./components/IndicatorManager";
import { SymbolSearchDialog } from "./components/SymbolSearchDialog";
import { Toast } from "./components/Toast";
import {
  type AccountInfo,
  type BacktestTrade,
  type Bar,
  type DataStat,
  type OrderRequest,
  type OrderResult,
  type PendingOrder,
  type Position,
  type Symbol,
  type Timeframe,
} from "./lib/types";

/**
 * A stop or target the user has dragged, placed or removed that the broker has not yet
 * confirmed. It stays on screen meanwhile: the live feed reports the positions many
 * times a second and would otherwise put the old level back under the cursor.
 */
interface LevelOverride {
  price: number;
  /** Which request put it there; only that request may take it away again. */
  seq: number;
  /** The request is on its way to the broker (as against a level merely being dragged). */
  sending: boolean;
}

const levelName = (level: Level) => (level === "sl" ? "Stop loss" : "Take profit");

/** The overrides without those a finished request put there. */
function settleOverrides(all: Record<string, LevelOverride>, ticket: number, seq: number) {
  let next = all;
  for (const level of ["sl", "tp"]) {
    const key = `${ticket}:${level}`;
    if (all[key]?.seq === seq) {
      if (next === all) next = { ...all };
      delete next[key];
    }
  }
  return next;
}

// How much history to show. The persistent store backfills this once, then
// serves it locally; the user can raise it to load even deeper history.
const DEFAULT_BARS = 20_000;
const BAR_STEPS = [5_000, 10_000, 20_000, 50_000, 100_000];

const PLOT_COLORS = ["#2962ff", "#ff9800", "#e91e63", "#00bcd4", "#8bc34a", "#9c27b0"];

interface IndicatorSet {
  key: string;
  plots: IndicatorPlot[];
  legend: LegendIndicator[];
  drawings: Drawing[];
}

const NO_DRAWINGS: Drawing[] = [];
const NO_INDICATORS: IndicatorSet = { key: "", plots: [], legend: [], drawings: NO_DRAWINGS };
const NO_ORDERS: PendingOrder[] = [];

/** The chart lines of an order that waits: its price, its stop loss and its take profit. */
const ORDER_LINE = /^(order|osl|otp)-(\d+)$/;
const ORDER_PARTS: Record<string, OrderPart> = { order: "price", osl: "sl", otp: "tp" };
const orderPartName = (part: OrderPart) => (part === "price" ? "Order price" : part === "sl" ? "Stop loss" : "Take profit");

// A position's lines: its entry takes the colour of its side (the same blue / red
// as the Buy / Sell buttons), the stop is orange and the target green.
const LINE_COLORS = { buy: "#2962ff", sell: "#f23645", sl: "#ff9800", tp: "#089981", draft: "#9598a1" };

export default function App() {
  const [symbols, setSymbols] = useState<Symbol[]>([]);
  const [symbol, setSymbol] = usePersistentState<string | null>("symbol", null);
  const [timeframe, setTimeframe] = usePersistentState<Timeframe>("timeframe", "H1");
  const [barCount, setBarCount] = usePersistentState<number>("barCount", DEFAULT_BARS);
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  // The limit / stop orders that wait for their price (live trading; a replay has none).
  const [orders, setOrders] = useState<PendingOrder[]>([]);
  const ordersRef = useRef(orders);
  ordersRef.current = orders;
  /** Orders this page took back itself: their disappearing is no news. */
  const cancelledByUs = useRef(new Set<number>());
  const symbolsRef = useRef(symbols);
  symbolsRef.current = symbols;
  const [broker, setBroker] = useState<string>("");
  // Price<->pixel mapping, so the DOM overlays can sit on the chart's price scale.
  const [chartGeom, setChartGeom] = useState<ChartGeometry | null>(null);
  const [legend, setLegend] = useState<LegendValues | null>(null);

  const [error, setError] = useState<string | null>(null);
  const dismissError = useCallback(() => setError(null), []);
  // A brief confirmation ("Copied 1.12840"); an error, if there is one, wins the spot.
  const [notice, setNotice] = useState<string | null>(null);
  const dismissNotice = useCallback(() => setNotice(null), []);
  // The right-click menu: where it opened and the chart price under the pointer.
  const [chartMenu, setChartMenu] = useState<{ x: number; y: number; price: number | null } | null>(null);
  const closeChartMenu = useCallback(() => setChartMenu(null), []);
  const [orderForm, setOrderForm] = usePersistentState<OrderForm>("orderForm", {
    volume: 0.1,
    sl: "",
    tp: "",
  });
  const [dataStats, setDataStats] = useState<DataStat[]>([]);

  const [fitSignal, setFitSignal] = useState(0);
  // Where the pointer is over the candles; only followed while a replay start is chosen.
  const [hover, setHover] = useState<HoverInfo | null>(null);

  // -- shell layout ------------------------------------------------------
  const [showWatchlist, setShowWatchlist] = usePersistentState("showWatchlist", true);
  const [showDock, setShowDock] = usePersistentState("showDock", true);
  const [pinnedSymbols, setPinnedSymbols] = usePersistentState<string[]>("pinnedSymbols", []);
  const [searchOpen, setSearchOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const [panel, setPanel] = usePersistentState<DockTab>("panel", "trade");
  const [activeIndicators, setActiveIndicators] = usePersistentState<string[]>(
    "activeIndicators",
    [],
  );
  // What the active indicators drew, tagged with the symbol / interval it was computed for: their
  // lines, their legend rows, and the shapes they put on the chart.
  const [indicatorSet, setIndicatorSet] = useState<IndicatorSet>(NO_INDICATORS);
  // The documentation dialog: which page it opens on (null: closed).
  const [docs, setDocs] = useState<string | null>(null);
  // The welcome tour: the step it is open on (null: closed). It opens by itself the first time the app starts.
  const [tourSeen, setTourSeen] = usePersistentState("tourSeen", false);
  const [tour, setTour] = useState<number | null>(null);
  const [about, setAbout] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  // A newer release on GitHub: the backend looks for it by itself; the button is in the top bar.
  const update = useUpdate();
  const [updateOpen, setUpdateOpen] = useState(false);
  const [updateTold, setUpdateTold] = usePersistentState<string>("updateTold", "");
  // MetaTrader is open, but the app is still on made-up prices
  const [canConnect, setCanConnect] = useState(false);
  const [indicatorVersion, setIndicatorVersion] = useState(0);

  const appRef = useRef<HTMLDivElement>(null);

  const activeSymbol = useMemo(
    () => symbols.find((s) => s.name === symbol) ?? null,
    [symbols, symbol],
  );
  const digits = activeSymbol?.digits ?? 5;
  const point = activeSymbol?.point ?? 10 ** -digits;

  /** Round to the symbol's own precision: a broker rejects a price with more decimals. */
  const roundPrice = useCallback((value: number) => Number(value.toFixed(digits)), [digits]);

  // -- initial load: health + symbols --------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const health = await api.health();
        setBroker(health.broker);
        setVersion(health.version ?? null);
        const list = await api.symbols();
        setSymbols(list);
        // Open the first symbol when none is remembered, or when the remembered
        // one is not offered by this broker (e.g. after switching accounts).
        if (list.length && (!symbol || !list.some((s) => s.name === symbol))) {
          setSymbol(list[0].name);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshAccount = useCallback(async () => {
    try {
      const [acc, pos, ord] = await Promise.all([
        api.account(),
        api.positions(),
        api.orders().catch(() => null), // (a server that does not know pending orders has none)
      ]);
      setAccount(acc);
      setPositions(pos);
      if (ord) setOrders(ord);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshDataStats = useCallback(async () => {
    try {
      setDataStats(await api.dataStats());
    } catch {
      /* ignore */
    }
  }, []);

  // -- replay --------------------------------------------------------------------
  // TradingView's flow: click Replay, click a bar to start from, then play or step
  // and trade the paper account. The state machine and the pace live in
  // lib/useReplay.ts. While it runs the chart's candles come from it, handed over
  // through the bridge below (the two hooks need each other, so each reads the
  // other's latest functions instead of calling them directly).
  const chartBridge = useRef<{
    show: (bars: Bar[], view: ViewPolicy) => void;
    append: (bars: Bar[]) => void;
  }>({ show: () => undefined, append: () => undefined });

  /** A stop or a target closed a position while the replay moved on. */
  const onReplayClosed = useCallback((closed: BacktestTrade[]) => {
    if (closed.length > 1) {
      const total = closed.reduce((sum, t) => sum + t.pnl, 0);
      setNotice(`${closed.length} positions closed · ${formatMoney(total, "", true)}`);
      return;
    }
    const t = closed[0];
    const what = t.reason === "tp" ? "Take profit hit" : "Stop loss hit";
    setNotice(`${what} · ${t.side} ${formatLots(t.volume)} · ${formatMoney(t.pnl, "", true)}`);
  }, []);

  const replay = useReplay({
    symbol,
    timeframe,
    showBars: (bars, view) => chartBridge.current.show(bars, view),
    appendBars: (bars) => chartBridge.current.append(bars),
    onError: setError,
    onClosed: onReplayClosed,
    onEnded: () => void profiles.reload(),
  });
  const replayActive = replay.mode === "running";
  const replayPicking = replay.mode === "picking" || replay.mode === "starting";

  // The program that started after an install says how it went (once: a reload does not say it again). While the
  // page is still waiting for that program to come back, the page that reloads is the one to say it.
  const restarting = update.restart !== null;
  const updateResult = update.info?.result ?? null;
  useEffect(() => {
    if (!updateResult || restarting) return;
    const key = `${updateResult.version}:${updateResult.ok}`;
    if (key === updateTold) return;
    setUpdateTold(key);
    setNotice(updateResult.message);
  }, [updateResult, restarting, updateTold, setUpdateTold]);

  // The program is about to close for the update: the window that says so opens by itself.
  useEffect(() => {
    if (restarting) setUpdateOpen(true);
  }, [restarting]);

  // The paper-trading profiles. The replay trades on the active one, so when a profile is chosen,
  // started over or deleted while a replay runs, the account on screen is read again.
  const profiles = useReplayProfiles(() => {
    if (replay.mode === "running") void replay.reloadAccount();
  });
  // A replay beginning or ending changes the profile's numbers (what was left open is settled).
  useEffect(() => {
    void profiles.reload();
  }, [replay.mode, profiles.reload]);

  // -- the bars on the chart --------------------------------------------------
  // The coverage figures in the dock are only refreshed once the dust has settled,
  // so that request never competes with the one the chart is waiting for.
  const statsTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(statsTimer.current), []);
  const onBarsSettled = useCallback(() => {
    window.clearTimeout(statsTimer.current);
    statsTimer.current = window.setTimeout(() => void refreshDataStats(), 600);
  }, [refreshDataStats]);
  const onBarsFailed = useCallback(
    (message: string, shown: ChartFrame) => {
      setError(message);
      // The chart is still on the previous interval: make the header say so.
      if (shown.symbol === symbol && shown.bars.length && shown.timeframe !== timeframe) {
        setTimeframe(shown.timeframe);
      }
    },
    [symbol, timeframe, setTimeframe],
  );

  // What the chart shows follows the symbol / interval / depth asked for, but it
  // never goes blank on the way (see lib/useChartData.ts).
  const viewHintRef = useRef<(() => ViewHint | null) | null>(null);
  const readView = useCallback(() => viewHintRef.current?.() ?? null, []);
  const {
    frame,
    loading: barsLoading,
    showReplayBars,
    appendReplayBars,
    prefetchInterval,
    syncTail,
  } = useChartData({
    symbol,
    timeframe,
    barCount,
    enabled: !replayActive,
    readView,
    onError: onBarsFailed,
    onSettled: onBarsSettled,
  });
  chartBridge.current = { show: showReplayBars, append: appendReplayBars };

  // -- the live market --------------------------------------------------------------------
  // Every tick of the symbol, and the account and positions whenever they change, are
  // pushed by the server (see lib/useLiveFeed.ts); nothing here asks for them.
  const applyState = useCallback((state: StreamState) => {
    setAccount(state.account);
    setPositions(state.positions);
    // An order that is no longer waiting and has a position of its number was filled: say so.
    for (const gone of ordersRef.current) {
      if (state.orders.some((o) => o.ticket === gone.ticket) || cancelledByUs.current.delete(gone.ticket)) continue;
      const position = state.positions.find((p) => p.ticket === gone.ticket);
      if (!position) continue;
      const decimals = symbolsRef.current.find((s) => s.name === position.symbol)?.digits ?? 5;
      setNotice(
        `${kindTitle(gone.order_type)} filled · ${position.side === "BUY" ? "bought" : "sold"} ${formatLots(position.volume)} ${position.symbol} at ${position.price_open.toFixed(decimals)}`,
      );
    }
    setOrders(state.orders);
  }, []);
  const live = useLiveFeed({
    symbol,
    enabled: !replayActive,
    onState: applyState,
    onReconnect: syncTail, // whatever happened while it was down may have been missed
  });
  const tick = live.tick;
  // The broker's clock, learned from its ticks (see lib/serverClock.ts).
  const clock = useServerClock(tick);
  const bars = frame.bars;
  // The interval of the candles on screen: while the next one loads that is still
  // the previous one, and the legend, countdown and live candle must agree with it.
  const shownTimeframe = frame.timeframe;
  // The instrument of those candles. It differs from `activeSymbol` only for the
  // moment between picking a symbol and its candles arriving; the price format and
  // the title must change together with the candles, not before them.
  const shownSymbol = useMemo(
    () => symbols.find((s) => s.name === frame.symbol) ?? null,
    [symbols, frame.symbol],
  );
  // Only worth saying "loading" if it takes a moment.
  const showProgress = useDelayedFlag(barsLoading, 140);

  // Draft SL/TP belong to one symbol; clear them when the symbol *changes* so
  // their price lines cannot distort the new symbol's scale. On the first mount
  // (restored from storage) the values are kept.
  const prevSymbolRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevSymbolRef.current !== null && prevSymbolRef.current !== symbol) {
      setOrderForm((f) => ({ ...f, sl: "", tp: "", price: "" }));
    } else if (prevSymbolRef.current === null) {
      // (the price of a limit order left over from the last visit belongs to a market that moved on)
      setOrderForm((f) => (f.price ? { ...f, price: "" } : f));
    }
    prevSymbolRef.current = symbol;
  }, [symbol, setOrderForm]);

  // The candle being drawn right now: the newest stored bar with the ticks folded
  // into it. It is worked out while rendering, from the very frame the chart is
  // given, so a new set of candles arrives with its live candle already on it
  // instead of a frame later. The candles on screen decide the bucket: while the
  // next interval loads, the old one stays live.
  const frameKey = `${frame.symbol}|${frame.timeframe}`;
  const liveRef = useRef<{ key: string; bar: Bar | null }>({ key: "", bar: null });
  const liveBar = useMemo<Bar | null>(() => {
    // No tick yet, or one for a symbol the chart is not showing.
    if (!live.tick || replayActive || !bars.length || frame.symbol !== symbol) return null;
    const prev = liveRef.current.key === frameKey ? liveRef.current.bar : null;
    // All the ticks since the last frame, not just the newest: the candle's high and
    // low are the terminal's, not those of a sample.
    const batch = live.ticks.length ? live.ticks : [live.tick];
    const next = foldTicks(prev, bars, batch, TF[frame.timeframe].seconds);
    liveRef.current = { key: frameKey, bar: next };
    return next;
  }, [live.tick, live.ticks, bars, frameKey, frame.symbol, frame.timeframe, symbol, replayActive]);

  // The account and positions are pushed; reading them is only the first look and the
  // safety net for a stream that is down (quickly then, lazily while it is up).
  useEffect(() => {
    refreshAccount();
    const id = window.setInterval(refreshAccount, live.connected ? 15_000 : replayActive ? 5_000 : 2_000);
    return () => window.clearInterval(id);
  }, [refreshAccount, live.connected, replayActive]);

  // The newest candles are checked against the terminal's own: a moment after a
  // candle opens (the one before it is final by then; also right after a new symbol or
  // interval is on screen, which covers the gap between the candles and the stream),
  // when the tab comes back, and every so often.
  const newestTime = liveBar?.time ?? null;
  useEffect(() => {
    if (replayActive || newestTime == null) return;
    const id = window.setTimeout(() => void syncTail(), 1_500);
    return () => window.clearTimeout(id);
  }, [replayActive, newestTime, frameKey, syncTail]);
  useEffect(() => {
    if (replayActive) return;
    const check = () => {
      if (!document.hidden) void syncTail();
    };
    const id = window.setInterval(check, 30_000);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", check);
    };
  }, [replayActive, syncTail]);

  const toggleReplay = useCallback(() => {
    if (replay.mode === "off") {
      setError(null);
      replay.open();
    } else {
      replay.exit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay.mode, replay.open, replay.exit]);

  // Replay belongs to one symbol and interval: switching either one ends it,
  // exactly as TradingView does, instead of leaving the old candles under a new
  // symbol's name.
  const replayContextRef = useRef({ symbol, timeframe });
  useEffect(() => {
    const before = replayContextRef.current;
    if (before.symbol === symbol && before.timeframe === timeframe) return;
    replayContextRef.current = { symbol, timeframe };
    if (replay.mode !== "off") replay.exit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe, replay.mode, replay.exit]);

  // A click on a bar starts the replay there while one is being set up, and does
  // nothing otherwise.
  const onBarClick = useCallback(
    (time: number) => {
      if (replay.mode === "picking") void replay.start(time);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replay.mode, replay.start],
  );

  useEffect(() => {
    if (replay.mode !== "picking") setHover(null);
  }, [replay.mode]);

  // Daily and coarser bars carry no time of day worth printing.
  const intraday = TF[timeframe].seconds < 86_400;

  // -- the quote and the instrument ------------------------------------------------
  const lastBar = bars.length ? bars[bars.length - 1] : null;

  // Sell / Buy prices. Live they are the bid and ask; a replay has one price
  // (every paper order fills at the bar close), so both buttons show it.
  const bid = replayActive ? (lastBar?.close ?? null) : tick ? tick.bid || tick.last || null : null;
  const ask = replayActive ? (lastBar?.close ?? null) : tick ? tick.ask || tick.last || null : null;

  // The instrument as the broker describes it just now: what a tick is worth moves with the exchange
  // rates, so the copy from the symbol list is only the fallback (see lib/sizing.ts).
  const [freshSpec, setFreshSpec] = useState<Symbol | null>(null);
  useEffect(() => {
    setFreshSpec(null);
    if (!symbol || replayActive) return;
    let alive = true;
    const load = () => {
      api
        .symbol(symbol)
        .then((s) => alive && setFreshSpec(s))
        .catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [symbol, replayActive]);
  const tradeSpec = freshSpec && freshSpec.name === symbol ? freshSpec : activeSymbol;
  /** How far from the market an order or a stop has to be (price units); a replay has no such rule. */
  const minDistance = replayActive ? 0 : (tradeSpec?.trade_stops_level ?? 0) * (tradeSpec?.point ?? point);

  // -- positions and their levels ------------------------------------------
  // Live positions come from the broker, replay positions from the paper
  // account; the tags, lines and drag handling below treat them the same way.
  const [overrides, setOverrides] = useState<Record<string, LevelOverride>>({});
  const overrideSeq = useRef(0);
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const livePositions = useMemo(() => {
    if (!Object.keys(overrides).length) return positions;
    return positions.map((p) => {
      const sl = overrides[`${p.ticket}:sl`];
      const tp = overrides[`${p.ticket}:tp`];
      return sl || tp ? { ...p, sl: sl ? sl.price : p.sl, tp: tp ? tp.price : p.tp } : p;
    });
  }, [positions, overrides]);
  /** Levels whose change is on its way to the broker, as "ticket:sl" / "ticket:tp". */
  const pendingLevels = useMemo(
    () => new Set(Object.entries(overrides).filter(([, o]) => o.sending).map(([key]) => key)),
    [overrides],
  );
  const chartPositions = useMemo(
    () =>
      (replayActive ? (replay.account?.positions ?? []) : livePositions).filter((p) => p.symbol === symbol),
    [replayActive, replay.account, livePositions, symbol],
  );
  /** Positions with a close on its way to the broker. */
  const [closing, setClosing] = useState<ReadonlySet<number>>(() => new Set());
  /** Which side's market order is on its way to the broker. */
  const [sending, setSending] = useState<"BUY" | "SELL" | null>(null);

  /**
   * Default distance for a position's stop / target when the user asks for one.
   * A fixed percentage is not enough: many brokers reject a level that sits
   * within a minimum distance of the market ("Invalid stops"), so this uses the
   * instrument's typical bar range instead, with the symbol's own minimum as a
   * floor.
   */
  const defaultStopStep = useMemo(() => {
    const minDistance = point * 100; // comfortably clear of broker stop levels
    const recent = bars.slice(-200);
    if (recent.length < 10) {
      const entry = recent.length ? recent[recent.length - 1].close : 0;
      return Math.max(minDistance, entry * 0.0025);
    }
    let sum = 0;
    for (const b of recent) sum += b.high - b.low;
    // Half an average bar range is a conventional default stop.
    // (Three significant figures: it follows the market's range, but a replay adds a
    // bar every tick and nothing downstream should be rebuilt for a change in the fifth digit.)
    return Math.max(minDistance, Number(((sum / recent.length) * 0.5).toPrecision(3)));
  }, [point, bars]);

  const levelsFor = useCallback(
    (p: Position) => ({
      sl: p.sl || roundPrice(p.price_open - defaultStopStep),
      tp: p.tp || roundPrice(p.price_open + defaultStopStep),
      slSet: p.sl > 0,
      tpSet: p.tp > 0,
    }),
    [defaultStopStep, roundPrice],
  );

  /** Move one level on screen without telling the broker (live feedback while dragging). */
  const previewLevel = useCallback(
    (ticket: number, level: Level, price: number) => {
      if (replayActive) {
        replay.patchPositions((list) =>
          list.map((p) =>
            p.ticket !== ticket ? p : level === "sl" ? { ...p, sl: price } : { ...p, tp: price },
          ),
        );
        return;
      }
      const seq = ++overrideSeq.current;
      setOverrides((o) => ({ ...o, [`${ticket}:${level}`]: { price, seq, sending: false } }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replayActive, replay.patchPositions],
  );

  /** Let go of a level that was only being previewed: the broker's own figure shows again. */
  const dropPreview = useCallback((ticket: number, level: Level) => {
    setOverrides((o) => {
      const key = `${ticket}:${level}`;
      if (!(key in o)) return o;
      const next = { ...o };
      delete next[key];
      return next;
    });
  }, []);

  /** A drag that did not end in a change: the line goes back where it was. */
  const restoreLevel = useCallback(
    (ticket: number, level: Level, originalPrice: number) => {
      if (replayActive) previewLevel(ticket, level, originalPrice);
      else dropPreview(ticket, level);
    },
    [replayActive, previewLevel, dropPreview],
  );

  /**
   * Send a level change and reconcile. Live, the new levels are shown straight away
   * and held there (see LevelOverride) until the broker has answered; then the
   * broker's own figures replace them — which also drops any position that has since
   * been closed, so the chart cannot keep drawing a stale stop. `done` is what to say
   * once it went through.
   */
  const modifyLevels = useCallback(
    async (ticket: number, sl: number, tp: number, done?: string) => {
      const started = performance.now();
      let seq = 0;
      if (!replayActive) {
        seq = ++overrideSeq.current;
        setOverrides((o) => ({
          ...o,
          [`${ticket}:sl`]: { price: sl, seq, sending: true },
          [`${ticket}:tp`]: { price: tp, seq, sending: true },
        }));
      }
      try {
        const res = replayActive
          ? await replayApi.modifyPosition(ticket, sl, tp)
          : await api.modifyPosition(ticket, sl, tp);
        if (res && res.ok === false) {
          setError(`Broker refused the change: ${res.error ?? "unknown error"}`);
        } else if (!replayActive && done) {
          setNotice(`${done} · ${Math.round(performance.now() - started)} ms`);
        }
      } catch (err) {
        setError(`Could not update the position: ${(err as Error).message}`);
      } finally {
        // Reconcile even on failure so the drawn line matches reality.
        if (replayActive) {
          void replay.refreshAccount();
        } else {
          await refreshAccount();
          setOverrides((o) => settleOverrides(o, ticket, seq));
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replayActive, refreshAccount, replay.refreshAccount],
  );

  // Persist once, when a level drag ends (on the chart line or on its tag).
  // `delta` is how far the level travelled, so `price - delta` is where it began.
  const commitLevel = useCallback(
    (ticket: number, level: Level, price: number, delta: number) => {
      const pos = chartPositions.find((p) => p.ticket === ticket);
      if (!pos || !delta) {
        // gone, or a stray click that never moved the line
        restoreLevel(ticket, level, price - delta);
        return;
      }

      const candidate = roundPrice(price);

      // Anything on the wrong side of the entry is rejected by the broker as
      // "Invalid stops", so it is caught here with a clear message.
      const problem = levelProblem(pos, level, candidate, digits);
      if (problem) {
        setError(`${problem} The line was put back.`);
        restoreLevel(ticket, level, price - delta);
        return;
      }

      // Only the grabbed level moves; the other one is sent as the broker holds it.
      void modifyLevels(
        ticket,
        level === "sl" ? candidate : pos.sl,
        level === "tp" ? candidate : pos.tp,
        `${levelName(level)} moved to ${candidate.toFixed(digits)}`,
      );
    },
    [chartPositions, roundPrice, digits, restoreLevel, modifyLevels],
  );

  /**
   * Put a stop or target at a price the user picked (a TP / SL button dropped on
   * the chart, or "Set stop loss here" in the right-click menu). Nothing was drawn
   * yet, so a refusal only needs the message.
   */
  const placeLevel = useCallback(
    (ticket: number, level: Level, price: number) => {
      const pos = chartPositions.find((p) => p.ticket === ticket);
      if (!pos) return;
      const candidate = roundPrice(price);
      const problem = levelProblem(pos, level, candidate, digits);
      if (problem) {
        setError(`${problem} Nothing was placed.`);
        return;
      }
      void modifyLevels(
        ticket,
        level === "sl" ? candidate : pos.sl,
        level === "tp" ? candidate : pos.tp,
        `${levelName(level)} set at ${candidate.toFixed(digits)}`,
      );
    },
    [chartPositions, roundPrice, digits, modifyLevels],
  );

  /** Remove a stop or target: sends 0 for that level, leaving the other intact. */
  const clearLevel = useCallback(
    (ticket: number, level: Level) => {
      const pos = chartPositions.find((p) => p.ticket === ticket);
      if (!pos) return;
      if (replayActive) previewLevel(ticket, level, 0); // hide the line now; the reconcile confirms it
      void modifyLevels(
        ticket,
        level === "sl" ? 0 : pos.sl,
        level === "tp" ? 0 : pos.tp,
        `${levelName(level)} removed`,
      );
    },
    [chartPositions, replayActive, previewLevel, modifyLevels],
  );

  /**
   * Create a stop or target at the suggested distance, on the side the broker
   * requires. Its line and tag are then on the chart, ready to be dragged.
   */
  const createLevel = useCallback(
    (ticket: number, level: Level) => {
      const pos = chartPositions.find((p) => p.ticket === ticket);
      if (!pos) return;
      const isBuy = pos.side === "BUY";
      const away = level === "sl" ? !isBuy : isBuy; // up or down from the entry
      const price = roundPrice(pos.price_open + (away ? defaultStopStep : -defaultStopStep));
      void modifyLevels(
        ticket,
        level === "sl" ? price : pos.sl,
        level === "tp" ? price : pos.tp,
        `${levelName(level)} set at ${price.toFixed(digits)}`,
      );
    },
    [chartPositions, defaultStopStep, roundPrice, digits, modifyLevels],
  );

  /** A drag cut short (the window lost focus): the line goes back to where it began. */
  const cancelLevelDrag = useCallback(
    (ticket: number, level: Level, startPrice: number) => restoreLevel(ticket, level, startPrice),
    [restoreLevel],
  );

  // -- orders that wait for their price ---------------------------------------
  // Limit and stop orders (live trading only: a replay fills everything at the bar close). Like a
  // position's levels, an order's price, stop and target can be dragged on the chart; the dragged figure
  // is held in `orderDrafts` until the broker has answered, so the next push from the feed cannot put the
  // old one back under the cursor.
  const [orderBusy, setOrderBusy] = useState<ReadonlySet<number>>(() => new Set());
  const markOrderBusy = useCallback((ticket: number, on: boolean) => {
    setOrderBusy((set) => {
      if (set.has(ticket) === on) return set;
      const next = new Set(set);
      if (on) next.add(ticket);
      else next.delete(ticket);
      return next;
    });
  }, []);
  /** Prices being moved that the broker has not confirmed, as "ticket:price" / "ticket:sl" / "ticket:tp". */
  const [orderDrafts, setOrderDrafts] = useState<Record<string, number>>({});

  const chartOrders = useMemo(() => {
    if (replayActive) return NO_ORDERS;
    const mine = orders.filter((o) => o.symbol === symbol);
    if (!Object.keys(orderDrafts).length) return mine;
    return mine.map((o) => {
      const price = orderDrafts[`${o.ticket}:price`];
      const sl = orderDrafts[`${o.ticket}:sl`];
      const tp = orderDrafts[`${o.ticket}:tp`];
      if (price == null && sl == null && tp == null) return o;
      return { ...o, price: price ?? o.price, sl: sl ?? o.sl, tp: tp ?? o.tp };
    });
  }, [replayActive, orders, symbol, orderDrafts]);
  const ordersKey = chartOrders.map((o) => `${o.ticket}:${o.side}:${o.price}:${o.sl}:${o.tp}`).join("|");

  /**
   * Send an order, to the broker or (in a replay) the paper account, and say what came of it. Resolves
   * with the broker's answer, or null when it was not taken (the refusal has already been shown).
   */
  const submitOrder = useCallback(
    async (order: OrderRequest): Promise<OrderResult | null> => {
      const waits = !!order.order_type;
      if (waits && replayActive) {
        setError("A replay fills everything at the bar close: it has no orders that wait for a price.");
        return null;
      }
      const started = performance.now();
      try {
        let result = replayActive ? await replayApi.placeOrder(order) : await api.placeOrder(order);
        if (!result.ok) {
          setError(`Order refused: ${result.error ?? "unknown error"}`);
          return null;
        }
        // (a broker that leaves the price out of its answer: it is on the position that was opened)
        if (!order.order_type && !replayActive && !(result.price > 0)) {
          const open = await api
            .positions(order.symbol)
            .then((list) => list.find((p) => p.ticket === result.order_id))
            .catch(() => undefined);
          if (open) result = { ...result, price: open.price_open };
        }
        if (!replayActive) {
          const ms = Math.round(performance.now() - started);
          const decimals = symbolsRef.current.find((s) => s.name === order.symbol)?.digits ?? digits;
          const lots = formatLots(result.volume || order.volume);
          setNotice(
            order.order_type
              ? `${kindTitle(order.order_type)} placed · ${lots} ${order.symbol} at ${(order.price ?? 0).toFixed(decimals)} · ${ms} ms`
              : `${order.side === "BUY" ? "Bought" : "Sold"} ${lots} ${order.symbol} at ${result.price.toFixed(decimals)} · ${ms} ms`,
          );
        }
        return result;
      } catch (err) {
        setError((err as Error).message);
        return null;
      } finally {
        void (replayActive ? replay.refreshAccount() : refreshAccount());
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replayActive, refreshAccount, replay.refreshAccount, digits],
  );

  /** Leave an order waiting at the price in the ticket: a limit order, or a stop order when the price is on the other side of the market. */
  const submitPending = useCallback(
    async (side: "BUY" | "SELL") => {
      if (!symbol || replayActive) return;
      if (!(orderForm.volume > 0)) {
        setError("Enter a lot size above zero.");
        return;
      }
      const typed = Number(orderForm.price);
      if (!orderForm.price || !Number.isFinite(typed) || typed <= 0) {
        setError("Enter the price the order should wait for.");
        return;
      }
      if (bid == null || ask == null) {
        setError("There is no quote for this symbol yet.");
        return;
      }
      const price = roundPrice(typed);
      const kind = pendingKind(side, price, bid, ask);
      if (!kind) {
        setError(`${price.toFixed(digits)} is the market price: use Buy / Sell on the Market tab for that.`);
        return;
      }
      const sl = orderForm.sl ? Number(orderForm.sl) : null;
      const tp = orderForm.tp ? Number(orderForm.tp) : null;
      const problem =
        pendingProblem(kind, price, bid, ask, minDistance, digits) ?? levelsProblem(side, price, sl, tp, minDistance, digits);
      if (problem) {
        setError(`${problem} Nothing was placed.`);
        return;
      }
      setSending(side);
      try {
        const placed = await submitOrder({ symbol, side, volume: orderForm.volume, order_type: kind, price, sl, tp });
        // the order has its own line now: the draft one makes way for the next order's price
        if (placed) setOrderForm((f) => ({ ...f, price: "" }));
      } finally {
        setSending(null);
      }
    },
    [symbol, replayActive, orderForm, bid, ask, roundPrice, digits, minDistance, submitOrder, setOrderForm],
  );

  // The Limit tab starts with a price next to the market, so its line is on the chart to drag to where
  // the order should wait. (Nothing is sent until Buy / Sell is pressed.)
  useEffect(() => {
    if (orderForm.type !== "limit" || orderForm.price || replayActive || bid == null || ask == null) return;
    const start = roundPrice((bid + ask) / 2).toFixed(digits);
    setOrderForm((f) => (f.type === "limit" && !f.price ? { ...f, price: start } : f));
  }, [orderForm.type, orderForm.price, replayActive, bid, ask, roundPrice, digits, setOrderForm]);

  /** Let go of the figures being dragged on one order (or just one of them). */
  const dropOrderDraft = useCallback((ticket: number, part?: OrderPart) => {
    setOrderDrafts((all) => {
      const gone = Object.keys(all).filter((key) => (part ? key === `${ticket}:${part}` : key.startsWith(`${ticket}:`)));
      if (!gone.length) return all;
      const next = { ...all };
      for (const key of gone) delete next[key];
      return next;
    });
  }, []);

  /** Take a waiting order back. */
  const cancelOrder = useCallback(
    async (ticket: number) => {
      const order = ordersRef.current.find((o) => o.ticket === ticket);
      const started = performance.now();
      markOrderBusy(ticket, true);
      cancelledByUs.current.add(ticket); // it disappearing from the feed is no news
      try {
        const res = await api.cancelOrder(ticket);
        if (res && res.ok === false) {
          cancelledByUs.current.delete(ticket);
          setError(`Broker refused to take the order back: ${res.error ?? "unknown error"}`);
        } else if (order) {
          const decimals = symbolsRef.current.find((s) => s.name === order.symbol)?.digits ?? digits;
          setNotice(`${kindTitle(order.order_type)} taken back · ${order.symbol} at ${order.price.toFixed(decimals)} · ${Math.round(performance.now() - started)} ms`);
        }
      } catch (err) {
        cancelledByUs.current.delete(ticket);
        setError(`Could not take the order back: ${(err as Error).message}`);
      } finally {
        await refreshAccount();
        markOrderBusy(ticket, false);
      }
    },
    [markOrderBusy, refreshAccount, digits],
  );

  /** Move a waiting order's price, or change its stop loss / take profit (0 removes one). `done` is what to say afterwards. */
  const modifyOrder = useCallback(
    async (ticket: number, change: { price?: number; sl?: number; tp?: number }, done: string) => {
      markOrderBusy(ticket, true);
      const started = performance.now();
      try {
        const res = await api.modifyOrder(ticket, change);
        if (res && res.ok === false) setError(`Broker refused the change: ${res.error ?? "unknown error"}`);
        else setNotice(`${done} · ${Math.round(performance.now() - started)} ms`);
      } catch (err) {
        setError(`Could not change the order: ${(err as Error).message}`);
      } finally {
        // (reconcile even on failure, so what is drawn is what the broker holds)
        await refreshAccount();
        dropOrderDraft(ticket);
        markOrderBusy(ticket, false);
      }
    },
    [markOrderBusy, refreshAccount, dropOrderDraft],
  );

  const previewOrder = useCallback((ticket: number, part: OrderPart, price: number) => {
    setOrderDrafts((all) => ({ ...all, [`${ticket}:${part}`]: price }));
  }, []);

  /** Persist a price once its drag has ended. */
  const commitOrder = useCallback(
    (ticket: number, part: OrderPart, price: number, delta: number) => {
      const order = ordersRef.current.find((o) => o.ticket === ticket);
      if (!order || !delta) {
        dropOrderDraft(ticket, part); // gone, or a stray click that never moved it
        return;
      }
      const next = roundPrice(price);
      const entry = part === "price" ? next : order.price;
      const sl = part === "sl" ? next : order.sl;
      const tp = part === "tp" ? next : order.tp;
      // A kind of order cannot cross the market (a buy limit stays below the buy price): a different
      // kind is a different order, so that has to be cancelled and placed again.
      const problem =
        (part === "price" && bid != null && ask != null
          ? pendingProblem(order.order_type, next, bid, ask, minDistance, digits)
          : null) ?? levelsProblem(order.side, entry, sl, tp, minDistance, digits);
      if (problem) {
        setError(`${problem} The line was put back.`);
        dropOrderDraft(ticket, part);
        return;
      }
      void modifyOrder(ticket, { [part]: next }, `${orderPartName(part)} moved to ${next.toFixed(digits)}`);
    },
    [dropOrderDraft, roundPrice, bid, ask, minDistance, digits, modifyOrder],
  );

  const cancelOrderDrag = useCallback((ticket: number, part: OrderPart) => dropOrderDraft(ticket, part), [dropOrderDraft]);

  /** Remove an order's stop loss or take profit. */
  const clearOrderLevel = useCallback(
    (ticket: number, part: "sl" | "tp") => {
      previewOrder(ticket, part, 0); // hide it now; the broker's answer confirms
      void modifyOrder(ticket, { [part]: 0 }, `${orderPartName(part)} removed`);
    },
    [previewOrder, modifyOrder],
  );

  /** "Set stop loss here" for an order that waits. */
  const placeOrderLevel = useCallback(
    (ticket: number, part: "sl" | "tp", price: number) => {
      const order = ordersRef.current.find((o) => o.ticket === ticket);
      if (!order) return;
      const next = roundPrice(price);
      const problem = levelsProblem(
        order.side,
        order.price,
        part === "sl" ? next : order.sl,
        part === "tp" ? next : order.tp,
        minDistance,
        digits,
      );
      if (problem) {
        setError(`${problem} Nothing was placed.`);
        return;
      }
      previewOrder(ticket, part, next);
      void modifyOrder(ticket, { [part]: next }, `${orderPartName(part)} set at ${next.toFixed(digits)}`);
    },
    [roundPrice, minDistance, digits, previewOrder, modifyOrder],
  );

  // Live feedback while a single chart line moves. Only the dragged line changes.
  const onLineDrag = useCallback(
    (id: string, price: number) => {
      if (id === "draft-sl") {
        setOrderForm((f) => ({ ...f, sl: price.toFixed(digits) }));
        return;
      }
      if (id === "draft-tp") {
        setOrderForm((f) => ({ ...f, tp: price.toFixed(digits) }));
        return;
      }
      if (id === "draft-price") {
        setOrderForm((f) => ({ ...f, price: price.toFixed(digits) }));
        return;
      }
      const waiting = ORDER_LINE.exec(id);
      if (waiting) {
        previewOrder(Number(waiting[2]), ORDER_PARTS[waiting[1]], price);
        return;
      }
      const match = /^(sl|tp)-(\d+)$/.exec(id);
      if (match) previewLevel(Number(match[2]), match[1] as Level, price); // the entry never drags
    },
    [digits, previewLevel, previewOrder, setOrderForm],
  );

  const onLineDragEnd = useCallback(
    (id: string, price: number, delta: number) => {
      const waiting = ORDER_LINE.exec(id);
      if (waiting) {
        commitOrder(Number(waiting[2]), ORDER_PARTS[waiting[1]], price, delta);
        return;
      }
      const match = /^(sl|tp)-(\d+)$/.exec(id);
      if (match) commitLevel(Number(match[2]), match[1] as Level, price, delta);
    },
    [commitLevel, commitOrder],
  );

  // -- chart price lines ---------------------------------------------------
  // Draft SL/TP from the ticket are drawn so levels can be set before the order
  // is sent. Each open position adds its entry line plus a line per level that
  // exists; their details live in the tags (PositionOverlay), not in line titles.
  // (Keyed on where positions were opened and their levels: their floating profit
  // changes with every bar of a replay and must not rebuild the lines each time.)
  const linesKey = chartPositions
    .map((p) => `${p.ticket}:${p.side}:${p.price_open}:${p.sl}:${p.tp}`)
    .join("|");
  const priceLines = useMemo<PriceLineSpec[]>(() => {
    const lines: PriceLineSpec[] = [];

    const draftSl = Number(orderForm.sl);
    if (orderForm.sl && Number.isFinite(draftSl)) {
      lines.push({ id: "draft-sl", price: draftSl, color: LINE_COLORS.sl, title: "SL", lineStyle: 2 });
    }
    const draftTp = Number(orderForm.tp);
    if (orderForm.tp && Number.isFinite(draftTp)) {
      lines.push({ id: "draft-tp", price: draftTp, color: LINE_COLORS.tp, title: "TP", lineStyle: 2 });
    }
    // Where the ticket's limit / stop order would wait (the Limit tab); drag it to choose the price.
    const draftPrice = Number(orderForm.price);
    if (!replayActive && orderForm.type === "limit" && orderForm.price && Number.isFinite(draftPrice) && draftPrice > 0) {
      lines.push({ id: "draft-price", price: draftPrice, color: LINE_COLORS.draft, title: "Order", lineStyle: 2 });
    }

    // Orders that wait: dashed, in the colour of their side; their details are in the tags (OrderOverlay).
    for (const o of chartOrders) {
      lines.push({ id: `order-${o.ticket}`, price: o.price, color: o.side === "BUY" ? LINE_COLORS.buy : LINE_COLORS.sell, title: "", lineStyle: 2 });
      if (o.sl > 0) lines.push({ id: `osl-${o.ticket}`, price: o.sl, color: LINE_COLORS.sl, title: "", lineStyle: 2 });
      if (o.tp > 0) lines.push({ id: `otp-${o.ticket}`, price: o.tp, color: LINE_COLORS.tp, title: "", lineStyle: 2 });
    }

    for (const p of chartPositions) {
      const lv = levelsFor(p);
      lines.push({
        id: `entry-${p.ticket}`,
        price: p.price_open,
        color: p.side === "BUY" ? LINE_COLORS.buy : LINE_COLORS.sell,
        title: "",
        draggable: false, // the entry is the broker's; only SL and TP move
      });
      if (lv.slSet) {
        lines.push({ id: `sl-${p.ticket}`, price: p.sl, color: LINE_COLORS.sl, title: "" });
      }
      if (lv.tpSet) {
        lines.push({ id: `tp-${p.ticket}`, price: p.tp, color: LINE_COLORS.tp, title: "" });
      }
    }
    return lines;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderForm.sl, orderForm.tp, orderForm.type, orderForm.price, replayActive, ordersKey, linesKey, levelsFor]);

  // -- trading -------------------------------------------------------------
  const trade = useCallback(
    async (side: "BUY" | "SELL") => {
      if (!symbol) return;
      if (!(orderForm.volume > 0)) {
        setError("Enter a lot size above zero.");
        return;
      }
      if (!replayActive) setSending(side);
      try {
        await submitOrder({
          symbol,
          side,
          volume: orderForm.volume,
          sl: orderForm.sl ? Number(orderForm.sl) : null,
          tp: orderForm.tp ? Number(orderForm.tp) : null,
        });
      } finally {
        setSending(null);
      }
    },
    [symbol, orderForm, replayActive, submitOrder],
  );

  /** Close a position from its on-chart tag or the Trade panel. */
  const closePosition = useCallback(
    (ticket: number) => {
      const started = performance.now();
      const position = replayActive ? undefined : positionsRef.current.find((p) => p.ticket === ticket);
      if (!replayActive) setClosing((set) => new Set(set).add(ticket));
      (replayActive ? replayApi.closePosition(ticket) : api.closePosition(ticket))
        .then((res) => {
          if (res && res.ok === false) {
            setError(`Broker refused to close the position: ${res.error ?? "unknown error"}`);
          } else if (position) {
            const ms = Math.round(performance.now() - started);
            setNotice(`Closed ${position.symbol} ${formatLots(position.volume)} · ${ms} ms`);
          }
        })
        .catch((err) => setError(`Could not close the position: ${(err as Error).message}`))
        .finally(() => {
          void (replayActive ? replay.refreshAccount() : refreshAccount());
          setClosing((set) => {
            const next = new Set(set);
            next.delete(ticket);
            return next;
          });
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replayActive, refreshAccount, replay.refreshAccount],
  );

  // -- indicators ----------------------------------------------------------
  const toggleIndicator = useCallback(
    (id: string) => {
      setActiveIndicators((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
    },
    [setActiveIndicators],
  );

  // Run active indicators whenever they, the symbol, or the timeframe change.
  useEffect(() => {
    if (!symbol || activeIndicators.length === 0) {
      setIndicatorSet(NO_INDICATORS);
      return;
    }
    const key = `${symbol}|${timeframe}`;
    let cancelled = false;
    (async () => {
      const plots: IndicatorPlot[] = [];
      const legend: LegendIndicator[] = [];
      const drawings: Drawing[] = [];
      const missing: string[] = [];
      // Every indicator that is not an overlay gets a pane of its own, in the order they were added.
      // Sharing one (two oscillators each asking for "pane 1") would draw RSI's 0-100 and MACD's
      // 0.001 on one scale, and one of them would be a flat line.
      let nextPane = 1;
      for (const id of activeIndicators) {
        try {
          const result = await indicatorApi.run(id, symbol, timeframe, 500);
          if (result.error) {
            setError(`Indicator "${result.name}": ${result.error}`);
            continue;
          }
          const pane = result.overlay || result.plots.length === 0 ? 0 : nextPane++;
          const colors = result.plots.map((p, i) => p.color ?? PLOT_COLORS[i % PLOT_COLORS.length]);
          result.plots.forEach((p, i) => {
            plots.push({
              name: p.name,
              color: colors[i],
              pane,
              type: p.type === "histogram" ? "histogram" : "line",
              data: p.data,
            });
          });
          legend.push({ id, name: result.name, colors, pane });
          (result.drawings ?? []).forEach((d, i) => {
            drawings.push({ ...d, id: `${id}:${d.id || i}`, owner: id });
          });
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            missing.push(id); // the indicator was deleted: drop it from the chart
          } else {
            setError((err as Error).message);
          }
        }
      }
      if (cancelled) return;
      setIndicatorSet({ key, plots, legend, drawings });
      if (missing.length) {
        setActiveIndicators((ids) => ids.filter((x) => !missing.includes(x)));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe, activeIndicators, indicatorVersion, setActiveIndicators]);

  // Values computed for another interval than the candles on screen would sit on
  // the wrong bars. Until the right ones arrive the plots keep their shape (so the
  // sub-panes stay where they are) but carry no values.
  const livePlots = useMemo(
    () =>
      indicatorSet.key === frameKey
        ? indicatorSet.plots
        : indicatorSet.plots.map((p) => ({ ...p, data: [] })),
    [indicatorSet, frameKey],
  );
  // Shapes an indicator drew for another symbol or interval do not belong on these candles.
  const liveDrawings = indicatorSet.key === frameKey ? indicatorSet.drawings : NO_DRAWINGS;

  // Indicators are computed on live data, so during a replay they would draw
  // values from after the cursor and give the future away. Clip them to it.
  const cursorTime = replayActive && bars.length ? bars[bars.length - 1].time : 0;
  const shownPlots = useMemo(() => {
    if (!replayActive || !cursorTime) return livePlots;
    return livePlots.map((p) => ({ ...p, data: p.data.filter((d) => d.time <= cursorTime) }));
  }, [livePlots, replayActive, cursorTime]);
  // The same goes for drawings: one is shown once the replay has reached all of its points
  // (a horizontal line has no time, so it is always shown).
  const shownDrawings = useMemo(() => {
    if (!replayActive || !cursorTime) return liveDrawings;
    return liveDrawings.filter((d) => d.type === "hline" || d.points.every((p) => p.time <= cursorTime));
  }, [liveDrawings, replayActive, cursorTime]);
  const overlayLegend = useMemo(() => indicatorSet.legend.filter((l) => l.pane === 0), [indicatorSet.legend]);
  const paneLegend = useMemo(() => indicatorSet.legend.filter((l) => l.pane > 0), [indicatorSet.legend]);

  // -- shell actions -------------------------------------------------------
  const resetView = useCallback(() => setFitSignal((v) => v + 1), []);

  const toggleFullscreen = useCallback(() => {
    const el = appRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.().catch(() => undefined);
  }, []);

  // Keep the header button in sync when the user leaves fullscreen with Esc.
  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  /** Header buttons: open the panel on that tab, or hide it if it is already showing it. */
  const toggleDock = useCallback(
    (tab: DockTab) => {
      if (showDock && panel === tab) {
        setShowDock(false);
      } else {
        setPanel(tab);
        setShowDock(true);
      }
    },
    [showDock, panel, setPanel, setShowDock],
  );

  const openIndicatorPanel = useCallback(() => {
    setPanel("indicators");
    setShowDock(true);
  }, [setPanel, setShowDock]);

  // -- the welcome tour ---------------------------------------------------------
  const closeTour = useCallback(() => {
    setTourSeen(true);
    setTour(null);
  }, [setTourSeen]);

  // The page starts over once the app has connected to MetaTrader; the tour comes back to the step it was on.
  useEffect(() => {
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(RESUME_KEY);
      sessionStorage.removeItem(RESUME_KEY);
    } catch {
      /* private mode */
    }
    const step = resumeStep(raw);
    if (step !== null) setTour(step);
  }, []);

  // The first time the app is started (once it knows what it is connected to): the tour.
  useEffect(() => {
    if (broker && !tourSeen && tour === null) setTour(0);
  }, [broker, tourSeen, tour]);

  // On made-up prices: is MetaTrader open by now? (The strip at the bottom then offers to connect.)
  useEffect(() => {
    if (broker !== "mock") {
      setCanConnect(false);
      return;
    }
    let live = true;
    const look = () =>
      api
        .terminal()
        .then((s) => live && setCanConnect(s.can_connect))
        .catch(() => undefined);
    void look();
    const id = window.setInterval(look, 15_000);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, [broker]);

  // -- right-click menu ------------------------------------------------------
  /**
   * Replaces the browser's own menu ("Save image as…") on the chart with ours.
   * Text fields keep the browser's menu (cut / copy / paste), and the replay
   * dialog and controls get no menu at all.
   */
  const onChartContextMenu = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea")) return;
      e.preventDefault();
      if (target.closest(".rp-picker, .rp-bar, .rp-report, .dr-bar, .dr-style")) {
        setChartMenu(null);
        return;
      }
      // The price under the pointer — only meaningful over the price pane, not
      // over the time axis or an indicator's sub-pane.
      let price: number | null = null;
      if (chartGeom) {
        const local = e.clientY - chartGeom.containerTop();
        if (local >= 0 && local <= chartGeom.paneHeight()) price = chartGeom.localYToPrice(local);
      }
      setChartMenu({ x: e.clientX, y: e.clientY, price });
    },
    [chartGeom],
  );

  // A menu belongs to the chart it was opened on.
  useEffect(() => setChartMenu(null), [symbol, timeframe, replayActive]);

  const chartMenuItems = useMemo<ContextMenuItem[]>(() => {
    if (!chartMenu) return [];
    const items: ContextMenuItem[] = [];
    const price = chartMenu.price;
    if (price != null) {
      const text = price.toFixed(digits);
      items.push({
        key: "copy-price",
        label: `Copy price ${text}`,
        onSelect: () => {
          void copyText(text).then((ok) =>
            ok ? setNotice(`Copied ${text}`) : setError("Could not copy to the clipboard."),
          );
        },
      });

      // Right of the entry or left of it decides whether this price is a stop or a
      // target for each open position, so only the one that makes sense is offered.
      const at = roundPrice(price);

      // An order that waits at this price: a buy and a sell, each a limit order or (on the other side
      // of the market) a stop order. They carry the ticket's lot size and nothing else; the stop and
      // target of a waiting order are set from this menu or by dragging its lines.
      if (!replayActive && symbol && bid != null && ask != null && orderForm.volume > 0) {
        let firstOrder = true;
        for (const side of ["BUY", "SELL"] as const) {
          const kind = pendingKind(side, at, bid, ask);
          if (!kind) continue;
          const problem = pendingProblem(kind, at, bid, ask, minDistance, digits);
          items.push({
            key: `pending-${side}`,
            label: `${kindTitle(kind)} ${formatLots(orderForm.volume)} lots at ${at.toFixed(digits)}`,
            note: problem ?? undefined,
            tone: side === "BUY" ? "buy" : "sell",
            disabled: !!problem,
            separatorBefore: firstOrder,
            onSelect: () => void submitOrder({ symbol, side, volume: orderForm.volume, order_type: kind, price: at }),
          });
          firstOrder = false;
        }
      }

      let first = true;
      for (const p of chartPositions) {
        const kind = levelKindAt(p, at);
        if (!kind) continue;
        const lv = levelsFor(p);
        const verb = (kind === "sl" ? lv.slSet : lv.tpSet) ? "Move" : "Set";
        const noun = kind === "sl" ? "stop loss" : "take profit";
        const which = chartPositions.length > 1 ? ` · ${p.side} ${formatLots(p.volume)}` : "";
        items.push({
          key: `${kind}-${p.ticket}`,
          label: `${verb} ${noun} here${which}`,
          separatorBefore: first,
          onSelect: () => placeLevel(p.ticket, kind, price),
        });
        first = false;
      }
      for (const o of chartOrders) {
        const kind = orderLevelKindAt(o.side, o.price, at);
        if (!kind) continue;
        const verb = (kind === "sl" ? o.sl : o.tp) > 0 ? "Move" : "Set";
        const noun = kind === "sl" ? "stop loss" : "take profit";
        items.push({
          key: `order-${kind}-${o.ticket}`,
          label: `${verb} ${noun} here · ${kindTitle(o.order_type)} ${formatLots(o.volume)}`,
          separatorBefore: first,
          onSelect: () => placeOrderLevel(o.ticket, kind, price),
        });
        first = false;
      }
    }
    items.push({
      key: "reset-view",
      label: "Reset chart view",
      hint: "F",
      separatorBefore: items.length > 0,
      onSelect: resetView,
    });
    return items;
  }, [
    chartMenu,
    digits,
    roundPrice,
    chartPositions,
    chartOrders,
    levelsFor,
    placeLevel,
    placeOrderLevel,
    replayActive,
    symbol,
    bid,
    ask,
    minDistance,
    orderForm.volume,
    submitOrder,
    resetView,
  ]);

  // -- keyboard shortcuts ----------------------------------------------------
  // (Read through a ref, so the listeners are not taken down and put up again with
  // every bar of a replay.)
  const replayRef = useRef(replay);
  replayRef.current = replay;
  useEffect(() => {
    const isTyping = (target: HTMLElement | null) =>
      target &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable);

    function onKey(e: KeyboardEvent) {
      if (isTyping(e.target as HTMLElement | null)) return;
      const r = replayRef.current;

      if (e.key === "Escape" && r.mode !== "off") {
        r.exit();
        return;
      }
      if (r.mode === "running" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (e.key === " ") {
          e.preventDefault();
          r.toggle();
          return;
        }
        if (e.key === "ArrowRight") {
          e.preventDefault();
          void r.step(1);
          return;
        }
      }
      if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey) {
        resetView();
      }
    }
    // A space also presses the button that has the focus when it is released.
    function onKeyUp(e: KeyboardEvent) {
      if (e.key === " " && replayRef.current.mode === "running" && !isTyping(e.target as HTMLElement | null)) {
        e.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [resetView]);

  // -- derived readouts for the chart overlays -----------------------------------
  // The candle currently being drawn: the live-updated one, or the replay cursor's.
  const currentBar = replayActive ? lastBar : (liveBar ?? lastBar);

  const spread =
    !replayActive && tick && tick.bid && tick.ask
      ? spreadInPips(tick.bid, tick.ask, digits, point)
      : null;

  const legendTrade: LegendTrade | null = replayPicking
    ? null
    : {
        bid,
        ask,
        digits,
        spread,
        volume: orderForm.volume,
        onVolumeChange: (volume) => setOrderForm((f) => ({ ...f, volume })),
        disabled: !symbol,
        busy: sending,
        onBuy: () => void trade("BUY"),
        onSell: () => void trade("SELL"),
      };

  // The history figures under the chart describe the whole series. While only the
  // opening window of a new one is in, they keep the last complete figures instead
  // of flickering to a smaller count and back. A replay shows its loaded window.
  const lastRange = useRef<RangeInfo>({ from: null, to: null, bars: null });
  const rangeInfo = useMemo<RangeInfo>(() => {
    if (replayActive && replay.state) {
      return { from: replay.state.first_time, to: replay.state.last_time, bars: replay.state.total };
    }
    if (frame.complete) {
      lastRange.current = bars.length
        ? { from: bars[0].time, to: bars[bars.length - 1].time, bars: bars.length }
        : { from: null, to: null, bars: null };
    }
    return lastRange.current;
  }, [replayActive, replay.state, frame.complete, bars]);

  // Where the replay's trades opened and closed, drawn on the candles. Keyed on
  // the trades and on where each open position began, not on its floating profit.
  const openKey = chartPositions.map((p) => `${p.ticket}:${p.time}:${p.side}:${p.volume}`).join("|");
  const markers = useMemo(
    () => (replayActive ? replayMarkers(replay.trades, chartPositions, symbol) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [replayActive, replay.trades, openKey, symbol],
  );

  // The paper-trading profile menu: where a replay is set up and in the panel beside it while it runs.
  const profileMenu = (variant: "pill" | "field") => (
    <ProfileMenu
      view={profiles.view}
      busy={profiles.busy}
      error={profiles.error}
      onClearError={profiles.clearError}
      onOpen={profiles.reload}
      running={replayActive}
      live={
        replayActive && replay.account
          ? { balance: replay.account.balance, openPositions: replay.account.positions.length }
          : null
      }
      variant={variant}
      onCreate={profiles.create}
      onSelect={profiles.select}
      onRename={profiles.rename}
      onReset={profiles.reset}
      onDelete={profiles.remove}
    />
  );

  const source = broker === "mt5" ? "MetaTrader 5" : broker === "mock" ? "Mock data" : broker;

  // What a long / short box needs to place its trade: the account, the market and the way to send orders.
  const boxTrading = useMemo<BoxTrading>(
    () => ({
      enabled: !!symbol && !replayPicking,
      paper: replayActive,
      symbol: tradeSpec,
      digits,
      bid,
      ask,
      balance: replayActive ? (replay.account?.balance ?? null) : (account?.balance ?? null),
      currency: replayActive ? "" : (account?.currency ?? ""),
      positions: chartPositions,
      place: submitOrder,
      setLevels: (ticket, sl, tp) => void modifyLevels(ticket, sl, tp, "Stop loss and take profit set from the box"),
    }),
    [symbol, replayPicking, replayActive, tradeSpec, digits, bid, ask, replay.account, account, chartPositions, submitOrder, modifyLevels],
  );

  return (
    <div className="tv-app" ref={appRef}>
      <TopNav
        symbol={symbol}
        timeframe={timeframe}
        onTimeframe={setTimeframe}
        onPrefetch={prefetchInterval}
        onOpenSymbolSearch={() => setSearchOpen(true)}
        indicatorsOpen={showDock && panel === "indicators"}
        tradeOpen={showDock && panel === "trade"}
        onToggleIndicators={() => toggleDock("indicators")}
        onToggleTrade={() => toggleDock("trade")}
        replayActive={replay.mode !== "off"}
        onReplay={toggleReplay}
        fullscreen={isFullscreen}
        onToggleFullscreen={toggleFullscreen}
        update={updateChip(update.info)}
        onUpdate={() => setUpdateOpen(true)}
      />

      <div className="tv-body">
        <div className="tv-main">
          <div className="tv-chart-card">
            <div className="tv-chart-canvas" onContextMenu={onChartContextMenu}>
              <ChartBoundary>
                {(generation) => (
              <Chart
                key={generation}
                bars={bars}
                liveBar={liveBar}
                priceLines={priceLines}
                markers={markers}
                indicatorPlots={shownPlots}
                digits={shownSymbol?.digits}
                point={shownSymbol?.point}
                symbol={frame.symbol ?? undefined}
                timeframe={TF[shownTimeframe].legend}
                barSeconds={TF[shownTimeframe].seconds}
                view={frame.view}
                loading={showProgress}
                fitSignal={fitSignal}
                viewHintRef={viewHintRef}
                onLineDrag={onLineDrag}
                onLineDragEnd={onLineDragEnd}
                onGeometry={setChartGeom}
                onLegend={setLegend}
                onBarClick={onBarClick}
                onHover={replay.mode === "picking" ? setHover : undefined}
              />
                )}
              </ChartBoundary>

              <ChartLegend
                values={legend}
                title={shownSymbol?.description || frame.symbol || symbol || ""}
                interval={TF[shownTimeframe].legend}
                source={source}
                liveAt={replayActive ? null : live.connected && live.feedUp ? clock.freshAt : 0}
                lagging={live.feedSlow}
                trade={legendTrade}
                indicators={overlayLegend}
                onManageIndicators={openIndicatorPanel}
              />

              <PaneLegends geometry={chartGeom} rows={paneLegend} onManage={openIndicatorPanel} />

              <DrawingController
                geometry={chartGeom}
                symbol={frame.symbol ?? symbol}
                digits={digits}
                bars={bars}
                barSeconds={TF[shownTimeframe].seconds}
                indicatorDrawings={shownDrawings}
                paused={replayPicking}
                trading={boxTrading}
                onDocs={() => setDocs("drawings")}
                onError={setError}
                onNotice={setNotice}
              />

              <PriceTags
                geometry={chartGeom}
                digits={digits}
                last={currentBar?.close ?? null}
                up={currentBar ? currentBar.close >= currentBar.open : true}
                ask={replayActive ? null : (tick?.ask ?? null)}
                barClose={
                  !replayActive && currentBar && shownTimeframe !== "MN1"
                    ? currentBar.time + TF[shownTimeframe].seconds
                    : null
                }
                serverSkew={clock.skew}
              />

              {showProgress && <div className="tv-chart-progress" role="progressbar" aria-label="Loading chart" />}

              <PositionOverlay
                positions={chartPositions}
                digits={digits}
                currency={replayActive ? "" : (account?.currency ?? "")}
                geometry={chartGeom}
                levelsFor={levelsFor}
                onCreateLevel={createLevel}
                onPlaceLevel={placeLevel}
                onClearLevel={clearLevel}
                onDragLevel={previewLevel}
                onCommitLevel={commitLevel}
                onCancelDrag={cancelLevelDrag}
                onClosePosition={closePosition}
                closing={closing}
                pending={pendingLevels}
              />

              {!replayActive && (
                <OrderOverlay
                  orders={chartOrders}
                  digits={digits}
                  geometry={chartGeom}
                  onDrag={previewOrder}
                  onCommit={commitOrder}
                  onCancelDrag={cancelOrderDrag}
                  onCancel={cancelOrder}
                  onClearLevel={clearOrderLevel}
                  busy={orderBusy}
                />
              )}

              {replayPicking && (
                <>
                  <ReplayCut
                    hover={replay.mode === "picking" ? hover : null}
                    geometry={chartGeom}
                    bars={bars}
                    intraday={intraday}
                  />
                  <ReplayPicker
                    symbol={symbol ?? ""}
                    timeframe={timeframe}
                    newestTime={bars.length ? bars[bars.length - 1].time : null}
                    oldestTime={bars.length ? bars[0].time : null}
                    starting={replay.mode === "starting"}
                    profileMenu={profileMenu("pill")}
                    onStartAt={(time) => void replay.start(time)}
                    onCancel={replay.exit}
                  />
                </>
              )}

              {replayActive && replay.state && (
                <ReplayToolbar
                  state={replay.state}
                  playing={replay.playing}
                  speed={replay.speed}
                  speeds={REPLAY_SPEEDS}
                  intraday={intraday}
                  onToggle={replay.toggle}
                  onStep={() => void replay.step(1)}
                  onSpeed={replay.setSpeed}
                  onJumpToEnd={() => void replay.jumpToEnd()}
                  onPickAgain={replay.pickAgain}
                  onExit={replay.exit}
                />
              )}
            </div>

            <BottomToolbar
              range={rangeInfo}
              barCount={barCount}
              barSteps={BAR_STEPS}
              onBarCount={setBarCount}
              depthLocked={replayActive || replayPicking}
              utcOffsetHours={clock.offsetHours}
              onFit={resetView}
            />
          </div>

          {replayActive && replay.reportOpen && (
            <ReplayReport
              report={replay.report}
              account={replay.account}
              cursorTime={replay.state?.cursor_time ?? 0}
              intraday={intraday}
              digits={digits}
              title={`${symbol ?? ""} · ${TF[timeframe].short}`}
              onClose={replay.toggleReport}
            />
          )}

          <AccountStrip
            mode={replayActive ? "replay" : "live"}
            broker={broker}
            account={account}
            positionCount={positions.length}
            paper={replay.account}
            reportOpen={replay.reportOpen}
            onToggleReport={replay.toggleReport}
            canConnect={canConnect}
            onConnect={() => setTour(METATRADER_STEP)}
          />
        </div>

        {showDock && (
          <Dock tab={panel} onTab={setPanel} onClose={() => setShowDock(false)}>
            {panel === "indicators" ? (
              <IndicatorManager
                activeIds={activeIndicators}
                onToggle={toggleIndicator}
                onChanged={() => setIndicatorVersion((v) => v + 1)}
                onDocs={() => setDocs("indicators")}
              />
            ) : replayActive ? (
              <ReplayTradePanel
                symbol={symbol}
                price={lastBar ? lastBar.close : null}
                digits={digits}
                account={replay.account}
                trades={replay.trades}
                intraday={intraday}
                form={orderForm}
                onFormChange={setOrderForm}
                onRefresh={replay.refreshAccount}
                onClosePosition={closePosition}
                profileMenu={profileMenu("field")}
                onOpenReport={() => {
                  if (!replay.reportOpen) replay.toggleReport();
                }}
              />
            ) : (
              <>
                <OrderPanel
                  symbol={symbol}
                  tick={tick}
                  positions={livePositions}
                  closing={closing}
                  orders={orders}
                  cancelling={orderBusy}
                  form={orderForm}
                  digits={digits}
                  onFormChange={setOrderForm}
                  onRefresh={refreshAccount}
                  onClosePosition={closePosition}
                  onSubmitPending={submitPending}
                  onCancelOrder={cancelOrder}
                />
                <DataCoverage stats={dataStats} symbol={symbol} timeframe={timeframe} />
              </>
            )}
          </Dock>
        )}

        {showWatchlist && (
          <RightPanel
            symbols={symbols}
            selected={symbol}
            onSelect={setSymbol}
            pinned={pinnedSymbols}
            onPinnedChange={setPinnedSymbols}
            onClose={() => setShowWatchlist(false)}
          />
        )}

        <RightRail
          watchlistOpen={showWatchlist}
          onToggleWatchlist={() => setShowWatchlist((v) => !v)}
          onDocs={() => setDocs("getting_started")}
          onTour={() => setTour(0)}
          onAbout={() => setAbout(true)}
        />
      </div>

      {chartMenu && (
        <ChartContextMenu x={chartMenu.x} y={chartMenu.y} items={chartMenuItems} onClose={closeChartMenu} />
      )}

      {error ? (
        <Toast message={error} onDismiss={dismissError} />
      ) : notice ? (
        <Toast message={notice} tone="info" duration={updateResult && notice === updateResult.message ? 9000 : undefined} onDismiss={dismissNotice} />
      ) : null}

      {tour !== null && (
        <WelcomeTour
          start={tour}
          onClose={closeTour}
          onDocs={setDocs}
          onIndicators={() => {
            closeTour();
            openIndicatorPanel();
          }}
          onAbout={() => setAbout(true)}
        />
      )}

      {about && (
        <AboutDialog
          version={version}
          onClose={() => setAbout(false)}
          onDocs={setDocs}
          onTour={() => {
            setAbout(false);
            setTour(0);
          }}
          update={{
            info: update.info,
            busy: update.busy,
            onCheck: () => void update.check(),
            onEnabled: (enabled) => void update.setEnabled(enabled),
            onOpen: () => {
              setAbout(false);
              setUpdateOpen(true);
            },
          }}
        />
      )}

      {updateOpen && update.info && update.info.latest && (update.info.available || update.restart) && (
        <UpdateDialog
          info={update.info}
          busy={update.busy}
          problem={update.problem}
          restart={update.restart}
          onInstall={() => void update.install()}
          onSkip={() => {
            void update.skip(update.info?.latest ?? "");
            setUpdateOpen(false);
          }}
          onClose={() => setUpdateOpen(false)}
          onDismiss={() => {
            update.dismiss();
            setUpdateOpen(false);
          }}
        />
      )}

      {docs !== null && <DocsDialog initial={docs} onClose={() => setDocs(null)} />}

      {searchOpen && (
        <SymbolSearchDialog
          symbols={symbols}
          selected={symbol}
          pinned={pinnedSymbols}
          onPick={setSymbol}
          onTogglePin={(name) =>
            setPinnedSymbols((list) =>
              list.includes(name) ? list.filter((n) => n !== name) : [name, ...list],
            )
          }
          onClose={() => setSearchOpen(false)}
        />
      )}
    </div>
  );
}
