"""MetaTrader terminals: finding them, choosing one, hiding its window, and what the app tells the user."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import desktop
from app.config import Settings
from app.data.store import store_path_for_broker
from app.preferences import Preferences
from app.state import AppState
from app.terminals import Terminal, TerminalWindow, Win32, Window, broker_of, choose, detect, installed


# -- names -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("folder", "broker"),
    [
        ("Fusion Markets MetaTrader 5", "Fusion Markets"),
        ("IC Markets MetaTrader 5", "IC Markets"),
        ("Pepperstone MetaTrader 5 Terminal", "Pepperstone"),
        ("MT5 Exness", "Exness"),
        ("MetaTrader 5", "MetaTrader 5"),  # nothing left: the folder's own name
    ],
)
def test_the_broker_is_read_from_the_install_folder(folder: str, broker: str) -> None:
    assert broker_of(folder) == broker


# -- finding terminals ---------------------------------------------------------------------------
class FakeWindows:
    """Stands in for the Windows calls: some processes, each with windows."""

    def __init__(self, running: dict[int, str] | None = None, windows: dict[int, list[Window]] | None = None) -> None:
        self.running = running or {}
        self.windows = windows or {}
        self.log: list[tuple[str, int]] = []
        self.refuses = False  # a terminal that does not close when asked (a dialog is waiting for an answer)

    def processes(self, image: str) -> list[tuple[int, str]]:
        return list(self.running.items())

    def main_windows(self, pid: int) -> list[Window]:
        return list(self.windows.get(pid, []))

    def _set(self, hwnd: int, **changes) -> None:
        for pid, ws in self.windows.items():
            self.windows[pid] = [Window(**{**w.__dict__, **changes}) if w.hwnd == hwnd else w for w in ws]

    def hide(self, hwnd: int) -> None:
        self.log.append(("hide", hwnd))
        self._set(hwnd, visible=False)

    def show(self, hwnd: int) -> None:
        self.log.append(("show", hwnd))
        self._set(hwnd, visible=True, minimized=False)

    def close(self, hwnd: int) -> None:
        self.log.append(("close", hwnd))
        if self.refuses:
            return
        for pid, ws in list(self.windows.items()):
            if any(w.hwnd == hwnd for w in ws):  # the terminal ends: its windows and its process are gone
                del self.windows[pid]
                self.running.pop(pid, None)


def make_terminal(root: Path, folder: str, data_hash: str | None = None, appdata: Path | None = None) -> str:
    exe = root / folder / "terminal64.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    if data_hash and appdata:
        data = appdata / "MetaQuotes" / "Terminal" / data_hash
        (data / "logs").mkdir(parents=True)
        (data / "origin.txt").write_bytes(("\ufeff" + str(exe.parent)).encode("utf-16-le"))
    return str(exe)


@pytest.fixture
def pc(tmp_path):
    """A PC with two brokers' terminals in Program Files and a third one somewhere else (known to MetaTrader)."""
    program_files = tmp_path / "Program Files"
    appdata = tmp_path / "AppData"
    elsewhere = tmp_path / "Trading"
    a = make_terminal(program_files, "Fusion Markets MetaTrader 5", "AAAA", appdata)
    b = make_terminal(program_files, "IC Markets MetaTrader 5")
    c = make_terminal(elsewhere, "Pepperstone MT5", "CCCC", appdata)
    (program_files / "Notepad").mkdir()  # not a terminal
    env = {"ProgramFiles": str(program_files), "APPDATA": str(appdata), "LOCALAPPDATA": str(tmp_path / "Local")}
    return env, a, b, c


def test_installed_terminals_are_found_in_program_files_and_through_metatraders_own_list(pc) -> None:
    env, a, b, c = pc
    found = {os.path.normcase(exe) for exe, _ in installed(env)}
    assert found == {os.path.normcase(x) for x in (a, b, c)}


def test_detect_marks_the_running_ones_and_adds_a_portable_install_nobody_listed(pc, tmp_path) -> None:
    env, a, b, c = pc
    portable = str(tmp_path / "usb" / "terminal64.exe")
    win = FakeWindows(running={101: a, 202: portable})
    by_name = {t.name: t for t in detect(win, env)}
    assert by_name["Fusion Markets MetaTrader 5"].running and by_name["Fusion Markets MetaTrader 5"].pid == 101
    assert not by_name["IC Markets MetaTrader 5"].running
    assert by_name["usb"].running and by_name["usb"].broker == "usb"
    assert detect(win, env)[0].running  # running ones come first


