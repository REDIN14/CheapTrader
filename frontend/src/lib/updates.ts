// Updates: the small amount of logic behind the update button and window. Sizes, the text of a release, the
// share of a download, how long ago the last look was, and what to make of the program coming back after an
// install. Kept apart from the components so that it can be tested.

import type { UpdateStatus } from "./types";

/** "58.1 MB", "340 KB", "12 B". */
export function formatBytes(bytes: number): string {
  if (!(bytes > 0)) return "0 B";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/**
 * What a release says is new. A release page starts with how to install and then has a "What is in <version>"
 * section: that section, as plain lines (headings lose their #, bullets become •, bold and code lose their marks,
 * and a bullet that was wrapped by hand over several lines is one line again, so that the window wraps it its own
 * way). A release without such a heading is shown whole.
 */
export function whatIsNew(notes: string): string {
  const text = notes.replace(/\r\n/g, "\n").trim();
  const heading = text.search(/^#{1,3}\s*What(?:'s| is)?\s+(?:new\s+)?in\b.*$/im);
  const body = heading >= 0 ? text.slice(heading).split("\n").slice(1).join("\n") : text;
  const lines: string[] = [];
  for (const raw of body.split("\n")) {
    const line = raw
      .replace(/^\s*#{1,6}\s*/, "")
      .replace(/^(\s*)[*-]\s+/, "$1• ")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1");
    // an indented line that is no bullet goes on with the line before it
    const goesOn = /^\s+[^\s•]/.test(line) && lines.length > 0 && lines[lines.length - 1].trim() !== "";
    if (goesOn) lines[lines.length - 1] += " " + line.trim();
    else lines.push(line);
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** How much of a download is done, 0 to 100, or null while its size is not known. */
export function progressPercent(done: number, total: number): number | null {
  if (!(total > 0)) return null;
  return Math.max(0, Math.min(100, Math.floor((done / total) * 100)));
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;

/** "Checked just now.", "Checked 5 minutes ago.", "Not checked yet." */
export function checkedText(info: Pick<UpdateStatus, "checked_at">, now = Date.now() / 1000): string {
  if (info.checked_at == null) return "Not checked yet.";
  const age = Math.max(0, now - info.checked_at);
  if (age < 60) return "Checked just now.";
  if (age < 3600) return `Checked ${plural(Math.floor(age / 60), "minute")} ago.`;
  if (age < 86_400) return `Checked ${plural(Math.floor(age / 3600), "hour")} ago.`;
  return `Checked ${plural(Math.floor(age / 86_400), "day")} ago.`;
}

/** The one line the About window says about updates. */
export function updateLine(info: Pick<UpdateStatus, "enabled" | "available" | "skipped" | "latest" | "error" | "checked_at">): string {
  if (info.error) return info.error;
  if (info.available && info.latest) {
    return info.skipped ? `Version ${info.latest} is available (you chose to skip it).` : `Version ${info.latest} is available.`;
  }
  if (info.latest) return "You have the latest version.";
  return info.enabled ? "Not checked yet." : "Looking for updates is switched off.";
}

/** The label of the button in the top bar, or null when there is nothing to show. */
export function updateChip(info: UpdateStatus | null): { label: string; tone: "available" | "busy" | "failed"; title: string } | null {
  if (!info) return null;
  if (info.phase === "failed") return { label: "Update failed", tone: "failed", title: info.message || "The update did not work" };
  if (info.phase === "installing") return { label: "Installing…", tone: "busy", title: "The program closes and opens again" };
  if (info.phase === "downloading" || info.phase === "verifying") {
    const percent = progressPercent(info.done, info.total);
    return {
      label: percent === null || info.phase === "verifying" ? "Updating…" : `Updating ${percent}%`,
      tone: "busy",
      title: `Downloading ${info.latest ?? "the update"}`,
    };
  }
  if (info.available && !info.skipped && info.latest) {
    return { label: `Update ${info.latest}`, tone: "available", title: `CheapTrader ${info.latest} is available (you have ${info.current})` };
  }
  return null;
}

/** What the page sees of the program while it waits for it to come back after an install. */
export interface Probe {
  /** The server answered. */
  up: boolean;
  /** The version it reported. */
  version?: string;
  /** Its update status, when it was asked. */
  status?: UpdateStatus | null;
  /** Seconds that the same version has been answering. */
  sameFor: number;
}

export type Outcome = { state: "waiting" } | { state: "done"; version: string } | { state: "failed"; message: string };

/** How long to wait for the program to come back before giving up. */
export const RESTART_PATIENCE = 240;
/** How long a program that came back as the same version is given to say what happened. */
export const SAME_VERSION_GRACE = 20;

/**
 * The program has been asked to install an update and close. It comes back as the new version (reload the page),
 * or it comes back as the old one because the installer did not finish, or it does not come back at all.
 */
export function restartOutcome(before: string, probe: Probe, waited: number): Outcome {
  if (waited > RESTART_PATIENCE && !(probe.up && probe.version !== before)) {
    return { state: "failed", message: "CheapTrader did not come back. Open it from the Start menu." };
  }
  if (!probe.up) return { state: "waiting" };
  if (probe.version && probe.version !== before) return { state: "done", version: probe.version };
  const status = probe.status;
  if (status?.result && !status.result.ok) return { state: "failed", message: status.result.message };
  if (status?.phase === "failed") return { state: "failed", message: status.message || "The update did not work." };
  if (status?.phase === "installing") return { state: "waiting" }; // the old program is still closing
  if (probe.sameFor >= SAME_VERSION_GRACE) {
    return { state: "failed", message: `CheapTrader started again as version ${before}: the update was not installed.` };
  }
  return { state: "waiting" };
}
