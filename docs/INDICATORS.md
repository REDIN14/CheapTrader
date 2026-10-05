# Writing Indicators — Complete Reference

This is the authoritative guide for authoring CheapTrader indicators. It is
written for both humans and AI agents (via the MCP server). **Anything you can
compute in Python over OHLCV data, you can render as an indicator.**

An indicator draws **lines** (§3) and, if it wants, **shapes** on the chart: boxes, trend lines,
labels, position boxes. Shapes have their own guide: [Drawing on the Chart](DRAWINGS.md).
You can read both guides in the app: the book button in the Indicators panel opens this one, and the
book in the drawing tools opens the drawing guide.

---

## 1. The contract

An indicator is a single Python file that defines one function:

```python
def compute(df, params):
    ...
    return <result>
```

- `df` — a `pandas.DataFrame` of bars (see §2).
- `params` — a `dict` of your indicator's parameters (see §6).
- The return value is normalised into chart plots (see §3).

That is the entire required surface. No imports are required, no base class, no
registration.

---

## 2. The `df` DataFrame

One row per bar, oldest first, indexed `0..n-1`.

| Column | Type | Meaning |
| --- | --- | --- |
| `time` | int | UTC epoch **seconds** (bar open time) |
| `open` | float | Open price |
| `high` | float | High price |
| `low` | float | Low price |
| `close` | float | Close price |
| `tick_volume` | int | Tick volume |
| `spread` | int | Spread in points |
| `real_volume` | int | Real volume (0 for FX) |

`df` is a normal pandas DataFrame — use `.rolling()`, `.ewm()`, `.diff()`,
`.shift()`, `.clip()`, `.cumsum()`, boolean masks, `np.where`, etc.

> **Alignment rule:** every returned series must be the **same length as `df`**.
> Use `NaN` for warm-up periods (e.g. the first `period-1` values of a moving
> average). `NaN` values are dropped from the rendered line automatically.

### How many bars `df` holds

`df` holds **as many bars as the chart shows**: its history depth, which is 20,000 bars unless it was
changed (the bar count at the bottom left of the chart: 5,000 up to 100,000), so that the lines reach
back as far as the candles do. During a replay it holds every bar back to the replay's first candle.
(Before version 0.2.3 it was always the newest 500, so a line covered the last few percent of the
chart and a replay that began further back had none.)

An indicator that needs **more** than that says so with one line at the top level of its file:

```python
NEEDS_BARS = 60_000      # the most bars it will ever want


def compute(df, params):
    return {"SMA 50000": df["close"].rolling(50_000).mean()}
```

The indicator is then run over that many bars. The lines that come back are only the ones over the bars
the chart shows (the older bars are there to warm the indicator up), so `len(df)` is bigger than the
chart but every series you return must still be as long as `df`. Good to know:

- It is read from the code **without running it**, so it must be a whole number, or a sum or
  product of whole numbers (`NEEDS_BARS = 50 * 1_000`). Something worked out from `params` is not
  read: write the most the indicator may need.
- It is a minimum, not a request to shrink: a chart deeper than that still gives the indicator all of
  its bars.
- The most any indicator is run over is 200,000 bars. Where the broker has fewer, it gets what there is
  (the first lines of an average that needs more than that stay empty, as for any warm-up).
- Snapshots (`POST /api/snapshot`) warm an indicator up the same way: it gets the bars it needs from
  before the range that is drawn.

---

## 3. Return formats

You may return any of the following. All are normalised identically.

### 3a. Simple dict — `{name: values}`

```python
def compute(df, params):
    return {"SMA": df["close"].rolling(20).mean()}
```

Each key becomes a line plot. `values` may be a pandas Series, a numpy array, or
a plain list.

### 3b. Rich dict — `{"plots": [...]}` (recommended)

Full control over name, colour, and plot type:

```python
def compute(df, params):
    macd = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    return {
        "plots": [
            {"name": "Histogram", "values": macd - signal, "type": "histogram", "color": "#787b86"},
            {"name": "MACD",      "values": macd,          "type": "line",      "color": "#2962ff"},
            {"name": "Signal",    "values": signal,        "type": "line",      "color": "#ff9800"},
        ]
    }
```

Plot object fields:

