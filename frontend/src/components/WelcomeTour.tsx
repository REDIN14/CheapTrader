// The welcome tour: what a first-time user needs to know, in a few short steps. It opens by itself the
// first time the app starts, and again from the "?" menu.
//
// The MetaTrader step is live. It says what the app sees right now (is MetaTrader installed? open? is an
// account logged in? is the app connected?) and, when a terminal is open that the app is not using yet,
// connects to it by itself — no restart, no password, no path to type.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { PROJECT, supportLinks } from "../lib/project";
import {
  METATRADER_STEP,
  RESUME_KEY,
  TOUR_STEPS,
  connectDue,
  metatraderChecks,
  metatraderReady,
  type Check,
} from "../lib/tour";
import type { TerminalStatus } from "../lib/types";
import {
  BookIcon,
  BrandMark,
  ChannelIcon,
  CheckIcon,
  CloseIcon,
  HeartIcon,
  LockIcon,
  LongPositionIcon,
  RectangleIcon,
  ShortPositionIcon,
  TrashIcon,
  TrendLineIcon,
} from "./Icons";

interface Props {
  /** The step to open on. */
  start: number;
  /** The tour is over (finished, skipped or closed): it is not opened by itself again. */
  onClose: () => void;
  /** Open a page of the documentation ("getting_started", "indicators", "drawings"). */
  onDocs: (page: string) => void;
  /** Open the Indicators panel. */
  onIndicators: () => void;
  /** Open the About window (credits, licences, ways to support the project). */
  onAbout: () => void;
}

// -- small pieces ---------------------------------------------------------------------------------------------------
function Callout({ tone, children }: { tone: "info" | "warn"; children: ReactNode }) {
  return <div className={`tour-callout ${tone}`}>{children}</div>;
}

function Chip({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="tour-chip">
      {icon}
      {children}
    </span>
  );
}

const Kbd = ({ children }: { children: ReactNode }) => <kbd>{children}</kbd>;

function CheckRow({ check }: { check: Check }) {
  return (
    <li className={`tour-check ${check.state}`}>
      <i aria-hidden="true">{check.state === "ok" ? <CheckIcon size={14} /> : check.state === "warn" ? "!" : check.state === "wait" ? "" : ""}</i>
      <span>
        <b>{check.title}</b>
        {check.detail && <small className="detail">{check.detail}</small>}
        {check.hint && check.state !== "ok" && <small>{check.hint}</small>}
      </span>
    </li>
  );
}

// -- the steps ---------------------------------------------------------------------------------------------------------
function Welcome() {
  return (
    <>
      <p className="tour-lead">A free, TradingView-style trading platform that works with MetaTrader 5.</p>
      <ul className="tour-list">
        <li>Live charts, intervals and a watchlist of every symbol your broker offers.</li>
        <li>Drawing tools, including long / short boxes that can place the trade for you.</li>
        <li>Indicators in Python: use the built-in ones, or write your own in a few lines.</li>
        <li>Bar Replay with a paper account, to practise on past data without any risk.</li>
      </ul>
      <Callout tone="warn">
        <b>Trading is risky.</b> CheapTrader is not financial advice and comes without any warranty. Start on a demo
        account: sending orders from the app is <b>switched off</b> until you switch it on yourself.
      </Callout>
      <p className="tour-note">
        This tour takes about two minutes. You can open it again at any time from the <b>?</b> button at the right edge.
      </p>
    </>
  );
}

function MetaTrader({
  status,
  problem,
  busy,
  reloading,
  onConnect,
}: {
  status: TerminalStatus | null;
  problem: string | null;
  busy: boolean;
  reloading: boolean;
  onConnect: () => void;
}) {
  const checks = metatraderChecks(status, problem);
  const ready = metatraderReady(checks);
  const mock = status?.mode === "mock";
  return (
    <>
      <p className="tour-lead">
        CheapTrader reads prices and sends orders through <b>MetaTrader 5</b>. You only have to:
      </p>
      <ol className="tour-list numbered">
        <li>
          <b>Install MetaTrader 5</b> from your broker or metatrader5.com (most brokers give a free demo account).
        </li>
        <li>
          <b>Log in</b> to your account inside MetaTrader (<i>File ▸ Login to Trade Account</i>).
        </li>
        <li>
          <b>Leave it open.</b> A minimised window is fine.
        </li>
      </ol>
      <p className="tour-note">
        That is all: CheapTrader finds the terminal, the account and the symbols by itself — no password, login number
        or path to type in. What it sees right now:
      </p>
      {reloading && <Callout tone="info">Connected to MetaTrader — loading your account and symbols…</Callout>}
      {!reloading && ready && (
        <Callout tone="info">
          <b>You are connected.</b> The chart, the symbol list and the account at the bottom are MetaTrader’s own now.
        </Callout>
      )}

      {status ? (
        <ul className="tour-checks" aria-live="polite">
          {checks.map((c) => (
            <CheckRow key={c.key} check={c} />
          ))}
        </ul>
      ) : (
        <p className="tour-note">Looking for MetaTrader…</p>
      )}

      {!reloading && status && !mock && status.broker !== "mt5" && (
        <div className="tour-actions">
          <button className="tour-btn" disabled={busy} onClick={onConnect}>
            {busy ? "Connecting…" : "Connect now"}
          </button>
          <span className="tour-note">
            {status.can_connect
              ? "A terminal is open: CheapTrader connects by itself, this button just does it right away."
              : "Open MetaTrader first; this page notices it within seconds."}
          </span>
        </div>
      )}
      <p className="tour-note">
        No MetaTrader? CheapTrader still runs — on made-up (synthetic) prices, so you can try everything except real
        trading.
      </p>
    </>
  );
}

