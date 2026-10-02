"""The MetaTrader 5 terminals on this PC.

* which are installed (one per broker, each broker ships its own: ``C:\\Program Files\\Fusion Markets
  MetaTrader 5``, ``...\\IC Markets MetaTrader 5``) and which are running;
* which one the app should talk to when the settings do not say (``choose``);
* showing and hiding the terminal's window, keeping it hidden if the user wants that, and closing a
  hidden terminal together with the app (it would otherwise run on, out of sight).

Everything that touches Windows goes through ``Win32`` (ctypes only, no extra package), so the
rest can be tested with a stand-in.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app.preferences import Preferences, preferences

logger = logging.getLogger(__name__)

EXE = "terminal64.exe"
WINDOW_CLASS = "MetaQuotes::MetaTrader"  # the main window's class: "MetaQuotes::MetaTrader::5.00"
#: How long a terminal that was asked to close is given before it is shown again (see TerminalWindow.close_hidden).
CLOSE_WAIT = 10.0


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    visible: bool
    minimized: bool


class Windows(Protocol):
    def processes(self, image: str) -> list[tuple[int, str]]:
        """``(pid, full path)`` of every running process whose program is called ``image``."""

    def main_windows(self, pid: int) -> list[Window]:
        """The terminal's own top-level windows (not its tooltips, menus and helper windows)."""

    def hide(self, hwnd: int) -> None: ...

    def show(self, hwnd: int) -> None: ...

    def close(self, hwnd: int) -> None:
        """Ask the window to close, as its own close button does (the program may still say no)."""


# the Windows-only part: everything above is plain Python and is tested with a stand-in
class Win32:
    """The Windows calls, by ctypes. Does nothing (and finds nothing) elsewhere."""

    def __init__(self) -> None:
        self._ok = os.name == "nt"
        if self._ok:
            from ctypes import wintypes

            self._wt = wintypes
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._u32 = ctypes.WinDLL("user32", use_last_error=True)
            self._k32.OpenProcess.restype = wintypes.HANDLE
            self._k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            self._u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            self._u32.IsWindowVisible.argtypes = [wintypes.HWND]
            self._u32.IsIconic.argtypes = [wintypes.HWND]
            self._u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            self._u32.GetWindow.restype = wintypes.HWND
            self._u32.SetForegroundWindow.argtypes = [wintypes.HWND]
            self._u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self._u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self._u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            self._u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self._u32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
            self._u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            self._u32.PostMessageW.restype = wintypes.BOOL

    def processes(self, image: str) -> list[tuple[int, str]]:
        if not self._ok:
            return []
        wt = self._wt

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
                ("szExeFile", wt.WCHAR * 260),
            ]

        out: list[tuple[int, str]] = []
        snapshot = self._k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        more = self._k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == image.lower():
                path = self._image_path(entry.th32ProcessID)
                if path:
                    out.append((int(entry.th32ProcessID), path))
            more = self._k32.Process32NextW(snapshot, ctypes.byref(entry))
        self._k32.CloseHandle(snapshot)
        return out

    def _image_path(self, pid: int) -> str:
        handle = self._k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = self._wt.DWORD(1024)
            self._k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            return buffer.value
        finally:
            self._k32.CloseHandle(handle)

    def main_windows(self, pid: int) -> list[Window]:
        if not self._ok:
            return []
        wt, u32 = self._wt, self._u32
        found: list[Window] = []

        def visit(hwnd, _lparam) -> bool:
            owner_pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if owner_pid.value != pid or u32.GetWindow(hwnd, 4):  # GW_OWNER: dialogs belong to the main one
                return True
            name = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, name, 256)
            if name.value.startswith(WINDOW_CLASS):
                length = u32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(hwnd, title, length + 1)
                found.append(Window(int(hwnd or 0), title.value, bool(u32.IsWindowVisible(hwnd)), bool(u32.IsIconic(hwnd))))
            return True

        callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(visit)
        u32.EnumWindows(callback, 0)
        return found

    def hide(self, hwnd: int) -> None:
        if self._ok:
            self._u32.ShowWindow(hwnd, 0)  # SW_HIDE

    def show(self, hwnd: int) -> None:
        if self._ok:
            # SW_RESTORE brings a minimised window back; on any other it would un-maximise it
            self._u32.ShowWindow(hwnd, 9 if self._u32.IsIconic(hwnd) else 5)
            self._u32.ShowWindow(hwnd, 5)  # SW_SHOW (a hidden window that was minimised is still iconic until now)
            self._u32.SetForegroundWindow(hwnd)

    def close(self, hwnd: int) -> None:
        if self._ok:
            self._u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: the same as the window's close button


