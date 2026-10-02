# Changelog

All notable changes to CheapTrader. The version is in `backend/app/__init__.py`.

## 0.1.3 — the program opens itself again after an update

* Installing an update from the program now ends with the program open again. In 0.1.2 the update was installed, but
  the program did not come back: it stopped with the message "Failed to load Python DLL" and had to be started by
  hand. The program that was being replaced passed its start-up information on to the new one, and that pointed to
  temporary files which were deleted when the old program closed. The update now starts the new program fresh.
* Updating *from* 0.1.2 still ends with that message once, because it is 0.1.2 that opens the new version. The update
  has worked by then: click OK and start CheapTrader. From 0.1.3 on the program restarts by itself.
* The notes in the update window no longer break in the middle of a sentence.

## 0.1.2 — a hidden MetaTrader terminal closes with the program

* When the MetaTrader window is hidden (the *Hide the MetaTrader window* switch in the MetaTrader panel) and
  CheapTrader is closed, the terminal is now closed with it. Before, it stayed running with no window and no taskbar
  button, and had to be ended in Task Manager.
* Only a terminal that the program was told to hide is closed. One whose window is on the screen, minimised or not,
  is left as it is.
* The terminal is asked to close the way its own close button asks, and is never forced. If it is still there after
  ten seconds (a dialog may be waiting for an answer in the hidden window), its window is shown again so that you can
  answer it, and the terminal keeps running.
* Anything else running in that terminal, such as an Expert Advisor, stops with it. Show the window before closing
  CheapTrader to keep the terminal open. The switch's text in the MetaTrader panel says so.

## 0.1.1 — profiles, updates, a new site, support links

The 0.1.1 installer was rebuilt on 2 October 2026 so that it includes everything below (the first build of 0.1.1 had only the support links).

**Replay**
* The paper account is now a **profile**: a named account with a starting balance of your choice. Make as many as
  you like (one per strategy), switch between them, rename them, start one over with a new balance, delete them.
  The menu is beside the *Replay* tag in the side panel and at the end of the start bar.
* A profile **keeps its balance and its whole trade history** when a replay ends, when another replay starts and
  when the program is restarted. Before, every replay began again with 10,000. Each profile is a file of its own
  in the data folder (`replay\profiles`), saved on every trade and every couple of seconds while a replay runs.
* A position still open when a replay ends (leave, pick another bar, close the program, or a crash) is closed at
  the last price it was marked at and recorded as *Replay ended*; stepping back records *Rewound*.
* Profit is calculated in the account's currency from the broker's tick value (a yen pair no longer reads in
  yen), and booked in cents.
* Trades remember their symbol: the chart marks those of the symbol on screen, the history and the report list
  them all.
* New backend routes: `POST /api/replay/stop` and `/api/replay/profiles` (list, make, rename, choose, start over,
  delete). `reset-account` starts only the profile in use over.

**Updates**
* The program looks at GitHub's release list a little after it starts and every six hours, and shows an **Update**
  button when a newer release exists. **Install and restart** downloads the installer, checks its SHA-256 against
  the release's `SHA256SUMS.txt`, closes the program, installs and opens it again, without touching the data
  folder. Nothing is downloaded until you click. **Skip this version** hides a release.
* Only a copy set up by the installer can install itself; a portable copy gets a link to the release page.
* The check can be switched off in the About window (or `CT_UPDATE_CHECK=false`). It is the only connection the
  program makes to the internet by itself.
* New routes: `GET /api/update`, `POST /api/update/check`, `/install`, `/skip`, `/enabled`. New start option:
  `--reconnect` (what an update starts the new version with, so the open window is kept).

**Website**
* The GitHub Pages site was rewritten: plain text, real screenshots, no stock template, and no outside requests.

**Support**
* The project can be supported on Ko-fi: the link is in the *About & support* window, on the last page of the
  welcome tour, in the README and behind the repository's **Sponsor** button.

## 0.1.0 — first public release

**Charts and data**
* TradingView-style candlestick chart with live prices from MetaTrader 5, a watchlist of every symbol the
  broker offers, all intervals, saved layout, price tags, right-click menu.
* A persistent bar store: history is fetched once and then served locally.
* Runs without MetaTrader on a synthetic market; connects to MetaTrader by itself, without a restart, as soon
  as a terminal is open and logged in.

**Trading**
* Market orders and limit / stop orders (placed from the ticket, the chart's right-click menu or a position box),
  stop loss and take profit that can be dragged on the chart, pending orders shown and editable on the chart.
* Long / short position boxes that can place their trade: buy or sell now with their stop and target, leave a
  limit order at the entry, put their levels on an open position, and size the trade by risk (percent of
  balance, an amount, or lots). After a fill the box's entry line moves to where the trade opened.
* **Orders from the app are off in a fresh install.** A switch in the MetaTrader menu turns them on.

**Drawing tools**
* Trend line, long / short position, rectangle (extended to the right), parallel channel. Saved per symbol; can
  be locked (no moving, no deleting), removed for one symbol or all, and added from Python or the REST API.

**Indicators**
* Built-in indicators and your own in Python (`compute(df, params)`), overlays and panes, shapes drawn with
  `ct_draw`, run in a sandbox.

**Replay**
* Bar replay with a paper account, stop loss / take profit, trade markers and a performance report.

**Windows program**
* `CheapTrader.exe` (one file, no Python needed) and an installer; a welcome tour on first start that checks
  and connects MetaTrader; in-app documentation; About window with credits.

**Safety**
* Listens on `127.0.0.1` only and refuses requests from other web pages and for other host names.
