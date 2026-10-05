# Changelog

All notable changes to CheapTrader. The version is in `backend/app/__init__.py`.

## 0.2.4 — indicator settings that take effect

* **Saving an indicator's settings works.** Every Save in an indicator's settings was refused ("Field required":
  the page sent the change without the indicator's id, which the program also wanted in the body), so a new period
  or any other change never reached the chart. The program now takes a change without the id, and changes only the
  fields that are given.
* **The parameters of the built-in indicators can be changed.** The 20-bar Simple Moving Average can become a 50-bar
  one, and so on: press Save and the chart draws it at once. The values are checked (a period is a whole number of at
  least 1, a multiplier is above 0), they are kept in the data folder, and Reset to defaults brings the built-in's own
  back. The code of a built-in stays as it comes; Copy makes an indicator of your own from it.
* **The gear of an indicator in the chart's legend opens that indicator's settings** (it opened the list), and the
  legend shows the values after the name, as TradingView does: "Simple Moving Average 50".
* A save that is refused says why in red next to the Save button (it was small grey text under it).

## 0.2.3 — indicators see the whole chart

* **An indicator is run over every candle on the chart, not just the newest 500.** The page asked for 500 bars
  whatever the chart held, so on a chart of 20,000 candles a line covered the last few percent of it (scroll back
  and it ended), a 200-bar average started late, one over 500 bars or more was empty, and a replay that began more
  than 500 bars back had no indicator line at all. Now the indicator gets as many bars as the chart shows (the bar
  count at the bottom left, 20,000 by default, up to 100,000), and during a replay every bar back to the replay's
  first candle (the lines are still cut at the cursor, so they cannot show the future).
* **An indicator that needs more says so.** One line at the top level of its code, `NEEDS_BARS = 60_000`, makes the
  program run it over that many bars (200,000 at most; where the broker has fewer it gets what there is). Only the
  lines over the chart's own bars come back, the older bars warm the indicator up. The screenshot tool (`POST
  /api/snapshot`) warms indicators up the same way. The line is read without running the code. See the indicator
  guide, "How many bars `df` holds".
* The indicators of a chart are run side by side instead of one after the other.
* `POST /api/indicators/{id}/run` takes a `count` of up to 100,000 (it was 20,000). An indicator that is too slow
  says over how many bars it timed out; the guide explains what to do about a loop over the bars (it takes seconds
  over 20,000 bars where it took no time over 500).

## 0.2.2 — a window that cannot outlive the program, and an update nobody can break

* **Ending CheapTrader in Task Manager no longer leaves its window behind.** *End task* on CheapTrader ended the program
  but not its window, which went on showing the last chart with nothing behind it; reloading it gave *127.0.0.1
  refused the connection*. The windows are now tied to the program (a Windows job object): when the program ends,
  however it ends, the system ends them with it. To make that hold for every window, the running program opens
  them itself, also the second one when CheapTrader is opened again while it runs. Ending only the window (Task
  Manager, or *Task beenden* in the taskbar menu) was already fine: the program follows a few seconds later, and
  opening it again right away works.
* **Opening CheapTrader by hand while an update installs no longer breaks the update.** The installer cannot replace a
  program that is running. A start by hand during the few seconds it takes made it give up (exit code 5): the old
  version came back and nothing was updated. A start now waits until the installer is done, and when the program is
  open again there is one window, not two or three. The script that installs an update comes from the version that is
  being replaced, so this starts to help with the update after the one that installs 0.2.2.
* The window no longer offers to translate the page (Edge asked on a PC whose language is not English).
* After a window was ended by force, Edge no longer asks in the window whether to restore pages.

## 0.2.1 — opening the program again right after closing it

* **No more "this page is not reachable".** Closing CheapTrader and opening it again within a few seconds could leave
  a window that said *127.0.0.1 refused the connection* (or, at other moments, open nothing at all for minutes).
  The program ends a few seconds after its window is closed; the second start found it still running, opened a window
  on it, and the program then ended under that window. Now the second start asks the running copy to stay for the
  window, and a copy that is already ending is waited for: the second start then begins the program afresh.
* A start that waits for a copy that is ending no longer keeps the program from opening later (it held a lock that
  only the other copy should hold).
* The program ends within a few seconds of deciding to, even when a request is still being answered (a big history
  read for a window that is gone no longer keeps it running).
* **Quit** in the MetaTrader menu closes the window with the program, instead of leaving a window whose page nothing
  serves. If the program's server ever stops by itself, the window is closed and a message says so (the details are
  in `data\logs`).
* If an open CheapTrader does not answer, a second start says so after three minutes instead of doing nothing.

## 0.2.0 — your account's results, in the replay's report

* **How the live account has done.** The bar at the bottom of the live chart shows what the replay's bar shows:
  return, trades (and how many won and lost), win rate, maximum drawdown and profit factor, worked out from your
  broker's own history. The server's name at its left opens the full report in a drawer above the bar:
  * **Overview**: the replay's ten figures beside the account's curve.
  * **Trades**: every closed trade with its prices, how long it was held, what it cost (commission, swap and
    fees), its P&L after those costs, a running total and how it ended (stop loss, take profit, stop out, closed
    by hand).
  * **Statistics**: every figure MetaTrader's own report has (expected payoff, recovery factor, Sharpe ratio,
    absolute drawdown, long and short trades, streaks, volume, time held), what the trades cost, the money that
    moved, and what each instrument made.
  * **Account**: what the broker says about the account: demo or real, hedging or netting, leverage, credit,
    margin level, the margin call and stop out levels, how many deals the history holds.
  * A choice of period: all time, this year, this month, this week, today.
* It is the replay's report, one component for both: the replay's report gains the **Statistics** tab and shows
  each trade's prices with the right number of decimals for its own symbol.
* Deposits and withdrawals are left out of the curve, the drawdowns and the percentages, so putting money in is not
  a gain. The report only reads: nothing is sent to the broker. MetaTrader gives the history that its History tab
  holds; choose *All history* there to load the rest.
* New: `GET /api/account/report`; `GET /api/account` carries more of what the broker says about the account.

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
