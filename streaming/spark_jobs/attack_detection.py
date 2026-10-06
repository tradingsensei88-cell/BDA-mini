"""CyberShield AI - Spark Structured Streaming attack-detection job.

Consumes raw NSL-KDD style flow events from the ``network-events`` Kafka
topic, scores every event with the trained Spark MLlib pipeline
(``ml/models/best_model``), and publishes the enriched detections to the
``security-events`` / ``alerts`` Kafka topics (optionally mirroring
predictions and pipeline metrics into PostgreSQL).

Pipeline (per micro-batch)
--------------------------
1. **Read** ``network-events`` from Kafka and parse the JSON payload into
   the canonical :class:`~streaming.schemas.event_schema.NetworkEvent`
   layout (41 features + pipeline metadata).
2. **Featurise** with the *train-fitted* preprocessing stages of the
   persisted ``PipelineModel`` (StringIndexer / OneHotEncoder /
   VectorAssembler / StandardScaler). The trailing label indexer is
   dropped - ground-truth labels are unavailable at inference time. When
   no model artifact exists yet the job degrades to a transparent
   heuristic scorer so the demo stack stays operational end to end.
3. **Predict** - the classifier emits ``prediction`` (label index) and
   ``probability`` (class distribution). Both are converted to the
   ``SecurityEvent`` contract through pure Spark SQL expressions so the
   executors never need the ``streaming`` package on their PYTHONPATH.
4. **Route** - attack events at/above the alert threshold additionally
   produce ``Alert`` messages on the ``alerts`` topic.
5. **Sink** - one ``foreach_batch`` per micro-batch publishes to Kafka
   (per-partition producers, flushed at batch end) and, when enabled,
   writes ``predictions`` + ``system_metrics`` rows to PostgreSQL.

Delivery semantics: Kafka -> Spark is end-to-end *at-least-once* (source
offsets live in the checkpoint); every sink is idempotent (``ON CONFLICT
DO NOTHING`` inserts, UUID-keyed Kafka messages) so replays never
duplicate state.

Usage::

    # host dev run (Kafka at localhost:29092, local model artifact)
    python -m streaming.spark_jobs.attack_detection --trigger-seconds 5

    # cluster run via spark-submit (see docker-compose.yml volumes)
    spark-submit --master spark://spark-master:7077 \\
        --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 \\
        streaming/spark_jobs/attack_detection.py --bootstrap-servers kafka:9092
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.ml import PipelineModel
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from ml.training.spark_utils import (
    ATTACK_CLASSES,
    CATEGORICAL_FEATURES,
    DEFAULT_MODELS_DIR,
    build_spark_session,
    read_json,
)
from streaming.logging_config import configure_logging, get_logger
from streaming.schemas.event_schema import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    NSL_KDD_CATEGORICAL_FIELDS,
    NSL_KDD_FEATURE_FIELDS,
    TOPIC_ALERTS,
    TOPIC_NETWORK_EVENTS,
    TOPIC_SECURITY_EVENTS,
)
from streaming.settings import env, kafka_bootstrap_servers, load_env

logger = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

JOB_NAME = "cybershield-attack-detection"
COMPONENT = "spark"

#: Consumer group used by the structured-streaming Kafka source.
DEFAULT_CONSUMER_GROUP = "cybershield-spark-detection"

#: Risk-score bands mirroring ``severity_from_risk_score`` in the schema
#: module, re-expressed as SQL CASE inputs so executors stay dependency-free.
_SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (85.0, "critical"),
    (65.0, "high"),
    (40.0, "medium"),
    (15.0, "low"),
)

#: Relative severity weight per attack category (mirrors
#: ``_CATEGORY_RISK_WEIGHT`` in streaming.schemas.event_schema).
_CATEGORY_RISK_WEIGHT: dict[str, float] = {
    "Normal": 0.20,
    "DoS": 0.80,
    "Probe": 0.55,
    "R2L": 0.90,
    "U2R": 1.00,
    "Unknown": 0.70,
}

#: Scorer identity used when no trained artifact is available; the name
#: makes the degraded path obvious in every downstream consumer.
HEURISTIC_MODEL_NAME = "cybershield-heuristic-fallback"


# =============================================================================
# Source schema
# =============================================================================


def numeric_feature_fields() -> list[str]:
    """The non-categorical NSL-KDD features (all read as doubles)."""

    return [name for name in NSL_KDD_FEATURE_FIELDS if name not in NSL_KDD_CATEGORICAL_FIELDS]


def build_event_schema() -> StructType:
    """Flat StructType for the JSON payload published by the event producer.

    ``from_json`` ignores unknown keys and nulls missing ones, so schema
    drift between producer versions can never fail the stream.
    """

    fields: list[StructField] = [
        StructField("event_id", StringType(), True),
        StructField("timestamp", TimestampType(), True),
    ]
    for name in NSL_KDD_FEATURE_FIELDS:
        if name in NSL_KDD_CATEGORICAL_FIELDS:
            fields.append(StructField(name, StringType(), True))
        else:
            fields.append(StructField(name, DoubleType(), True))
    fields.extend(
        [
            StructField("attack_type", StringType(), True),
            StructField("attack_category", StringType(), True),
            StructField("source_host", StringType(), True),
            StructField("destination_host", StringType(), True),
            StructField("source_ip", StringType(), True),
            StructField("destination_ip", StringType(), True),
        ]
    )
    return StructType(fields)


# =============================================================================
# Source: Kafka -> parsed events
# =============================================================================


def read_kafka_stream(
    spark: SparkSession,
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    starting_offsets: str,
    max_offsets_per_trigger: int,
) -> DataFrame:
    """Return the append-only Kafka source DataFrame (offsets in checkpoint)."""

    return (
        spark.read.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", topic)
        .option("kafka.group.id", group_id)
        .option("startingOffsets", starting_offsets)
        .option("failOnDataLoss", "false")
        .option("maxOffsetsPerTrigger", max_offsets_per_trigger)
        .load()
    )


def parse_events(raw: DataFrame, schema: StructType) -> DataFrame:
    """Decode Kafka JSON values into the flat event layout, dropping poison pills."""

    parsed = raw.select(
        F.from_json(F.col("value").cast("string"), schema).alias("event"),
        F.col("timestamp").alias("kafka_timestamp"),
    )
    exploded = parsed.select("event.*", "kafka_timestamp")
    # Malformed/empty JSON yields an all-null struct; drop those rows so a
    # poison pill can never stall the micro-batch.
    return exploded.where(F.col("event_id").isNotNull() & F.col("timestamp").isNotNull())


def prepare_features(events: DataFrame) -> DataFrame:
    """Normalise feature dtypes and fill nulls so encoders never error/skip."""

    frame = events
    for name in numeric_feature_fields():
        frame = frame.withColumn(name, F.coalesce(F.col(name).cast("double"), F.lit(0.0)))
    for name in CATEGORICAL_FEATURES:
        frame = frame.withColumn(
            name, F.coalesce(F.col(name).cast("string"), F.lit("unknown"))
        )
    return frame


# =============================================================================
# SQL-side scoring helpers (contract-compatible with the pydantic schemas)
# =============================================================================


def _case_map(expression: Column, mapping: dict[str, Any], otherwise: Any) -> Column:
    """Build a ``when/otherwise`` chain mapping a string column to literals."""

    result = F.lit(otherwise)
    for key, value in mapping.items():
        result = F.when(expression == F.lit(key), F.lit(value)).otherwise(result)
    return result


def risk_score_expression(category: Column, confidence: Column) -> Column:
    """``compute_risk_score`` as pure SQL: category weight x confidence x 100."""

    weight = _case_map(category, _CATEGORY_RISK_WEIGHT, 0.5)
    return F.round(
        F.least(F.lit(100.0), F.greatest(F.lit(0.0), weight * confidence * 100.0)), 2
    )


def severity_expression(risk: Column) -> Column:
    """``severity_from_risk_score`` as pure SQL bands."""

    result = F.lit("info")
    for threshold, label in reversed(_SEVERITY_BANDS):
        result = F.when(risk >= F.lit(threshold), F.lit(label)).otherwise(result)
    return result


def _probability_map(probability_col: Column, label_index: list[str]) -> Column:
    """Classifier probability vector -> ``{class: prob}`` map keyed by name."""

    return F.map_from_arrays(
        F.array(*[F.lit(name) for name in label_index]),
        F.vector_to_array(probability_col),
    )


def _iso(column: Column) -> Column:
    """Timestamps -> ISO-8601 UTC strings (session TZ is pinned to UTC)."""

    return F.date_format(column, "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'")


# =============================================================================
# Scoring branches
# =============================================================================


def split_pipeline(spark: SparkSession, model_path: str) -> tuple[PipelineModel, PipelineModel]:
    """Split the saved artifact into ``(featurizer, classifier)``.

    The training pipeline persists ``[3x StringIndexer, OHE, Assembler,
    Scaler, LabelIndexer, Classifier]``. Streaming inference must not run
    the label indexer (no ground truth at inference time), so the final two
    stages are separated.
    """

    pipeline = PipelineModel.load(model_path)
    if len(pipeline.stages) < 2:  # pragma: no cover - corrupt artifact guard
        raise ValueError(f"Model artifact has {len(pipeline.stages)} stage(s); expected >= 2")
    featurizer = PipelineModel(stages=pipeline.stages[:-2])
    classifier = PipelineModel(stages=pipeline.stages[-1:])
    return featurizer, classifier


def score_with_model(
    features: DataFrame,
    *,
    featurizer: PipelineModel,
    classifier: PipelineModel,
    label_index: list[str],
    model_name: str,
    model_version: str,
) -> DataFrame:
    """Apply the persisted pipeline and add the ``SecurityEvent`` scoring columns."""

    predictions = classifier.transform(featurizer.transform(features))
    category = _case_map(
        F.col("prediction").cast("int").cast("string"),
        {str(code): name for code, name in enumerate(label_index)},
        "Unknown",
    )
    confidence = F.array_max(F.vector_to_array(F.col("probability")))

    return predictions.select(
        "*",  # keep all source + scoring columns
        category.alias("predicted_category"),
        F.greatest(F.lit(0.0), F.least(F.lit(1.0), confidence)).alias("confidence"),
        _probability_map(F.col("probability"), label_index).alias("probabilities"),
        risk_score_expression(category, confidence).alias("risk_score"),
        F.when(category != F.lit("Normal"), F.lit(True)).otherwise(F.lit(False)).alias(
            "is_attack"
        ),
        F.lit(model_name).alias("scoring_model"),
        F.lit(model_version).alias("scoring_version"),
    ).drop("features", "rawPrediction", "probability", "prediction")


def score_with_heuristic(
    events: DataFrame,
    *,
    model_version: str,
) -> DataFrame:
    """Transparent rules-based fallback used when no model artifact exists.

    Classic IDS heuristics over the NSL-KDD features (error rates, failed
    logins, root compromise indicators). Output columns match
    :func:`score_with_model` so every downstream sink is agnostic.
    """

    confidence = F.greatest(
        F.lit(0.0),
        F.least(
            F.lit(0.99),
            F.greatest(
                F.col("rerror_rate"),
                F.col("srv_rerror_rate"),
                F.col("dst_host_serror_rate"),
                F.col("dst_host_srv_serror_rate"),
            )
            * F.lit(0.55)
            + F.least(F.col("num_failed_logins") / F.lit(5.0), F.lit(1.0)) * F.lit(0.30)
            + F.least(F.col("num_compromised") / F.lit(3.0), F.lit(1.0)) * F.lit(0.25)
            + F.when(F.col("root_shell") > F.lit(0), F.lit(0.35)).otherwise(F.lit(0.0))
            + F.when(F.col("su_attempted") > F.lit(0), F.lit(0.20)).otherwise(F.lit(0.0))
            + F.when(F.col("is_host_login") > F.lit(0), F.lit(0.20)).otherwise(F.lit(0.0)),
        ),
    )

    category = (
        F.when(F.col("num_failed_logins") > F.lit(2), F.lit("R2L"))
        .when(
            (F.col("root_shell") > F.lit(0)) | (F.col("su_attempted") > F.lit(0)),
            F.lit("U2R"),
        )
        .when(
            (F.greatest(F.col("rerror_rate"), F.col("serror_rate")) > F.lit(0.5))
            & (F.col("count") > F.lit(50)),
            F.lit("DoS"),
        )
        .when(F.col("diff_srv_rate") > F.lit(0.5), F.lit("Probe"))
        .when(confidence > F.lit(0.4), F.lit("Probe"))
        .otherwise(F.lit("Normal"))
    )

    probability_map = F.map_from_entries(
        F.array(
            *[
                F.struct(
                    F.lit(name).alias("key"),
                    F.when(category == F.lit(name), confidence)
                    .when(F.lit(name) == F.lit("Normal"), F.lit(1.0) - confidence)
                    .otherwise(F.lit(0.0))
                    .alias("value"),
                )
                for name in ATTACK_CLASSES
            ]
        )
    )

    return events.select(
        "*",
        category.alias("predicted_category"),
        confidence.alias("confidence"),
        probability_map.alias("probabilities"),
        risk_score_expression(category, confidence).alias("risk_score"),
        F.when(category != F.lit("Normal"), F.lit(True)).otherwise(F.lit(False)).alias(
            "is_attack"
        ),
        F.lit(HEURISTIC_MODEL_NAME).alias("scoring_model"),
        F.lit(model_version).alias("scoring_version"),
    )


# =============================================================================
# Output shaping (SecurityEvent / Alert JSON contracts)
# =============================================================================


def build_security_events(scored: DataFrame) -> DataFrame:
    """Project the scored stream onto the ``SecurityEvent`` wire contract."""

    return scored.select(
        F.coalesce(F.col("event_id"), F.expr("uuid()")).alias("event_id"),
        F.col("event_id").alias("network_event_id"),
        _iso(F.col("timestamp")).alias("timestamp"),
        _iso(F.current_timestamp()).alias("predicted_at"),
        F.col("scoring_model").alias("model_name"),
        F.col("scoring_version").alias("model_version"),
        F.col("predicted_category"),
        F.col("attack_type"),
        F.col("is_attack"),
        F.round(F.col("confidence"), 6).alias("confidence"),
        F.col("risk_score"),
        F.col("probabilities"),
        F.col("source_host"),
        F.col("destination_host"),
        F.col("source_ip"),
        F.col("destination_ip"),
        F.round(
            (F.unix_timestamp(F.current_timestamp()) - F.unix_timestamp(F.col("timestamp")))
            * 1000.0,
            2,
        ).alias("latency_ms"),
    )


def build_alerts(events: DataFrame, *, threshold: float) -> DataFrame:
    """Derive ``Alert`` messages from attack events crossing the risk threshold."""

    attacks = events.where(F.col("is_attack") & (F.col("risk_score") >= F.lit(threshold)))
    title = F.concat_ws(
        " ",
        F.col("predicted_category"),
        F.lit("attack detected on"),
        F.coalesce(F.col("destination_host"), F.lit("unknown host")),
    )
    description = F.concat(
        F.lit("Spark streaming detection: "),
        F.col("predicted_category"),
        F.lit(" (confidence="),
        F.col("confidence").cast("string"),
        F.lit(", risk="),
        F.col("risk_score").cast("string"),
        F.lit(")."),
    )
    return attacks.select(
        F.expr("uuid()").alias("alert_id"),
        F.lower(F.col("predicted_category")).alias("alert_type"),
        title.alias("title"),
        description.alias("description"),
        severity_expression(F.col("risk_score")).alias("severity"),
        F.lit("open").alias("status"),
        F.col("risk_score"),
        F.col("source_host"),
        F.col("destination_host"),
        F.col("source_ip"),
        F.col("destination_ip"),
        F.array(F.col("network_event_id")).alias("related_event_ids"),
        F.struct(
            F.col("model_name"),
            F.col("model_version"),
            F.col("confidence"),
            F.col("attack_type"),
            F.lit("spark-structured-streaming").alias("source"),
        ).alias("evidence"),
        _iso(F.current_timestamp()).alias("created_at"),
    )


# =============================================================================
# Sinks
# =============================================================================

_KAFKA_COLUMNS = ("topic", "key", "value")


def _to_kafka_rows(frame: DataFrame, topic: str, key_column: str) -> DataFrame:
    """Shape a batch frame into (topic, key, value) Kafka rows."""

    return frame.select(
        F.lit(topic).alias("topic"),
        F.col(key_column).cast("string").alias("key"),
        F.to_json(F.struct(*[F.col(name) for name in frame.columns])).alias("value"),
    )


def _publish_kafka(rows: DataFrame, bootstrap_servers: str) -> None:
    """Send (topic, key, value) rows using one producer per partition, flushed at end."""

    if rows.rdd.isEmpty():
        return

    from kafka import KafkaProducer  # instantiated per executor task inside the closure

    def send_partition(partition: Iterable[Any]) -> None:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            key_serializer=lambda key: str(key).encode("utf-8") if key is not None else None,
            value_serializer=lambda value: str(value).encode("utf-8"),
            acks=1,
            linger_ms=50,
        )
        try:
            for topic, key, value in partition:
                producer.send(topic, key=key, value=value)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=10)

    rows.foreachPartition(send_partition)


def _write_postgres_batch(batch: DataFrame, dsn: str) -> None:
    """Persist prediction rows + per-batch system metrics (idempotent)."""

    import psycopg2
    from psycopg2.extras import Json

    records = batch.collect()
    if not records:
        return

    connection = psycopg2.connect(dsn, connect_timeout=10)
    try:
        with connection:
            with connection.cursor() as cursor:
                # FK-safe insert: rows are skipped while the event consumer
                # has not persisted the matching network_events row yet.
                cursor.executemany(
                    """
                    INSERT INTO predictions (
                        event_id, predicted_at, is_attack, attack_type,
                        confidence, probabilities, latency_ms, model_version_id
                    )
                    SELECT
                        e.id,
                        %s::timestamptz,
                        %s, %s, %s::numeric, %s::jsonb, %s::numeric,
                        (SELECT mv.id FROM model_versions mv
                          WHERE mv.model_name = %s AND mv.version = %s
                          LIMIT 1)
                    FROM network_events e
                    WHERE e.id = %s::uuid
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (
                            row["predicted_at"],
                            bool(row["is_attack"]),
                            str(row["predicted_category"]),
                            float(row["confidence"]),
                            Json(dict(row["probabilities"] or {})),
                            float(row["latency_ms"]) if row["latency_ms"] is not None else None,
                            str(row["model_name"]),
                            str(row["model_version"]),
                            str(row["network_event_id"]),
                        )
                        for row in records
                    ],
                )
                cursor.executemany(
                    """
                    INSERT INTO system_metrics (component, metric_name, metric_value, unit, host)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (COMPONENT, "batch_events_processed", float(len(records)), "count", JOB_NAME),
                        (
                            COMPONENT,
                            "batch_attacks_detected",
                            float(sum(1 for row in records if row["is_attack"])),
                            "count",
                            JOB_NAME,
                        ),
                        (
                            COMPONENT,
                            "batch_alerts_generated",
                            float(
                                sum(
                                    1
                                    for row in records
                                    if row["is_attack"] and float(row["risk_score"]) >= 0.0
                                )
                            ),
                            "count",
                            JOB_NAME,
                        ),
                    ],
                )
    finally:
        connection.close()


def make_detection_sink(
    *,
    bootstrap_servers: str,
    security_topic: str,
    alerts_topic: str,
    alert_threshold: float,
    postgres_dsn: str | None,
) -> Any:
    """Build the ``foreach_batch`` closure publishing one micro-batch everywhere."""

    def detection_sink(batch: DataFrame, batch_id: int) -> None:
        if batch.isEmpty():
            return

        events = _to_kafka_rows(batch, security_topic, "event_id")
        _publish_kafka(events, bootstrap_servers)

        alerts = build_alerts(batch, threshold=alert_threshold)
        alert_rows = _to_kafka_rows(alerts, alerts_topic, "alert_id")
        _publish_kafka(alert_rows, bootstrap_servers)

        if postgres_dsn:
            try:
                _write_postgres_batch(batch, postgres_dsn)
            except Exception as exc:  # noqa: BLE001 - DB outage must not kill stream
                logger.error("postgres_sink_failed", batch_id=batch_id, error=str(exc))

        logger.info(
            "batch_published",
            batch_id=batch_id,
            security_topic=security_topic,
            alerts_topic=alerts_topic,
        )

    return detection_sink


# =============================================================================
# Job assembly
# =============================================================================


def resolve_model_artifacts(models_dir: Path) -> tuple[str | None, list[str], str, str]:
    """Return ``(model_path, label_index, model_name, model_version)``.

    ``label_index`` comes from ``model_metadata.json`` when available; the
    canonical :data:`ATTACK_CLASSES` order is the documented fallback (the
    training pipeline indexes the most-frequent class, ``Normal``, first).
    """

    best_model = models_dir / "best_model"
    model_path = str(best_model) if best_model.exists() else None

    label_index = list(ATTACK_CLASSES)
    model_name = DEFAULT_MODEL_NAME
    model_version = DEFAULT_MODEL_VERSION
    metadata_path = models_dir / "model_metadata.json"
    if metadata_path.exists():
        try:
            metadata = read_json(metadata_path)
            if isinstance(metadata, dict):
                label_index = list(metadata.get("label_index") or label_index)
                model_name = str(metadata.get("model_name") or model_name)
                model_version = str(metadata.get("version") or model_version)
        except Exception as exc:  # noqa: BLE001 - metadata is advisory
            logger.warning("model_metadata_unreadable", path=str(metadata_path), error=str(exc))

    if model_path is None:
        logger.warning(
            "model_artifact_missing",
            path=str(best_model),
            hint="run `python ml/training/train_model.py`; using heuristic fallback",
        )
    return model_path, label_index, model_name, model_version


def run_job(
    *,
    bootstrap_servers: str,
    topic: str,
    security_topic: str,
    alerts_topic: str,
    group_id: str,
    starting_offsets: str,
    max_offsets_per_trigger: int,
    models_dir: Path,
    checkpoint_dir: Path,
    trigger_seconds: float,
    alert_threshold: float,
    postgres_dsn: str | None,
    master: str | None,
    await_termination: bool = True,
) -> Any:
    """Build and start the streaming query; returns the ``StreamingQuery``."""

    started = time.monotonic()
    spark = build_spark_session(
        "CyberShield-AI-AttackDetection",
        master=master,
        enable_kafka=True,
    )

    model_path, label_index, model_name, model_version = resolve_model_artifacts(models_dir)

    raw = read_kafka_stream(
        spark,
        bootstrap_servers=bootstrap_servers,
        topic=topic,
        group_id=group_id,
        starting_offsets=starting_offsets,
        max_offsets_per_trigger=max_offsets_per_trigger,
    )
    features = prepare_features(parse_events(raw, build_event_schema()))

    if model_path is not None:
        featurizer, classifier = split_pipeline(spark, model_path)
        scored = score_with_model(
            features,
            featurizer=featurizer,
            classifier=classifier,
            label_index=label_index,
            model_name=model_name,
            model_version=model_version,
        )
        logger.info("scoring_with_model", path=model_path, classes=label_index)
    else:
        scored = score_with_heuristic(features, model_version=model_version)
        logger.warning("scoring_with_heuristic", version=model_version)

    security_events = build_security_events(scored)

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    sink = make_detection_sink(
        bootstrap_servers=bootstrap_servers,
        security_topic=security_topic,
        alerts_topic=alerts_topic,
        alert_threshold=alert_threshold,
        postgres_dsn=postgres_dsn,
    )

    query = (
        security_events.writeStream.queryName(JOB_NAME)
        .outputMode("append")
        .option("checkpointLocation", str(checkpoint_dir / "detection"))
        .trigger(processingTime=f"{max(1, int(trigger_seconds))} seconds")
        .foreachBatch(sink)
        .start()
    )

    logger.info(
        "streaming_job_started",
        job=JOB_NAME,
        topic=topic,
        security_topic=security_topic,
        alerts_topic=alerts_topic,
        trigger_seconds=trigger_seconds,
        alert_threshold=alert_threshold,
        postgres=bool(postgres_dsn),
        scoring="model" if model_path is not None else "heuristic",
        setup_seconds=round(time.monotonic() - started, 2),
    )

    if await_termination:
        try:
            query.awaitTermination()
        except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
            query.stop()
            raise
    return query


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="attack_detection",
        description=(
            "Spark Structured Streaming attack detection "
            "(Kafka -> ML pipeline -> Kafka/PostgreSQL)."
        ),
    )
    parser.add_argument("--bootstrap-servers", default=None, help="Kafka brokers (default: env).")
    parser.add_argument("--topic", default=TOPIC_NETWORK_EVENTS, help="Input topic.")
    parser.add_argument("--security-topic", default=TOPIC_SECURITY_EVENTS)
    parser.add_argument("--alerts-topic", default=TOPIC_ALERTS)
    parser.add_argument("--group-id", default=None, help="Consumer group (env or default).")
    parser.add_argument(
        "--starting-offsets",
        default="latest",
        choices=("latest", "earliest"),
        help="Kafka offsets, honoured only for fresh checkpoints.",
    )
    parser.add_argument("--max-offsets-per-trigger", type=int, default=100_000)
    parser.add_argument(
        "--models-dir", default=None, help="Model artifact directory (default: ml/models)."
    )
    parser.add_argument("--checkpoint-dir", default=None, help="Streaming checkpoint dir.")
    parser.add_argument(
        "--trigger-seconds", type=float, default=5.0, help="Micro-batch processing interval."
    )
    parser.add_argument(
        "--alert-threshold", type=float, default=40.0, help="Minimum risk score to alert."
    )
    parser.add_argument(
        "--write-postgres",
        action="store_true",
        help="Also persist predictions + metrics to PostgreSQL (DATABASE_URL).",
    )
    parser.add_argument("--master", default=None, help="Spark master (default: env or local[*]).")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR.")
    parser.add_argument("--json-logs", action="store_true", help="Force JSON log output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    bootstrap = args.bootstrap_servers or env("SPARK_KAFKA_BOOTSTRAP") or kafka_bootstrap_servers()
    group = args.group_id or env("KAFKA_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP) or DEFAULT_CONSUMER_GROUP
    models_dir = Path(args.models_dir) if args.models_dir else DEFAULT_MODELS_DIR
    default_checkpoint = DEFAULT_MODELS_DIR.parent / "checkpoints"
    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else default_checkpoint
    checkpoint_dir = checkpoint_dir / JOB_NAME

    postgres_dsn = None
    if args.write_postgres:
        from streaming.settings import database_url

        postgres_dsn = database_url()

    try:
        run_job(
            bootstrap_servers=bootstrap,
            topic=args.topic,
            security_topic=args.security_topic,
            alerts_topic=args.alerts_topic,
            group_id=group,
            starting_offsets=args.starting_offsets,
            max_offsets_per_trigger=args.max_offsets_per_trigger,
            models_dir=models_dir,
            checkpoint_dir=checkpoint_dir,
            trigger_seconds=max(1.0, args.trigger_seconds),
            alert_threshold=args.alert_threshold,
            postgres_dsn=postgres_dsn,
            master=args.master,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.warning("streaming_job_interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.exception("streaming_job_failed", error=str(exc))
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
