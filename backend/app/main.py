"""CyberShield AI - FastAPI application entrypoint.

Wires together every layer built for the platform:

* REST routers mounted under ``/api`` (events, threats, alerts, analytics,
  ML metadata, simulation control, investigations) plus the compact
  ``/health`` liveness probe used by Docker Compose;
* the WebSocket feed at ``/ws/security-events`` (connection manager +
  background streamer bridging Redis pub/sub, or the in-process
  fallback, to connected dashboards);
* application lifespan: PostgreSQL + Redis clients, the event
  persistence worker, demo-mode simulation bootstrap and the streamer;
* middleware: CORS, request ids, structured request logging and simple
  in-memory rate limiting;
* custom exception handlers emitting the shared ``ErrorResponse``
  envelope (with the request id for log correlation).

The API stays fully functional even when Kafka/Spark/HDFS - or even
PostgreSQL/Redis - are not running: every dependency degrades gracefully
and demo mode keeps a realistic event stream flowing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.core import database
from app.core.config import settings
from app.core.exceptions import APIError
from app.services.event_service import get_event_service
from app.services.redis_service import get_redis_service
from app.services.simulation_service import get_simulation_service
from app.services.system_service import get_system_service
from app.websocket import get_event_streamer, get_ws_manager
from app.websocket import router as websocket_router

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.DEBUG if settings.debug else logging.INFO
    ),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("cybershield.backend")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _json_safe(value: Any) -> Any:
    """Round-trip a value through JSON so responses always serialise."""

    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(value)


def _error_response(
    status_code: int,
    message: str,
    *,
    request_id: str | None = None,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Shared ``ErrorResponse`` envelope: ``{"error": {...}, "request_id"}``."""

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": status_code, "message": message, "detail": detail},
            "request_id": request_id,
        },
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Rate limiting (simple in-memory sliding window)
# ---------------------------------------------------------------------------
class InMemoryRateLimiter:
    """Per-client sliding-window limiter backed by a plain dict."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_sweep = time.monotonic()

    async def hit(self, key: str) -> tuple[bool, int, float]:
        """Record a request; returns ``(allowed, remaining, retry_after)``."""

        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(0.0, self.window_seconds - (now - hits[0]))
                return False, 0, retry_after
            hits.append(now)
            if now - self._last_sweep >= self.window_seconds * 5:
                self._sweep(cutoff)
            return True, self.limit - len(hits), 0.0

    def _sweep(self, cutoff: float) -> None:
        self._hits = {
            key: hits for key, hits in self._hits.items() if hits and hits[-1] >= cutoff
        }
        self._last_sweep = time.monotonic()


rate_limiter = InMemoryRateLimiter(settings.rate_limit_per_minute)

#: Paths that must never be throttled (probes, docs, browser favicon).
_RATE_LIMIT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)


def _is_rate_limit_exempt(path: str) -> bool:
    if path in ("", "/"):
        return True
    return any(path.startswith(prefix) for prefix in _RATE_LIMIT_EXEMPT_PREFIXES)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks for every dependency (all graceful)."""

    startup_started = time.perf_counter()
    logger.info(
        "backend.startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
    )

    # -- PostgreSQL (degrades to in-memory state) ---------------------------
    database_ready = await database.init_database()

    # -- Redis (degrades to in-process pub/sub) -----------------------------
    redis = get_redis_service()
    redis_ready = await redis.connect()

    # -- Event service persistence worker -----------------------------------
    events = get_event_service()
    await events.start()

    # -- Wire dynamic providers into the health service ----------------------
    system = get_system_service()
    system.set_websocket_stats_provider(get_ws_manager().stats)
    system.set_simulation_status_provider(get_simulation_service().get_status)

    # -- WebSocket streamer (pub/sub -> clients) -----------------------------
    streamer = get_event_streamer()
    await streamer.start()

    # -- Demo mode: backfill history + start the simulator --------------------
    simulation = get_simulation_service()
    if settings.demo_mode:
        await simulation.bootstrap(auto_start=True)
        logger.info("backend.demo_mode_active", source=simulation.active_source)

    app.state.started_at = time.time()
    logger.info(
        "backend.ready",
        postgres="available" if database_ready else "in-memory",
        redis="available" if redis_ready else "in-process",
        startup_ms=round((time.perf_counter() - startup_started) * 1000.0, 1),
        docs="/docs",
        websocket=settings.ws_channel,
    )

    try:
        yield
    finally:
        logger.info("backend.shutdown")
        if settings.demo_mode:
            try:
                await simulation.generator.stop()
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                logger.debug("backend.simulation_stop_failed", error=str(exc))
        await streamer.stop()
        await events.stop()
        await redis.close()
        await database.close_database()
        uptime = time.time() - getattr(app.state, "started_at", time.time())
        logger.info("backend.stopped", uptime_seconds=round(uptime, 1))


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "system", "description": "Service banner, liveness probe and detailed system status."},
    {"name": "events", "description": "Network/security event telemetry with pagination and filters."},
    {"name": "threats", "description": "Detected attacks enriched with alert and investigation context."},
    {"name": "alerts", "description": "Alert lifecycle: listing, detail, status updates and statistics."},
    {"name": "analytics", "description": "Aggregated chart data: distributions, timelines, top sources, heatmaps."},
    {"name": "ml", "description": "Model metadata, metrics, feature importance, confusion matrix, predictions."},
    {"name": "simulation", "description": "Control the event simulator (start / pause / resume / reset / rate)."},
    {"name": "investigations", "description": "Incident investigations created from alerts."},
    {"name": "websocket", "description": "Real-time feed at `/ws/security-events` with subscribe support."},
]

