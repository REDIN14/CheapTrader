"""Where the app's files live.

While developing, everything sits next to the code (``backend/data``, ``backend/.env``).
Built into a Windows program (see ``scripts/build_exe.py``) the code is unpacked from the
exe, which is no place to keep anything, so the bar store, the indicators, the settings
and the logs live next to ``CheapTrader.exe`` instead (or, if that folder is not
writable, under ``%LOCALAPPDATA%\\CheapTrader``).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def frozen() -> bool:
    """True inside the built program."""
    return bool(getattr(sys, "frozen", False))


def backend_root() -> Path:
    """The ``backend`` folder (development)."""
    return Path(__file__).resolve().parents[1]


def bundle_dir() -> Path:
    """Where a built program keeps its read-only files (the page, the indicator runner)."""
    return Path(getattr(sys, "_MEIPASS", backend_root()))


def app_dir() -> Path:
    """The folder the program is run from: the exe's, or ``backend`` while developing."""
    return Path(sys.executable).resolve().parent if frozen() else backend_root()


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """The bar store, the indicators and the logs. ``CT_DATA_DIR`` overrides it."""
    chosen = os.environ.get("CT_DATA_DIR")
    if chosen:
        return Path(chosen)
    if not frozen():
        return backend_root() / "data"
    beside = app_dir() / "data"
    if _writable(beside):
        return beside
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CheapTrader" / "data"


def env_file() -> str:
    """The settings file: ``.env`` in the folder the code is run from (as it always was)
    or, in the built program, next to the exe."""
    return str(app_dir() / ".env") if frozen() else ".env"


def ui_dir() -> Path | None:
    """The built page (``index.html`` and its assets), if this program is to serve it.

    The built program always does. In development the page comes from Vite, unless
    ``CT_UI_DIR`` says otherwise (handy to try the one-port setup: ``frontend/dist``).
    """
    chosen = os.environ.get("CT_UI_DIR")
    if chosen:
        folder = Path(chosen)
    elif frozen():
        folder = bundle_dir() / "web"
    else:
        return None
    return folder if (folder / "index.html").is_file() else None


def docs_dir() -> Path:
    """The documentation (`docs/*.md`): in the repository, or bundled into the exe."""
    return bundle_dir() / "docs" if frozen() else backend_root().parent / "docs"


def logs_dir() -> Path:
    folder = data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
