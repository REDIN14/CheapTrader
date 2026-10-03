"""The built program: start the server, open its window, quit when the window is closed.

``CheapTrader.exe`` has no console. It starts the whole app (page, API, live stream and the
MetaTrader helper processes) as one server on this machine only, opens it in a window of
its own (Edge or Chrome in "app" mode, so no tabs and no address bar), and stops everything
when that window is closed.

* a second start while one is running asks the first to open another window onto itself (a copy whose window
  has just been closed ends a few seconds later, and a window opened on a copy that is ending would show
  "connection refused", so the first copy only agrees while it is not ending). A second start that finds the first
  one on its way out waits for it to end and starts afresh. Only the first copy ever starts a window, so every window
  belongs to a Windows job that ends with the program (``app/windowjob.py``): ending the program by force (Task
  Manager) takes its windows with it, instead of leaving one that shows a page nothing serves;
* a start while an update is being installed waits for it (the installer cannot replace a program that is running);
* ``--no-window`` serves without a window (stop it with Task Manager or ``taskkill``);
* ``--reconnect`` is what an update starts the new version with: the window the old version left open is
  used again instead of opening another;
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
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app import paths
from app.windowjob import WindowJob

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


def open_window(url: str, job: WindowJob | None = None) -> subprocess.Popen | None:
    """The app window. It has a profile of its own so that it is a browser process of its own. With a ``job`` the window
    is tied to the program: the system ends it when the program ends, however that happens."""
    browser = find_browser()
    if browser is None:
        return None
    profile = paths.data_dir() / "window"
    process = subprocess.Popen(
        [
            browser,
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            # a window that was ended by force leaves its profile "not closed properly": no question about it in the window
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
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
    if job is not None:
        job.add(process)
    return process


_user32 = None


def _top_level_windows() -> list[tuple[int, str]]:
    """``(handle, title)`` of the windows on the desktop that have a title (minimised ones too)."""
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
        _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    found: list[tuple[int, str]] = []

    def visit(hwnd, _lparam) -> bool:
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append((int(hwnd or 0), buffer.value))
        return True

    _user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit), 0)
    return found


def visible_titles() -> list[str]:
    """The titles of the windows on the desktop (minimised ones too)."""
    return [title for _hwnd, title in _top_level_windows()]


def _shows_the_app(title: str, port: int) -> bool:
    return "CheapTrader" in title and f":{port}" in title


def close_windows(port: int) -> None:
    """Ask the windows that show the app on ``port`` to close, as their close button does (the Quit button ends the
    program, so its window goes with it and is not left showing a page that nothing serves)."""
    for hwnd, title in _top_level_windows():
        if _shows_the_app(title, port):
            _user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def app_window_open(port: int) -> bool:
    """Is there a window showing the app? The page names itself "CheapTrader · 127.0.0.1:<port>"."""
    return any(_shows_the_app(title, port) for title in visible_titles())


def window_returns(port: int, within: float = 8.0, *, shown=app_window_open, clock=time.monotonic, sleep=time.sleep) -> bool:
    """Is a window of the app showing (or about to show) on ``port``? Looks for a few seconds."""
    deadline = clock() + within
    while True:
        if shown(port):
            return True
        if clock() >= deadline:
            return False
        sleep(0.5)


#: How long without a window before the program quits (a page reload, a moment of nothing).
CLOSE_GRACE = 4.0
#: How long to wait for the window to show up at all.
APPEAR_WITHIN = 60.0
#: How long the program stays for a window that a second start has announced (Edge may need a while to open it).
EXPECT_WINDOW_FOR = 20.0
#: How long the server waits for a request that is still being worked on when the program ends. Without a limit a
#: big history read that the closed window had asked for keeps the program alive until it is done, and whoever
#: opens the program again meanwhile has to wait for it.
SHUTDOWN_GRACE = 5


class Lifetime:
    """When the program may end, and whether a window is on its way.

    The program ends when its window has been closed for a few seconds. If the user opens CheapTrader again
    just then, the second start finds this copy still running and opens a window on it. Two things must hold:
    this copy must not end while that window is opening (it takes a second or two before the window has the
    page's name, and the program looks for its window by that name), and a window must never be opened on a copy
    that is already ending. So a second start announces its window (``expect_window``) and is refused if this copy
    has decided to end; the copy decides to end (``may_end``) only when no window is announced. Both happen
    under one lock, so whichever comes first wins and the other knows.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._expected_until = 0.0
        self._ending = False

    def expect_window(self, within: float = EXPECT_WINDOW_FOR) -> bool:
        """A window is about to open on this copy. False: the copy is ending, so no window may."""
        with self._lock:
            if self._ending:
                return False
            self._expected_until = max(self._expected_until, self._clock() + within)
            return True

    def expecting(self) -> bool:
        with self._lock:
            return self._clock() < self._expected_until

    def may_end(self) -> bool:
        """The window has been closed for good, as far as this copy can tell. True: it ends now, and from here on
        refuses every window. False: a window has been announced, so it goes on."""
        with self._lock:
            if self._clock() < self._expected_until:
                return False
            self._ending = True
            return True

    def end(self) -> None:
        """It ends whatever is expected (Quit, an update, the server stopped): no window may open on it any more."""
        with self._lock:
            self._ending = True

    @property
    def ending(self) -> bool:
        with self._lock:
            return self._ending


lifetime = Lifetime()
#: The processes of the windows this program has opened: they end with it (see ``app/windowjob.py``).
window_job = WindowJob()


def wait_until_closed(
    port: int,
    alive,
    *,
    shown=app_window_open,
    expecting=lambda: False,
    end=lambda: True,
    clock=time.monotonic,
    sleep=time.sleep,
    poll: float = 0.5,
) -> None:
    """Return when the app's window has been closed (or the server has ended on its own).

    The window is looked for on the desktop rather than waited for as a process: Edge may hand the
    window to a browser that is already running and exit at once, which says nothing about whether
    the window is still open. A window that a second start has announced (``expecting``) counts as shown until
    it is: it has no name yet when it opens. ``end`` asks whether the program may end now; it says no when such a
    window was announced a moment ago (see ``Lifetime``).
    """
    began = clock()
    seen = False
    gone: float | None = None
    while alive():
        sleep(poll)
        now = clock()
        if shown(port) or expecting():
            seen, gone = True, None
        elif seen:
            gone = now if gone is None else gone
            if now - gone >= CLOSE_GRACE:
                if end():
                    logger.info("the window was closed")
                    return
                gone = None  # a window was announced just now: wait for it
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


LOCK_NAME = "Local\\CheapTrader.singleton"
_singleton = None  # the handle must live as long as the program does


def acquire_singleton(name: str = LOCK_NAME) -> bool:
    """Take the lock that says "this is the program": True when this process now holds it, False when another copy does.

    The first copy owns a named mutex; a second start finds it taken. That is how a double click while the first
    copy is still coming up (it can take ten seconds, a minute the very first time) does not start a second server.

    A try that fails lets go of its handle at once. A named object lives for as long as anyone holds it, so a start
    that waited for the other copy to end while holding a handle would keep the lock alive after that copy was gone:
    every later start would find it "taken" and the program could not be opened until that wait was over.
    """
    global _singleton
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            kernel32.CloseHandle(handle)
        return False
    _singleton = handle
    return True


def ask_for_window(port: int, *, open_one: bool = True, unless_shown: bool = False) -> str:
    """Ask the copy of the program on ``port`` for a window onto itself.

    ``"handled"``: it agreed and opened the window itself (a window that the copy opens belongs to its job, so it ends
    with it); ``"stay"``: it agreed to stay for a window that this start opens (a copy too old to open one itself);
    ``"refused"``: it is ending, or it does not answer, so no window may be opened on it.
    ``open_one`` false asks only for it to stay; ``unless_shown`` asks it to open none when one is already showing.
    """
    body = json.dumps({"open": open_one, "unless_shown": unless_shown}).encode()
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/app/window", data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            answer = json.loads(response.read())
    except (OSError, ValueError, urllib.error.URLError):
        return "refused"
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        return "refused"
    return "handled" if answer.get("handled") is True else "stay"


def show_window(url: str) -> None:
    """A window on the program, opened by this process: its own (Edge or Chrome), else the default browser. Only for a
    running copy that cannot open one itself; a window opened here is not tied to that copy."""
    if open_window(url) is None:
        webbrowser.open(url)


def update_running() -> bool:
    """Is an update being installed? The installer cannot replace a program that is running, so none may be started."""
    from app import updater

    return updater.update_running(paths.data_dir() / updater.UPDATES_FOLDER)


def wait_for_update(*, updating=None, clock=time.monotonic, sleep=time.sleep, patience: float | None = None) -> bool:
    """While an update is being installed nothing is started: the installer replaces the program's file, which a running
    program holds, and it gives up when it cannot (that is what a user who opened CheapTrader again, because nothing was
    showing, did to the update). The script that installs it opens the program when it is done. True: this start waited.
    A start that waited only opens a window when none is showing: the script's start and the user's would otherwise
    open one each, next to the one the update left open."""
    updating = updating or update_running
    patience = START_TIMEOUT if patience is None else patience
    began = clock()
    waited = False
    while updating() and clock() - began < patience:
        waited = True
        sleep(0.5)
    return waited


def lead_or_join(
    argv: list[str],
    *,
    acquire=None,
    port_of=None,
    alive=None,
    ask=None,
    show=None,
    shown=None,
    warn=None,
    unless_shown: bool = False,
    clock=time.monotonic,
    sleep=time.sleep,
    patience: float | None = None,
) -> bool:
    """Is this start the program? True when it has taken the lock and goes on to be it.

    False when another copy has it and this start has dealt with that: the other copy was up and agreed to stay, and a
    window has been opened on it; or it never came up in ``patience`` seconds (the user is told). A copy that is ending is waited for:
    when it is gone the lock is free and this start takes it, so the user who closed the program and opened it again
    a moment later gets a program, not a window on one that has just stopped (and not a start that does nothing).

    ``unless_shown``: the window is only opened when none is showing (a start of an update, or one that waited for it).
    """
    acquire = acquire or acquire_singleton
    port_of = port_of or running_port
    alive = alive or health
    ask = ask or ask_for_window
    show = show or show_window
    shown = shown or app_window_open
    warn = warn or (lambda text: message(text, error=True))
    patience = START_TIMEOUT if patience is None else patience
    wants_window = "--no-window" not in argv
    unless_shown = unless_shown or "--reconnect" in argv
    began = clock()
    while not acquire():
        port = port_of()
        if alive(port) is not None:
            answer = ask(port, open_one=wants_window, unless_shown=unless_shown)
            if answer != "refused":
                if answer == "stay" and wants_window and not (unless_shown and shown(port)):
                    show(f"http://{HOST}:{port}/")
                return False
        if clock() - began > patience:
            if "--no-window" not in argv:
                warn(
                    "CheapTrader is already open but does not answer.\n\nIf it does not come up in a moment, end "
                    "CheapTrader in Task Manager and open it again."
                )
            return False
        sleep(0.3)
    return True


def answer_window_request(life: Lifetime, *, open_one: bool, unless_shown: bool, showing: bool, open_now) -> dict:
    """What the running copy says to a second start that wants a window onto it (``POST /api/app/window``).

    ``ok`` false: this copy is ending, no window may be opened on it. Otherwise the copy stays for the window (see
    ``Lifetime``) and, when asked to, opens it itself with ``open_now``: its windows are then processes of its job and end
    with it. ``showing`` says whether a window is already showing (or has just been opened, and is still loading); with
    ``unless_shown`` the copy opens none then. ``handled`` tells the second start that it has nothing left to do.
    """
    if not life.expect_window():
        return {"ok": False}
    if not open_one:
        return {"ok": True}
    if not (unless_shown and showing):
        open_now()
    return {"ok": True, "handled": True}


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
    waited = wait_for_update()  # an update is being installed: this start comes after it
    if not lead_or_join(argv, unless_shown=waited):  # another copy has the lock: a window onto it, or nothing (and not a word in its log)
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

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_config=None, access_log=False, timeout_graceful_shutdown=SHUTDOWN_GRACE)
    )
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()

    from app.api import terminal_routes

    def quit_now() -> None:
        lifetime.end()  # no window may be opened on it from here on
        server.should_exit = True

    def hand_over_now() -> None:
        """An update closes the program, and its window stays open meanwhile: the new version finds it by itself."""
        window_job.release()
        quit_now()

    window_lock = threading.Lock()
    last_window = [float("-inf")]  # when this program last opened a window

    def open_here() -> None:
        """A window onto this program, started by this program: it is a process of its job."""
        last_window[0] = time.monotonic()

        def show() -> None:
            if open_window(url, window_job) is None:
                webbrowser.open(url)

        threading.Thread(target=show, name="open-window", daemon=True).start()

    def window_asked(open_one: bool = False, unless_shown: bool = False) -> dict:
        with window_lock:  # two starts that ask at once (an update's and a user's) are told about each other's window
            showing = app_window_open(port) or time.monotonic() - last_window[0] < EXPECT_WINDOW_FOR
            return answer_window_request(
                lifetime, open_one=open_one, unless_shown=unless_shown, showing=showing, open_now=open_here
            )

    # the page's Quit button (MetaTrader menu) stops the program, and its window with it; a second start asks for its window
    terminal_routes.quit_hook = quit_now
    terminal_routes.update_hook = hand_over_now
    terminal_routes.window_closer = lambda: close_windows(port)
    terminal_routes.window_hook = window_asked

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

    after_update = "--reconnect" in argv or waited
    if after_update and window_returns(port, within=8.0 if "--reconnect" in argv else 1.5):
        # Started by an update (see app/updater.py), or by a user while it was installed: the window of the version that
        # was replaced is still open, and its page reloads by itself as soon as this server answers. Opening another
        # would make two.
        logger.info("the window of the previous version is still open and reconnects by itself")
        wait_until_closed(port, thread.is_alive, expecting=lifetime.expecting, end=lifetime.may_end)
        return stop(server, thread, port)

    with window_lock:
        last_window[0] = time.monotonic()
        opened = open_window(url, window_job)
    if opened is None:
        # No Edge or Chrome: the default browser. There is no window of ours to watch then, so the
        # program runs until the Quit button in the page (or Task Manager) ends it.
        webbrowser.open(url)
        thread.join()
        return 0
    wait_until_closed(port, thread.is_alive, expecting=lifetime.expecting, end=lifetime.may_end)
    return stop(server, thread, port)


def stop(server, thread: threading.Thread, port: int) -> int:
    if not thread.is_alive() and not lifetime.ending:
        # The server ended by itself, which nobody asked for. A window left open would show a page that nothing
        # serves ("connection refused" once it is reloaded): close it, and say what happened.
        logger.error("the server stopped by itself")
        close_windows(port)
        message(f"CheapTrader stopped unexpectedly.\n\nThe details are in\n{paths.logs_dir() / 'cheaptrader.log'}", error=True)
        return 1
    logger.info("stopping")
    lifetime.end()
    server.should_exit = True
    thread.join(timeout=40)
    # The program ends in the way it means to: what is left of the browser stays (it may show a page the user opened from
    # here and is using). Only a program that is ended by force takes its windows with it: the job does that.
    window_job.end()
    return 0
