# Drawing on the Chart — Complete Reference

Shapes on the chart come from three places, and they all end up on the same chart:

| From | How | Who can change it |
| --- | --- | --- |
| **You, by hand** | the floating bar of drawing tools (§1) | you |
| **A script** | the REST API, `POST /api/drawings` (§4) | you, and the script |
| **A Python indicator** | return `"drawings"` from `compute` (§3) | the indicator only |

Drawings are anchored to the **market**, not to the screen: each point is a *(time, price)* pair, so a
drawing stays on the same candles when you pan, zoom, change the interval or resize the window.
Your own drawings and those added by scripts are saved on the server, per symbol, and come back after a
restart (§6). See also the [indicator guide](INDICATORS.md).

---

## 1. The drawing tools

### 1a. The bar of tools

A small bar floats over the left side of the chart. Drag it by the dotted **grip** on top to put it
anywhere on the chart; double-click the grip to put it back. Where you leave it is remembered.

| Button | What it does |
| --- | --- |
| Trend line | A line through two points |
| `S` Short position | A box for a trade that sells: stop above, target below |
| `L` Long position | A box for a trade that buys: stop below, target above |
| Rectangle | A box between two corners, **extended to the right** |
| Parallel channel | Two parallel lines and the band between them |
| Eye | Hide / show all your drawings (the choice is remembered) |
| Bin | Opens a small menu to remove drawings: those of this symbol or of every symbol, and the locked ones on their own (§1f) |
| Book | Opens this documentation |

> A drawing is a picture, with one exception: a long or short position box can place its trade. It shows
> an idea with its risk-to-reward ratio, and **only when you choose "Buy now", "Sell now" or a limit
> order from the box** (its bar, or a right-click on it) is an order sent (§1e). Nothing is sent by
> drawing, moving or selecting it.

### 1b. Drawing each kind

Click a tool; a line at the bottom of the chart says what to click next. A tool stays armed until its
drawing is finished, or until you press **Esc**.

| Tool | Clicks |
| --- | --- |
| Trend line | the start, then the end |
| Rectangle | one corner, then the opposite corner |
| Parallel channel | the start of the base line, its end, then a point on the second line (this sets the width) |
| Long / Short position | one click, the entry. The box appears with a target at twice the distance of the stop, based on the recent average range. Drag the handles to set the real levels |

Esc steps back one stage: it drops a half-placed point, then disarms the tool, then deselects.

The rectangle **extends to the right** by default, to the edge of the chart and on into the future, which
is how a range or a zone is usually drawn. Its right side stays where you drew it, as a dotted line.
Turn the extension off for a drawing in the bar that appears when it is selected (§1c).

### 1c. Selecting, moving, styling, deleting

* Click a line, or inside a rectangle or position box, to select it. Round **handles** appear.
* Drag a handle to change that point; drag the drawing itself to move all of it. A rectangle has a
  handle on every corner and side; a position box has handles for its width, its target and its stop.
* Drag on empty chart to pan; the wheel zooms wherever the pointer is, also over a drawing. A drag that
  starts on a drawing moves that drawing instead, so grab the chart beside it to pan.
* The bar above a selected drawing has a **padlock** (§1d), sets its **colour**, its **thickness**,
  whether it **extends to the right** (trend line, rectangle, channel) and deletes it.
* **Right-click** a drawing for its menu: lock or unlock it, delete it, and for a position box also
  trade it and size it (§1e).
* **Delete** removes the selected drawing. Click on empty chart to deselect.

Shapes that an indicator draws are shown in the same way, but they are not yours to change: they belong
to the indicator and follow it (§3).

### 1d. Locking a drawing

The padlock in the bar over a selected drawing (and **Lock** in its right-click menu) locks it. A locked
drawing

* **cannot be moved**: it has no handles, and dragging it does nothing;
* **cannot be removed**: **Delete**, the bar's bin and the menu's *Delete* refuse and say why, the bin
  menu of §1f leaves it alone, and so does a script (`423 Locked`, §4);
* **can still be restyled**: its colour, thickness and, for a position box, its size and its orders;
* wears a small padlock on the chart.

Press the padlock again to unlock it. The lock is saved with the drawing, so it survives a restart.

### 1e. Trading from a long or short box

Right-click a position box, or select it and use the bar over it, to trade the idea it shows. The box
says what the order is: its **entry** is the line between the green and the red part, its **target** and
**stop** are the far edges.

