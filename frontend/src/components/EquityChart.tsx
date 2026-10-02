// The paper account's equity over the replay: a line from the opening balance,
// shaded green where the account is ahead of where it started and red where it is
// behind. Hovering reads a point off it. Drawn as plain SVG — it is one line.

import { useEffect, useMemo, useRef, useState } from "react";
import { formatMoney, formatShortTime } from "../lib/format";
import type { EquityPoint } from "../lib/types";

interface Props {
  points: EquityPoint[];
  /** The balance the account started with: the baseline the shading is measured from. */
  baseline: number;
  intraday: boolean;
}

const PAD = { top: 12, right: 12, bottom: 22, left: 64 };

/** A few round numbers to label the vertical axis with. */
function niceTicks(lo: number, hi: number, wanted = 4): number[] {
  const span = hi - lo || Math.abs(hi) * 0.01 || 1;
  const raw = span / wanted;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

export function EquityChart({ points, baseline, intraday }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const read = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const geo = useMemo(() => {
    const { w, h } = size;
    if (w < 80 || h < 60 || points.length < 1) return null;
    const t0 = points[0].time;
    const t1 = points[points.length - 1].time;
    let lo = Math.min(baseline, ...points.map((p) => p.value));
    let hi = Math.max(baseline, ...points.map((p) => p.value));
    const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.002 || 1;
    lo -= pad;
    hi += pad;

    const plotW = w - PAD.left - PAD.right;
    const plotH = h - PAD.top - PAD.bottom;
    const x = (t: number) => PAD.left + (t1 === t0 ? plotW / 2 : ((t - t0) / (t1 - t0)) * plotW);
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * plotH;

    const xy = points.map((p) => [x(p.time), y(p.value)] as const);
    const line = xy.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
    const yBase = y(baseline);
    const area = `${line} L${xy[xy.length - 1][0].toFixed(1)} ${yBase.toFixed(1)} L${xy[0][0].toFixed(1)} ${yBase.toFixed(1)} Z`;
    return { w, h, plotW, plotH, xy, line, area, yBase, y, ticks: niceTicks(lo, hi), t0, t1 };
  }, [size, points, baseline]);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!geo) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    let best = 0;
    let bestDist = Infinity;
    geo.xy.forEach(([x], i) => {
      const d = Math.abs(x - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHover(best);
  };

  const at = hover != null && geo ? points[hover] : null;
  const atXY = hover != null && geo ? geo.xy[hover] : null;

  return (
    <div className="rp-equity" ref={box}>
      {geo ? (
        <svg width={geo.w} height={geo.h} onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img" aria-label="Equity curve">
          <defs>
            <clipPath id="rp-above">
              <rect x={PAD.left} y={0} width={geo.plotW} height={geo.yBase} />
            </clipPath>
            <clipPath id="rp-below">
              <rect x={PAD.left} y={geo.yBase} width={geo.plotW} height={geo.h} />
            </clipPath>
          </defs>

          {geo.ticks.map((v) => (
            <g key={v}>
              <line className="grid" x1={PAD.left} x2={PAD.left + geo.plotW} y1={geo.y(v)} y2={geo.y(v)} />
              <text className="tick" x={PAD.left - 8} y={geo.y(v)} textAnchor="end" dominantBaseline="middle">
                {v.toLocaleString("en-US", { maximumFractionDigits: 2 })}
              </text>
            </g>
          ))}

          <path className="area up" d={geo.area} clipPath="url(#rp-above)" />
          <path className="area down" d={geo.area} clipPath="url(#rp-below)" />
          <line className="base" x1={PAD.left} x2={PAD.left + geo.plotW} y1={geo.yBase} y2={geo.yBase} />
          <path className="line" d={geo.line} />

          <text className="tick" x={PAD.left} y={geo.h - 6} textAnchor="start">
            {formatShortTime(geo.t0, intraday)}
          </text>
          <text className="tick" x={PAD.left + geo.plotW} y={geo.h - 6} textAnchor="end">
            {formatShortTime(geo.t1, intraday)}
          </text>

          {at && atXY && (
            <g className="hover">
              <line x1={atXY[0]} x2={atXY[0]} y1={PAD.top} y2={PAD.top + geo.plotH} />
              <circle cx={atXY[0]} cy={atXY[1]} r={3.5} />
            </g>
          )}
        </svg>
      ) : (
        <p className="rp-empty">The curve appears once the replay has moved.</p>
      )}

      {at && atXY && geo && (
        <div className="rp-equity-tip" style={{ left: Math.min(atXY[0] + 12, geo.w - 170), top: PAD.top }}>
          <b>{formatMoney(at.value)}</b>
          <span className={at.value >= baseline ? "pos" : "neg"}>{formatMoney(at.value - baseline, "", true)}</span>
          <small>{formatShortTime(at.time, intraday)}</small>
        </div>
      )}
    </div>
  );
}
