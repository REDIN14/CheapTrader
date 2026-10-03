# Getting Started with CheapTrader

CheapTrader is a free, TradingView-style trading platform for **MetaTrader 5**: live charts, drawing tools
that can place trades, indicators you write in Python, and bar replay with a paper account. This page is
what you need to know to start. The welcome tour (the **?** button at the right edge of the app, then
*Welcome tour*) shows the same in a few steps.

> Trading leveraged products carries a high risk of losing money. CheapTrader is provided "as is", without
> warranty, and is not financial advice. **Start on a demo account.** Sending orders from the app is
> switched off until you switch it on yourself (§5).

---

## 1. What you need

| You need | For |
| --- | --- |
| Windows 10 or 11 (64-bit) | the program |
| **MetaTrader 5**, installed from your broker or from metatrader5.com, with a trading account (a free demo account is perfect) | real prices, your account and positions, and trading |

Nothing else: no Python, no Node, no Expert Advisor, no DLL. Without MetaTrader CheapTrader still runs, on
made-up (synthetic) prices, so you can look around and try the tools. The bar at the bottom says
**SYNTHETIC DATA** while that is the case.

---

## 2. Start it

Run `CheapTrader.exe` (or the shortcut the installer made). A window opens with the chart; closing that
window stops the program. The first time, the welcome tour opens by itself.

* Windows may show *"Windows protected your PC"* (SmartScreen) for a program it has not seen before. Click
  **More info**, then **Run anyway**. Programs from small projects are often not signed; you can compare the
  file's SHA-256 checksum with the one on the download page.
* Your drawings, saved settings and the history of bars live in a `data` folder next to `CheapTrader.exe`
  (or, if that folder cannot be written to, in `%LOCALAPPDATA%\CheapTrader\data`). Uninstalling keeps it.
* There are no accounts and no tracking. CheapTrader talks to MetaTrader on your own PC, and to GitHub only
  to ask whether a newer version exists (see "Updating" below). That check can be switched off in the About window.

### Updating

When a newer release is on GitHub, an **Update** button appears at the top of the window. Click it to read what
is new. **Install and restart** downloads the installer, checks it against the published checksum, closes
CheapTrader, installs and opens it again. Your data folder is not touched. A portable copy (the zip) cannot
install itself: the button then opens the release page.

---

## 3. Connect MetaTrader 5

You only have to do three things:

1. **Install MetaTrader 5** (from your broker; each broker ships its own copy).
2. **Log in** to your trading account inside MetaTrader: *File, Login to Trade Account*.
3. **Leave MetaTrader open.** A minimised window is fine.

CheapTrader then finds the terminal, the account and the symbols by itself. There is no password, login
number or path to type in. If MetaTrader is installed but closed when CheapTrader starts, CheapTrader opens
it (MetaTrader logs in with the account it remembers).

The **MetaTrader 5** step of the welcome tour shows what CheapTrader sees right now:

| Check | Means | If it is not ticked |
| --- | --- | --- |
| Installed | a MetaTrader 5 terminal was found on this PC | install it from your broker's website |
| Open | the terminal is running | start it from the Start menu |
| An account is logged in | the terminal is connected to a trading account | *File, Login to Trade Account* |
| Connected | CheapTrader uses the terminal's prices, bars and account | it connects by itself within seconds; *Connect now* does it right away |
| Takes orders | MetaTrader will accept the app's orders | click the **Algo Trading** button in MetaTrader's toolbar so that it turns green |

If you start CheapTrader **before** MetaTrader, it begins on made-up prices and switches to the real market
as soon as a terminal is open and logged in: the chip at the bottom changes to **METATRADER FOUND · CONNECT**
(and the tour connects by itself). No restart is needed.

Several brokers installed? CheapTrader takes the one that is running, else the one you used last. The
**MetaTrader** menu in the bottom bar lists them and lets you choose.

---

## 4. Find your way around