# -- which terminals there are ------------------------------------------------------------------
@dataclass(frozen=True)
class Terminal:
    exe: str  # full path of terminal64.exe
    folder: str  # its install folder
    name: str  # the folder's name: "Fusion Markets MetaTrader 5"
    broker: str  # "Fusion Markets"
    running: bool
    pid: int | None
    last_used: float  # when the terminal last wrote to its data folder (0: unknown)

    def as_dict(self) -> dict:
        return asdict(self)


def broker_of(folder_name: str) -> str:
    """The broker's name out of the name of the folder its terminal is installed in."""
    cleaned = re.sub(r"(?i)\bmeta\s*trader\s*5?\b|\bmt5\b|\bterminal\b", " ", folder_name)
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned).strip()
    return cleaned or folder_name


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def installed(env: dict[str, str] | None = None) -> list[tuple[str, Path | None]]:
    """``(terminal64.exe, its data folder or None)`` for every terminal installed on this PC.

    Found in the usual install places (one folder deep) and through MetaTrader's own list:
    every terminal that has ever run has a data folder in ``%APPDATA%\\MetaQuotes\\Terminal`` whose
    ``origin.txt`` says where the program is.
    """
    env = dict(os.environ) if env is None else env
    exes: dict[str, tuple[str, Path | None]] = {}

    def add(exe: Path, data: Path | None = None) -> None:
        if exe.is_file():
            key = os.path.normcase(str(exe))
            if key not in exes or data is not None:
                exes[key] = (str(exe), data)

    for root_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = env.get(root_name)
        if root and Path(root).is_dir():
            for child in Path(root).iterdir():
                if child.is_dir() and "meta" in child.name.lower():
                    add(child / EXE)
    local = env.get("LOCALAPPDATA")
    if local and (Path(local) / "Programs").is_dir():
        for child in (Path(local) / "Programs").iterdir():
            if child.is_dir() and "meta" in child.name.lower():
                add(child / EXE)
    appdata = env.get("APPDATA")
    if appdata and (Path(appdata) / "MetaQuotes" / "Terminal").is_dir():
        for data in (Path(appdata) / "MetaQuotes" / "Terminal").iterdir():
            origin = data / "origin.txt"
            if origin.is_file():
                raw = origin.read_bytes()
                for encoding in ("utf-16", "utf-8", "mbcs"):
                    try:
                        text = raw.decode(encoding).strip().strip("\ufeff")
                        break
                    except (UnicodeError, LookupError):
                        text = ""
                if text:
                    add(Path(text) / EXE, data)
    return list(exes.values())


def _last_used(data: Path | None, exe: str) -> float:
    candidates = []
    if data is not None:
        candidates += [data / "logs", data / "config"]
    best = 0.0
    for path in candidates:
        with contextlib.suppress(OSError):
            best = max(best, path.stat().st_mtime)
    return best


def detect(win: Windows | None = None, env: dict[str, str] | None = None) -> list[Terminal]:
    """Every terminal installed or running, the running ones marked."""
    win = win or Win32()
    running = {os.path.normcase(os.path.normpath(path)): (pid, path) for pid, path in win.processes(EXE)}
    found: dict[str, Terminal] = {}
    for exe, data in installed(env):
        key = os.path.normcase(os.path.normpath(exe))
        folder = str(Path(exe).parent)
        found[key] = Terminal(exe, folder, Path(folder).name, broker_of(Path(folder).name),
                              key in running, running[key][0] if key in running else None, _last_used(data, exe))
    for key, (pid, exe) in running.items():  # a portable install that nobody listed
        if key not in found:
            folder = str(Path(exe).parent)
            found[key] = Terminal(exe, folder, Path(folder).name, broker_of(Path(folder).name), True, pid, 0.0)
    return sorted(found.values(), key=lambda t: (not t.running, -t.last_used, t.name.lower()))


