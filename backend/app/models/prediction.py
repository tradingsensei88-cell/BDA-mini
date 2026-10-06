"""ORM model for ``predictions`` - per-event model inference results.

Mirrors ``infrastructure/postgres/init.sql`` (section 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Prediction(Base):
    """Model inference output for a single network/security event."""

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_predictions_confidence"
        ),
        CheckConstraint("latency_ms >= 0", name="ck_predictions_latency_ms"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("network_events.id", ondelete="CASCADE"),
        nullable=True,
    )
    security_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_attack: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attack_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    probabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    feature_vector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Prediction id={self.id} attack={self.is_attack} "
            f"type={self.attack_type!r} conf={self.confidence}>"
        )
