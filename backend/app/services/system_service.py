"""System Health Service.

Probes every platform dependency (Kafka, Spark, HDFS, PostgreSQL, Redis,
WebSocket) and assembles the ``/api/system/status`` + ``/api/health``
payloads.

Every probe is non-blocking and heavily time-boxed; services that are not
running produce ``warning`` status in demo mode (expected - the backend keeps
working without them) and ``offline`` in live mode.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import structlog

from app.core import database
from app.core.config import settings
from app.services.redis_service import get_redis_service

logger = structlog.get_logger("cybershield.backend.system")

_PROBE_TIMEOUT = 1.5
_STATUS_CACHE_TTL = 5.0

#: Probe return type: (status, latency_ms, message, details)
ProbeResult = tuple[str, float | None, str, dict[str, Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemService:
    """Health-check orchestrator with per-service history tracking."""

    def __init__(self) -> None:
        self._history: dict[str, deque[bool]] = {}
        self._cache: tuple[float, list[dict[str, Any]]] | None = None
        self._websocket_stats_provider: Callable[[], dict[str, Any]] | None = None
        self._simulation_provider: Callable[[], dict[str, Any]] | None = None
        self.started_at = time.time()

    # ------------------------------------------------------------ providers

    def set_websocket_stats_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        """Wire the WebSocket manager stats (set during app startup)."""

        self._websocket_stats_provider = provider

    def set_simulation_status_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        """Wire the simulation status (set during app startup)."""

        self._simulation_provider = provider

    # --------------------------------------------------------------- probes

    async def _probe_kafka(self) -> ProbeResult:
        candidates = [
            _split_host_port(settings.kafka_bootstrap_servers),
            _split_host_port(settings.kafka_external_servers),
        ]
        return await self._probe_tcp(
            candidates,
            service="kafka",
            success_message="Broker TCP endpoint reachable",
            demo_note=(
                "Kafka is not running - the built-in demo generator supplies events."
            ),
        )

    async def _probe_spark(self) -> ProbeResult:
        urls = [_spark_http_url(settings.spark_master_url)]
        candidates = [url for url in urls if url]
        return await self._probe_http(
            candidates,
            service="spark",
            success_message="Spark master UI reachable",
            demo_note="Spark is not running - risk scoring and analytics fall back to in-process logic.",
        )

    async def _probe_hdfs(self) -> ProbeResult:
        urls = [settings.hdfs_web_url]
        local = settings.hdfs_web_url.replace("namenode", "localhost")
        if local not in urls:
            urls.append(local)
        return await self._probe_http(
            urls,
            service="hdfs",
            success_message="NameNode UI reachable",
            demo_note="HDFS is not running - persistence is degraded to PostgreSQL/in-memory only.",
        )

    async def _probe_postgres(self) -> ProbeResult:
        started = time.perf_counter()
        latency = await database.ping_database()
        if latency is not None:
            return "healthy", latency, "SELECT 1 OK", dict(database.database_state())
        elapsed = round((time.perf_counter() - started) * 1000.0, 2)
        state = dict(database.database_state())
        status = "warning" if settings.demo_mode else "offline"
        message = (
            "PostgreSQL unreachable - running with in-memory state (demo mode)."
            if settings.demo_mode
            else "PostgreSQL unreachable."
        )
        return status, elapsed, message, state

    async def _probe_redis(self) -> ProbeResult:
        service = get_redis_service()
        latency = await service.ping()
        state = service.state()
        if latency is not None:
            return "healthy", latency, "PING OK", state
        status = "warning" if settings.demo_mode else "offline"
        message = (
            "Redis unreachable - using the in-process pub/sub fallback (demo mode)."
            if settings.demo_mode
            else "Redis unreachable."
        )
        return status, None, message, state

    async def _probe_websocket(self) -> ProbeResult:
        stats = self._websocket_stats_provider() if self._websocket_stats_provider else {}
        connections = int(stats.get("active_connections", 0))
        return (
            "healthy",
            0.0,
            f"{connections} active connection(s)",
            stats,
        )

    async def _probe_backend(self) -> ProbeResult:
        uptime = time.time() - self.started_at
        return (
            "healthy",
            0.0,
            "API responding",
            {"uptime_seconds": round(uptime, 1), "version": settings.app_version},
        )

    # ------------------------------------------------------------ utilities

    async def _probe_tcp(
        self,
        candidates: list[tuple[str, int]],
        *,
        service: str,
        success_message: str,
        demo_note: str,
    ) -> ProbeResult:
        for host, port in candidates:
            if not host:
                continue
            started = time.perf_counter()
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT
                )
                latency = round((time.perf_counter() - started) * 1000.0, 2)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
                del reader
                return "healthy", latency, f"{success_message} ({host}:{port})", {"endpoint": f"{host}:{port}"}
            except Exception:  # noqa: BLE001 - anything else means "not reachable"
                continue
        status = "warning" if settings.demo_mode else "offline"
        return status, None, demo_note, {"tried": [f"{h}:{p}" for h, p in candidates]}

    async def _probe_http(
        self,
        urls: list[str],
        *,
        service: str,
        success_message: str,
        demo_note: str,
    ) -> ProbeResult:
        if not urls:
            status = "warning" if settings.demo_mode else "offline"
            return status, None, demo_note, {}
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx always installed
            status = "warning" if settings.demo_mode else "offline"
            return status, None, "httpx unavailable", {}

        for url in urls:
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, verify=False) as client:
                    response = await client.get(url)
                latency = round((time.perf_counter() - started) * 1000.0, 2)
                if response.status_code < 500:
                    return "healthy", latency, f"{success_message} ({url})", {"url": url}
            except Exception:  # noqa: BLE001
                continue
        status = "warning" if settings.demo_mode else "offline"
        return status, None, demo_note, {"tried": urls}

    # -------------------------------------------------------------- status

    async def get_services(self, *, force: bool = False) -> list[dict[str, Any]]:
        """All service snapshots (cached for a few seconds)."""

        if (
            not force
            and self._cache is not None
            and (time.monotonic() - self._cache[0]) < _STATUS_CACHE_TTL
        ):
            return [dict(service) for service in self._cache[1]]

        probes: list[tuple[str, str, Callable[[], Awaitable[ProbeResult]]]] = [
            ("backend", "Backend API", self._probe_backend),
            ("postgres", "PostgreSQL", self._probe_postgres),
            ("redis", "Redis", self._probe_redis),
            ("kafka", "Apache Kafka", self._probe_kafka),
            ("spark", "Apache Spark", self._probe_spark),
            ("hdfs", "HDFS NameNode", self._probe_hdfs),
            ("websocket", "WebSocket Feed", self._probe_websocket),
        ]

        results = await asyncio.gather(
            *(probe() for _, _, probe in probes), return_exceptions=True
        )

        checked_at = _utc_now().isoformat()
        services: list[dict[str, Any]] = []
        for (key, display_name, _), outcome in zip(probes, results):
            if isinstance(outcome, BaseException):
                status, latency, message, details = (
                    "warning" if settings.demo_mode else "offline",
                    None,
                    f"probe failed: {outcome}",
                    {},
                )
            else:
                status, latency, message, details = outcome
            history = self._history.setdefault(key, deque(maxlen=60))
            history.append(status == "healthy")
            uptime = round(sum(history) / len(history) * 100.0, 2) if history else 100.0
            services.append(
                {
                    "service": key,
                    "display_name": display_name,
                    "status": status,
                    "latency_ms": latency,
                    "uptime": uptime,
                    "message": message,
                    "details": details,
                    "checked_at": checked_at,
                }
            )

        self._cache = (time.monotonic(), services)
        return [dict(service) for service in services]

    async def get_pipeline_status(
        self, services: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """End-to-end pipeline view from ingestion to dashboard."""

        from app.services.event_service import get_event_service  # local import avoids cycles

        services = services or await self.get_services()
        by_key = {service["service"]: service for service in services}
        event_service = get_event_service()
        metrics = event_service.get_metrics()

        recent, _ = event_service.get_recent_events(limit=200)
        measured_latencies = [float(r.get("latency_ms") or 0.0) for r in recent]
        avg_inference_latency = (
            round(sum(measured_latencies) / len(measured_latencies), 2)
            if measured_latencies
            else None
        )

        simulation: dict[str, Any] = {}
        if self._simulation_provider is not None:
            try:
                simulation = self._simulation_provider()
            except Exception as exc:  # noqa: BLE001
                logger.debug("system.simulation_provider_failed", error=str(exc))

        sim_state = str(simulation.get("state") or "stopped")
        ingest_status = "healthy" if sim_state == "running" else "warning"
        ingest_throughput = f"{float(simulation.get('events_per_sec') or metrics['events_per_sec']):.1f} ev/s"

        stages: list[dict[str, Any]] = [
            {
                "id": "ingest",
                "name": "Event Ingestion",
                "status": ingest_status,
                "latency_ms": None,
                "throughput": ingest_throughput,
                "processed": int(metrics.get("total_processed", 0)),
                "note": "Demo generator (Kafka unavailable)" if settings.demo_mode else "Kafka producer",
            },
            {
                "id": "kafka",
                "name": "Kafka Buffer",
                "status": by_key.get("kafka", {}).get("status", "offline"),
                "latency_ms": by_key.get("kafka", {}).get("latency_ms"),
                "throughput": ingest_throughput,
                "processed": int(metrics.get("total_processed", 0)),
                "note": "By-passed in demo mode" if settings.demo_mode else "",
            },
            {
                "id": "spark",
                "name": "Spark Streaming",
                "status": by_key.get("spark", {}).get("status", "offline"),
                "latency_ms": by_key.get("spark", {}).get("latency_ms"),
                "throughput": ingest_throughput,
                "processed": int(metrics.get("total_processed", 0)),
                "note": "In-process scoring fallback" if settings.demo_mode else "",
            },
            {
                "id": "ml",
                "name": "ML Inference",
                "status": "healthy",
                "latency_ms": avg_inference_latency,
                "throughput": f"{float(metrics.get('avg_events_per_sec', 0.0)):.1f} ev/s",
                "processed": int(metrics.get("total_processed", 0)),
                "note": "cybershield-attack-classifier",
            },
            {
                "id": "postgres",
                "name": "PostgreSQL Store",
                "status": by_key.get("postgres", {}).get("status", "offline"),
                "latency_ms": by_key.get("postgres", {}).get("latency_ms"),
                "throughput": "",
                "processed": int(metrics.get("persistence_written", 0)),
                "note": "In-memory only in demo mode" if settings.demo_mode else "",
            },
            {
                "id": "websocket",
                "name": "WebSocket Feed",
                "status": by_key.get("websocket", {}).get("status", "offline"),
                "latency_ms": by_key.get("websocket", {}).get("latency_ms"),
                "throughput": "",
                "processed": int(by_key.get("websocket", {}).get("details", {}).get("messages_broadcast", 0)),
                "note": f"{by_key.get('websocket', {}).get('details', {}).get('active_connections', 0)} client(s)",
            },
        ]

        return {
            "status": _aggregate_status([by_key.get("backend", {}), *services]),
            "mode": "demo" if settings.demo_mode else "live",
            "stages": stages,
            "events_per_sec": float(metrics.get("events_per_sec", 0.0)),
            "total_events": int(metrics.get("total_processed", 0)),
        }

    async def get_system_status(self) -> dict[str, Any]:
        """Full payload for ``GET /api/system/status``."""

        from app.services.event_service import get_event_service

        services = await self.get_services()
        pipeline = await self.get_pipeline_status(services)

        return {
            "status": pipeline["status"],
            "mode": pipeline["mode"],
            "version": settings.app_version,
            "environment": settings.environment,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "checked_at": _utc_now().isoformat(),
            "services": services,
            "pipeline": pipeline,
            "database": dict(database.database_state()),
            "redis": get_redis_service().state(),
            "websocket": (
                self._websocket_stats_provider() if self._websocket_stats_provider else {}
            ),
            "demo_mode": settings.demo_mode,
            "events": get_event_service().get_metrics(),
        }

    async def get_quick_health(self) -> dict[str, Any]:
        """Compact payload for ``GET /api/health``."""

        services = await self.get_services()
        by_key = {service["service"]: service for service in services}
        overall = _aggregate_status(list(by_key.values()))
        checks = {
            key: by_key[key]["status"]
            for key in ("backend", "postgres", "redis", "kafka", "spark", "hdfs", "websocket")
            if key in by_key
        }
        return {
            "status": "healthy" if overall == "healthy" else "degraded",
            "overall": overall,
            "checks": checks,
        }


def _aggregate_status(services: list[dict[str, Any]]) -> str:
    statuses = [str(service.get("status", "offline")) for service in services if service]
    if any(status == "offline" for status in statuses):
        return "offline"
    if any(status == "warning" for status in statuses):
        return "warning"
    return "healthy"


def _split_host_port(endpoint: str | None) -> tuple[str, int]:
    if not endpoint:
        return "", 0
    value = endpoint.strip()
    host, _, port_text = value.partition(":")
    try:
        port = int(port_text)
    except ValueError:
        port = 9092
    return host, port


def _spark_http_url(master_url: str) -> str:
    """Derive the Spark master UI URL from ``spark://host:7077``."""

    if not master_url:
        return ""
    if master_url.startswith("spark://"):
        host = master_url[len("spark://") :].split(":")[0]
        return f"http://{host}:8080"
    if master_url.startswith("http"):
        return master_url
    return ""


#: Shared service instance.
system_service = SystemService()


def get_system_service() -> SystemService:
    """FastAPI-friendly accessor for the shared service."""

    return system_service
