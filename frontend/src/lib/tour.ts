// The welcome tour, as far as it is logic: which steps there are, what the app can say about MetaTrader
// right now (installed? open? logged in? connected?), and when it should try to connect by itself.
// (The words and the window are in components/WelcomeTour.tsx.)

import { orderProblems } from "./terminal";
import type { TerminalStatus } from "./types";

export interface TourStep {
  id: "welcome" | "metatrader" | "chart" | "drawings" | "indicators" | "trading" | "replay";
  /** The name in the list at the side. */
  name: string;
}

export const TOUR_STEPS: TourStep[] = [
  { id: "welcome", name: "Welcome" },
  { id: "metatrader", name: "MetaTrader 5" },
  { id: "chart", name: "The chart" },
  { id: "drawings", name: "Drawing tools" },
  { id: "indicators", name: "Indicators" },
  { id: "trading", name: "Trading" },
  { id: "replay", name: "Replay" },
];

/** The step that explains (and checks) the MetaTrader connection. */
export const METATRADER_STEP = TOUR_STEPS.findIndex((s) => s.id === "metatrader");

// -- what the app sees of MetaTrader ------------------------------------------------------------------------------
/**
 * ok: done. todo: something for the user to do. wait: the app is on it. warn: it works, but something is off.
 */
export type CheckState = "ok" | "todo" | "wait" | "warn";

export interface Check {
  key: "mode" | "installed" | "open" | "account" | "connected" | "orders";
  state: CheckState;
  title: string;
  /** What was found, or what went wrong. */
  detail?: string;
  /** What to do about it. */
  hint?: string;
}

const names = (status: TerminalStatus): string =>
  [...new Set(status.terminals.map((t) => t.name || t.broker))].join(", ");

/**
 * The checklist the tour shows for MetaTrader. `problem` is what the last try to connect said (a sentence
 * from MetaTrader or the app), shown beside whatever is still missing.
 */
export function metatraderChecks(status: TerminalStatus | null, problem: string | null = null): Check[] {
  if (!status) return [];
  const { info } = status;

  if (status.mode === "mock") {
    return [
      {
        key: "mode",
        state: "todo",
        title: "CheapTrader is set to made-up prices",
        hint: "This copy was started with CT_BROKER=mock, so it does not look for MetaTrader. Remove that setting and restart to use MetaTrader.",
      },
    ];
  }

  const connected = status.broker === "mt5";
  const installed = connected || status.terminals.length > 0;
  const open = connected || status.terminals.some((t) => t.running);
  const loggedIn = connected && info.account_login > 0;

  const checks: Check[] = [
    {
      key: "installed",
      state: installed ? "ok" : "todo",
      title: "MetaTrader 5 is installed",
      detail: installed ? (connected ? info.name || names(status) : names(status)) || undefined : undefined,
      hint: installed
        ? undefined
        : "Install MetaTrader 5 from your broker’s website (or metatrader5.com). Most brokers give you a free demo account.",
    },
    {
      key: "open",
      state: open ? "ok" : "todo",
      title: "MetaTrader 5 is open",
      hint: open ? undefined : installed ? "Start it from the Start menu. A minimised window is fine." : undefined,
    },
  ];

  if (connected) {
    checks.push({
      key: "account",
      state: loggedIn ? "ok" : "todo",
      title: "An account is logged in",
      detail: loggedIn ? [info.account_login, info.account_server].filter(Boolean).join(" · ") : undefined,
      hint: loggedIn ? undefined : "In MetaTrader choose File ▸ Login to Trade Account. CheapTrader picks it up by itself.",
    });
  } else {
    checks.push({
      key: "account",
      state: open && status.can_connect && !problem ? "wait" : "todo",
      title: "An account is logged in",
      hint: open
        ? "In MetaTrader choose File ▸ Login to Trade Account. CheapTrader connects as soon as it can."
        : "Log in to your trading account inside MetaTrader (File ▸ Login to Trade Account).",
    });
  }

  checks.push({
    key: "connected",
    state: connected ? (loggedIn ? "ok" : "wait") : status.can_connect && !problem ? "wait" : "todo",
    title: connected ? "CheapTrader is connected" : "CheapTrader is connected to MetaTrader",
    detail: connected ? info.company || undefined : (problem ?? undefined),
    hint: connected ? undefined : "Until then you see made-up (synthetic) prices.",
  });

  if (connected && loggedIn) {
    const issues = orderProblems(info);
    checks.push({
      key: "orders",
      state: issues.length ? "warn" : "ok",
      title: issues.length ? "MetaTrader will refuse orders" : "MetaTrader takes orders from CheapTrader",
      detail: issues[0],
      hint: issues.length ? "Click the Algo Trading button in MetaTrader so that it turns green." : undefined,
    });
  }
  return checks;
}

/** MetaTrader is connected and has an account: everything the rest of the tour talks about works. */
export function metatraderReady(checks: Check[]): boolean {
  return checks.length > 0 && checks.every((c) => c.state === "ok" || c.state === "warn");
}

// -- connecting by itself -------------------------------------------------------------------------------------------
/** How long the tour waits between two attempts to connect on its own. */
export const RETRY_MS = 8000;

/** Should the tour try to connect now? A terminal is open and the app is not on it yet, and the last try is not recent. */
export function connectDue(status: TerminalStatus | null, now: number, lastTry: number | null, busy: boolean): boolean {
  if (!status || busy || !status.can_connect) return false;
  return lastTry === null || now - lastTry >= RETRY_MS;
}

// -- picking the tour up again after the page reloads (it reloads once the app has connected) --------------------------
export const RESUME_KEY = "cheaptrader:tourResume";

/** The step to go back to, from what was stored; null for anything that is not a step. */
export function resumeStep(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  return n >= 0 && n < TOUR_STEPS.length ? n : null;
}
