"""Other web pages cannot use the program: not by posting to it, not by DNS rebinding, not over the
stream. Scripts and the page itself are not affected."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("CT_BROKER", "mock")

from app.main import app  # noqa: E402
from app.security import hostname, same_site  # noqa: E402

HOME = "http://127.0.0.1:8765"


@pytest.fixture
def client():
    with TestClient(app, base_url=HOME) as c:
        yield c


# something that changes something, and harmless: the terminal to prefer is forgotten
CHANGE = ("/api/terminal/choose", {"path": None})


def test_the_page_itself_and_scripts_are_let_in(client) -> None:
    assert client.get("/api/health").status_code == 200
    # a script sends no Origin
    assert client.post(CHANGE[0], json=CHANGE[1]).status_code == 200
    # the page sends its own address
    assert client.post(CHANGE[0], json=CHANGE[1], headers={"Origin": HOME}).status_code == 200


def test_another_site_cannot_change_anything(client) -> None:
    for method, path in (("POST", "/api/terminal/choose"), ("POST", "/api/app/quit"), ("DELETE", "/api/orders/1"), ("PATCH", "/api/orders")):
        reply = client.request(method, path, json=CHANGE[1], headers={"Origin": "https://evil.example"})
        assert reply.status_code == 403, (method, path)
        assert "Another web page" in reply.json()["detail"]
    # a page opened from a file, or a sandboxed one, says its Origin is "null"
    assert client.post(CHANGE[0], json=CHANGE[1], headers={"Origin": "null"}).status_code == 403
    # the same host on another port is another site
    assert client.post(CHANGE[0], json=CHANGE[1], headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403


def test_reading_from_another_site_is_left_to_the_browsers_own_rule(client) -> None:
    # (no CORS header is sent, so the other page cannot read the answer)
    reply = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert reply.status_code == 200
    assert "access-control-allow-origin" not in reply.headers


def test_a_preflight_from_another_site_is_not_answered_with_permission(client) -> None:
    reply = client.options(
        "/api/orders",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert "access-control-allow-origin" not in reply.headers


def test_a_host_name_that_is_not_the_programs_own_is_refused(client) -> None:
    # DNS rebinding: the request reaches 127.0.0.1 but carries the attacker's domain
    reply = client.get("/api/health", headers={"Host": "attacker.example:8765"})
    assert reply.status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:5173"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "[::1]:8765"}).status_code == 200


def test_the_test_client_is_only_let_in_because_the_tests_say_so(monkeypatch) -> None:
    monkeypatch.delenv("CT_ALLOWED_HOSTS")
    with TestClient(app) as c:  # "testserver"
        assert c.get("/api/health").status_code == 400
    monkeypatch.setenv("CT_ALLOWED_HOSTS", "testserver")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200


def pong(screen, t: int) -> dict:
    """The answer to a ping (the stream may say other things first)."""
    screen.send_json({"type": "ping", "t": t})
    for _ in range(20):
        message = screen.receive_json()
        if message["type"] == "pong":
            return message
    raise AssertionError("no pong")


def test_the_stream_is_not_open_to_other_sites(client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/stream", headers={"Origin": "https://evil.example"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/stream", headers={"Host": "attacker.example"}):
            pass
    # (the test client's stream calls itself "testserver" unless it is told better)
    page = {"Host": "127.0.0.1:8765", "Origin": HOME}
    with client.websocket_connect("/ws/stream", headers=page) as screen:
        assert pong(screen, 1) == {"type": "pong", "t": 1}
    with client.websocket_connect("/ws/stream") as screen:  # a script
        assert pong(screen, 2)["t"] == 2


def test_a_page_the_user_names_is_let_in(client, monkeypatch) -> None:
    monkeypatch.setenv("CT_ALLOWED_ORIGINS", "http://localhost:5173")
    assert client.post(CHANGE[0], json=CHANGE[1], headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post(CHANGE[0], json=CHANGE[1], headers={"Origin": "https://evil.example"}).status_code == 403


def test_the_pieces() -> None:
    assert hostname("127.0.0.1:8765") == "127.0.0.1"
    assert hostname("LOCALHOST") == "localhost"
    assert hostname("[::1]:8765") == "[::1]"
    assert same_site("http://127.0.0.1:8765", "127.0.0.1:8765")
    assert same_site("HTTP://127.0.0.1:8765/", "127.0.0.1:8765")
    assert not same_site("http://127.0.0.1:8765.evil.example", "127.0.0.1:8765")
    assert not same_site("ftp://127.0.0.1:8765", "127.0.0.1:8765")
