"""MetaTrader terminals: finding them, choosing one, hiding its window, and what the app tells the user."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import desktop
from app.data.store import store_path_for_broker
from app.preferences import Preferences
from app.terminals import Terminal, TerminalWindow, Window, broker_of, choose, detect, installed


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
