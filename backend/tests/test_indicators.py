"""Tests for the indicator sandbox and registry."""

from __future__ import annotations

from app.broker.mock_adapter import MockAdapter
from app.indicators.registry import IndicatorRegistry
from app.indicators.sandbox import run_indicator
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
