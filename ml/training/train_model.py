"""CyberShield AI - Spark MLlib attack-classifier training pipeline.

Trains and compares four multiclass classifiers on the processed NSL-KDD
splits (``data/processed/train.parquet`` / ``test.parquet``), selects the best
one by weighted F1, persists it together with rich metadata artifacts, and
exports an sklearn mirror model used by the standalone prediction service.

Pipeline overview
-----------------
1. **Load** the processed Parquet splits (Spark reader with pandas fallback).
2. **Feature pipeline** (``pyspark.ml.Pipeline``, fitted on train only):

   * ``StringIndexer``  x3 - ``protocol_type`` / ``service`` / ``flag``
   * ``OneHotEncoder``      - indexed categoricals to sparse vectors
   * ``VectorAssembler``    - 37 numeric features + encoded categoricals
   * ``StandardScaler``     - zero-mean/unit-std normalisation
   * ``StringIndexer``      - ``attack_category`` -> ``label`` index

3. **Train + evaluate** four candidates on the fitted features:

   ====================  =========================================
   Model                 Hyper-parameters (as specified)
   ====================  =========================================
   Random Forest         ``numTrees=100, maxDepth=15``
   Decision Tree         ``maxDepth=15``
   GBT                   ``maxIter=50, maxDepth=10``
   Logistic Regression   ``maxIter=100, family="multinomial"``
   ====================  =========================================

   Every metric (accuracy, weighted precision/recall/F1, per-class stats,
   5x5 confusion matrix, feature importance) is computed from **real**
   predictions on the held-out test split.

4. **Select** the best model by weighted F1 score.
5. **Persist** (all under ``ml/models/``):

   * ``best_model/``            - Spark ``PipelineModel`` (preprocessing + classifier)
   * ``model_metadata.json``    - model card: metrics, classes, features, comparison
   * ``feature_importance.json``- aggregated + per-slot importances
   * ``confusion_matrix.json``  - counts and row-normalised matrix
   * ``sklearn_model.pkl``      - mirror model for the standalone prediction service
   * ``sklearn_model_meta.json``- mirror model card

Usage::

    python ml/training/train_model.py                     # full local run
    python ml/training/train_model.py --quick 30000       # fast smoke run
    spark-submit ml/training/train_model.py               # on a Spark cluster
    python ml/training/train_model.py --master spark://spark-master:7077 \\
        --train-path hdfs://namenode:8020/data/processed/train.parquet
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.classification import (
    DecisionTreeClassifier,
    GBTClassifier,
    LogisticRegression,
    OneVsRest,
    RandomForestClassifier,
)
from pyspark.ml.feature import OneHotEncoder, StandardScaler, StringIndexer, VectorAssembler
from pyspark.sql import DataFrame, SparkSession

from ml.training.spark_utils import (
    ATTACK_CLASSES,
    CATEGORICAL_FEATURES,
    DROPPED_FEATURES,
    DEFAULT_MODELS_DIR,
    DEFAULT_PROCESSED_DIR,
    build_spark_session,
    evaluate_predictions,
    extract_feature_importance,
    normalize_confusion_matrix,
    read_parquet_split,
    save_model,
    subsample,
    to_jsonable,
    utc_now_iso,
    write_json,
)
from streaming.logging_config import configure_logging, get_logger
from streaming.schemas.event_schema import (
    NSL_KDD_CATEGORICAL_FIELDS,
    NSL_KDD_FEATURE_FIELDS,
)
from streaming.settings import load_env

logger = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

MODEL_VERSION = "1.0.0"
DATASET_NAME = "NSL-KDD"
RANDOM_SEED = 42

#: Directory (inside the models dir) holding the persisted best pipeline.
BEST_MODEL_DIRNAME = "best_model"

#: sklearn mirror defaults - matches the Spark Random Forest candidate so the
#: standalone service reproduces the tree-family behaviour out of the JVM.
MIRROR_TREES = 100
MIRROR_MAX_DEPTH = 15


@dataclass
class ModelSpec:
    """Static description of one candidate classifier."""

    display_name: str
    model_type: str
    factory: Callable[[], Any]
    static_params: dict[str, Any] | None = None

    def hyperparameters(self) -> dict[str, Any]:
        """Hyper-parameters recorded in the metadata (best effort).

        A ``static_params`` override is used when present: wrapped estimators
        (e.g. GBT inside ``OneVsRest``) do not expose the inner learner's
        params through ``extractParamMap``.
        """

        if self.static_params is not None:
            return dict(self.static_params)
        try:
            model = self.factory()
            params = model.extractParamMap()
            resolved: dict[str, Any] = {}
            for param, value in params.items():
                name = param.name
                if name in (
                    "numTrees",
                    "maxDepth",
                    "maxIter",
                    "family",
                    "impurity",
                    "regParam",
                    "elasticNetParam",
                    "seed",
                ):
                    resolved[name] = value
            return resolved
        except Exception:  # noqa: BLE001 - metadata only
            return {}


def build_model_specs() -> list[ModelSpec]:
    """Return the four candidate classifiers specified for the project."""

    return [
        ModelSpec(
            display_name="Random Forest Classifier",
            model_type="RandomForestClassifier",
            factory=lambda: RandomForestClassifier(
                labelCol="label",
                featuresCol="features",
                numTrees=100,
                maxDepth=15,
                seed=RANDOM_SEED,
            ),
        ),
        ModelSpec(
            display_name="Decision Tree Classifier",
            model_type="DecisionTreeClassifier",
            factory=lambda: DecisionTreeClassifier(
                labelCol="label",
                featuresCol="features",
                maxDepth=15,
                seed=RANDOM_SEED,
            ),
        ),
        ModelSpec(
            display_name="Gradient Boosted Trees Classifier",
            model_type="GBTClassifier (OneVsRest)",
            # Spark's GBTClassifier is binary-only; OneVsRest reduces the
            # 5-class task to five one-vs-rest GBT experts so it can compete
            # against the natively-multiclass candidates on the same labels.
            factory=lambda: OneVsRest(
                classifier=GBTClassifier(
                    maxIter=50,
                    maxDepth=10,
                    seed=RANDOM_SEED,
                ),
                labelCol="label",
                featuresCol="features",
            ),
            static_params={
                "maxIter": 50,
                "maxDepth": 10,
                "seed": RANDOM_SEED,
                "multiclassStrategy": "OneVsRest",
            },
        ),
        ModelSpec(
            display_name="Logistic Regression (multinomial)",
            model_type="LogisticRegression",
            factory=lambda: LogisticRegression(
                labelCol="label",
                featuresCol="features",
                maxIter=100,
                family="multinomial",
                elasticNetParam=0.0,
            ),
        ),
    ]


@dataclass
class CandidateResult:
    """Everything produced while training/evaluating one candidate."""

    spec: ModelSpec
    classifier: Any
    metrics: dict[str, Any]
    feature_importance: dict[str, float] = field(default_factory=dict)
    feature_importance_detailed: dict[str, float] = field(default_factory=dict)
    training_seconds: float = 0.0

    def comparison_row(self) -> dict[str, Any]:
        return {
            "model_name": self.spec.display_name,
            "model_type": self.spec.model_type,
            "accuracy": self.metrics["accuracy"],
            "precision": self.metrics["precision"],
            "recall": self.metrics["recall"],
            "f1_score": self.metrics["f1_score"],
            "macro_f1": self.metrics.get("macro_f1"),
            "training_seconds": round(self.training_seconds, 2),
            "hyperparameters": self.spec.hyperparameters(),
        }


# =============================================================================
# Data preparation
# =============================================================================


def detect_feature_columns(frame: DataFrame) -> tuple[list[str], list[str]]:
    """Return ``(numeric_features, categorical_features)`` present in ``frame``.

    The zero-variance ``num_outbound_cmds`` column (removed during
    preprocessing) is excluded, as are all non-feature metadata columns.
    """

    available = set(frame.columns)
    numeric = [
        column
        for column in NSL_KDD_FEATURE_FIELDS
        if column in available
        and column not in NSL_KDD_CATEGORICAL_FIELDS
        and column not in DROPPED_FEATURES
    ]
    categorical = [column for column in CATEGORICAL_FEATURES if column in available]

    missing = [
        column
        for column in NSL_KDD_FEATURE_FIELDS
        if column not in available and column not in DROPPED_FEATURES
    ]
    if missing:
        logger.warning("feature_columns_missing", missing=missing[:10], count=len(missing))

    logger.info(
        "feature_columns_detected",
        numeric=len(numeric),
        categorical=len(categorical),
    )
    return numeric, categorical


def clean_split(frame: DataFrame, numeric: Sequence[str], categorical: Sequence[str]) -> DataFrame:
    """Fill nulls and enforce numeric types on the feature columns."""

    cleaned = frame.na.fill(0.0, subset=list(numeric))
    cleaned = cleaned.na.fill("unknown", subset=list(categorical))
    for column in numeric:
        cleaned = cleaned.withColumn(column, cleaned[column].cast("double"))
    return cleaned


def build_preprocessing_pipeline(numeric_features: Sequence[str]) -> Pipeline:
    """Construct the shared feature-engineering pipeline (unfitted)."""

    indexers = [
        StringIndexer(inputCol=column, outputCol=f"{column}_idx", handleInvalid="keep")
        for column in CATEGORICAL_FEATURES
    ]
    ohe_outputs = [f"{column}_ohe" for column in CATEGORICAL_FEATURES]
    encoder = OneHotEncoder(
        inputCols=[f"{column}_idx" for column in CATEGORICAL_FEATURES],
        outputCols=ohe_outputs,
        handleInvalid="keep",
    )
    assembler = VectorAssembler(
        inputCols=[*numeric_features, *ohe_outputs],
        outputCol="features_raw",
        handleInvalid="skip",
    )
    scaler = StandardScaler(
        inputCol="features_raw", outputCol="features", withMean=False, withStd=True
    )
    label_indexer = StringIndexer(inputCol="attack_category", outputCol="label")

    return Pipeline(stages=[*indexers, encoder, assembler, scaler, label_indexer])


# =============================================================================
# Training + evaluation
# =============================================================================


def train_candidate(
    spec: ModelSpec,
    features_train: DataFrame,
    features_test: DataFrame,
    *,
    ohe_model: Any,
    numeric_features: Sequence[str],
) -> CandidateResult:
    """Fit one classifier, evaluate it on test data and collect importances."""

    logger.info("model_training_started", model=spec.display_name, type=spec.model_type)
    started = time.monotonic()

    classifier = spec.factory().fit(features_train)
    training_seconds = time.monotonic() - started

    predictions = classifier.transform(features_test)
    metrics = evaluate_predictions(predictions)
    aggregated, detailed = extract_feature_importance(
        classifier, numeric_features=numeric_features, ohe_models=[ohe_model]
    )

    logger.info(
        "model_training_complete",
        model=spec.display_name,
        accuracy=metrics["accuracy"],
        f1_score=metrics["f1_score"],
        training_seconds=round(training_seconds, 2),
    )
    return CandidateResult(
        spec=spec,
        classifier=classifier,
        metrics=metrics,
        feature_importance=aggregated,
        feature_importance_detailed=detailed,
        training_seconds=training_seconds,
    )


def select_best(results: Sequence[CandidateResult]) -> CandidateResult:
    """Pick the candidate with the highest weighted F1 (accuracy as tiebreak)."""

    return max(
        results,
        key=lambda result: (result.metrics["f1_score"], result.metrics["accuracy"]),
    )


def print_comparison_table(results: Sequence[CandidateResult], best: CandidateResult) -> None:
    """Print a human-readable model-comparison table to stdout."""

    header = f"{'Model':<42}{'Acc':>9}{'Prec':>9}{'Rec':>9}{'F1':>9}{'Secs':>9}"
    print("\n" + "=" * len(header))
    print("CYBERSHIELD AI - MODEL COMPARISON (test split, real metrics)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for result in results:
        marker = " *" if result is best else "  "
        metrics = result.metrics
        print(
            f"{result.spec.display_name:<40}{marker}"
            f"{metrics['accuracy']:>9.4f}{metrics['precision']:>9.4f}"
            f"{metrics['recall']:>9.4f}{metrics['f1_score']:>9.4f}"
            f"{result.training_seconds:>9.1f}"
        )
    print("-" * len(header))
    print(f"Best model: {best.spec.display_name} (weighted F1 = {best.metrics['f1_score']:.4f})")
    print("=" * len(header) + "\n")


# =============================================================================
# Artifact persistence
# =============================================================================


def build_metadata(
    best: CandidateResult,
    all_results: Sequence[CandidateResult],
    *,
    label_index: Sequence[str],
    numeric_features: Sequence[str],
    training_samples: int,
    test_samples: int,
    train_class_distribution: dict[str, int],
    spark_version: str,
    total_seconds: float,
    best_model_saved: bool,
) -> dict[str, Any]:
    """Assemble the full ``model_metadata.json`` payload."""

    features = [*numeric_features, *CATEGORICAL_FEATURES]
    attack_total = sum(
        count for name, count in train_class_distribution.items() if name != "Normal"
    )
    baseline_attack_percentage = (
        round(100.0 * attack_total / training_samples, 4) if training_samples else 0.0
    )

    return {
        "model_name": best.spec.display_name,
        "model_type": best.spec.model_type,
        "artifact_name": "cybershield-attack-classifier",
        "version": MODEL_VERSION,
        "training_date": utc_now_iso(),
        "dataset": DATASET_NAME,
        "training_samples": training_samples,
        "test_samples": test_samples,
        "features": features,
        "num_features": len(features),
        "classes": list(ATTACK_CLASSES),
        "label_index": list(label_index),
        "metrics": {
            "accuracy": best.metrics["accuracy"],
            "precision": best.metrics["precision"],
            "recall": best.metrics["recall"],
            "f1_score": best.metrics["f1_score"],
        },
        "per_class_metrics": best.metrics["per_class_metrics"],
        "confusion_matrix": best.metrics["confusion_matrix"],
        "feature_importance": best.feature_importance,
        "all_models_comparison": [result.comparison_row() for result in all_results],
        "hyperparameters": best.spec.hyperparameters(),
        "spark_evaluator_cross_check": best.metrics.get("spark_evaluator", {}),
        "training_class_distribution": train_class_distribution,
        "baseline_attack_percentage": baseline_attack_percentage,
        "spark_version": spark_version,
        "training_seconds_total": round(total_seconds, 2),
        "best_model_artifact_saved": best_model_saved,
        "notes": [
            "All metrics are computed on the held-out NSL-KDD test split "
            "(KDDTest+); no synthetic or interpolated values.",
            "Preprocessing (encoders/scaler) is fitted on the training split only.",
            "label_index maps the Spark 'prediction' column back to attack categories.",
            "baseline_attack_percentage is the attack share of the training split, "
            "used by the streaming job as the attack-trend baseline.",
        ],
    }


def save_training_artifacts(
    best: CandidateResult,
    all_results: Sequence[CandidateResult],
    *,
    models_dir: Path,
    metadata: dict[str, Any],
    best_model_saved: bool,
) -> dict[str, str]:
    """Write metadata / importance / confusion-matrix JSON artifacts."""

    outputs: dict[str, str] = {}

    metadata_path = write_json(models_dir / "model_metadata.json", metadata)
    outputs["model_metadata"] = str(metadata_path)

    importance_payload = {
        "model_name": best.spec.display_name,
        "model_type": best.spec.model_type,
        "generated_at": utc_now_iso(),
        "num_features_aggregated": len(best.feature_importance),
        "feature_importance": best.feature_importance,
        "feature_importance_detailed": best.feature_importance_detailed,
    }
    importance_path = write_json(models_dir / "feature_importance.json", importance_payload)
    outputs["feature_importance"] = str(importance_path)

    matrix = best.metrics["confusion_matrix"]
    confusion_payload = {
        "model_name": best.spec.display_name,
        "model_type": best.spec.model_type,
        "generated_at": utc_now_iso(),
        "labels": list(ATTACK_CLASSES),
        "matrix": matrix,
        "normalized": normalize_confusion_matrix(matrix),
        "per_class_metrics": best.metrics["per_class_metrics"],
        "test_samples": int(sum(sum(row) for row in matrix)),
    }
    confusion_path = write_json(models_dir / "confusion_matrix.json", confusion_payload)
    outputs["confusion_matrix"] = str(confusion_path)

    if not best_model_saved:
        logger.warning(
            "best_model_not_persisted",
            hint="Spark MLWriter failed (check Hadoop/winutils); the sklearn "
            "mirror and JSON artifacts are still available.",
        )
    return outputs


# =============================================================================
# sklearn mirror model (standalone inference outside the JVM)
# =============================================================================


def train_sklearn_mirror(
    *,
    train_path: Path,
    test_path: Path,
    models_dir: Path,
    numeric_features: Sequence[str],
    quick_rows: int | None,
    n_estimators: int = MIRROR_TREES,
) -> dict[str, Any] | None:
    """Train a Random Forest mirror with scikit-learn on the same features.

    Spark ``PipelineModel`` artifacts can only be executed inside a JVM, so a
    lightweight sklearn twin of the tree-family model is exported for the
    standalone prediction service (FastAPI). It is trained on the same
    processed Parquet splits - still real training, not a mock.

    Returns the mirror metadata dict, or ``None`` when unavailable.
    """

    try:
        import joblib
        import numpy as np
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
    except ImportError as exc:  # pragma: no cover - dependency specific
        logger.warning("sklearn_mirror_skipped", error=str(exc))
        return None

    try:
        train_pdf = pd.read_parquet(train_path)
        test_pdf = pd.read_parquet(test_path)
    except Exception as exc:  # noqa: BLE001 - e.g. HDFS-only layout
        logger.warning("sklearn_mirror_skipped", reason="parquet_unreadable_locally", error=str(exc))
        return None

    if quick_rows is not None and len(train_pdf) > quick_rows:
        train_pdf = train_pdf.sample(n=quick_rows, random_state=RANDOM_SEED)

    # The processed splits already contain *train-fitted* encoded categorical
    # columns (``<feature>_encoded``) - reuse them for perfect consistency.
    encoded_columns = [f"{column}_encoded" for column in CATEGORICAL_FEATURES]
    feature_names = [*numeric_features, *encoded_columns]
    missing = [name for name in feature_names if name not in train_pdf.columns]
    if missing:
        logger.warning("sklearn_mirror_skipped", reason="missing_columns", columns=missing[:5])
        return None

    x_train = train_pdf[feature_names].astype("float64").to_numpy()
    y_train = train_pdf["attack_category"].astype(str).to_numpy()
    x_test = test_pdf[feature_names].astype("float64").to_numpy()
    y_test = test_pdf["attack_category"].astype(str).to_numpy()

    logger.info(
        "sklearn_mirror_training_started",
        rows=int(len(x_train)),
        trees=n_estimators,
        features=len(feature_names),
    )
    started = time.monotonic()
    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=MIRROR_MAX_DEPTH,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    training_seconds = time.monotonic() - started

    predictions = model.predict(x_test)
    labels = list(model.classes_)
    matrix = confusion_matrix(y_test, predictions, labels=labels)
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 6),
        "f1_score": round(
            float(f1_score(y_test, predictions, average="weighted", zero_division=0)), 6
        ),
    }

    artifact_path = models_dir / "sklearn_model.pkl"
    try:
        joblib.dump(
            {
                "model": model,
                "features": feature_names,
                "classes": labels,
                "trained_at": utc_now_iso(),
            },
            artifact_path,
        )
        logger.info("sklearn_mirror_saved", path=str(artifact_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("sklearn_mirror_save_failed", error=str(exc))
        return None

    metadata = {
        "model_type": "RandomForestClassifier",
        "library": "scikit-learn",
        "artifact": str(artifact_path),
        "n_estimators": n_estimators,
        "max_depth": MIRROR_MAX_DEPTH,
        "features": feature_names,
        "encoded_columns": encoded_columns,
        "classes": labels,
        "training_samples": int(len(x_train)),
        "test_samples": int(len(x_test)),
        "metrics": metrics,
        "confusion_matrix": to_jsonable(matrix),
        "training_seconds": round(training_seconds, 2),
        "trained_at": utc_now_iso(),
        "notes": [
            "Mirror of the Spark tree model for standalone (non-JVM) inference.",
            "Trained on the same processed splits with train-fitted encodings.",
        ],
    }
    write_json(models_dir / "sklearn_model_meta.json", metadata)
    logger.info("sklearn_mirror_ready", **metrics)
    return metadata


# =============================================================================
# Orchestration
# =============================================================================


def train_models(
    *,
    train_path: Path,
    test_path: Path,
    models_dir: Path,
    master: str | None = None,
    quick_rows: int | None = None,
    train_sklearn: bool = True,
    hdfs_model_uri: str | None = None,
) -> dict[str, Any]:
    """End-to-end training run. Returns the metadata payload."""

    total_started = time.monotonic()
    spark = build_spark_session(
        "CyberShield-AI-Training",
        master=master,
        enable_hdfs=hdfs_model_uri is not None,
    )

    # -- load ------------------------------------------------------------------
    train_df = read_parquet_split(spark, train_path)
    test_df = read_parquet_split(spark, test_path)
    train_df = subsample(train_df, quick_rows)
    train_df.cache()
    test_df.cache()
    training_samples = train_df.count()
    test_samples = test_df.count()
    logger.info("splits_loaded", train=training_samples, test=test_samples)

    numeric_features, categorical_features = detect_feature_columns(train_df)
    train_df = clean_split(train_df, numeric_features, categorical_features)
    test_df = clean_split(test_df, numeric_features, categorical_features)

    # -- fit shared preprocessing on the training split --------------------------
    prep_pipeline = build_preprocessing_pipeline(numeric_features)
    prep_model = prep_pipeline.fit(train_df)
    features_train = prep_model.transform(train_df).cache()
    features_test = prep_model.transform(test_df).cache()

    label_indexer = prep_model.stages[-1]
    label_index = list(label_indexer.labels)
    ohe_model = prep_model.stages[len(CATEGORICAL_FEATURES)]  # 3 indexers precede it
    logger.info("preprocessing_fitted", label_index=label_index)

    # -- train + evaluate every candidate ----------------------------------------
    results = [
        train_candidate(
            spec,
            features_train,
            features_test,
            ohe_model=ohe_model,
            numeric_features=numeric_features,
        )
        for spec in build_model_specs()
    ]

    best = select_best(results)
    print_comparison_table(results, best)

    # -- persist the best pipeline (preprocessing + classifier) -------------------
    best_pipeline = PipelineModel(stages=[*prep_model.stages, best.classifier])
    best_model_path = models_dir / BEST_MODEL_DIRNAME
    best_model_saved = save_model(best_pipeline, best_model_path)

    if hdfs_model_uri:
        save_model(best_pipeline, hdfs_model_uri)

    # -- metadata + auxiliary artifacts -------------------------------------------
    train_class_distribution = {
        str(row["attack_category"]): int(row["count"])
        for row in train_df.groupBy("attack_category").count().collect()
    }
    metadata = build_metadata(
        best,
        results,
        label_index=label_index,
        numeric_features=numeric_features,
        training_samples=training_samples,
        test_samples=test_samples,
        train_class_distribution=train_class_distribution,
        spark_version=spark.version,
        total_seconds=time.monotonic() - total_started,
        best_model_saved=best_model_saved,
    )
    outputs = save_training_artifacts(
        best, results, models_dir=models_dir, metadata=metadata, best_model_saved=best_model_saved
    )

    # -- sklearn mirror for standalone inference -------------------------------------
    if train_sklearn:
        mirror_trees = MIRROR_TREES if quick_rows is None else 40
        mirror_meta = train_sklearn_mirror(
            train_path=train_path,
            test_path=test_path,
            models_dir=models_dir,
            numeric_features=numeric_features,
            quick_rows=quick_rows,
            n_estimators=mirror_trees,
        )
        if mirror_meta is not None:
            outputs["sklearn_model"] = mirror_meta["artifact"]

    metadata["outputs"] = outputs
    write_json(models_dir / "model_metadata.json", metadata)

    features_train.unpersist()
    features_test.unpersist()
    train_df.unpersist()
    test_df.unpersist()

    logger.info(
        "training_pipeline_complete",
        best_model=best.spec.display_name,
        f1_score=best.metrics["f1_score"],
        outputs=outputs,
        total_seconds=round(time.monotonic() - total_started, 2),
    )
    return metadata


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train_model",
        description="Train and compare Spark MLlib attack classifiers on NSL-KDD.",
    )
    parser.add_argument("--train-path", default=None, help="Train Parquet (local or HDFS URI).")
    parser.add_argument("--test-path", default=None, help="Test Parquet (local or HDFS URI).")
    parser.add_argument(
        "--processed-dir", default=None, help="Directory with train/test Parquet files."
    )
    parser.add_argument(
        "--models-dir", default=None, help="Artifact output directory (default: ml/models)."
    )
    parser.add_argument("--master", default=None, help="Spark master URL (default: local[*]).")
    parser.add_argument(
        "--quick", type=int, default=None, help="Subsample N training rows for a fast run."
    )
    parser.add_argument(
        "--no-sklearn-mirror",
        action="store_true",
        help="Skip the sklearn mirror model for standalone inference.",
    )
    parser.add_argument(
        "--hdfs-model-uri",
        default=None,
        help="Additionally save the best PipelineModel to this HDFS path "
        "(e.g. hdfs://namenode:8020/models/best_model).",
    )
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR.")
    parser.add_argument("--json-logs", action="store_true", help="Force JSON log output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    processed_dir = Path(args.processed_dir) if args.processed_dir else DEFAULT_PROCESSED_DIR
    train_path = Path(args.train_path) if args.train_path else processed_dir / "train.parquet"
    test_path = Path(args.test_path) if args.test_path else processed_dir / "test.parquet"
    models_dir = Path(args.models_dir) if args.models_dir else DEFAULT_MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)

    for path in (train_path, test_path):
        exists_locally = path.exists()
        is_remote = str(path).startswith("hdfs://")
        if not exists_locally and not is_remote:
            logger.error("input_split_missing", path=str(path))
            print(
                f"ERROR: processed split not found: {path}\n"
                "Run `python -m ml.preprocessing.preprocess` first."
            )
            return 1

    try:
        metadata = train_models(
            train_path=train_path,
            test_path=test_path,
            models_dir=models_dir,
            master=args.master,
            quick_rows=args.quick,
            train_sklearn=not args.no_sklearn_mirror,
            hdfs_model_uri=args.hdfs_model_uri,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.warning("training_interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.exception("training_failed", error=str(exc))
        return 2

    print(
        f"Done. Best model: {metadata['model_name']} "
        f"(accuracy={metadata['metrics']['accuracy']:.4f}, "
        f"f1={metadata['metrics']['f1_score']:.4f}) -> {models_dir}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
