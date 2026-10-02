// A newer CheapTrader is on GitHub: what is new in it, and a button to install it.
//
// "Install and restart" downloads the installer of the release, checks it against the checksums published with
// it, closes the program, runs the installer and opens the program again. The data folder is not touched. A copy
// that was not set up by the installer (the portable zip, or one run from the source) cannot do that: it links
// to the release page instead. This window stays open while the program restarts and the page reloads by itself.

import { useEffect, useRef } from "react";
import type { Restart } from "../lib/useUpdate";
import type { UpdateStatus } from "../lib/types";
import { isWebAddress } from "../lib/project";
import { formatBytes, progressPercent, whatIsNew } from "../lib/updates";
import { CloseIcon, UpdateIcon } from "./Icons";

interface Props {
  info: UpdateStatus;
  busy: boolean;
  /** Why the last click did not work, in the backend's words. */
  problem: string | null;
  restart: Restart | null;
  onInstall: () => void;
  onSkip: () => void;
  onClose: () => void;
  /** The wait for the program to come back ended badly and the message has been read. */
  onDismiss: () => void;
}

const WHILE_DOWNLOADING: Record<string, string> = {
  downloading: "Downloading the installer",
  verifying: "Checking the download against the published checksum",
  installing: "Closing CheapTrader to install it",
};

export function UpdateDialog({ info, busy, problem, restart, onInstall, onSkip, onClose, onDismiss }: Props) {
  const dialog = useRef<HTMLDivElement>(null);
  const waiting = !!restart && !restart.problem;
  const working = info.phase === "downloading" || info.phase === "verifying" || info.phase === "installing" || waiting;
  const locked = info.phase === "installing" || waiting; // the program is about to close: nothing to do but wait
  const percent = progressPercent(info.done, info.total);
  const notes = whatIsNew(info.notes);
  const page = isWebAddress(info.page) ? info.page : null;

  useEffect(() => {
    dialog.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || locked) return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [locked, onClose]);

  const failure = restart?.problem ?? (info.phase === "failed" ? info.message : null) ?? problem;
  const earlier = info.result && !info.result.ok ? info.result.message : null;

  return (
    <div className="tour-backdrop" onClick={locked ? undefined : onClose}>
      <div
        ref={dialog}
        className="about update-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="about-head">
          <span className="update-mark">
            <UpdateIcon size={26} />
          </span>
          <div>
            <h2 id="update-title">CheapTrader {info.latest} is available</h2>
            <span>
              You have {info.current}
              {info.size > 0 && info.can_install ? ` · download ${formatBytes(info.size)}` : ""}
            </span>
          </div>
          {!locked && (
            <button className="tv-icon-btn" title="Close (Esc)" aria-label="Close" onClick={onClose}>
              <CloseIcon size={22} />
            </button>
          )}
        </header>

        <div className="about-body">
          {notes && (
            <section>
              <h3>What is new</h3>
              <pre className="update-notes">{notes}</pre>
            </section>
          )}

          {info.can_install ? (
            <p>
              Installing downloads the installer from GitHub, checks it against the checksums published with the release,
              closes CheapTrader, installs and opens it again. Your drawings, indicators, settings, paper-trading profiles
              and stored history stay where they are.
            </p>
          ) : (
            <p>
              {info.installable_here
                ? "This release has no installer that can be checked here, so it cannot be installed from this window."
                : "This copy of CheapTrader was not set up by the installer, so it cannot update itself."}{" "}
              Download the new version from its release page.
            </p>
          )}

          {working && (
            <div className="update-progress" role="status">
              <div className="update-bar" aria-hidden="true">
                <i style={{ width: `${waiting || info.phase === "installing" ? 100 : (percent ?? 4)}%` }} />
              </div>
              <span>
                {waiting || info.phase === "installing"
                  ? `Installing ${info.latest}. This window comes back by itself.`
                  : `${WHILE_DOWNLOADING[info.phase]}${
                      info.phase === "downloading" && info.total > 0 ? `: ${formatBytes(info.done)} of ${formatBytes(info.total)}` : "…"
                    }`}
              </span>
            </div>
          )}

          {failure && (
            <p className="update-problem" role="alert">
              {failure}
            </p>
          )}
          {!failure && earlier && !working && <p className="update-problem">{earlier}</p>}

          <div className="tour-actions">
            {info.can_install ? (
              <button className="tour-btn primary" disabled={busy || working} onClick={onInstall}>
                {failure && !working ? "Try again" : "Install and restart"}
              </button>
            ) : (
              page && (
                <a className="tour-btn primary" href={page} target="_blank" rel="noopener noreferrer">
                  Open the download page
                </a>
              )
            )}
            {working && !locked && (
              <button className="tour-btn" onClick={onClose}>
                Keep working
              </button>
            )}
            {!working && (
              <>
                <button className="tour-btn" onClick={restart?.problem ? onDismiss : onClose}>
                  Not now
                </button>
                <button className="tour-btn" onClick={onSkip} title="Do not tell me about this version again">
                  Skip this version
                </button>
              </>
            )}
            {info.can_install && page && !working && (
              <a className="about-link" href={page} target="_blank" rel="noopener noreferrer">
                Release page
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
