import assert from "node:assert/strict";
import { test } from "node:test";
import { isWebAddress, issuesUrl, licenseUrl, supportLinks } from "../src/lib/project";
import { orderProblems } from "../src/lib/terminal";
import {
  METATRADER_STEP,
  RETRY_MS,
  TOUR_STEPS,
  connectDue,
  metatraderChecks,
  metatraderReady,
  resumeStep,
} from "../src/lib/tour";
import type { TerminalCandidate, TerminalInfo, TerminalStatus } from "../src/lib/types";

const info = (change: Partial<TerminalInfo> = {}): TerminalInfo => ({
  connected: true,
  name: "Fusion Markets MetaTrader 5",
  company: "Fusion Markets Pty Ltd",
  path: "C:\\Program Files\\Fusion Markets MetaTrader 5",
  exe: "C:\\Program Files\\Fusion Markets MetaTrader 5\\terminal64.exe",
  data_path: "",
  build: 5000,
  algo_trading: true,
  api_allowed: true,
  account_login: 12345,
  account_server: "FusionMarkets-Demo",
  account_trading: true,
  account_expert: true,
  ...change,
});

const candidate = (running: boolean): TerminalCandidate => ({
  exe: "C:\\Program Files\\Fusion Markets MetaTrader 5\\terminal64.exe",
  folder: "C:\\Program Files\\Fusion Markets MetaTrader 5",
  name: "Fusion Markets MetaTrader 5",
  broker: "Fusion Markets",
  running,
  pid: running ? 100 : null,
  last_used: 0,
});

const status = (change: Partial<TerminalStatus> = {}): TerminalStatus => ({
  broker: "mock",
  mode: "auto",
  info: info({ connected: false, name: "mock", account_login: 0, account_server: "" }),
  window: { found: false, hidden: null, minimized: false, hide_preference: false },
  terminals: [],
  can_connect: false,
  chosen: null,
  orders: { allowed: false, by_settings: false },
  app: { packaged: true, can_quit: true, version: "0.1.0" },
  ...change,
});

const states = (s: TerminalStatus | null, problem: string | null = null) =>
  Object.fromEntries(metatraderChecks(s, problem).map((c) => [c.key, c.state]));

// -- the checklist ---------------------------------------------------------------------------------------------------
test("nothing to show before the app has looked", () => {
  assert.deepEqual(metatraderChecks(null), []);
});

test("with no MetaTrader on the PC every step is still to do, and the first says how to get it", () => {
  const checks = metatraderChecks(status());
  assert.deepEqual(states(status()), { installed: "todo", open: "todo", account: "todo", connected: "todo" });
  assert.match(checks[0].hint!, /Install MetaTrader 5/);
  assert.equal(metatraderReady(checks), false);
});

test("an installed terminal that is not open: the next thing is to open it", () => {
  const s = status({ terminals: [candidate(false)] });
  assert.deepEqual(states(s), { installed: "ok", open: "todo", account: "todo", connected: "todo" });
  const checks = metatraderChecks(s);
  assert.equal(checks[0].detail, "Fusion Markets MetaTrader 5");
  assert.match(checks[1].hint!, /Start it from the Start menu/);
});

test("an open terminal that the app can connect to: it is on it", () => {
  const s = status({ terminals: [candidate(true)], can_connect: true });
  assert.deepEqual(states(s), { installed: "ok", open: "ok", account: "wait", connected: "wait" });
});

test("when connecting failed, what MetaTrader said is shown and nothing claims to be on its way", () => {
  const s = status({ terminals: [candidate(true)], can_connect: true });
  const checks = metatraderChecks(s, "MetaTrader 5 is open, but no account is logged in.");
  assert.deepEqual(Object.fromEntries(checks.map((c) => [c.key, c.state])), { installed: "ok", open: "ok", account: "todo", connected: "todo" });
  assert.equal(checks[3].detail, "MetaTrader 5 is open, but no account is logged in.", "under the step that did not work");
  assert.match(checks[2].hint!, /Login to Trade Account/);
});

test("connected with an account: all done, and the account is named", () => {
  const s = status({ broker: "mt5", info: info(), terminals: [candidate(true)] });
  const checks = metatraderChecks(s);
  assert.deepEqual(Object.fromEntries(checks.map((c) => [c.key, c.state])), {
    installed: "ok",
    open: "ok",
    account: "ok",
    connected: "ok",
    orders: "ok",
  });
  assert.equal(checks.find((c) => c.key === "account")!.detail, "12345 · FusionMarkets-Demo");
  assert.equal(metatraderReady(checks), true);
});

