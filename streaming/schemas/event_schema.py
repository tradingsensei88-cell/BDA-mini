"""CyberShield AI - Pydantic schemas for every Kafka message in the pipeline.

This module is the **single source of truth** for the message contract shared
by producers, consumers, Spark streaming jobs and the ML layer:

* :data:`NSL_KDD_FEATURE_FIELDS` - canonical ordered list of the 41 NSL-KDD
  features (mirrors the raw ``KDDTrain+``/``KDDTest+`` column order).
* :class:`NetworkEvent` - one raw network flow event published to
  ``network-events``.
* :class:`SecurityEvent` - a :class:`NetworkEvent` enriched with model
  predictions (category, confidence, risk score).
* :class:`Alert` - an actionable SOC alert derived from predictions/anomalies.
* :class:`AnomalyEvent` - unsupervised (Isolation Forest) detection result.

All timestamps are normalised to timezone-aware UTC datetimes on validation,
so downstream consumers can rely on a single temporal convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, field_validator, model_validator

# =============================================================================
# Kafka topic names (must match infrastructure/kafka/create-topics.sh)
# =============================================================================

TOPIC_NETWORK_EVENTS = "network-events"
TOPIC_SECURITY_EVENTS = "security-events"
TOPIC_PREDICTIONS = "predictions"
TOPIC_ALERTS = "alerts"
TOPIC_ANOMALIES = "anomalies"

#: Suffix used for dead-letter topics (e.g. ``network-events.dlq``).
DLQ_TOPIC_SUFFIX = ".dlq"


def dlq_topic_name(topic: str) -> str:
    """Return the dead-letter topic name for ``topic``."""

    return f"{topic}{DLQ_TOPIC_SUFFIX}"


# =============================================================================
# Canonical NSL-KDD column definitions (41 features + 2 labels)
# =============================================================================

#: The 41 NSL-KDD features, in the exact order used by the raw dataset files.
NSL_KDD_FEATURE_FIELDS: tuple[str, ...] = (
    "duration",
    "protocol_type",
    "service",
    "flag",
    "src_bytes",
    "dst_bytes",
    "land",
    "wrong_fragment",
    "urgent",
    "hot",
    "num_failed_logins",
    "logged_in",
    "num_compromised",
    "root_shell",
    "su_attempted",
    "num_root",
    "num_file_creations",
    "num_shells",
    "num_access_files",
    "num_outbound_cmds",
    "is_host_login",
    "is_guest_login",
    "count",
    "srv_count",
    "serror_rate",
    "srv_serror_rate",
    "rerror_rate",
    "srv_rerror_rate",
    "same_srv_rate",
    "diff_srv_rate",
    "srv_diff_host_rate",
    "dst_host_count",
    "dst_host_srv_count",
    "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate",
    "dst_host_srv_serror_rate",
    "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
)

#: The two label columns present in the raw dataset (not features).
NSL_KDD_LABEL_FIELDS: tuple[str, ...] = ("attack_type", "difficulty_level")

#: All 43 raw dataset columns in file order.
NSL_KDD_COLUMNS: tuple[str, ...] = NSL_KDD_FEATURE_FIELDS + NSL_KDD_LABEL_FIELDS

#: Features that are categorical strings in the raw dataset.
NSL_KDD_CATEGORICAL_FIELDS: tuple[str, ...] = ("protocol_type", "service", "flag")

#: Features constrained to 0/1 (or small ordinal) flags - excluded from scaling.
NSL_KDD_BINARY_FIELDS: tuple[str, ...] = (
    "land",
    "logged_in",
    "root_shell",
    "su_attempted",
    "is_host_login",
    "is_guest_login",
)

# =============================================================================
# Enumerations
# =============================================================================


class AttackCategory(str, Enum):
    """The five NSL-KDD attack super-categories (plus a defensive fallback)."""

    NORMAL = "Normal"
    DOS = "DoS"
    PROBE = "Probe"
    R2L = "R2L"
    U2R = "U2R"
    UNKNOWN = "Unknown"


class Severity(str, Enum):
    """Alert/incident severity levels (mirrors the ``alerts.severity`` CHECK)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(str, Enum):
    """Alert lifecycle states (mirrors the ``alerts.status`` CHECK)."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


# =============================================================================
# Shared helpers
# =============================================================================


def utc_now() -> datetime:
    """Timezone-aware UTC now."""

    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC (naive values assumed UTC)."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


#: Relative severity weight per category used by :func:`compute_risk_score`.
_CATEGORY_RISK_WEIGHT: dict[AttackCategory, float] = {
    AttackCategory.U2R: 1.00,
    AttackCategory.R2L: 0.90,
    AttackCategory.DOS: 0.80,
    AttackCategory.UNKNOWN: 0.70,
    AttackCategory.PROBE: 0.55,
    AttackCategory.NORMAL: 0.20,
}


def compute_risk_score(category: AttackCategory, confidence: float) -> float:
    """Heuristic risk score in ``[0, 100]`` from category weight x confidence."""

    weight = _CATEGORY_RISK_WEIGHT.get(category, 0.5)
    return round(min(100.0, max(0.0, weight * float(confidence) * 100.0)), 2)


def severity_from_risk_score(risk_score: float) -> Severity:
    """Map a 0-100 risk score onto :class:`Severity` bands."""

    if risk_score >= 85:
        return Severity.CRITICAL
    if risk_score >= 65:
        return Severity.HIGH
    if risk_score >= 40:
        return Severity.MEDIUM
    if risk_score >= 15:
        return Severity.LOW
    return Severity.INFO


# =============================================================================
# 1. NetworkEvent - raw flow event published to `network-events`
# =============================================================================


class NetworkEvent(BaseModel):
    """A single NSL-KDD style network flow event, Kafka-serialisable as JSON.

    Carries the 41 canonical features plus pipeline metadata (identity,
    timestamps, synthetic host topology, attack ground-truth labels).
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # -- Pipeline metadata ---------------------------------------------------
    event_id: uuid.UUID = Field(description="Unique event id (UUID4).")
    timestamp: datetime = Field(description="Event time (UTC, ISO-8601 on the wire).")

    # -- Basic connection features -------------------------------------------
    duration: int = Field(default=0, ge=0, description="Connection duration (seconds).")
    protocol_type: str = Field(default="tcp", description="tcp / udp / icmp.")
    service: str = Field(default="http", description="Destination service (http, ftp, ...).")
    flag: str = Field(default="SF", description="Connection state flag (SF, S0, REJ, ...).")
    src_bytes: int = Field(default=0, ge=0)
    dst_bytes: int = Field(default=0, ge=0)
    land: int = Field(default=0, ge=0, le=3)
    wrong_fragment: int = Field(default=0, ge=0)
    urgent: int = Field(default=0, ge=0)

    # -- Content features ------------------------------------------------------
    hot: int = Field(default=0, ge=0)
    num_failed_logins: int = Field(default=0, ge=0)
    logged_in: int = Field(default=0, ge=0, le=3)
    num_compromised: int = Field(default=0, ge=0)
    root_shell: int = Field(default=0, ge=0, le=3)
    su_attempted: int = Field(default=0, ge=0, le=3)
    num_root: int = Field(default=0, ge=0)
    num_file_creations: int = Field(default=0, ge=0)
    num_shells: int = Field(default=0, ge=0)
    num_access_files: int = Field(default=0, ge=0)
    num_outbound_cmds: int = Field(default=0, ge=0)
    is_host_login: int = Field(default=0, ge=0, le=1)
    is_guest_login: int = Field(default=0, ge=0, le=1)

    # -- Time-based traffic features -------------------------------------------
    count: int = Field(default=0, ge=0)
    srv_count: int = Field(default=0, ge=0)
    serror_rate: float = Field(default=0.0, ge=0, le=1)
    srv_serror_rate: float = Field(default=0.0, ge=0, le=1)
    rerror_rate: float = Field(default=0.0, ge=0, le=1)
    srv_rerror_rate: float = Field(default=0.0, ge=0, le=1)
    same_srv_rate: float = Field(default=0.0, ge=0, le=1)
    diff_srv_rate: float = Field(default=0.0, ge=0, le=1)
    srv_diff_host_rate: float = Field(default=0.0, ge=0, le=1)

    # -- Host-based traffic features --------------------------------------------
    dst_host_count: int = Field(default=0, ge=0, le=255)
    dst_host_srv_count: int = Field(default=0, ge=0, le=255)
    dst_host_same_srv_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_diff_srv_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_same_src_port_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_srv_diff_host_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_serror_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_srv_serror_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_rerror_rate: float = Field(default=0.0, ge=0, le=1)
    dst_host_srv_rerror_rate: float = Field(default=0.0, ge=0, le=1)

    # -- Ground-truth labels (from the dataset) ---------------------------------
    attack_type: str = Field(default="normal", description="Fine-grained NSL-KDD label.")
    attack_category: AttackCategory = Field(
        default=AttackCategory.NORMAL, description="DoS / Probe / R2L / U2R / Normal."
    )
    difficulty_level: int | None = Field(default=None, ge=0, le=100)

    # -- Synthetic topology / enrichment -----------------------------------------
    source_host: str = Field(default="HOST-001", description="Origin host name.")
    destination_host: str = Field(default="HOST-002", description="Target host name.")
    source_ip: IPvAnyAddress | None = Field(default=None, description="Origin IP.")
    destination_ip: IPvAnyAddress | None = Field(default=None, description="Target IP.")
    source_port: int | None = Field(default=None, ge=0, le=65535)
    destination_port: int | None = Field(default=None, ge=0, le=65535)

    # -- Validators --------------------------------------------------------------

    @field_validator("timestamp", mode="after")
    @classmethod
    def _timestamp_to_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    # -- Convenience helpers -------------------------------------------------------

    @property
    def is_attack(self) -> bool:
        """``True`` when the ground-truth category is not ``Normal``."""

        return self.attack_category is not AttackCategory.NORMAL

    def feature_vector(self) -> dict[str, Any]:
        """Return the 41 canonical NSL-KDD features as an ordered dict."""

        return {name: getattr(self, name) for name in NSL_KDD_FEATURE_FIELDS}


