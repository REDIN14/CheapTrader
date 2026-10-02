// About CheapTrader: the version, where it lives, how to support it, and the credits the licences of the
// parts it is made of ask for (most of all TradingView’s: the chart library requires the notice below and a
// link to tradingview.com in a window of the app that every user can open).

import { useEffect, useRef } from "react";
import { PROJECT, isWebAddress, issuesUrl, licenseUrl, supportLinks } from "../lib/project";
import { BookIcon, BrandMark, CloseIcon, HeartIcon } from "./Icons";

interface Props {
  version: string | null;
  onClose: () => void;
  onDocs: (page: string) => void;
  onTour: () => void;
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

export function AboutDialog({ version, onClose, onDocs, onTour }: Props) {
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
