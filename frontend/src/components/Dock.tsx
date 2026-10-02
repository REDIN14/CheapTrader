// The side panel that holds the order ticket and the Python indicator manager.
// Its header carries the two tabs and a close button, so showing and hiding the
// panel needs no separate toggle.

import type { ReactNode } from "react";
import { CloseIcon } from "./Icons";

export type DockTab = "trade" | "indicators";

interface Props {
  tab: DockTab;
  onTab: (tab: DockTab) => void;
  onClose: () => void;
  children: ReactNode;
}

export function Dock({ tab, onTab, onClose, children }: Props) {
  return (
    <aside className="tv-panel tv-dock">
      <header className="tv-panel-head">
        <div className="tv-tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "trade"}
            className={tab === "trade" ? "tv-tab active" : "tv-tab"}
            onClick={() => onTab("trade")}
          >
            Trade
          </button>
          <button
            role="tab"
            aria-selected={tab === "indicators"}
            className={tab === "indicators" ? "tv-tab active" : "tv-tab"}
            onClick={() => onTab("indicators")}
          >
            Indicators
          </button>
        </div>
        <button className="tv-icon-btn" title="Close panel" onClick={onClose}>
          <CloseIcon size={22} />
        </button>
      </header>
      <div className="tv-panel-body">{children}</div>
    </aside>
  );
}