def choose(
    terminals: list[Terminal],
    *,
    explicit: str | None = None,
    saved: str | None = None,
    server: str | None = None,
) -> str | None:
    """The terminal to talk to.

    1. the one the settings name (``CT_MT5_PATH``);
    2. the one the user picked in the app, if it is still there;
    3. a running one (with several running: the one for the broker ``server`` names, else the newest);
    4. the one used most recently;
    5. none: MetaTrader's own package then looks for one by itself.
    """
    if explicit:
        return explicit
    if saved and Path(saved).is_file():
        return saved
    running = [t for t in terminals if t.running]
    pool = running or terminals
    if not pool:
        return None
    if server and len(pool) > 1:
        wanted = re.sub(r"[^a-z0-9]", "", server.lower())
        matching = [t for t in pool if re.sub(r"[^a-z0-9]", "", t.broker.lower()) in wanted]
        pool = matching or pool
    if running:
        return max(pool, key=lambda t: t.pid or 0).exe
    return max(pool, key=lambda t: t.last_used).exe


# -- the terminal's window --------------------------------------------------------------------
class TerminalWindow:
    """Shows and hides the connected terminal's window, and keeps it hidden if asked to.

    The terminal keeps running either way; hiding only takes its window (and its taskbar
    button) off the screen. The choice is remembered in ``preferences.json``. A window that
    appears later (the terminal was started a moment after the app, or restarted) is hidden
    too, once; one the user brings back by hand is left alone.

    A hidden terminal has no window to close and no taskbar button to find, so when the app
    ends it is closed with it (``close_hidden``); one whose window is showing is left running.
    """

    def __init__(self, win: Windows | None = None, prefs: Preferences | None = None, interval: float = 2.0) -> None:
        self._win = win or Win32()
        self._prefs = prefs or preferences
        self._interval = interval
        self._exe: str | None = None
        self._seen: set[int] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def use(self, exe: str | None) -> None:
        """The program of the terminal the app is connected to."""
        if exe != self._exe:
            self._exe = exe
            self._seen = set()

    def _windows(self) -> list[Window]:
        if not self._exe:
            return []
        out: list[Window] = []
        for pid, path in self._win.processes(EXE):
            if _same(path, self._exe):
                out += self._win.main_windows(pid)
        return out

    def state(self) -> dict:
        windows = self._windows()
        visible = [w for w in windows if w.visible]
        return {
            "found": bool(windows),
            "hidden": (not visible) if windows else None,
            "minimized": bool(visible) and all(w.minimized for w in visible),
        }

    def set_hidden(self, hidden: bool) -> dict:
        self._prefs.set("hide_terminal", bool(hidden))
        for w in self._windows():
            self._seen.add(w.hwnd)
            if hidden and w.visible:
                self._win.hide(w.hwnd)
            elif not hidden:
                self._win.show(w.hwnd)  # also brings a window that is open but behind or minimised to the front
        return self.state()

    def keep(self) -> None:
        """One look: hide the windows that have appeared since the last one, if the user wants them hidden."""
        wanted = bool(self._prefs.get("hide_terminal"))
        for w in self._windows():
            if w.hwnd in self._seen:
                continue
            self._seen.add(w.hwnd)
            if wanted and w.visible:
                self._win.hide(w.hwnd)
                logger.info("hid the MetaTrader window %r", w.title)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="terminal-window", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _running(self) -> bool:
        return any(_same(path, self._exe or "") for _pid, path in self._win.processes(EXE))

    def close_hidden(self, wait: float = CLOSE_WAIT, *, clock=time.monotonic, sleep=time.sleep) -> str:
        """The app is ending: close the terminal it is connected to if its window is hidden.

        Only a terminal the user has had hidden (the preference is on and no window of it shows) is
        touched; one that is open on the screen, minimised or not, is the user's and stays. The terminal
        is asked to close the way its own close button does and given ``wait`` seconds. If it is still
        there then (a dialog may be waiting for an answer in a window nobody can see) its window is shown
        again so that the user can deal with it. Nothing is ever killed. Returns what happened:
        ``"closed"``, ``"shown"`` (it did not close), or why nothing was done.
        """
        if not self._exe:
            return "no terminal is connected"
        if not self._prefs.get("hide_terminal"):
            return "not hidden by the user"
        windows = self._windows()
        if not windows:
            return "no terminal window"
        if any(w.visible for w in windows):
            return "the window is showing"
        for w in windows:
            self._win.close(w.hwnd)
        deadline = clock() + wait
        while True:
            if not self._running():
                logger.info("closed the hidden MetaTrader terminal together with the app")
                return "closed"
            if clock() >= deadline:
                break
            sleep(0.25)
        for w in self._windows():
            self._win.show(w.hwnd)
        logger.warning("the hidden MetaTrader terminal did not close; its window is shown again")
        return "shown"

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.keep()
            except Exception:  # noqa: BLE001 - a hiccup in the window list must not end the keeper
                logger.debug("terminal window check failed", exc_info=True)