| Field | Required | Values | Default |
| --- | --- | --- | --- |
| `name` | yes | string | — |
| `values` | yes | Series / array / list | — |
| `type` | no | `"line"` \| `"histogram"` | `"line"` |
| `color` | no | hex string, e.g. `"#2962ff"` | auto-assigned |

### 3c. Bare list or Series

```python
def compute(df, params):
    return df["close"] - df["open"]   # single unnamed line
```

A list, a tuple, a pandas Series or a numpy array becomes one line named `plot`.

### 3d. Shapes — a `"drawings"` key

Any dict you return (3a or 3b) may also carry a `"drawings"` list. The helpers of the `ct_draw`
module build the shapes; a point is `(time, price)` and times come from `df["time"]`:

```python
from ct_draw import hline, rectangle


def compute(df, params):
    recent = df.tail(50)
    hi, lo = float(recent["high"].max()), float(recent["low"].min())
    t0, t1 = int(recent["time"].iloc[0]), int(recent["time"].iloc[-1])
    return {
        "plots": [{"name": "SMA", "values": df["close"].rolling(20).mean()}],
        "drawings": [
            rectangle((t0, hi), (t1, lo), extend_right=True),
            hline((hi + lo) / 2, dash="dotted"),
        ],
    }
```

An indicator that only draws returns `{"drawings": [...]}`. The kinds, their points and styles, the
helpers, the errors and the limits are in the [drawing guide](DRAWINGS.md).

---

## 4. Overlay vs. pane

Set when the indicator is **created**, not in the code:

- **Overlay** (`overlay: true`) — drawn on the price chart. Use for moving
  averages, Bollinger Bands, VWAP, envelopes, etc.
- **Pane** (`overlay: false`) — drawn in a sub-pane of its own below the
  chart with an independent scale. Use for oscillators: RSI, MACD, Stochastic,
  ATR, volume studies.

> Pane indicators **never** distort the price scale, and **every pane indicator gets
> a pane of its own**, in the order they were added, with its name at the top-left of
> its pane. Two oscillators therefore never share a scale (RSI's 0–100 and MACD's
> 0.001 would flatten one of them). The `pane` number given when creating an
> indicator does not choose a shared pane; all of an indicator's plots go into its
> one pane. The panes can be resized by dragging the dividers between them (the sizes are
> remembered).

An indicator is either an overlay or a pane indicator: its lines cannot be split
between the two. To have both, make two indicators (a moving average as an overlay
and RSI as a pane). **Shapes** (§3d) are always drawn on the price chart, whichever
kind the indicator is.

---

## 5. Available libraries

These are importable inside `compute` (and at module top level):

- `numpy` (`import numpy as np`)
- `pandas` (`import pandas as pd`)
- `math`, `statistics`, `datetime`, `json`, `re`, `collections`, `itertools`,
  `functools`, `decimal`, `fractions`, `random`, `typing`, `dataclasses`, `enum`

`scipy` and `ta-lib` are **not** installed. Implement indicators with pandas/numpy
(see §9 for common recipes); `np.polyfit`, `np.convolve` and `DataFrame.rolling` cover most of
what `scipy` is usually wanted for.

`np` and `pd` are not predefined: import them at the top of the file.

### Blocked (for safety)

`os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `importlib`, `ctypes`,
`multiprocessing`, `threading`, `pickle`, `marshal`, `builtins`, `gc`,
`inspect`, `code`, `resource`, `signal`, `mmap`, `sqlite3`, `http`, `urllib`,
`requests`, `asyncio`, `concurrent`, `glob`, `tempfile`, `io`, `platform`,
`getpass`, `webbrowser`, `runpy`, `pkgutil`, `zipimport`.

Attempting to import a blocked module raises
`ImportError: Import of '<name>' is not allowed in the indicator sandbox`.

> The block applies **only to your indicator file**. Libraries such as pandas may
> still import what they need internally.

---

## 6. Parameters

Parameters are declared as a JSON object when creating the indicator and arrive
as `params`. Always provide defaults so the indicator runs without configuration:

```python
def compute(df, params):
    period = int(params.get("period", 14))
    mult = float(params.get("mult", 2.0))
    source = params.get("source", "close")   # "open" | "high" | "low" | "close"
    price = df[source]
    ...