# -- choosing --------------------------------------------------------------------------------------
def terminal(name: str, *, running: bool = False, pid: int | None = None, last_used: float = 0.0, tmp: Path | None = None) -> Terminal:
    return Terminal(f"C:\\{name}\\terminal64.exe", f"C:\\{name}", name, broker_of(name), running, pid, last_used)


def test_the_settings_win_then_the_users_pick(tmp_path) -> None:
    pick = tmp_path / "terminal64.exe"
    pick.write_bytes(b"")
    many = [terminal("A MetaTrader 5", running=True, pid=5), terminal("B MetaTrader 5")]
    assert choose(many, explicit="X:\\mine\\terminal64.exe") == "X:\\mine\\terminal64.exe"
    assert choose(many, saved=str(pick)) == str(pick)
    assert choose(many, saved=str(tmp_path / "gone.exe")) == many[0].exe  # a pick that is no longer there is ignored


def test_a_running_terminal_beats_an_installed_one_and_the_server_picks_between_running_ones() -> None:
    fusion = terminal("Fusion Markets MetaTrader 5", running=True, pid=10)
    ic = terminal("IC Markets MetaTrader 5", running=True, pid=99)
    idle = terminal("Pepperstone MetaTrader 5", last_used=9e9)
    assert choose([idle, fusion]) == fusion.exe
    assert choose([fusion, ic]) == ic.exe  # both run: the newer one
    assert choose([fusion, ic], server="FusionMarkets-Demo") == fusion.exe  # unless the settings name a broker


def test_with_nothing_running_the_one_used_last_is_chosen() -> None:
    old = terminal("Old MetaTrader 5", last_used=100)
    new = terminal("New MetaTrader 5", last_used=200)
    assert choose([old, new]) == new.exe
    assert choose([]) is None  # nothing found: the package looks by itself


# -- the window ---------------------------------------------------------------------------------------
@pytest.fixture
def prefs(tmp_path) -> Preferences:
    return Preferences(tmp_path / "preferences.json")


def window_world(visible: bool = True, minimized: bool = False):
    exe = "C:\\Program Files\\Fusion Markets MetaTrader 5\\terminal64.exe"
    win = FakeWindows(running={7: exe}, windows={7: [Window(1000, "12345678 - Fusion-Demo", visible, minimized)]})
    return exe, win


def test_hiding_takes_the_window_off_the_screen_and_is_remembered(prefs) -> None:
    exe, win = window_world(minimized=True)
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    assert keeper.state() == {"found": True, "hidden": False, "minimized": True}
    assert keeper.set_hidden(True)["hidden"] is True
    assert win.log == [("hide", 1000)]
    assert prefs.get("hide_terminal") is True
    assert Preferences(prefs.path).get("hide_terminal") is True  # read back from the file: it survives a restart
    assert keeper.set_hidden(False)["hidden"] is False
    assert win.log[-1] == ("show", 1000) and prefs.get("hide_terminal") is False


def test_a_window_that_appears_later_is_hidden_once_if_the_user_wants_that(prefs) -> None:
    exe, win = window_world()
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    keeper.keep()
    assert win.log == []  # not asked to hide: nothing happens
    prefs.set("hide_terminal", True)
    win.windows[7].append(Window(2000, "new window", True, False))
    keeper.keep()
    assert win.log == [("hide", 2000)]  # the new one only; 1000 was already looked at
    win._set(2000, visible=True)  # the user brings it back by hand
    keeper.keep()
    assert win.log == [("hide", 2000)]  # and it is left alone


def test_the_terminal_that_is_not_connected_is_not_touched(prefs) -> None:
    exe, win = window_world()
    win.running[8] = "D:\\Other MetaTrader 5\\terminal64.exe"
    win.windows[8] = [Window(3000, "other", True, False)]
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    keeper.set_hidden(True)
    assert win.log == [("hide", 1000)]


def test_without_a_window_the_choice_is_still_remembered(prefs) -> None:
    keeper = TerminalWindow(FakeWindows(), prefs)
    keeper.use("C:\\nowhere\\terminal64.exe")
    assert keeper.state() == {"found": False, "hidden": None, "minimized": False}
    keeper.set_hidden(True)
    assert prefs.get("hide_terminal") is True


# -- the app ends: a hidden terminal ends with it --------------------------------------------------------------
def hidden_terminal(prefs: Preferences, *, wanted: bool = True, **world):
    """A connected terminal whose window the user had the app hide."""
    exe, win = window_world(visible=False, **world)
    prefs.set("hide_terminal", wanted)
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    return keeper, win


