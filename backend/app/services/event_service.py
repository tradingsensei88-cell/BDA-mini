"""Event Processing Service.

Owns the real-time lifecycle of every incoming event:

1. **Normalize** the payload into the canonical record shape shared by the
   REST API, WebSocket feed and UI.
2. **Score** the event with the :mod:`~app.services.risk_scoring` engine when
   no score is attached.
3. **Buffer** it in a bounded in-memory ring (real-time display + analytics).
4. **Publish** it on Redis for WebSocket fan-out (best-effort).
5. **Persist** it to PostgreSQL through a bounded background queue
   (best-effort - silently skipped when the database is down).
6. **Track** metrics: events/sec, totals, category/severity counts.

The service is the single source of truth for recent events - PostgreSQL is a
write-through cache, never a hard dependency.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

import structlog

from app.core import database
from app.core.config import settings
from app.services.risk_scoring import RiskResult, get_risk_engine
from app.services.redis_service import get_redis_service

logger = structlog.get_logger("cybershield.backend.events")

EventListener = Callable[[dict[str, Any]], Awaitable[None]]

#: Rolling window (seconds) used to compute events/sec.
_EPS_WINDOW_SECONDS = 10.0

#: Default "top contributing features" per category when the producer does
#: not provide them (keeps the UI informative in demo mode).
_DEFAULT_TOP_FEATURES: dict[str, list[str]] = {
    "Normal": ["duration", "src_bytes", "dst_bytes"],
    "DoS": ["count", "serror_rate", "src_bytes"],
    "Probe": ["dst_host_count", "rerror_rate", "diff_srv_rate"],
    "R2L": ["num_failed_logins", "logged_in", "hot"],
    "U2R": ["root_shell", "num_root", "num_compromised"],
    "Unknown": ["count", "serror_rate", "dst_host_count"],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: Any) -> datetime | None:
    """Parse datetimes/ISO strings into aware UTC datetimes."""

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _minute_key(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _hour_key(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


class EventProcessingService:
    """In-memory buffer + metrics + persistence for streaming events."""

    def __init__(self, *, max_recent_events: int = 5000, persist: bool = True) -> None:
        self.max_recent_events = max(100, max_recent_events)
        self.persist = persist

        self._events: deque[dict[str, Any]] = deque(maxlen=self.max_recent_events)
        self._by_id: dict[str, dict[str, Any]] = {}
        self._listeners: list[EventListener] = []
        self._lock = asyncio.Lock()

        # -- rolling counters ----------------------------------------------
        self.total_processed = 0
        self.attacks = 0
        self.normal = 0
        self.category_counts: Counter[str] = Counter()
        self.severity_counts: Counter[str] = Counter()
        self._risk_sum = 0.0
        self._confidence_sum = 0.0
        self.last_event_at: datetime | None = None
        self.started_at = _utc_now()
        self.persistence_written = 0
        self.persistence_dropped = 0

        # -- time-series buckets --------------------------------------------
        self._minute_buckets: dict[datetime, Counter[str]] = {}
        self._host_hour_counts: dict[tuple[datetime, str], int] = {}
        self._hour_severity: dict[datetime, Counter[str]] = {}
        self._second_marks: deque[float] = deque()

        # -- persistence queue ------------------------------------------------
        self._persist_queue: "asyncio.Queue[dict[str, Any] | None] | None" = None
        self._persist_worker: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Start the background persistence worker."""

        if self._persist_worker is not None and not self._persist_worker.done():
            return
        self._persist_queue = asyncio.Queue(maxsize=2000)
        self._persist_worker = asyncio.create_task(
            self._persistence_worker(), name="cybershield-event-persistence"
        )

    async def stop(self) -> None:
        """Flush and stop the persistence worker."""

        queue = self._persist_queue
        if queue is not None:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - extreme backpressure
                pass
        worker = self._persist_worker
        if worker is not None:
            try:
                await asyncio.wait_for(worker, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                worker.cancel()
            except Exception as exc:  # noqa: BLE001
                logger.debug("events.persistence_stop_error", error=str(exc))
        self._persist_worker = None
        self._persist_queue = None

    def subscribe(self, listener: EventListener) -> None:
        """Register an async callback invoked for every processed event."""

        self._listeners.append(listener)

    # ---------------------------------------------------------- ingestion

    async def process_incoming_event(
        self,
        event_data: Mapping[str, Any],
        *,
        notify: bool = True,
        publish: bool = True,
        persist: bool | None = None,
    ) -> dict[str, Any]:
        """Normalize, score, buffer and fan-out one event. Returns the record."""

        record = self.normalize_event(event_data)

        async with self._lock:
            self._buffer_append(record)
            self._update_metrics(record)

        if publish:
            try:
                await get_redis_service().publish_event(settings.redis_event_channel, record)
            except Exception as exc:  # noqa: BLE001 - fan-out is best-effort
                logger.debug("events.redis_publish_failed", error=str(exc))

        if notify:
            for listener in list(self._listeners):
                try:
                    await listener(record)
                except Exception as exc:  # noqa: BLE001 - a bad listener must not break ingestion
                    logger.warning("events.listener_failed", error=str(exc))

        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._enqueue_persistence(record)
        return record

    def normalize_event(self, event_data: Mapping[str, Any]) -> dict[str, Any]:
        """Coerce an arbitrary producer payload into the canonical record."""

        now = _utc_now()
        data = dict(event_data)

        timestamp = _parse_dt(data.get("timestamp") or data.get("event_time")) or now
        event_id = str(data.get("id") or data.get("event_id") or uuid.uuid4())

        attack_category = str(
            data.get("attack_category") or data.get("category") or "Normal"
        )
        predicted_category = str(data.get("predicted_category") or attack_category)
        is_attack = bool(data.get("is_attack", predicted_category != "Normal"))

        confidence = data.get("confidence")
        if confidence is None:
            confidence = 0.92 if is_attack else 0.97
        confidence = float(confidence)
        confidence = min(1.0, max(0.0, confidence))

        anomaly_score = data.get("anomaly_score")
        anomaly_score = float(anomaly_score) if anomaly_score is not None else None

        risk_result: RiskResult | None = None
        risk_score = data.get("risk_score")
        if risk_score is None:
            risk_result = get_risk_engine().calculate_risk(
                attack_category=predicted_category,
                ml_confidence=confidence,
                anomaly_score=anomaly_score or 0.0,
                event_frequency=float(data.get("event_frequency") or 0.0),
                source_reputation=float(data.get("source_reputation") or 0.0),
            )
            risk_score = risk_result.score
        risk_score = round(min(100.0, max(0.0, float(risk_score))), 2)

        engine = get_risk_engine()
        risk_band = str(data.get("risk_band") or engine.band_for(risk_score))
        severity = str(data.get("severity") or engine.severity_for(risk_score))

        src_bytes = int(data.get("src_bytes") or 0)
        dst_bytes = int(data.get("dst_bytes") or 0)
        protocol = str(data.get("protocol") or "TCP").upper()
        if protocol not in ("TCP", "UDP", "ICMP"):
            protocol = "TCP"

        features = {k: v for k, v in (data.get("features") or {}).items()}
        top_features = list(data.get("top_features") or [])
        if not top_features:
            top_features = _DEFAULT_TOP_FEATURES.get(predicted_category, _DEFAULT_TOP_FEATURES["Unknown"])

        probabilities = {
            str(k): round(float(v), 4)
            for k, v in dict(data.get("probabilities") or {}).items()
            if _is_number(v)
        }

        return {
            "id": event_id,
            "timestamp": _iso(timestamp),
            "ingested_at": _iso(_parse_dt(data.get("ingested_at")) or now),
            # -- endpoints ------------------------------------------------
            "source_host": str(data.get("source_host") or "HOST-000"),
            "source_ip": str(data.get("source_ip") or _derive_ip(data.get("source_host"), 1)),
            "destination_host": str(data.get("destination_host") or "HOST-001"),
            "destination_ip": str(data.get("destination_ip") or _derive_ip(data.get("destination_host"), 2)),
            "source_port": _as_int(data.get("source_port")),
            "destination_port": _as_int(data.get("destination_port")),
            # -- flow ------------------------------------------------------
            "protocol": protocol,
            "service": str(data.get("service") or "http"),
            "flag": str(data.get("flag") or "SF"),
            "duration": int(data.get("duration") or 0),
            "src_bytes": src_bytes,
            "dst_bytes": dst_bytes,
            "bytes_total": src_bytes + dst_bytes,
            "packets_sent": int(data.get("packets_sent") or 0),
            "packets_received": int(data.get("packets_received") or 0),
            "bytes_sent": src_bytes,
            "bytes_received": dst_bytes,
            # -- labels & model ------------------------------------------
            "attack_type": str(data.get("attack_type") or ("normal" if not is_attack else "unknown")),
            "attack_category": attack_category,
            "predicted_category": predicted_category,
            "is_attack": is_attack,
            "confidence": round(confidence, 4),
            "probabilities": probabilities,
            "risk_score": risk_score,
            "risk_band": risk_band,
            "severity": severity,
            "anomaly_score": anomaly_score,
            "model_name": str(data.get("model_name") or "cybershield-attack-classifier"),
            "model_version": str(data.get("model_version") or "1.0.0"),
            "latency_ms": _as_float(data.get("latency_ms")) or 0.0,
            "top_features": top_features,
            "status": str(data.get("status") or "new"),
            "features": features,
            "risk_components": (
                [component.__dict__ for component in risk_result.components]
                if risk_result is not None
                else data.get("risk_components")
            ),
        }

    # ------------------------------------------------------------- storage

    def _buffer_append(self, record: dict[str, Any]) -> None:
        if len(self._events) == self.max_recent_events and self._events:
            oldest = self._events[0]
            self._by_id.pop(str(oldest.get("id")), None)
        self._events.append(record)
        self._by_id[str(record["id"])] = record

    def _update_metrics(self, record: dict[str, Any]) -> None:
        moment = _parse_dt(record.get("timestamp")) or _utc_now()
        category = str(record.get("predicted_category") or "Normal")
        severity = str(record.get("severity") or "info")

        self.total_processed += 1
        if record.get("is_attack"):
            self.attacks += 1
        else:
            self.normal += 1
        self.category_counts[category] += 1
        self.severity_counts[severity] += 1
        self._risk_sum += float(record.get("risk_score") or 0.0)
        self._confidence_sum += float(record.get("confidence") or 0.0)
        self.last_event_at = moment

        minute = _minute_key(moment)
        bucket = self._minute_buckets.setdefault(minute, Counter())
        bucket[category] += 1

        host = str(record.get("source_host") or "HOST-000")
        hour = _hour_key(moment)
        if record.get("is_attack"):
            host_key = (hour, host)
            self._host_hour_counts[host_key] = self._host_hour_counts.get(host_key, 0) + 1
            hour_severity = self._hour_severity.setdefault(hour, Counter())
            hour_severity[severity] += 1

        self._second_marks.append(moment.timestamp())
        self._prune_time_series(moment)

    def _prune_time_series(self, now: datetime) -> None:
        # EPS window
        cutoff = now.timestamp() - _EPS_WINDOW_SECONDS
        while self._second_marks and self._second_marks[0] < cutoff:
            self._second_marks.popleft()

        # Keep 8 days of minute buckets / heatmap counters (7d windows + slack).
        oldest_minute = _minute_key(now) - timedelta(days=8)
        for key in [k for k in self._minute_buckets if k < oldest_minute]:
            self._minute_buckets.pop(key, None)
        oldest_hour = _hour_key(now) - timedelta(days=8)
        for key in [k for k in self._host_hour_counts if k[0] < oldest_hour]:
            self._host_hour_counts.pop(key, None)
        for key in [k for k in self._hour_severity if k < oldest_hour]:
            self._hour_severity.pop(key, None)

    async def _persistence_worker(self) -> None:
        """Consume the persistence queue and write events to PostgreSQL."""

        queue = self._persist_queue
        if queue is None:  # pragma: no cover - defensive
            return
        while True:
            record = await queue.get()
            try:
                if record is None:
                    break
                await self._persist_event(record)
            except Exception as exc:  # noqa: BLE001 - worker must never die
                logger.debug("events.persist_failed", error=str(exc))
            finally:
                queue.task_done()

    def _enqueue_persistence(self, record: dict[str, Any]) -> None:
        queue = self._persist_queue
        if queue is None or not database.is_database_available():
            return
        try:
            queue.put_nowait(record)
        except asyncio.QueueFull:  # pragma: no cover - extreme backpressure
            self.persistence_dropped += 1
            if self.persistence_dropped % 100 == 1:
                logger.warning("events.persistence_backpressure", dropped=self.persistence_dropped)

    async def _persist_event(self, record: dict[str, Any]) -> None:
        """Insert one event row (raw_payload keeps the whole record)."""

        if not database.is_database_available():
            return
        try:
            from uuid import UUID

            from app.models import NetworkEvent as NetworkEventModel

            payload = {k: v for k, v in record.items() if _json_safe(v)}
            async with database.session_scope() as session:
                session.add(
                    NetworkEventModel(
                        id=UUID(str(record["id"])),
                        event_time=_parse_dt(record.get("timestamp")) or _utc_now(),
                        source_ip=str(record.get("source_ip") or "0.0.0.0"),
                        destination_ip=str(record.get("destination_ip") or "0.0.0.0"),
                        source_port=_as_int(record.get("source_port")),
                        destination_port=_as_int(record.get("destination_port")),
                        protocol=str(record.get("protocol") or "TCP"),
                        bytes_sent=int(record.get("src_bytes") or 0),
                        bytes_received=int(record.get("dst_bytes") or 0),
                        packets_sent=int(record.get("packets_sent") or 0),
                        packets_received=int(record.get("packets_received") or 0),
                        duration_ms=int(record.get("duration") or 0) * 1000,
                        tcp_flags=str(record.get("flag") or ""),
                        hostname=str(record.get("source_host") or ""),
                        sensor_id="demo-generator" if settings.demo_mode else "kafka-consumer",
                        raw_payload=payload,
                    )
                )
            self.persistence_written += 1
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            raise exc

    # ------------------------------------------------------------- queries

    def get_recent_events(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        attack_type: str | None = None,
        attack_category: str | None = None,
        severity: str | None = None,
        is_attack: bool | None = None,
        min_risk: float | None = None,
        source_ip: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, newest-first listing over the in-memory buffer."""

        needle = search.strip().lower() if search else None
        matches: list[dict[str, Any]] = []
        for record in reversed(self._events):
            moment = _parse_dt(record.get("timestamp"))
            if since is not None and (moment is None or moment < since):
                continue
            if until is not None and (moment is None or moment > until):
                continue
            if attack_type is not None and record.get("attack_type") != attack_type:
                continue
            if attack_category is not None and _neq(record.get("attack_category"), attack_category):
                continue
            if severity is not None and record.get("severity") != severity:
                continue
            if is_attack is not None and bool(record.get("is_attack")) != is_attack:
                continue
            if min_risk is not None and float(record.get("risk_score") or 0.0) < min_risk:
                continue
            if source_ip is not None and record.get("source_ip") != source_ip:
                continue
            if needle and not _matches_search(record, needle):
                continue
            matches.append(record)

        total = len(matches)
        return [dict(item) for item in matches[offset : offset + limit]], total

    def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
        """Look up a single event by id."""

        record = self._by_id.get(str(event_id))
        return dict(record) if record is not None else None

    def get_events_since(self, since: datetime) -> list[dict[str, Any]]:
        """All buffered events at/after ``since`` (oldest first)."""

        result: list[dict[str, Any]] = []
        for record in self._events:
            moment = _parse_dt(record.get("timestamp"))
            if moment is not None and moment >= since:
                result.append(record)
        return result

    def get_minute_buckets(self, since: datetime) -> list[tuple[datetime, Counter[str]]]:
        """Category counts per minute at/after ``since`` (oldest first)."""

        return [
            (minute, counts)
            for minute, counts in sorted(self._minute_buckets.items())
            if minute >= since
        ]

    def get_hourly_host_heat(self, since: datetime) -> dict[tuple[datetime, str], int]:
        """Raw ``(hour, host) -> attacks`` mapping at/after ``since``."""

        return {key: value for key, value in self._host_hour_counts.items() if key[0] >= since}

    def get_hourly_severity(self, since: datetime) -> dict[datetime, Counter[str]]:
        """Severity totals per hour at/after ``since``."""

        return {key: values for key, values in self._hour_severity.items() if key >= since}

    def events_per_second(self) -> float:
        """Rolling events/sec over the last :data:`_EPS_WINDOW_SECONDS`."""

        if not self._second_marks:
            return 0.0
        now = _utc_now().timestamp()
        cutoff = now - _EPS_WINDOW_SECONDS
        while self._second_marks and self._second_marks[0] < cutoff:
            self._second_marks.popleft()
        if not self._second_marks:
            return 0.0
        elapsed = max(1.0, now - self._second_marks[0])
        return round(len(self._second_marks) / elapsed, 2)

    def get_metrics(self) -> dict[str, Any]:
        """JSON-friendly metrics snapshot (used by WS + health endpoints)."""

        uptime = max(0.001, (_utc_now() - self.started_at).total_seconds())
        avg_risk = self._risk_sum / self.total_processed if self.total_processed else 0.0
        avg_confidence = (
            self._confidence_sum / self.total_processed if self.total_processed else 0.0
        )
        return {
            "events_per_sec": self.events_per_second(),
            "avg_events_per_sec": round(self.total_processed / uptime, 2),
            "total_processed": self.total_processed,
            "attacks": self.attacks,
            "normal": self.normal,
            "attack_rate": round(self.attacks / self.total_processed * 100.0, 2)
            if self.total_processed
            else 0.0,
            "category_counts": dict(self.category_counts),
            "severity_counts": dict(self.severity_counts),
            "avg_risk_score": round(avg_risk, 2),
            "avg_confidence": round(avg_confidence, 4),
            "buffer_size": len(self._events),
            "buffer_capacity": self.max_recent_events,
            "persistence_written": self.persistence_written,
            "persistence_dropped": self.persistence_dropped,
            "started_at": self.started_at.isoformat(),
            "last_event_at": _iso(self.last_event_at),
        }

    # ------------------------------------------------------------- helpers

    @property
    def buffer(self) -> Sequence[dict[str, Any]]:
        """Read-only view of the ring buffer (oldest first)."""

        return tuple(self._events)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_search(record: Mapping[str, Any], needle: str) -> bool:
    haystack = " ".join(
        str(record.get(field) or "")
        for field in (
            "source_host",
            "source_ip",
            "destination_host",
            "destination_ip",
            "attack_type",
            "attack_category",
            "predicted_category",
            "service",
        )
    ).lower()
    return needle in haystack


def _neq(value: Any, expected: str) -> bool:
    return str(value or "").lower() != expected.lower()


def _derive_ip(host: Any, fallback_octet: int) -> str:
    """Deterministic synthetic IP for records missing endpoints."""

    if isinstance(host, str) and host.startswith("HOST-"):
        try:
            index = int(host.split("-")[1])
            return f"172.16.{index // 64}.{index % 64 + 1}"
        except (IndexError, ValueError):
            pass
    return f"172.16.0.{fallback_octet}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, list, dict, type(None)))


#: Shared service instance used by API routes and the demo pipeline.
event_service = EventProcessingService()


def get_event_service() -> EventProcessingService:
    """FastAPI-friendly accessor for the shared service."""

    return event_service
