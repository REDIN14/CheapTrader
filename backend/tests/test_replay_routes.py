"""Replay REST routes, against the mock broker."""

from __future__ import annotations

import os

os.environ["CT_BROKER"] = "mock"

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.state import get_state  # noqa: E402


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def test_end_date_includes_the_whole_day() -> None:
    """Choosing 2026-01-03 as the end date must keep the bars of January 3rd."""
    with TestClient(app) as client:
        state = client.post(
            "/api/replay/load",
            params={"symbol": "EURUSD", "timeframe": "H1", "start": "2026-01-01", "end": "2026-01-03"},
        ).json()

    assert _day(state["first_time"]) == "2026-01-01"
    assert _day(state["last_time"]) == "2026-01-03"


def _begin(client: TestClient, back: int = 120, **extra) -> tuple[dict, int]:
    """Start a replay `back` bars before the newest H1 bar; returns the reply and the start time."""
    bars = client.get(
        "/api/bars", params={"symbol": "EURUSD", "timeframe": "H1", "count": 400}
    ).json()
    when = bars[-back]["time"]
    reply = client.post(
        "/api/replay/start",
        params={"symbol": "EURUSD", "timeframe": "H1", "time": when, **extra},
    )
    assert reply.status_code == 200, reply.text
    return reply.json(), when


def test_start_puts_the_cursor_on_the_bar_asked_for() -> None:
    with TestClient(app) as client:
        update, when = _begin(client)

    state, account = update["state"], update["account"]
    assert state["cursor_time"] == when
    assert update["reset"] is True
    # what the chart gets to draw is everything up to the cursor, newest last
    assert len(update["bars"]) == state["index"] + 1
    assert update["bars"][-1]["time"] == when
    # …while the bars after it are loaded and waiting
    assert state["total"] > state["index"] + 50
    assert state["last_time"] > when
    assert account["balance"] == account["equity"] == account["initial_balance"] == 10_000
    assert account["positions"] == [] and update["closed"] == []


def test_start_keeps_history_before_the_bar_and_caps_what_comes_after() -> None:
    with TestClient(app) as client:
        update, _ = _begin(client, lookback=300, lookahead=100)
    state = update["state"]
    assert state["index"] == 300  # exactly `lookback` bars of context before the start
    assert state["total"] - state["index"] - 1 <= 100  # and no more than `lookahead` after it


def test_advance_returns_only_the_new_bars_and_marks_positions_to_them() -> None:
    with TestClient(app) as client:
        update, _ = _begin(client)
        start_index = update["state"]["index"]
        placed = client.post(
            "/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 1.0}
        ).json()
        assert placed["ok"]
        moved = client.post("/api/replay/advance", params={"delta": 3}).json()

    assert moved["reset"] is False
    assert moved["state"]["index"] == start_index + 3
    assert len(moved["bars"]) == 3
    assert moved["bars"][0]["time"] > update["bars"][-1]["time"]
    (position,) = moved["account"]["positions"]
    expected = (moved["bars"][-1]["close"] - placed["price"]) * 1.0 * 100_000
    assert position["profit"] == pytest.approx(expected)
    assert moved["account"]["unrealized"] == pytest.approx(expected)
    assert moved["account"]["equity"] == pytest.approx(10_000 + expected)


def test_advance_reports_the_trades_a_stop_or_target_closed() -> None:
    with TestClient(app) as client:
        _begin(client)
        engine = get_state().replay
        entry = engine.bars[engine.index].close
        ahead = engine.bars[engine.index + 1 : engine.index + 11]
        highest, lowest = max(b.high for b in ahead), min(b.low for b in ahead)
        # aim half way to whichever side the next ten bars actually reach
        if highest > entry:
            order = {"tp": entry + (highest - entry) / 2}
            reason = "tp"
        else:
            assert lowest < entry
            order = {"sl": entry - (entry - lowest) / 2}
            reason = "sl"
        placed = client.post(
            "/api/replay/orders",
            json={"symbol": "EURUSD", "side": "BUY", "volume": 1.0, **order},
        ).json()
        assert placed["ok"], placed

        moved = client.post("/api/replay/advance", params={"delta": 10}).json()

    assert [t["reason"] for t in moved["closed"]] == [reason]
    assert moved["closed"][0]["ticket"] == placed["order_id"]
    assert moved["account"]["positions"] == []
    assert moved["account"]["trades_total"] == 1
    assert moved["account"]["realized"] == pytest.approx(moved["closed"][0]["pnl"])
    assert moved["account"]["balance"] == pytest.approx(10_000 + moved["closed"][0]["pnl"])


def test_advancing_backwards_hands_over_the_whole_picture() -> None:
    with TestClient(app) as client:
        update, _ = _begin(client)
        client.post("/api/replay/advance", params={"delta": 5})
        client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "SELL", "volume": 0.5})
        back = client.post("/api/replay/advance", params={"delta": -3}).json()

    assert back["reset"] is True
    assert back["state"]["index"] == update["state"]["index"] + 2
    assert len(back["bars"]) == back["state"]["index"] + 1  # everything up to the cursor
    assert back["account"]["positions"] == []  # rewinding starts the account again


def test_account_and_report_describe_the_paper_account() -> None:
    with TestClient(app) as client:
        _begin(client)
        placed = client.post(
            "/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 1.0}
        ).json()
        client.post("/api/replay/advance", params={"delta": 4})
        closed = client.delete(f"/api/replay/positions/{placed['order_id']}").json()
        assert closed["ok"]
        account = client.get("/api/replay/account").json()
        report = client.get("/api/replay/report", params={"points": 50}).json()
        trades = client.get("/api/replay/trades").json()

    assert account["trades_total"] == 1 and account["positions"] == []
    assert account["realized"] == pytest.approx(trades[0]["pnl"])
    assert report["account"] == account
    assert report["summary"]["trades"] == 1
    assert report["summary"]["net_profit"] == pytest.approx(trades[0]["pnl"])
    assert report["trades"] == trades
    assert trades[0]["ticket"] == placed["order_id"]
    equity = report["equity"]
    assert 2 <= len(equity) <= 52
    assert equity[0]["value"] == 10_000  # the curve starts at the opening balance
    assert [p["time"] for p in equity] == sorted(p["time"] for p in equity)


def test_reset_account_starts_the_curve_again_at_the_cursor() -> None:
    with TestClient(app) as client:
        _begin(client)
        client.post("/api/replay/advance", params={"delta": 6})
        client.post("/api/replay/reset-account")
        report = client.get("/api/replay/report").json()
    assert len(report["equity"]) == 1
    assert report["equity"][0]["value"] == 10_000
    assert report["summary"]["trades"] == 0


def test_a_replay_that_was_never_started_says_so() -> None:
    state = get_state()
    state.replay = None
    with TestClient(app) as client:
        assert client.post("/api/replay/advance").status_code == 409
        assert client.get("/api/replay/report").status_code == 409


def test_state_reports_the_loaded_window_not_just_the_cursor() -> None:
    with TestClient(app) as client:
        loaded = client.post(
            "/api/replay/load",
            params={"symbol": "EURUSD", "timeframe": "H1", "start": "2026-01-01", "end": "2026-01-02"},
        ).json()
        visible = client.get("/api/replay/bars").json()

    assert loaded["total"] > 20
    assert len(visible) == 1  # at the start only the first bar is revealed...
    assert loaded["last_time"] > loaded["first_time"]  # ...but the state knows the extent