| Choice | What it does |
| --- | --- |
| **Buy / Sell N lots now** | An order at the market price **at once**, with the box's stop and target on it. The price does **not** have to have reached the entry line. Once the trade is open, the **middle line of the box moves to the price it was filled at** (and the start of the box to the candle it opened in, as long as the box runs on past it): the box then shows the real trade. The stop and the target stay where they are, and the size is worked out again from the new entry. A locked box stays as it was drawn |
| **Buy / Sell limit (or stop) at the entry** | Leaves an order waiting at the box's entry price, with the box's stop and target. It is a *limit* order when the entry is on the better side of the market (a buy below it, a sell above it) and a *stop* order on the other side. Live trading only: a replay fills everything at the bar close |
| **Set stop and target of the open buy / sell** | Appears when you hold an open position on this symbol in the same direction: puts the box's stop and target on it |
| **Risk 0.5 % / 1 % / 2 % / 5 %**, *Another share, an amount, or lots…* | How big the trade is (below) |

Nothing asks again: the menu entry says what it will send (the lots, the stop and the target), and a
message afterwards says what happened. An entry that cannot be sent is greyed out with the reason beside
it, for instance `The stop loss of a buy has to be below the current sell price 1.12885; 1.13166 is not.`

**Position sizing.** The bar over a box has a *Risk* field with a unit: a share of the account balance
(`%`, the default is 1 %), an amount of money (the account currency), or plain `lots`. The number of lots
is worked out from the distance between the entry and the stop and what one price step of a lot is worth
for this instrument (the broker's tick value, read again every minute), rounded **down** to the volume
step. The box prints it under its title: `0.81 lots · risk 98.94 USD (0.99%)`. When the broker's smallest
or largest volume changes the figure, the bar marks it and says so. A replay sizes with its paper account.

Move the box's stop and the size follows at once when the risk is given in `%` or money (the risk stays
what you asked for); given in `lots`, the lots stay and the risk changes.

### 1f. Removing drawings

The bin in the bar of tools opens a menu. Every line says how many drawings it would remove, and asks a
second time before it does:

| Line | Removes |
| --- | --- |
| On *this symbol* | the drawings of the symbol on the chart that are not locked |
| On all symbols | the same, on every symbol |
| Locked ones on *this symbol* | only the locked drawings of this symbol |
| Locked ones on all symbols | only the locked drawings of every symbol |

A locked drawing stays when the first two are used; the message says how many were kept. A single locked
drawing is removed by unlocking it first.

### 1g. What is remembered

| What | Where |
| --- | --- |
| Your drawings, with their places, colours, thickness, locks and sizes | on the server, per symbol (survives a restart) |
| Whether drawings are hidden | in the browser |
| Where the bar of tools was left | in the browser |

---

## 2. What a drawing is

A drawing is a small JSON object:

```json
{
  "id": "b5a4e3cbdb31",
  "type": "rectangle",
  "points": [
    { "time": 1790427600, "price": 1.1300 },
    { "time": 1790600400, "price": 1.1200 }
  ],
  "style": { "color": "#2962ff", "fill_opacity": 0.15, "extend_right": true }
}
```

| Field | Meaning |
| --- | --- |
| `id` | Optional when you add one (the server makes it); a given id must be new |
| `type` | One of the kinds in §2a |
| `points` | A list of `{ "time", "price" }` (§2a says how many each kind takes) |
| `style` | Everything optional; each kind has sensible defaults (§2b) |
| `locked` | `true` makes it unmovable and unremovable until it is unlocked (§1d). Default `false` |
| `created` | When it was made (epoch seconds); set by the server |

### 2a. The kinds and their points

| `type` | Points | What the points are |
| --- | --- | --- |
| `trendline` | 2 | the two ends |
| `rectangle` | 2 | two opposite corners |
| `channel` | 3 | the two ends of the base line, and a point on the parallel line |
| `long` | 3 | the entry; the target (its end time and its take-profit price); the stop (the same end time, the stop price) |
| `short` | 3 | the same, for a sell: the target below the entry, the stop above |
| `hline` | 1 | only the `price` counts: a line across the whole chart |
| `vline` | 1 | only the `time` counts: a line from top to bottom |
| `polyline` | 2 to 500 | the corners of a line that bends |
| `text` | 1 | where the text sits; the words are `style.text` |

A wrong number of points is rejected, and says so: `a rectangle takes 2 point(s), not 1`.