def no_wait(_seconds: float) -> None:
    """Instead of sleeping: the tests that close a terminal never wait for real."""


def test_a_hidden_terminal_is_closed_with_the_app(prefs) -> None:
    exe, win = window_world()
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    keeper.set_hidden(True)  # the user's switch
    assert keeper.close_hidden(sleep=no_wait) == "closed"
    assert win.log == [("hide", 1000), ("close", 1000)]  # it was asked, the way its own close button asks
    assert win.running == {}  # and it is gone, not left running out of sight
    assert prefs.get("hide_terminal") is True  # the choice stays for the next start


def test_a_terminal_that_is_showing_is_left_running(prefs) -> None:
    exe, win = window_world(visible=True)
    prefs.set("hide_terminal", True)  # the user wants it hidden but has it on the screen now
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    assert keeper.close_hidden(sleep=no_wait) == "the window is showing"
    assert win.log == [] and win.running  # asked nothing, closed nothing


def test_a_minimised_terminal_is_on_the_screen_and_stays(prefs) -> None:
    exe, win = window_world(visible=True, minimized=True)  # it has a taskbar button: the user can find it
    prefs.set("hide_terminal", True)
    keeper = TerminalWindow(win, prefs)
    keeper.use(exe)
    assert keeper.close_hidden(sleep=no_wait) == "the window is showing"
    assert win.log == []


def test_a_terminal_the_user_did_not_have_hidden_is_not_closed(prefs) -> None:
    """Hidden by something else, or the switch is off: it is not the app's to close."""
    keeper, win = hidden_terminal(prefs, wanted=False)
    assert keeper.close_hidden(sleep=no_wait) == "not hidden by the user"
    assert win.log == [] and win.running


def test_nothing_is_closed_before_a_terminal_is_chosen(prefs) -> None:
    exe, win = window_world(visible=False)
    prefs.set("hide_terminal", True)
    keeper = TerminalWindow(win, prefs)  # the mock broker: no terminal was ever connected
    assert keeper.close_hidden(sleep=no_wait) == "no terminal is connected"
    assert win.log == [] and win.running


def test_a_terminal_without_a_window_is_not_asked_anything(prefs) -> None:
    keeper, win = hidden_terminal(prefs)
    win.windows.clear()  # still starting, or its window has not appeared
    assert keeper.close_hidden(sleep=no_wait) == "no terminal window"
    assert win.log == [] and win.running


def test_only_the_connected_terminal_is_closed(prefs) -> None:
    keeper, win = hidden_terminal(prefs)
    win.running[8] = "D:\\Other MetaTrader 5\\terminal64.exe"  # the user's other broker, hidden or not
    win.windows[8] = [Window(3000, "other", False, False)]
    assert keeper.close_hidden(sleep=no_wait) == "closed"
    assert win.log == [("close", 1000)]
    assert list(win.running) == [8]


def test_a_terminal_with_one_window_showing_is_not_closed_at_all(prefs) -> None:
    keeper, win = hidden_terminal(prefs)
    win.windows[7].append(Window(2000, "a second window", True, False))
    assert keeper.close_hidden(sleep=no_wait) == "the window is showing"
    assert win.log == [] and win.running


def test_every_window_of_a_hidden_terminal_is_asked_to_close(prefs) -> None:
    keeper, win = hidden_terminal(prefs)
    win.windows[7].append(Window(2000, "a second window", False, False))
    assert keeper.close_hidden(sleep=no_wait) == "closed"
    assert win.log == [("close", 1000), ("close", 2000)]


def test_a_terminal_that_takes_a_moment_to_close_is_waited_for(prefs) -> None:
    keeper, win = hidden_terminal(prefs)
    win.refuses = True  # nothing happens at once: the terminal is saving its charts
    ticks: list[float] = []

    def sleep(seconds: float) -> None:
        ticks.append(seconds)
        if len(ticks) == 3:
            win.running.clear()  # and then it is done

    assert keeper.close_hidden(wait=10, clock=lambda: 0.25 * len(ticks), sleep=sleep) == "closed"
    assert ("show", 1000) not in win.log  # it was not brought back while it was still closing


