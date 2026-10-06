"""CyberShield AI - held-out evaluation of the trained attack classifier.

Loads the persisted ``ml/models/best_model`` ``PipelineModel``, re-scores the
held-out NSL-KDD test split and writes a rich ``evaluation_report.json``
artifact next to the training metadata. This closes the loop of the ML
training pipeline: training selects the model, this job independently
re-verifies it on data the pipeline never saw while fitting.

Checks performed
----------------
* **Metric reproduction** - accuracy / weighted precision / recall / F1 /
  macro-F1, per-class stats and the 5x5 confusion matrix computed from the
  live predictions (``spark_utils.evaluate_predictions``).
* **Training-vs-evaluation drift** - the freshly computed numbers are
  compared against ``model_metadata.json`` (the training run evaluated the
  same split, so results must match bit-for-bit unless the artifacts were
  produced from different data).
* **Baseline comparison** - majority-class and random baselines contextualise
  the weighted F1 for the report.

Usage::

    python -m ml.evaluation.evaluate                       # local artifacts
    python -m ml.evaluation.evaluate --quick 20000         # subsample test
    python -m ml.evaluation.evaluate \\
        --model-path hdfs://namenode:8020/models/best_model \\
        --test-path hdfs://namenode:8020/data/processed/test.parquet
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.ml import PipelineModel
from pyspark.sql import DataFrame, SparkSession

from ml.training.spark_utils import (
    ATTACK_CLASSES,
    DEFAULT_MODELS_DIR,
    DEFAULT_PROCESSED_DIR,
    build_spark_session,
    evaluate_predictions,
    matrix_summary,
    normalize_confusion_matrix,
    per_class_metrics,
    read_json,
    to_jsonable,
    utc_now_iso,
    write_json,
)
from streaming.logging_config import configure_logging, get_logger
from streaming.settings import load_env

logger = get_logger(__name__)

#: Tolerance for the training-vs-evaluation metric drift check.
DRIFT_TOLERANCE = 0.01


# =============================================================================
# Evaluation core
# =============================================================================


def load_test_frame(
    spark: SparkSession, test_path: Path, quick_rows: int | None
) -> tuple[DataFrame, int]:
    """Read (and optionally subsample) the held-out test split.

    Returns ``(frame, full_row_count)`` so the report can state whether the
    evaluation ran on the complete split or a quick subsample.
    """

    from ml.training.spark_utils import subsample

    frame = read_parquet_or_fail(spark, test_path)
    full_rows = frame.count()
    if quick_rows is not None and full_rows > quick_rows:
        frame = subsample(frame, quick_rows)
    return frame, full_rows


def read_parquet_or_fail(spark: SparkSession, path: Path) -> DataFrame:
    """``read_parquet_split`` with a friendly pre-check for the local case."""

    from ml.training.spark_utils import read_parquet_split

    if not path.exists() and not str(path).startswith(("hdfs://", "s3a://", "file://")):
        raise FileNotFoundError(
            f"Test split not found: {path}. Run `python -m ml.preprocessing.preprocess` first."
        )
    return read_parquet_split(spark, path)


def majority_baseline(frame: DataFrame) -> dict[str, float]:
    """Predict the majority class for every row (accuracy = majority share)."""

    rows = frame.groupBy("attack_category").count().collect()
    counts = {str(row["attack_category"]): int(row["count"]) for row in rows}
    total = sum(counts.values())
    if not total:
        return {"majority_class": None, "accuracy": 0.0, "support": 0}
    majority = max(counts, key=counts.get)
    return {
        "majority_class": majority,
        "accuracy": round(counts[majority] / total, 6),
        "support": total,
        "class_distribution": counts,
    }


def compare_with_training(
    metrics: dict[str, Any], training_metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """Flag drift between this evaluation and the training-time metrics."""

    if not isinstance(training_metadata, dict):
        return {"available": False, "reason": "model_metadata.json missing"}

    trained = training_metadata.get("metrics") or {}
    comparison: dict[str, Any] = {"available": True, "metrics": {}, "within_tolerance": True}
    for key in ("accuracy", "precision", "recall", "f1_score"):
        expected = trained.get(key)
        actual = metrics.get(key)
        if expected is None or actual is None:
            continue
        delta = round(float(actual) - float(expected), 6)
        within = abs(delta) <= DRIFT_TOLERANCE
        comparison["metrics"][key] = {
            "training": float(expected),
            "evaluation": float(actual),
            "delta": delta,
            "within_tolerance": within,
        }
        comparison["within_tolerance"] = comparison["within_tolerance"] and within
    return comparison


# =============================================================================
# Backend selection: Spark PipelineModel vs. sklearn mirror
# =============================================================================


def spark_model_loadable(model_path: Path) -> bool:
    """Return ``True`` when a complete Spark ``PipelineModel`` is present.

    A directory that only holds a stray ``metadata`` folder (the footprint of
    a half-finished save - e.g. a Windows host without ``hadoop.dll``) is not
    loadable, so we treat it as absent and fall back to the sklearn mirror.
    """

    if str(model_path).startswith(("hdfs://", "s3a://", "gs://")):
        return True
    root = Path(model_path)
    return (root / "metadata" / "metadata.json").is_file() and (root / "data").exists()


def evaluate_with_sklearn(
    *,
    models_dir: Path,
    test_path: Path,
    quick_rows: int | None = None,
) -> dict[str, Any]:
    """Evaluate the standalone sklearn mirror on the held-out test split.

    Used when the Spark ``PipelineModel`` binary cannot be loaded (Windows dev
    hosts without ``hadoop.dll``); the training run always exports this mirror
    alongside the JSON artifacts. Produces the same report schema as
    :func:`evaluate_model` so downstream consumers are backend-agnostic.
    """

    import numpy as np
    import pandas as pd
    from sklearn.metrics import confusion_matrix

    try:
        import joblib
    except ImportError as exc:  # pragma: no cover - dependency specific
        raise RuntimeError(f"joblib/scikit-learn unavailable for mirror evaluation: {exc}") from exc

    artifact = models_dir / "sklearn_model.pkl"
    if not artifact.is_file():
        raise FileNotFoundError(
            f"Neither a Spark PipelineModel nor the sklearn mirror ({artifact}) is available. "
            "Run `python ml/training/train_model.py` first."
        )

    total_started = time.monotonic()
    bundle = joblib.load(artifact)
    model = bundle["model"]
    feature_names = list(bundle["features"])
    logger.info("sklearn_mirror_loaded", path=str(artifact), features=len(feature_names))

    if not test_path.exists():
        raise FileNotFoundError(
            f"Test split not found: {test_path}. Run `python -m ml.preprocessing.preprocess` first."
        )
    test_pdf = pd.read_parquet(test_path)
    full_test_rows = int(len(test_pdf))
    if quick_rows is not None and full_test_rows > quick_rows:
        test_pdf = test_pdf.sample(n=quick_rows, random_state=42)
    missing = [name for name in feature_names if name not in test_pdf.columns]
    if missing:
        raise RuntimeError(f"Test split is missing model feature columns: {missing[:5]}")

    x_test = test_pdf[feature_names].astype("float64").to_numpy()
    y_test = test_pdf["attack_category"].astype(str).to_numpy()
    y_pred = np.asarray(model.predict(x_test)).astype(str)

    matrix = confusion_matrix(y_test, y_pred, labels=list(ATTACK_CLASSES)).tolist()
    matrix = [[int(cell) for cell in row] for row in matrix]
    summary = matrix_summary(matrix)
    per_class = per_class_metrics(matrix)

    counts = test_pdf["attack_category"].astype(str).value_counts().to_dict()
    baseline = {
        "majority_class": max(counts, key=counts.get) if counts else None,
        "accuracy": round((max(counts.values()) / len(test_pdf)) if counts and len(test_pdf) else 0.0, 6),
        "support": int(len(test_pdf)),
        "class_distribution": {str(k): int(v) for k, v in counts.items()},
    }

    metrics = {
        "accuracy": summary["accuracy"],
        "precision": summary["precision"],
        "recall": summary["recall"],
        "f1_score": summary["f1_score"],
        "macro_f1": summary["macro_f1"],
        "per_class_metrics": per_class,
        "confusion_matrix": matrix,
        "confusion_matrix_labels": list(ATTACK_CLASSES),
    }

    training_metadata: dict[str, Any] | None = None
    metadata_file = models_dir / "model_metadata.json"
    if metadata_file.exists():
        try:
            training_metadata = read_json(metadata_file)
        except Exception as exc:  # noqa: BLE001 - advisory only
            logger.warning("training_metadata_unreadable", error=str(exc))

    report: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "backend": "sklearn-mirror",
        "model_path": str(artifact),
        "test_path": str(test_path),
        "test_samples": int(len(test_pdf)),
        "full_test_split_rows": full_test_rows,
        "subsampled": int(len(test_pdf)) < full_test_rows,
        "classes": list(ATTACK_CLASSES),
        "metrics": {key: metrics[key] for key in ("accuracy", "precision", "recall", "f1_score", "macro_f1")},
        "per_class_metrics": metrics["per_class_metrics"],
        "confusion_matrix": metrics["confusion_matrix"],
        "confusion_matrix_normalized": normalize_confusion_matrix(metrics["confusion_matrix"]),
        "confusion_matrix_labels": metrics["confusion_matrix_labels"],
        "majority_baseline": baseline,
        "training_comparison": compare_with_training(metrics, training_metadata),
        "evaluation_seconds": round(time.monotonic() - total_started, 2),
        "notes": [
            "Spark PipelineModel was not loadable on this host (missing Hadoop "
            "native libraries); evaluated the exported sklearn mirror instead.",
            "The mirror is a RandomForest trained on the same processed splits, "
            "so its metrics are close to - but not identical to - the Spark model.",
        ],
    }
    report = to_jsonable(report)

    report_path = write_json(models_dir / "evaluation_report.json", report)
    logger.info(
        "evaluation_complete",
        backend="sklearn-mirror",
        accuracy=report["metrics"]["accuracy"],
        f1_score=report["metrics"]["f1_score"],
        report=str(report_path),
        seconds=report["evaluation_seconds"],
    )
    print_comparison(report)
    return report


# =============================================================================
# Orchestration
# =============================================================================


def evaluate_model(
    *,
    model_path: Path,
    test_path: Path,
    models_dir: Path,
    master: str | None = None,
    quick_rows: int | None = None,
) -> dict[str, Any]:
    """Run the full evaluation and persist the report. Returns the payload."""

    total_started = time.monotonic()
    if not spark_model_loadable(model_path):
        logger.warning(
            "spark_model_unloadable",
            path=str(model_path),
            hint="falling back to the sklearn mirror (Windows host without hadoop.dll)",
        )
        return evaluate_with_sklearn(
            models_dir=models_dir, test_path=test_path, quick_rows=quick_rows
        )
    spark = build_spark_session(
        "CyberShield-AI-Evaluation",
        master=master,
        enable_hdfs=str(model_path).startswith("hdfs://"),
    )

    pipeline = PipelineModel.load(str(model_path))
    logger.info("model_loaded", path=str(model_path), stages=len(pipeline.stages))

    test_df, full_test_rows = load_test_frame(spark, test_path, quick_rows)
    test_samples = test_df.count()
    logger.info("test_split_loaded", rows=test_samples, full_split=full_test_rows)

    predictions = pipeline.transform(test_df)
    metrics = evaluate_predictions(predictions)
    baseline = majority_baseline(test_df)

    training_metadata: dict[str, Any] | None = None
    metadata_file = models_dir / "model_metadata.json"
    if metadata_file.exists():
        try:
            training_metadata = read_json(metadata_file)
        except Exception as exc:  # noqa: BLE001 - advisory only
            logger.warning("training_metadata_unreadable", error=str(exc))

    report: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "model_path": str(model_path),
        "test_path": str(test_path),
        "test_samples": test_samples,
        "full_test_split_rows": full_test_rows,
        "subsampled": test_samples < full_test_rows,
        "classes": list(ATTACK_CLASSES),
        "metrics": {
            key: metrics[key]
            for key in ("accuracy", "precision", "recall", "f1_score", "macro_f1")
        },
        "per_class_metrics": metrics["per_class_metrics"],
        "confusion_matrix": metrics["confusion_matrix"],
        "confusion_matrix_normalized": normalize_confusion_matrix(metrics["confusion_matrix"]),
        "confusion_matrix_labels": metrics["confusion_matrix_labels"],
        "spark_evaluator_cross_check": metrics["spark_evaluator"],
        "majority_baseline": baseline,
        "training_comparison": compare_with_training(metrics, training_metadata),
        "evaluation_seconds": round(time.monotonic() - total_started, 2),
        "notes": [
            "Metrics are recomputed live from the persisted pipeline on the "
            "held-out test split; nothing is read from the training metadata.",
            "training_comparison compares against model_metadata.json within a "
            f"tolerance of {DRIFT_TOLERANCE} (same split, so deltas flag drift).",
        ],
    }
    report = to_jsonable(report)

    report_path = write_json(models_dir / "evaluation_report.json", report)
    logger.info(
        "evaluation_complete",
        accuracy=report["metrics"]["accuracy"],
        f1_score=report["metrics"]["f1_score"],
        report=str(report_path),
        seconds=report["evaluation_seconds"],
    )
    print_comparison(report)
    return report


def print_comparison(report: dict[str, Any]) -> None:
    """Human-readable summary on stdout."""

    metrics = report["metrics"]
    baseline = report["majority_baseline"]
    print("\n" + "=" * 64)
    print("CYBERSHIELD AI - MODEL EVALUATION (held-out test split)")
    print("=" * 64)
    print(f"Model            : {report['model_path']}")
    print(f"Test samples     : {report['test_samples']}")
    print(
        "Metrics          : "
        f"accuracy={metrics['accuracy']:.4f} precision={metrics['precision']:.4f} "
        f"recall={metrics['recall']:.4f} f1={metrics['f1_score']:.4f}"
    )
    print(
        f"Majority baseline: class={baseline.get('majority_class')} "
        f"accuracy={baseline.get('accuracy', 0.0):.4f}"
    )
    comparison = report.get("training_comparison") or {}
    if comparison.get("available"):
        status = "OK (no drift)" if comparison.get("within_tolerance") else "DRIFT DETECTED"
        print(f"Training match : {status}")
        for key, entry in comparison.get("metrics", {}).items():
            print(
                f"  {key:<10} training={entry['training']:.4f} "
                f"evaluation={entry['evaluation']:.4f} delta={entry['delta']:+.4f}"
            )
    print("=" * 64 + "\n")


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate",
        description="Evaluate the persisted CyberShield attack classifier on the test split.",
    )
    parser.add_argument(
        "--model-path", default=None, help="PipelineModel dir (default: ml/models/best_model)."
    )
    parser.add_argument("--test-path", default=None, help="Test Parquet (default: data/processed).")
    parser.add_argument("--models-dir", default=None, help="Artifact dir for the report.")
    parser.add_argument("--master", default=None, help="Spark master URL (default: local[*]).")
    parser.add_argument(
        "--quick", type=int, default=None, help="Subsample the test split to N rows."
    )
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR.")
    parser.add_argument("--json-logs", action="store_true", help="Force JSON log output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    models_dir = Path(args.models_dir) if args.models_dir else DEFAULT_MODELS_DIR
    model_path = Path(args.model_path) if args.model_path else models_dir / "best_model"
    test_path = Path(args.test_path) if args.test_path else DEFAULT_PROCESSED_DIR / "test.parquet"

    if (
        not spark_model_loadable(model_path)
        and not (models_dir / "sklearn_model.pkl").exists()
        and not str(model_path).startswith(("hdfs://", "s3a://"))
    ):
        logger.error("model_artifact_missing", path=str(model_path))
        print(
            f"ERROR: trained model not found at {model_path}\n"
            "Run `python ml/training/train_model.py` first."
        )
        return 1

    try:
        evaluate_model(
            model_path=model_path,
            test_path=test_path,
            models_dir=models_dir,
            master=args.master,
            quick_rows=args.quick,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.warning("evaluation_interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.exception("evaluation_failed", error=str(exc))
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
