// The cut line that follows the pointer while a replay start is being chosen:
// everything to its right is shaded (that is what the replay will hide and then
// reveal), and a label says which bar it is on and how much there is to play.

import { lowerBound } from "../lib/barMath";
import type { ChartGeometry, HoverInfo } from "../lib/chart";
import { formatChartTime, formatInt } from "../lib/format";
import type { Bar } from "../lib/types";
import { ScissorsIcon } from "./Icons";

interface Props {
  hover: HoverInfo | null;
  geometry: ChartGeometry | null;
  /** The candles on the chart: how many lie after the hovered bar is worked out from them. */
  bars: Bar[];
  /** Show the clock time (intraday bars) or just the date. */
  intraday: boolean;
}

/** Room kept clear at the label's ends so it never touches the chart's edges. */
const LABEL_MARGIN = 8;

export function ReplayCut({ hover, geometry, bars, intraday }: Props) {
  if (!hover || !geometry) return null;

  const width = geometry.plotWidth();
  const height = geometry.paneHeight();
  if (width <= 0 || height <= 0 || hover.x < 0 || hover.x > width) return null;

  const at = lowerBound(bars, hover.time);
  const ahead = at < bars.length && bars[at].time === hover.time ? bars.length - 1 - at : null;

  // The label sits to the right of the line, or to the left of it near the right edge.
  const flip = hover.x > width - 280;

  return (
    <div className="rp-cut" style={{ width, height }} aria-hidden="true">
      <div className="rp-cut-future" style={{ left: hover.x }} />
      <div className="rp-cut-line" style={{ left: hover.x }} />
      <div
        className={flip ? "rp-cut-label flip" : "rp-cut-label"}
        style={{ left: flip ? hover.x - LABEL_MARGIN : hover.x + LABEL_MARGIN }}
      >
        <ScissorsIcon size={16} />
        <span>{formatChartTime(hover.time, intraday)}</span>
        {ahead != null && <em>{ahead > 0 ? `${formatInt(ahead)} bars to play` : "no bars left to play"}</em>}
      </div>
    </div>
  );
}
