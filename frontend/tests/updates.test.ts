import { test } from "node:test";
import assert from "node:assert/strict";
import {
  RESTART_PATIENCE,
  SAME_VERSION_GRACE,
  checkedText,
  formatBytes,
  progressPercent,
  restartOutcome,
  updateChip,
  updateLine,
  whatIsNew,
} from "../src/lib/updates.ts";
import type { UpdateStatus } from "../src/lib/types.ts";

const base: UpdateStatus = {
  enabled: true,
  current: "0.1.1",
  latest: "0.2.0",
  available: true,
  skipped: false,
  can_install: true,
  installable_here: true,
  notes: "",
  page: "https://github.com/x/y/releases/tag/v0.2.0",
  published: "",
  size: 60_000_000,
  checked_at: 1_000_000,
  error: null,
  phase: "idle",
  message: "",
  done: 0,
  total: 0,
  result: null,
};

test("sizes are written the way people read them", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(-5), "0 B");
  assert.equal(formatBytes(900), "900 B");
  assert.equal(formatBytes(340 * 1024), "340 KB");
  assert.equal(formatBytes(58.14 * 1024 * 1024), "58.1 MB");
  assert.equal(formatBytes(1.5 * 1024 * 1024 * 1024), "1.50 GB");
});

test("a release's text is cut down to what is new", () => {
  const notes = [
    "## Install",
    "",
    "* **Installer** (`CheapTrader-0.2.0-setup.exe`) or the portable zip.",
    "",
    "## What is in 0.2.0",
    "",
    "**Replay**",
    "* Paper-trading profiles with `balance` of their own.",
    "  * A nested line",
    "",
    "",
    "",
    "### Fixed",
    "- A position left open is closed.",
  ].join("\n");
  assert.equal(
    whatIsNew(notes),
    ["Replay", "• Paper-trading profiles with balance of their own.", "  • A nested line", "", "Fixed", "• A position left open is closed."].join("\n"),
  );
});

test("a bullet that was wrapped by hand is one line again", () => {
  const notes = [
    "## What is in 0.2.0",
    "",
    "* When the window is hidden and the program is closed, the terminal is closed with it. Before, it stayed",
    "  running with no window and no taskbar",
    "  button.",
    "* Another one.",
    "  * A nested bullet, which stays one.",
    "",
    "  Indented text after a blank line is not joined to anything.",
  ].join("\n");
  assert.equal(
    whatIsNew(notes),
    [
      "• When the window is hidden and the program is closed, the terminal is closed with it. Before, it stayed running with no window and no taskbar button.",
      "• Another one.",
      "  • A nested bullet, which stays one.",
      "",
      "  Indented text after a blank line is not joined to anything.",
    ].join("\n"),
  );
});

test("a release without that heading is shown whole, and other spellings of it are understood", () => {
  assert.equal(whatIsNew("Just a line.\r\n\r\n* one"), "Just a line.\n\n• one");
  assert.equal(whatIsNew("## Install\n\nx\n\n## What's new in 0.3.0\n\n* y"), "• y");
  assert.equal(whatIsNew("## Install\n\nx\n\n## What is new in 0.3.0\n\n* z"), "• z");
  assert.equal(whatIsNew(""), "");
});

test("the share of a download is a whole number between 0 and 100, or unknown", () => {
  assert.equal(progressPercent(0, 0), null);
  assert.equal(progressPercent(5, 0), null);
  assert.equal(progressPercent(0, 100), 0);
  assert.equal(progressPercent(333, 1000), 33);
  assert.equal(progressPercent(2000, 1000), 100);
});

test("when the last look was is told in the largest sensible unit", () => {
  const now = 1_000_000;
  assert.equal(checkedText({ checked_at: null }, now), "Not checked yet.");
  assert.equal(checkedText({ checked_at: now - 20 }, now), "Checked just now.");
  assert.equal(checkedText({ checked_at: now - 60 }, now), "Checked 1 minute ago.");
  assert.equal(checkedText({ checked_at: now - 600 }, now), "Checked 10 minutes ago.");
  assert.equal(checkedText({ checked_at: now - 7300 }, now), "Checked 2 hours ago.");
  assert.equal(checkedText({ checked_at: now - 3 * 86_400 - 5 }, now), "Checked 3 days ago.");
  assert.equal(checkedText({ checked_at: now + 500 }, now), "Checked just now.", "a clock a little off is not a time in the future");
});

