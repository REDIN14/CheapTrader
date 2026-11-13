"""Paged chart/replay history, historical indicators and the MT5 invalid-range fallback."""

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.broker.mt5_adapter import MT5Adapter
from app.config import Settings
from app.data.store import BarStore
from app.main import app
from app.replay.engine import ReplayEngine
from app.schemas import Bar, BarPage, IndicatorResult, OrderRequest, Timeframe
from app.state import get_state


def bar(time: int, close: float = 100) -> Bar:
    return Bar(time=time, open=close, high=close + 1, low=close - 1, close=close)


def test_paging_can_pass_100000_bars_and_stops_only_at_the_brokers_history(monkeypatch) -> None:
    first = 1_600_000_000 // 60 * 60
    source = [bar(first + i * 60) for i in range(120_100)]
    with TestClient(app) as client:
        state = get_state()

        def history(symbol, timeframe, count=500, start=None, end=None):
            if start is not None:
                return [b for b in source if int(start.timestamp()) <= b.time <= int(end.timestamp())]
            return [b for b in source if end is None or b.time <= int(end.timestamp())][-count:]

        monkeypatch.setattr(state.broker.adapter, "get_bars", history)
        loaded = client.get("/api/bars", params={"symbol": "EURUSD", "timeframe": "M1", "count": 1500}).json()
        while True:
            response = client.get("/api/bars/history", params={
                "symbol": "EURUSD", "timeframe": "M1", "before": loaded[0]["time"], "count": 20_000,
            })
            assert response.status_code == 200, response.text
            page = response.json()
            loaded = page["bars"] + loaded
            if not page["has_more"]:
                break
        assert len(loaded) == len(source) > 100_000
        assert len({b["time"] for b in loaded}) == len(source)
        assert loaded[0]["time"] == first


def test_replay_can_start_a_year_before_the_live_window_and_prepend_without_moving_trades() -> None:
    when = int(datetime(2025, 11, 6, tzinfo=timezone.utc).timestamp())
    with TestClient(app) as client:
        client.get("/api/bars", params={"symbol": "EURUSD", "timeframe": "M1", "count": 1500})
        response = client.post("/api/replay/start", params={
            "symbol": "EURUSD", "timeframe": "M1", "time": when, "lookback": 5, "lookahead": 5,
        })
        assert response.status_code == 200, response.text
        started = response.json()
        assert started["state"]["cursor_time"] == when
        client.post("/api/replay/orders", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.1})
        account = client.get("/api/replay/account").json()
        older = client.post("/api/replay/history", params={"count": 50}).json()
        assert older["state"]["cursor_time"] == when
        assert older["state"]["index"] == started["state"]["index"] + 50
        assert len(older["bars"]) == len(started["bars"]) + 50
        assert older["bars"][-1] == started["bars"][-1]
        assert older["account"] == account and older["closed"] == []


def test_playing_past_a_loaded_window_fetches_more_and_honours_stops(monkeypatch) -> None:
    with TestClient(app) as client:
        engine = ReplayEngine.from_bars("EURUSD", Timeframe.M1, [bar(60), bar(120)])
        engine.begin(0)
        engine.has_more_after = True
        engine.paper.place(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1, tp=105), engine.current_bar)
        get_state().replay = engine
        monkeypatch.setattr(get_state().cache, "history_after", lambda *args: BarPage(
            bars=[bar(180, 106), bar(240, 108)], has_more=False,
        ))
        reply = client.post("/api/replay/advance", params={"delta": 3})
        assert reply.status_code == 200, reply.text
        update = reply.json()
        assert update["state"]["cursor_time"] == 240
        assert update["state"]["total"] == 4 and not update["state"]["has_more_after"]
        assert update["closed"][0]["reason"] == "tp"
        assert update["closed"][0]["exit_time"] == 180


def test_a_range_outside_cached_history_never_downloads_the_intervening_year(tmp_path) -> None:
    store = BarStore(tmp_path / "bars.db")
    store.upsert("AUDCAD", Timeframe.M1, [bar(1_800_000_000)])
    calls = []

    def fetch(symbol, timeframe, count=500, start=None, end=None):
        calls.append((int(start.timestamp()), int(end.timestamp())))
        return [bar(int(start.timestamp()))]

    broker = SimpleNamespace(get_bars=fetch)
    start = datetime(2025, 11, 6, tzinfo=timezone.utc)
    end = datetime(2025, 11, 6, 0, 1, tzinfo=timezone.utc)
    store.ensure_range(broker, "AUDCAD", Timeframe.M1, start, end)
    assert calls and all(int(start.timestamp()) <= a <= b <= int(end.timestamp()) for a, b in calls)


def test_a_window_between_separate_cached_islands_is_actually_fetched(tmp_path) -> None:
    store = BarStore(tmp_path / "bars.db")
    store.upsert("AUDCAD", Timeframe.M1, [bar(100), bar(10_000)])
    calls = []

    def fetch(symbol, timeframe, count=500, start=None, end=None):
        calls.append((int(start.timestamp()), int(end.timestamp())))
        return [bar(t) for t in range(5000, 5301, 60)]

    bars = store.ensure_range(SimpleNamespace(get_bars=fetch), "AUDCAD", Timeframe.M1,
                              datetime.fromtimestamp(5000, timezone.utc), datetime.fromtimestamp(5300, timezone.utc))
    assert len(bars) == 6 and calls == [(5000, 5300)]


def test_invalid_mt5_range_parameters_fall_back_to_small_dated_requests() -> None:
    rows = [{"time": i * 60, "open": 1, "high": 2, "low": 0, "close": 1,
             "tick_volume": 1, "spread": 0, "real_volume": 0} for i in range(4000)]
    calls = []

    def dated(symbol, tf, until, count):
        assert type(until) is int and type(count) is int and count <= 1500
        calls.append(until)
        return [r for r in rows if r["time"] <= until][-count:]

    broker = MT5Adapter(Settings(broker="mock"))
    broker._connected = True
    broker._mt5 = SimpleNamespace(TIMEFRAME_M1=1, copy_rates_range=lambda *args: None,
                                  last_error=lambda: (-2, "Terminal: Invalid params"), copy_rates_from=dated)
    bars = broker.get_bars("AUDCAD", Timeframe.M1, start=datetime.fromtimestamp(60, timezone.utc),
                           end=datetime.fromtimestamp(3999 * 60, timezone.utc))
    assert len(bars) == 3999 and len(calls) == 3
    assert bars[0].time == 60 and bars[-1].time == 3999 * 60


def test_an_indicator_receives_its_historical_window_past_the_old_count_cap(monkeypatch) -> None:
    from app.api import indicator_routes

    source = [bar(1_500_000_000 + i * 60) for i in range(100_001)]
    observed = []

    def compute(**kwargs):
        observed.append(kwargs)
        return IndicatorResult(id="builtin.sma", name="SMA", overlay=True, pane=0, plots=[])

    with TestClient(app) as client:
        monkeypatch.setattr(get_state().cache, "ensure_range", lambda *args: source)
        monkeypatch.setattr(indicator_routes, "run_indicator", compute)
        reply = client.post("/api/indicators/builtin.sma/run", params={
            "symbol": "EURUSD", "timeframe": "M1", "count": 100_000,
            "start": source[0].time, "end": source[-1].time,
        })
        assert reply.status_code == 200, reply.text
    assert len(observed[0]["bars"]) == 100_001
    assert observed[0]["show_from"] == source[0].time
