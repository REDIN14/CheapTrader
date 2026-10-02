"""The few choices the user makes in the app that must survive a restart.

Kept in ``preferences.json`` in the data folder (next to ``bars.db``), written atomically:

* ``hide_terminal``     — keep the MetaTrader window hidden while the app runs;
* ``terminal_path``     — the MetaTrader terminal to use, when several are installed;
* ``allow_live_orders`` — the user has switched on, in the app, sending orders to the broker.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from app import paths

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {"hide_terminal": False, "terminal_path": None, "allow_live_orders": False}


class Preferences:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        # resolved late: the data folder may be redirected (tests, CT_DATA_DIR) after import
        return self._path or paths.data_dir() / "preferences.json"

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> Any:
        with self._lock:
            return self._read().get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            target = self.path
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, target)
        logger.info("preference %s = %r", key, value)


preferences = Preferences()
