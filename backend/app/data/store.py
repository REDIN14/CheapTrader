"""Persistent, incremental bar store.

Bars are cached in a local SQLite database. Requests only fetch the data that
is actually missing from the broker:

- "latest N bars"  -> serve from DB; fetch only if the newest bar is stale or
  fewer than N bars are stored (then page *backwards* for the shortfall).
- "range [a, b]"   -> serve from DB; fetch only the uncovered sub-ranges.

Nothing is ever regenerated wholesale.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import paths
from app.broker.base import BrokerAdapter
from app.schemas import TIMEFRAME_SECONDS, Bar, Timeframe

logger = logging.getLogger(__name__)

# Seconds per timeframe, used to size backfill windows.
_TF_SECONDS = TIMEFRAME_SECONDS

DATA_DIR = paths.data_dir()


def store_path_for_broker(base: Path, broker: str) -> Path:
    """The bar store of one broker.

    Quotes and the server's clock differ from broker to broker, and candles of two of them in one
    file would draw a chart nobody traded. The first broker to use ``base`` keeps it (its name is
    written next to it in ``<base>.broker``, which also covers history gathered before this existed);
    any other broker gets a file of its own, named after it.
    """
    broker = broker.strip()
    if not broker:
        return base
    marker = base.with_name(base.name + ".broker")
    try:
        owner = marker.read_text(encoding="utf-8").strip()
    except OSError:
        owner = ""
    if not owner:
        base.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(broker, encoding="utf-8")
        return base
    if owner.lower() == broker.lower():
        return base
    slug = re.sub(r"[^a-z0-9]+", "-", broker.lower()).strip("-") or "broker"
    return base.with_name(f"{base.stem}.{slug}{base.suffix}")


def default_db_path(source: str) -> Path:
    """Database file for one data source ("mt5", "mock", ...).

    The store keys rows by (symbol, timeframe, time) and has no idea where a bar
    came from, so bars synthesised by the mock adapter must never share a file
    with history fetched from a real broker: they would silently end up as fake
    candles in real charts. The mock therefore gets a file of its own.
    """
    return DATA_DIR / ("bars.mock.db" if source == "mock" else "bars.db")


# A stretch with no bars at all is only suspicious beyond this length. Weekends
# (2 days) and ordinary holiday closures stay well below it, so a healthy series
# never triggers a fetch. MN1 is left out: its bars are a month apart by nature.
_MAX_GAP = {
    Timeframe.M1: 6 * 86400,
    Timeframe.M5: 6 * 86400,
    Timeframe.M15: 6 * 86400,
    Timeframe.M30: 6 * 86400,
    Timeframe.H1: 6 * 86400,
    Timeframe.H4: 6 * 86400,
    Timeframe.D1: 14 * 86400,
    Timeframe.W1: 56 * 86400,
}

# Holes healed per request, so one badly damaged series cannot stall a page load.
_MAX_GAP_FETCHES = 4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    time        INTEGER NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    tick_volume INTEGER NOT NULL DEFAULT 0,
    spread      INTEGER NOT NULL DEFAULT 0,
    real_volume INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe, time)
);
CREATE INDEX IF NOT EXISTS idx_bars_lookup ON bars (symbol, timeframe, time DESC);
"""


@dataclass
class Coverage:
    count: int
    oldest: int | None
    newest: int | None


