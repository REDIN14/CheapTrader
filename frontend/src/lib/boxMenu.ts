// The menu a right-click on a drawing opens. For a long / short box it is where its trade is placed:
// now, or waiting at its entry; put its stop and target on a position that is already open; choose
// how big the trade is. Every drawing can be locked and deleted from it.

import type { ContextMenuItem } from "../components/ChartContextMenu";
import type { BoxOrder } from "./boxOrder";
import type { BoxTrading, BoxView } from "./boxTrading";
import type { Drawing, DrawingStyle } from "./drawings";
import { formatMoney } from "./format";
import { kindTitle, levelsProblem } from "./orders";
import { formatVolume } from "./sizing";
import type { Position } from "./types";

export interface MenuActions {
  /** Send the order of the box. */
  order: (order: BoxOrder) => void;
  /** Put the box's stop and target on a position that is open. */
  applyTo: (position: Position) => void;
  /** Change how big the trade is. */
  setSize: (change: DrawingStyle) => void;
  /** Open the size editor in the bar over the box. */
  editSize: () => void;
  lock: (locked: boolean) => void;
  remove: () => void;
}

/** The shares of the balance offered as one-click sizes. */
export const RISK_PRESETS = [0.5, 1, 2, 5] as const;

const near = (a: number, b: number) => Math.abs(a - b) < 1e-9;

export function buildDrawingMenu(
  drawing: Drawing,
  view: BoxView | null,
  trading: BoxTrading,
  act: MenuActions,
): ContextMenuItem[] {
  const items: ContextMenuItem[] = [];
  const locked = !!drawing.locked;
  const price = (value: number) => value.toFixed(trading.digits);

  if (view && view.size) {
    const { plan, size } = view;
    const word = plan.side === "BUY" ? "Buy" : "Sell";
    const tone = plan.side === "BUY" ? "buy" : "sell";
    const step = trading.symbol?.volume_step ?? 0.01;
    const lots = size.ok ? formatVolume(size.lots, step) : "";
    items.push({
      key: "title",
      heading: true,
      label: size.ok
        ? `${plan.side === "BUY" ? "Long" : "Short"} · ${lots} lots${size.capped === "min" ? " (the smallest)" : size.capped === "max" ? " (the largest)" : ""} · risk ${formatMoney(size.risk, trading.currency)}${size.riskPercent > 0 ? ` (${size.riskPercent.toFixed(2)}%)` : ""}`
        : `${plan.side === "BUY" ? "Long" : "Short"}`,
      onSelect: () => undefined,
    });

    const reason = (order: BoxOrder | null): string | undefined => {
      if (!trading.enabled) return "Orders cannot be sent right now";
      if (!order) return "Not worked out yet";
      return order.problem ?? undefined;
    };

    const now = view.now;
    const nowWhy = reason(now);
    items.push({
      key: "now",
      label: `${word} ${lots || "…"} lots now`,
      note: nowWhy ?? `at the market · stop ${price(plan.stop)} · target ${price(plan.target)}`,
      tone,
      disabled: !!nowWhy || !now,
      onSelect: () => now && act.order(now),
    });

    if (view.wait) {
      const wait = view.wait;
      const waitWhy = reason(wait);
      items.push({
        key: "wait",
        label: wait.kind ? `${kindTitle(wait.kind)} ${lots || "…"} lots at ${price(plan.entry)}` : "Wait at the entry",
        note: waitWhy ?? `waits for the price · stop ${price(plan.stop)} · target ${price(plan.target)}`,
        tone,
        disabled: !!waitWhy,
        onSelect: () => act.order(wait),
      });
    }

    // A position that is already open can take the box's stop and target.
    for (const position of trading.positions.filter((p) => p.side === plan.side)) {
      const problem =
        levelsProblem(position.side, position.price_open, plan.stop, plan.target, 0, trading.digits) ??
        (trading.enabled ? undefined : "Orders cannot be sent right now");
      items.push({
        key: `apply-${position.ticket}`,
        label:
          trading.positions.filter((p) => p.side === plan.side).length > 1
            ? `Set stop and target of the open ${position.side.toLowerCase()} ${formatVolume(position.volume)} (#${position.ticket})`
            : `Set stop and target of the open ${position.side.toLowerCase()} ${formatVolume(position.volume)}`,
        note: problem ?? `stop ${price(plan.stop)} · target ${price(plan.target)} from this box`,
        disabled: !!problem,
        separatorBefore: false,
        onSelect: () => act.applyTo(position),
      });
    }

    // How big the trade is.
    items.push({ key: "size-title", heading: true, label: "Size of the trade", separatorBefore: true, onSelect: () => undefined });
    const style = drawing.style;
    const mode = style.risk_mode ?? "percent";
    const percent = style.risk_percent ?? 1;
    for (const share of RISK_PRESETS) {
      items.push({
        key: `risk-${share}`,
        label: `Risk ${share}% of the balance`,
        note: trading.balance != null && trading.balance > 0 ? formatMoney((trading.balance * share) / 100, trading.currency) : undefined,
        checked: mode === "percent" && near(percent, share),
        onSelect: () => act.setSize({ risk_mode: "percent", risk_percent: share }),
      });
    }
    items.push({
      key: "risk-custom",
      label: mode === "percent" ? "Another share, an amount, or lots…" : mode === "amount" ? "An amount (set), another or lots…" : "Lots (set), or a share or amount…",
      onSelect: act.editSize,
    });
  }

  items.push({
    key: "lock",
    label: locked ? "Unlock" : "Lock",
    note: locked ? "Lets it be moved and deleted again" : "It cannot be moved or deleted until unlocked",
    separatorBefore: items.length > 0,
    onSelect: () => act.lock(!locked),
  });
  items.push({
    key: "delete",
    label: "Delete",
    hint: "Del",
    tone: "danger",
    disabled: locked,
    note: locked ? "Locked: unlock it first" : undefined,
    onSelect: act.remove,
  });
  return items;
}
