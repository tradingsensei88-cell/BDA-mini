"""Kafka producers that generate and publish network/security telemetry.

Exports are resolved lazily (PEP 562) so that importing e.g. the dataset
adapter never pulls in the Kafka client, and vice versa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from streaming.producers.dataset_adapter import NSLKDDAdapter
    from streaming.producers.event_producer import EventProducer, ProducerStats

__all__ = ["NSLKDDAdapter", "EventProducer", "ProducerStats", "ProducerConnectionError"]

_LAZY_IMPORTS: dict[str, str] = {
    "NSLKDDAdapter": "streaming.producers.dataset_adapter",
    "EventProducer": "streaming.producers.event_producer",
    "ProducerStats": "streaming.producers.event_producer",
    "ProducerConnectionError": "streaming.producers.event_producer",
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
