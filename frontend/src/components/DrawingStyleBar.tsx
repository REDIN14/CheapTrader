// The little bar over a selected drawing: lock, colour, thickness, "extend to the right" and delete.
// For a long / short box it also holds how big the trade is (a share of the balance, an amount, or
// lots) and the buttons that place it: now, or waiting at the box's entry.

import { useEffect, useState, type RefObject } from "react";
import type { BoxOrder } from "../lib/boxOrder";
import type { BoxTrading, BoxView } from "../lib/boxTrading";
import { CAN_EXTEND, COLORS, styleOf, type Drawing, type DrawingStyle } from "../lib/drawings";
import { formatMoney } from "../lib/format";
import { kindTitle } from "../lib/orders";
import { DEFAULTS, formatVolume, type RiskMode } from "../lib/sizing";
import { ExtendRightIcon, LockIcon, TrashIcon, UnlockIcon } from "./Icons";

const LINE_WIDTHS = [1, 2, 3, 4];

const round2 = (value: number) => Math.round(value * 100) / 100;

interface Props {
  drawing: Drawing;
  /** The trade a long / short box stands for; null for every other drawing. */
  view: BoxView | null;
  trading: BoxTrading;
  /** The box's size field, so a menu entry can send the user to it. */
  sizeInput: RefObject<HTMLInputElement>;
  onStyle: (change: DrawingStyle) => void;
  onLock: (locked: boolean) => void;
  onDelete: () => void;
  onOrder: (order: BoxOrder) => void;
}

export function StyleBar({ drawing, view, trading, sizeInput, onStyle, onLock, onDelete, onOrder }: Props) {
  const style = styleOf(drawing);
  const locked = !!drawing.locked;
  const box = view !== null;
  const lined = !box && drawing.type !== "text";
  const extendable = CAN_EXTEND.includes(drawing.type);
  const extended = !!style.extend_right;

  return (
    <>
      <button
        className={locked ? "dr-tool on" : "dr-tool"}
        title={locked ? "Locked: it cannot be moved or deleted. Click to unlock." : "Lock it, so it cannot be moved or deleted"}
        aria-label={locked ? "Unlock the drawing" : "Lock the drawing"}
        aria-pressed={locked}
        onClick={() => onLock(!locked)}
      >
        {locked ? <LockIcon size={22} /> : <UnlockIcon size={22} />}
      </button>

      {view && <SizeEditor drawing={drawing} view={view} trading={trading} inputRef={sizeInput} onStyle={onStyle} />}

      {!box && (
        <span className="dr-swatches">
          {COLORS.map((c) => (
            <button
              key={c}
              className={c.toLowerCase() === style.color.toLowerCase() ? "dr-swatch on" : "dr-swatch"}
              style={{ background: c }}
              title="Colour"
              aria-label={`Colour ${c}`}
              onClick={() => onStyle({ color: c, fill: drawing.style.fill ? c : undefined })}
            />
          ))}
        </span>
      )}
      {lined && (
        <span className="dr-widths">
          {LINE_WIDTHS.map((w) => (
            <button
              key={w}
              className={w === style.width ? "dr-width on" : "dr-width"}
              title={`Line ${w}`}
              aria-label={`Line thickness ${w}`}
              onClick={() => onStyle({ width: w })}
            >
              <i style={{ height: w }} />
            </button>
          ))}
        </span>
      )}
      {extendable && (
        <button
          className={extended ? "dr-tool on" : "dr-tool"}
          title={extended ? "Stops at its right end (click to stop extending)" : "Extend to the right"}
          aria-label="Extend to the right"
          aria-pressed={extended}
          onClick={() => onStyle({ extend_right: !extended })}
        >
          <ExtendRightIcon size={22} />
        </button>
      )}

      {view && <OrderButtons view={view} trading={trading} onOrder={onOrder} />}

      <button
        className="dr-tool danger"
        title={locked ? "Locked: unlock it to delete it" : "Delete (Del)"}
        aria-label="Delete the drawing"
        disabled={locked}
        onClick={onDelete}
      >
        <TrashIcon size={22} />
      </button>
    </>
  );
}

