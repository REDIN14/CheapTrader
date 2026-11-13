"""Native replay candles must remain usable when finer MT5 history is missing."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.replay.engine import ReplayEngine
from app.schemas import Bar, BarPage, Timeframe
from app.state import get_state


@pytest.mark.parametrize("missing", ["empty", "error"])
@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_switch_from_four_hours_does_not_require_minute_or_tick_detail(monkeypatch, timeframe, missing) -> None:
    when = int(datetime(2025, 11, 6, 4, tzinfo=timezone.utc).timestamp())
    with TestClient(app) as client:
        started = client.post("/api/replay/start", params={
            "symbol": "EURUSD", "timeframe": "H4", "time": when, "lookback": 12, "lookahead": 8,
        })
        assert started.status_code == 200, started.text
        order = client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1}).json()
        assert order["ok"]
        account = client.get("/api/replay/account").json()
        report = client.get("/api/replay/report").json()
        engine = get_state().replay
        ensure = get_state().cache.ensure_range

        def limited(broker, symbol, interval, start, end):
            if interval in (Timeframe.M1, Timeframe.S1) and (
                interval != timeframe or (interval == Timeframe.M1 and (end - start).total_seconds() < 60)
            ):
                if missing == "error":
                    raise RuntimeError("Terminal: Call failed")
                return []
            return ensure(broker, symbol, interval, start, end)

        monkeypatch.setattr(get_state().cache, "ensure_range", limited)
        response = client.post("/api/replay/timeframe", params={"timeframe": timeframe.value, "lookback": 12, "lookahead": 8})
        assert response.status_code == 200, response.text
        changed = response.json()
        assert get_state().replay is engine
        assert changed["state"]["timeframe"] == timeframe.value
        assert changed["state"]["cursor_time"] == when
        assert changed["account"] == account and changed["closed"] == []
        assert changed["bars"][-1]["close"] == started.json()["bars"][-1]["close"]
        assert client.get("/api/replay/report").json() == report
        assert client.post("/api/replay/advance").status_code == 200


def candle(time, high=105, low=95):
    return Bar(time=time, open=100, high=high, low=low, close=100)


def target_window(monkeypatch, current, following):
    state = get_state()
    monkeypatch.setattr(state.cache, "history_before", lambda *args: BarPage(bars=[current], has_more=False))
    monkeypatch.setattr(state.cache, "history_after", lambda *args: BarPage(bars=[following], has_more=False))


def test_missing_minutes_reuses_source_candles_without_replaying_past_stops(monkeypatch) -> None:
    with TestClient(app) as client:
        engine = ReplayEngine.from_bars("EURUSD", Timeframe.H4, [
            candle(0, low=10), candle(14400), candle(28800, high=999, low=89),
        ])
        engine.begin(1)
        get_state().replay = engine
        client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1, "sl": 90})
        account = client.get("/api/replay/account").json()
        target_window(monkeypatch, candle(0, high=999, low=1), candle(86400))
        monkeypatch.setattr(get_state().cache, "ensure_range", lambda *args: [])

        response = client.post("/api/replay/timeframe", params={"timeframe": "D1"})
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["account"] == account
        assert changed["bars"][-1]["high"] == 105 and changed["bars"][-1]["low"] == 10
        moved = client.post("/api/replay/advance").json()
        assert moved["closed"][0]["reason"] == "sl" and moved["closed"][0]["exit_time"] == 28800


def test_missing_tick_detail_uses_seconds_already_loaded_in_the_replay(monkeypatch) -> None:
    with TestClient(app) as client:
        engine = ReplayEngine.from_bars("EURUSD", Timeframe.S5, [candle(3617), candle(3640, high=999, low=89)])
        engine.begin(0)
        get_state().replay = engine
        client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1, "sl": 90})
        target_window(monkeypatch, candle(3600, high=999, low=1), candle(7200))

        def detail(broker, symbol, interval, start, end):
            return [candle(3600, high=999, low=1)] if interval == Timeframe.M1 else []

        monkeypatch.setattr(get_state().cache, "ensure_range", detail)
        response = client.post("/api/replay/timeframe", params={"timeframe": "H1"})
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["state"]["cursor_time"] == 3617
        assert changed["bars"][-1]["high"] == 105 and changed["bars"][-1]["low"] == 95
        assert changed["closed"] == [] and len(changed["account"]["positions"]) == 1
        moved = client.post("/api/replay/advance").json()
        assert moved["closed"][0]["exit_time"] == 3640


def test_no_finer_data_keeps_the_price_without_showing_future_target_extremes(monkeypatch) -> None:
    with TestClient(app) as client:
        engine = ReplayEngine.from_bars("EURUSD", Timeframe.H4, [candle(3617)])
        engine.begin(0)
        get_state().replay = engine
        client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1, "sl": 90})
        target_window(monkeypatch, candle(3600, high=999, low=1), candle(3900))
        monkeypatch.setattr(get_state().cache, "ensure_range", lambda *args: [])
        response = client.post("/api/replay/timeframe", params={"timeframe": "M5"})
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["state"]["cursor_time"] == 3617
        assert changed["bars"][-1]["high"] == changed["bars"][-1]["low"] == changed["bars"][-1]["close"] == 100
        moved = client.post("/api/replay/advance").json()
        assert moved["closed"] == [] and len(moved["account"]["positions"]) == 1