function Chart() {
  return (
    <>
      <p className="tour-lead">The chart works the way TradingView’s does.</p>
      <ul className="tour-list">
        <li>
          <b>Symbol:</b> click the symbol name at the top left to search. The list icon on the right edge opens your
          watchlist; pin the symbols you use most.
        </li>
        <li>
          <b>Interval:</b> <i>1m … D</i> in the top bar. The chart keeps your place and zoom when you switch.
        </li>
        <li>
          <b>Move around:</b> drag to pan, use the mouse wheel to zoom, drag an axis to stretch it. <Kbd>F</Kbd> fits the
          chart to the screen.
        </li>
        <li>
          <b>Right-click</b> the chart to copy a price, place an order at that price, or set a stop loss / take profit
          there.
        </li>
        <li>
          The small dot next to the title is green while prices are arriving live.
        </li>
      </ul>
    </>
  );
}

function Drawings({ onDocs }: { onDocs: (page: string) => void }) {
  return (
    <>
      <p className="tour-lead">The bar at the left edge of the chart holds the drawing tools.</p>
      <div className="tour-chips">
        <Chip icon={<TrendLineIcon size={20} />}>Trend line</Chip>
        <Chip icon={<ShortPositionIcon size={20} />}>Short position</Chip>
        <Chip icon={<LongPositionIcon size={20} />}>Long position</Chip>
        <Chip icon={<RectangleIcon size={20} />}>Rectangle</Chip>
        <Chip icon={<ChannelIcon size={20} />}>Channel</Chip>
      </div>
      <ul className="tour-list">
        <li>
          Pick a tool and click on the chart. A hint at the bottom says what to click next; <Kbd>Esc</Kbd> cancels.
        </li>
        <li>
          Click a drawing to change its colour or thickness, or to <b>lock it</b> <LockIcon size={16} className="inline" /> so it
          cannot be moved or deleted by accident.
        </li>
        <li>
          <b>Long / Short boxes are trades.</b> Right-click one to buy or sell <i>now</i> with its stop and target, leave
          a limit order at its entry, or size the trade by risk (a % of your balance, an amount, or lots).
        </li>
        <li>
          The bin <TrashIcon size={16} className="inline" /> removes the drawings of this symbol or of all symbols; locked ones
          stay unless you choose <i>locked ones</i>.
        </li>
        <li>Everything is saved per symbol. Scripts and indicators can draw too.</li>
      </ul>
      <div className="tour-actions">
        <button className="tour-btn" onClick={() => onDocs("drawings")}>
          <BookIcon size={18} /> Read the drawing guide
        </button>
      </div>
    </>
  );
}

const SAMPLE = `def compute(df, params):
    period = int(params.get("period", 14))
    return {"Momentum": df["close"] - df["close"].shift(period)}`;

function Indicators({ onDocs, onIndicators }: { onDocs: (page: string) => void; onIndicators: () => void }) {
  return (
    <>
      <p className="tour-lead">
        <b>Indicators</b> in the top bar: SMA, EMA, RSI, MACD and more are built in. To make your own, write a small
        Python function:
      </p>
      <pre className="tour-code" aria-label="An example indicator">
        <code>{SAMPLE}</code>
      </pre>
      <ul className="tour-list">
        <li>
          <code>df</code> is a table of candles with the columns <code>time</code>, <code>open</code>, <code>high</code>,{" "}
          <code>low</code>, <code>close</code> and <code>tick_volume</code> (a pandas DataFrame).
        </li>
        <li>
          Return one or more lines. Choose whether they are drawn on the price (<i>overlay</i>) or in a pane of their
          own, like RSI.
        </li>
        <li>
          An indicator can draw shapes too — lines, boxes, labels — with <code>ct_draw</code>.
        </li>
        <li>Indicators run in a sandbox with a time and memory limit, so a mistake cannot harm your PC.</li>
      </ul>
      <div className="tour-actions">
        <button className="tour-btn" onClick={onIndicators}>
          Open the Indicators panel
        </button>
        <button className="tour-btn" onClick={() => onDocs("indicators")}>
          <BookIcon size={18} /> Read the indicator guide
        </button>
      </div>
    </>
  );
}

