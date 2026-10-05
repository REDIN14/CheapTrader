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
