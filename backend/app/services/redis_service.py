"""Redis Service.

Provides pub/sub for real-time event distribution plus a lightweight cache
for metrics/alerts/counters.

Everything degrades gracefully: when Redis is unreachable the service keeps
an in-process cache and dispatches ``publish_event`` calls to *local*
subscribers instead, so the WebSocket pipeline works identically in demo
mode.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Iterable

import structlog

from app.core.config import settings

logger = structlog.get_logger("cybershield.backend.redis")

MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]

_METRICS_KEY = "cybershield:metrics:latest"
_ALERTS_KEY = "cybershield:alerts:recent"
_COUNTER_PREFIX = "cybershield:counter:"


class RedisService:
    """Async Redis wrapper with an in-memory fallback."""

    def __init__(self) -> None:
        self._client: Any = None
        self._available = False
        self._last_error: str | None = None
        self._connected_at: float | None = None
        self._connected_url: str | None = None
        self._connect_lock = asyncio.Lock()

        # -- in-memory fallback -------------------------------------------
        self._memory: dict[str, Any] = {}
        self._counters: dict[str, int] = defaultdict(int)
        self._recent_alerts: deque[dict[str, Any]] = deque(maxlen=200)
        self._local_subscribers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._redis_tasks: list[asyncio.Task[None]] = []
        self._closing = False

    # ------------------------------------------------------------- status

    @property
    def available(self) -> bool:
        """Whether a live Redis connection is established."""

        return self._available

    def state(self) -> dict[str, Any]:
        """Diagnostics snapshot for the health endpoints."""

        return {
            "available": self._available,
            "mode": "redis" if self._available else "in-memory",
            "url": self._connected_url,
            "connected_at": self._connected_at,
            "last_error": self._last_error,
            "local_subscribers": {channel: len(handlers) for channel, handlers in self._local_subscribers.items()},
            "websocket_tasks": len(self._redis_tasks),
        }

    # ------------------------------------------------------------ connect

    async def connect(self) -> bool:
        """Attempt to connect (configured URL, then its localhost variant)."""

        async with self._connect_lock:
            if self._available and self._client is not None:
                return True

            try:
                import redis.asyncio as aioredis  # imported lazily so demo mode has no hard dep
            except ImportError as exc:  # pragma: no cover - dependency missing
                self._last_error = f"redis package unavailable: {exc}"
                logger.warning("redis.import_failed", error=self._last_error)
                return False

            urls: list[str] = []
            for url in (settings.redis_url, settings.local_redis_url):
                if url not in urls:
                    urls.append(url)

            for url in urls:
                client = None
                try:
                    client = aioredis.from_url(
                        url,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_connect_timeout=max(0.5, settings.redis_connect_timeout),
                        socket_timeout=max(1.0, settings.redis_connect_timeout * 2),
                    )
                    started = time.perf_counter()
                    await client.ping()
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    self._client = client
                    self._available = True
                    self._last_error = None
                    self._connected_at = time.time()
                    self._connected_url = url
                    logger.info("redis.connected", url=url, latency_ms=round(latency_ms, 1))
                    return True
                except Exception as exc:  # noqa: BLE001 - any error means "unavailable"
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    if client is not None:
                        await _close_quietly(client)
                    logger.warning("redis.connect_failed", url=url, error=self._last_error)

            self._available = False
            logger.warning(
                "redis.unavailable_memory_mode",
                note="Redis is not reachable - using the in-process pub/sub fallback.",
                last_error=self._last_error,
            )
            return False

    async def close(self) -> None:
        """Stop subscription tasks and close the connection."""

        self._closing = True
        for task in list(self._redis_tasks):
            task.cancel()
        for task in list(self._redis_tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._redis_tasks.clear()

        if self._client is not None:
            await _close_quietly(self._client)
            self._client = None
            logger.info("redis.closed")
        self._available = False
        self._closing = False

    async def ping(self) -> float | None:
        """Round-trip latency in milliseconds, or ``None`` when unavailable."""

        if self._client is None:
            return None
        try:
            started = time.perf_counter()
            await self._client.ping()
            return round((time.perf_counter() - started) * 1000.0, 2)
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None

    # -------------------------------------------------------- pub / sub

    async def publish_event(self, channel: str, data: dict[str, Any]) -> None:
        """Publish ``data`` on ``channel`` (Redis pub/sub or local dispatch)."""

        payload = dict(data)
        if self._available and self._client is not None:
            try:
                await self._client.publish(channel, json.dumps(payload, default=str))
                return
            except Exception as exc:  # noqa: BLE001 - fall back to local dispatch
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("redis.publish_failed", channel=channel, error=self._last_error)
                self._available = False

        await self._dispatch_local(channel, payload)

    async def subscribe(self, channels: Iterable[str], handler: MessageHandler) -> asyncio.Task[None] | None:
        """Subscribe ``handler(channel, data)`` to ``channels``.

        With Redis: returns the background task running the pub/sub loop.
        Without Redis: registers a local subscriber and returns ``None``.
        """

        channel_list = [channel for channel in channels if channel]
        if self._available and self._client is not None:
            task = asyncio.create_task(
                self._redis_subscription_loop(channel_list, handler),
                name="cybershield-redis-subscription",
            )
            self._redis_tasks.append(task)
            return task

        for channel in channel_list:
            self._local_subscribers[channel].append(handler)
        logger.info("redis.subscribed_local", channels=channel_list)
        return None

    async def _redis_subscription_loop(self, channels: list[str], handler: MessageHandler) -> None:
        """Long-running pub/sub loop with reconnect/backoff."""

        backoff = 1.0
        while not self._closing:
            pubsub = None
            try:
                pubsub = self._client.pubsub()
                await pubsub.subscribe(*channels)
                logger.info("redis.subscription_started", channels=channels)
                backoff = 1.0
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        data = json.loads(message.get("data") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        data = {"raw": message.get("data")}
                    await handler(message.get("channel", ""), data)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                logger.warning("redis.subscription_error", error=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
            finally:
                if pubsub is not None:
                    await _close_quietly(pubsub)

    async def _dispatch_local(self, channel: str, data: dict[str, Any]) -> None:
        """Deliver a message to in-process subscribers."""

        handlers = list(self._local_subscribers.get(channel, []))
        for subscriber in handlers:
            try:
                await subscriber(channel, data)
            except Exception as exc:  # noqa: BLE001 - one bad subscriber must not break others
                logger.warning("redis.local_subscriber_failed", channel=channel, error=str(exc))

    # ------------------------------------------------------------- cache

    async def set_cached_metrics(self, data: dict[str, Any], ttl_seconds: int = 120) -> None:
        """Cache the latest metrics snapshot."""

        payload = dict(data)
        self._memory[_METRICS_KEY] = {"value": payload, "expires_at": time.time() + ttl_seconds}
        if self._available and self._client is not None:
            try:
                await self._client.set(_METRICS_KEY, json.dumps(payload, default=str), ex=ttl_seconds)
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.cache_write_failed", key=_METRICS_KEY, error=str(exc))

    async def get_cached_metrics(self) -> dict[str, Any] | None:
        """Return the cached metrics snapshot (or ``None``)."""

        if self._available and self._client is not None:
            try:
                raw = await self._client.get(_METRICS_KEY)
                if raw is not None:
                    return json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.cache_read_failed", key=_METRICS_KEY, error=str(exc))

        entry = self._memory.get(_METRICS_KEY)
        if entry is None:
            return None
        if entry["expires_at"] is not None and entry["expires_at"] < time.time():
            self._memory.pop(_METRICS_KEY, None)
            return None
        return entry["value"]

    async def cache_alert(self, alert: dict[str, Any]) -> None:
        """Remember the most recent alerts (newest first, max 200)."""

        if self._available and self._client is not None:
            try:
                await self._client.lpush(_ALERTS_KEY, json.dumps(dict(alert), default=str))
                await self._client.ltrim(_ALERTS_KEY, 0, 199)
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.alert_cache_failed", error=str(exc))
        self._recent_alerts.appendleft(dict(alert))

    async def get_cached_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent cached alerts."""

        if self._available and self._client is not None:
            try:
                raw_items = await self._client.lrange(_ALERTS_KEY, 0, max(0, limit - 1))
                return [json.loads(item) for item in raw_items]
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.alert_cache_read_failed", error=str(exc))
        return [dict(alert) for alert in list(self._recent_alerts)[:limit]]

    # ---------------------------------------------------------- counters

    async def increment_counter(self, name: str, amount: int = 1) -> int:
        """Atomically increment a named counter (Redis or local)."""

        key = f"{_COUNTER_PREFIX}{name}"
        if self._available and self._client is not None:
            try:
                return int(await self._client.incrby(key, amount))
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.counter_failed", counter=name, error=str(exc))
        self._counters[name] += amount
        return self._counters[name]

    async def get_counter(self, name: str) -> int:
        """Read a named counter."""

        if self._available and self._client is not None:
            try:
                raw = await self._client.get(f"{_COUNTER_PREFIX}{name}")
                return int(raw) if raw is not None else 0
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis.counter_read_failed", counter=name, error=str(exc))
        return self._counters.get(name, 0)


async def _close_quietly(resource: Any) -> None:
    """Close a redis client/pubsub object ignoring API differences + errors."""

    for method_name in ("aclose", "close"):
        method = getattr(resource, method_name, None)
        if method is None:
            continue
        try:
            result = method()
            if asyncio.iscoroutine(result):
                await result
            return
        except Exception:  # noqa: BLE001 - closing must never raise
            continue


#: Shared service instance.
redis_service = RedisService()


def get_redis_service() -> RedisService:
    """FastAPI-friendly accessor for the shared service."""

    return redis_service
