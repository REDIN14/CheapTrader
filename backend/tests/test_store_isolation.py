"""The mock broker's synthetic bars must never share a file with real history."""

from __future__ import annotations

from app.config import Settings
from app.data.store import default_db_path
from app.schemas import Timeframe
from app.state import AppState


def test_mock_and_real_sources_use_different_files() -> None:
    assert default_db_path("mock") != default_db_path("mt5")
    assert default_db_path("mock").name == "bars.mock.db"
    assert default_db_path("mt5").name == "bars.db"


def test_explicit_mock_broker_uses_the_mock_store() -> None:
    state = AppState(Settings(broker="mock"))
    state.startup()
    try:
        assert state.cache.store.path == default_db_path("mock")
    finally:
        state.shutdown()


def test_auto_falling_back_to_mock_switches_store(monkeypatch) -> None:
    """``auto`` starts on the real store and must move off it if MT5 is missing."""
    from app.broker import isolated, mt5_adapter
    from app.broker.base import BrokerError

    def no_terminal(self) -> None:
        raise BrokerError("no terminal")

    # Simulate a machine without a running MetaTrader terminal, so the test never
    # touches a real one: neither in this process (CT_MT5_ISOLATE=false) nor in the
    # reading process the server normally starts.
    monkeypatch.setattr(mt5_adapter.MT5Adapter, "connect", no_terminal)
    monkeypatch.setattr(isolated.TradeProcess, "start", no_terminal)

    state = AppState(Settings(broker="auto"))
    assert state.cache.store.path == default_db_path("mt5")  # not known yet

    state.startup()
    try:
        assert state.broker.adapter.name == "mock"
        assert state.cache.store.path == default_db_path("mock")
    finally:
        state.shutdown()


def test_mock_bars_are_written_to_the_mock_file_only() -> None:
    state = AppState(Settings(broker="mock"))
    state.startup()
    try:
        state.cache.get_bars(state.broker.adapter, "EURUSD", Timeframe.H1, count=20)
        assert default_db_path("mock").exists()
        assert state.cache.store.coverage("EURUSD", Timeframe.H1).count >= 20
        # The real file was never even created by this run.
        assert not default_db_path("mt5").exists()
    finally:
        state.shutdown()