app = FastAPI(
    title="CyberShield AI API",
    version=settings.app_version,
    description=(
        "Big Data Cyber Attack Detection Platform - REST and WebSocket API for "
        "network telemetry, ML predictions, alerts, analytics, simulation control "
        "and incident investigations.\n\n"
        "**Real-time feed:** connect to `WS /ws/security-events` to receive "
        "`security_event`, `alert`, `anomaly`, `metric_update` and `system_health` "
        "messages. Send `{\"type\": \"subscribe\", \"topics\": [...]}` to narrow the feed.\n\n"
        "**Demo mode:** when enabled the backend generates realistic NSL-KDD style "
        "traffic in-process, so every endpoint works without Kafka/Spark/HDFS."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
#
# Registration order (first registered = innermost): rate limit -> request id
# -> CORS. CORS is added last so it wraps error responses (a browser can then
# read 4xx/5xx bodies); the request id is attached to every response,
# including 429s produced by the limiter.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next: Any) -> JSONResponse:
    """Throttle requests per client host (in-memory, fixed window)."""

    path = request.url.path
    if request.method == "OPTIONS" or _is_rate_limit_exempt(path):
        return await call_next(request)

    client = request.client.host if request.client else "unknown"
    allowed, remaining, retry_after = await rate_limiter.hit(client)
    if not allowed:
        logger.warning("rate_limit.exceeded", client=client, path=path)
        return _error_response(
            429,
            "Too many requests - slow down.",
            request_id=getattr(request.state, "request_id", None),
            detail={
                "limit_per_minute": rate_limiter.limit,
                "retry_after_seconds": round(retry_after, 1),
            },
            headers={"Retry-After": str(int(max(1.0, retry_after)))},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rate_limiter.limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Any) -> JSONResponse:
    """Assign/propagate the request id and log every completed request."""

    request_id = request.headers.get(settings.request_id_header) or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id, method=request.method, path=request.url.path
    )

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - log with context, let handlers respond
        logger.exception(
            "request.failed", duration_ms=round((time.perf_counter() - started) * 1000.0, 2)
        )
        raise

    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    response.headers[settings.request_id_header] = request_id
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        logger.info(
            "request.completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[settings.request_id_header, "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Application errors raised by routes (404/400/409/503/429)."""

    payload = exc.to_payload()
    payload["request_id"] = getattr(request.state, "request_id", None)
    log = logger.warning if exc.status_code < 500 else logger.error
    log("api.error", status_code=exc.status_code, message=exc.message, path=request.url.path)
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Framework-raised HTTP exceptions (unknown routes, auth, ...)."""

    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    if exc.status_code == 404 and message == "Not Found":
        message = f"Route not found: {request.url.path}"
    return _error_response(
        exc.status_code,
        message,
        request_id=getattr(request.state, "request_id", None),
        detail=None if isinstance(exc.detail, str) else _json_safe(exc.detail),
        headers=dict(exc.headers) if exc.headers else None,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic request validation failures (422) in the shared envelope."""

    return _error_response(
        422,
        "Request validation failed.",
        request_id=getattr(request.state, "request_id", None),
        detail=_json_safe(exc.errors()),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: never leak internals, always log with full context."""

    logger.exception("api.unhandled_error", path=request.url.path, error=str(exc))
    return _error_response(
        500,
        "Internal server error.",
        request_id=getattr(request.state, "request_id", None),
    )


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------
@app.get("/", tags=["system"], summary="Service banner")
async def root() -> dict[str, Any]:
    """Basic service identification and discovery links."""

    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
        "docs": "/docs",
        "api": settings.api_prefix,
        "health": "/health",
        "websocket": settings.ws_channel,
    }


@app.get("/health", tags=["system"], summary="Liveness / readiness probe")
async def health(request: Request) -> JSONResponse:
    """Fast liveness probe consumed by Docker Compose and load balancers."""

    started_at = getattr(request.app.state, "started_at", None)
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "cybershield-backend",
            "version": settings.app_version,
            "environment": settings.environment,
            "demo_mode": settings.demo_mode,
            "websocket_connections": get_ws_manager().active_count,
            "uptime_seconds": round(time.time() - started_at, 1) if started_at else 0.0,
        },
    )


# ---------------------------------------------------------------------------
# Routers: REST (``/api``) + WebSocket feed
# ---------------------------------------------------------------------------
app.include_router(api_router)
app.include_router(websocket_router)


if __name__ == "__main__":  # pragma: no cover - dev convenience
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
        log_level="info",
    )