class BarStore:
    """SQLite-backed incremental bar cache."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or default_db_path("mt5")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Holes already tried this run, so a stretch the broker has no data for is
        # asked about once instead of on every request.
        self._tried_gaps: set[tuple[str, str, int, int]] = set()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # -- reads -------------------------------------------------------------
    def coverage(self, symbol: str, timeframe: Timeframe) -> Coverage:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n, MIN(time) AS lo, MAX(time) AS hi "
                "FROM bars WHERE symbol=? AND timeframe=?",
                (symbol, timeframe.value),
            ).fetchone()
        return Coverage(count=row["n"], oldest=row["lo"], newest=row["hi"])

    def read(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> list[Bar]:
        sql = (
            "SELECT time, open, high, low, close, tick_volume, spread, real_volume "
            "FROM bars WHERE symbol=? AND timeframe=?"
        )
        params: list = [symbol, timeframe.value]
        if start is not None:
            sql += " AND time >= ?"
            params.append(start)
        if end is not None:
            sql += " AND time <= ?"
            params.append(end)
        sql += " ORDER BY time DESC"
        if count is not None:
            sql += " LIMIT ?"
            params.append(count)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        bars = [
            Bar(
                time=r["time"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                tick_volume=r["tick_volume"],
                spread=r["spread"],
                real_volume=r["real_volume"],
            )
            for r in rows
        ]
        bars.reverse()
        return bars

    # -- writes ------------------------------------------------------------
    def upsert(self, symbol: str, timeframe: Timeframe, bars: list[Bar]) -> int:
        if not bars:
            return 0
        rows = [
            (
                symbol,
                timeframe.value,
                b.time,
                b.open,
                b.high,
                b.low,
                b.close,
                b.tick_volume,
                b.spread,
                b.real_volume,
            )
            for b in bars
        ]
        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO bars (symbol, timeframe, time, open, high, low, close, "
                "tick_volume, spread, real_volume) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol, timeframe, time) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, "
                "close=excluded.close, tick_volume=excluded.tick_volume, "
                "spread=excluded.spread, real_volume=excluded.real_volume",
                rows,
            )
        return len(rows)

    # -- incremental fetch -------------------------------------------------
    def get_bars(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
        refresh_recent: int = 2,
    ) -> list[Bar]:
        """Return bars, fetching only what is missing from the broker."""
        if start is not None and end is not None:
            return self._get_range(broker, symbol, timeframe, start, end)
        return self._get_latest(broker, symbol, timeframe, count, refresh_recent)

    def _get_latest(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        count: int,
        refresh_recent: int,
    ) -> list[Bar]:
        cov = self.coverage(symbol, timeframe)

        # Cold start: fetch the whole window in a single request.
        if cov.newest is None:
            bars = broker.get_bars(symbol, timeframe, count=count)
            self.upsert(symbol, timeframe, bars)
            return self.read(symbol, timeframe, count=count)

        # Bring the newest end up to date, however long the store sat unused.
        self._refresh_tail(broker, symbol, timeframe, cov.newest, refresh_recent)
        cov = self.coverage(symbol, timeframe)

        # Backfill older history only if we are short of `count`.
        if cov.count < count:
            self._backfill(broker, symbol, timeframe, count)

        bars = self.read(symbol, timeframe, count=count)
        if self._fill_gaps(broker, symbol, timeframe, bars):
            bars = self.read(symbol, timeframe, count=count)
        return bars

    def _refresh_tail(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        newest: int,
        refresh_recent: int,
    ) -> None:
        """Store the broker's latest bars and fetch whatever lies between them and ours.

        The forming bar changes constantly, so the last couple of bars are always
        re-read. Their position also shows how far behind the store is (a store
        last used days ago would otherwise keep serving a stale tail), and the
        stretch in between is fetched. Comparing bar times with each other keeps
        this independent of the broker's time zone.
        """
        recent = broker.get_bars(symbol, timeframe, count=max(refresh_recent, 2))
        if not recent:
            return
        self.upsert(symbol, timeframe, recent)
        # More than one bar apart means at least one bar in between is missing.
        if recent[0].time - newest > _TF_SECONDS[timeframe]:
            self._fetch_range(broker, symbol, timeframe, newest, recent[0].time)

    def _fill_gaps(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        bars: list[Bar],
    ) -> bool:
        """Fetch stretches inside ``bars`` that hold no data at all.

        Normal market closures are far shorter than ``_MAX_GAP``; anything longer
        means bars went missing (for example after fabricated ones were removed),
        and the broker is asked for them. Each hole is tried once per run.
        Returns True when new bars arrived.
        """
        limit = _MAX_GAP.get(timeframe)
        if limit is None or len(bars) < 2:
            return False

        healed = False
        attempts = 0
        for before, after in zip(bars, bars[1:]):
            if after.time - before.time <= limit:
                continue
            key = (symbol, timeframe.value, before.time, after.time)
            if key in self._tried_gaps:
                continue
            self._tried_gaps.add(key)
            # The window includes both neighbours, which are already stored, so
            # more than two bars back means something new.
            if self._fetch_range(broker, symbol, timeframe, before.time, after.time) > 2:
                healed = True
            attempts += 1
            if attempts >= _MAX_GAP_FETCHES:
                break
        return healed

    def _get_range(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        cov = self.coverage(symbol, timeframe)

        # Fetch only the sub-ranges of [start, end] that are not yet stored.
        # Nothing already in the DB is ever re-fetched.
        if cov.oldest is None or cov.newest is None:
            self._fetch_range(broker, symbol, timeframe, start_ts, end_ts)
        else:
            if start_ts < cov.oldest:
                self._fetch_range(broker, symbol, timeframe, start_ts, cov.oldest)
            if end_ts > cov.newest:
                self._fetch_range(broker, symbol, timeframe, cov.newest, end_ts)

        bars = self.read(symbol, timeframe, start=start_ts, end=end_ts)
        if self._fill_gaps(broker, symbol, timeframe, bars):
            bars = self.read(symbol, timeframe, start=start_ts, end=end_ts)
        return bars

    def _fetch_range(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        start_ts: int,
        end_ts: int,
    ) -> int:
        """Fetch and store a single [start_ts, end_ts] window from the broker."""
        if end_ts <= start_ts:
            return 0
        start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        bars = broker.get_bars(symbol, timeframe, start=start, end=end)
        return self.upsert(symbol, timeframe, bars)

    def _backfill(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        target: int,
        max_pages: int = 40,
    ) -> int:
        """Page backwards until at least ``target`` bars are stored."""
        step = _TF_SECONDS[timeframe]
        page = max(target, 1000)
        total = 0

        for _ in range(max_pages):
            cov = self.coverage(symbol, timeframe)
            if cov.count >= target:
                break

            if cov.oldest is None:
                # Nothing stored yet: fetch the latest page first.
                bars = broker.get_bars(symbol, timeframe, count=page)
            else:
                window_end = datetime.fromtimestamp(cov.oldest, tz=timezone.utc)
                window_start = window_end - timedelta(seconds=step * page)
                bars = broker.get_bars(symbol, timeframe, start=window_start, end=window_end)
                # Drop the boundary bar we already have.
                bars = [b for b in bars if b.time < cov.oldest]

            if not bars:
                break
            total += self.upsert(symbol, timeframe, bars)

            new_cov = self.coverage(symbol, timeframe)
            if new_cov.oldest == cov.oldest:
                break  # no progress -> broker has no more history

        return total

    def ensure_history(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        target: int,
    ) -> Coverage:
        """Fetch deeper history only if fewer than ``target`` bars are stored."""
        cov = self.coverage(symbol, timeframe)
        if cov.count < target:
            self._backfill(broker, symbol, timeframe, target)
            cov = self.coverage(symbol, timeframe)
        return cov

    def ensure_range(
        self,
        broker: BrokerAdapter,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Return every stored bar in [start, end], fetching only what is missing."""
        return self._get_range(broker, symbol, timeframe, start, end)

    def stats(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, timeframe, COUNT(*) AS n, MIN(time) AS lo, MAX(time) AS hi "
                "FROM bars GROUP BY symbol, timeframe ORDER BY symbol, timeframe"
            ).fetchall()
        return [
            {
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "count": r["n"],
                "oldest": r["lo"],
                "newest": r["hi"],
            }
            for r in rows
        ]
