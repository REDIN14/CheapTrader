"""Shared application state: broker, cache, symbol registry, replay engine."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.broker.base import BrokerAdapter, BrokerError
from app.broker.manager import BrokerManager
from app.config import Settings, get_settings
from app.data.cache import DataCache
from app.data.store import BarStore, default_db_path, store_path_for_broker
from app.data.symbols import SymbolRegistry
from app.indicators.registry import IndicatorRegistry
from app import paths
from app.preferences import preferences
from app.replay.engine import ReplayEngine
from app.replay.profiles import ProfileStore
from app.schemas import TerminalInfo
from app.stream.factory import make_feed
from app.stream.hub import MarketHub
from app.terminals import TerminalWindow
from app.updater import Updater


logger = logging.getLogger(__name__)


@dataclass
class Prepared:
    """A MetaTrader connection that works, waiting to be put to use (see AppState.prepare_metatrader)."""

    adapter: BrokerAdapter
    terminal: TerminalInfo
    cache: DataCache
    symbols: SymbolRegistry


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.broker = BrokerManager(self.settings)
        # "auto" only learns which broker it got once it has connected, so
        # startup() re-points the store if that turns out to be the mock.
        self.cache = DataCache(store=BarStore(default_db_path(self.settings.broker.lower())))
        self.symbols = SymbolRegistry()
        self.indicators = IndicatorRegistry()
        self.replay: ReplayEngine | None = None
        # The paper-trading profiles the replay trades on: they outlive a replay and a restart.
        self.profiles = ProfileStore()
        # Looks for a newer release on GitHub now and then, and installs it when the user says so.
        self.updater = Updater(
            preferences,
            repo=self.settings.update_repo,
            api=self.settings.update_api,
            default_enabled=self.settings.update_check,
            data_dir=paths.data_dir,
        )
        # The live feed (ticks, positions, account); created once a broker is connected.
        self.hub: MarketHub | None = None
        # The MetaTrader window: shown or hidden as the user last chose.
        self.terminal_window = TerminalWindow()
        # One change of broker at a time (see connect_metatrader_now).
        self.switch_lock = asyncio.Lock()

    def end_replay(self) -> None:
        """The replay is over (the user left it, started another, or the program is stopping): the paper
        account closes what is still open at the price under the cursor and keeps the result."""
        engine, self.replay = self.replay, None
        if engine is not None:
            engine.end("session")

    def orders_allowed(self) -> bool:
        """May the app send orders to a real broker? Switched on in the settings (CT_ALLOW_LIVE_ORDERS)
        or by the user in the app (remembered in the preferences). Off, nothing reaches the broker."""
        return bool(self.settings.allow_live_orders or preferences.get("allow_live_orders"))

    def prepare_metatrader(self) -> Prepared | None:
        """Connect to a MetaTrader terminal that has become ready since the app started on the synthetic
        market, without using it yet (this blocks: run it on a thread). None: already on MetaTrader.
        Raises BrokerError, in words the user can act on, when there is nothing to connect to."""
        if self.broker.adapter.name == "mt5":
            return None
        if self.settings.broker.lower() == "mock":
            raise BrokerError("CheapTrader is set to the synthetic market (CT_BROKER=mock), so it does not use MetaTrader.")
        adapter = self.broker.connect_metatrader()
        try:
            terminal = adapter.get_terminal()
            if not terminal.account_login:
                raise BrokerError(
                    "MetaTrader 5 is open, but no account is logged in. In MetaTrader choose "
                    "File > Login to Trade Account, then try again."
                )
            symbols = SymbolRegistry()
            symbols.sync(adapter)
            wanted = store_path_for_broker(default_db_path("mt5"), terminal.company or terminal.account_server)
            cache = DataCache(store=BarStore(wanted))
        except Exception:
            adapter.disconnect()
            raise
        return Prepared(adapter=adapter, terminal=terminal, cache=cache, symbols=symbols)

    def commit_metatrader(self, prepared: Prepared) -> None:
        """Put a prepared MetaTrader connection to use (on the event loop): the prices, history, symbols,
        account and orders are the terminal's from now on, and the screens that are open follow."""
        old = self.broker.adopt(prepared.adapter)
        self.cache = prepared.cache
        self.symbols = prepared.symbols
        self.replay = None  # a replay was made from the other market's bars
        try:
            self.terminal_window.use(prepared.terminal.exe)
            self.terminal_window.keep()
            self.terminal_window.start()
        except Exception:  # noqa: BLE001 - the window is a convenience
            logger.warning("could not take over the terminal's window", exc_info=True)
        if self.hub is not None:
            self.hub.swap_feed(make_feed(prepared.adapter, self.settings))
        if old is not None:
            try:
                old.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("the synthetic market did not close cleanly", exc_info=True)
        logger.info("Switched to MetaTrader 5 (%s)", prepared.terminal.name or "terminal")

    def startup(self) -> None:
        adapter = self.broker.connect()
        # Synthetic bars from the mock adapter must never land in the history
        # that real broker data is cached in (see default_db_path).
        wanted = default_db_path(adapter.name)
        if adapter.name == "mt5":
            try:
                terminal = adapter.get_terminal()
                wanted = store_path_for_broker(wanted, terminal.company or terminal.account_server)
                self.terminal_window.use(terminal.exe)
                self.terminal_window.keep()
                self.terminal_window.start()
            except Exception:  # noqa: BLE001 - neither is worth stopping the app for
                logger.warning("could not read the terminal's details", exc_info=True)
        if self.cache.store.path != wanted:
            self.cache = DataCache(store=BarStore(wanted))
        self.symbols.sync(adapter)
        self.hub = MarketHub(make_feed(adapter, self.settings))
        try:
            # A replay that was cut off (the program was closed in the middle of it) left positions open.
            self.profiles.settle_interrupted()
        except Exception:  # noqa: BLE001 - the profiles are not worth stopping the app for
            logger.warning("could not tidy the paper profiles", exc_info=True)
        self.updater.start()

    def shutdown(self) -> None:
        self.updater.stop()
        try:
            self.end_replay()
        except Exception:  # noqa: BLE001
            logger.warning("could not settle the replay's paper account", exc_info=True)
        self.terminal_window.stop()
        if self.hub is not None:
            self.hub.stop()
        self.broker.disconnect()


_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