```

Supported parameter value types: numbers, strings, booleans, and nested
lists/dicts (JSON).

---

## 7. Limits

| Limit | Default | Config |
| --- | --- | --- |
| Wall-clock timeout | 10 s | `CT_INDICATOR_TIMEOUT` |
| Memory cap | 2048 MB | `CT_INDICATOR_MEMORY_MB` |

Exceeding the timeout returns
`Indicator timed out after 10.0s over 20,000 bars`. Exceeding memory kills the process. Keep
computations vectorised — avoid Python loops over bars. An indicator is run over the whole chart now
(see §2), so a loop that took no time over 500 bars can take seconds over 20,000, and one that compares
every bar with every other (a loop inside a loop) will not finish: work on the whole series at once
(`.rolling()`, `.shift()`, `np.where`), or raise `CT_INDICATOR_TIMEOUT`. A vectorised indicator takes
about a second over 20,000 bars and two or three over 200,000.

---

## 8. Errors

Any exception inside `compute` is caught and returned as
`"<ExceptionType>: <message>"` — it never crashes the server. Common causes:

- Returning a series whose length ≠ `len(df)`.
- Referencing a column that does not exist.
- Importing a blocked module.
- Division by zero producing `inf` (use `.replace([np.inf, -np.inf], np.nan)`).

---

## 9. Recipes

### Simple Moving Average (overlay)

```python
def compute(df, params):
    period = int(params.get("period", 20))
    return {"SMA": df["close"].rolling(period).mean()}
```

### Exponential Moving Average (overlay)

```python
def compute(df, params):
    period = int(params.get("period", 21))
    return {"EMA": df["close"].ewm(span=period, adjust=False).mean()}
```

### Bollinger Bands (overlay, 3 lines)

```python
def compute(df, params):
    period = int(params.get("period", 20))
    mult = float(params.get("std", 2.0))
    mid = df["close"].rolling(period).mean()
    sd = df["close"].rolling(period).std()
    return {
        "plots": [
            {"name": "Upper",  "values": mid + mult * sd, "color": "#2962ff"},
            {"name": "Middle", "values": mid,             "color": "#ff9800"},
            {"name": "Lower",  "values": mid - mult * sd, "color": "#2962ff"},
        ]
    }
```

### RSI (pane)

```python
def compute(df, params):
    period = int(params.get("period", 14))
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return {"RSI": 100 - (100 / (1 + rs))}
```

### MACD (pane, histogram + 2 lines)

```python
def compute(df, params):
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return {
        "plots": [
            {"name": "Histogram", "values": macd - sig, "type": "histogram", "color": "#787b86"},
            {"name": "MACD",      "values": macd,       "type": "line",      "color": "#2962ff"},
            {"name": "Signal",    "values": sig,        "type": "line",      "color": "#ff9800"},
        ]
    }
```

### ATR (pane)

```python
import numpy as np


def compute(df, params):
    period = int(params.get("period", 14))
    prev_close = df["close"].shift(1)
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()),
    )
    return {"ATR": tr.rolling(period).mean()}
```

### Stochastic Oscillator (pane, %K + %D)

```python
def compute(df, params):
    k_period = int(params.get("k", 14))
    d_period = int(params.get("d", 3))
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min)
    d = k.rolling(d_period).mean()
    return {
        "plots": [
            {"name": "%K", "values": k, "color": "#2962ff"},
            {"name": "%D", "values": d, "color": "#ff9800"},
        ]
    }
```

### VWAP (overlay, session-anchored)

```python
import numpy as np


def compute(df, params):
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["tick_volume"].replace(0, np.nan)
    return {"VWAP": (typical * vol).cumsum() / vol.cumsum()}
```

### Volume (pane, histogram)

```python
def compute(df, params):
    return {
        "plots": [
            {"name": "Volume", "values": df["tick_volume"], "type": "histogram", "color": "#787b86"}
        ]
    }
```

### Linear-regression line (overlay, numpy)

```python
import numpy as np


def compute(df, params):
    period = int(params.get("period", 100))
    x = np.arange(period)
    closes = df["close"].to_numpy()
    fit = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        slope, intercept = np.polyfit(x, closes[i - period + 1 : i + 1], 1)
        fit[i] = slope * (period - 1) + intercept
    return {
        "plots": [
            {"name": "Regression", "values": fit, "color": "#2962ff"},
        ]
    }