function Trading({ status }: { status: TerminalStatus | null }) {
  const connected = status?.broker === "mt5";
  const on = status?.orders.allowed ?? false;
  return (
    <>
      <p className="tour-lead">
        Trade from the <b>Trade</b> panel (top right), the <b>Sell / Buy</b> buttons on the chart, or from a long / short
        box.
      </p>
      <ul className="tour-list">
        <li>
          <b>Market</b> and <b>Limit</b> tabs. A limit order waits at a price you choose; on the other side of the market
          the same price makes it a stop order.
        </li>
        <li>
          Drag the <b>SL</b> and <b>TP</b> tags on the chart to set the stop loss and take profit; the ✕ on a tag closes
          the position or removes that level.
        </li>
        <li>Orders that wait show on the chart too: drag them to move them, ✕ takes them back.</li>
      </ul>
      <Callout tone="warn">
        <b>Sending orders is off until you switch it on.</b> Open the <b>MetaTrader</b> menu in the bottom bar and turn on{" "}
        <i>Send orders to the broker</i> when you are ready — on a demo account first.
        {connected && (
          <>
            {" "}
            Right now it is <b>{on ? "ON" : "off"}</b>.
          </>
        )}
      </Callout>
      <Callout tone="info">
        MetaTrader itself must allow it: its <b>Algo Trading</b> button (in the toolbar) has to be green, or MetaTrader
        refuses orders from any program.
      </Callout>
    </>
  );
}

function Replay({ onDocs, onAbout }: { onDocs: (page: string) => void; onAbout: () => void }) {
  const links = supportLinks();
  return (
    <>
      <p className="tour-lead">
        <b>Bar Replay</b> lets you practise on history with a paper account — nothing reaches your broker.
      </p>
      <ul className="tour-list">
        <li>
          Click <b>Replay</b> in the top bar, click the candle to start from, then play, pause or step.
        </li>
        <li>Buy and sell with stop loss and take profit. The report shows your equity curve and statistics.</li>
        <li>
          <Kbd>Space</Kbd> plays / pauses, <Kbd>→</Kbd> steps one bar, <Kbd>Esc</Kbd> leaves the replay.
        </li>
      </ul>
      <Callout tone="info">
        <b>You are ready.</b> Where to find help: the book icons open the guides; the <b>?</b> button at the right edge shows
        the keyboard shortcuts, this tour again, and <i>About &amp; support</i>.
      </Callout>
      <div className="tour-actions">
        <button className="tour-btn" onClick={() => onDocs("getting_started")}>
          <BookIcon size={18} /> Getting started guide
        </button>
        <button className="tour-btn" onClick={onAbout}>
          About &amp; credits
        </button>
        {links.map((s) => (
          <a key={s.id} className="tour-btn support" href={s.url} target="_blank" rel="noopener noreferrer">
            <HeartIcon size={18} /> {s.label}
          </a>
        ))}
      </div>
      {links.length > 0 && (
        <p className="tour-note">{PROJECT.name} is free. If it helps you, a donation keeps it going — thank you!</p>
      )}
    </>
  );
}

// -- the window ------------------------------------------------------------------------------------------------------
const TITLES: Record<string, string> = {
  welcome: "Welcome to CheapTrader",
  metatrader: "Connect MetaTrader 5",
  chart: "The chart",
  drawings: "Drawing tools",
  indicators: "Indicators — and your own",
  trading: "Trading",
  replay: "Practise with Replay",
};

