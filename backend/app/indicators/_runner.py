"""Sandboxed child process that executes a user indicator.

This module is launched as a subprocess by ``app.indicators.sandbox``. It:

1. imports everything it needs *before* locking down imports,
2. installs a guarded ``__import__`` that blocks dangerous modules,
3. loads the user's indicator module and calls ``compute(df, params)``,
4. normalises the result and prints a single JSON object to stdout.

The parent enforces the wall-clock timeout and (on Windows) a memory cap.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import sys

# Modules that must never be importable from user indicator code.
BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "importlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "pickle",
    "marshal",
    "builtins",
    "gc",
    "inspect",
    "code",
    "codeop",
    "pty",
    "fcntl",
    "resource",
    "signal",
    "mmap",
    "sqlite3",
    "http",
    "urllib",
    "requests",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncio",
    "concurrent",
    "glob",
    "tempfile",
    "fileinput",
    "io",
    "sysconfig",
    "platform",
    "getpass",
    "pwd",
    "grp",
    "crypt",
    "termios",
    "tty",
    "webbrowser",
    "antigravity",
    "this",
    "site",
    "runpy",
    "pkgutil",
    "zipimport",
    "webbrowser",
}

_real_import = builtins.__import__
_user_file: str | None = None


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """Block dangerous imports, but only when requested from user code.

    Libraries such as pandas/numpy lazily import ``os``/``io``/``threading``
    internally at runtime. Those imports originate from library modules, so we
    allow them and only enforce the blocklist for the user's indicator module.
    """
    caller_file = (globals or {}).get("__file__")
    if _user_file is not None and caller_file == _user_file:
        top = name.split(".")[0]
        if top in BLOCKED_MODULES:
            raise ImportError(f"Import of '{name}' is not allowed in the indicator sandbox")
    return _real_import(name, globals, locals, fromlist, level)


def _to_float_list(values) -> list[float | None]:
    """Convert a numpy array / pandas Series / list into JSON-safe floats."""
    out: list[float | None] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if f != f:  # NaN
            out.append(None)
        else:
            out.append(f)
    return out


def _normalise(result, times: list[int]) -> list[dict]:
    """Normalise the user's return value into a list of plot dicts."""
    plots: list[dict] = []

    def add(name: str, values, color: str | None = None, kind: str = "line") -> None:
        series = _to_float_list(values)
        data = [
            {"time": t, "value": v}
            for t, v in zip(times, series, strict=False)
            if v is not None
        ]
        plots.append({"name": name, "type": kind, "color": color, "data": data})

    if isinstance(result, dict) and "plots" in result:
        for p in result["plots"]:
            add(
                p.get("name", "plot"),
                p.get("values", p.get("data", [])),
                p.get("color"),
                p.get("type", "line"),
            )
    elif isinstance(result, dict):
        for name, values in result.items():
            add(name, values)
    elif isinstance(result, (list, tuple)) or hasattr(result, "tolist"):  # a list, or a Series / array
        add("plot", result)
    else:
        raise ValueError(
            "compute() must return a dict of {name: values}, a {'plots': [...]} dict, "
            "or a list of values"
        )
    return plots


# -- drawings ------------------------------------------------------------------------------------
DRAWING_TYPES = {"trendline", "rectangle", "long", "short", "channel", "hline", "vline", "polyline", "text"}

#: The most shapes one indicator may draw (the chart redraws all of them on every pan and zoom).
MAX_DRAWINGS = 500


def _epoch(value) -> int:
    """A moment as epoch seconds: a number (also numpy), an ISO string, a datetime / pandas Timestamp."""
    if isinstance(value, bool):
        raise ValueError("a time is not a boolean")
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(float(text))
        except ValueError:
            import datetime as _dt

            moment = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=_dt.timezone.utc)
            return int(moment.timestamp())
    return int(float(value))


def _point(raw) -> dict:
    """A point given as (time, price), [time, price] or {"time": .., "price": ..}."""
    if isinstance(raw, dict):
        time_, price = raw.get("time", 0), raw.get("price", 0)
    else:
        time_, price = raw[0], raw[1]
    price = float(price)
    if price != price or price in (float("inf"), float("-inf")):
        raise ValueError("a price is not a number")
    return {"time": _epoch(time_), "price": price}


def _normalise_drawings(raw) -> list[dict]:
    """The drawings an indicator returned, as plain JSON (the parent checks them against the schema)."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("'drawings' must be a list of drawings (see docs/DRAWINGS.md)")
    if len(raw) > MAX_DRAWINGS:
        raise ValueError(f"too many drawings ({len(raw)}): an indicator may draw at most {MAX_DRAWINGS}")
    out = []
    for i, item in enumerate(raw, start=1):
        try:
            if not isinstance(item, dict):
                raise ValueError("a drawing is a dict: {'type': ..., 'points': [...]}")
            kind = item.get("type")
            if kind not in DRAWING_TYPES:
                raise ValueError(f"unknown type {kind!r}; use one of {sorted(DRAWING_TYPES)}")
            style = {k: v for k, v in (item.get("style") or {}).items() if v is not None}
            out.append({"type": kind, "points": [_point(p) for p in item.get("points", [])], "style": style})
        except Exception as exc:  # noqa: BLE001 - say which drawing is wrong
            raise ValueError(f"drawing #{i}: {exc}") from exc
    return out


def _install_draw_helpers() -> None:
    """`from ct_draw import hline, rectangle, ...`: one-liners that build the drawing dicts."""
    import types

    helper = types.ModuleType("ct_draw")

    def make(kind, points, style):
        return {"type": kind, "points": [list(p) if not isinstance(p, dict) else p for p in points], "style": style}

    helper.trendline = lambda p1, p2, **style: make("trendline", [p1, p2], style)
    helper.rectangle = lambda p1, p2, **style: make("rectangle", [p1, p2], style)
    helper.channel = lambda p1, p2, p3, **style: make("channel", [p1, p2, p3], style)
    helper.polyline = lambda points, **style: make("polyline", list(points), style)
    helper.text = lambda point, text, **style: make("text", [point], {**style, "text": text})
    helper.hline = lambda price, **style: make("hline", [(0, price)], style)
    helper.vline = lambda time, **style: make("vline", [(time, 0)], style)

    def position(kind):
        def build(entry, target, stop, **style):
            """entry = (time, price); target = (end time, take-profit price); stop = the stop price."""
            return make(kind, [entry, target, (target[0], stop)], style)

        return build

    helper.long = position("long")
    helper.short = position("short")
    sys.modules["ct_draw"] = helper


def main() -> int:
    global _user_file

    user_path = sys.argv[1]
    payload_path = sys.argv[2]

    with open(payload_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    import pandas as pd  # imported before the guard is installed

    df = pd.DataFrame(payload["bars"])
    params = payload.get("params", {})
    times = [int(t) for t in df["time"].tolist()]

    _install_draw_helpers()

    # Lock down imports for everything that runs from here on (user code).
    _user_file = user_path
    builtins.__import__ = _guarded_import

    try:
        spec = importlib.util.spec_from_file_location("user_indicator", user_path)
        if spec is None or spec.loader is None:
            raise ValueError("could not load indicator module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "compute"):
            raise ValueError("Indicator must define a compute(df, params) function")

        result = module.compute(df, params)
        drawings: list[dict] = []
        if isinstance(result, dict) and "drawings" in result:
            result = dict(result)
            drawings = _normalise_drawings(result.pop("drawings"))
        plots = _normalise(result, times)
        print(json.dumps({"ok": True, "plots": plots, "drawings": drawings}))
    except Exception as exc:  # noqa: BLE001 - report any user error back to the parent
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
