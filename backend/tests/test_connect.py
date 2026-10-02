"""Starting without MetaTrader and connecting to it later, and the app's own switch for sending orders.

A first-time user may start CheapTrader before MetaTrader is open. The app then begins on the synthetic
market; once a terminal is open and logged in it can switch over (``POST /api/terminal/connect``) without
a restart, and the screens that are open follow. The stand-in terminal (tests/fake_mt5) lets this run for
real, through the reader / trader / feed processes.
"""

from __future__ import annotations

import json
import os
import time
import types
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.state as app_state
from app import __version__
from app.api import terminal_routes
from app.config import Settings
from app.main import app
from app.terminals import Terminal

FAKE = Path(__file__).parent / "fake_mt5"


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    """A stand-in MetaTrader terminal that is not open yet. ``open()`` opens it (and logs in)."""
    path = tmp_path / "terminal.json"
    path.write_text(
        json.dumps(
            {
                "rate": 50,
                "t0": int(time.time() * 1000) - 3000,
                "base": 1.1,
                "step": 0.00001,
                "order_delay": 0.0,
                "requotes": 0,
                "positions": [],
                "orders": [],
                "pending": [],
                "next_ticket": 1,
                "symbols": {"EURUSD": {"visible": True}, "GBPUSD": {"visible": False}},
                "terminal_running": False,
                "logged_in": True,
            }
        )
    )
    monkeypatch.setenv("FAKE_MT5_STATE", str(path))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(p for p in (str(FAKE), os.environ.get("PYTHONPATH", "")) if p))

    found: list[Terminal] = []
    # what the PC has installed: never the real terminals of the machine the tests run on
    monkeypatch.setattr(terminal_routes, "_detected", lambda: list(found))

    def edit(**changes) -> None:
        state = json.loads(path.read_text())
        state.update(changes)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, path)

    def install(running: bool) -> None:
        found[:] = [
            Terminal(
                exe=str(tmp_path / "terminal64.exe"),
                folder=str(tmp_path),
                name="Fake MetaTrader 5",
                broker="Fake",
                running=running,
                pid=1234 if running else None,
                last_used=0.0,
            )
        ]

    def open_(logged_in: bool = True) -> None:
        edit(terminal_running=True, logged_in=logged_in)
        install(running=True)

    return types.SimpleNamespace(edit=edit, install=install, open=open_, found=found)


@contextmanager
def running_app(**settings):
    """The app, started the way the program starts, with settings of its own (not the developer's .env)."""
    state = app_state.AppState(Settings(_env_file=None, **{"broker": "auto", **settings}))
    previous = app_state._state
    app_state._state = state
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        app_state._state = previous


def test_without_a_terminal_the_app_starts_on_the_synthetic_market(terminal) -> None:
    with running_app() as (client, _):
        health = client.get("/api/health").json()
        assert health["broker"] == "mock" and health["version"] == __version__
        status = client.get("/api/terminal").json()
        assert status["broker"] == "mock" and status["mode"] == "auto"
        assert status["can_connect"] is False  # nothing is open to connect to
        assert status["terminals"] == []
        assert status["app"]["version"] == __version__


def test_an_installed_terminal_is_listed_even_while_the_app_is_on_the_synthetic_market(terminal) -> None:
    terminal.install(running=False)
    with running_app() as (client, _):
        status = client.get("/api/terminal").json()
        assert [t["name"] for t in status["terminals"]] == ["Fake MetaTrader 5"]
        assert status["terminals"][0]["running"] is False
        assert status["can_connect"] is False  # installed, but not open: the user opens it first


def test_connecting_while_nothing_is_open_says_why(terminal) -> None:
    with running_app() as (client, _):
        reply = client.post("/api/terminal/connect")
        assert reply.status_code == 409
        assert "initialize() failed" in reply.json()["detail"]
        assert client.get("/api/health").json()["broker"] == "mock"


def test_a_terminal_that_is_open_without_an_account_is_not_used(terminal) -> None:
    with running_app() as (client, _):
        terminal.open(logged_in=False)  # the user opens MetaTrader but has not logged in
        assert client.get("/api/terminal").json()["can_connect"] is True
        reply = client.post("/api/terminal/connect")
        assert reply.status_code == 409
        assert "no account is logged in" in reply.json()["detail"]
        assert client.get("/api/health").json()["broker"] == "mock"
        # the user logs in, and the same button works
        terminal.edit(logged_in=True)
        assert client.post("/api/terminal/connect").status_code == 200
        assert client.get("/api/health").json()["broker"] == "mt5"