test("connected to a terminal nobody has logged in to: the account is the thing to do", () => {
  const s = status({ broker: "mt5", info: info({ account_login: 0, account_server: "" }) });
  const checks = metatraderChecks(s);
  const by = Object.fromEntries(checks.map((c) => [c.key, c.state]));
  assert.equal(by.account, "todo");
  assert.equal(by.connected, "wait");
  assert.equal(metatraderReady(checks), false);
  assert.equal(checks.find((c) => c.key === "orders"), undefined, "no account, nothing to say about orders yet");
});

test("a terminal that will refuse orders is flagged, with the one thing to switch on", () => {
  const s = status({ broker: "mt5", info: info({ algo_trading: false }) });
  const orders = metatraderChecks(s).find((c) => c.key === "orders")!;
  assert.equal(orders.state, "warn");
  assert.match(orders.detail!, /Algo Trading is switched off/);
  assert.match(orders.hint!, /turns green/);
  assert.equal(metatraderReady(metatraderChecks(s)), true, "it is connected; only orders are held back");
});

test("a program set to made-up prices says so instead of asking for MetaTrader", () => {
  const checks = metatraderChecks(status({ mode: "mock", terminals: [candidate(true)] }));
  assert.equal(checks.length, 1);
  assert.equal(checks[0].key, "mode");
  assert.match(checks[0].hint!, /CT_BROKER=mock/);
});

test("the problems with orders come in words, one per cause", () => {
  assert.deepEqual(orderProblems(info()), []);
  assert.equal(orderProblems(info({ algo_trading: false, api_allowed: false })).length, 2);
});

// -- connecting by itself --------------------------------------------------------------------------------------------
test("the tour tries to connect when a terminal is open and the last try is not recent", () => {
  const ready = status({ can_connect: true, terminals: [candidate(true)] });
  assert.equal(connectDue(ready, 1000, null, false), true, "never tried");
  assert.equal(connectDue(ready, 1000 + RETRY_MS - 1, 1000, false), false, "tried a moment ago");
  assert.equal(connectDue(ready, 1000 + RETRY_MS, 1000, false), true);
  assert.equal(connectDue(ready, 5000, null, true), false, "one try at a time");
  assert.equal(connectDue(status(), 5000, null, false), false, "nothing open to connect to");
  assert.equal(connectDue(null, 5000, null, false), false);
});

test("a tour that is picked up again after the page reloads goes back to the right step", () => {
  assert.equal(resumeStep("1"), 1);
  assert.equal(resumeStep("0"), 0);
  assert.equal(resumeStep(String(TOUR_STEPS.length)), null, "past the last step");
  assert.equal(resumeStep("-1"), null);
  assert.equal(resumeStep("two"), null);
  assert.equal(resumeStep(null), null);
  assert.equal(TOUR_STEPS[METATRADER_STEP].id, "metatrader");
});

test("the steps are in the order the tour tells them, each once", () => {
  assert.deepEqual(TOUR_STEPS.map((s) => s.id), ["welcome", "metatrader", "chart", "drawings", "indicators", "trading", "replay"]);
});

// -- the project's links -----------------------------------------------------------------------------------------------
test("only real web addresses are ever linked", () => {
  assert.equal(isWebAddress("https://github.com/someone/CheapTrader"), true);
  assert.equal(isWebAddress("http://example.com"), false, "https only");
  assert.equal(isWebAddress("javascript:alert(1)"), false);
  assert.equal(isWebAddress(""), false);
  assert.equal(isWebAddress("https://"), false);
});

test("a donation page that is not set up is not offered", () => {
  const project = {
    support: [
      { id: "github", label: "GitHub Sponsors", url: "https://github.com/sponsors/someone" },
      { id: "kofi", label: "Ko-fi", url: "" },
      { id: "bad", label: "Bad", url: "javascript:alert(1)" },
    ],
  };
  assert.deepEqual(supportLinks(project).map((s) => s.id), ["github"]);
  assert.deepEqual(supportLinks({ support: [] }), []);
});

test("the issues page and the licence come from the repository when there is one", () => {
  assert.equal(issuesUrl({ repo: "", issues: "" }), null);
  assert.equal(issuesUrl({ repo: "https://github.com/someone/CheapTrader/", issues: "" }), "https://github.com/someone/CheapTrader/issues");
  assert.equal(issuesUrl({ repo: "https://github.com/someone/CheapTrader", issues: "https://example.com/help" }), "https://example.com/help");
  assert.equal(licenseUrl({ repo: "" }), null);
  assert.equal(licenseUrl({ repo: "https://github.com/someone/CheapTrader/" }), "https://github.com/someone/CheapTrader/blob/main/LICENSE");
});
