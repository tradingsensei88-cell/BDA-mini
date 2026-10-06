"""Schemas for the ML intelligence endpoints (``/api/ml/*``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelInfo(BaseModel):
    """Identity and provenance of the deployed attack-classifier."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "cybershield-attack-classifier",
                "version": "1.0.0",
                "algorithm": "random_forest",
                "stage": "production",
                "is_active": True,
                "training_dataset": "NSL-KDD",
                "trained_at": "2026-09-28T11:20:00Z",
                "artifact_path": "ml/models/cybershield-attack-classifier.joblib",
                "classes": ["Normal", "DoS", "Probe", "R2L", "U2R"],
                "n_features": 41,
                "feature_names": ["duration", "protocol_type", "service"],
                "metadata_source": "ml/models/model_metadata.json",
            }
        }
    )

    name: str = Field(description="Model name.")
    version: str = Field(description="Model version.")
    algorithm: str = Field(description="Algorithm family, e.g. random_forest.")
    stage: str = Field(default="production", description="Registry stage.")
    is_active: bool = Field(default=True, description="Whether the model is serving traffic.")
    training_dataset: str = Field(description="Training dataset identifier.")
    trained_at: datetime | None = Field(default=None, description="Training completion time (UTC).")
    artifact_path: str | None = Field(default=None, description="Path to the serialized artifact.")
    classes: list[str] = Field(default_factory=list, description="Output classes in order.")
    n_features: int = Field(default=41, ge=0, description="Number of input features.")
    feature_names: list[str] = Field(
        default_factory=list, description="Ordered input feature names."
    )
    hyperparameters: dict[str, object] = Field(
        default_factory=dict, description="Hyperparameters used for training."
    )
    metadata_source: str = Field(
        default="builtin-default",
        description="Where the metadata was loaded from (file path or builtin-default).",
    )


class ClassMetric(BaseModel):
    """Per-class precision/recall/F1/support."""

    label: str = Field(description="Class label.", examples=["DoS"])
    precision: float = Field(ge=0, le=1, description="Precision, 0-1.")
    recall: float = Field(ge=0, le=1, description="Recall, 0-1.")
    f1: float = Field(ge=0, le=1, description="F1 score, 0-1.")
    support: int = Field(ge=0, description="Ground-truth sample count.")


class ModelMetrics(BaseModel):
    """Global + per-class evaluation metrics."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "accuracy": 0.9736,
                "precision": 0.9681,
                "recall": 0.9532,
                "f1": 0.9602,
                "macro_f1": 0.9245,
                "auc_roc": 0.9912,
                "false_positive_rate": 0.0231,
                "evaluated_at": "2026-09-28T11:35:00Z",
                "test_samples": 22544,
                "per_class": [
                    {"label": "DoS", "precision": 0.988, "recall": 0.984, "f1": 0.986, "support": 7460}
                ],
            }
        }
    )

    accuracy: float = Field(ge=0, le=1, description="Overall accuracy, 0-1.")
    precision: float = Field(ge=0, le=1, description="Weighted precision, 0-1.")
    recall: float = Field(ge=0, le=1, description="Weighted recall, 0-1.")
    f1: float = Field(ge=0, le=1, description="Weighted F1, 0-1.")
    macro_f1: float = Field(ge=0, le=1, description="Unweighted mean F1 across classes.")
    auc_roc: float | None = Field(default=None, ge=0, le=1, description="One-vs-rest AUC.")
    false_positive_rate: float | None = Field(
        default=None, ge=0, le=1, description="False positive rate on benign traffic."
    )
    evaluated_at: datetime | None = Field(default=None, description="Evaluation time (UTC).")
    test_samples: int = Field(default=0, ge=0, description="Samples in the test split.")
    per_class: list[ClassMetric] = Field(
        default_factory=list, description="Per-class classification report."
    )
    metadata_source: str = Field(default="builtin-default", description="Data provenance.")


class FeatureImportanceItem(BaseModel):
    """One row of the feature-importance ranking."""

    rank: int = Field(ge=1, description="1-based importance rank.")
    feature: str = Field(description="NSL-KDD feature name.", examples=["src_bytes"])
    importance: float = Field(ge=0, description="Importance weight, 0-1.")
    category: str = Field(
        default="", description="Feature family: basic, content, traffic, host."
    )


class FeatureImportanceResponse(BaseModel):
    """Ranked feature importances from the trained model."""

    model_name: str = Field(description="Model the importances belong to.")
    total_features: int = Field(ge=0, description="Number of features returned.")
    items: list[FeatureImportanceItem] = Field(
        default_factory=list, description="Descending importance ranking."
    )
    metadata_source: str = Field(default="builtin-default", description="Data provenance.")


class ConfusionMatrixResponse(BaseModel):
    """5x5 confusion matrix over Normal/DoS/Probe/R2L/U2R."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "labels": ["Normal", "DoS", "Probe", "R2L", "U2R"],
                "matrix": [[9711, 35, 118, 22, 1], [56, 7213, 60, 3, 0]],
                "normalized": [[0.9836, 0.0035, 0.012, 0.0022, 0.0001]],
                "total": 22544,
                "metadata_source": "ml/models/confusion_matrix.json",
            }
        }
    )

    labels: list[str] = Field(default_factory=list, description="Class order for rows/columns.")
    matrix: list[list[int]] = Field(
        default_factory=list, description="Counts; matrix[true][predicted]."
    )
    normalized: list[list[float]] = Field(
        default_factory=list, description="Row-normalized matrix (0-1)."
    )
    total: int = Field(default=0, ge=0, description="Total evaluated samples.")
    metadata_source: str = Field(default="builtin-default", description="Data provenance.")


