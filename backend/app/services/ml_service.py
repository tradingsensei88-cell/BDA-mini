"""ML Intelligence Service.

Serves model metadata, evaluation metrics, feature importance, confusion
matrix and live prediction statistics to the dashboard.

Artifacts (produced by the ``ml/`` training pipeline) are loaded from
``ml/models/`` when present:

* ``model_metadata.json`` - name, version, algorithm, training info.
* ``feature_importance.json`` - ranked feature importances.
* ``confusion_matrix.json`` - 5x5 confusion matrix.

When artifacts are missing the service falls back to built-in, realistic
NSL-KDD sample data so every ``/api/ml/*`` endpoint works standalone. Per-class
metrics are always *derived from the confusion matrix*, keeping the numbers
internally consistent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import structlog

from app.core.config import settings
from app.services.event_service import EventProcessingService, get_event_service

logger = structlog.get_logger("cybershield.backend.ml")

#: Class order used across the platform.
CLASS_LABELS: tuple[str, ...] = ("Normal", "DoS", "Probe", "R2L", "U2R")

#: The 41 canonical NSL-KDD features (matches streaming/schemas/event_schema.py).
FEATURE_NAMES: tuple[str, ...] = (
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes",
    "land", "wrong_fragment", "urgent", "hot", "num_failed_logins", "logged_in",
    "num_compromised", "root_shell", "su_attempted", "num_root",
    "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count", "serror_rate",
    "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate",
    "diff_srv_rate", "srv_diff_host_rate", "dst_host_count",
    "dst_host_srv_count", "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
)

_BASIC_FEATURES = frozenset(FEATURE_NAMES[:9])
_CONTENT_FEATURES = frozenset(FEATURE_NAMES[9:22])
_TRAFFIC_FEATURES = frozenset(FEATURE_NAMES[22:31])

#: Fallback confusion matrix (rows = truth, columns = predicted).
_DEFAULT_CONFUSION_MATRIX: list[list[int]] = [
    [9600, 20, 95, 15, 1],
    [45, 7180, 40, 2, 0],
    [110, 35, 2310, 10, 0],
    [180, 3, 30, 800, 2],
    [10, 0, 2, 8, 38],
]

#: Fallback feature importances (normalized on the fly).
_DEFAULT_FEATURE_IMPORTANCE: dict[str, float] = {
    "src_bytes": 0.082, "dst_bytes": 0.071, "count": 0.066,
    "dst_host_srv_count": 0.058, "serror_rate": 0.055, "same_srv_rate": 0.052,
    "dst_host_same_srv_rate": 0.047, "logged_in": 0.044, "flag": 0.042,
    "dst_host_count": 0.040, "service": 0.038, "duration": 0.036,
    "rerror_rate": 0.034, "diff_srv_rate": 0.031, "hot": 0.029,
    "dst_host_serror_rate": 0.027, "srv_serror_rate": 0.026,
    "dst_host_srv_serror_rate": 0.024, "dst_host_rerror_rate": 0.022,
    "dst_host_srv_rerror_rate": 0.021, "protocol_type": 0.019,
    "num_failed_logins": 0.018, "srv_count": 0.016, "num_compromised": 0.015,
    "root_shell": 0.014, "dst_host_diff_srv_rate": 0.013,
    "dst_host_same_src_port_rate": 0.012, "srv_rerror_rate": 0.011,
    "wrong_fragment": 0.010, "num_root": 0.009, "num_file_creations": 0.008,
    "dst_host_srv_diff_host_rate": 0.007, "srv_diff_host_rate": 0.006,
    "num_shells": 0.005, "urgent": 0.004, "land": 0.003,
    "num_access_files": 0.003, "su_attempted": 0.002, "is_guest_login": 0.002,
    "num_outbound_cmds": 0.001, "is_host_login": 0.001,
}

_DEFAULT_MODEL_METADATA: dict[str, Any] = {
    "name": "cybershield-attack-classifier",
    "version": "1.0.0",
    "algorithm": "random_forest",
    "stage": "production",
    "is_active": True,
    "training_dataset": "NSL-KDD",
    "trained_at": "2026-09-28T11:20:00+00:00",
    "artifact_path": "ml/models/cybershield-attack-classifier.joblib",
    "classes": list(CLASS_LABELS),
    "n_features": len(FEATURE_NAMES),
    "feature_names": list(FEATURE_NAMES),
    "hyperparameters": {"n_estimators": 300, "max_depth": 24, "random_state": 42},
    "auc_roc": 0.9912,
    "false_positive_rate": 0.0231,
    "evaluated_at": "2026-09-28T11:35:00+00:00",
}


def _feature_family(name: str) -> str:
    if name in _BASIC_FEATURES:
        return "basic"
    if name in _CONTENT_FEATURES:
        return "content"
    if name in _TRAFFIC_FEATURES:
        return "traffic"
    return "host"


class MLService:
    """Reads model artifacts with caching + a robust built-in fallback."""

    def __init__(self, events: EventProcessingService | None = None) -> None:
        self.events = events or get_event_service()
        self._cache: dict[str, tuple[float | None, Any]] = {}

    # ------------------------------------------------------------ artifacts

    def _load_artifact(self, filename: str) -> tuple[Any | None, str | None]:
        """Load + cache a JSON artifact; auto-reloads when the mtime changes."""

        path: Path = settings.ml_models_path / filename
        try:
            mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            mtime = None

        cached = self._cache.get(filename)
        if cached is not None and cached[0] == mtime:
            return cached[1], (str(path) if mtime is not None else None)

        data: Any | None = None
        if mtime is not None:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                logger.info("ml.artifact_loaded", file=str(path))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("ml.artifact_invalid", file=str(path), error=str(exc))
                data = None
        self._cache[filename] = (mtime, data)
        return data, (str(path) if data is not None else None)

    def reload(self) -> None:
        """Drop cached artifacts (they are re-read on next access)."""

        self._cache.clear()

    # ------------------------------------------------------------ model info

    def get_model_info(self) -> dict[str, Any]:
        """Identity + provenance of the deployed classifier."""

        artifact, source = self._load_artifact("model_metadata.json")
        merged = dict(_DEFAULT_MODEL_METADATA)
        if isinstance(artifact, Mapping):
            merged = _merge_metadata(merged, artifact)

        trained_at = _coerce_datetime(merged.get("trained_at") or merged.get("training_date"))
        return {
            "name": str(merged.get("name") or merged.get("model_name") or _DEFAULT_MODEL_METADATA["name"]),
            "version": str(merged.get("version") or _DEFAULT_MODEL_METADATA["version"]),
            "algorithm": str(merged.get("algorithm") or _DEFAULT_MODEL_METADATA["algorithm"]),
            "stage": str(merged.get("stage") or "production"),
            "is_active": bool(merged.get("is_active", True)),
            "training_dataset": str(merged.get("training_dataset") or "NSL-KDD"),
            "trained_at": trained_at.isoformat() if trained_at else None,
            "artifact_path": str(merged.get("artifact_path") or "") or None,
            "classes": [str(c) for c in merged.get("classes") or CLASS_LABELS],
            "n_features": int(merged.get("n_features") or len(FEATURE_NAMES)),
            "feature_names": [str(f) for f in merged.get("feature_names") or FEATURE_NAMES],
            "hyperparameters": dict(merged.get("hyperparameters") or {}),
            "metadata_source": source or "builtin-default",
        }

    # --------------------------------------------------------------- metrics

    def get_metrics(self) -> dict[str, Any]:
        """Global + per-class metrics, derived from the confusion matrix."""

        matrix, labels, source = self._confusion_data()
        per_class = _per_class_metrics(matrix, labels)
        total = sum(sum(row) for row in matrix) or 1
        correct = sum(matrix[i][i] for i in range(min(len(matrix), len(labels))))
        accuracy = correct / total

        macro_f1 = sum(row["f1"] for row in per_class) / len(per_class) if per_class else 0.0
        weighted_precision = (
            sum(row["precision"] * row["support"] for row in per_class) / total
            if per_class
            else 0.0
        )
        weighted_recall = (
            sum(row["recall"] * row["support"] for row in per_class) / total
            if per_class
            else 0.0
        )
        weighted_f1 = (
            sum(row["f1"] * row["support"] for row in per_class) / total if per_class else 0.0
        )

        artifact, _ = self._load_artifact("model_metadata.json")
        extra = artifact if isinstance(artifact, Mapping) else {}
        evaluated_at = _coerce_datetime(
            extra.get("evaluated_at") or extra.get("evaluation_date")
        ) or _coerce_datetime(_DEFAULT_MODEL_METADATA["evaluated_at"])

        return {
            "accuracy": round(accuracy, 4),
            "precision": round(weighted_precision, 4),
            "recall": round(weighted_recall, 4),
            "f1": round(weighted_f1, 4),
            "macro_f1": round(macro_f1, 4),
            "auc_roc": float(extra.get("auc_roc", _DEFAULT_MODEL_METADATA["auc_roc"])),
            "false_positive_rate": float(
                extra.get("false_positive_rate", _DEFAULT_MODEL_METADATA["false_positive_rate"])
            ),
            "evaluated_at": evaluated_at.isoformat() if evaluated_at else None,
            "test_samples": total,
            "per_class": per_class,
            "metadata_source": source or "builtin-default",
        }

    # ---------------------------------------------------- feature importance

    def get_feature_importance(self, *, limit: int | None = None) -> dict[str, Any]:
        """Ranked feature importances (normalized to sum to 1)."""

        artifact, source = self._load_artifact("feature_importance.json")
        mapping = _coerce_feature_importance(artifact) or dict(_DEFAULT_FEATURE_IMPORTANCE)

        total = sum(max(0.0, float(v)) for v in mapping.values()) or 1.0
        ordered = sorted(mapping.items(), key=lambda kv: float(kv[1]), reverse=True)
        if limit is not None:
            ordered = ordered[: max(1, limit)]

        items = [
            {
                "rank": index + 1,
                "feature": str(name),
                "importance": round(max(0.0, float(value)) / total, 4),
                "category": _feature_family(str(name)),
            }
            for index, (name, value) in enumerate(ordered)
        ]
        return {
            "model_name": self.get_model_info()["name"],
            "total_features": len(items),
            "items": items,
            "metadata_source": source or "builtin-default",
        }

    # ------------------------------------------------------ confusion matrix

    def get_confusion_matrix(self) -> dict[str, Any]:
        """5x5 confusion matrix (raw + row-normalized)."""

        matrix, labels, source = self._confusion_data()
        normalized: list[list[float]] = []
        for row in matrix:
            row_total = sum(row) or 1
            normalized.append([round(value / row_total, 4) for value in row])
        return {
            "labels": labels,
            "matrix": matrix,
            "normalized": normalized,
            "total": sum(sum(row) for row in matrix),
            "metadata_source": source or "builtin-default",
        }

    def _confusion_data(self) -> tuple[list[list[int]], list[str], str | None]:
        artifact, source = self._load_artifact("confusion_matrix.json")
        parsed = _coerce_confusion_matrix(artifact)
        if parsed is None:
            return [list(row) for row in _DEFAULT_CONFUSION_MATRIX], list(CLASS_LABELS), None
        matrix, labels = parsed
        return matrix, labels, source

    # ---------------------------------------------------------- predictions

    def get_predictions(self, *, limit: int = 50) -> dict[str, Any]:
        """Recent predictions + confidence distribution from the live buffer."""

        recent, _ = self.events.get_recent_events(limit=max(1, limit))
        all_recent = self.events.get_events_since(self.events.started_at)

        items = [
            {
                "event_id": str(record.get("id")),
                "predicted_at": record.get("timestamp"),
                "predicted_category": str(record.get("predicted_category") or "Normal"),
                "attack_type": record.get("attack_type"),
                "is_attack": bool(record.get("is_attack")),
                "confidence": float(record.get("confidence") or 0.0),
                "risk_score": float(record.get("risk_score") or 0.0),
                "source_ip": record.get("source_ip"),
                "latency_ms": float(record.get("latency_ms") or 0.0),
            }
            for record in recent
        ]

        total = len(all_recent)
        attacks = sum(1 for r in all_recent if r.get("is_attack"))
        confidence_sum = sum(float(r.get("confidence") or 0.0) for r in all_recent)
        latency_sum = sum(float(r.get("latency_ms") or 0.0) for r in all_recent)
        class_distribution: dict[str, int] = {label: 0 for label in CLASS_LABELS}
        for record in all_recent:
            label = str(record.get("predicted_category") or "Normal")
            class_distribution[label] = class_distribution.get(label, 0) + 1

        stats = {
            "total": total,
            "attacks": attacks,
            "attack_rate": round(attacks / total * 100.0, 2) if total else 0.0,
            "avg_confidence": round(confidence_sum / total, 4) if total else 0.0,
            "avg_latency_ms": round(latency_sum / total, 2) if total else 0.0,
            "class_distribution": class_distribution,
        }

        return {
            "items": items,
            "stats": stats,
            "confidence_distribution": _confidence_histogram(all_recent),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_metadata(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Case-tolerant merge of artifact metadata over the defaults."""

    merged = dict(base)
    aliases = {
        "model_name": "name",
        "model": "name",
        "training_date": "trained_at",
        "features": "feature_names",
        "feature_columns": "feature_names",
    }
    for key, value in override.items():
        if value is None:
            continue
        canonical = aliases.get(key, key)
        merged[canonical] = value
    return merged


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _coerce_feature_importance(artifact: Any) -> dict[str, float] | None:
    """Accept the common feature-importance shapes."""

    if artifact is None:
        return None
    payload = artifact
    if isinstance(artifact, Mapping):
        for key in ("items", "features", "feature_importance", "importances"):
            if key in artifact:
                payload = artifact[key]
                break

    result: dict[str, float] = {}
    if isinstance(payload, Mapping):
        for name, value in payload.items():
            try:
                result[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, Mapping):
                name = entry.get("feature") or entry.get("name")
                value = entry.get("importance", entry.get("value"))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                name, value = entry[0], entry[1]
            else:
                continue
            try:
                result[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
    return result or None


def _coerce_confusion_matrix(artifact: Any) -> tuple[list[list[int]], list[str]] | None:
    """Accept ``{labels, matrix}``, ``{labels, confusion_matrix}`` or a raw 2-D list."""

    matrix: Any = None
    labels: list[str] | None = None
    if isinstance(artifact, Mapping):
        for key in ("matrix", "confusion_matrix", "values"):
            if key in artifact:
                matrix = artifact[key]
                break
        raw_labels = artifact.get("labels") or artifact.get("classes")
        if isinstance(raw_labels, list):
            labels = [str(label) for label in raw_labels]
    elif isinstance(artifact, list):
        matrix = artifact

    if not isinstance(matrix, list) or not matrix:
        return None
    try:
        parsed = [[int(cell) for cell in row] for row in matrix]
    except (TypeError, ValueError):
        return None
    size = len(parsed)
    if any(len(row) != size for row in parsed):
        return None
    if labels is None or len(labels) != size:
        labels = list(CLASS_LABELS[:size]) if size <= 5 else [f"class_{i}" for i in range(size)]
    return parsed, labels


def _per_class_metrics(matrix: list[list[int]], labels: list[str]) -> list[dict[str, Any]]:
    """Precision/recall/F1/support derived from the confusion matrix."""

    size = len(labels)
    col_totals = [sum(matrix[row][col] for row in range(size)) for col in range(size)]
    row_totals = [sum(row) for row in matrix]

    rows: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        true_positive = matrix[index][index]
        precision = true_positive / col_totals[index] if col_totals[index] else 0.0
        recall = true_positive / row_totals[index] if row_totals[index] else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rows.append(
            {
                "label": label,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "support": row_totals[index],
            }
        )
    return rows


def _confidence_histogram(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Confidence buckets split per predicted class."""

    bucket_defs = [
        ("0.0-0.5", 0.0, 0.5),
        ("0.5-0.6", 0.5, 0.6),
        ("0.6-0.7", 0.6, 0.7),
        ("0.7-0.8", 0.7, 0.8),
        ("0.8-0.9", 0.8, 0.9),
        ("0.9-1.0", 0.9, 1.0000001),
    ]
    buckets: list[dict[str, Any]] = []
    for label, lower, upper in bucket_defs:
        buckets.append(
            {
                "bucket": label,
                "lower": lower,
                "normal": 0,
                "dos": 0,
                "probe": 0,
                "r2l": 0,
                "u2r": 0,
                "total": 0,
            }
        )

    key_map = {"Normal": "normal", "DoS": "dos", "Probe": "probe", "R2L": "r2l", "U2R": "u2r"}
    for record in records:
        confidence = float(record.get("confidence") or 0.0)
        for bucket, lower, upper in zip(buckets, [d[1] for d in bucket_defs], [d[2] for d in bucket_defs]):
            if lower <= confidence < upper:
                field = key_map.get(str(record.get("predicted_category") or "Normal"))
                if field:
                    bucket[field] += 1
                bucket["total"] += 1
                break
    return buckets


#: Shared service instance.
ml_service = MLService()


def get_ml_service() -> MLService:
    """FastAPI-friendly accessor for the shared service."""

    return ml_service
