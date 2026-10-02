"""Broker manager: selects and owns the active broker adapter.

Selection logic (``CT_BROKER``):
- ``mt5``  -> force MetaTrader 5 (raises if unavailable)
- ``mock`` -> force the synthetic adapter
- ``auto`` -> try MT5, fall back to mock (default)
"""

from __future__ import annotations

import logging

from app.broker.base import BrokerAdapter, BrokerError
from app.broker.mock_adapter import MockAdapter
from app.config import Settings

logger = logging.getLogger(__name__)


class BrokerManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._adapter: BrokerAdapter | None = None
        # The terminal this manager chose by itself (as against one named in the settings), so that a
        # later attempt may choose again: another terminal may be the one that is open by then.
        self._picked: str | None = None

    @property
    def adapter(self) -> BrokerAdapter:
        if self._adapter is None:
            raise BrokerError("Broker not initialised; call connect() first")
        return self._adapter

    def _pick_terminal(self) -> None:
        """Say which MetaTrader terminal to talk to (every helper process is given the path)."""
        if not self._settings.mt5_autodetect:
            return
        if self._settings.mt5_path and self._settings.mt5_path != self._picked:
            return  # the user named one: that is the one
        try:
            from app import terminals
            from app.preferences import preferences

            path = terminals.choose(
                terminals.detect(),
                saved=preferences.get("terminal_path"),
                server=self._settings.mt5_server,
            )
        except Exception:  # noqa: BLE001 - detection is a convenience; the package can still find one
            logger.warning("could not look for MetaTrader terminals", exc_info=True)
            return
        if path:
            logger.info("MetaTrader terminal: %s", path)
            self._settings.mt5_path = path
            self._picked = path

    def connect_metatrader(self) -> BrokerAdapter:
        """Connect to a MetaTrader terminal and return the adapter (not yet the one in use). Raises when
        there is none to talk to, or it will not answer."""
        self._pick_terminal()
        from app.broker.isolated import IsolatedMT5Adapter
        from app.broker.mt5_adapter import MT5Adapter

        adapter: MT5Adapter = (
            IsolatedMT5Adapter(self._settings) if self._settings.mt5_isolate else MT5Adapter(self._settings)
        )
        adapter.connect()
        return adapter

    def adopt(self, adapter: BrokerAdapter) -> BrokerAdapter | None:
        """Use this adapter from now on; the one that was in use is returned (to be let go of by the caller)."""
        old, self._adapter = self._adapter, adapter
        return old

    def connect(self) -> BrokerAdapter:
        choice = self._settings.broker.lower()

        if choice == "mock":
            return self._connect_mock()

        if choice in ("mt5", "auto"):
            try:
                adapter = self.connect_metatrader()
                self._adapter = adapter
                logger.info("Using MetaTrader 5 broker adapter")
                return adapter
            except Exception as exc:  # noqa: BLE001 - fall back deliberately
                if choice == "mt5":
                    raise
                logger.warning("MT5 unavailable (%s); falling back to mock adapter", exc)

        return self._connect_mock()

    def _connect_mock(self) -> BrokerAdapter:
        self._adapter = MockAdapter(
            tick_rate=self._settings.mock_tick_rate, volatility=self._settings.mock_volatility
        )
        self._adapter.connect()
        logger.info("Using mock broker adapter")
        return self._adapter

    def disconnect(self) -> None:
        if self._adapter is not None:
            self._adapter.disconnect()
            self._adapter = None
