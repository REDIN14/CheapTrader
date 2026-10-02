"""Entry point of the built program (``CheapTrader.exe``).

The same exe is also the program's helpers: the live feed and the MetaTrader reader and
trader are started as ``CheapTrader.exe --worker app.stream.mt5_feed`` and the like, and the
indicator sandbox as ``--script``. ``procutil.dispatch`` runs those; anything else is the
program itself.
"""

from __future__ import annotations

import sys


def main() -> int:
    from app import procutil

    if procutil.dispatch(sys.argv):
        return 0
    from app import desktop

    return desktop.run()


if __name__ == "__main__":
    sys.exit(main())