export function WelcomeTour({ start, onClose, onDocs, onIndicators, onAbout }: Props) {
  const [step, setStep] = useState(Math.min(Math.max(start, 0), TOUR_STEPS.length - 1));
  const [status, setStatus] = useState<TerminalStatus | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const lastTry = useRef<number | null>(null);
  const working = useRef(false);

  const id = TOUR_STEPS[step].id;
  const last = step === TOUR_STEPS.length - 1;
  const watching = id === "metatrader" || id === "trading";

  // What the app sees of MetaTrader: looked at while a step that talks about it is on screen.
  const look = useCallback(async () => {
    try {
      setStatus(await api.terminal());
    } catch {
      /* the next look tries again */
    }
  }, []);
  useEffect(() => {
    if (!watching) return;
    void look();
    const timer = window.setInterval(look, 2500);
    return () => window.clearInterval(timer);
  }, [watching, look]);

  const connect = useCallback(async () => {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setProblem(null);
    lastTry.current = Date.now();
    try {
      const next = await api.connectTerminal();
      setProblem(null);
      setStatus(next);
      if (next.broker === "mt5") {
        // Symbols, bars and the account are MetaTrader's now: the page starts over, and the tour comes back to this step.
        setReloading(true);
        try {
          sessionStorage.setItem(RESUME_KEY, String(METATRADER_STEP));
        } catch {
          /* private mode: the tour just does not come back */
        }
        window.setTimeout(() => window.location.reload(), 900);
      }
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      working.current = false;
      setBusy(false);
    }
  }, []);

  // A terminal is open and the app is not on it yet: connect, without being asked.
  useEffect(() => {
    if (id !== "metatrader" || reloading) return;
    if (connectDue(status, Date.now(), lastTry.current, working.current)) void connect();
  }, [id, status, reloading, connect]);

  const go = useCallback((to: number) => setStep(Math.min(Math.max(to, 0), TOUR_STEPS.length - 1)), []);

  // Keys: arrows move, Esc ends the tour (unless a page of the documentation is open over it), Tab stays inside.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement | null)?.closest("input, textarea, select");
      if (e.key === "Escape") {
        if (document.querySelectorAll('[aria-modal="true"]').length > 1) return;
        e.stopPropagation();
        onClose();
      } else if (!typing && e.key === "ArrowRight") {
        setStep((s) => Math.min(s + 1, TOUR_STEPS.length - 1));
      } else if (!typing && e.key === "ArrowLeft") {
        setStep((s) => Math.max(s - 1, 0));
      } else if (e.key === "Tab" && dialog.current) {
        if (document.querySelectorAll('[aria-modal="true"]').length > 1) return;
        const items = [...dialog.current.querySelectorAll<HTMLElement>("button:not(:disabled), a[href]")];
        if (!items.length) return;
        const at = items.indexOf(document.activeElement as HTMLElement);
        if (e.shiftKey && at <= 0) {
          e.preventDefault();
          items[items.length - 1].focus();
        } else if (!e.shiftKey && (at === -1 || at === items.length - 1)) {
          e.preventDefault();
          items[0].focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  useEffect(() => {
    dialog.current?.focus();
  }, []);

  // A new step starts at its top.
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [step]);

  const content =
    id === "welcome" ? (
      <Welcome />
    ) : id === "metatrader" ? (
      <MetaTrader status={status} problem={problem} busy={busy} reloading={reloading} onConnect={() => void connect()} />
    ) : id === "chart" ? (
      <Chart />
    ) : id === "drawings" ? (
      <Drawings onDocs={onDocs} />
    ) : id === "indicators" ? (
      <Indicators onDocs={onDocs} onIndicators={onIndicators} />
    ) : id === "trading" ? (
      <Trading status={status} />
    ) : (
      <Replay onDocs={onDocs} onAbout={onAbout} />
    );

  return (
    <div className="tour-backdrop" role="presentation">
      <div ref={dialog} className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title" tabIndex={-1}>
        <aside className="tour-steps" aria-label="Steps">
          <div className="tour-brand">
            <BrandMark size={26} />
            <b>CheapTrader</b>
          </div>
          <ol>
            {TOUR_STEPS.map((s, i) => (
              <li key={s.id}>
                <button
                  className={i === step ? "active" : i < step ? "done" : undefined}
                  aria-current={i === step ? "step" : undefined}
                  onClick={() => go(i)}
                >
                  <i>{i < step ? <CheckIcon size={12} /> : i + 1}</i>
                  {s.name}
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <section className="tour-main">
          <header className="tour-head">
            <h2 id="tour-title">{TITLES[id]}</h2>
            <button className="tv-icon-btn" title="Close the tour (Esc)" aria-label="Close the tour" onClick={onClose}>
              <CloseIcon size={22} />
            </button>
          </header>

          <div className="tour-body" ref={body}>
            {content}
          </div>

          <footer className="tour-foot">
            {last ? <span /> : (
              <button className="tour-link" onClick={onClose}>
                Skip the tour
              </button>
            )}
            <span className="tour-count">
              {step + 1} / {TOUR_STEPS.length}
            </span>
            <span className="tour-nav">
              <button className="tour-btn" disabled={step === 0} onClick={() => go(step - 1)}>
                Back
              </button>
              {last ? (
                <button className="tour-btn primary" onClick={onClose}>
                  Start trading
                </button>
              ) : (
                <button className="tour-btn primary" onClick={() => go(step + 1)}>
                  Next
                </button>
              )}
            </span>
          </footer>
        </section>
      </div>
    </div>
  );
}