### 2b. Style

Every key is optional.

| Key | Values | Applies to |
| --- | --- | --- |
| `color` | any CSS colour, e.g. `"#ff9800"` | all but `long` and `short` (those are green and red) |
| `width` | `1` to `8` (pixels) | lines and outlines |
| `dash` | `"solid"`, `"dashed"`, `"dotted"` | lines and outlines |
| `fill` | a colour; the default is `color` | `rectangle`, `channel` |
| `fill_opacity` | `0` to `1` | `rectangle`, `channel` |
| `extend_right` | `true` / `false` | `trendline`, `channel`, `rectangle` (**default `true`**) |
| `extend_left` | `true` / `false` | `trendline`, `channel` |
| `text` | up to 200 characters | the words of a `text`; a label on an `hline` or `vline` |
| `font_size` | `6` to `72` | `text`, and labels |
| `risk_mode` | `"percent"`, `"amount"` or `"lots"`: which of the next three counts. Default `"percent"` | `long`, `short` (their size, §1e) |
| `risk_percent` | above `0` up to `100`: a share of the account balance. Default `1` | `long`, `short` |
| `risk_amount` | above `0`: money, in the account currency | `long`, `short` |
| `lots` | above `0`: a plain volume | `long`, `short` |

### 2c. Times and prices

* A **time** is a moment: epoch seconds (a number, also as a string), an ISO date such as
  `"2026-10-01T09:30:00"` (no zone means UTC), or, in Python, a `datetime` or a pandas `Timestamp`.
* A **price** is a number on the symbol's price scale.
* The candles' times are the broker's server clock written as epoch seconds (the clock under the chart
  shows its offset from UTC). **Times copied from `df["time"]` always fit.** A time worked out from your
  own PC's clock can sit a few hours away from where you meant.
* The chart has no room for the hours the market is closed. A time in a weekend gap is placed between
  the last candle before it and the first after it, in proportion. A time past the newest candle is
  placed as if the candles went on at the interval's pace, so a drawing can reach into the future.

---

## 3. Drawing from a Python indicator

An indicator may return shapes along with (or instead of) its lines. Put them under a `"drawings"` key
of the dict that `compute` returns. Both of the return formats of the [indicator guide](INDICATORS.md)
work:

```python
from ct_draw import hline, rectangle


def compute(df, params):
    n = int(params.get("bars", 50))
    recent = df.tail(n)
    hi, lo = float(recent["high"].max()), float(recent["low"].min())
    t0, t1 = int(recent["time"].iloc[0]), int(recent["time"].iloc[-1])
    return {
        "drawings": [
            rectangle((t0, hi), (t1, lo), extend_right=True, color="#2962ff", fill_opacity=0.12),
            hline((hi + lo) / 2, color="#787b86", dash="dotted", width=1),
        ]
    }
```

This is the built-in **Range box (drawings)** indicator. Turn it on in the Indicators panel to see it.

Plots and drawings go together:

```python
def compute(df, params):
    sma = df["close"].rolling(20).mean()
    return {
        "plots": [{"name": "SMA", "values": sma, "color": "#2962ff"}],
        "drawings": [...],
    }
```

or, with the simple form, `{"SMA": sma, "drawings": [...]}`. An indicator that only draws returns just
`{"drawings": [...]}`.

### 3a. The `ct_draw` helpers

`from ct_draw import ...` is always available inside an indicator. Each helper builds one drawing; extra
keyword arguments are the style keys of §2b. A point is `(time, price)`.

| Helper | Builds |
| --- | --- |
| `trendline(p1, p2, **style)` | a trend line |
| `rectangle(p1, p2, **style)` | a rectangle between two corners |
| `channel(p1, p2, p3, **style)` | a parallel channel |
| `polyline(points, **style)` | a line through a list of points |
| `text(point, "words", **style)` | a label at a point |
| `hline(price, **style)` | a horizontal line across the chart |
| `vline(time, **style)` | a vertical line |
| `long(entry, target, stop_price, **style)` | a long position box: `entry` and `target` are `(time, price)`, `stop_price` is a number |
| `short(entry, target, stop_price, **style)` | a short position box |

You can also write the dicts of §2 yourself: `{"type": "text", "points": [(t, p)], "style": {"text": "hi"}}`.
Points may be tuples, lists or `{"time", "price"}` dicts, and times may be numpy integers, `datetime`s or
pandas `Timestamp`s.

### 3b. How an indicator's drawings behave

