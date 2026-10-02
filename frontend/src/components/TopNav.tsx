// TradingView-style header: one toolbar, left to right
//
//   brand · symbol search | intervals ▾ | Indicators | Replay ........ ⛶ · Trade
//
// One control per function: the symbol button opens the search overlay (which
// also opens a symbol), Indicators and Trade each toggle their tab of the side
// panel, and everything else the header could offer — alerts, compare, layouts,
// chart types — is simply not rendered because the app has no such feature.

import { Fragment, useState } from "react";
import { useDismiss } from "../lib/hooks";
import { QUICK_TIMEFRAMES, TF, TIMEFRAME_GROUPS } from "../lib/timeframes";
import { TIMEFRAMES, type Timeframe } from "../lib/types";
import {
  BrandMark,
  ChevronDown,
  FullscreenExitIcon,
  FullscreenIcon,
  IndicatorsIcon,
  ReplayIcon,
  SearchIcon,
  UpdateIcon,
} from "./Icons";

interface Props {
  symbol: string | null;
  timeframe: Timeframe;
  onTimeframe: (tf: Timeframe) => void;
  /** The pointer (or focus) is on an interval: start loading it so the click is instant. */
  onPrefetch?: (tf: Timeframe) => void;
  onOpenSymbolSearch: () => void;
  indicatorsOpen: boolean;
  tradeOpen: boolean;
  onToggleIndicators: () => void;
  onToggleTrade: () => void;
  replayActive: boolean;
  onReplay: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  /** A newer version is on GitHub (or being installed): the button that opens its window. */
  update?: { label: string; tone: "available" | "busy" | "failed"; title: string } | null;
  onUpdate?: () => void;
}

export function TopNav(props: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismiss<HTMLDivElement>(() => setMenuOpen(false), menuOpen);

  // The favourites are pinned; an interval picked from the menu is shown too, so
  // the header always says what the chart is on.
  const pinned = QUICK_TIMEFRAMES.includes(props.timeframe)
    ? QUICK_TIMEFRAMES
    : [...QUICK_TIMEFRAMES, props.timeframe].sort((a, b) => TF[a].seconds - TF[b].seconds);

  return (
    <header className="tv-header">
      <div className="tv-brand" title="CheapTrader">
        <BrandMark size={24} />
      </div>

      <button className="tv-symbol" onClick={props.onOpenSymbolSearch} title="Symbol search">
        <SearchIcon size={22} />
        <span>{props.symbol ?? "—"}</span>
      </button>

      <span className="tv-sep" />

      <div className="tv-intervals">
        {pinned.map((tf) => (
          <button
            key={tf}
            className={tf === props.timeframe ? "tv-hbtn tv-int active" : "tv-hbtn tv-int"}
            title={TF[tf].long}
            onPointerEnter={() => props.onPrefetch?.(tf)}
            onFocus={() => props.onPrefetch?.(tf)}
            onClick={() => props.onTimeframe(tf)}
          >
            {TF[tf].short}
          </button>
        ))}
        <div className="tv-anchor" ref={menuRef}>
          <button
            className={menuOpen ? "tv-hbtn tv-int tv-int-more active" : "tv-hbtn tv-int tv-int-more"}
            title="All intervals"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <ChevronDown size={18} />
          </button>
          {menuOpen && (
            <div className="tv-menu" role="menu">
              {TIMEFRAME_GROUPS.map((group) => (
                <Fragment key={group}>
                  <div className="tv-menu-title">{group}</div>
                  {TIMEFRAMES.filter((tf) => TF[tf].group === group).map((tf) => (
                    <button
                      key={tf}
                      role="menuitem"
                      className={tf === props.timeframe ? "tv-menu-item active" : "tv-menu-item"}
                      onPointerEnter={() => props.onPrefetch?.(tf)}
                      onFocus={() => props.onPrefetch?.(tf)}
                      onClick={() => {
                        props.onTimeframe(tf);
                        setMenuOpen(false);
                      }}
                    >
                      {TF[tf].long}
                    </button>
                  ))}
                </Fragment>
              ))}
            </div>
          )}
        </div>
      </div>

      <span className="tv-sep" />

      <button
        className={props.indicatorsOpen ? "tv-hbtn active" : "tv-hbtn"}
        onClick={props.onToggleIndicators}
        title="Indicators"
      >
        <IndicatorsIcon />
        <span className="tv-hbtn-label">Indicators</span>
      </button>

      <span className="tv-sep" />

      <button
        className={props.replayActive ? "tv-hbtn active" : "tv-hbtn"}
        onClick={props.onReplay}
        title="Bar replay"
      >
        <ReplayIcon />
        <span className="tv-hbtn-label">Replay</span>
      </button>

      <div className="tv-header-right">
        {props.update && (
          <button className={`tv-update ${props.update.tone}`} onClick={props.onUpdate} title={props.update.title}>
            <UpdateIcon size={18} />
            <span>{props.update.label}</span>
          </button>
        )}
        <button
          className="tv-hbtn tv-icon"
          title={props.fullscreen ? "Exit full screen" : "Full screen"}
          onClick={props.onToggleFullscreen}
        >
          {props.fullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
        </button>

        <button
          className={props.tradeOpen ? "tv-trade active" : "tv-trade"}
          onClick={props.onToggleTrade}
          title="Order ticket"
        >
          <span className="tv-trade-logo">
            <BrandMark size={22} />
          </span>
          <span>Trade</span>
        </button>
      </div>
    </header>
  );
}
