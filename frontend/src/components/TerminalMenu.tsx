// The MetaTrader terminal, from the account bar.
//
// One button, one panel: which terminal the app is connected to (the broker's own copy of
// MetaTrader 5), whether it will take orders — and if not, what to switch on in it — a switch
// that hides the terminal's window (remembered), the other terminals found on this PC, and, in
// the packaged program, the address it is served on and a way to quit it.

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { copyText } from "../lib/clipboard";
import { orderProblems } from "../lib/terminal";
import type { TerminalStatus } from "../lib/types";
import { TerminalIcon } from "./Icons";

/** Does the terminal take orders from the app? Whatever stops it is listed, in words. */
const problems = (status: TerminalStatus): string[] => orderProblems(status.info);

export function TerminalMenu() {
  const [status, setStatus] = useState<TerminalStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [confirmOrders, setConfirmOrders] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.terminal());
    } catch {
      /* keep what was shown: the next look tries again */
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(load, open ? 4000 : 30_000);
    return () => window.clearInterval(id);
  }, [load, open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setConfirmQuit(false);
      setConfirmOrders(false);
      setNote(null);
      setError(null);
    }
  }, [open]);

  const act = async (work: () => Promise<TerminalStatus | void>, done?: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await work();
      if (next) setStatus(next);
      setNote(done ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;
  const { info, window: win } = status;
  const issues = problems(status);
  const hidden = win.hidden ?? win.hide_preference;
  const address = window.location.origin;

  return (
    <>
      <button
        ref={button}
        className={open ? "tv-strip-btn open" : "tv-strip-btn"}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={
          issues.length
            ? `MetaTrader will not take orders: ${issues[0]}`
            : `${info.name || "MetaTrader 5"} — orders, window, algo trading, terminals`
        }
      >
        <TerminalIcon size={18} />
        <span>MetaTrader</span>
        {(issues.length > 0 || !status.orders.allowed) && <i className={issues.length ? "tv-strip-flag" : "tv-strip-flag soft"} />}
      </button>

      {open &&
        createPortal(
          <div className="tv-tmenu" ref={panel} role="dialog" aria-label="MetaTrader terminal">
            <div className="tv-tmenu-head">
              <b>{info.name || "MetaTrader 5"}</b>
              <span>
                {[info.company, info.account_login ? `account ${info.account_login}` : "", info.account_server]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {info.path && <span className="tv-tmenu-path" title={info.path}>{info.path}</span>}
            </div>

            <div className="tv-menu-title">WINDOW</div>
            <label className="tv-tmenu-row switch">
              <span>
                Hide the MetaTrader window
                <small>
                  {win.found
                    ? "The terminal keeps running in the background and the app keeps working. Remembered next time."
                    : "No terminal window found yet (it may still be starting). The choice is remembered."}
                </small>
              </span>
              <button
                role="switch"
                aria-checked={hidden}
                className={hidden ? "tv-switch on" : "tv-switch"}
                disabled={busy}
                onClick={() => act(() => api.hideTerminal(!hidden))}
              >
                <i />
              </button>
            </label>

            <div className="tv-menu-title">ORDERS FROM THIS APP</div>
            <div className="tv-tmenu-row switch">
              <span>
                Send orders to the broker
                <small>
                  {status.orders.by_settings
                    ? "On, because the settings file says so (CT_ALLOW_LIVE_ORDERS=true)."
                    : status.orders.allowed
                      ? "On: Buy and Sell place real orders on this account."
                      : "Off: Buy and Sell are refused, nothing can reach the broker. Switch on when you are ready — on a demo account first."}
                </small>
              </span>
              <button
                role="switch"
                aria-label="Send orders to the broker"
                aria-checked={status.orders.allowed}
                className={status.orders.allowed ? "tv-switch on" : "tv-switch"}
                disabled={busy || status.orders.by_settings}
                onClick={() => (status.orders.allowed ? act(() => api.setOrders(false), "Orders are off.") : setConfirmOrders((v) => !v))}
              >
                <i />
              </button>
            </div>
            {confirmOrders && !status.orders.allowed && (
              <div className="tv-tmenu-confirm" role="alertdialog" aria-label="Switch on orders">
                <p>
                  Buy and Sell will place <b>real orders</b> on account{" "}
                  <b>{[info.account_login || "", info.account_server].filter(Boolean).join(" · ") || "of this terminal"}</b>. If it is a live account you can lose money.
                  Try a demo account first.
                </p>
                <div>
                  <button
                    className="tv-tmenu-btn danger"
                    disabled={busy}
                    onClick={() => {
                      setConfirmOrders(false);
                      void act(() => api.setOrders(true), "Orders are on.");
                    }}
                  >
                    Switch on
                  </button>
                  <button className="tv-tmenu-btn" onClick={() => setConfirmOrders(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="tv-menu-title">ALGO TRADING</div>
            <div className={issues.length ? "tv-tmenu-status warn" : "tv-tmenu-status ok"}>
              {issues.length ? (
                <ul>
                  {issues.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              ) : (
                <span>On: the terminal takes the app&rsquo;s orders.</span>
              )}
            </div>
            <details className="tv-tmenu-how" open>
              <summary>What to switch on in MetaTrader</summary>
              <ol>
                <li>
                  In the terminal&rsquo;s toolbar click <b>Algo Trading</b> so that it turns <b>green</b>. (Or: Tools
                  &rarr; Options &rarr; Expert Advisors &rarr; tick <b>Allow algorithmic trading</b>.)
                </li>
                <li>
                  Stay logged in to the account with its <b>trading password</b>. An investor (read-only) password can
                  look but not trade.
                </li>
                <li>
                  Nothing else: no Expert Advisor, no &ldquo;Allow DLL imports&rdquo;. The app talks to the terminal
                  through MetaTrader&rsquo;s Python interface.
                </li>
                <li>
                  Still refused? The broker may have switched off automated trading for the account: ask them.
                </li>
              </ol>
            </details>

            {status.terminals.length > 1 && (
              <>
                <div className="tv-menu-title">TERMINALS ON THIS PC</div>
                {status.terminals.map((t) => {
                  const inUse = info.exe && t.exe.toLowerCase() === info.exe.toLowerCase();
                  const picked = (status.chosen ?? "").toLowerCase() === t.exe.toLowerCase();
                  return (
                    <button
                      key={t.exe}
                      className={picked ? "tv-tmenu-term picked" : "tv-tmenu-term"}
                      disabled={busy}
                      title={t.exe}
                      onClick={() =>
                        act(
                          () => api.chooseTerminal(picked ? null : t.exe),
                          picked ? "Back to choosing automatically." : `${t.broker} is used the next time CheapTrader starts.`,
                        )
                      }
                    >
                      <i className={t.running ? "tv-strip-dot on" : "tv-strip-dot"} />
                      <span>
                        {t.broker}
                        <small>
                          {inUse ? "in use now" : t.running ? "running" : "installed"}
                          {picked ? " · your choice" : ""}
                        </small>
                      </span>
                    </button>
                  );
                })}
                <div className="tv-tmenu-hint">
                  Found automatically: the one you pick, else a running one, else the one used last.
                </div>
              </>
            )}

            <div className="tv-menu-title">THIS PAGE</div>
            <div className="tv-tmenu-row">
              <span>
                {address}
                <small>Where CheapTrader is open on this PC.</small>
              </span>
              <button
                className="tv-tmenu-btn"
                onClick={async () => {
                  setCopied(await copyText(address));
                  window.setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            {status.app.can_quit && (
              <div className="tv-tmenu-row">
                <span>
                  Quit CheapTrader
                  <small>Stops the app. Positions stay open in MetaTrader.</small>
                </span>
                <button
                  className={confirmQuit ? "tv-tmenu-btn danger" : "tv-tmenu-btn"}
                  disabled={busy}
                  onClick={() => (confirmQuit ? act(() => api.quit().then(() => undefined), "Stopping…") : setConfirmQuit(true))}
                >
                  {confirmQuit ? "Click again to quit" : "Quit"}
                </button>
              </div>
            )}

            {note && <div className="tv-tmenu-note">{note}</div>}
            {error && <div className="tv-tmenu-note error">{error}</div>}
          </div>,
          document.body,
        )}
    </>
  );
}
