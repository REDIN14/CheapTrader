"""Tests for the indicator sandbox and registry."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.broker.mock_adapter import MockAdapter
from app.indicators.needs import MAX_INDICATOR_BARS, bars_to_load, declared_bars
from app.indicators.registry import IndicatorRegistry
from app.indicators.sandbox import run_indicator
from app.main import app
from app.schemas import IndicatorSpec, Timeframe


def _bars(count: int = 100):
    broker = MockAdapter()
    broker.connect()
    return broker.get_bars("EURUSD", Timeframe.H1, count=count)


def test_sma_indicator_runs() -> None:
    code = '''
def compute(df, params):
    period = int(params.get("period", 5))
    return {"SMA": df["close"].rolling(period).mean()}
'''
    result = run_indicator("t", "SMA", code, _bars(), params={"period": 5})
    assert result.error is None
    assert len(result.plots) == 1
    assert result.plots[0]["name"] == "SMA"
    assert len(result.plots[0]["data"]) > 0


def test_multiple_plots() -> None:
    code = '''
def compute(df, params):
    return {"a": df["close"], "b": df["open"]}
'''
    result = run_indicator("t", "Multi", code, _bars())
    assert result.error is None
    assert {p["name"] for p in result.plots} == {"a", "b"}


def test_blocked_import() -> None:
    code = '''
import os

def compute(df, params):
    return {"x": df["close"]}
'''
    result = run_indicator("t", "Evil", code, _bars())
    assert result.error is not None
    assert "not allowed" in result.error


def test_missing_compute() -> None:
    result = run_indicator("t", "Bad", "x = 1\n", _bars())
    assert result.error is not None
    assert "compute" in result.error


def test_runtime_error_reported() -> None:
    code = '''
def compute(df, params):
    raise ValueError("boom")
'''
    result = run_indicator("t", "Boom", code, _bars())
    assert result.error is not None
    assert "boom" in result.error


def test_timeout() -> None:
    code = '''
def compute(df, params):
    while True:
        pass
'''
    from app.config import Settings

    settings = Settings(indicator_timeout=1.0)
    result = run_indicator("t", "Loop", code, _bars(), settings=settings)
    assert result.error is not None
    assert "timed out" in result.error


def test_registry_crud(tmp_path) -> None:
    registry = IndicatorRegistry(data_dir=tmp_path)
    assert len(registry.builtins()) >= 5

    spec = registry.save(IndicatorSpec(id="", name="My Ind", code="def compute(df, p): return {}"))
    assert spec.id.startswith("user.")

    fetched = registry.get(spec.id)
    assert fetched is not None and fetched.name == "My Ind"

    assert registry.delete(spec.id) is True
    assert registry.get(spec.id) is None

    # Built-ins cannot be deleted.
    assert registry.delete("builtin.sma") is False


def test_a_bare_series_or_array_is_one_line() -> None:
    code = '''
import numpy as np

def compute(df, params):
    return df["close"] - df["open"] if params.get("series", True) else np.asarray(df["close"])
'''
    for use_series in (True, False):
        result = run_indicator("t", "Bare", code, _bars(), params={"series": use_series})
        assert result.error is None, result.error
        assert [p["name"] for p in result.plots] == ["plot"] and len(result.plots[0]["data"]) > 50


# -- how many bars an indicator is run over --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code,expected",
    [
        ("NEEDS_BARS = 5000\n\ndef compute(df, p): ...\n", 5000),
        ("NEEDS_BARS = 5_000", 5000),
        ("NEEDS_BARS = 50 * 1000", 50000),
        ("NEEDS_BARS = 20 * 1_000 + 500", 20500),
        ("NEEDS_BARS = 2 * (3000 - 500) // 2", 2500),
        ("NEEDS_BARS: int = 3000", 3000),
        ("NEEDS_BARS = 100\nNEEDS_BARS = 200", 200),  # the last one wins, as in Python
        ("", None),
        ("def compute(df, p): ...", None),
        ("NEEDS_BARS = 0", None),
        ("NEEDS_BARS = -5", None),
        ("NEEDS_BARS = 12.5", None),
        ("NEEDS_BARS = True", None),
        ("NEEDS_BARS = 'many'", None),
        ("NEEDS_BARS = int('5')", None),  # worked out by running something: not read
        ("NEEDS_BARS = 2 ** 20", None),
        ("NEEDS_BARS = 10 // 0", None),
        ("def f():\n    NEEDS_BARS = 9000", None),  # only a line at the top level counts
        ("class A:\n    NEEDS_BARS = 9000", None),
        ("NEEDS_BARS = (", None),  # it does not even parse
        ("x = 1\0", None),
    ],
)
def test_the_number_of_bars_an_indicator_needs_is_read_from_its_code(code: str, expected: int | None) -> None:
    assert declared_bars(code) == expected


def test_reading_what_an_indicator_needs_runs_nothing() -> None:
    assert declared_bars("raise SystemExit('this must not run')\nNEEDS_BARS = 7000") == 7000


def test_how_many_bars_are_loaded() -> None:
    assert bars_to_load(500, None) == 500
    assert bars_to_load(500, 3000) == 3000  # it needs more than is shown: the others only warm it up
    assert bars_to_load(20_000, 3000) == 20_000  # the chart is deeper than it needs
    assert bars_to_load(500, 10**9) == MAX_INDICATOR_BARS
    assert bars_to_load(100_000, 150_000) == 150_000


SMA_50 = """
def compute(df, params):
    return {"SMA": df["close"].rolling(50).mean()}