test("the About window's line says what is known", () => {
  assert.equal(updateLine({ ...base }), "Version 0.2.0 is available.");
  assert.equal(updateLine({ ...base, skipped: true }), "Version 0.2.0 is available (you chose to skip it).");
  assert.equal(updateLine({ ...base, available: false }), "You have the latest version.");
  assert.equal(updateLine({ ...base, latest: null, available: false }), "Not checked yet.");
  assert.equal(updateLine({ ...base, latest: null, available: false, enabled: false }), "Looking for updates is switched off.");
  assert.equal(updateLine({ ...base, error: "Could not reach GitHub." }), "Could not reach GitHub.");
});

test("the top bar button shows an update, its progress and its failure, and nothing otherwise", () => {
  assert.equal(updateChip(null), null);
  assert.equal(updateChip({ ...base, available: false }), null);
  assert.equal(updateChip({ ...base, skipped: true }), null);
  assert.deepEqual(updateChip({ ...base })?.label, "Update 0.2.0");
  assert.equal(updateChip({ ...base })?.tone, "available");
  assert.equal(updateChip({ ...base, phase: "downloading", done: 30, total: 120 })?.label, "Updating 25%");
  assert.equal(updateChip({ ...base, phase: "downloading", done: 0, total: 0 })?.label, "Updating…");
  assert.equal(updateChip({ ...base, phase: "verifying", done: 120, total: 120 })?.label, "Updating…");
  assert.equal(updateChip({ ...base, phase: "installing" })?.label, "Installing…");
  assert.deepEqual(updateChip({ ...base, phase: "failed", message: "Cut off." }), { label: "Update failed", tone: "failed", title: "Cut off." });
});

test("after an install the page waits, then reloads on the new version", () => {
  const still = (extra = {}) => ({ up: true, version: "0.1.1", sameFor: 1, ...extra });
  assert.deepEqual(restartOutcome("0.1.1", { up: false, sameFor: 0 }, 5), { state: "waiting" });
  assert.deepEqual(restartOutcome("0.1.1", { up: true, version: "0.2.0", sameFor: 0 }, 9), { state: "done", version: "0.2.0" });
  // the old program is still answering while it closes
  assert.deepEqual(restartOutcome("0.1.1", still({ status: { ...base, phase: "installing" } }), 3), { state: "waiting" });
  assert.deepEqual(restartOutcome("0.1.1", still(), 3), { state: "waiting" });
});

test("after an install that did not work the page says why", () => {
  const same = (extra = {}) => ({ up: true, version: "0.1.1", sameFor: 1, ...extra });
  const result = { version: "0.2.0", ok: false, message: "The installer for 0.2.0 did not finish (exit code 5)." };
  assert.deepEqual(restartOutcome("0.1.1", same({ status: { ...base, phase: "idle", result } }), 30), { state: "failed", message: result.message });
  assert.deepEqual(restartOutcome("0.1.1", same({ status: { ...base, phase: "failed", message: "Cut off." } }), 30), { state: "failed", message: "Cut off." });
  // the same version answering for a while, with nothing said about it
  const quiet = restartOutcome("0.1.1", same({ sameFor: SAME_VERSION_GRACE, status: { ...base, phase: "idle" } }), 40);
  assert.equal(quiet.state, "failed");
  assert.match(quiet.state === "failed" ? quiet.message : "", /still|not installed/i);
});

test("a program that never comes back is given up on, a new version that comes back late is not", () => {
  const late = restartOutcome("0.1.1", { up: false, sameFor: 0 }, RESTART_PATIENCE + 1);
  assert.equal(late.state, "failed");
  assert.deepEqual(restartOutcome("0.1.1", { up: true, version: "0.2.0", sameFor: 0 }, RESTART_PATIENCE + 50), { state: "done", version: "0.2.0" });
});
