"""Remove synthetic (mock) bars that ended up in the real bar store.

Why this exists: before the mock adapter got its own database file, running the
backend without a MetaTrader terminal (CT_BROKER=auto silently falls back to the
mock) or running the test-suite wrote fabricated candles into data/bars.db, right
next to real broker history. They are easy to recognise: a broker's intraday bars
always open on the timeframe grid (an H1 bar opens at hh:00:00), the mock's did not.

Usage - stop the backend first, then from the backend folder:

    uv run python scripts/purge_mock_bars.py            # report only, changes nothing
    uv run python scripts/purge_mock_bars.py --apply    # back up, then delete

The database is copied to ``bars.db.bak-<timestamp>`` before anything is deleted.
Only M1-H1 are checked: H4 and above can legitimately start off-grid on some
brokers, so they are left alone.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Intraday timeframes whose bars always open on a whole multiple of their length.
GRID_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "bars.db"


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


def find_off_grid(conn: sqlite3.Connection) -> list[tuple[str, str, int, int, int]]:
    """(symbol, timeframe, count, first, last) for every series holding off-grid bars."""
    found: list[tuple[str, str, int, int, int]] = []
    for timeframe, step in GRID_SECONDS.items():
        rows = conn.execute(
            "SELECT symbol, COUNT(*), MIN(time), MAX(time) FROM bars "
            "WHERE timeframe = ? AND time % ? != 0 GROUP BY symbol ORDER BY symbol",
            (timeframe, step),
        ).fetchall()
        found.extend((symbol, timeframe, n, lo, hi) for symbol, n, lo, hi in rows)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="bar database to clean")
    parser.add_argument("--apply", action="store_true", help="back up and delete (default: report only)")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"No database at {args.db}")
        return 1

    conn = sqlite3.connect(str(args.db), timeout=30)
    off_grid = find_off_grid(conn)
    if not off_grid:
        print("Nothing to remove: every M1-H1 bar sits on its timeframe grid.")
        return 0

    total = sum(n for _, _, n, _, _ in off_grid)
    print(f"Off-grid (synthetic) bars in {args.db}:")
    for symbol, timeframe, n, lo, hi in off_grid:
        print(f"  {symbol:10s} {timeframe:4s} {n:7,d} bars   {fmt(lo)} -> {fmt(hi)}")
    print(f"  {'total':15s} {total:7,d}")

    if not args.apply:
        print("\nNothing was changed. Re-run with --apply to back up the database and delete them.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = args.db.with_name(f"{args.db.name}.bak-{stamp}")
    # sqlite3's backup API copies a consistent snapshot, including anything still
    # sitting in the write-ahead log.
    with sqlite3.connect(str(backup)) as dst:
        conn.backup(dst)
    dst.close()
    print(f"\nBacked up to {backup}")

    deleted = 0
    with conn:
        for timeframe, step in GRID_SECONDS.items():
            deleted += conn.execute(
                "DELETE FROM bars WHERE timeframe = ? AND time % ? != 0", (timeframe, step)
            ).rowcount
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(f"Deleted {deleted:,d} synthetic bars.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
