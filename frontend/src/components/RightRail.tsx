// The slim icon rail on the right edge, like TradingView's widget bar.
//
// It holds the two controls that have no place in the header: the Watchlist
// toggle at the top, and the keyboard-shortcut reference (the "?" button) at the
// bottom. Panels that the header already opens (Trade, Indicators) are not
// repeated here — one control per function.

import { useState } from "react";
import { useDismiss } from "../lib/hooks";
import { BookIcon, HeartIcon, HelpIcon, WatchlistIcon } from "./Icons";

const SHORTCUTS: [string, string][] = [
  ["F", "Fit chart to screen"],
  ["Esc", "Cancel a drawing or exit replay"],
  ["Del", "Delete the selected drawing"],
  ["Drag", "Pan the chart"],
  ["Wheel", "Zoom the chart"],
  ["Drag an axis", "Stretch price or time"],
  ["Double-click", "Fit chart to screen"],
  ["Right-click", "Copy price, set SL / TP"],
  ["Drag TP / SL", "Place it on the chart"],
  ["Space", "Play / pause a replay"],
  ["→", "Next bar in a replay"],
];

interface Props {
  watchlistOpen: boolean;
  onToggleWatchlist: () => void;
  /** Open the documentation. */
  onDocs: () => void;
  /** Open the welcome tour. */
  onTour: () => void;
  /** Open the About window (credits, support). */
  onAbout: () => void;
}

export function RightRail({ watchlistOpen, onToggleWatchlist, onDocs, onTour, onAbout }: Props) {
  const [helpOpen, setHelpOpen] = useState(false);
  const helpRef = useDismiss<HTMLDivElement>(() => setHelpOpen(false), helpOpen);

  return (
    <nav className="tv-rail" aria-label="Side bar">
      <button
        className={watchlistOpen ? "tv-rail-btn active" : "tv-rail-btn"}
        title={watchlistOpen ? "Hide watchlist" : "Show watchlist"}
        aria-pressed={watchlistOpen}
        onClick={onToggleWatchlist}
      >
        <WatchlistIcon />
      </button>

      <span className="tv-rail-fill" />

      <div className="tv-anchor" ref={helpRef}>
        <button
          className={helpOpen ? "tv-rail-btn active" : "tv-rail-btn"}
          title="Help: shortcuts, tour, documentation"
          aria-expanded={helpOpen}
          onClick={() => setHelpOpen((v) => !v)}
        >
          <HelpIcon />
        </button>
        {helpOpen && (
          <div className="tv-menu tv-menu-keys" role="dialog" aria-label="Keyboard shortcuts">
            <div className="tv-menu-title">KEYBOARD AND MOUSE</div>
            {SHORTCUTS.map(([key, text]) => (
              <div key={key} className="tv-key-row">
                <kbd>{key}</kbd>
                <span>{text}</span>
              </div>
            ))}
            <button
              className="tv-menu-item docs-link"
              onClick={() => {
                setHelpOpen(false);
                onDocs();
              }}
            >
              <BookIcon size={20} />
              <span>Documentation</span>
            </button>
            <button
              className="tv-menu-item"
              onClick={() => {
                setHelpOpen(false);
                onTour();
              }}
            >
              <HelpIcon size={20} />
              <span>Welcome tour</span>
            </button>
            <button
              className="tv-menu-item"
              onClick={() => {
                setHelpOpen(false);
                onAbout();
              }}
            >
              <HeartIcon size={20} />
              <span>About &amp; support</span>
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
