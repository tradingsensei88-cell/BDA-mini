"""CyberShield AI - shared PySpark helpers for the ML training / evaluation layer.

This module centralises everything that :mod:`ml.training.train_model` and
:mod:`ml.evaluation.evaluate` share:

* :func:`build_spark_session` - a single, environment-driven ``SparkSession``
  factory. It creates a **full local** session (``local[*]``) by default so
  every script runs on a developer machine without a cluster, and switches to
  HDFS/Kafka integration through explicit flags.
* :func:`read_parquet_split` - robust Parquet loading that prefers native
  Spark reads and transparently falls back to pandas/pyarrow (useful on
  Windows hosts without ``winutils.exe``).
* Metric helpers computing **real** evaluation numbers from Spark predictions:
  confusion matrix, per-class precision/recall/F1, weighted metrics
  (manual + ``MulticlassClassificationEvaluator`` cross-check).
* Feature-importance extraction from tree ensembles, mapping OneHotEncoder
  expansions back onto their source NSL-KDD columns.
* JSON helpers (:func:`to_jsonable`, :func:`write_json`) that serialise numpy
  scalars and Spark vectors losslessly.

Windows note
------------
Spark on Windows works without ``winutils.exe`` for pure-local workloads, but
some Hadoop file-system calls may fail; every helper in this module degrades
gracefully (pandas fallback, non-fatal logging) instead of aborting the run.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.ml import PipelineModel
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.sql import DataFrame, SparkSession

from streaming.logging_config import get_logger
from streaming.settings import env, load_env

logger = get_logger(__name__)

# =============================================================================
# Project layout + domain constants
# =============================================================================

#: Repository root (``.../cybershield-ai``).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

#: Default output directory for model artifacts.
DEFAULT_MODELS_DIR: Path = PROJECT_ROOT / "ml" / "models"

#: Directory holding the processed Parquet splits.
DEFAULT_PROCESSED_DIR: Path = PROJECT_ROOT / "data" / "processed"

#: Canonical category order (matches ``ATTACK_CATEGORY_CODES`` in the
#: preprocessing module and the class order used across the frontend/API).
ATTACK_CLASSES: tuple[str, ...] = ("Normal", "DoS", "Probe", "R2L", "U2R")

#: Categorical NSL-KDD features handled by StringIndexer + OneHotEncoder.
CATEGORICAL_FEATURES: tuple[str, ...] = ("protocol_type", "service", "flag")

#: Features dropped by the preprocessing pipeline (zero variance on train).
DROPPED_FEATURES: frozenset[str] = frozenset({"num_outbound_cmds"})

#: The 41 canonical NSL-KDD feature names (single source of truth import).
from streaming.schemas.event_schema import (  # noqa: E402  (after bootstrap)
    NSL_KDD_FEATURE_FIELDS,
)

#: Root of the locally provisioned winutils shim (Windows dev hosts only).
WINDOWS_SHIM_ROOT: Path = PROJECT_ROOT / ".winutils"


# =============================================================================
# Windows dev-host support: local winutils shim
# =============================================================================

#: Source of a minimal ``winutils.exe`` shim compiled on demand with the
#: system .NET Framework compiler. Spark's ``RawLocalFileSystem`` shells out
#: to ``winutils chmod`` when creating the ``_temporary`` staging directory
#: of an ``MLWriter`` save; NTFS has no POSIX permissions, so a permissive
#: no-op shim is the standard way to unblock local Windows development.
#: It is only provisioned when no real ``HADOOP_HOME`` exists and HDFS is
#: not requested; production (Docker/Linux) runs never use it.
_WINUTILS_SHIM_SOURCE = '''\
using System;
using System.IO;

internal static class WinUtilsShim
{
    private static int Main(string[] args)
    {
        // Minimal winutils shim for local Windows development.
        // Exit code 0 (success) for every sub-command; chmod/chown are
        // inherently meaningless on NTFS and are treated as no-ops.
        if (args.Length == 0)
        {
            Console.WriteLine("Hadoop 3.3.4 (cybershield local winutils shim)");
            return 0;
        }
        switch (args[0].ToLowerInvariant())
        {
            case "version":
            case "--version":
                Console.WriteLine("Hadoop 3.3.4");
                return 0;
            case "ls":
                if (args.Length > 1 && Directory.Exists(args[1]))
                {
                    foreach (string entry in Directory.GetFileSystemEntries(args[1]))
                    {
                        Console.WriteLine(entry);
                    }
                }
                return 0;
            default:
                // chmod / chown / mkdir / df / ... -> succeed silently.
                return 0;
        }
    }
}
'''


def _find_dotnet_compiler() -> Path | None:
    """Return the system C# compiler (csc.exe) when available."""

    candidates = [
        Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def provision_windows_winutils_shim(*, force: bool = False) -> Path | None:
    """Compile/attach a minimal ``winutils.exe`` shim for local Windows runs.

    Returns the ``HADOOP_HOME`` root when a shim is (or was) provisioned,
    ``None`` on non-Windows hosts, when a real ``HADOOP_HOME`` already exists,
    or when provisioning is disabled (``CYBERSHIELD_WINUTILS_SHIM=0``).

    The shim is compiled from an embedded C# source with the .NET Framework
    ``csc.exe`` that ships with Windows - no downloads involved - and only
    affects the local development experience: without it Spark's
    ``MLWriter`` cannot create directories on a machine lacking the real
    Hadoop Windows binaries.
    """

    if os.name != "nt":
        return None
    if os.environ.get("CYBERSHIELD_WINUTILS_SHIM", "1") == "0":
        return None

    existing_home = os.environ.get("HADOOP_HOME") or os.environ.get("hadoop.home.dir")
    if existing_home:
        winutils = Path(existing_home) / "bin" / "winutils.exe"
        if winutils.is_file():
            logger.info("winutils_found", home=existing_home)
            return Path(existing_home)

    binary = WINDOWS_SHIM_ROOT / "bin" / "winutils.exe"
    source = WINDOWS_SHIM_ROOT / "src" / "WinUtilsShim.cs"
    if binary.is_file() and not force:
        os.environ.setdefault("HADOOP_HOME", str(WINDOWS_SHIM_ROOT))
        os.environ.setdefault("hadoop.home.dir", str(WINDOWS_SHIM_ROOT))
        return WINDOWS_SHIM_ROOT

    compiler = _find_dotnet_compiler()
    if compiler is None:
        logger.warning(
            "winutils_shim_unavailable",
            hint="csc.exe not found; Spark MLWriter saves may fail on Windows",
        )
        return None

    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        binary.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(_WINUTILS_SHIM_SOURCE, encoding="utf-8")
        completed = subprocess.run(
            [
                str(compiler),
                "/nologo",
                "/target:exe",
                f"/out:{binary}",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0 or not binary.is_file():
            logger.warning(
                "winutils_shim_compile_failed",
                returncode=completed.returncode,
                stderr=(completed.stderr or "")[:300],
            )
            return None
    except Exception as exc:  # noqa: BLE001 - dev convenience only
        logger.warning("winutils_shim_compile_failed", error=str(exc))
        return None

    os.environ["HADOOP_HOME"] = str(WINDOWS_SHIM_ROOT)
    os.environ["hadoop.home.dir"] = str(WINDOWS_SHIM_ROOT)
    logger.info("winutils_shim_ready", binary=str(binary))
    return WINDOWS_SHIM_ROOT


# =============================================================================
# Spark session factory
# =============================================================================


def default_master() -> str:
    """Return the default Spark master for this host.

    Resolution order: ``SPARK_MASTER`` env var -> ``local[*]``. The fully
    local session is intentional: every training/evaluation script must run
    on a bare developer machine without a cluster.
    """

    return env("SPARK_MASTER", "local[*]") or "local[*]"


def build_spark_session(
    app_name: str,
    *,
    master: str | None = None,
    enable_hdfs: bool = False,
    enable_kafka: bool = False,
    kafka_package: str | None = None,
    extra_config: dict[str, str] | None = None,
    log_level: str | None = None,
) -> SparkSession:
    """Create (or reuse) an environment-configured :class:`SparkSession`.

    Args:
        app_name: Spark application name shown in the UI.
        master: Explicit master URL. Defaults to ``SPARK_MASTER`` env var or
            ``local[*]``. Pass ``spark://<host>:7077`` to use a cluster.
        enable_hdfs: Point ``fs.defaultFS`` at the HDFS NameNode
            (``HDFS_NAMENODE_URL``, default ``hdfs://namenode:8020``).
        enable_kafka: Attach the ``spark-sql-kafka`` connector package
            (needed by the structured streaming job, not by training).
        kafka_package: Maven coordinate override, defaults to
            ``SPARK_KAFKA_PACKAGE`` env var or the Spark 3.5 / Scala 2.12 jar.
        extra_config: Additional ``spark.*`` configuration keys.
        log_level: Spark log level, defaults to ``SPARK_LOG_LEVEL`` / ``WARN``.

    Returns:
        A ready-to-use :class:`SparkSession`.
    """

    load_env()
    builder = SparkSession.builder.appName(app_name).master(master or default_master())
    resolved_master = master or default_master()

    config: dict[str, str] = {
        "spark.sql.shuffle.partitions": env("SPARK_SHUFFLE_PARTITIONS", "16") or "16",
        "spark.sql.session.timeZone": "UTC",
        "spark.ui.showConsoleProgress": "false",
        "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
    }

    # Windows dev hosts: provision the local winutils shim so MLWriter saves
    # (model artifacts) work without a full Hadoop installation.
    if os.name == "nt" and not enable_hdfs:
        shim_root = provision_windows_winutils_shim()
        if shim_root is not None:
            config["spark.hadoop.hadoop.home.dir"] = str(shim_root)
    if resolved_master.startswith("local") and os.name == "nt":
        os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

    if enable_hdfs:
        config["spark.hadoop.fs.defaultFS"] = (
            env("HDFS_NAMENODE_URL", "hdfs://namenode:8020") or "hdfs://namenode:8020"
        )
    if enable_kafka:
        config["spark.jars.packages"] = (
            kafka_package
            or env("SPARK_KAFKA_PACKAGE")
            or "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1"
        )
    config.update(extra_config or {})

    for key, value in config.items():
        builder = builder.config(key, value)

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel(log_level or env("SPARK_LOG_LEVEL", "WARN") or "WARN")

    logger.info(
        "spark_session_ready",
        app_name=app_name,
        master=spark.sparkContext.master,
        spark_version=spark.version,
        hdfs=enable_hdfs,
        kafka_connector=enable_kafka,
    )
    return spark


# =============================================================================
# JSON helpers (numpy / Spark objects -> plain Python)
# =============================================================================


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value into something ``json.dump`` accepts.

    Handles numpy scalars/arrays, Spark vectors, datetimes and Paths.
    Unknown objects fall back to ``str(value)`` so serialisation never fails.
    """

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)

    # numpy / pandas scalars expose .item()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:  # noqa: BLE001 - fall through to str()
            pass

    # Spark ML vectors expose .toArray()
    to_array = getattr(value, "toArray", None)
    if callable(to_array):
        try:
            return [float(x) for x in to_array().tolist()]
        except Exception:  # noqa: BLE001
            pass

    return str(value)


def write_json(path: str | Path, payload: Any, *, indent: int = 2) -> Path:
    """Write ``payload`` as UTF-8 JSON, creating parent directories."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(payload), handle, indent=indent, ensure_ascii=False)
    logger.info("json_written", path=str(target))
    return target


def read_json(path: str | Path) -> Any:
    """Read a JSON document; raises ``FileNotFoundError`` when missing."""

    target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_directory(path: str | Path) -> Path:
    """Create ``path`` (recursively) and return it as a :class:`Path`."""

    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def utc_now_iso() -> str:
    """Timezone-aware UTC timestamp used in every artifact."""

    from datetime import timezone

    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Data loading
# =============================================================================


def _looks_like_hdfs(path: str) -> bool:
    return any(path.startswith(scheme) for scheme in ("hdfs://", "s3a://", "s3://", "gs://"))


def read_parquet_split(
    spark: SparkSession,
    path: str | Path,
    *,
    fallback_pandas: bool = True,
) -> DataFrame:
    """Read a Parquet split into a Spark DataFrame.

    The native Spark reader is attempted first (required for HDFS paths).
    On local filesystems a failure - e.g. a Windows host without
    ``winutils.exe`` - falls back to pandas/pyarrow + ``createDataFrame``
    so training always stays runnable.

    Args:
        spark: Active session.
        path: Local path or Hadoop URI.
        fallback_pandas: Enable the pandas fallback for local paths.

    Raises:
        RuntimeError: When both readers fail.
    """

    path_str = str(path)
    try:
        frame = spark.read.parquet(path_str)
        frame.count()  # force evaluation so FS errors surface here
        logger.info("parquet_read_spark", path=path_str, columns=len(frame.columns))
        return frame
    except Exception as exc:  # noqa: BLE001 - any Hadoop/FS failure
        logger.warning("parquet_read_spark_failed", path=path_str, error=str(exc))
        if not fallback_pandas or _looks_like_hdfs(path_str):
            raise RuntimeError(f"Unable to read parquet {path_str!r}: {exc}") from exc

    local_path = path_str[7:] if path_str.startswith("file://") else path_str
    try:
        import pandas as pd

        pdf = pd.read_parquet(local_path)
        frame = dataframe_from_pandas(spark, pdf)
        logger.info(
            "parquet_read_pandas_fallback", path=local_path, rows=int(len(pdf))
        )
        return frame
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Unable to read parquet {path_str!r} with Spark or pandas: {exc}"
        ) from exc


def dataframe_from_pandas(spark: SparkSession, pdf: "Any") -> DataFrame:
    """Convert a pandas frame (pyarrow dtypes included) into a Spark frame.

    Nullable pandas extensions (``string[python]``, ``Int64``, ``boolean``)
    are normalised to plain Python objects so Spark's type inference works.
    """

    import pandas as pd

    normalised = pdf.copy()
    for column in normalised.columns:
        dtype = normalised[column].dtype
        dtype_name = str(dtype)
        if dtype == object or dtype_name.startswith("string"):
            normalised[column] = normalised[column].astype("object").where(
                normalised[column].notna(), None
            )
        elif dtype_name == "Int64":
            if normalised[column].isna().any():
                normalised[column] = normalised[column].astype("float64")
            else:
                normalised[column] = normalised[column].astype("int64")
        elif dtype_name == "boolean":
            normalised[column] = normalised[column].astype("object")
    return spark.createDataFrame(normalised)


def subsample(frame: DataFrame, max_rows: int | None, *, seed: int = 42) -> DataFrame:
    """Deterministically subsample ``frame`` down to ``max_rows`` (if set)."""

    if max_rows is None:
        return frame
    total = frame.count()
    if total <= max_rows:
        return frame
    fraction = max(0.0, min(1.0, max_rows / float(total)))
    sampled = frame.sample(withReplacement=False, fraction=fraction, seed=seed)
    logger.info("dataset_subsampled", total=total, target=max_rows, fraction=round(fraction, 4))
    return sampled


# =============================================================================
# Metrics
# =============================================================================


def compute_confusion_matrix(
    predictions: DataFrame,
    *,
    class_names: Sequence[str] = ATTACK_CLASSES,
    label_col: str = "label",
    prediction_col: str = "prediction",
) -> list[list[int]]:
    """Aggregate ``(label, prediction)`` counts into an NxN matrix."""

    num_classes = len(class_names)
    matrix = [[0 for _ in range(num_classes)] for _ in range(num_classes)]

    rows = (
        predictions.groupBy(label_col, prediction_col)
        .count()
        .collect()
    )
    for row in rows:
        label = row[label_col]
        prediction = row[prediction_col]
        if label is None or prediction is None:
            continue
        i, j = int(label), int(prediction)
        if 0 <= i < num_classes and 0 <= j < num_classes:
            matrix[i][j] = int(row["count"])
    return matrix


def per_class_metrics(
    matrix: Sequence[Sequence[int]],
    class_names: Sequence[str] = ATTACK_CLASSES,
) -> dict[str, dict[str, float | int]]:
    """Per-class precision / recall / F1 / support from a confusion matrix."""

    num_classes = len(class_names)
    results: dict[str, dict[str, float | int]] = {}

    for i, name in enumerate(class_names):
        true_positive = int(matrix[i][i])
        support = int(sum(matrix[i]))
        predicted_total = int(sum(matrix[r][i] for r in range(num_classes)))

        precision = true_positive / predicted_total if predicted_total else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        results[name] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1_score": round(f1, 6),
            "support": support,
        }
    return results


def matrix_summary(
    matrix: Sequence[Sequence[int]],
    class_names: Sequence[str] = ATTACK_CLASSES,
) -> dict[str, float]:
    """Accuracy + weighted precision/recall/F1 computed from the matrix."""

    num_classes = len(class_names)
    total = int(sum(sum(row) for row in matrix))
    correct = int(sum(matrix[i][i] for i in range(num_classes)))
    accuracy = correct / total if total else 0.0

    per_class = per_class_metrics(matrix, class_names)
    weighted_precision = 0.0
    weighted_recall = 0.0
    weighted_f1 = 0.0
    macro_f1 = 0.0

    for name in class_names:
        stats = per_class[name]
        weight = (stats["support"] / total) if total else 0.0
        weighted_precision += weight * float(stats["precision"])
        weighted_recall += weight * float(stats["recall"])
        weighted_f1 += weight * float(stats["f1_score"])
        macro_f1 += float(stats["f1_score"]) / num_classes

    return {
        "accuracy": round(accuracy, 6),
        "precision": round(weighted_precision, 6),
        "recall": round(weighted_recall, 6),
        "f1_score": round(weighted_f1, 6),
        "macro_f1": round(macro_f1, 6),
        "support": total,
    }


def spark_evaluator_metrics(
    predictions: DataFrame,
    *,
    label_col: str = "label",
    prediction_col: str = "prediction",
) -> dict[str, float]:
    """Cross-check metrics through ``MulticlassClassificationEvaluator``."""

    metrics: dict[str, float] = {}
    for metric_name in ("accuracy", "weightedPrecision", "weightedRecall", "f1"):
        try:
            evaluator = MulticlassClassificationEvaluator(
                labelCol=label_col,
                predictionCol=prediction_col,
                metricName=metric_name,
            )
            metrics[metric_name] = round(float(evaluator.evaluate(predictions)), 6)
        except Exception as exc:  # noqa: BLE001 - evaluation is best-effort
            logger.warning("evaluator_metric_failed", metric=metric_name, error=str(exc))
    return metrics


def evaluate_predictions(
    predictions: DataFrame,
    *,
    class_names: Sequence[str] = ATTACK_CLASSES,
    label_col: str = "label",
    prediction_col: str = "prediction",
) -> dict[str, Any]:
    """Full evaluation bundle: matrix, per-class stats, weighted metrics.

    The canonical numbers are computed from the confusion matrix (fully
    transparent); ``MulticlassClassificationEvaluator`` results are added as
    a cross-check under ``spark_evaluator``.
    """

    matrix = compute_confusion_matrix(
        predictions, class_names=class_names, label_col=label_col, prediction_col=prediction_col
    )
    summary = matrix_summary(matrix, class_names)
    per_class = per_class_metrics(matrix, class_names)
    cross_check = spark_evaluator_metrics(
        predictions, label_col=label_col, prediction_col=prediction_col
    )

    return {
        "accuracy": summary["accuracy"],
        "precision": summary["precision"],
        "recall": summary["recall"],
        "f1_score": summary["f1_score"],
        "macro_f1": summary["macro_f1"],
        "per_class_metrics": per_class,
        "confusion_matrix": matrix,
        "confusion_matrix_labels": list(class_names),
        "spark_evaluator": cross_check,
    }


def normalize_confusion_matrix(matrix: Sequence[Sequence[int]]) -> list[list[float]]:
    """Row-normalised confusion matrix (recall view), rounded to 4 decimals."""

    normalized: list[list[float]] = []
    for row in matrix:
        total = sum(row)
        if total:
            normalized.append([round(cell / total, 4) for cell in row])
        else:
            normalized.append([0.0 for _ in row])
    return normalized


# =============================================================================
# Feature importance
# =============================================================================


def _ohe_output_names(ohe_model: Any) -> list[tuple[str, int]]:
    """Return ``[(output_column, num_output_slots), ...]`` for an OHE model.

    Slot counting must match the fitted encoder's output vector exactly, or
    ``extract_feature_importance`` falls back to generic slot names. Spark
    sizes the vector as ``categorySizes`` minus the dropped-last category
    (when ``dropLast``) plus one trailing ``invalid`` bucket per column when
    ``handleInvalid == "keep"`` (which the training pipeline uses), so both
    adjustments are applied here.
    """

    names: list[tuple[str, int]] = []
    try:
        sizes = [int(size) for size in list(ohe_model.categorySizes)]
        drop_last = bool(ohe_model.getDropLast())
        try:
            keep_invalid = str(ohe_model.getHandleInvalid()).lower() == "keep"
        except Exception:  # noqa: BLE001 - older Spark lacks the getter
            keep_invalid = False
        output_cols = list(ohe_model.getOutputCols())
        for column, size in zip(output_cols, sizes):
            slots = size - 1 if drop_last else size
            if keep_invalid:
                slots += 1
            names.append((column, max(1, slots)))
    except Exception as exc:  # noqa: BLE001 - stay defensive across Spark versions
        logger.warning("ohe_introspection_failed", error=str(exc))
    return names


def _resolve_importance_values(classifier: Any) -> list[float] | None:
    """Return a per-slot importance vector for a fitted classifier.

    Handles the two shapes the training pipeline produces:

    * a natively-multiclass tree model (Random Forest / Decision Tree / GBT)
      exposing ``featureImportances`` directly; and
    * a ``OneVsRestModel`` (Spark's GBT is binary-only, so the multiclass GBT
      candidate is wrapped), whose ``models`` are one tree ensemble per class
      - their ``featureImportances`` are averaged into a single vector.

    ``None`` signals the model carries no importances (e.g. logistic
    regression), and the caller degrades to empty artifacts.
    """

    importances = getattr(classifier, "featureImportances", None)
    if importances is not None:
        try:
            return [float(value) for value in importances.toArray().tolist()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("feature_importance_extract_failed", error=str(exc))
            return None

    member_models = getattr(classifier, "models", None)
    if member_models:
        vectors: list[list[float]] = []
        for member in member_models:
            member_importances = getattr(member, "featureImportances", None)
            if member_importances is None:
                return None
            try:
                vectors.append([float(value) for value in member_importances.toArray().tolist()])
            except Exception as exc:  # noqa: BLE001
                logger.warning("ovr_feature_importance_failed", error=str(exc))
                return None
        if vectors:
            length = len(vectors[0])
            return [
                sum(vector[index] for vector in vectors) / float(len(vectors))
                for index in range(length)
            ]
    return None


def extract_feature_importance(
    classifier: Any,
    *,
    numeric_features: Sequence[str],
    ohe_models: Iterable[Any] = (),
) -> tuple[dict[str, float], dict[str, float]]:
    """Extract tree feature importances, aggregated by original feature.

    Returns ``(aggregated, detailed)``:

    * ``aggregated`` - importance per NSL-KDD feature
      (OneHotEncoder slots are summed back into their source column, e.g.
      every ``service`` slot contributes to the ``service`` entry).
    * ``detailed``   - importance per assembled vector slot.

    Supports natively-multiclass tree models and ``OneVsRest`` ensembles
    (member importances averaged); logistic-regression style models without
    importances yield two empty dicts.
    """

    values = _resolve_importance_values(classifier)
    if values is None:
        logger.info("feature_importance_unavailable", model=type(classifier).__name__)
        return {}, {}

    detailed_names: list[str] = list(numeric_features)
    source_map: dict[str, str] = {name: name for name in numeric_features}
    for ohe_model in ohe_models:
        for column, slots in _ohe_output_names(ohe_model):
            for slot in range(slots):
                slot_name = f"{column}_{slot}"
                detailed_names.append(slot_name)
                source_map[slot_name] = column.split("_ohe")[0] if "_ohe" in column else column

    if len(detailed_names) != len(values):
        logger.warning(
            "feature_importance_length_mismatch",
            names=len(detailed_names),
            values=len(values),
        )
        detailed_names = [f"slot_{i}" for i in range(len(values))]
        source_map = {name: name for name in detailed_names}

    detailed = {
        name: round(value, 8) for name, value in zip(detailed_names, values)
    }
    aggregated: dict[str, float] = {}
    for name, value in zip(detailed_names, values):
        key = source_map.get(name, name)
        aggregated[key] = round(aggregated.get(key, 0.0) + value, 8)

    # Sort by importance descending for readable artifacts.
    aggregated = dict(sorted(aggregated.items(), key=lambda item: item[1], reverse=True))
    return aggregated, detailed


# =============================================================================
# Model persistence
# =============================================================================


def save_model(model: PipelineModel, path: str | Path, *, overwrite: bool = True) -> bool:
    """Persist a fitted ``PipelineModel``; returns ``False`` on failure.

    Saving must never abort a training run: the metadata/feature-importance
    JSON artifacts stay valid even when the Spark writer fails (e.g. a
    Windows host without ``winutils.exe``).
    """

    target = str(path)
    try:
        writer = model.write()
        if overwrite:
            writer = writer.overwrite()
        writer.save(target)
        logger.info("model_saved", path=target)
        return True
    except Exception as exc:  # noqa: BLE001 - persistence is best effort
        logger.error("model_save_failed", path=target, error=str(exc))
        return False


def load_model(
    spark: SparkSession,
    path: str | Path,
    *,
    required: bool = False,
) -> PipelineModel | None:
    """Load a persisted ``PipelineModel``; ``None`` when unavailable."""

    target = str(path)
    try:
        model = PipelineModel.load(target)
        logger.info("model_loaded", path=target, stages=len(model.stages))
        return model
    except Exception as exc:  # noqa: BLE001
        if required:
            raise
        logger.warning("model_load_failed", path=target, error=str(exc))
        return None


def timed() -> float:
    """Monotonic start marker for measuring stage durations."""

    return time.monotonic()


def os_cpu_hint() -> int:
    """Best-effort core count used in logs / default parallelism hints."""

    return os.cpu_count() or 1
