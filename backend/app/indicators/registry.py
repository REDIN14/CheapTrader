"""Indicator registry: stores user indicators on disk and provides built-ins.

A built-in's code is part of the program and cannot be changed, but its parameters can (the length of a moving
average, say): what the user set is kept in ``indicators/builtin/<id>.json`` in the data folder, and only what differs
from the built-in's own values is written down.
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import paths
from app.schemas import IndicatorSpec, IndicatorUpdate

logger = logging.getLogger(__name__)

#: What an indicator's id may look like: it names a file in the data folder.
_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
#: The largest whole number a built-in's parameter may be set to.
MAX_WHOLE = 1_000_000


class IndicatorError(ValueError):
    """A change to an indicator that cannot be made; the message says why, in words for the user."""


def _number(value: Any) -> float | None:
    """A parameter's value as a number: a number, or text that is one (the settings send what was typed)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def checked_params(defaults: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    """New values for a built-in's parameters, checked against the built-in's own (``defaults``): only parameters it
    has, a whole number of at least 1 where it takes one (a period, a number of bars), a number above 0 where it takes
    a fraction. Raises ``IndicatorError`` naming the first that is wrong."""
    out: dict[str, Any] = {}
    for key, value in given.items():
        if key not in defaults:
            raise IndicatorError(f"It has no parameter called {key!r} (its parameters: {', '.join(defaults)}).")
        default = defaults[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise IndicatorError(f"{key} is true or false.")
            out[key] = value
        elif isinstance(default, int):
            number = _number(value)
            if number is None or not math.isfinite(number) or number != int(number):
                raise IndicatorError(f"{key} must be a whole number (it was {value!r}).")
            if not 1 <= number <= MAX_WHOLE:
                raise IndicatorError(f"{key} must be from 1 to {MAX_WHOLE:,} (it was {int(number)}).")
            out[key] = int(number)
        elif isinstance(default, float):
            number = _number(value)
            if number is None or not math.isfinite(number) or number <= 0:
                raise IndicatorError(f"{key} must be a number above 0 (it was {value!r}).")
            out[key] = number
        else:
            out[key] = value
    return out

BUILTIN_INDICATORS: list[dict] = [
    {
        "id": "builtin.sma",
        "name": "Simple Moving Average",
        "overlay": True,
        "pane": 0,
        "params": {"period": 20},
        "code": '''"""Simple Moving Average."""


def compute(df, params):
    period = int(params.get("period", 20))
    return {"SMA": df["close"].rolling(period).mean()}
''',
    },
    {
        "id": "builtin.ema",
        "name": "Exponential Moving Average",
        "overlay": True,
        "pane": 0,
        "params": {"period": 21},
        "code": '''"""Exponential Moving Average."""


def compute(df, params):
    period = int(params.get("period", 21))
    return {"EMA": df["close"].ewm(span=period, adjust=False).mean()}
''',
    },
    {
        "id": "builtin.bollinger",
        "name": "Bollinger Bands",
        "overlay": True,
        "pane": 0,
        "params": {"period": 20, "std": 2.0},
        "code": '''"""Bollinger Bands."""


def compute(df, params):
    period = int(params.get("period", 20))
    mult = float(params.get("std", 2.0))
    mid = df["close"].rolling(period).mean()
    sd = df["close"].rolling(period).std()
    return {
        "Upper": mid + mult * sd,
        "Middle": mid,
        "Lower": mid - mult * sd,
    }
''',
    },
    {
        "id": "builtin.rsi",
        "name": "Relative Strength Index",
        "overlay": False,
        "pane": 1,
        "params": {"period": 14},
        "code": '''"""Relative Strength Index."""


def compute(df, params):
    period = int(params.get("period", 14))
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return {"RSI": 100 - (100 / (1 + rs))}
''',
    },
    {
        "id": "builtin.macd",
        "name": "MACD",
        "overlay": False,
        "pane": 1,
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "code": '''"""Moving Average Convergence Divergence."""


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
            {"name": "MACD", "values": macd, "type": "line", "color": "#2962ff"},
            {"name": "Signal", "values": sig, "type": "line", "color": "#ff9800"},
        ]
    }
''',
    },
    {
        "id": "builtin.rangebox",
        "name": "Range box (drawings)",
        "overlay": True,
        "pane": 0,
        "params": {"bars": 50},
        "code": '''"""The high-low range of the last N bars as a box on the chart: an example of drawings."""

from ct_draw import hline, rectangle


def compute(df, params):
    n = int(params.get("bars", 50))
    recent = df.tail(n)
    hi, lo = float(recent["high"].max()), float(recent["low"].min())
    t0, t1 = int(recent["time"].iloc[0]), int(recent["time"].iloc[-1])
    return {
        "drawings": [
            rectangle((t0, hi), (t1, lo), extend_right=True, color="#2962ff", fill="#2962ff", fill_opacity=0.12),
            hline((hi + lo) / 2, color="#787b86", dash="dotted", width=1),
        ]
    }
''',
    },
]


class IndicatorRegistry:
    """Persists user indicators as JSON files under a data directory."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or paths.data_dir() / "indicators"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._builtins = {b["id"]: b for b in BUILTIN_INDICATORS}

    # -- built-ins ---------------------------------------------------------
    def builtins(self) -> list[IndicatorSpec]:
        return [self._builtin_spec(b) for b in BUILTIN_INDICATORS]

    def is_builtin(self, indicator_id: str) -> bool:
        return indicator_id in self._builtins

    def _builtin_spec(self, b: dict) -> IndicatorSpec:
        """A built-in as the user set it: its own code, its parameters with the user's values over its own."""
        return IndicatorSpec(
            id=b["id"],
            name=b["name"],
            code=b["code"],
            overlay=b["overlay"],
            pane=b["pane"],
            params={**b["params"], **self._builtin_params(b)},
            defaults=dict(b["params"]),
        )

    def _builtin_path(self, indicator_id: str) -> Path:
        return self._dir / "builtin" / f"{indicator_id}.json"

    def _builtin_params(self, b: dict) -> dict[str, Any]:
        """The values the user gave a built-in's parameters. A file that was edited by hand into something the
        built-in does not take is left out, so it cannot break the built-in."""
        try:
            saved = json.loads(self._builtin_path(b["id"]).read_text(encoding="utf-8")).get("params")
            return checked_params(b["params"], saved) if isinstance(saved, dict) else {}
        except (OSError, ValueError, AttributeError):
            return {}

    def set_builtin_params(self, indicator_id: str, params: dict[str, Any]) -> IndicatorSpec:
        """Give a built-in new values for (some of) its parameters; the others keep theirs. Setting them back to the
        built-in's own values leaves nothing written down. Raises ``IndicatorError`` for a value it does not take."""
        b = self._builtins[indicator_id]
        values = {**b["params"], **self._builtin_params(b), **checked_params(b["params"], params)}
        changed = {key: value for key, value in values.items() if value != b["params"][key]}
        path = self._builtin_path(indicator_id)
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"params": changed}, indent=2), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return self._builtin_spec(b)

    def update(self, indicator_id: str, change: IndicatorUpdate) -> IndicatorSpec | None:
        """Change what ``change`` gives. None: there is no such indicator (and too little was given to make one).

        A built-in takes new parameters only: a different code, name or kind is refused (``IndicatorError``), the
        same ones (the settings send them back as they are) are fine.
        """
        b = self._builtins.get(indicator_id)
        if b is not None:
            if change.code is not None and change.code.strip() != b["code"].strip():
                raise IndicatorError(
                    "The code of a built-in indicator cannot be changed. To change it, make a copy of it "
                    "(Copy, in its settings): the copy is your own indicator."
                )
            if (change.name is not None and change.name.strip() != b["name"]) or (
                change.overlay is not None and change.overlay != b["overlay"]
            ):
                raise IndicatorError("Only the parameters of a built-in indicator can be changed.")
            return self._builtin_spec(b) if change.params is None else self.set_builtin_params(indicator_id, change.params)

        current = self.get(indicator_id)
        if current is None:
            if change.name is None or change.code is None:
                return None
            self._path(indicator_id)  # an id that cannot name a file is refused before anything is written
            current = IndicatorSpec(id=indicator_id, name=change.name, code=change.code)
        updated = current.model_copy(update=change.model_dump(exclude_none=True))
        if not updated.name.strip():
            raise IndicatorError("An indicator needs a name.")
        updated.id = indicator_id
        return self.save(updated)

    # -- user indicators ---------------------------------------------------
    def _path(self, indicator_id: str) -> Path:
        if not _ID.fullmatch(indicator_id) or ".." in indicator_id:
            raise IndicatorError(f"{indicator_id!r} is not an indicator id.")
        return self._dir / f"{indicator_id}.json"

    def list(self) -> list[IndicatorSpec]:
        specs = self.builtins()
        for path in sorted(self._dir.glob("*.json")):
            try:
                specs.append(IndicatorSpec(**json.loads(path.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping corrupt indicator file %s", path)
        return specs

    def get(self, indicator_id: str) -> IndicatorSpec | None:
        if indicator_id in self._builtins:
            return self._builtin_spec(self._builtins[indicator_id])
        try:
            path = self._path(indicator_id)
        except IndicatorError:
            return None
        if not path.exists():
            return None
        return IndicatorSpec(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, spec: IndicatorSpec) -> IndicatorSpec:
        if not spec.id or self.is_builtin(spec.id):
            spec.id = f"user.{uuid.uuid4().hex[:12]}"
        spec.created_at = spec.created_at or datetime.now(timezone.utc)
        spec.defaults = None  # only a built-in has parameters of its own to go back to
        self._path(spec.id).write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        return spec

    def delete(self, indicator_id: str) -> bool:
        if self.is_builtin(indicator_id):
            return False
        try:
            path = self._path(indicator_id)
        except IndicatorError:
            return False
        if path.exists():
            path.unlink()
            return True
        return False
