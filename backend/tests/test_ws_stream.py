"""The WebSocket end to end, on the mock broker: every tick, and the account when it changes."""

from __future__ import annotations

import os
import time

os.environ["CT_BROKER"] = "mock"
os.environ["CT_MOCK_TICK_RATE"] = "100"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def receive_until(ws, predicate, limit: float = 5.0) -> list[dict]:
    seen: list[dict] = []
    end = time.monotonic() + limit
    while time.monotonic() < end:
        message = ws.receive_json()
        seen.append(message)
        if predicate(seen):
            return seen
    raise AssertionError(f"gave up waiting; saw {[m['type'] for m in seen]}")


def tick_times(messages: list[dict]) -> list[int]:
    return [t["time_msc"] for m in messages if m["type"] == "ticks" for t in m["data"]]


def test_every_tick_arrives_once_and_in_order() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        seen = receive_until(ws, lambda m: len(tick_times(m)) >= 60)
        times = tick_times(seen)
        assert times == sorted(set(times))
        assert seen[0]["type"] in {"subscribed", "state", "ticks"}
        assert any(m["type"] == "subscribed" and m["symbol"] == "EURUSD" for m in seen)
        assert all(m["symbol"] == "EURUSD" for m in seen if m["type"] == "ticks")
        # about 100 ticks a second: sixty of them take well under two seconds to arrive
        assert (times[-1] - times[0]) < 2500


def test_the_screen_hears_about_a_new_position_before_it_asks() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        receive_until(ws, lambda m: any(x["type"] == "state" for x in m))

        order = client.post("/api/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1}).json()
        assert order["ok"]
        seen = receive_until(
            ws, lambda m: any(x["type"] == "state" and x["positions"] for x in m), limit=3.0
        )
        state = next(m for m in seen if m["type"] == "state" and m["positions"])
        assert state["positions"][0]["ticket"] == order["order_id"]
        assert state["account"]["currency"] == "USD"

        client.delete(f"/api/positions/{order['order_id']}")
        receive_until(ws, lambda m: any(x["type"] == "state" and not x["positions"] for x in m), limit=3.0)


def test_a_moved_stop_reaches_the_screen() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        tick = client.get("/api/tick", params={"symbol": "EURUSD"}).json()
        order = client.post("/api/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1}).json()
        sl = round(tick["bid"] - 0.01, 5)
        client.patch("/api/positions", json={"ticket": order["order_id"], "sl": sl})
        receive_until(
            ws,
            lambda m: any(x["type"] == "state" and x["positions"] and x["positions"][0]["sl"] == sl for x in m),
            limit=3.0,
        )


def test_switching_symbol_switches_the_ticks() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        receive_until(ws, lambda m: len(tick_times(m)) >= 3)
        ws.send_json({"type": "subscribe", "symbol": "USDJPY"})
        seen = receive_until(
            ws, lambda m: sum(1 for x in m if x["type"] == "ticks" and x["symbol"] == "USDJPY") >= 3
        )
        # once USDJPY has started, no EURUSD tick follows
        first_jpy = next(i for i, m in enumerate(seen) if m["type"] == "ticks" and m["symbol"] == "USDJPY")
        assert all(m["symbol"] == "USDJPY" for m in seen[first_jpy:] if m["type"] == "ticks")


def test_ping_is_answered() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "ping", "t": 12345})
        seen = receive_until(ws, lambda m: any(x["type"] == "pong" for x in m))
        assert next(m for m in seen if m["type"] == "pong")["t"] == 12345


def test_leaving_stops_the_feed_following_the_symbol() -> None:
    with TestClient(app) as client:
        hub = app_hub()
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
            receive_until(ws, lambda m: len(tick_times(m)) >= 2)
            assert hub._refs == {"EURUSD": 1}
        deadline = time.monotonic() + 3
        while hub._refs and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub._refs == {}


def app_hub():
    from app.state import get_state

    return get_state().hub
