"""Which feed fits the broker that is connected."""

from __future__ import annotations

from app.broker.base import BrokerAdapter
from app.config import Settings
from app.procutil import module_command
from app.stream.feed import Feed, ProcessFeed, ThreadFeed


def make_feed(adapter: BrokerAdapter, settings: Settings) -> Feed:
    if adapter.name == "mt5" and settings.mt5_isolate:
        from app.broker.isolated import backend_root, mt5_settings

        return ProcessFeed(
            module_command("app.stream.mt5_feed"),
            {
                "settings": mt5_settings(settings),
                "interval": settings.feed_interval,
                "state_interval": settings.state_interval,
            },
            cwd=backend_root(),
        )

    from app.stream.sources import AdapterSource, Mt5Source

    source = Mt5Source(adapter) if adapter.name == "mt5" else AdapterSource(adapter)  # type: ignore[arg-type]
    return ThreadFeed(source, interval=settings.feed_interval, state_interval=settings.state_interval)
