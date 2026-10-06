"""ORM model for ``investigations`` - analyst case management.

Mirrors ``infrastructure/postgres/init.sql`` (section 7). Array columns use
native PostgreSQL ``TEXT[]`` / ``UUID[]`` types.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_STATUS_CHECK = "status IN ('open', 'in_progress', 'on_hold', 'closed')"
_PRIORITY_CHECK = "priority IN ('critical', 'high', 'medium', 'low')"
_SEVERITY_CHECK = "severity IN ('critical', 'high', 'medium', 'low', 'info')"


class Investigation(Base):
    """An analyst case file grouping related alerts into one incident."""

    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_investigations_status"),
        CheckConstraint(_PRIORITY_CHECK, name="ck_investigations_priority"),
        CheckConstraint(_SEVERITY_CHECK, name="ck_investigations_severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    analyst: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    attack_vector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mitre_techniques: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    related_alert_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Investigation id={self.id} title={self.title!r} "
            f"status={self.status!r} priority={self.priority!r}>"
        )
