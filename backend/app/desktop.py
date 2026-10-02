"""The built program: start the server, open its window, quit when the window is closed.

``CheapTrader.exe`` has no console. It starts the whole app (page, API, live stream and the
MetaTrader helper processes) as one server on this machine only, opens it in a window of
its own (Edge or Chrome in "app" mode, so no tabs and no address bar), and stops everything
when that window is closed.

* a second start while one is running just opens another window onto the first;
* ``--no-window`` serves without a window (stop it with Task Manager or ``taskkill``);
* ``--console`` also shows the log in a console window, for finding out what went wrong;
* everything is logged to ``logs/cheaptrader.log`` (the helper processes to ``logs/workers.log``)
  in the program's data folder.
"""

from __future__ import annotations

import ctypes
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import paths

TITLE = "CheapTrader"
#: The port when ``CT_PORT`` does not say (8000 is the development server's).
DEFAULT_PORT = 8765
HOST = "127.0.0.1"
#: How long the server may take to come up (a MetaTrader terminal that has to start first can be slow).
START_TIMEOUT = 180.0

logger = logging.getLogger("cheaptrader.desktop")


def message(text: str, *, error: bool = False, wait: bool = True) -> None:
    """A dialog: the one way a program without a console can tell the user something."""
    if os.name != "nt":
        print(text)
        return
    flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    flags |= 0x40000  # MB_TOPMOST
    if wait:
        ctypes.windll.user32.MessageBoxW(0, text, TITLE, flags)
    else:
        threading.Thread(target=ctypes.windll.user32.MessageBoxW, args=(0, text, TITLE, flags), daemon=True).start()


def setup_logging(console: bool) -> Path:
    log = paths.logs_dir() / "cheaptrader.log"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    ]
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return log


def attach_console() -> None:
    """``--console``: give the program a console window to show its log in."""
    if os.name != "nt":
        return
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8")


def find_browser() -> str | None:
    """Edge (on every current Windows), else Chrome."""
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for relative in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            candidate = Path(root) / relative
            if candidate.is_file():
                return str(candidate)
    return None


def open_window(url: str) -> subprocess.Popen | None:
    """The app window. It has a profile of its own so that it is a browser process of its own:
    waiting for it is then waiting for the user to close the window."""
    browser = find_browser()
    if browser is None:
        return None
    profile = paths.data_dir() / "window"
    return subprocess.Popen(
        [
            browser,
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            "--window-size=1600,950",
            # A fresh Edge profile otherwise downloads ~900 MB of components and bundled extensions
            # into the data folder; this is a window onto one page, it needs none of that (21 MB).
            "--disable-extensions",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--disable-features=msEdgeShopping,msEdgeWallet,EdgeShopping,EdgeWallet,msWebOOUI,msEdgeEnhanceImages",
            "--no-service-autorun",
            "--disable-domain-reliability",
        ]
    )


_user32 = None


def visible_titles() -> list[str]:
    """The titles of the windows on the desktop (minimised ones too)."""
    global _user32
    if os.name != "nt":
        return []
    from ctypes import wintypes

    if _user32 is None:
        _user32 = ctypes.WinDLL("user32")
        _user32.IsWindowVisible.argtypes = [wintypes.HWND]
        _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    titles: list[str] = []

    def visit(hwnd, _lparam) -> bool:
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
        return True

    _user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit), 0)
    return titles


def app_window_open(port: int) -> bool:
    """Is there a window showing the app? The page names itself "CheapTrader · 127.0.0.1:<port>"."""
    return any("CheapTrader" in title and f":{port}" in title for title in visible_titles())


#: How long without a window before the program quits (a page reload, a moment of nothing).
CLOSE_GRACE = 4.0
#: How long to wait for the window to show up at all.
APPEAR_WITHIN = 60.0


