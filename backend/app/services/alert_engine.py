"""Alert Engine.

Promotes security events, anomalies and traffic bursts into SOC alerts:

* **Attack detection** - predicted attack with confidence above
  :attr:`AlertThresholds.attack_confidence` (default 0.7).
* **High-risk prediction** - composite risk score above
  :attr:`AlertThresholds.risk_score` (default 80).
* **Anomaly detection** - anomaly score above
  :attr:`AlertThresholds.anomaly_score` (default 0.7).
* **Attack flood** - more than :attr:`AlertThresholds.attacks_per_minute`
  attacks in a rolling minute (default 100).

Alerts with the same *identity* (type + endpoints + category) inside the
deduplication window are collapsed into a single record whose ``occurrences``
counter is incremented - keeping the feed calm under sustained floods.

Lifecycle statuses follow the database constraint:
``open / acknowledged / investigating / resolved / false_positive``. The API
accepts ``new`` as an alias of ``open``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping

import structlog

from app.core import database
from app.schemas.alerts import normalize_alert_status
from app.services.risk_scoring import get_risk_engine

logger = structlog.get_logger("cybershield.backend.alerts")

AlertListener = Callable[[dict[str, Any], str], Awaitable[None]]

#: Fine category -> alert family.
_CATEGORY_ALERT_TYPE: dict[str, str] = {
    "DoS": "ddos",
    "Probe": "port_scan",
    "R2L": "credential_attack",
    "U2R": "privilege_escalation",
    "Normal": "high_risk",
    "Unknown": "suspicious_activity",
}

_SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_ACTIVE_STATUSES = ("open", "acknowledged", "investigating")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass
class AlertThresholds:
    """Trigger thresholds for alert generation."""

    attack_confidence: float = 0.7
    anomaly_score: float = 0.7
    attacks_per_minute: int = 100
    risk_score: float = 80.0
    dedup_window_seconds: float = 45.0


@dataclass
class _DedupKey:
    """Identity used to collapse duplicate alerts."""

    alert_type: str
    source_ip: str | None
    destination_ip: str | None
    attack_category: str | None

    def as_key(self) -> str:
        return "|".join(
            [
                self.alert_type,
                self.source_ip or "-",
                self.destination_ip or "-",
                (self.attack_category or "-").lower(),
            ]
        )


class AlertEngine:
    """In-memory alert store + rule evaluation.

    The engine is intentionally dependency-free (no database required); when
    PostgreSQL is available alerts are additionally persisted best-effort.
    """

    def __init__(
        self,
        *,
        thresholds: AlertThresholds | None = None,
        max_alerts: int = 2000,
        persist: bool = True,
    ) -> None:
        self.thresholds = thresholds or AlertThresholds()
        self.max_alerts = max(10, max_alerts)
        self.persist = persist

        self._alerts: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._dedup_index: dict[str, tuple[str, float]] = {}
        self._listeners: list[AlertListener] = []
        self._lock = asyncio.Lock()

        # -- counters surfaced through /api/alerts/stats ---------------
        self.total_generated = 0
        self.total_deduplicated = 0
        self.total_anomalies = 0

    # ------------------------------------------------------------ listeners

    def register_listener(self, listener: AlertListener) -> None:
        """Register an async callback invoked as ``listener(alert, event)``.

        ``event`` is ``"new"`` for fresh alerts and ``"updated"`` when a
        duplicate was folded into an existing record.
        """

        self._listeners.append(listener)

    async def _notify(self, alert: dict[str, Any], event: str) -> None:
        for listener in list(self._listeners):
            try:
                await listener(alert, event)
            except Exception as exc:  # noqa: BLE001 - listeners must not break the engine
                logger.warning("alert.listener_failed", error=str(exc))

    # ---------------------------------------------------------- rule engine

    async def process_event(self, security_event: Mapping[str, Any]) -> dict[str, Any] | None:
        """Evaluate one enriched security event and return the alert (if any).

        Returns ``None`` when no rule fires.
        """

        is_attack = bool(security_event.get("is_attack"))
        confidence = _as_float(security_event.get("confidence"), 0.0)
        risk_score = _as_float(security_event.get("risk_score"), 0.0)
        category = _str(security_event.get("predicted_category") or security_event.get("attack_category"))
        anomaly_score = _as_float(security_event.get("anomaly_score"), 0.0)

        reasons: list[str] = []
        if is_attack and confidence >= self.thresholds.attack_confidence:
            reasons.append("attack_detected")
        if is_attack and risk_score >= self.thresholds.risk_score:
            reasons.append("high_risk")
        if anomaly_score >= self.thresholds.anomaly_score and is_attack:
            reasons.append("anomaly_detected")

        if not reasons:
            return None

        alert_type = _CATEGORY_ALERT_TYPE.get(category or "Unknown", "suspicious_activity")
        if anomaly_score >= self.thresholds.anomaly_score and not is_attack:
            alert_type = "anomaly"
        return await self._build_and_store(
            alert_type=alert_type,
            reason="+".join(reasons),
            attack_category=category,
            attack_type=_str(security_event.get("attack_type")),
            source_host=_str(security_event.get("source_host")),
            source_ip=_str(security_event.get("source_ip")),
            destination_host=_str(security_event.get("destination_host")),
            destination_ip=_str(security_event.get("destination_ip")),
            risk_score=risk_score,
            confidence=confidence,
            event_id=_str(security_event.get("id")),
            evidence={
                "model_name": security_event.get("model_name"),
                "model_version": security_event.get("model_version"),
                "anomaly_score": anomaly_score,
                "thresholds": {
                    "attack_confidence": self.thresholds.attack_confidence,
                    "risk_score": self.thresholds.risk_score,
                },
            },
        )

    async def process_anomaly(self, anomaly: Mapping[str, Any]) -> dict[str, Any] | None:
        """Promote an anomaly detection result into an alert."""

        score = _as_float(anomaly.get("anomaly_score"), 0.0)
        if score < self.thresholds.anomaly_score:
            return None

        self.total_anomalies += 1
        return await self._build_and_store(
            alert_type="anomaly",
            reason="anomaly_detected",
            attack_category=_str(anomaly.get("attack_category")) or "Unknown",
            attack_type=_str(anomaly.get("method")) or "isolation_forest",
            source_host=_str(anomaly.get("source_host")),
            source_ip=_str(anomaly.get("source_ip")),
            destination_host=_str(anomaly.get("destination_host")),
            destination_ip=None,
            risk_score=min(100.0, score * 100.0),
            confidence=score,
            event_id=_str(anomaly.get("id")),
            evidence={
                "method": anomaly.get("method", "isolation_forest"),
                "anomaly_score": score,
                "features": anomaly.get("features", {}),
            },
        )

    async def process_frequency(self, attacks_last_minute: int) -> dict[str, Any] | None:
        """Raise a flood alert when the rolling attack rate crosses the threshold."""

        if attacks_last_minute < self.thresholds.attacks_per_minute:
            return None
        return await self._build_and_store(
            alert_type="attack_flood",
            reason="frequency_threshold",
            attack_category="Unknown",
            attack_type="burst",
            source_host=None,
            source_ip=None,
            destination_host=None,
            destination_ip=None,
            risk_score=min(100.0, 60.0 + attacks_last_minute / 10.0),
            confidence=0.9,
            event_id=None,
            evidence={"attacks_last_minute": attacks_last_minute},
        )

    # ------------------------------------------------------------- creation

    async def create_alert(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Manually open an alert (used by tooling / tests)."""

        alert = await self._build_and_store(
            alert_type=_str(payload.get("alert_type")) or "manual",
            reason="manual",
            attack_category=_str(payload.get("attack_category")),
            attack_type=None,
            source_host=None,
            source_ip=_str(payload.get("source_ip")),
            destination_host=None,
            destination_ip=_str(payload.get("destination_ip")),
            risk_score=_as_float(payload.get("risk_score"), 0.0),
            confidence=None,
            event_id=None,
            evidence={"manual": True},
            title=_str(payload.get("title")),
            description=_str(payload.get("description")),
            severity=_str(payload.get("severity")),
        )
        assert alert is not None  # manual creation always stores
        return alert

    async def _build_and_store(
        self,
        *,
        alert_type: str,
        reason: str,
        attack_category: str | None,
        attack_type: str | None,
        source_host: str | None,
        source_ip: str | None,
        destination_host: str | None,
        destination_ip: str | None,
        risk_score: float,
        confidence: float | None,
        event_id: str | None,
        evidence: dict[str, Any],
        title: str | None = None,
        description: str | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        resolved_severity = severity or get_risk_engine().severity_for(risk_score)

        key = _DedupKey(alert_type, source_ip, destination_ip, attack_category).as_key()
        async with self._lock:
            duplicate_id = self._dedup_lookup(key, now)

            if duplicate_id is not None:
                existing = self._alerts.get(duplicate_id)
                if existing is not None:
                    alert = self._merge_duplicate(
                        existing,
                        now=now,
                        risk_score=risk_score,
                        confidence=confidence,
                        severity=resolved_severity,
                        event_id=event_id,
                        evidence=evidence,
                    )
                    self._dedup_index[key] = (duplicate_id, time.monotonic())
                    self.total_deduplicated += 1
                    updated = dict(alert)
                    self._persist_best_effort(updated)
                    await self._notify(updated, "updated")
                    return updated

            alert_id = str(uuid.uuid4())
            alert = {
                "id": alert_id,
                "alert_type": alert_type,
                "title": title or _default_title(alert_type, source_host, source_ip, attack_type),
                "description": description or _default_description(
                    alert_type, reason, attack_category, attack_type, source_ip, risk_score, confidence
                ),
                "severity": resolved_severity,
                "status": "open",
                "risk_score": round(float(risk_score), 2),
                "confidence": round(float(confidence), 4) if confidence is not None else None,
                "source_host": source_host,
                "source_ip": source_ip,
                "destination_host": destination_host,
                "destination_ip": destination_ip,
                "attack_category": attack_category,
                "attack_type": attack_type,
                "occurrences": 1,
                "related_event_ids": [event_id] if event_id else [],
                "evidence": {"reason": reason, **evidence},
                "assigned_to": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "acknowledged_at": None,
                "resolved_at": None,
            }
            self._alerts[alert_id] = alert
            self._dedup_index[key] = (alert_id, time.monotonic())
            self.total_generated += 1
            self._enforce_capacity()
            self._persist_best_effort(alert)

        await self._notify(alert, "new")
        logger.info(
            "alert.created",
            alert_id=alert_id,
            alert_type=alert_type,
            severity=resolved_severity,
            reason=reason,
        )
        return alert

    def _merge_duplicate(
        self,
        existing: dict[str, Any],
        *,
        now: datetime,
        risk_score: float,
        confidence: float | None,
        severity: str,
        event_id: str | None,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
        existing["risk_score"] = round(max(_as_float(existing.get("risk_score"), 0.0), float(risk_score)), 2)
        if confidence is not None:
            existing["confidence"] = round(
                max(_as_float(existing.get("confidence"), 0.0), float(confidence)), 4
            )
        # Escalate severity only (never silently de-escalate).
        if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(existing.get("severity", "info"), 0):
            existing["severity"] = severity
        if event_id:
            related = existing.setdefault("related_event_ids", [])
            if event_id not in related:
                related.append(event_id)
                del related[:-50]  # keep the 50 most recent ids
        merged_evidence = existing.setdefault("evidence", {})
        merged_evidence.update({k: v for k, v in evidence.items() if k == "anomaly_score"})
        merged_evidence["last_occurrence_at"] = now.isoformat()
        existing["updated_at"] = now.isoformat()
        return existing

    def _dedup_lookup(self, key: str, now: datetime) -> str | None:
        """Return the id of a recent alert matching ``key`` (or ``None``)."""

        entry = self._dedup_index.get(key)
        if entry is None:
            return None
        alert_id, seen_monotonic = entry
        if (time.monotonic() - seen_monotonic) > self.thresholds.dedup_window_seconds:
            self._dedup_index.pop(key, None)
            return None
        return alert_id if alert_id in self._alerts else None

    def _enforce_capacity(self) -> None:
        while len(self._alerts) > self.max_alerts:
            self._alerts.popitem(last=False)

    def _persist_best_effort(self, alert: dict[str, Any]) -> None:
        """Write the alert to PostgreSQL without blocking the caller."""

        if not self.persist or not database.is_database_available():
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist_alert(alert))
        except RuntimeError:  # pragma: no cover - no running loop (sync context)
            pass

    # ------------------------------------------------------------- queries

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        """Return one alert by id."""

        alert = self._alerts.get(alert_id)
        return dict(alert) if alert is not None else None

    def list_alerts(
        self,
        *,
        statuses: Iterable[str] | None = None,
        severity: str | None = None,
        alert_type: str | None = None,
        search: str | None = None,
        min_risk: float | None = None,
        since: datetime | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, newest-first alert listing; returns ``(page, total)``."""

        wanted_statuses = {normalize_alert_status(s) for s in statuses} if statuses else None
        needle = search.strip().lower() if search else None

        matches: list[dict[str, Any]] = []
        for alert in reversed(self._alerts.values()):  # newest first
            if wanted_statuses is not None and alert.get("status") not in wanted_statuses:
                continue
            if severity is not None and alert.get("severity") != severity:
                continue
            if alert_type is not None and alert.get("alert_type") != alert_type:
                continue
            if min_risk is not None and _as_float(alert.get("risk_score"), 0.0) < min_risk:
                continue
            if since is not None and _parse_iso(alert.get("created_at")) < since:
                continue
            if needle and not _matches_search(alert, needle):
                continue
            matches.append(dict(alert))

        total = len(matches)
        return matches[offset : offset + limit], total

    def get_active_alert_count(self) -> int:
        """Number of alerts still in an active (unresolved) state."""

        return sum(1 for a in self._alerts.values() if a.get("status") in _ACTIVE_STATUSES)

    def get_stats(self, *, recent_limit: int = 8) -> dict[str, Any]:
        """Aggregate counts for ``GET /api/alerts/stats``."""

        by_severity: dict[str, int] = {key: 0 for key in _SEVERITY_RANK}
        by_status: dict[str, int] = {key: 0 for key in ("open", "acknowledged", "investigating", "resolved", "false_positive")}
        risk_total = 0.0
        risk_count = 0
        last_24h = 0
        cutoff = _utc_now() - timedelta(hours=24)
        recent: list[dict[str, Any]] = []

        for alert in reversed(self._alerts.values()):
            by_severity[alert.get("severity", "info")] = by_severity.get(alert.get("severity", "info"), 0) + 1
            by_status[alert.get("status", "open")] = by_status.get(alert.get("status", "open"), 0) + 1
            risk = alert.get("risk_score")
            if risk is not None:
                risk_total += float(risk)
                risk_count += 1
            created = _parse_iso(alert.get("created_at"))
            if created is not None and created >= cutoff:
                last_24h += 1
            if len(recent) < recent_limit:
                recent.append(dict(alert))

        return {
            "total": len(self._alerts),
            "active": self.get_active_alert_count(),
            "last_24h": last_24h,
            "avg_risk_score": round(risk_total / risk_count, 2) if risk_count else 0.0,
            "by_severity": [{"key": key, "count": count} for key, count in by_severity.items()],
            "by_status": [{"key": key, "count": count} for key, count in by_status.items()],
            "recent": recent,
        }

    # ------------------------------------------------------------ lifecycle

    async def update_alert_status(
        self,
        alert_id: str,
        new_status: str,
        *,
        assigned_to: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        """Transition an alert to ``new_status``; returns the updated alert."""

        normalized = normalize_alert_status(new_status)
        async with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                return None

            now = _utc_now()
            previous = alert.get("status")
            alert["status"] = normalized
            alert["updated_at"] = now.isoformat()
            if normalized == "acknowledged" and not alert.get("acknowledged_at"):
                alert["acknowledged_at"] = now.isoformat()
            if normalized in ("resolved", "false_positive"):
                alert["resolved_at"] = now.isoformat()
                if not alert.get("acknowledged_at"):
                    alert["acknowledged_at"] = now.isoformat()
            if assigned_to is not None:
                alert["assigned_to"] = assigned_to
            if note:
                evidence = alert.setdefault("evidence", {})
                notes = evidence.setdefault("notes", [])
                notes.append({"at": now.isoformat(), "text": note})
            updated = dict(alert)

        logger.info(
            "alert.status_updated",
            alert_id=alert_id,
            previous=previous,
            current=normalized,
        )
        self._persist_best_effort(updated)
        await self._notify(updated, "updated")
        return updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_title(
    alert_type: str, source_host: str | None, source_ip: str | None, attack_type: str | None
) -> str:
    origin = source_host or source_ip or "unknown source"
    detail = f"{attack_type} " if attack_type and attack_type not in alert_type else ""
    heading = {
        "ddos": "DoS flood",
        "port_scan": "Port scan",
        "credential_attack": "Credential attack",
        "privilege_escalation": "Privilege escalation",
        "anomaly": "Anomalous traffic",
        "attack_flood": "Attack flood",
        "high_risk": "High-risk flow",
        "manual": "Manual alert",
    }.get(alert_type, alert_type.replace("_", " ").title())
    return f"{heading}: {detail}from {origin}".strip()


def _default_description(
    alert_type: str,
    reason: str,
    attack_category: str | None,
    attack_type: str | None,
    source_ip: str | None,
    risk_score: float,
    confidence: float | None,
) -> str:
    parts = [f"{alert_type.replace('_', ' ')} triggered by {reason.replace('+', ' + ')}"]
    if attack_category:
        parts.append(f"category={attack_category}")
    if attack_type:
        parts.append(f"type={attack_type}")
    if source_ip:
        parts.append(f"source={source_ip}")
    parts.append(f"risk={risk_score:.1f}")
    if confidence is not None:
        parts.append(f"confidence={confidence:.2f}")
    return "; ".join(parts) + "."


def _matches_search(alert: Mapping[str, Any], needle: str) -> bool:
    haystack = " ".join(
        str(alert.get(field) or "")
        for field in (
            "title",
            "description",
            "source_ip",
            "source_host",
            "destination_ip",
            "destination_host",
            "attack_type",
            "attack_category",
            "alert_type",
        )
    ).lower()
    return needle in haystack


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result


def _as_float(value: Any, default: float | None) -> float:
    try:
        if value is None:
            return default  # type: ignore[return-value]
        return float(value)
    except (TypeError, ValueError):
        return default  # type: ignore[return-value]


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _persist_alert(alert: Mapping[str, Any]) -> None:
    """Best-effort insert into the ``alerts`` table."""

    try:
        from uuid import UUID

        from app.models import Alert as AlertModel

        async with database.session_scope() as session:
            session.add(
                AlertModel(
                    id=UUID(str(alert["id"])),
                    alert_type=str(alert["alert_type"]),
                    title=str(alert["title"]),
                    description=alert.get("description"),
                    severity=str(alert.get("severity", "medium")),
                    status=str(alert.get("status", "open")),
                    source_ip=alert.get("source_ip"),
                    destination_ip=alert.get("destination_ip"),
                    risk_score=alert.get("risk_score"),
                    assigned_to=alert.get("assigned_to"),
                    alert_metadata={
                        "attack_category": alert.get("attack_category"),
                        "attack_type": alert.get("attack_type"),
                        "occurrences": alert.get("occurrences"),
                        "evidence": alert.get("evidence"),
                    },
                )
            )
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.debug("alert.persist_skipped", error=str(exc))


#: Shared engine instance used by API routes and the demo pipeline.
alert_engine = AlertEngine()


def get_alert_engine() -> AlertEngine:
    """FastAPI-friendly accessor for the shared engine."""

    return alert_engine
