"""Investigation Service.

Analyst case management: opens case files from alerts, tracks status and
serves the ``/api/investigations`` endpoints.

State lives in memory (like every other service) and is persisted to
PostgreSQL best-effort when the database is available.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Mapping

import structlog

from app.core import database

logger = structlog.get_logger("cybershield.backend.investigations")

_VALID_STATUSES = ("open", "in_progress", "on_hold", "closed")

_SEVERITY_TO_PRIORITY: dict[str, str] = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "low",
}

_ALERT_TYPE_TO_VECTOR: dict[str, str] = {
    "ddos": "network",
    "attack_flood": "network",
    "port_scan": "network",
    "credential_attack": "remote_access",
    "privilege_escalation": "local",
    "anomaly": "unknown",
    "high_risk": "unknown",
}

_ALERT_TYPE_TO_MITRE: dict[str, list[str]] = {
    "ddos": ["T1498"],
    "attack_flood": ["T1498"],
    "port_scan": ["T1046"],
    "credential_attack": ["T1110"],
    "privilege_escalation": ["T1068"],
    "anomaly": ["T1071"],
    "high_risk": ["T1071"],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvestigationService:
    """In-memory investigation store with best-effort persistence."""

    def __init__(self, *, max_records: int = 500, persist: bool = True) -> None:
        self.max_records = max(10, max_records)
        self.persist = persist
        self._records: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------- creation

    async def create_from_alert(
        self,
        alert: Mapping[str, Any],
        *,
        title: str | None = None,
        analyst: str | None = None,
        priority: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Open a case file from an alert payload."""

        severity = str(alert.get("severity") or "medium")
        alert_type = str(alert.get("alert_type") or "suspicious_activity")
        now = _utc_now().isoformat()

        record = {
            "id": str(uuid.uuid4()),
            "title": (title or f"Investigation: {alert.get('title') or alert_type}")[:255],
            "status": "open",
            "priority": priority or _SEVERITY_TO_PRIORITY.get(severity, "medium"),
            "severity": severity,
            "analyst": analyst,
            "summary": summary
            or (
                f"Opened from alert {alert.get('id')} ({alert_type}). "
                f"Source {alert.get('source_host') or alert.get('source_ip') or 'unknown'}."
            ),
            "findings": None,
            "attack_vector": _ALERT_TYPE_TO_VECTOR.get(alert_type, "unknown"),
            "mitre_techniques": list(_ALERT_TYPE_TO_MITRE.get(alert_type, [])),
            "tags": list(tags or [alert_type]),
            "related_alert_ids": [str(alert.get("id"))] if alert.get("id") else [],
            "opened_at": now,
            "closed_at": None,
            "created_at": now,
            "updated_at": now,
        }

        async with self._lock:
            self._records[record["id"]] = record
            while len(self._records) > self.max_records:
                self._records.popitem(last=False)

        self._persist_best_effort(record)
        logger.info(
            "investigation.created",
            investigation_id=record["id"],
            alert_id=alert.get("id"),
            priority=record["priority"],
        )
        return dict(record)

    async def seed_demo(
        self,
        alerts: list[Mapping[str, Any]],
        *,
        count: int = 5,
        analysts: tuple[str, ...] = ("analyst-7", "analyst-2", "analyst-11", "analyst-4"),
    ) -> list[dict[str, Any]]:
        """Open a handful of cases from recent alerts (demo bootstrap)."""

        created: list[dict[str, Any]] = []
        selected = alerts[: max(0, count)]
        for index, alert in enumerate(selected):
            record = await self.create_from_alert(
                alert,
                analyst=analysts[index % len(analysts)],
                summary=(
                    f"Auto-opened during demo bootstrap. {alert.get('description') or ''}"
                ).strip(),
                tags=[str(alert.get("alert_type") or "triage"), "demo"],
            )
            # Spread the cases across the lifecycle so the UI shows variety.
            if index % 3 == 1:
                record = await self._set_status(record["id"], "in_progress") or record
            elif index % 3 == 2:
                record = await self._set_status(record["id"], "closed") or record
            created.append(record)
        return created

    async def _set_status(self, investigation_id: str, status: str) -> dict[str, Any] | None:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid investigation status {status!r}")
        async with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return None
            now = _utc_now().isoformat()
            record["status"] = status
            record["updated_at"] = now
            if status == "closed":
                record["closed_at"] = now
            return dict(record)

    # --------------------------------------------------------------- queries

    def get(self, investigation_id: str) -> dict[str, Any] | None:
        """Fetch one investigation by id."""

        record = self._records.get(str(investigation_id))
        return dict(record) if record is not None else None

    def list_investigations(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, newest-first listing; returns ``(page, total)``."""

        needle = search.strip().lower() if search else None
        matches: list[dict[str, Any]] = []
        for record in reversed(self._records.values()):
            if status and record.get("status") != status:
                continue
            if needle and needle not in _search_blob(record):
                continue
            matches.append(dict(record))
        total = len(matches)
        return matches[offset : offset + limit], total

    def find_by_alert(self, alert_id: str) -> list[dict[str, Any]]:
        """All investigations referencing ``alert_id``."""

        return [
            dict(record)
            for record in self._records.values()
            if str(alert_id) in [str(a) for a in record.get("related_alert_ids") or []]
        ]

    def count(self) -> int:
        """Total investigations held."""

        return len(self._records)

    # ----------------------------------------------------------- persistence

    def _persist_best_effort(self, record: Mapping[str, Any]) -> None:
        if not self.persist or not database.is_database_available():
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist_investigation(dict(record)))
        except RuntimeError:  # pragma: no cover - no running loop
            pass


def _search_blob(record: Mapping[str, Any]) -> str:
    return " ".join(
        str(record.get(field) or "")
        for field in ("title", "summary", "analyst", "attack_vector", "tags", "mitre_techniques")
    ).lower()


async def _persist_investigation(record: Mapping[str, Any]) -> None:
    """Best-effort insert into the ``investigations`` table."""

    try:
        from uuid import UUID

        from app.models import Investigation as InvestigationModel

        async with database.session_scope() as session:
            session.add(
                InvestigationModel(
                    id=UUID(str(record["id"])),
                    title=str(record["title"]),
                    status=str(record.get("status", "open")),
                    priority=str(record.get("priority", "medium")),
                    severity=str(record.get("severity", "medium")),
                    analyst=record.get("analyst"),
                    summary=record.get("summary"),
                    findings=record.get("findings"),
                    attack_vector=record.get("attack_vector"),
                    mitre_techniques=list(record.get("mitre_techniques") or []),
                    tags=list(record.get("tags") or []),
                    related_alert_ids=[
                        UUID(str(alert_id))
                        for alert_id in record.get("related_alert_ids") or []
                        if _is_uuid(alert_id)
                    ],
                )
            )
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.debug("investigation.persist_skipped", error=str(exc))


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


#: Shared service instance.
investigation_service = InvestigationService()


def get_investigation_service() -> InvestigationService:
    """FastAPI-friendly accessor for the shared service."""

    return investigation_service
