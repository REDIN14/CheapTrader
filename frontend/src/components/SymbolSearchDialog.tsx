// Symbol search overlay, opened by the header symbol button.
//
// Picking a result only switches the chart to that symbol. Adding a symbol to
// the watchlist is a separate action, done with the star — matching the
// TradingView behaviour where the two are independent.
//
// Keyboard: type to filter, ↑ ↓ to move, Enter to open, Esc to close.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Symbol } from "../lib/types";
import { CloseIcon, SearchIcon, StarIcon } from "./Icons";

interface Props {
  symbols: Symbol[];
  selected: string | null;
  onPick: (symbol: string) => void;
  /** Symbols currently in the watchlist; drives the star state. */
  pinned: string[];
  onTogglePin: (symbol: string) => void;
  onClose: () => void;
}

export function SymbolSearchDialog({
  symbols,
  selected,
  onPick,
  pinned,
  onTogglePin,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    const list = q
      ? symbols.filter(
          (s) => s.name.toUpperCase().includes(q) || s.description.toUpperCase().includes(q),
        )
      : symbols;
    return list.slice(0, 200);
  }, [symbols, query]);

  // A new filter starts again from the best match.
  useEffect(() => setActive(0), [query]);

  // Keep the highlighted row in view while arrowing through a long list.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(".tv-modal-row.active")
      ?.scrollIntoView({ block: "nearest" });
  }, [active, matches]);

  const pick = (name: string) => {
    onPick(name);
    onClose();
  };

  return (
    <div className="tv-modal-backdrop" onClick={onClose}>
      <div className="tv-modal" role="dialog" aria-label="Symbol search" onClick={(e) => e.stopPropagation()}>
        <div className="tv-modal-head">
          <SearchIcon size={24} />
          <input
            ref={inputRef}
            className="tv-modal-input"
            placeholder="Search symbol…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, matches.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter" && matches[active]) {
                pick(matches[active].name);
              }
            }}
          />
          <button className="tv-icon-btn" title="Close" onClick={onClose}>
            <CloseIcon size={22} />
          </button>
        </div>

        <div className="tv-modal-cols">
          <span>Symbol</span>
          <span>Description</span>
        </div>

        <ul className="tv-modal-list" ref={listRef}>
          {matches.map((s, i) => {
            const inList = pinned.includes(s.name);
            const classes = ["tv-modal-row"];
            if (s.name === selected) classes.push("selected");
            if (i === active) classes.push("active");
            return (
              <li key={s.name} className={classes.join(" ")} onMouseEnter={() => setActive(i)}>
                <button
                  className={inList ? "tv-star on" : "tv-star"}
                  title={inList ? "Remove from watchlist" : "Add to watchlist"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(s.name);
                  }}
                >
                  <StarIcon size={18} />
                </button>
                <button
                  className="tv-modal-symbol"
                  onClick={() => pick(s.name)}
                  title={`Open ${s.name} on the chart`}
                >
                  <span className="tv-sym-name">{s.name}</span>
                  <span className="tv-sym-desc">{s.description}</span>
                </button>
              </li>
            );
          })}
          {matches.length === 0 && <li className="tv-modal-empty">No symbol matches “{query}”.</li>}
        </ul>
      </div>
    </div>
  );
}