def test_a_terminal_that_opens_later_is_connected_without_a_restart(terminal) -> None:
    with running_app() as (client, _):
        with client.websocket_connect("/ws/stream") as screen:
            screen.send_json({"type": "subscribe", "symbol": "EURUSD"})

            terminal.open()
            status = client.get("/api/terminal").json()
            assert status["can_connect"] is True and status["broker"] == "mock"

            reply = client.post("/api/terminal/connect")
            assert reply.status_code == 200, reply.text
            now = reply.json()
            assert now["broker"] == "mt5" and now["info"]["account_login"] == 1
            assert now["can_connect"] is False

            # the screen that was open is told, and then gets the terminal's own account and prices
            kinds: list[str] = []
            account = None
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not (("broker" in kinds) and account):
                message = screen.receive_json()
                kinds.append(message["type"])
                if message["type"] == "state" and "broker" in kinds:
                    account = message["account"]
            assert "broker" in kinds
            assert account and account["server"] == "Fake-Demo"

        health = client.get("/api/health").json()
        assert health["broker"] == "mt5"
        assert "EURUSD" in [s["name"] for s in client.get("/api/symbols", params={"limit": 50}).json()]
        assert client.get("/api/account").json()["server"] == "Fake-Demo"
        # asking again changes nothing
        assert client.post("/api/terminal/connect").status_code == 200


def test_a_program_set_to_the_synthetic_market_keeps_it(terminal) -> None:
    terminal.open()
    with running_app(broker="mock") as (client, _):
        status = client.get("/api/terminal").json()
        assert status["mode"] == "mock" and status["can_connect"] is False
        reply = client.post("/api/terminal/connect")
        assert reply.status_code == 409 and "CT_BROKER=mock" in reply.json()["detail"]


# -- sending orders ---------------------------------------------------------------------------------------
ORDER = {"symbol": "EURUSD", "side": "BUY", "volume": 0.1}


def test_orders_are_off_until_the_user_switches_them_on_in_the_app(terminal) -> None:
    terminal.open()
    with running_app() as (client, _):
        assert client.get("/api/health").json()["broker"] == "mt5"
        assert client.get("/api/terminal").json()["orders"] == {"allowed": False, "by_settings": False}

        refused = client.post("/api/orders", json=ORDER)
        assert refused.status_code == 403
        assert "MetaTrader menu" in refused.json()["detail"]
        assert terminal_orders(terminal) == []  # nothing reached the (stand-in) terminal

        on = client.post("/api/app/orders", json={"enabled": True}).json()
        assert on["orders"] == {"allowed": True, "by_settings": False}
        assert client.post("/api/orders", json=ORDER).json()["ok"] is True
        assert len(terminal_orders(terminal)) == 1

        off = client.post("/api/app/orders", json={"enabled": False}).json()
        assert off["orders"]["allowed"] is False
        assert client.post("/api/orders", json=ORDER).status_code == 403


def test_the_choice_is_remembered_for_the_next_start(terminal) -> None:
    terminal.open()
    with running_app() as (client, _):
        client.post("/api/app/orders", json={"enabled": True})
    with running_app() as (client, _):
        assert client.get("/api/terminal").json()["orders"]["allowed"] is True


def test_orders_switched_on_in_the_settings_cannot_be_switched_off_here(terminal) -> None:
    terminal.open()
    with running_app(allow_live_orders=True) as (client, _):
        assert client.get("/api/terminal").json()["orders"] == {"allowed": True, "by_settings": True}
        reply = client.post("/api/app/orders", json={"enabled": False})
        assert reply.status_code == 409 and "CT_ALLOW_LIVE_ORDERS" in reply.json()["detail"]
        assert client.post("/api/orders", json=ORDER).json()["ok"] is True


def terminal_orders(terminal) -> list[dict]:
    """The orders the stand-in terminal was given."""
    path = Path(os.environ["FAKE_MT5_STATE"])
    return json.loads(path.read_text()).get("orders", [])
