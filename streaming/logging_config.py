"""CyberShield AI - structured logging bootstrap based on ``structlog``.

Every Python component of the platform (Kafka producers/consumers, Spark jobs,
ML scripts) imports :func:`get_logger` from this module so that log records
share a single, consistent structure:

* **development** (default when stdout is a TTY): human-readable console
  output with colours and aligned key/value pairs.
* **production / piped output**: newline-delimited JSON, ready for shipping to
  Loki/ELK/Kafka log collectors.

Configuration is controlled exclusively through environment variables:

* ``LOG_LEVEL``  - ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR`` (default ``INFO``).
* ``LOG_FORMAT`` - ``json`` or ``console``. When unset the renderer is chosen
  automatically (console for TTYs, JSON otherwise).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_configured = False


def _parse_level(level: str | None) -> int:
    """Translate a level name (``"info"``, ``"DEBUG"``, ...) into a logging int."""

    if not level:
        return logging.INFO
    resolved = logging.getLevelName(str(level).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(
    level: str | None = None,
    json_logs: bool | None = None,
    **initial_values: Any,
) -> None:
    """Configure ``structlog`` (and stdlib ``logging``) exactly once.

    Args:
        level: Level name overriding ``LOG_LEVEL``.
        json_logs: Force JSON output (``True``) or console output (``False``).
            When ``None`` the renderer is derived from ``LOG_FORMAT`` or from
            whether stdout is an interactive terminal.
        **initial_values: Extra key/value pairs bound to every log record
            (e.g. ``service="producer"``).
    """

    global _configured
    if _configured:
        return

    level_name = level or os.getenv("LOG_LEVEL", "INFO")
    level_int = _parse_level(level_name)

    if json_logs is None:
        fmt = os.getenv("LOG_FORMAT", "").strip().lower()
        if fmt == "json":
            json_logs = True
        elif fmt == "console":
            json_logs = False
        else:
            json_logs = not sys.stdout.isatty()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_logs:
        renderer: Any = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Keep third-party library logs (kafka, urllib3, ...) on the same stream.
    logging.basicConfig(
        stream=sys.stdout,
        level=level_int,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    logging.getLogger("kafka").setLevel(max(level_int, logging.WARNING))

    _configured = True

    if initial_values:
        structlog.contextvars.bind_contextvars(**initial_values)


def get_logger(name: str | None = None, **initial_values: Any) -> Any:
    """Return a configured ``structlog`` bound logger.

    Ensures :func:`configure_logging` has run, so callers can simply do::

        from streaming.logging_config import get_logger

        logger = get_logger(__name__)
        logger.info("consumer_started", topic="network-events")
    """

    configure_logging()
    if initial_values:
        return structlog.get_logger(name).bind(**initial_values)
    return structlog.get_logger(name)
