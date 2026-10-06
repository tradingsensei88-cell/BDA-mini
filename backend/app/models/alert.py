"""ORM model for ``alerts`` - actionable SOC alerts.

Mirrors ``infrastructure/postgres/init.sql`` (section 6). The ``metadata``
column is exposed as :attr:`Alert.alert_metadata` because ``metadata`` is
reserved on declarative classes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlertStatusEnum(str, Enum):
    """Alert lifecycle states - mirrors the ``alerts.status`` CHECK constraint.

    ``new`` is accepted as an alias of :attr:`OPEN` at the API edge and
    normalized to ``open``.
    """

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class AlertSeverityEnum(str, Enum):
    """Alert severities - mirrors the ``alerts.severity`` CHECK constraint."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


_SEVERITY_CHECK = "severity IN ('critical', 'high', 'medium', 'low', 'info')"
_STATUS_CHECK = (
    "status IN ('open', 'acknowledged', 'investigating', 'resolved', 'false_positive')"
)


class Alert(Base):
    """An SOC-facing alert derived from predictions or anomaly detections."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(_SEVERITY_CHECK, name="ck_alerts_severity"),
        CheckConstraint(_STATUS_CHECK, name="ck_alerts_status"),
        CheckConstraint(
            "risk_score >= 0 AND risk_score <= 100", name="ck_alerts_risk_score"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    destination_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("predictions.id", ondelete="SET NULL"),
        nullable=True,
    )
    anomaly_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("anomalies.id", ondelete="SET NULL"),
        nullable=True,
    )
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Alert id={self.id} type={self.alert_type!r} severity={self.severity!r} "
            f"status={self.status!r}>"
        )
