"""ORM model for ``security_events`` - normalized detections from IDS/IPS and logs.

Mirrors ``infrastructure/postgres/init.sql`` (section 2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_SEVERITY_CHECK = "severity IN ('critical', 'high', 'medium', 'low', 'info')"


class SecurityEvent(Base):
    """A normalized security detection (port scan, brute force, DDoS, ...)."""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(_SEVERITY_CHECK, name="ck_security_events_severity"),
        CheckConstraint(
            "destination_port BETWEEN 0 AND 65535",
            name="ck_security_events_destination_port",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    destination_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    destination_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mitre_technique: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_log: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SecurityEvent id={self.id} type={self.event_type!r} "
            f"severity={self.severity!r}>"
        )
