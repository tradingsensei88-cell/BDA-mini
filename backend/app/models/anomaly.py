"""ORM model for ``anomalies`` - unsupervised outlier detections.

Mirrors ``infrastructure/postgres/init.sql`` (section 5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Anomaly(Base):
    """A sliding-window anomaly detection result (e.g. Isolation Forest)."""

    __tablename__ = "anomalies"
    __table_args__ = (
        CheckConstraint("window_end >= window_start", name="chk_anomalies_window"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="isolation_forest")
    anomaly_score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    is_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Anomaly id={self.id} score={self.anomaly_score} "
            f"method={self.method!r}>"
        )
