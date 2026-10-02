"""Indicator registry: stores user indicators on disk and provides built-ins."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import paths
from app.schemas import IndicatorSpec

logger = logging.getLogger(__name__)

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
        return [
            IndicatorSpec(
                id=b["id"],
                name=b["name"],
                code=b["code"],
                overlay=b["overlay"],
                pane=b["pane"],
                params=b["params"],
            )
            for b in BUILTIN_INDICATORS
        ]

    def is_builtin(self, indicator_id: str) -> bool:
        return indicator_id in self._builtins

    # -- user indicators ---------------------------------------------------
    def _path(self, indicator_id: str) -> Path:
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
            b = self._builtins[indicator_id]
            return IndicatorSpec(
                id=b["id"],
                name=b["name"],
                code=b["code"],
                overlay=b["overlay"],
                pane=b["pane"],
                params=b["params"],
            )
        path = self._path(indicator_id)
        if not path.exists():
            return None
        return IndicatorSpec(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, spec: IndicatorSpec) -> IndicatorSpec:
        if not spec.id or self.is_builtin(spec.id):
            spec.id = f"user.{uuid.uuid4().hex[:12]}"
        spec.created_at = spec.created_at or datetime.now(timezone.utc)
        self._path(spec.id).write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        return spec

    def delete(self, indicator_id: str) -> bool:
        if self.is_builtin(indicator_id):
            return False
        path = self._path(indicator_id)
        if path.exists():
            path.unlink()
            return True
        return False
