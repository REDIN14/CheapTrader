"""Broker adapter interface.

All broker integrations (MetaTrader 5, mock, future brokers) implement this
interface so the rest of the application is broker-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas import (
    AccountInfo,
    Bar,
    Deal,
    ModifyOrderRequest,
    ModifyRequest,
    OrderRequest,
    OrderResult,
    PendingOrder,
    Position,
    Symbol,
    TerminalInfo,
    Tick,
    Timeframe,
)


class BrokerError(RuntimeError):
    """Raised when a broker operation fails."""


class BrokerAdapter(ABC):
    """Abstract broker interface."""

    name: str = "base"

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection to the broker terminal."""

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the adapter currently has a live connection."""

    @abstractmethod
    def list_symbols(self) -> list[Symbol]:
        """Return every instrument offered by the broker."""

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Return OHLCV bars, either the most recent ``count`` or a date range."""

    @abstractmethod
    def get_tick(self, symbol: str) -> Tick | None:
        """Return the latest tick for a symbol."""

    @abstractmethod
    def get_ticks(
        self,
        symbol: str,
        start: datetime,
        count: int = 1000,
    ) -> list[Tick]:
        """Return recent ticks starting at ``start``."""

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """Return account information."""

    @abstractmethod
    def get_positions(self, symbol: str | None = None) -> list[Position]:
        """Return open positions, optionally filtered by symbol."""

    def get_deals(self) -> list[Deal]:
        """The account's history as the broker has it: every fill and every operation on the balance, oldest first.

        (What the performance report is made from; a broker that keeps no history has none.)
        """
        return []

    def get_terminal(self) -> TerminalInfo:
        """What the trading terminal reports about itself (the mock has none)."""
        return TerminalInfo(connected=self.connected, name=self.name)

    def get_symbol(self, name: str) -> Symbol | None:
        """One instrument as the broker describes it right now (its tick value moves with the exchange rates)."""
        return next((s for s in self.list_symbols() if s.name == name), None)

    def get_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        """The pending (limit / stop) orders that are waiting, optionally of one symbol."""
        return []

    def cancel_order(self, ticket: int) -> OrderResult:
        """Take a pending order back."""
        return OrderResult(ok=False, error="This broker has no pending orders.")

    def modify_order(self, request: ModifyOrderRequest) -> OrderResult:
        """Move a pending order, or change its stop and target."""
        return OrderResult(ok=False, error="This broker has no pending orders.")

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit a market or pending order."""

    @abstractmethod
    def modify_position(self, request: ModifyRequest) -> OrderResult:
        """Modify SL/TP of an open position."""

    @abstractmethod
    def close_position(self, ticket: int) -> OrderResult:
        """Close an open position by ticket."""
