"""Background streamer bridging the pipeline to WebSocket clients.

Responsibilities:

* Subscribe to the Redis pub/sub channels (``cybershield:events``,
  ``alerts``, ``anomalies``, ``metrics``) and forward every message to
  the WebSocket manager for broadcasting.
* Fall back to the in-process pub/sub inside ``redis_service`` when
  Redis is unavailable — a reconciliation loop covers runtime
  transitions (Redis coming up or going down) so the feed never stalls.
* Bridge the alert engine's listener output (alerts are not published
  to Redis by the engine itself).
* Push periodic ``metric_update`` and ``system_health`` snapshots even
  when no events are flowing.

Runs as an asyncio background task started by the app lifespan.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Mapping

import structlog

from app.core.config import settings
from app.services.alert_engine import get_alert_engine
from app.services.event_service import get_event_service
from app.services.redis_service import get_redis_service
from app.services.simulation_service import get_simulation_service
from app.services.system_service import get_system_service
from app.websocket.manager import ConnectionManager, get_ws_manager

logger = structlog.get_logger("cybershield.backend.websocket.streamer")

#: Attack events with an anomaly score at/above this are additionally
#: broadcast on the ``anomaly`` channel.
ANOMALY_BROADCAST_THRESHOLD = 0.70

_METRICS_INTERVAL_SECONDS = 5.0
_HEALTH_EVERY_N_TICKS = 3  # full system health every ~15 seconds
_RECONCILE_INTERVAL_SECONDS = 15.0


def _iso(epoch: float | None = None) -> str:
    moment = epoch if epoch is not None else time.time()
    return datetime.fromtimestamp(moment, tz=timezone.utc).isoformat()


def _anomaly_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Lightweight derived anomaly message from an event record."""

    return {
        "id": record.get("id"),
        "timestamp": record.get("timestamp"),
        "source_host": record.get("source_host"),
        "source_ip": record.get("source_ip"),
        "destination_host": record.get("destination_host"),
        "destination_ip": record.get("destination_ip"),
        "protocol": record.get("protocol"),
        "service": record.get("service"),
        "attack_type": record.get("attack_type"),
        "attack_category": record.get("attack_category"),
        "severity": record.get("severity"),
        "anomaly_score": record.get("anomaly_score"),
        "ml_confidence": record.get("ml_confidence"),
        "risk_score": record.get("risk_score"),
        "risk_band": record.get("risk_band"),
    }