| What | Where |
| --- | --- |
| Pick a symbol | click the symbol name at the top left; the list icon at the right edge is the watchlist |
| Change the interval | `1m` ... `D` in the top bar |
| Zoom and move | wheel to zoom, drag to pan, drag an axis to stretch it, `F` fits the chart |
| Right-click the chart | copy a price, place an order at that price, set a stop loss or take profit there |
| Drawing tools | the bar at the left of the chart: see the [drawing guide](DRAWINGS.md) |
| Indicators | **Indicators** in the top bar, and your own in Python: see the [indicator guide](INDICATORS.md) |
| Trade panel | **Trade** in the top bar (Market and Limit orders, stop loss, take profit) |
| Your account's results | the server's name at the left of the bar at the bottom (§6) |
| Bar Replay | **Replay** in the top bar (§7) |
| Help | the **?** button at the right edge: shortcuts, this tour, documentation, About |

---

## 5. Trading, and why orders start switched off

Orders can be placed from the **Trade** panel, the **Sell / Buy** buttons on the chart, a right-click on the
chart, and from long / short boxes. A fresh CheapTrader refuses all of them: nothing can reach your broker by
accident while you are still finding your way around.

To switch orders on, open the **MetaTrader** menu in the bottom bar, turn on **Send orders to the broker**
and confirm. The choice is remembered. Do this on a **demo account** first.

Two more things must be right in MetaTrader itself: the **Algo Trading** button has to be green, and the
account has to be allowed to trade (an "investor" password only lets you look). The MetaTrader menu tells you
when something stops the terminal from taking orders.

---

## 6. How your account is doing

The bar at the bottom of the chart shows your **Balance**, **Equity** and **Open P&L**, and how the account has
done so far: **Return**, **Trades**, **Win rate**, **Max drawdown** and **Profit factor**. They are worked out
from your broker's own history, the closed trades of the whole account.

Click the server's name at the left of the bar for the full report: the account's curve, every closed trade
(with what it cost in commission and swap), every statistic MetaTrader's own report has, what each instrument
made, and what the broker says about the account. The choice at the top cuts it to this year, month, week or
today. Deposits and withdrawals are left out of the curve and the percentages, so putting money in is not a
gain. If trades are missing, open the **History** tab in MetaTrader and choose **All history**, then press the
circular-arrow button at the right of the report's top bar to read it again.

---

## 7. Practise first: Replay

**Replay** runs history bar by bar with a paper account. Click *Replay* in the top bar, click the candle to
start from, then play, pause or step (`Space`, `Right arrow`). Buy and sell with stop loss and take profit;
the report shows the equity curve and statistics. Nothing reaches your broker.

The paper account is a **profile**: it has a starting balance you choose (10,000 unless you say otherwise) and
it keeps its balance and every trade for good. Nothing is reset when a replay ends or when you close the
program. The menu beside the *Replay* tag (in the side panel, and at the end of the start bar) lets you make
more profiles, for instance one per strategy, switch between them, rename them, start one over with a new
balance, and delete the ones you no longer need. Positions still open when a replay ends are closed at the last
price, so the result is not lost.

---

## 8. When something does not work

| Problem | Cause and cure |
| --- | --- |
| The bar says SYNTHETIC DATA | no terminal is connected. Open MetaTrader and log in; this page connects by itself. Or open the welcome tour, step *MetaTrader 5* |
| "MetaTrader 5 is open, but no account is logged in" | in MetaTrader choose *File, Login to Trade Account* |
| Buy / Sell say "Live orders are disabled" | switch orders on in the MetaTrader menu (§5) |
| MetaTrader refuses orders | click **Algo Trading** in its toolbar so that it is green; check the account may trade |
| It cannot find MetaTrader though it is installed | start MetaTrader once by hand and log in; then reopen the tour. A portable install must be running to be found |
| The prices are late | the MetaTrader menu or the dot next to the chart title says whether MetaTrader is busy |
| A drawing cannot be moved or deleted | it is locked: press the padlock in its bar |
| The window says "this page is not reachable" (connection refused) | CheapTrader is not running: its window can only show the program while the program is open. Close that window and open CheapTrader from the Start menu. (Closing the program and opening it again at once is fine: the new start waits for the old one to end.) |
| Something else | the program writes a log to `data\logs` next to it. Report problems on the project page (About, *Report a problem*) and attach the last lines |