"""


def test_the_bars_before_show_from_only_warm_the_indicator_up() -> None:
    bars = _bars(300)
    whole = run_indicator("t", "SMA", SMA_50, bars)
    cut = run_indicator("t", "SMA", SMA_50, bars, show_from=bars[200].time)
    assert whole.error is None and cut.error is None
    data = cut.plots[0]["data"]
    assert len(data) == 100 and data[0]["time"] == bars[200].time  # the lines start at the bar asked for ...
    assert data == whole.plots[0]["data"][-100:]  # ... with the values the longer run gave them
    # without the bars before, the same lines would start with nothing (50 bars to warm up)
    alone = run_indicator("t", "SMA", SMA_50, bars[200:])
    assert len(alone.plots[0]["data"]) == 100 - 49


def test_a_timeout_says_how_many_bars_it_was_over() -> None:
    from app.config import Settings

    code = "def compute(df, params):\n    while True:\n        pass\n"
    result = run_indicator("t", "Loop", code, _bars(120), settings=Settings(indicator_timeout=1.0))
    assert result.error is not None and "timed out after 1.0s over 120 bars" in result.error


LONG_SMA = """
NEEDS_BARS = 1500


def compute(df, params):
    return {"SMA": df["close"].rolling(1000).mean()}
"""


def _save(client: TestClient, code: str) -> str:
    made = client.post("/api/indicators", json={"id": "", "name": "Long", "code": code, "overlay": True, "pane": 0, "params": {}})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def test_the_route_runs_an_indicator_over_the_bars_it_needs_and_returns_the_lines_over_the_ones_asked_for() -> None:
    with TestClient(app) as client:
        wanting = _save(client, LONG_SMA)
        silent = _save(client, LONG_SMA.replace("NEEDS_BARS = 1500", "pass"))
        params = {"symbol": "EURUSD", "timeframe": "H1", "count": 200}
        shown = client.post(f"/api/indicators/{wanting}/run", params=params).json()
        assert shown["error"] is None, shown["error"]
        # the 200 bars asked for, all with a value: the 1300 before them warmed a 1000-bar average up
        assert len(shown["plots"][0]["data"]) == 200
        # an indicator that says nothing is run over the 200 and has no 1000-bar average to show
        plain = client.post(f"/api/indicators/{silent}/run", params=params).json()
        assert plain["error"] is None and plain["plots"][0]["data"] == []


def test_the_route_gives_an_indicator_as_deep_a_chart_as_there_is() -> None:
    with TestClient(app) as client:
        deep = client.post("/api/indicators/builtin.sma/run", params={"symbol": "EURUSD", "timeframe": "H1", "count": 25_000})
        assert deep.status_code == 200, deep.text
        body = deep.json()
        # more than the 20,000 an indicator could be given before; a 20-bar average has no value for its first 19
        assert body["error"] is None and len(body["plots"][0]["data"]) == 25_000 - 19
        for count in (100_001, 0, -3):
            refused = client.post("/api/indicators/builtin.sma/run", params={"symbol": "EURUSD", "timeframe": "H1", "count": count})
            assert refused.status_code == 422, count


# -- changing an indicator's settings ---------------------------------------------------------------------------------
PERIOD_SMA = """
def compute(df, params):
    return {"SMA": df["close"].rolling(int(params.get("period", 5))).mean()}
