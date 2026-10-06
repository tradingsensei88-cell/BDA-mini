"""Simulation Service.

Controls the traffic source that feeds the platform:

* **Demo mode** (default) - wraps :class:`DemoDataGenerator`, the in-process
  NSL-KDD style event simulator. Fully standalone, no Kafka required.
* **Live mode** - an external producer (e.g. the Kafka
  ``streaming/producers/event_producer.py``) can be attached with
  :meth:`SimulationService.attach_producer`; all controls are duck-typed so the
  backend never hard-depends on the streaming package.

Exposes ``start / pause / resume / reset / set_rate / get_status`` used by the
``/api/simulation/*`` endpoints. The service is a process-wide singleton and
guards state transitions with an ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable

import structlog

from app.core.config import settings
from app.services.demo_data_generator import DemoDataGenerator, get_demo_generator

logger = structlog.get_logger("cybershield.backend.simulation")

#: Any object exposing (a subset of) start/pause/resume/reset/set_rate/get_status.
ProducerLike = Any


class SimulationService:
    """Thread-safe (asyncio) controller for the active traffic source."""

    def __init__(self, generator: DemoDataGenerator | None = None) -> None:
        self.generator = generator or get_demo_generator()
        self._producer: ProducerLike | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- producers

    def attach_producer(self, producer: ProducerLike) -> None:
        """Attach an external producer (e.g. the Kafka event producer).

        Once attached, all simulation controls are forwarded to it instead of
        the demo generator. Pass ``None`` to detach and fall back to demo mode.
        """

        self._producer = producer
        logger.info(
            "simulation.producer_attached",
            producer=type(producer).__name__ if producer is not None else None,
        )

    @property
    def active_source(self) -> str:
        """``kafka`` when an external producer is attached, else ``demo``."""

        return "kafka" if self._producer is not None else "demo"

    # ------------------------------------------------------------- lifecycle

    async def bootstrap(self, *, auto_start: bool = False) -> dict[str, Any]:
        """Backfill history + seed alerts/investigations (demo only)."""

        if self._producer is None:
            await self.generator.bootstrap()
        if auto_start:
            await self.start()
        return self.get_status()

    async def start(self) -> dict[str, Any]:
        """Start the simulation (idempotent - re-start resumes when paused)."""

        async with self._lock:
            await self._invoke("start")
            status = self.get_status()
            logger.info("simulation.started", source=status.get("source"), rate=status.get("rate"))
            return status

    async def pause(self) -> dict[str, Any]:
        """Pause emission while keeping the task alive."""

        async with self._lock:
            await self._invoke("pause")
            status = self.get_status()
            logger.info("simulation.paused", source=status.get("source"))
            return status

    async def resume(self) -> dict[str, Any]:
        """Resume after :meth:`pause` (starts the simulation when stopped)."""

        async with self._lock:
            if self._producer is None and not self.generator.running:
                await self._invoke("start")
            else:
                await self._invoke("resume")
            status = self.get_status()
            logger.info("simulation.resumed", source=status.get("source"))
            return status

    async def reset(self) -> dict[str, Any]:
        """Stop the simulation and zero its statistics.

        Platform state (event buffer, alerts, investigations) is intentionally
        left untouched - reset only affects the simulation counters/state.
        """

        async with self._lock:
            await self._invoke("reset", stop_first=True)
            status = self.get_status()
            logger.info("simulation.reset", source=status.get("source"))
            return status

    async def set_rate(self, rate: int) -> dict[str, Any]:
        """Change the emission rate (events/second)."""

        if rate < 1 or rate > 10_000:
            raise ValueError("rate must be between 1 and 10000")
        async with self._lock:
            await self._invoke("set_rate", rate)
            status = self.get_status()
            logger.info("simulation.rate_set", rate=rate, source=status.get("source"))
            return status

    # ---------------------------------------------------------------- status

    def get_status(self) -> dict[str, Any]:
        """Current status payload (``schemas.simulation.SimulationStatus`` shape)."""

        if self._producer is not None:
            status = self._producer_status()
            if status is not None:
                return status
        status = self.generator.get_status()
        status["source"] = "demo"
        status["demo_mode"] = settings.demo_mode
        return status

    def snapshot(self) -> dict[str, Any]:
        """Alias used by :class:`SystemService` providers (sync-safe)."""

        return self.get_status()

    # --------------------------------------------------------------- helpers

    async def _invoke(self, method: str, *args: Any, stop_first: bool = False) -> Any:
        """Call ``method`` on the active source, await-ing it when needed."""

        target = self._producer if self._producer is not None else self.generator
        if target is None:  # pragma: no cover - defensive
            raise RuntimeError("no simulation source attached")

        if method == "reset" and stop_first and hasattr(target, "stop"):
            outcome = getattr(target, "stop")()
            if inspect.isawaitable(outcome):
                await outcome

        handler: Callable[..., Any] | None = getattr(target, method, None)
        if handler is None:
            if self._producer is not None:
                # External producers may not implement every control; treat
                # missing handlers as a graceful no-op so the API stays usable.
                logger.debug("simulation.control_unsupported", method=method)
                return None
            raise RuntimeError(f"simulation source does not support {method!r}")

        try:
            outcome = handler(*args)
        except TypeError:
            # e.g. producer.set_rate accepts keyword arguments only.
            outcome = handler(rate=args[0]) if args else handler()
        if inspect.isawaitable(outcome):
            outcome = await outcome
        return outcome

    def _producer_status(self) -> dict[str, Any] | None:
        """Normalize an external producer status into the API shape."""

        assert self._producer is not None
        getter = getattr(self._producer, "get_status", None)
        if getter is None:
            return None
        try:
            raw = getter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("simulation.producer_status_failed", error=str(exc))
            return None

        # A demo-style status dict is already the right shape.
        if isinstance(raw, dict) and {"state", "rate", "total_events"} & set(raw):
            status = dict(raw)
            status.setdefault("source", "kafka")
            status.setdefault("demo_mode", settings.demo_mode)
            return status

        # Generic producer object (attributes or small dicts) -> best effort.
        state = str(getattr(raw, "state", raw.get("state", "running") if isinstance(raw, dict) else "running"))
        return {
            "state": state,
            "running": state == "running",
            "paused": state == "paused",
            "rate": int(getattr(raw, "rate", 0) or (raw.get("rate", 0) if isinstance(raw, dict) else 0)),
            "events_per_sec": float(
                getattr(raw, "events_per_sec", 0.0)
                or (raw.get("events_per_sec", 0.0) if isinstance(raw, dict) else 0.0)
            ),
            "avg_events_per_sec": 0.0,
            "total_events": int(
                getattr(raw, "total_events", 0) or (raw.get("total_events", 0) if isinstance(raw, dict) else 0)
            ),
            "alerts_generated": 0,
            "anomalies_detected": 0,
            "category_breakdown": {},
            "source": "kafka",
            "demo_mode": settings.demo_mode,
            "started_at": None,
            "uptime_seconds": 0.0,
            "last_event_at": None,
            "message": f"Kafka producer state: {state}.",
        }


#: Shared controller singleton.
simulation_service = SimulationService()


def get_simulation_service() -> SimulationService:
    """FastAPI-friendly accessor for the shared controller."""

    return simulation_service
