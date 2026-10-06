"""Event schemas shared across producers, consumers, and Spark jobs.

Re-exports the canonical Kafka message models and constants so downstream
code can simply do::

    from streaming.schemas import NetworkEvent, AttackCategory, TOPIC_NETWORK_EVENTS
"""

from __future__ import annotations

from streaming.schemas.event_schema import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    DLQ_TOPIC_SUFFIX,
    NSL_KDD_BINARY_FIELDS,
    NSL_KDD_CATEGORICAL_FIELDS,
    NSL_KDD_COLUMNS,
    NSL_KDD_FEATURE_FIELDS,
    NSL_KDD_LABEL_FIELDS,
    TOPIC_ALERTS,
    TOPIC_ANOMALIES,
    TOPIC_NETWORK_EVENTS,
    TOPIC_PREDICTIONS,
    TOPIC_SECURITY_EVENTS,
    Alert,
    AlertStatus,
    AnomalyEvent,
    AttackCategory,
    NetworkEvent,
    SecurityEvent,
    Severity,
    compute_risk_score,
    dlq_topic_name,
    ensure_utc,
    severity_from_risk_score,
    utc_now,
)

__all__ = [
    # Models
    "NetworkEvent",
    "SecurityEvent",
    "Alert",
    "AnomalyEvent",
    # Enums
    "AttackCategory",
    "Severity",
    "AlertStatus",
    # Topics
    "TOPIC_NETWORK_EVENTS",
    "TOPIC_SECURITY_EVENTS",
    "TOPIC_PREDICTIONS",
    "TOPIC_ALERTS",
    "TOPIC_ANOMALIES",
    "DLQ_TOPIC_SUFFIX",
    "dlq_topic_name",
    # NSL-KDD column definitions
    "NSL_KDD_FEATURE_FIELDS",
    "NSL_KDD_LABEL_FIELDS",
    "NSL_KDD_COLUMNS",
    "NSL_KDD_CATEGORICAL_FIELDS",
    "NSL_KDD_BINARY_FIELDS",
    # Helpers
    "compute_risk_score",
    "severity_from_risk_score",
    "ensure_utc",
    "utc_now",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_MODEL_VERSION",
]
