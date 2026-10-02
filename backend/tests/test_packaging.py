"""What the built program (CheapTrader.exe) needs from the code: where its files go, how it starts
its helpers, and that it serves its own page."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app import desktop, paths, procutil
from app.config import Settings
from app.main import mount_ui


@pytest.fixture
def built(monkeypatch, tmp_path):
    """Pretend to be the built program: ``tmp_path/CheapTrader.exe`` with its files beside it."""
    exe = tmp_path / "CheapTrader.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.delenv("CT_DATA_DIR", raising=False)
    monkeypatch.delenv("CT_UI_DIR", raising=False)
    return tmp_path


def test_helpers_are_started_with_python_m_while_developing() -> None:
    assert procutil.module_command("app.stream.mt5_feed", "--x") == [sys.executable, "-m", "app.stream.mt5_feed", "--x"]
    assert procutil.script_command(Path("runner.py"), "a") == [sys.executable, "runner.py", "a"]


def test_the_built_program_starts_itself_again_as_its_helper(built) -> None:
    exe = str(built / "CheapTrader.exe")
    assert procutil.module_command("app.broker.trade_worker", "--role", "reader") == [
        exe, "--worker", "app.broker.trade_worker", "--role", "reader"
    ]
    assert procutil.script_command("runner.py", "a", "b") == [exe, "--script", "runner.py", "a", "b"]


def test_dispatch_runs_a_worker_module_and_a_script(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "marker.txt"
    (tmp_path / "pretend_worker.py").write_text(
        f"import sys\nif __name__ == '__main__':\n    open({str(marker)!r}, 'w').write(repr(sys.argv))\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "argv", sys.argv)  # dispatch rewrites it; give it back afterwards
    assert procutil.dispatch(["exe", "--worker", "pretend_worker", "a", "b"])
    ran_as = eval(marker.read_text())  # like python -m: argv[0] is the module's file, the rest as given
    assert ran_as[0].endswith("pretend_worker.py") and ran_as[1:] == ["a", "b"]

    script = tmp_path / "pretend_script.py"
    script.write_text(f"import sys\nopen({str(marker)!r}, 'w').write(repr(sys.argv[1:]))\n", encoding="utf-8")
    assert procutil.dispatch(["exe", "--script", str(script), "x"])
    assert marker.read_text() == repr(["x"])

    assert not procutil.dispatch(["exe"])  # a normal start
    assert not procutil.dispatch(["exe", "--console"])


def test_a_built_program_keeps_its_files_beside_the_exe(built) -> None:
    assert paths.data_dir() == built / "data"
    assert paths.env_file() == str(built / ".env")
    assert (built / "data").is_dir()
    assert paths.logs_dir() == built / "data" / "logs"


def test_a_folder_it_cannot_write_to_sends_the_data_to_the_users_app_data(built, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(built / "appdata"))
    monkeypatch.setattr(paths, "_writable", lambda folder: False)
    assert paths.data_dir() == built / "appdata" / "CheapTrader" / "data"


def test_the_data_folder_can_be_chosen(built, monkeypatch) -> None:
    monkeypatch.setenv("CT_DATA_DIR", str(built / "elsewhere"))
    assert paths.data_dir() == built / "elsewhere"


def test_while_developing_nothing_moves(monkeypatch) -> None:
    monkeypatch.delenv("CT_DATA_DIR", raising=False)
    monkeypatch.delenv("CT_UI_DIR", raising=False)
    assert paths.data_dir() == paths.backend_root() / "data"
    assert paths.env_file() == ".env"
    assert paths.ui_dir() is None  # the page comes from Vite


def test_the_page_is_found_in_the_bundle_or_where_ct_ui_dir_says(built, monkeypatch) -> None:
    assert paths.ui_dir() is None  # nothing there yet
    web = built / "_internal" / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<title>x</title>")
    assert paths.ui_dir() == web
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.ui_dir() is None
    monkeypatch.setenv("CT_UI_DIR", str(web))
    assert paths.ui_dir() == web


def test_the_page_is_served_beside_the_api_and_the_stream(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<title>CheapTrader</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict:
        return {"pong": True}

    @app.websocket("/ws/echo")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    mount_ui(app, tmp_path)
    client = TestClient(app)
    assert "<title>CheapTrader</title>" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/api/ping").json() == {"pong": True}
    with client.websocket_connect("/ws/echo") as ws:
        assert ws.receive_text() == "hello"


def test_the_port_is_8765_unless_the_settings_name_one(monkeypatch) -> None:
    import app.config

    monkeypatch.setattr(app.config, "get_settings", lambda: Settings(_env_file=None))
    assert desktop.chosen_port() == desktop.DEFAULT_PORT
    monkeypatch.setattr(app.config, "get_settings", lambda: Settings(_env_file=None, port=9001))
    assert desktop.chosen_port() == 9001


def test_nothing_answers_on_a_port_nobody_serves() -> None:
    assert desktop.health(desktop.free_port(0)) is None
