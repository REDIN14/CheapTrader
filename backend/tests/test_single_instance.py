"""Opening the program again a moment after it was closed: never a window on a copy that is ending, and never a start
that does nothing."""

from __future__ import annotations

import ctypes
import os
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import desktop
from app.api import terminal_routes
from app.desktop import Lifetime, acquire_singleton, answer_window_request, ask_for_window, lead_or_join, wait_until_closed


class Clock:
    """A clock that the tests move by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


# -- when the program may end ---------------------------------------------------------------------------------------
def test_a_window_that_is_announced_keeps_the_program_for_a_while() -> None:
    clock = Clock()
    life = Lifetime(clock)
    assert not life.expecting()
    assert life.expect_window(20)
    assert life.expecting() and not life.may_end()  # not while a window is on its way
    clock.now = 21
    assert not life.expecting() and life.may_end()  # it never came


def test_announcing_again_never_shortens_the_wait() -> None:
    clock = Clock()
    life = Lifetime(clock)
    life.expect_window(20)
    clock.now = 5
    life.expect_window(10)
    clock.now = 19
    assert life.expecting()


def test_once_the_program_has_decided_to_end_no_window_is_accepted() -> None:
    life = Lifetime(Clock())
    assert life.may_end()
    assert not life.expect_window()
    assert not life.expecting()
    assert life.may_end()  # and it stays decided


def test_quitting_ends_it_whatever_is_expected() -> None:
    life = Lifetime(Clock())
    life.expect_window()
    life.end()
    assert not life.expect_window()


def test_when_ending_and_announcing_meet_exactly_one_of_them_wins() -> None:
    for _ in range(300):
        life = Lifetime()  # the real clock
        outcome: dict[str, bool] = {}
        threads = [
            threading.Thread(target=lambda: outcome.update(window=life.expect_window())),
            threading.Thread(target=lambda: outcome.update(ends=life.may_end())),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # either the window was accepted and the program goes on, or the program ends and the window was refused
        assert outcome["window"] != outcome["ends"]


# -- the watcher -------------------------------------------------------------------------------------------------------
def test_the_program_does_not_end_while_a_window_that_was_announced_is_opening() -> None:
    clock = Clock()
    life = Lifetime(clock)
    announced = []

    def shown(_port: int) -> bool:
        return (
            clock.now < 2.0 or clock.now >= 9.0
        )  # the first window until 2 s; the new one is named only at 9 s

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if (
            clock.now >= 3.0 and not announced
        ):  # the user opens the program again: its window is announced
            announced.append(life.expect_window())

    wait_until_closed(
        8765,
        lambda: clock.now < 14.0,
        shown=shown,
        expecting=life.expecting,
        end=life.may_end,
        clock=clock,
        sleep=sleep,
    )
    assert announced == [True]
    assert (
        clock.now >= 14.0
    )  # it went on until the server ended: without the announcement it would have left at 6 s
    assert life.expect_window()  # and it never decided to end


def test_a_window_that_was_announced_and_never_came_does_not_keep_the_program_for_ever() -> None:
    clock = Clock()
    life = Lifetime(clock)
    announced = []

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= 3.0 and not announced:
            announced.append(life.expect_window(20))

    wait_until_closed(
        8765,
        lambda: True,
        shown=lambda _p: clock.now < 2.0,
        expecting=life.expecting,
        end=life.may_end,
        clock=clock,
        sleep=sleep,
    )
    assert (
        3.0 + 20 + desktop.CLOSE_GRACE <= clock.now <= 3.0 + 20 + desktop.CLOSE_GRACE + 1.5
    )  # the wait, then the grace
    assert not life.expect_window()  # it ended: no window may open on it now


def test_a_window_announced_at_the_last_moment_stops_the_program_from_ending() -> None:
    clock = Clock()
    answers = [
        False,
        True,
    ]  # the first time it asks whether it may end, a window has just been announced

    def end() -> bool:
        return answers.pop(0)

    wait_until_closed(
        8765,
        lambda: True,
        shown=lambda _p: clock.now < 1.0,
        end=end,
        clock=clock,
        sleep=clock.sleep,
    )
    # it asked twice, a whole grace apart: the first no started the count again
    assert answers == [] and clock.now >= 1.0 + 2 * desktop.CLOSE_GRACE


# -- a second start -------------------------------------------------------------------------------------------------------
class Scene:
    """The other copy of the program, as a second start sees it. ``agrees`` is what it answers when asked for a window:
    True, "handled" (it opened the window itself), "stay" (an older copy: it only stays, this start opens the window)
    or False, "refused" (it is ending)."""

    def __init__(self, locks: list[bool], up: list[bool], agrees: list, window_showing: bool = False) -> None:
        self.clock = Clock()
        self._locks, self._up, self._agrees = locks, up, agrees
        self._window_showing = window_showing
        self.windows: list[str] = []
        self.asked: list[tuple[int, bool, bool]] = []
        self.tries = 0

    @staticmethod
    def _next(items: list):
        return items.pop(0) if len(items) > 1 else items[0]

    def lead(self, argv: list[str] | None = None, patience: float = 180.0, unless_shown: bool = False) -> bool:
        self.warnings: list[str] = []

        def acquire() -> bool:
            self.tries += 1
            return self._next(self._locks)

        def alive(_port: int):
            return {"broker": "mock"} if self._next(self._up) else None

        def ask(port: int, *, open_one: bool, unless_shown: bool) -> str:
            self.asked.append((port, open_one, unless_shown))
            answer = self._next(self._agrees)
            return {True: "handled", False: "refused"}.get(answer, answer)

        return lead_or_join(
            argv or [],
            acquire=acquire,
            port_of=lambda: 8765,
            alive=alive,
            ask=ask,
            show=self.windows.append,
            shown=lambda _port: self._window_showing,
            warn=self.warnings.append,
            unless_shown=unless_shown,
            clock=self.clock,
            sleep=self.clock.sleep,
            patience=patience,
        )


def test_the_first_start_is_the_program() -> None:
    scene = Scene(locks=[True], up=[False], agrees=[False])
    assert scene.lead() is True
    assert scene.windows == [] and scene.asked == []


def test_a_second_start_asks_the_running_copy_for_a_window_and_the_copy_opens_it() -> None:
    scene = Scene(locks=[False], up=[True], agrees=[True])
    assert scene.lead() is False
    # the window is the running copy's own (so it ends with it): this start opens nothing
    assert scene.asked == [(8765, True, False)] and scene.windows == []


def test_an_older_copy_only_stays_and_this_start_opens_the_window() -> None:
    scene = Scene(locks=[False], up=[True], agrees=["stay"])
    assert scene.lead() is False
    assert scene.windows == ["http://127.0.0.1:8765/"]


def test_a_second_start_without_a_window_asks_only_for_the_copy_to_stay() -> None:
    scene = Scene(locks=[False], up=[True], agrees=["stay"])
    assert scene.lead(["--no-window"]) is False
    assert scene.asked == [(8765, False, False)] and scene.windows == []


# -- an update is being installed -----------------------------------------------------------------------------------------------
def test_a_start_while_an_update_is_installed_waits_for_it() -> None:
    clock = Clock()
    answers = [True, True, True, False]  # three looks at the installer running, then it is done
    assert desktop.wait_for_update(updating=lambda: answers.pop(0), clock=clock, sleep=clock.sleep) is True
    assert answers == [] and 1.0 <= clock.now <= 2.0


def test_a_start_when_no_update_is_installed_does_not_wait() -> None:
    clock = Clock()
    assert desktop.wait_for_update(updating=lambda: False, clock=clock, sleep=clock.sleep) is False
    assert clock.now == 0.0


def test_a_start_that_waited_for_an_update_only_opens_a_window_when_none_is_showing() -> None:
    scene = Scene(locks=[False], up=[True], agrees=[True])
    assert scene.lead(unless_shown=True) is False
    assert scene.asked == [(8765, True, True)]  # the running copy is asked to open none if one is showing


def test_the_start_that_an_update_makes_opens_no_second_window_either() -> None:
    scene = Scene(locks=[False], up=[True], agrees=[True])
    assert scene.lead(["--reconnect"]) is False
    assert scene.asked == [(8765, True, True)]


def test_an_older_copy_is_not_given_a_second_window_when_one_is_showing() -> None:
    scene = Scene(locks=[False], up=[True], agrees=["stay"], window_showing=True)
    assert scene.lead(["--reconnect"]) is False
    assert scene.windows == []
    scene = Scene(locks=[False], up=[True], agrees=["stay"], window_showing=False)
    assert scene.lead(["--reconnect"]) is False
    assert scene.windows == ["http://127.0.0.1:8765/"]


def test_a_second_start_that_is_no_update_opens_its_window_even_when_one_is_showing() -> None:
    scene = Scene(locks=[False], up=[True], agrees=["stay"], window_showing=True)
    assert scene.lead() is False
    assert scene.windows == ["http://127.0.0.1:8765/"]  # a second double-click is a second window, as it always was


def test_an_update_that_never_ends_does_not_keep_a_start_for_ever() -> None:
    clock = Clock()
    assert desktop.wait_for_update(updating=lambda: True, clock=clock, sleep=clock.sleep, patience=20.0) is True
    assert 20.0 <= clock.now <= 21.0


def test_a_copy_that_is_ending_is_waited_for_and_the_second_start_becomes_the_program() -> None:
    # it answers, and says no (it has decided to end); then it stops answering; then the lock is free
    scene = Scene(locks=[False, False, False, True], up=[True, False, False], agrees=[False])
    assert scene.lead() is True
    assert scene.windows == []  # never a window on a program that is ending
    assert scene.asked == [(8765, True, False)]
    assert 0.5 <= scene.clock.now <= 1.2  # a moment, not minutes


def test_a_copy_that_is_still_starting_is_waited_for() -> None:
    scene = Scene(locks=[False], up=[False, False, True], agrees=[True])
    assert scene.lead() is False
    assert scene.asked == [(8765, True, False)]  # it was asked only once it answered
    assert 0.5 <= scene.clock.now <= 1.0


def test_a_copy_that_never_comes_up_does_not_keep_the_second_start_for_ever_and_the_user_is_told() -> (
    None
):
    scene = Scene(locks=[False], up=[False], agrees=[False])
    assert scene.lead(patience=30.0) is False
    assert scene.windows == [] and 30.0 <= scene.clock.now <= 31.0
    assert len(scene.warnings) == 1 and "does not answer" in scene.warnings[0]


def test_a_start_without_a_window_says_nothing_when_it_gives_up() -> None:
    scene = Scene(locks=[False], up=[False], agrees=[False])
    assert scene.lead(["--no-window"], patience=10.0) is False
    assert scene.warnings == []


# -- the lock itself ---------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.name != "nt", reason="a Windows lock")
def test_a_start_that_found_the_lock_taken_does_not_keep_it_alive(monkeypatch) -> None:
    name = f"Local\\CheapTrader.test.{uuid.uuid4().hex}"
    monkeypatch.setattr(desktop, "_singleton", None)
    assert acquire_singleton(name)  # this process is the program
    mine = desktop._singleton
    assert not acquire_singleton(name)  # a second start finds the lock taken ...
    assert not acquire_singleton(name)  # ... also when it tries again while it waits
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle(mine)  # the program ends
    assert acquire_singleton(name)  # the lock is free: nothing was holding it for the waiting start
    kernel32.CloseHandle(desktop._singleton)


# -- asking a running copy ---------------------------------------------------------------------------------------------------
def serve(body: bytes, seen: list[str]):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            sent = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.append(f"{self.command} {self.path} {sent.decode()}")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"ok": true, "handled": true}', "handled"),  # it opened the window itself
        (b'{"ok": true}', "stay"),  # an older copy: it stays, the window is the asker's to open
        (b'{"ok": false}', "refused"),
        (b"not json", "refused"),
        (b"{}", "refused"),
        (b"[]", "refused"),
    ],
)
def test_the_running_copy_is_asked_for_a_window_and_the_answer_is_read(body: bytes, expected: str) -> None:
    seen: list[str] = []
    server = serve(body, seen)
    try:
        assert ask_for_window(server.server_address[1]) == expected
        assert seen == ['POST /api/app/window {"open": true, "unless_shown": false}']
    finally:
        server.shutdown()
        server.server_close()


def test_what_the_second_start_asks_for_goes_with_the_request() -> None:
    seen: list[str] = []
    server = serve(b'{"ok": true}', seen)
    try:
        port = server.server_address[1]
        ask_for_window(port, open_one=False)
        ask_for_window(port, unless_shown=True)
        assert [s.split(" ", 2)[2] for s in seen] == ['{"open": false, "unless_shown": false}', '{"open": true, "unless_shown": true}']
    finally:
        server.shutdown()
        server.server_close()


def test_a_copy_that_does_not_answer_has_not_agreed() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert ask_for_window(port) == "refused"  # nothing listens there


# -- what the running copy answers ------------------------------------------------------------------------------------------------
def test_a_copy_that_is_ending_refuses_and_opens_no_window() -> None:
    life = Lifetime(Clock())
    life.end()
    opened: list[bool] = []
    answer = answer_window_request(life, open_one=True, unless_shown=False, showing=False, open_now=lambda: opened.append(True))
    assert answer == {"ok": False} and opened == []


def test_a_copy_opens_the_window_itself_when_asked_to() -> None:
    life = Lifetime(Clock())
    opened: list[bool] = []
    answer = answer_window_request(life, open_one=True, unless_shown=False, showing=True, open_now=lambda: opened.append(True))
    assert answer == {"ok": True, "handled": True} and opened == [True]  # a second window, though one is showing
    assert life.expecting()  # and it stays for it


def test_a_copy_opens_none_when_asked_to_leave_it_be_and_one_is_showing() -> None:
    life = Lifetime(Clock())
    opened: list[bool] = []
    answer = answer_window_request(life, open_one=True, unless_shown=True, showing=True, open_now=lambda: opened.append(True))
    assert answer == {"ok": True, "handled": True} and opened == []
    answer = answer_window_request(life, open_one=True, unless_shown=True, showing=False, open_now=lambda: opened.append(True))
    assert answer == {"ok": True, "handled": True} and opened == [True]


def test_a_copy_that_is_only_asked_to_stay_opens_nothing() -> None:
    life = Lifetime(Clock())
    opened: list[bool] = []
    answer = answer_window_request(life, open_one=False, unless_shown=False, showing=False, open_now=lambda: opened.append(True))
    assert answer == {"ok": True} and opened == [] and life.expecting()


# -- the routes -----------------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CT_BROKER", "mock")
    from app.main import app

    for hook in ("quit_hook", "update_hook", "window_closer", "window_hook"):
        monkeypatch.setattr(terminal_routes, hook, None)
    with TestClient(app) as c:
        yield c


def test_a_window_is_accepted_when_nothing_closes_the_program_by_itself(client) -> None:
    assert client.post("/api/app/window").json() == {"ok": True}  # the development server
    assert client.post("/api/app/window", json={"open": True, "unless_shown": True}).json() == {"ok": True}


def test_the_program_says_yes_or_no_to_a_window(client, monkeypatch) -> None:
    life = Lifetime(Clock())
    opened: list[bool] = []

    def hook(open_one: bool, unless_shown: bool) -> dict:
        return answer_window_request(life, open_one=open_one, unless_shown=unless_shown, showing=False, open_now=lambda: opened.append(True))

    monkeypatch.setattr(terminal_routes, "window_hook", hook)
    assert client.post("/api/app/window", json={}).json() == {"ok": True}  # what a copy that was started by 0.2.1 sends
    assert life.expecting() and opened == []
    assert client.post("/api/app/window", json={"open": True, "unless_shown": False}).json() == {"ok": True, "handled": True}
    assert opened == [True]
    life.end()
    assert client.post("/api/app/window", json={"open": True}).json() == {"ok": False}
    assert opened == [True]  # never a window on a copy that is ending


def test_an_update_closes_the_program_the_way_that_keeps_its_window(client, monkeypatch) -> None:
    """The update's hook lets the window go on (see ``WindowJob.release``); Quit's does not."""
    from app.state import get_state

    updater = get_state().updater
    status = updater.status()
    closed_with: list = []
    monkeypatch.setattr(updater, "install", lambda quit_app: closed_with.append(quit_app) or status)

    def quit_hook() -> None: ...

    def update_hook() -> None: ...

    monkeypatch.setattr(terminal_routes, "quit_hook", quit_hook)
    monkeypatch.setattr(terminal_routes, "update_hook", update_hook)
    assert client.post("/api/update/install").status_code == 200
    assert closed_with == [update_hook]  # not the plain quit
    monkeypatch.setattr(terminal_routes, "update_hook", None)  # the development server
    assert client.post("/api/update/install").status_code == 200
    assert closed_with == [update_hook, quit_hook]


def test_quit_closes_the_window_and_then_the_program(client, monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(terminal_routes, "window_closer", lambda: order.append("window closed"))
    monkeypatch.setattr(terminal_routes, "quit_hook", lambda: order.append("program stopped"))
    assert client.post("/api/app/quit").json() == {"ok": True}
    assert order == ["window closed", "program stopped"]


def test_quit_works_without_a_window_to_close(client, monkeypatch) -> None:
    stopped: list[bool] = []
    monkeypatch.setattr(terminal_routes, "quit_hook", lambda: stopped.append(True))
    assert client.post("/api/app/quit").json() == {"ok": True}
    assert stopped == [True]


def test_only_the_window_of_this_copy_is_closed(monkeypatch) -> None:
    class Fake:
        def __init__(self) -> None:
            self.posted: list[tuple[int, int]] = []

        def PostMessageW(self, hwnd, message, _w, _l) -> bool:  # noqa: N802
            self.posted.append((hwnd, message))
            return True

    fake = Fake()
    monkeypatch.setattr(desktop, "_user32", fake)
    monkeypatch.setattr(
        desktop,
        "_top_level_windows",
        lambda: [
            (1, "CheapTrader · 127.0.0.1:8765"),
            (2, "Untitled - Notepad"),
            (3, "CheapTrader · 127.0.0.1:9000"),
            (4, "CheapTrader - File Explorer"),
        ],
    )
    desktop.close_windows(8765)
    assert fake.posted == [(1, 0x0010)]  # WM_CLOSE, to the one window of the program on this port


# -- a server that stops by itself ----------------------------------------------------------------------------------------------
class Finished:
    """A server thread that is no longer alive."""

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        pass


class Server:
    should_exit = False


def test_a_server_that_stopped_by_itself_does_not_leave_its_window_behind(monkeypatch) -> None:
    told: list[str] = []
    closed: list[int] = []
    monkeypatch.setattr(desktop, "lifetime", Lifetime(Clock()))
    monkeypatch.setattr(desktop, "close_windows", closed.append)
    monkeypatch.setattr(desktop, "message", lambda text, **_kw: told.append(text))
    assert desktop.stop(Server(), Finished(), 8765) == 1
    assert closed == [8765]
    assert told and "stopped unexpectedly" in told[0]


def test_a_program_that_was_asked_to_end_ends_quietly(monkeypatch) -> None:
    told: list[str] = []
    closed: list[int] = []
    life = Lifetime(Clock())
    life.end()
    monkeypatch.setattr(desktop, "lifetime", life)
    monkeypatch.setattr(desktop, "close_windows", closed.append)
    monkeypatch.setattr(desktop, "message", lambda text, **_kw: told.append(text))
    server = Server()
    assert desktop.stop(server, Finished(), 8765) == 0
    assert server.should_exit is True and closed == [] and told == []


def test_the_server_gives_a_running_request_only_a_few_seconds_when_the_program_ends() -> None:
    assert 1 <= desktop.SHUTDOWN_GRACE <= 10
