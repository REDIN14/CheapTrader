# Changelog

All notable changes to CheapTrader. The version is in `backend/app/__init__.py`.

## 0.1.1 — support links

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
