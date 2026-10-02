// What can be said about the MetaTrader terminal from what it reports (pure functions, shared by the
// MetaTrader menu and the welcome tour).

import type { TerminalInfo } from "./types";

/** Whatever stops the terminal from taking the app's orders, in words. Empty: it will take them. */
export function orderProblems(info: TerminalInfo): string[] {
  const out: string[] = [];
  if (!info.algo_trading) out.push("Algo Trading is switched off in the terminal: it refuses every order the app sends.");
  if (!info.api_allowed) out.push("The terminal’s Python interface is disabled.");
  if (!info.account_trading) out.push("This login cannot trade (an investor, read-only password?).");
  if (!info.account_expert) out.push("The broker has switched off automated trading for this account.");
  return out;
}