# =============================================================================
# 2. SecurityEvent - enriched detection result
# =============================================================================

DEFAULT_MODEL_NAME = "cybershield-attack-classifier"
DEFAULT_MODEL_VERSION = "0.1.0-bootstrap"


class SecurityEvent(BaseModel):
    """A :class:`NetworkEvent` enriched with model prediction + risk scoring."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    network_event_id: uuid.UUID | None = Field(
        default=None, description="Reference to the originating NetworkEvent."
    )
    timestamp: datetime = Field(default_factory=utc_now, description="Source event time (UTC).")
    predicted_at: datetime = Field(default_factory=utc_now, description="Inference time (UTC).")

    model_name: str = DEFAULT_MODEL_NAME
    model_version: str = DEFAULT_MODEL_VERSION

    predicted_category: AttackCategory
    attack_type: str | None = Field(
        default=None, description="Fine-grained predicted attack type, when available."
    )
    is_attack: bool
    confidence: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=100.0)
    probabilities: dict[str, float] = Field(
        default_factory=dict, description="Per-class probability distribution."
    )

    source_host: str | None = None
    destination_host: str | None = None
    source_ip: IPvAnyAddress | None = None
    destination_ip: IPvAnyAddress | None = None

    latency_ms: float | None = Field(default=None, ge=0, description="Inference latency.")

    @field_validator("timestamp", "predicted_at", mode="after")
    @classmethod
    def _timestamps_to_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @classmethod
    def from_network_event(
        cls,
        event: NetworkEvent,
        *,
        predicted_category: AttackCategory,
        confidence: float,
        attack_type: str | None = None,
        probabilities: dict[str, float] | None = None,
        risk_score: float | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        model_version: str = DEFAULT_MODEL_VERSION,
        latency_ms: float | None = None,
    ) -> "SecurityEvent":
        """Build an enriched event from a raw :class:`NetworkEvent`.

        ``risk_score`` defaults to the :func:`compute_risk_score` heuristic.
        """

        return cls(
            network_event_id=event.event_id,
            timestamp=event.timestamp,
            model_name=model_name,
            model_version=model_version,
            predicted_category=predicted_category,
            attack_type=attack_type,
            is_attack=predicted_category is not AttackCategory.NORMAL,
            confidence=confidence,
            risk_score=(
                risk_score
                if risk_score is not None
                else compute_risk_score(predicted_category, confidence)
            ),
            probabilities=probabilities or {},
            source_host=event.source_host,
            destination_host=event.destination_host,
            source_ip=event.source_ip,
            destination_ip=event.destination_ip,
            latency_ms=latency_ms,
        )


# =============================================================================
# 3. Alert - actionable SOC alert
# =============================================================================


class Alert(BaseModel):
    """An SOC-facing alert generated from a security event or an anomaly."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    alert_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    alert_type: str = Field(description="ddos / port_scan / brute_force / ...")
    title: str
    description: str | None = None
    severity: Severity = Severity.MEDIUM
    status: AlertStatus = AlertStatus.OPEN
    risk_score: float | None = Field(default=None, ge=0.0, le=100.0)

    source_host: str | None = None
    destination_host: str | None = None
    source_ip: IPvAnyAddress | None = None
    destination_ip: IPvAnyAddress | None = None

    related_event_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Free-form supporting evidence (features, model output)."
    )

    assigned_to: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    @field_validator("created_at", "acknowledged_at", "resolved_at", mode="after")
    @classmethod
    def _timestamps_to_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @classmethod
    def from_security_event(
        cls,
        event: SecurityEvent,
        *,
        alert_type: str | None = None,
        title: str | None = None,
        description: str | None = None,
        severity: Severity | None = None,
    ) -> "Alert":
        """Derive an alert from a :class:`SecurityEvent`.

        ``alert_type``/``title``/``severity`` default to values derived from
        the predicted category and risk score.
        """

        category = event.predicted_category
        resolved_severity = severity or severity_from_risk_score(event.risk_score)
        resolved_type = alert_type or category.value.lower()
        resolved_title = title or (
            f"{category.value} attack detected on {event.destination_host or 'unknown host'}"
        )
        return cls(
            alert_type=resolved_type,
            title=resolved_title,
            description=description,
            severity=resolved_severity,
            risk_score=event.risk_score,
            source_host=event.source_host,
            destination_host=event.destination_host,
            source_ip=event.source_ip,
            destination_ip=event.destination_ip,
            related_event_ids=[eid for eid in (event.network_event_id,) if eid is not None],
            evidence={
                "model_name": event.model_name,
                "model_version": event.model_version,
                "confidence": event.confidence,
                "attack_type": event.attack_type,
            },
        )


# =============================================================================
# 4. AnomalyEvent - unsupervised detection result
# =============================================================================


class AnomalyEvent(BaseModel):
    """Result of an unsupervised anomaly detector (e.g. Isolation Forest)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    anomaly_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    detected_at: datetime = Field(default_factory=utc_now)
    window_start: datetime | None = None
    window_end: datetime | None = None

    method: str = Field(default="isolation_forest", description="Detector identifier.")
    anomaly_score: float = Field(
        description="Higher = more anomalous. Scale depends on the detector."
    )
    threshold: float | None = None
    is_anomaly: bool = True

    source_host: str | None = None
    source_ip: IPvAnyAddress | None = None
    destination_host: str | None = None

    features: dict[str, float] = Field(
        default_factory=dict, description="Feature window used for the detection."
    )
    description: str | None = None

    @field_validator("detected_at", "window_start", "window_end", mode="after")
    @classmethod
    def _timestamps_to_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_window(self) -> "AnomalyEvent":
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("window_end must be >= window_start")
        return self
