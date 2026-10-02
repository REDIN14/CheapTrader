// TradingView-style watchlist panel.
//
// The table exposes only what the app knows about a symbol — its name and the
// broker's description — because there is no quote feed for unselected symbols.
//
// Selecting a row opens that symbol on the chart. Adding and removing is done
// with the stars: the one in the toolbar acts on the symbol currently on the
// chart, and each row's star removes that row. Searching the broker's full list
// is the header's symbol button, so it is not repeated here.

import { useMemo, useState } from "react";
import type { Symbol } from "../lib/types";
import { CloseIcon, StarIcon } from "./Icons";

interface Props {
  symbols: Symbol[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  /** Symbols the user pinned, newest first. */
  pinned: string[];
  onPinnedChange: (next: string[]) => void;
  onClose: () => void;
}

export function RightPanel({ symbols, selected, onSelect, pinned, onPinnedChange, onClose }: Props) {
  const [query, setQuery] = useState("");

  const byName = useMemo(() => {
    const map = new Map<string, Symbol>();
    for (const s of symbols) map.set(s.name, s);
    return map;
  }, [symbols]);

  // Rows to render: the user's list if they have one, else the first slice of
  // the broker's symbol table. A filter narrows whichever set is showing.
  const rows = useMemo(() => {
    const names = pinned.length ? pinned : symbols.slice(0, 60).map((s) => s.name);
    const q = query.trim().toUpperCase();
    const filtered = q
      ? names.filter(
          (n) => n.toUpperCase().includes(q) || (byName.get(n)?.description ?? "").toUpperCase().includes(q),
        )
      : names;
    return filtered.filter((n) => byName.has(n));
  }, [pinned, symbols, byName, query]);

  const pinnedSelected = selected != null && pinned.includes(selected);

  const toggleSelected = () => {
    if (!selected) return;
    onPinnedChange(
      pinned.includes(selected) ? pinned.filter((n) => n !== selected) : [selected, ...pinned],
    );
  };

  return (
    <aside className="tv-panel tv-watchlist">
      <header className="tv-panel-head">
        <span className="tv-panel-title">Watchlist</span>
        <button className="tv-icon-btn" title="Hide watchlist" onClick={onClose}>
          <CloseIcon size={22} />
        </button>
      </header>

      <div className="tv-wl-tools">
        <button
          className={pinnedSelected ? "tv-icon-btn star on" : "tv-icon-btn star"}
          title={
            selected
              ? pinnedSelected
                ? `Remove ${selected} from the watchlist`
                : `Add ${selected} to the watchlist`
              : "No symbol selected"
          }
          onClick={toggleSelected}
          disabled={!selected}
        >
          <StarIcon size={22} />
        </button>
        <input
          className="tv-wl-filter"
          placeholder={pinned.length ? "Filter your list" : "Filter symbols"}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="tv-table-head">
        <span>Symbol</span>
        <span>Description</span>
      </div>

      <ul className="tv-table">
        {rows.map((name) => {
          const spec = byName.get(name);
          return (
            <li
              key={name}
              className={name === selected ? "tv-row selected" : "tv-row"}
              onClick={() => onSelect(name)}
              title={spec?.description}
            >
              <span className="tv-cell-symbol">
                {pinned.length > 0 && (
                  <button
                    className="tv-star on"
                    title="Remove from the watchlist"
                    onClick={(e) => {
                      e.stopPropagation();
                      onPinnedChange(pinned.filter((n) => n !== name));
                    }}
                  >
                    <StarIcon size={18} />
                  </button>
                )}
                <span className="tv-sym-name">{name}</span>
              </span>
              <span className="tv-sym-desc">{spec?.description}</span>
            </li>
          );
        })}
        {rows.length === 0 && (
          <li className="tv-empty">
            <p>{query.trim() ? "No symbol matches that filter." : "Your list is empty."}</p>
          </li>
        )}
      </ul>
    </aside>
  );
}