* They are recomputed with the indicator whenever the chart loads another symbol or interval, and when
  you edit the indicator.
* They are **not** saved with your drawings and cannot be selected or moved: turn the indicator off and
  they go.
* In a replay, a shape is shown once the replay has reached **all** of its points (a horizontal line,
  which has no time, is always shown). An indicator is computed from live data, so this keeps it from
  giving the future away.
* The indicator runs over the latest bars the chart asks for (500). Use the times in `df`.
* A snapshot (`POST /api/snapshot`) draws the indicator's shapes too, so an AI agent can look at what
  it made. The symbol's saved drawings are in the picture as well, unless the request says
  `"include_drawings": false`.

### 3c. Errors and limits

A mistake in a drawing is reported with the indicator's name, like any other indicator error, and
nothing is drawn:

| Message | Cause |
| --- | --- |
| `drawing #1 (rectangle): a rectangle takes 2 point(s), not 1` | wrong number of points |
| `drawing #2: unknown type 'box'; use one of [...]` | misspelt `type` |
| `drawing #1: a price is not a number` | `NaN` or infinity as a price. Check with `pd.notna(...)` |
| `'drawings' must be a list of drawings` | `drawings` is not a list |
| `too many drawings (900): an indicator may draw at most 500` | the cap, because the chart redraws every shape as you pan |

`NaN` prices come from warm-up periods (§2 of the indicator guide): leave those out, as you do for plots.

---

## 4. Drawing from a script (REST)

Any program on this PC can draw on the chart, and a chart that is open shows the new shape at once.
The Windows program listens on `http://127.0.0.1:8765`; started from the source it is
`http://127.0.0.1:8000`.

| Action | Request |
| --- | --- |
| List a symbol's drawings | `GET /api/drawings?symbol=EURUSD` |
| Add one | `POST /api/drawings?symbol=EURUSD` with the JSON of §2 (`symbol` may be in the body instead) |
| Replace one | `PUT /api/drawings/{id}?symbol=EURUSD` |
| Change its points, style and / or lock | `PATCH /api/drawings/{id}?symbol=EURUSD` with `{ "points": [...], "style": {...}, "locked": true }`; the style is merged into the old one |
| Remove one | `DELETE /api/drawings/{id}?symbol=EURUSD` |
| Remove a symbol's drawings | `DELETE /api/drawings?symbol=EURUSD` |
| Remove everyone's | `DELETE /api/drawings?all_symbols=true` |
| Count them | `GET /api/drawings/summary` → `{ "EURUSD": { "total": 3, "locked": 1 } }` |

The two bulk removals leave **locked** drawings alone. Add `locked=include` to take them as well, or
`locked=only` to take just the locked ones. They answer `{ "ok": true, "removed": 2, "kept_locked": 1 }`
(with the count per symbol, `symbols`, for `all_symbols`).

`POST` answers `201` with the drawing as saved (with its `id`). Other answers: `404` no such drawing,
`409` that `id` already exists, `422` the drawing is not valid (the message says why), `422` when
the symbol already holds the most it can (2000), and **`423` when the drawing is locked** and the request
would move, replace or remove it. A locked drawing still takes a `PATCH` that only changes `style` or
`locked`, so `{ "locked": false }` unlocks it.

```python
import requests

API = "http://127.0.0.1:8765"
SYMBOL = "EURUSD"

bars = requests.get(f"{API}/api/bars", params={"symbol": SYMBOL, "timeframe": "H1", "count": 100}).json()
hi = max(b["high"] for b in bars)
lo = min(b["low"] for b in bars)

zone = {
    "type": "rectangle",
    "points": [
        {"time": bars[0]["time"], "price": hi},
        {"time": bars[-1]["time"], "price": lo},
    ],
    "style": {"color": "#ff9800", "fill_opacity": 0.1, "extend_right": True},
}
saved = requests.post(f"{API}/api/drawings", params={"symbol": SYMBOL}, json=zone)
saved.raise_for_status()
print("drawn", saved.json()["id"])

# later: widen the zone, then take it away again
requests.patch(f"{API}/api/drawings/{saved.json()['id']}", params={"symbol": SYMBOL}, json={"style": {"color": "#e91e63"}})
requests.delete(f"{API}/api/drawings/{saved.json()['id']}", params={"symbol": SYMBOL})
```

A position box can carry its size and a lock too. This one risks half a percent of the balance, and cannot
be dragged or deleted by accident; right-click it to trade it (§1e):

