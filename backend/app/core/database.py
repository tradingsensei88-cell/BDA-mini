"""CyberShield AI - asynchronous database layer (SQLAlchemy 2.x + asyncpg).

The backend runs happily **without** PostgreSQL (demo / dev mode): every
service keeps working against in-memory state while this module reports the
database as unavailable. When PostgreSQL *is* reachable the engine is used for
write-through persistence and health checks.

Usage::

    from app.core.database import init_database, close_database, get_db, session_scope

    # lifespan startup / shutdown
    await init_database()
    ...
    await close_database()

    # FastAPI dependency (raises 503 when the database is unavailable)
    async def endpoint(db: AsyncSession = Depends(get_db)): ...
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = structlog.get_logger("cybershield.backend.database")


class DatabaseUnavailableError(RuntimeError):
    """Raised when a database operation is attempted while Postgres is down."""


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


# ---------------------------------------------------------------------------
# Module state (single engine per process)
# ---------------------------------------------------------------------------

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_available: bool = False
_last_error: Optional[str] = None
_connected_at: Optional[float] = None
_connected_url: Optional[str] = None
_lock = asyncio.Lock()


def _candidate_urls() -> list[str]:
    """Configured DSN first, then a localhost variant for local development."""

    primary = settings.sqlalchemy_database_url
    local = primary.replace("@postgres:", "@localhost:").replace("@db:", "@localhost:")
    urls: list[str] = []
    for url in (primary, local):
        if url not in urls:
            urls.append(url)
    return urls


def get_engine() -> Optional[AsyncEngine]:
    """Return the engine, or ``None`` when the database layer was never initialised."""

    return _engine


def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    """Return the session factory, or ``None`` before :func:`init_database`."""

    return _session_factory


def is_database_available() -> bool:
    """``True`` when the last connection attempt succeeded."""

    return _available


def database_state() -> dict[str, object]:
    """Small diagnostics snapshot for the health endpoints."""

    return {
        "available": _available,
        "connected_at": _connected_at,
        "url": _connected_url,
        "last_error": _last_error,
        "pool": (
            {
                "size": _engine.pool.size(),
                "checked_out": _engine.pool.checkedout(),
            }
            if _engine is not None
            else None
        ),
    }


def _build_engine(url: str) -> AsyncEngine:
    """Create the async engine for ``url`` with the configured pool settings."""

    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=max(1, settings.db_pool_size),
        max_overflow=max(0, settings.db_max_overflow),
        pool_recycle=1800,
        pool_timeout=10,
        connect_args={
            "timeout": max(1.0, settings.db_connect_timeout),
            "command_timeout": 10.0,
            # Fail fast instead of retrying DNS lookups for minutes.
            "server_settings": {"application_name": "cybershield-backend"},
        },
    )


async def init_database() -> bool:
    """Try to connect to PostgreSQL; degrade gracefully on failure.

    Returns ``True`` when the database is reachable. Never raises.
    """

    global _engine, _session_factory, _available, _last_error, _connected_at, _connected_url

    async with _lock:
        attempts = max(1, settings.db_connect_retries)
        for url in _candidate_urls():
            for attempt in range(1, attempts + 1):
                engine = _build_engine(url)
                try:
                    started = time.perf_counter()
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    _engine = engine
                    _session_factory = async_sessionmaker(
                        engine, expire_on_commit=False, class_=AsyncSession
                    )
                    _available = True
                    _last_error = None
                    _connected_at = time.time()
                    _connected_url = _disarm(url)
                    logger.info(
                        "database.connected",
                        url=_disarm(url),
                        latency_ms=round(latency_ms, 1),
                    )
                    return True
                except Exception as exc:  # noqa: BLE001 - any driver error means "not available"
                    _last_error = f"{type(exc).__name__}: {exc}"
                    await engine.dispose()
                    logger.warning(
                        "database.connect_failed",
                        url=_disarm(url),
                        attempt=attempt,
                        error=_last_error,
                    )
                    if attempt < attempts:
                        await asyncio.sleep(0.75)

        _engine = None
        _session_factory = None
        _available = False
        logger.warning(
            "database.unavailable_demo_mode",
            note=(
                "PostgreSQL is not reachable - continuing in demo mode with "
                "in-memory state. Set DATABASE_URL to enable persistence."
            ),
            last_error=_last_error,
        )
        return False


async def close_database() -> None:
    """Dispose the engine and reset module state."""

    global _engine, _session_factory, _available, _connected_at, _connected_url

    async with _lock:
        if _engine is not None:
            try:
                await _engine.dispose()
                logger.info("database.disposed")
            except Exception as exc:  # noqa: BLE001 - shutdown must never raise
                logger.warning("database.dispose_failed", error=str(exc))
        _engine = None
        _session_factory = None
        _available = False
        _connected_at = None
        _connected_url = None


async def ping_database() -> Optional[float]:
    """Round-trip ``SELECT 1`` latency in milliseconds, or ``None`` if down."""

    if _engine is None:
        return None
    try:
        started = time.perf_counter()
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return round((time.perf_counter() - started) * 1000.0, 2)
    except Exception as exc:  # noqa: BLE001
        global _available, _last_error
        _available = False
        _last_error = f"{type(exc).__name__}: {exc}"
        return None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a transactional session.

    Raises :class:`DatabaseUnavailableError` when Postgres is not available so
    callers can decide whether to degrade or fail.
    """

    factory = _session_factory
    if factory is None or not _available:
        raise DatabaseUnavailableError(_last_error or "database is not initialised")

    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session or raises HTTP 503."""

    factory = _session_factory
    if factory is None or not _available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Database is unavailable (running in demo mode).",
                "reason": _last_error,
            },
        )
    async with session_scope() as session:  # pragma: no cover - exercised via API
        yield session


def _disarm(url: str) -> str:
    """Hide credentials from a DSN before logging."""

    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"