/** How big the trade is: a number and its unit (share of the balance, money, lots), and what that comes to. */
function SizeEditor({
  drawing,
  view,
  trading,
  inputRef,
  onStyle,
}: {
  drawing: Drawing;
  view: BoxView;
  trading: BoxTrading;
  inputRef: RefObject<HTMLInputElement>;
  onStyle: (change: DrawingStyle) => void;
}) {
  const style = drawing.style;
  const mode: RiskMode = style.risk_mode ?? "percent";
  const current =
    mode === "percent" ? (style.risk_percent ?? DEFAULTS.percent) : mode === "amount" ? (style.risk_amount ?? DEFAULTS.amount) : (style.lots ?? DEFAULTS.lots);
  const [text, setText] = useState(String(current));
  useEffect(() => setText(String(current)), [current, mode, drawing.id]);

  const size = view.size;
  const step = trading.symbol?.volume_step ?? 0.01;

  const commit = () => {
    const n = Number(text.trim().replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) {
      setText(String(current));
      return;
    }
    if (n === current) return;
    onStyle(
      mode === "percent"
        ? { risk_mode: "percent", risk_percent: Math.min(100, n) }
        : mode === "amount"
          ? { risk_mode: "amount", risk_amount: n }
          : { risk_mode: "lots", lots: n },
    );
  };

  // Changing the unit keeps the trade as it is: the number becomes what the same trade comes to in the new unit.
  const changeUnit = (next: RiskMode) => {
    if (next === mode) return;
    const keep = size?.ok ? size : null;
    if (next === "percent") onStyle({ risk_mode: next, risk_percent: keep && keep.riskPercent > 0 ? Math.min(100, round2(keep.riskPercent)) : DEFAULTS.percent });
    else if (next === "amount") onStyle({ risk_mode: next, risk_amount: keep && keep.risk > 0 ? round2(keep.risk) : DEFAULTS.amount });
    else onStyle({ risk_mode: next, lots: keep ? keep.lots : DEFAULTS.lots });
  };

  let result = "—";
  let tip = size?.problem ?? "The size of the trade cannot be worked out yet.";
  let warn = false;
  if (size?.ok) {
    result = `${formatVolume(size.lots, step)} lots`;
    tip = `If the stop is hit this loses ${formatMoney(size.risk, trading.currency)}${size.riskPercent > 0 ? ` (${size.riskPercent.toFixed(2)}% of the balance)` : ""}.`;
    if (size.capped === "min") {
      warn = true;
      tip += " That is more than was asked for: the smallest volume the broker takes is already that much.";
    } else if (size.capped === "max") {
      warn = true;
      tip += " The largest volume the broker takes is less than the risk asked for would need.";
    }
  }

  return (
    <span className="dr-size" title="How big the trade is">
      <span className="dr-size-label">Risk</span>
      <input
        ref={inputRef}
        className="dr-num"
        inputMode="decimal"
        aria-label="Size of the trade"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          else if (e.key === "Escape") {
            setText(String(current));
            e.currentTarget.blur();
          }
        }}
      />
      <select className="dr-unit" aria-label="Unit of the size" value={mode} onChange={(e) => changeUnit(e.target.value as RiskMode)}>
        <option value="percent">%</option>
        <option value="amount">{trading.currency || "$"}</option>
        <option value="lots">lots</option>
      </select>
      <span className={warn ? "dr-size-out warn" : "dr-size-out"} title={tip}>
        {result}
      </span>
    </span>
  );
}

/** Buy or sell now with the box's stop and target, or leave an order waiting at its entry. */
function OrderButtons({ view, trading, onOrder }: { view: BoxView; trading: BoxTrading; onOrder: (order: BoxOrder) => void }) {
  const { plan, now, wait } = view;
  const word = plan.side === "BUY" ? "Buy" : "Sell";
  const tone = plan.side === "BUY" ? "buy" : "sell";
  const why = (order: BoxOrder | null) => (!trading.enabled ? "Orders cannot be sent right now." : !order ? "Not worked out yet." : order.problem);
  const price = (value: number) => value.toFixed(trading.digits);
  const detail = (order: BoxOrder) => `${formatVolume(order.volume, trading.symbol?.volume_step ?? 0.01)} lots · stop ${price(order.sl)} · target ${price(order.tp)}`;

  return (
    <span className="dr-orders">
      <button
        className={`dr-order ${tone}`}
        disabled={!!why(now)}
        title={why(now) ?? `${word} at the market now: ${detail(now!)}`}
        onClick={() => now && onOrder(now)}
      >
        {word} now
      </button>
      {wait && (
        <button
          className={`dr-order ${tone} ghost`}
          disabled={!!why(wait)}
          title={
            why(wait) ??
            `Leave a ${wait.kind ? kindTitle(wait.kind).toLowerCase() : "order"} at the entry ${price(plan.entry)}: ${detail(wait)}`
          }
          onClick={() => onOrder(wait)}
        >
          {wait.kind ? kindTitle(wait.kind) : "At entry"}
        </button>
      )}
    </span>
  );
}