```python
last = bars[-1]
entry, risk = last["close"], hi - lo
idea = {
    "type": "long",
    "points": [
        {"time": last["time"], "price": entry},
        {"time": last["time"] + 24 * 3600, "price": entry + 2 * risk},
        {"time": last["time"] + 24 * 3600, "price": entry - risk},
    ],
    "style": {"risk_mode": "percent", "risk_percent": 0.5},
    "locked": True,
}
requests.post(f"{API}/api/drawings", params={"symbol": SYMBOL}, json=idea).raise_for_status()
```

Open pages learn about every change over the live connection (`{"type": "drawings", "symbol": "..."}`) and
read the list again, so a shape added by a script appears within a fraction of a second. (A replay has
no live connection: a page showing one looks again when you come back to its tab.)

---

## 5. Recipes

### Support and resistance of the last N bars

```python
from ct_draw import hline


def compute(df, params):
    recent = df.tail(int(params.get("bars", 100)))
    return {
        "drawings": [
            hline(float(recent["high"].max()), color="#f23645", text="resistance"),
            hline(float(recent["low"].min()), color="#089981", text="support"),
        ]
    }
```

### Yesterday's range, carried forward

```python
from ct_draw import rectangle


def compute(df, params):
    day = (df["time"] // 86400).astype(int)
    prev = df[day == day.iloc[-1] - 1]
    if prev.empty:
        return {"drawings": []}
    return {
        "drawings": [
            rectangle(
                (int(prev["time"].iloc[0]), float(prev["high"].max())),
                (int(prev["time"].iloc[-1]), float(prev["low"].min())),
                extend_right=True, color="#ff9800", fill_opacity=0.08,
            )
        ]
    }
```

### Label the swing high and low

```python
from ct_draw import text, trendline


def compute(df, params):
    recent = df.tail(int(params.get("bars", 120))).reset_index(drop=True)
    hi_i, lo_i = int(recent["high"].idxmax()), int(recent["low"].idxmin())
    hi = (int(recent["time"][hi_i]), float(recent["high"][hi_i]))
    lo = (int(recent["time"][lo_i]), float(recent["low"][lo_i]))
    return {
        "drawings": [
            trendline(lo, hi, color="#2962ff", extend_right=True),
            text(hi, "swing high", color="#f23645"),
            text(lo, "swing low", color="#089981"),
        ]
    }
```

### A long idea at the last close, risking one average range

```python
from ct_draw import long


def compute(df, params):
    last = df.iloc[-1]
    entry = float(last["close"])
    risk = float((df["high"] - df["low"]).tail(14).mean())
    start = int(last["time"])
    end = start + 24 * 3600
    return {"drawings": [long((start, entry), (end, entry + 2 * risk), entry - risk)]}
```

---

## 6. Where drawings are stored

One file per symbol, `drawings/<symbol>.json`, in the data folder: next to `CheapTrader.exe` in the
`data` folder for the Windows program, `backend/data` when run from the source. The file is rewritten
atomically on every change. Copy the folder to move your drawings to another PC; delete a file to clear
a symbol.

---

## 7. Troubleshooting

| Problem | Cause and cure |
| --- | --- |
| A shape from a script is not there | it is on another symbol: the `symbol` must be the name the chart uses (`EURUSD`). Or the drawings are hidden: press the eye |
| A shape sits hours away from where it should | its times came from a clock other than the candles'. Use `df["time"]` |
| An indicator's shapes are missing in a replay | the replay has not reached all of their points yet (§3b) |
| `422` on `POST` | the body is not valid; the message names the problem (points, type, style) |
| A drawing cannot be dragged | it comes from an indicator (§3b); drag its own copy, or change the indicator. Or it is locked: press the padlock in its bar (§1d) |
| A drawing will not delete | it is locked (§1d). Unlock it, or use *Locked ones* in the bin menu (§1f) |
| `423` from a script | the drawing is locked (§4); `PATCH` it with `{ "locked": false }` first |
| *Buy now* / *Sell now* is greyed out | the hover text says why: usually the box's stop or target is on the wrong side of the market, or the instrument's details have not arrived (§1e) |
| A limit order from a box is refused | the entry is too close to the market for the broker (its minimum distance), or it is exactly at the market. Move the entry, or buy / sell now |
| The documentation does not open | the backend serves it from the `docs` folder next to the program; check that the folder is there |