class EventStreamer:
    """Forwards pipeline output to WebSocket clients."""

    def __init__(self, manager: ConnectionManager | None = None) -> None:
        self.manager = manager or get_ws_manager()
        self._running = False
        self._redis_task: asyncio.Task[None] | None = None
        self._local_registered = False
        self._alert_listener_registered = False
        self._reconcile_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None
        self._started_at: float | None = None
        # -- counters -------------------------------------------------------
        self._forwarded_events = 0
        self._forwarded_alerts = 0
        self._forwarded_anomalies = 0
        self._forwarded_metric_updates = 0
        self._forwarded_health = 0
        self._errors = 0

    # ------------------------------------------------------------- control

    @property
    def running(self) -> bool:
        return self._running

    def channels(self) -> list[str]:
        """Configured pub/sub channels (deduplicated)."""

        seen: list[str] = []
        for channel in (
            settings.redis_event_channel,
            settings.redis_alert_channel,
            settings.redis_anomaly_channel,
            settings.redis_metrics_channel,
        ):
            if channel and channel not in seen:
                seen.append(channel)
        return seen

    def stats(self) -> dict[str, Any]:
        """Diagnostics snapshot."""

        return {
            "running": self._running,
            "mode": "redis" if get_redis_service().available else "in-process",
            "channels": self.channels(),
            "started_at": _iso(self._started_at) if self._started_at else None,
            "forwarded_events": self._forwarded_events,
            "forwarded_alerts": self._forwarded_alerts,
            "forwarded_anomalies": self._forwarded_anomalies,
            "forwarded_metric_updates": self._forwarded_metric_updates,
            "forwarded_health": self._forwarded_health,
            "errors": self._errors,
        }

    async def start(self) -> None:
        """Subscribe and launch the background loops (idempotent)."""

        if self._running:
            return
        self._running = True
        self._started_at = time.time()

        redis = get_redis_service()
        try:
            self._redis_task = await redis.subscribe(self.channels(), self._on_channel_message)
            # subscribe() registers an in-process handler & returns None when
            # Redis is unavailable at startup.
            self._local_registered = self._redis_task is None
        except Exception as exc:  # noqa: BLE001 - best effort
            self._errors += 1
            logger.warning("streamer.subscribe_failed", error=str(exc))

        if not self._alert_listener_registered:
            get_alert_engine().register_listener(self._on_alert)
            self._alert_listener_registered = True

        self._reconcile_task = asyncio.create_task(
            self._reconcile_loop(), name="cybershield-ws-reconcile"
        )
        self._metrics_task = asyncio.create_task(
            self._metrics_loop(), name="cybershield-ws-metrics"
        )
        logger.info(
            "streamer.started",
            channels=self.channels(),
            mode="redis" if redis.available else "in-process",
            local_fallback=self._local_registered,
        )

    async def stop(self) -> None:
        """Cancel the background loops."""

        if not self._running:
            return
        self._running = False
        current = asyncio.current_task()
        tasks = [task for task in (self._reconcile_task, self._metrics_task, self._redis_task) if task]
        for task in tasks:
            if task is not current:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._reconcile_task = None
        self._metrics_task = None
        self._redis_task = None
        logger.info("streamer.stopped", forwarded_events=self._forwarded_events)

    # ----------------------------------------------------------- forwarding

    async def _on_channel_message(self, channel: str, data: dict[str, Any]) -> None:
        """Handle a pub/sub message from any of the subscribed channels."""

        try:
            if channel == settings.redis_event_channel:
                await self._forward_event(data)
            elif channel == settings.redis_alert_channel:
                self._forwarded_alerts += 1
                await self.manager.broadcast("alert", data)
            elif channel == settings.redis_anomaly_channel:
                self._forwarded_anomalies += 1
                await self.manager.broadcast("anomaly", data)
            elif channel == settings.redis_metrics_channel:
                self._forwarded_metric_updates += 1
                await self.manager.broadcast("metric_update", data)
        except Exception as exc:  # noqa: BLE001 - one bad message must not kill the loop
            self._errors += 1
            logger.debug("streamer.forward_failed", channel=channel, error=str(exc))

    async def _forward_event(self, record: Any) -> None:
        """Broadcast a security event and, when applicable, an anomaly."""

        if not isinstance(record, dict):
            return
        self._forwarded_events += 1
        await self.manager.broadcast("security_event", record)
        if self._is_anomaly(record):
            self._forwarded_anomalies += 1
            await self.manager.broadcast("anomaly", _anomaly_payload(record))

    async def _on_alert(self, alert: dict[str, Any], change: str) -> None:
        """Bridge alert-engine notifications to WebSocket clients."""

        try:
            self._forwarded_alerts += 1
            payload = dict(alert)
            payload["change"] = change  # "new" | "updated"
            await self.manager.broadcast("alert", payload)
        except Exception as exc:  # noqa: BLE001
            self._errors += 1
            logger.debug("streamer.alert_forward_failed", error=str(exc))

    @staticmethod
    def _is_anomaly(record: Mapping[str, Any]) -> bool:
        """An attack event whose anomaly score crosses the threshold."""

        if not record.get("is_attack"):
            return False
        try:
            score = float(record.get("anomaly_score") or 0.0)
        except (TypeError, ValueError):
            return False
        return score >= ANOMALY_BROADCAST_THRESHOLD

    # ------------------------------------------------------------- loops

    async def _metrics_loop(self) -> None:
        """Periodic metric updates (+ system health snapshots)."""

        tick = 0
        while self._running:
            try:
                await asyncio.sleep(_METRICS_INTERVAL_SECONDS)
                if not self._running:
                    break
                tick += 1
                payload = self._metrics_payload()
                await self.manager.broadcast("metric_update", payload)
                self._forwarded_metric_updates += 1
                try:
                    await get_redis_service().set_cached_metrics(payload, ttl_seconds=120)
                except Exception:  # noqa: BLE001 - caching is best effort
                    pass
                if tick % _HEALTH_EVERY_N_TICKS == 0 and self.manager.active_count:
                    health = await self._system_health_payload()
                    await self.manager.broadcast("system_health", health)
                    self._forwarded_health += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                logger.warning("streamer.metrics_failed", error=str(exc))

    def _metrics_payload(self) -> dict[str, Any]:
        """Compact metrics message shared with the dashboards."""

        return {
            "server_time": _iso(),
            "events": get_event_service().get_metrics(),
            "active_alerts": get_alert_engine().get_active_alert_count(),
            "simulation": get_simulation_service().get_status(),
        }

    async def _system_health_payload(self) -> dict[str, Any]:
        """System health message for the ``system_health`` channel."""

        try:
            health = dict(await get_system_service().get_quick_health())
        except Exception as exc:  # noqa: BLE001
            self._errors += 1
            health = {"status": "degraded", "overall": "warning", "checks": {}, "error": str(exc)}
        health["server_time"] = _iso()
        health["websocket"] = self.manager.stats()
        return health

    async def _reconcile_loop(self) -> None:
        """Keep pub/sub registration aligned with Redis availability.

        * Redis up + no live subscription task -> (re)subscribe via Redis.
        * Redis down + no in-process handler -> register the fallback.

        This never produces duplicates: ``redis_service.publish_event``
        only dispatches locally when the Redis publish fails or is
        unavailable, so exactly one path delivers each message.
        """

        redis = get_redis_service()
        while self._running:
            try:
                await asyncio.sleep(_RECONCILE_INTERVAL_SECONDS)
                if not self._running:
                    break
                if redis.available:
                    if self._redis_task is None or self._redis_task.done():
                        self._redis_task = await redis.subscribe(
                            self.channels(), self._on_channel_message
                        )
                        logger.info("streamer.redis_subscription_restored")
                elif not self._local_registered:
                    await redis.subscribe(self.channels(), self._on_channel_message)
                    self._local_registered = True
                    logger.info("streamer.local_fallback_registered")
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                logger.debug("streamer.reconcile_failed", error=str(exc))


#: Shared streamer instance.
event_streamer = EventStreamer()


def get_event_streamer() -> EventStreamer:
    """FastAPI-friendly accessor for the shared streamer."""

    return event_streamer
