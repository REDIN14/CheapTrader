"""Tests for the REST API using the mock broker."""

from __future__ import annotations

import os

os.environ["CT_BROKER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_health_and_symbols() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["broker"] == "mock"

        symbols = client.get("/api/symbols").json()
        assert len(symbols) > 0


def test_bars_and_tick() -> None:
    with TestClient(app) as client:
        bars = client.get("/api/bars", params={"symbol": "EURUSD", "timeframe": "H1", "count": 50}).json()
        assert len(bars) == 50

        tick = client.get("/api/tick", params={"symbol": "EURUSD"}).json()
        assert "bid" in tick and "ask" in tick


def test_order_flow() -> None:
    with TestClient(app) as client:
        result = client.post(
            "/api/orders",
            json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1},
        ).json()
        assert result["ok"]

        positions = client.get("/api/positions").json()
        assert len(positions) == 1
        ticket = positions[0]["ticket"]

        closed = client.delete(f"/api/positions/{ticket}").json()
        assert closed["ok"]


def test_health_reports_the_live_feed_and_trades_are_logged(caplog) -> None:
    import logging

    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="app.api.routes"):
        assert client.get("/api/health").json()["feed"] in {"starting", "up"}
        order = client.post("/api/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1}).json()
        client.delete(f"/api/positions/{order['order_id']}")
    lines = [r.getMessage() for r in caplog.records if r.name == "app.api.routes"]
    assert any(line.startswith("BUY 0.1 EURUSD -> ok; broker") and "whole call" in line for line in lines), lines
    assert any(line.startswith(f"close {order['order_id']} -> ok") for line in lines), lines
