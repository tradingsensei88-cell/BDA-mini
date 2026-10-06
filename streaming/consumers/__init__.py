"""Kafka consumers that persist, enrich, and route streaming events.

Exports are resolved lazily (PEP 562) so importing the package does not pull
in the Kafka client / psycopg2 until :class:`EventConsumer` is actually used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from streaming.consumers.event_consumer import (
        ConsumerError,
        ConsumerStartupError,
        ConsumerStats,
        EventConsumer,
        PostgresEventWriter,
        event_to_db_row,
    )

__all__ = [
    "EventConsumer",
    "ConsumerStats",
    "PostgresEventWriter",
    "ConsumerStartupError",
    "ConsumerError",
    "event_to_db_row",
]

_LAZY_IMPORTS: dict[str, str] = {
    "EventConsumer": "streaming.consumers.event_consumer",
    "ConsumerStats": "streaming.consumers.event_consumer",
    "PostgresEventWriter": "streaming.consumers.event_consumer",
    "ConsumerStartupError": "streaming.consumers.event_consumer",
    "ConsumerError": "streaming.consumers.event_consumer",
    "event_to_db_row": "streaming.consumers.event_consumer",
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _LAZY_IMPORTS[name]
    except KeyError as exc:  # pragma: no cover - standard module behaviour
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:  # pragma: no cover - introspection helper
    return sorted(__all__)