```

### Z-Score (pane)

```python
def compute(df, params):
    period = int(params.get("period", 20))
    sma = df["close"].rolling(period).mean()
    zscore = (df["close"] - sma) / df["close"].rolling(period).std()
    return {
        "plots": [
            {"name": "Z-Score", "values": zscore, "type": "line", "color": "#e91e63"},
        ]
    }
```

### Support and resistance lines (shapes only)

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

More shape recipes are in the [drawing guide](DRAWINGS.md#5-recipes).

---

## 10. Using indicators via the MCP / REST

| Action | REST | MCP tool |
| --- | --- | --- |
| List indicators | `GET /api/indicators` | `list_indicators` |
| Read one | `GET /api/indicators/{id}` | `get_indicator` |
| Create | `POST /api/indicators` | `write_indicator` |
| Update | `PUT /api/indicators/{id}` | `write_indicator` |
| Delete | `DELETE /api/indicators/{id}` | `delete_indicator` |
| Run over bars | `POST /api/indicators/{id}/run?symbol=&timeframe=&count=` (`count`: the newest bars the lines are wanted over, 500 unless given, up to 100,000) | `run_indicator` |
| Snapshot with indicators | `POST /api/snapshot` | `get_snapshot` |

### Create payload

```json
{
  "id": "",
  "name": "My Momentum",
  "code": "def compute(df, params):\n    period = int(params.get('period', 10))\n    return {'Momentum': df['close'] - df['close'].shift(period)}\n",
  "overlay": false,
  "pane": 1,
  "params": { "period": 10 }
}
```

- Leave `id` empty on create; the server assigns `user.<hex>`.
- Built-in ids (`builtin.*`) cannot be modified or deleted.

### Run response

```json
{
  "id": "user.abc123",
  "name": "My Momentum",
  "overlay": false,
  "pane": 1,
  "plots": [
    { "name": "Momentum", "type": "line", "color": null,
      "data": [ { "time": 1790671597, "value": 0.0012 }, ... ] }
  ],
  "drawings": [],
  "error": null
}
```

The lines are for the newest `count` bars. An indicator with `NEEDS_BARS` (§2) is run over more
bars than that when it says so; the extra ones only warm it up and no point comes back for them.

`error` is `null` on success, otherwise a human-readable message. `drawings` lists the shapes
the indicator drew (empty if none); their format is in the [drawing guide](DRAWINGS.md#2-what-a-drawing-is).
Shapes you want to keep on the chart yourself, outside any indicator, are added with
`POST /api/drawings` (see [Drawing from a script](DRAWINGS.md#4-drawing-from-a-script-rest)).

---

## 11. AI workflow (visual self-correction)

1. `write_indicator` — create or update the indicator.
2. `run_indicator` — check `error` is `null` and inspect the returned series.
3. `get_snapshot` — render the chart **with** the indicator applied. The image
   contains only the chart, plus a header/footer binding it to the exact symbol,
   timeframe, and time window. Shapes the indicator draws (§3d) are in the picture;
   so are the symbol's saved drawings, unless the request says `"include_drawings": false`.
4. Visually audit the rendered line(s): wrong scale, flat line, misalignment,
   warm-up artefacts.
5. `write_indicator` again with corrections. Repeat until the visual output is
   correct.

### Checklist before returning an indicator

- [ ] `compute(df, params)` is defined.
- [ ] Every returned series has length `len(df)`.
- [ ] Warm-up values are `NaN`, not `0`.
- [ ] `inf`/`-inf` replaced with `NaN`.
- [ ] `overlay` is `true` for price-scale studies, `false` for oscillators.
- [ ] Parameters have sensible defaults.
- [ ] No blocked imports.
- [ ] Runs within the timeout over a whole chart (20,000 bars or more): vectorised, no per-bar Python loops where avoidable.
- [ ] If it needs more bars than a chart holds, `NEEDS_BARS = <whole number>` is at the top level of the file.
- [ ] Shapes (if any) use times taken from `df["time"]`, prices that are not `NaN`, and the right number of points for their kind.
- [ ] No more than 500 shapes.
