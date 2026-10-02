"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=paths.env_file(), env_prefix="CT_", extra="ignore")

    # Broker
    broker: str = "auto"  # auto | mt5 | mock
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None
    # Without mt5_path, look for the MetaTrader terminal to use (app/terminals.py): the one the user
    # picked in the app, else a running one, else the one used last. Off: leave it to the package.
    mt5_autodetect: bool = True

    # Safety: when False, order placement is rejected (paper-only).
    allow_live_orders: bool = False

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    backend_url: str = "http://127.0.0.1:8000"

    # Streaming (see app/stream): how often the feed looks for new ticks, and for a
    # change in the account or the open positions. Both are cheap reads (tens of
    # microseconds on MetaTrader), so the feed can afford to look often.
    feed_interval: float = 0.005
    state_interval: float = 0.05
    # MetaTrader's Python package holds Python's global lock for the whole of every
    # call, so a slow one (an order waiting for the broker, a long history read)
    # freezes the whole process. With this on, the live feed and the trading calls
    # each run in a process of their own and the server only relays.
    mt5_isolate: bool = True

    # Mock broker: how fast its market ticks, and how far it moves (a "volatile
    # session" is e.g. 40 and 3).
    mock_tick_rate: float = 8.0
    mock_volatility: float = 1.0

    # Indicator sandbox
    indicator_timeout: float = 10.0
    indicator_memory_mb: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()