def test_a_terminal_that_will_not_close_is_shown_again_and_never_killed(prefs, caplog) -> None:
    keeper, win = hidden_terminal(prefs)
    win.refuses = True  # a dialog is waiting for an answer in a window nobody can see
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with caplog.at_level(logging.WARNING, logger="app.terminals"):
        assert keeper.close_hidden(wait=5, clock=lambda: now[0], sleep=sleep) == "shown"
    assert win.log == [("close", 1000), ("show", 1000)]  # so the user can answer it
    assert win.running == {7: "C:\\Program Files\\Fusion Markets MetaTrader 5\\terminal64.exe"}  # still there: nothing was killed
    assert 5 <= now[0] < 6  # it waited what it was given, no longer
    assert "did not close" in caplog.text


# -- AppState.shutdown ----------------------------------------------------------------------------------------
class RecordingWindow:
    def __init__(self, order: list[str], fail: bool = False) -> None:
        self.order, self.fail = order, fail

    def stop(self) -> None:
        self.order.append("window keeper stopped")

    def close_hidden(self) -> str:
        self.order.append("terminal closed")
        if self.fail:
            raise RuntimeError("the window list could not be read")
        return "closed"


def started_state(monkeypatch: pytest.MonkeyPatch, window: RecordingWindow, order: list[str]) -> AppState:
    state = AppState(Settings(broker="mock"))
    state.startup()
    disconnect = state.broker.disconnect

    def disconnected() -> None:
        order.append("broker let go")
        disconnect()

    monkeypatch.setattr(state.broker, "disconnect", disconnected)
    state.terminal_window = window
    return state


def test_the_terminal_is_closed_after_the_app_has_let_go_of_it(monkeypatch) -> None:
    order: list[str] = []
    state = started_state(monkeypatch, RecordingWindow(order), order)
    state.shutdown()
    assert order == ["window keeper stopped", "broker let go", "terminal closed"]  # not while it is still being read from


def test_a_terminal_that_cannot_be_closed_does_not_stop_the_app_from_closing(monkeypatch, caplog) -> None:
    order: list[str] = []
    state = started_state(monkeypatch, RecordingWindow(order, fail=True), order)
    with caplog.at_level(logging.WARNING, logger="app.state"):
        state.shutdown()  # no exception
    assert order[-1] == "terminal closed"
    assert "could not close the hidden MetaTrader terminal" in caplog.text


# -- a real window (a stand-in program, never the user's own terminal) -------------------------------------------
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"

STAND_IN = """
using System;
using System.Runtime.InteropServices;

// Stands in for a MetaTrader terminal: a program called terminal64.exe with one top-level window of the
// terminal's window class. It closes when asked to (WM_CLOSE) unless it is started with "refuse".
class StandIn {
  delegate IntPtr WndProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  struct WNDCLASS {
    public uint style;
    public WndProc lpfnWndProc;
    public int cbClsExtra;
    public int cbWndExtra;
    public IntPtr hInstance;
    public IntPtr hIcon;
    public IntPtr hCursor;
    public IntPtr hbrBackground;
    public string lpszMenuName;
    public string lpszClassName;
  }

  [StructLayout(LayoutKind.Sequential)]
  struct MSG {
    public IntPtr hwnd;
    public uint message;
    public IntPtr wParam;
    public IntPtr lParam;
    public uint time;
    public int x;
    public int y;
  }

  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern ushort RegisterClassW(ref WNDCLASS c);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateWindowExW(uint exStyle, string cls, string title, uint style, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
  [DllImport("user32.dll")] static extern int GetMessageW(out MSG msg, IntPtr hwnd, uint min, uint max);
  [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG msg);
  [DllImport("user32.dll")] static extern IntPtr DispatchMessageW(ref MSG msg);
  [DllImport("user32.dll")] static extern IntPtr DefWindowProcW(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] static extern void PostQuitMessage(int code);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandleW(string name);

  static bool refuse;
  static WndProc proc;  // kept: the window class refers to it for as long as the program runs

  static IntPtr OnMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam) {
    if (msg == 0x0010 && refuse) return IntPtr.Zero;                // WM_CLOSE, ignored as when a dialog waits for an answer
    if (msg == 0x0002) { PostQuitMessage(0); return IntPtr.Zero; }  // WM_DESTROY: the window is gone, so is the program
    return DefWindowProcW(hwnd, msg, wParam, lParam);               // the default for WM_CLOSE destroys the window
  }

  static int Main(string[] args) {
    refuse = args.Length > 0 && args[0] == "refuse";
    proc = OnMessage;
    WNDCLASS cls = new WNDCLASS();
    cls.lpfnWndProc = proc;
    cls.hInstance = GetModuleHandleW(null);
    cls.lpszClassName = "MetaQuotes::MetaTrader::5.00";
    if (RegisterClassW(ref cls) == 0) return 2;
    IntPtr hwnd = CreateWindowExW(0, cls.lpszClassName, "12345678 - Stand-in", 0x00CF0000, 100, 100, 400, 300, IntPtr.Zero, IntPtr.Zero, cls.hInstance, IntPtr.Zero);
    if (hwnd == IntPtr.Zero) return 3;
    ShowWindow(hwnd, 4);  // SW_SHOWNOACTIVATE: it must not take the keyboard from whoever is working while the tests run
    MSG msg;
    while (GetMessageW(out msg, IntPtr.Zero, 0, 0) > 0) { TranslateMessage(ref msg); DispatchMessageW(ref msg); }
    return 0;
  }
}
"""


