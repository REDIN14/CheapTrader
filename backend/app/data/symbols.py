"""Universal symbol synchronisation from the broker."""

from __future__ import annotations

import logging

from app.broker.base import BrokerAdapter
from app.schemas import Symbol

logger = logging.getLogger(__name__)


class SymbolRegistry:
    """Keeps the full broker symbol list in memory and supports search."""

    def __init__(self) -> None:
        self._symbols: dict[str, Symbol] = {}

    def sync(self, broker: BrokerAdapter) -> list[Symbol]:
        symbols = broker.list_symbols()
        self._symbols = {s.name: s for s in symbols}
        logger.info("Synced %d symbols from broker", len(self._symbols))
        return symbols

    def all(self) -> list[Symbol]:
        return list(self._symbols.values())

    def get(self, name: str) -> Symbol | None:
        return self._symbols.get(name)

    def search(self, query: str, limit: int = 50) -> list[Symbol]:
        q = query.upper()
        matches = [
            s
            for s in self._symbols.values()
            if q in s.name.upper() or q in s.description.upper()
        ]
        return matches[:limit]

    def __len__(self) -> int:
        return len(self._symbols)