class PredictionItem(BaseModel):
    """A single recent model prediction."""

    event_id: str = Field(description="Related event id.")
    predicted_at: datetime = Field(description="Inference time (UTC).")
    predicted_category: str = Field(description="Predicted class.")
    attack_type: str | None = Field(default=None, description="Fine-grained label when known.")
    is_attack: bool = Field(description="Whether the flow was flagged as an attack.")
    confidence: float = Field(ge=0, le=1, description="Confidence, 0-1.")
    risk_score: float = Field(ge=0, le=100, description="Composite risk 0-100.")
    source_ip: str | None = Field(default=None, description="Source IP.")
    latency_ms: float | None = Field(default=None, ge=0, description="Inference latency (ms).")


class ConfidenceBucket(BaseModel):
    """One bucket of the confidence histogram, split per class."""

    bucket: str = Field(description="Bucket label, e.g. 0.9-1.0.")
    lower: float = Field(ge=0, le=1, description="Bucket lower bound.")
    normal: int = Field(default=0, ge=0)
    dos: int = Field(default=0, ge=0)
    probe: int = Field(default=0, ge=0)
    r2l: int = Field(default=0, ge=0)
    u2r: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0, description="All predictions in the bucket.")


class PredictionStats(BaseModel):
    """Aggregate statistics over recent predictions."""

    total: int = Field(ge=0, description="Predictions sampled.")
    attacks: int = Field(ge=0, description="Predictions flagged as attacks.")
    attack_rate: float = Field(ge=0, le=100, description="Attack share, 0-100.")
    avg_confidence: float = Field(ge=0, le=1, description="Mean confidence.")
    avg_latency_ms: float = Field(ge=0, description="Mean inference latency (ms).")
    class_distribution: dict[str, int] = Field(
        default_factory=dict, description="Counts per predicted class."
    )


class PredictionsResponse(BaseModel):
    """Recent predictions with the confidence distribution."""

    items: list[PredictionItem] = Field(default_factory=list, description="Most recent first.")
    stats: PredictionStats = Field(description="Aggregate statistics.")
    confidence_distribution: list[ConfidenceBucket] = Field(
        default_factory=list, description="Confidence histogram per class."
    )
    generated_at: datetime = Field(description="Computation time (UTC).")


#: Alias kept for spec compatibility - a single prediction result row.
PredictionResult = PredictionItem
