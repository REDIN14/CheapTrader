// A transient message: a failure (a refused order, a rejected stop level…) or a
// short confirmation ("Copied 1.12840"). It fades out on its own so a stale
// message never lingers over the chart, and can be dismissed early.

import { useEffect } from "react";
import { CloseIcon } from "./Icons";

interface Props {
  message: string;
  onDismiss: () => void;
  /** Errors are red and stay long enough to read; info is blue and brief. */
  tone?: "error" | "info";
  /** How long it stays up, in ms. */
  duration?: number;
}

export function Toast({ message, onDismiss, tone = "error", duration }: Props) {
  const lifetime = duration ?? (tone === "error" ? 9000 : 2200);

  // A new message restarts the timer.
  useEffect(() => {
    const id = window.setTimeout(onDismiss, lifetime);
    return () => window.clearTimeout(id);
  }, [message, lifetime, onDismiss]);

  return (
    <div className={tone === "error" ? "tv-toast" : "tv-toast info"} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      <button className="tv-icon-btn" title="Dismiss" onClick={onDismiss}>
        <CloseIcon size={20} />
      </button>
    </div>
  );
}