"""
RUN_200 = {"symbol": "EURUSD", "timeframe": "H1", "count": 200}


def _points(client: TestClient, indicator_id: str) -> int:
    body = client.post(f"/api/indicators/{indicator_id}/run", params=RUN_200).json()
    assert body["error"] is None, body["error"]
    return len(body["plots"][0]["data"])


def test_saving_the_settings_of_an_indicator_changes_what_it_draws() -> None:
    """What the settings send when Save is pressed: no id in the body (it is in the address). It was refused (422,
    "Field required") every time, so a change of the settings never did anything."""
    with TestClient(app) as client:
        made = client.post("/api/indicators", json={"name": "Mine", "code": PERIOD_SMA, "overlay": True, "params": {"period": 5}}).json()
        assert _points(client, made["id"]) == 200 - 4
        saved = client.put(f"/api/indicators/{made['id']}", json={"name": "Mine, longer", "code": PERIOD_SMA, "overlay": True, "params": {"period": 50}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["params"] == {"period": 50} and saved.json()["name"] == "Mine, longer"
        assert client.get(f"/api/indicators/{made['id']}").json()["params"] == {"period": 50}
        assert _points(client, made["id"]) == 200 - 49  # the chart draws it with the new period
        # only what is given changes
        renamed = client.put(f"/api/indicators/{made['id']}", json={"name": "Renamed"}).json()
        assert renamed["name"] == "Renamed" and renamed["params"] == {"period": 50} and renamed["code"] == PERIOD_SMA
        assert client.put(f"/api/indicators/{made['id']}", json={"name": "  "}).status_code == 400
        assert client.put("/api/indicators/user.nothere", json={"params": {"period": 3}}).status_code == 404


def test_a_built_in_takes_new_parameters_and_keeps_its_code() -> None:
    with TestClient(app) as client:
        before = client.get("/api/indicators/builtin.sma").json()
        assert before["params"] == {"period": 20} and before["defaults"] == {"period": 20}
        assert _points(client, "builtin.sma") == 200 - 19
        # what the settings send: the built-in's own name, code and kind, and the new period (typed, so maybe text)
        saved = client.put("/api/indicators/builtin.sma", json={**{k: before[k] for k in ("name", "code", "overlay")}, "params": {"period": "50"}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["params"] == {"period": 50} and saved.json()["defaults"] == {"period": 20}
        assert _points(client, "builtin.sma") == 200 - 49
        listed = next(s for s in client.get("/api/indicators").json() if s["id"] == "builtin.sma")
        assert listed["params"] == {"period": 50}
        # back to its own value: nothing is kept
        back = client.put("/api/indicators/builtin.sma", json={"params": {"period": 20}}).json()
        assert back["params"] == {"period": 20}
        assert _points(client, "builtin.sma") == 200 - 19


def test_some_of_a_built_ins_parameters_can_be_changed_and_the_others_keep_theirs() -> None:
    with TestClient(app) as client:
        client.put("/api/indicators/builtin.macd", json={"params": {"slow": 40}})
        assert client.put("/api/indicators/builtin.macd", json={"params": {"signal": 5}}).json()["params"] == {"fast": 12, "slow": 40, "signal": 5}
        bands = client.put("/api/indicators/builtin.bollinger", json={"params": {"std": 2.5}}).json()
        assert bands["params"] == {"period": 20, "std": 2.5}


@pytest.mark.parametrize(
    "indicator,change,words",
    [
        ("builtin.sma", {"code": "def compute(df, params):\n    return {}\n"}, "code of a built-in indicator cannot be changed"),
        ("builtin.sma", {"name": "My SMA"}, "Only the parameters"),
        ("builtin.sma", {"overlay": False}, "Only the parameters"),
        ("builtin.sma", {"params": {"length": 9}}, "no parameter called 'length'"),
        ("builtin.sma", {"params": {"period": 0}}, "from 1 to"),
        ("builtin.sma", {"params": {"period": -3}}, "from 1 to"),
        ("builtin.sma", {"params": {"period": 12.5}}, "whole number"),
        ("builtin.sma", {"params": {"period": "abc"}}, "whole number"),
        ("builtin.sma", {"params": {"period": True}}, "whole number"),
        ("builtin.bollinger", {"params": {"std": 0}}, "above 0"),
        ("builtin.bollinger", {"params": {"std": "x"}}, "above 0"),
    ],
)
def test_what_a_built_in_will_not_take(indicator: str, change: dict, words: str) -> None:
    with TestClient(app) as client:
        refused = client.put(f"/api/indicators/{indicator}", json=change)
        assert refused.status_code == 400 and words in refused.json()["detail"], refused.text
        assert client.get(f"/api/indicators/{indicator}").json()["params"] == client.get(f"/api/indicators/{indicator}").json()["defaults"]


def test_a_built_in_comes_back_as_it_was_set_after_a_restart(tmp_path) -> None:
    from app.schemas import IndicatorUpdate

    IndicatorRegistry(data_dir=tmp_path).update("builtin.rsi", IndicatorUpdate(params={"period": 9}))
    assert IndicatorRegistry(data_dir=tmp_path).get("builtin.rsi").params == {"period": 9}
    # and it is not listed as an indicator of the user's own
    assert [s.id for s in IndicatorRegistry(data_dir=tmp_path).list()].count("builtin.rsi") == 1


@pytest.mark.parametrize("content", ["not json", '{"params": {"period": -1}}', '{"params": ["x"]}', '["x"]', '{"params": {"nope": 3}}'])
def test_a_settings_file_edited_by_hand_cannot_break_a_built_in(tmp_path, content: str) -> None:
    (tmp_path / "builtin").mkdir()
    (tmp_path / "builtin" / "builtin.sma.json").write_text(content, encoding="utf-8")
    assert IndicatorRegistry(data_dir=tmp_path).get("builtin.sma").params == {"period": 20}


def test_a_run_says_which_parameters_it_used() -> None:
    with TestClient(app) as client:
        client.put("/api/indicators/builtin.bollinger", json={"params": {"period": 30}})
        body = client.post("/api/indicators/builtin.bollinger/run", params=RUN_200).json()
        assert body["params"] == {"period": 30, "std": 2.0}


@pytest.mark.parametrize("bad", ["..%5C..%5Cevil", "a b", "%2E%2E"])
def test_an_id_that_could_name_another_file_is_refused(bad: str) -> None:
    with TestClient(app) as client:
        assert client.put(f"/api/indicators/{bad}", json={"name": "x", "code": "def compute(df, p): ..."}).status_code in (400, 404)
        assert client.get(f"/api/indicators/{bad}").status_code == 404
        assert client.post("/api/indicators", json={"id": "..\\evil", "name": "x", "code": "def compute(df, p): ..."}).status_code == 400
