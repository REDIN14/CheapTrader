// The menu a right-click on the chart opens, in place of the browser's own
// ("Save image as…", "Copy image", "Inspect"). Like TradingView's, its first entry
// copies the price under the pointer. It only ever lists things the app can do.

import { useEffect, useLayoutEffect, useState } from "react";
import { useDismiss } from "../lib/hooks";

export interface ContextMenuItem {
  key: string;
  label: string;
  /** Shortcut or other small text shown on the right. */
  hint?: string;
  /** Draws a divider above this entry. */
  separatorBefore?: boolean;
  onSelect: () => void;
  /** Greyed out and not clickable; `note` says why. */
  disabled?: boolean;
  /** A small line under the label (what the entry will do, or why it cannot). */
  note?: string;
  /** A tick in front: the choice that is on. */
  checked?: boolean;
  /** Colours the entry like the action it is: buying, selling, or removing something. */
  tone?: "buy" | "sell" | "danger";
  /** A heading for the entries below it: text only, nothing to click. */
  heading?: boolean;
}

interface Props {
  /** Pointer position in viewport coordinates. */
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}

/** Keep the menu this far from the window edge when it has to be pushed back inside. */
const MARGIN = 8;

export function ChartContextMenu({ x, y, items, onClose }: Props) {
  // Closes on a press outside the menu and on Escape.
  const ref = useDismiss<HTMLDivElement>(onClose);
  const [place, setPlace] = useState({ left: x, top: y });

  // Open at the pointer, but never hang off the right or bottom edge.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setPlace({
      left: Math.max(MARGIN, Math.min(x, window.innerWidth - width - MARGIN)),
      top: Math.max(MARGIN, Math.min(y, window.innerHeight - height - MARGIN)),
    });
  }, [x, y, items.length, ref]);

  // The menu belongs to one spot on the chart; anything that moves the chart or
  // the window closes it.
  useEffect(() => {
    const close = () => onClose();
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    window.addEventListener("wheel", close, { passive: true });
    return () => {
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("wheel", close);
    };
  }, [onClose]);

  // Keyboard: the first entry is focused on opening, arrows move between entries,
  // Enter / Space activate the focused one.
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button:not(:disabled)")?.focus();
  }, [ref]);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const buttons = [...(ref.current?.querySelectorAll<HTMLElement>("button:not(:disabled)") ?? [])];
    const at = buttons.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "ArrowDown" ? at + 1 : at - 1;
    buttons[(next + buttons.length) % buttons.length]?.focus();
  };

  return (
    <div
      className="tv-ctxmenu"
      role="menu"
      ref={ref}
      style={{ left: place.left, top: place.top }}
      onKeyDown={onKeyDown}
      // Right-clicking the menu itself must not open the browser's menu either.
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((item) => (
        <div key={item.key}>
          {item.separatorBefore && <div className="tv-ctxsep" role="separator" />}
          {item.heading ? (
            <div className="tv-ctxhead" role="presentation">
              {item.label}
            </div>
          ) : (
            <button
              className={`tv-ctxitem${item.tone ? ` ${item.tone}` : ""}${item.note ? " with-note" : ""}`}
              role={item.checked === undefined ? "menuitem" : "menuitemcheckbox"}
              aria-checked={item.checked}
              disabled={item.disabled}
              onClick={() => {
                onClose();
                item.onSelect();
              }}
            >
              {item.checked !== undefined && <span className="tv-ctxtick">{item.checked ? "✓" : ""}</span>}
              <span className="tv-ctxtext">
                <span>{item.label}</span>
                {item.note && <small>{item.note}</small>}
              </span>
              {item.hint && <kbd>{item.hint}</kbd>}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
