// About CheapTrader: the version, where it lives, how to support it, and the credits the licences of the
// parts it is made of ask for (most of all TradingView’s: the chart library requires the notice below and a
// link to tradingview.com in a window of the app that every user can open).

import { useEffect, useRef } from "react";
import { PROJECT, isWebAddress, issuesUrl, licenseUrl, supportLinks } from "../lib/project";
import type { UpdateStatus } from "../lib/types";
import { checkedText, updateLine } from "../lib/updates";
import { BookIcon, BrandMark, CloseIcon, HeartIcon } from "./Icons";

interface Props {
  version: string | null;
  onClose: () => void;
  onDocs: (page: string) => void;
  onTour: () => void;
  /** Looking for newer versions: what is known, and the few things to do about it. */
  update: {
    info: UpdateStatus | null;
    busy: boolean;
    onCheck: () => void;
    onEnabled: (enabled: boolean) => void;
    onOpen: () => void;
  };
}

/** The notice of the chart library, as its licence asks for it. */
const TRADINGVIEW_NOTICE = "TradingView Lightweight Charts™ — Copyright (c) 2026 TradingView, Inc.";

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export function AboutDialog({ version, onClose, onDocs, onTour, update }: Props) {
  const dialog = useRef<HTMLDivElement>(null);
  const support = supportLinks();
  const issues = issuesUrl();
  const license = licenseUrl();

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.querySelectorAll('[aria-modal="true"]').length > 1) return; // a page of the docs is over it
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div className="tour-backdrop" onClick={onClose}>
      <div
        ref={dialog}
        className="about"
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="about-head">
          <BrandMark size={44} />
          <div>
            <h2 id="about-title">{PROJECT.name}</h2>
            <span>{version ? `Version ${version}` : "Version unknown"} · {PROJECT.license} licence</span>
          </div>
          <button className="tv-icon-btn" title="Close (Esc)" aria-label="Close" onClick={onClose}>
            <CloseIcon size={22} />
          </button>
        </header>

        <div className="about-body">
          <p>
            A free, TradingView-style trading platform for MetaTrader 5: live charts, drawing tools that can place
            trades, indicators written in Python, and bar replay with a paper account.
          </p>

          {support.length > 0 && (
            <section>
              <h3>Support the project</h3>
              <p>{PROJECT.name} is free and made in spare time. If it is useful to you, a donation helps to keep it going.</p>
              <div className="tour-actions">
                {support.map((s) => (
                  <a key={s.id} className="tour-btn support" href={s.url} target="_blank" rel="noopener noreferrer">
                    <HeartIcon size={18} /> {s.label}
                  </a>
                ))}
              </div>
            </section>
          )}

          <section>
            <h3>Help</h3>
            <div className="tour-actions">
              <button className="tour-btn" onClick={onTour}>
                Welcome tour
              </button>
              <button className="tour-btn" onClick={() => onDocs("getting_started")}>
                <BookIcon size={18} /> Getting started
              </button>
              {isWebAddress(PROJECT.repo) && (
                <a className="tour-btn" href={PROJECT.repo} target="_blank" rel="noopener noreferrer">
                  Source code
                </a>
              )}
              {issues && (
                <a className="tour-btn" href={issues} target="_blank" rel="noopener noreferrer">
                  Report a problem
                </a>
              )}
            </div>
          </section>

          <section>
            <h3>Updates</h3>
            {update.info ? (
              <>
                <p>
                  {updateLine(update.info)} <span className="about-muted">{checkedText(update.info)}</span>
                </p>
                <label className="about-check">
                  <input
                    type="checkbox"
                    checked={update.info.enabled}
                    disabled={update.busy}
                    onChange={(e) => update.onEnabled(e.target.checked)}
                  />
                  Look for new versions on GitHub
                </label>
                <p className="about-muted">
                  When this is on, {PROJECT.name} asks GitHub for the latest release a little after it starts and every six
                  hours. That is the only time it connects to the internet by itself, and nothing but the request itself is
                  sent. A new version is installed only when you click Install.
                </p>
                <div className="tour-actions">
                  <button className="tour-btn" disabled={update.busy} onClick={update.onCheck}>
                    Check now
                  </button>
                  {update.info.available && (
                    <button className="tour-btn primary" onClick={update.onOpen}>
                      Version {update.info.latest}
                    </button>
                  )}
                </div>
              </>
            ) : (
              <p className="about-muted">The program did not say whether there is a newer version.</p>
            )}
          </section>

          <section>
            <h3>Credits</h3>
            <p className="about-notice">
              Charts: {TRADINGVIEW_NOTICE} <External href="https://www.tradingview.com/">tradingview.com</External>
            </p>
            <p>
              MetaTrader 5 is a trademark of MetaQuotes Ltd. CheapTrader is an independent project: it is not affiliated
              with, endorsed by or sponsored by MetaQuotes or TradingView. The look of the interface is inspired by
              TradingView’s.
            </p>
            <p>
              CheapTrader is made with open-source software, listed with its licences on the{" "}
              <button className="about-link" onClick={() => onDocs("credits")}>
                credits page
              </button>
              .{license && (
                <>
                  {" "}
                  Its own licence is <External href={license}>here</External>.
                </>
              )}
            </p>
          </section>

          <section>
            <h3>Risk</h3>
            <p>
              Trading leveraged products carries a high risk of losing money. {PROJECT.name} is provided “as is”,
              without warranty of any kind, and is not financial advice. Try everything on a demo account first.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