def wait_until_closed(
    port: int,
    alive,
    *,
    shown=app_window_open,
    clock=time.monotonic,
    sleep=time.sleep,
    poll: float = 0.5,
) -> None:
    """Return when the app's window has been closed (or the server has ended on its own).

    The window is looked for on the desktop rather than waited for as a process: Edge may hand the
    window to a browser that is already running and exit at once, which says nothing about whether
    the window is still open.
    """
    began = clock()
    seen = False
    gone: float | None = None
    while alive():
        sleep(poll)
        now = clock()
        if shown(port):
            seen, gone = True, None
        elif seen:
            gone = now if gone is None else gone
            if now - gone >= CLOSE_GRACE:
                logger.info("the window was closed")
                return
        elif now - began > APPEAR_WITHIN:
            logger.warning("no window with the app appeared; leaving the server running")
            while alive():
                sleep(poll)
            return


def health(port: int) -> dict | None:
    """The answer of a CheapTrader server on ``port``, if there is one."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1.5) as response:
            data = json.loads(response.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "broker" in data else None


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise OSError("no free port")


_singleton = None  # the handle must live as long as the program does


def already_started() -> bool:
    """True when another copy of the program is running (or still starting).

    The first copy owns a named mutex; a second start finds it taken. That is how a double
    click while the first copy is still coming up (it can take ten seconds, a minute the very
    first time) does not start a second server.
    """
    global _singleton
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _singleton = kernel32.CreateMutexW(None, False, "Local\\CheapTrader.singleton")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def port_file() -> Path:
    return paths.data_dir() / "port.txt"


def running_port() -> int:
    """The port the running copy serves on (it may have had to pick another one)."""
    try:
        return int(port_file().read_text().strip())
    except (OSError, ValueError):
        return chosen_port()


def chosen_port() -> int:
    from app.config import get_settings

    settings = get_settings()
    return settings.port if "port" in settings.model_fields_set else DEFAULT_PORT


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is None:  # no console: nothing may fail because there is nowhere to print
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if already_started():  # another copy is running or starting: just another window onto it (and not a word in its log)
        waited = time.monotonic()
        while health(running_port()) is None and time.monotonic() - waited < START_TIMEOUT:
            time.sleep(0.5)
        url = f"http://{HOST}:{running_port()}/"
        if health(running_port()) is not None and "--no-window" not in argv and open_window(url) is None:
            webbrowser.open(url)
        return 0
    if "--console" in argv:
        attach_console()
    # matplotlib (the snapshot renderer) would otherwise rebuild its font cache in a fresh temporary folder on every start
    os.environ.setdefault("MPLCONFIGDIR", str(paths.data_dir() / "mplconfig"))
    log = setup_logging(console="--console" in argv)
    logger.info("starting (data in %s)", paths.data_dir())

    port = free_port(chosen_port())
    port_file().write_text(str(port))
    url = f"http://{HOST}:{port}/"

    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()

    from app.api import terminal_routes

    # the page's Quit button (MetaTrader menu) stops the program
    terminal_routes.quit_hook = lambda: setattr(server, "should_exit", True)

    began = time.monotonic()
    while health(port) is None:
        if not thread.is_alive() or time.monotonic() - began > START_TIMEOUT:
            server.should_exit = True
            message(f"CheapTrader could not start.\n\nThe details are in\n{log}", error=True)
            return 1
        time.sleep(0.25)
    logger.info("serving %s after %.1f s", url, time.monotonic() - began)

    if "--no-window" in argv:
        thread.join()
        return 0

    if open_window(url) is None:
        # No Edge or Chrome: the default browser. There is no window of ours to watch then, so the
        # program runs until the Quit button in the page (or Task Manager) ends it.
        webbrowser.open(url)
        thread.join()
        return 0
    wait_until_closed(port, thread.is_alive)
    return stop(server, thread)


def stop(server, thread: threading.Thread) -> int:
    logger.info("stopping")
    server.should_exit = True
    thread.join(timeout=40)
    return 0