@pytest.fixture(scope="module")
def stand_in_terminal(tmp_path_factory) -> Path:
    """A program named terminal64.exe, in a folder of its own, with a window of the terminal's class."""
    if os.name != "nt" or not CSC.exists():
        pytest.skip("needs Windows and its C# compiler")
    folder = tmp_path_factory.mktemp("Stand-in MetaTrader 5")
    (folder / "stand_in.cs").write_text(STAND_IN, encoding="utf-8")
    exe = folder / "terminal64.exe"
    built = subprocess.run(
        [str(CSC), "/nologo", "/target:winexe", f"/out:{exe}", str(folder / "stand_in.cs")], capture_output=True, text=True, timeout=120
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return exe


def open_stand_in(exe: Path, *args: str) -> tuple[subprocess.Popen, Win32]:
    """Run the stand-in and wait until its window is on the screen."""
    process = subprocess.Popen([str(exe), *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = Win32()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"the stand-in terminal ended at once (exit code {process.returncode})")
            if any(w.visible for w in win.main_windows(process.pid)):
                return process, win
            time.sleep(0.1)
        pytest.fail("the stand-in terminal never showed its window")
    except BaseException:
        process.kill()
        raise


@pytest.mark.skipif(os.name != "nt", reason="Windows windows")
def test_a_real_hidden_window_is_closed_with_the_app(stand_in_terminal, prefs) -> None:
    process, win = open_stand_in(stand_in_terminal)
    try:
        keeper = TerminalWindow(win, prefs)
        keeper.use(str(stand_in_terminal))
        assert keeper.set_hidden(True)["hidden"] is True  # taken off the screen, the program runs on
        time.sleep(0.5)
        assert process.poll() is None
        assert keeper.close_hidden(wait=15) == "closed"
        assert process.wait(timeout=15) == 0  # it left the way a program does when its window is closed
    finally:
        if process.poll() is None:
            process.kill()


@pytest.mark.skipif(os.name != "nt", reason="Windows windows")
def test_a_real_window_that_stays_open_is_shown_again_and_the_program_is_not_killed(stand_in_terminal, prefs) -> None:
    process, win = open_stand_in(stand_in_terminal, "refuse")
    try:
        keeper = TerminalWindow(win, prefs)
        keeper.use(str(stand_in_terminal))
        keeper.set_hidden(True)
        assert keeper.close_hidden(wait=1.5) == "shown"
        assert process.poll() is None  # still running: it was asked, not forced
        assert keeper.state()["hidden"] is False  # and its window is back for the user to deal with
    finally:
        process.kill()
        process.wait(timeout=15)


@pytest.mark.skipif(os.name != "nt", reason="Windows windows")
def test_a_real_window_on_the_screen_is_left_alone(stand_in_terminal, prefs) -> None:
    process, win = open_stand_in(stand_in_terminal)
    try:
        prefs.set("hide_terminal", True)
        keeper = TerminalWindow(win, prefs)
        keeper.use(str(stand_in_terminal))
        assert keeper.close_hidden(wait=1) == "the window is showing"
        time.sleep(0.5)
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=15)


# -- one bar store per broker ---------------------------------------------------------------------------
def test_each_broker_gets_its_own_bar_store(tmp_path) -> None:
    base = tmp_path / "bars.db"
    assert store_path_for_broker(base, "Fusion Markets Pty Ltd") == base  # the first broker keeps the file
    assert (tmp_path / "bars.db.broker").read_text() == "Fusion Markets Pty Ltd"
    assert store_path_for_broker(base, "fusion markets pty ltd") == base
    other = store_path_for_broker(base, "IC Markets (SC) Ltd")
    assert other == tmp_path / "bars.ic-markets-sc-ltd.db" and other != base
    assert store_path_for_broker(base, "") == base  # nothing known: nothing changes


# -- the window of the program -----------------------------------------------------------------------------
def test_the_program_quits_a_few_seconds_after_its_window_is_closed() -> None:
    now = [0.0]
    states = iter([True, True, False, False, False, False, False, False, False, False, False, False])

    def shown(_port: int) -> bool:
        return next(states)

    def sleep(seconds: float) -> None:
        now[0] += seconds

    desktop.wait_until_closed(8765, lambda: True, shown=shown, clock=lambda: now[0], sleep=sleep)
    assert 4.0 <= now[0] - 1.0 <= 6.5  # window gone after ~1 s, then the 4 s grace


def test_a_page_reload_is_not_a_closed_window() -> None:
    now = [0.0]
    pattern = [True, False, False, True] + [True] * 4  # gone for a second, then back
    states = iter(pattern)
    calls = [0]

    def shown(_port: int) -> bool:
        calls[0] += 1
        return next(states)

    def alive() -> bool:
        return calls[0] < len(pattern)

    def sleep(seconds: float) -> None:
        now[0] += seconds

    desktop.wait_until_closed(8765, alive, shown=shown, clock=lambda: now[0], sleep=sleep)
    assert calls[0] == len(pattern)  # it kept going until the server ended; it did not decide the window was closed


def test_a_window_that_never_appears_does_not_end_the_program() -> None:
    now = [0.0]
    stop_after = [desktop.APPEAR_WITHIN + 10.0]

    def alive() -> bool:
        return now[0] < stop_after[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    desktop.wait_until_closed(8765, alive, shown=lambda _p: False, clock=lambda: now[0], sleep=sleep)
    assert now[0] >= stop_after[0]  # it waited for the server to end, instead of quitting on its own


def test_the_window_is_recognised_by_the_name_the_page_gives_itself(monkeypatch) -> None:
    monkeypatch.setattr(desktop, "visible_titles", lambda: ["Untitled - Notepad", "CheapTrader \u00b7 127.0.0.1:8765", "CheapTrader"])
    assert desktop.app_window_open(8765)
    assert not desktop.app_window_open(9000)
    monkeypatch.setattr(desktop, "visible_titles", lambda: ["CheapTrader - File Explorer"])
    assert not desktop.app_window_open(8765)  # a folder with the same name is not the app


# -- the API ---------------------------------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CT_BROKER", "mock")
    from app.api import terminal_routes
    from app.main import app

    monkeypatch.setattr(terminal_routes, "quit_hook", None)
    # the status lists the terminals found on the PC, also on the mock broker: never the real ones of this machine
    monkeypatch.setattr(terminal_routes, "_detected", lambda: [])
    with TestClient(app) as c:
        yield c


def test_the_mock_broker_has_no_terminal_to_hide(client) -> None:
    status = client.get("/api/terminal").json()
    assert status["broker"] == "mock" and status["terminals"] == []
    assert status["window"]["found"] is False and status["app"]["can_quit"] is False
    assert client.post("/api/terminal/window", json={"hidden": True}).status_code == 409


def test_only_a_terminal_that_exists_can_be_chosen(client, monkeypatch, tmp_path) -> None:
    from app.api import terminal_routes

    exe = str(tmp_path / "Fusion MetaTrader 5" / "terminal64.exe")
    monkeypatch.setattr(terminal_routes, "_detected", lambda: [Terminal(exe, str(Path(exe).parent), "Fusion MetaTrader 5", "Fusion", False, None, 0.0)])
    assert client.post("/api/terminal/choose", json={"path": "C:\\nowhere\\terminal64.exe"}).status_code == 400
    assert client.post("/api/terminal/choose", json={"path": exe}).json()["chosen"] == exe
    assert client.post("/api/terminal/choose", json={"path": None}).json()["chosen"] is None


def test_quit_works_only_where_the_program_can_stop_itself(client, monkeypatch) -> None:
    from app.api import terminal_routes

    assert client.post("/api/app/quit").status_code == 409
    stopped = []
    monkeypatch.setattr(terminal_routes, "quit_hook", lambda: stopped.append(True))
    assert client.post("/api/app/quit").json() == {"ok": True}
    assert stopped == [True]  # after the answer went out


def test_the_page_names_itself_with_its_address() -> None:
    index = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    assert "location.host" in index.read_text(encoding="utf-8")
    assert sys.platform  # (the title is set before the page\u2019s own code runs, so the window can be found at once)
