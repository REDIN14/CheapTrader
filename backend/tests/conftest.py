"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep every test away from the real ``backend/data`` folder.

    The app singleton opens a bar store as soon as it is created. Without this a
    test that drives the API (even with the mock broker) writes into the same
    database file the real chart history lives in.
    """
    import app.data.store as store
    import app.state as app_state

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app_state, "_state", None)
    # the preferences file and the logs follow paths.data_dir(), which reads this
    monkeypatch.setenv("CT_DATA_DIR", str(tmp_path / "data"))
    # no test may go looking for the real MetaTrader terminals installed on this PC
    monkeypatch.setenv("CT_MT5_AUTODETECT", "false")
    # the test client calls the app "testserver"
    monkeypatch.setenv("CT_ALLOWED_HOSTS", "testserver")
