"""Chart drawings: the shapes a trader (or a script) puts on a chart, and where they are kept.

A drawing is anchored to the market, not to the screen: its points are ``(time, price)``, so it stays where it
was put when the interval, the zoom or the symbol's scale changes. Drawings belong to a symbol and are kept in
``drawings/<symbol>.json`` in the data folder, which is what makes them survive a restart.

The same shapes come from three places: the user drawing on the chart, a script calling the REST API
(``/api/drawings``), and a Python indicator returning ``"drawings"`` from ``compute`` (see ``docs/DRAWINGS.md``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import paths

logger = logging.getLogger(__name__)

DrawingType = Literal["trendline", "rectangle", "long", "short", "channel", "hline", "vline", "polyline", "text"]

#: The most drawings kept for one symbol (a script in a loop must not be able to fill the disk).
MAX_PER_SYMBOL = 2000

#: How many points each shape takes: an int, or ``(least, most)``.
POINTS: dict[str, int | tuple[int, int]] = {
    "trendline": 2,  # the two ends
    "rectangle": 2,  # two opposite corners
    "long": 3,  # entry (where the box starts), target (where it ends, and the take-profit price), stop (the stop price)
    "short": 3,
    "channel": 3,  # the two ends of the base line, and a point on the parallel line
    "hline": 1,  # a price (the time is ignored)
    "vline": 1,  # a time (the price is ignored)
    "polyline": (2, 500),
    "text": 1,
}


def as_epoch(value: Any) -> int:
    """A moment as epoch seconds: a number, a numeric string, an ISO date, or a datetime."""
    if isinstance(value, bool):
        raise ValueError("a time is not a boolean")
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp())
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(float(text))
        except ValueError:
            pass
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"not a time: {value!r}") from exc
        return int((moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp())
    if hasattr(value, "timestamp"):  # pandas.Timestamp and friends
        return int(value.timestamp())
    raise ValueError(f"not a time: {value!r}")


class DrawingPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: int = 0
    price: float = 0.0

    @field_validator("time", mode="before")
    @classmethod
    def _time(cls, value: Any) -> int:
        return as_epoch(value)

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("a price is not a boolean")
        return float(value)


class DrawingStyle(BaseModel):
    """How a drawing looks. Everything is optional: a drawing has sensible defaults for its type."""

    model_config = ConfigDict(extra="ignore")

    color: str | None = Field(default=None, max_length=32)
    width: int | None = Field(default=None, ge=1, le=8)
    dash: Literal["solid", "dashed", "dotted"] | None = None
    fill: str | None = Field(default=None, max_length=32)  # fill colour of a rectangle / channel / position
    fill_opacity: float | None = Field(default=None, ge=0, le=1)
    extend_right: bool | None = None
    extend_left: bool | None = None
    text: str | None = Field(default=None, max_length=200)  # the words of a "text" drawing, or a label on any
    font_size: int | None = Field(default=None, ge=6, le=72)
    # How big a trade a long / short box stands for: a share of the balance at risk, an amount of money at
    # risk, or a plain number of lots (``risk_mode`` says which one counts).
    risk_mode: Literal["percent", "amount", "lots"] | None = None
    risk_percent: float | None = Field(default=None, gt=0, le=100)
    risk_amount: float | None = Field(default=None, gt=0)
    lots: float | None = Field(default=None, gt=0)


class Drawing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="", max_length=64)
    type: DrawingType
    points: list[DrawingPoint]
    style: DrawingStyle = Field(default_factory=DrawingStyle)
    #: A locked drawing cannot be moved or removed (its style can still be changed) until it is unlocked.
    locked: bool = False
    #: When it was made (epoch seconds); set by the server.
    created: int = 0

    @model_validator(mode="after")
    def _points(self) -> Drawing:
        want = POINTS[self.type]
        low, high = (want, want) if isinstance(want, int) else want
        if not low <= len(self.points) <= high:
            how = f"{low}" if low == high else f"{low} to {high}"
            raise ValueError(f"a {self.type} takes {how} point(s), not {len(self.points)}")
        return self


class DrawingPatch(BaseModel):
    """A partial change: the points, the style and / or whether it is locked."""

    model_config = ConfigDict(extra="ignore")

    points: list[DrawingPoint] | None = None
    style: DrawingStyle | None = None
    locked: bool | None = None


class LockedError(Exception):
    """The drawing is locked: it cannot be moved, replaced or removed until it is unlocked."""

    def __init__(self, drawing_id: str) -> None:
        super().__init__(f"The drawing {drawing_id} is locked. Unlock it first.")
        self.drawing_id = drawing_id


#: Which drawings a bulk removal takes: the ones that are not locked, only the locked ones, or all.
LockedScope = Literal["exclude", "only", "include"]


def _wanted(d: Drawing, scope: LockedScope) -> bool:
    return scope == "include" or (d.locked if scope == "only" else not d.locked)


def _clean(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._#+-]", "_", symbol.strip())[:64] or "_"


class DrawingStore:
    """The drawings of every symbol, one JSON file each. Safe to use from several threads."""

    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder
        self._lock = threading.Lock()

    @property
    def folder(self) -> Path:
        # resolved late: the data folder may be redirected (CT_DATA_DIR, tests) after import
        return self._folder or paths.data_dir() / "drawings"

    def _file(self, symbol: str) -> Path:
        return self.folder / f"{_clean(symbol)}.json"

    def _read(self, symbol: str) -> list[Drawing]:
        try:
            raw = json.loads(self._file(symbol).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out: list[Drawing] = []
        for item in raw.get("drawings", []) if isinstance(raw, dict) else []:
            try:
                out.append(Drawing.model_validate(item))
            except ValueError:
                logger.warning("skipping a damaged drawing in %s", self._file(symbol).name)
        return out

    def _write(self, symbol: str, drawings: list[Drawing]) -> None:
        target = self._file(symbol)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"symbol": symbol, "drawings": [d.model_dump(exclude_none=True) for d in drawings]}, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def for_symbol(self, symbol: str) -> list[Drawing]:
        with self._lock:
            return self._read(symbol)

    def add(self, symbol: str, drawing: Drawing) -> Drawing:
        with self._lock:
            drawings = self._read(symbol)
            if not drawing.id:
                drawing = drawing.model_copy(update={"id": uuid.uuid4().hex[:12]})
            if any(d.id == drawing.id for d in drawings):
                raise KeyError(f"there is already a drawing {drawing.id}")
            if len(drawings) >= MAX_PER_SYMBOL:
                raise ValueError(f"{symbol} already has {MAX_PER_SYMBOL} drawings, the most it can hold")
            drawing = drawing.model_copy(update={"created": drawing.created or int(time.time())})
            drawings.append(drawing)
            self._write(symbol, drawings)
            return drawing

    def replace(self, symbol: str, drawing_id: str, new: Drawing) -> Drawing:
        with self._lock:
            drawings = self._read(symbol)
            for i, d in enumerate(drawings):
                if d.id == drawing_id:
                    if d.locked:
                        raise LockedError(drawing_id)
                    drawings[i] = new.model_copy(update={"id": drawing_id, "created": d.created})
                    self._write(symbol, drawings)
                    return drawings[i]
        raise KeyError(drawing_id)

    def patch(self, symbol: str, drawing_id: str, change: DrawingPatch) -> Drawing:
        with self._lock:
            drawings = self._read(symbol)
            for i, d in enumerate(drawings):
                if d.id != drawing_id:
                    continue
                if d.locked and change.points is not None:
                    raise LockedError(drawing_id)  # (its style, and the lock itself, can still be changed)
                update: dict[str, Any] = {}
                if change.locked is not None:
                    update["locked"] = change.locked
                if change.points is not None:
                    update["points"] = change.points
                if change.style is not None:
                    merged = d.style.model_dump(exclude_none=True) | change.style.model_dump(exclude_none=True)
                    update["style"] = DrawingStyle.model_validate(merged)
                updated = Drawing.model_validate(d.model_copy(update=update).model_dump())
                drawings[i] = updated
                self._write(symbol, drawings)
                return updated
        raise KeyError(drawing_id)

    def remove(self, symbol: str, drawing_id: str) -> bool:
        with self._lock:
            drawings = self._read(symbol)
            gone = next((d for d in drawings if d.id == drawing_id), None)
            if gone is None:
                return False
            if gone.locked:
                raise LockedError(drawing_id)
            self._write(symbol, [d for d in drawings if d.id != drawing_id])
            return True

    def clear(self, symbol: str, locked: LockedScope = "exclude") -> int:
        """Remove the drawings of one symbol: by default the ones that are not locked. Returns how many."""
        with self._lock:
            drawings = self._read(symbol)
            kept = [d for d in drawings if not _wanted(d, locked)]
            if len(kept) != len(drawings):
                self._write(symbol, kept)
            return len(drawings) - len(kept)

    def symbols(self) -> list[str]:
        """The symbols that have a file of drawings (by the name they were saved under)."""
        out: list[str] = []
        for file in sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []:
            try:
                name = json.loads(file.read_text(encoding="utf-8")).get("symbol")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(name, str) and name:
                out.append(name)
        return out

    def clear_all(self, locked: LockedScope = "exclude") -> dict[str, int]:
        """``clear`` for every symbol. Returns how many were removed from each symbol that lost any."""
        removed: dict[str, int] = {}
        for symbol in self.symbols():
            n = self.clear(symbol, locked)
            if n:
                removed[symbol] = n
        return removed

    def summary(self) -> dict[str, dict[str, int]]:
        """``{symbol: {"total": n, "locked": m}}`` for every symbol that has drawings."""
        out: dict[str, dict[str, int]] = {}
        for symbol in self.symbols():
            drawings = self.for_symbol(symbol)
            if drawings:
                out[symbol] = {"total": len(drawings), "locked": sum(1 for d in drawings if d.locked)}
        return out


store = DrawingStore()
