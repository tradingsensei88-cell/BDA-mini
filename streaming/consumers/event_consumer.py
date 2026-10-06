"""CyberShield AI - Kafka consumer that validates and persists network events.

Reads JSON events from the ``network-events`` topic inside a consumer group,
validates every message against
:class:`~streaming.schemas.event_schema.NetworkEvent`, optionally persists
them into the PostgreSQL ``network_events`` table, and routes malformed
messages to a dead-letter topic (``network-events.dlq``).

Delivery semantics
------------------
* **At-least-once**: offsets are committed manually and only *after* the
  corresponding rows have been flushed to PostgreSQL (or immediately when DB
  persistence is disabled).
* Poison pills (undecodable/invalid JSON) are counted, logged, forwarded to
  the DLQ and skipped so they can never block the pipeline.
* Transient failures (broker blips, DB outages) are retried with exponential
  backoff; the DB buffer is capped to bound memory usage.

CLI examples::

    # consume forever, no database (schema validation only)
    python -m streaming.consumers.event_consumer --no-db

    # validate + persist into PostgreSQL, stop after 5000 messages
    python -m streaming.consumers.event_consumer --max-messages 5000
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.errors import KafkaError
from kafka.structs import OffsetAndMetadata
from pydantic import ValidationError

try:  # PostgreSQL is optional at import time; required for DB persistence.
    import psycopg2
    from psycopg2.extras import Json, execute_values, register_uuid

    _PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on local install
    psycopg2 = None  # type: ignore[assignment]
    Json = None  # type: ignore[assignment]
    execute_values = None  # type: ignore[assignment]
    register_uuid = None  # type: ignore[assignment]
    _PSYCOPG2_AVAILABLE = False

from streaming.logging_config import configure_logging, get_logger
from streaming.schemas.event_schema import (
    TOPIC_NETWORK_EVENTS,
    NetworkEvent,
    dlq_topic_name,
)
from streaming.settings import (
    consumer_group,
    database_url,
    env,
    kafka_bootstrap_servers,
    load_env,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_STOPPED = "stopped"

DEFAULT_BATCH_SIZE = 500
DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
DEFAULT_POLL_TIMEOUT_MS = 1_000
DEFAULT_MAX_POLL_RECORDS = 500

#: Sensor identifier stored on every persisted row.
SENSOR_ID = "nsl-kdd-simulator"

#: Average Ethernet payload used to derive packet counters from byte counts.
_BYTES_PER_PACKET = 1460


class ConsumerStartupError(RuntimeError):
    """Raised when the consumer cannot start (e.g. ``--require-db`` and no DB)."""


class ConsumerError(RuntimeError):
    """Raised when the poll loop encounters unrecoverable Kafka failures."""


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@dataclass
class ConsumerStats:
    """Thread-safe snapshot of consumer activity."""

    state: str = STATE_IDLE
    consumed_total: int = 0
    valid_total: int = 0
    invalid_total: int = 0
    persisted_total: int = 0
    skipped_total: int = 0
    dlq_total: int = 0
    commit_total: int = 0
    poll_errors: int = 0
    db_flush_errors: int = 0
    dropped_total: int = 0
    window_eps: float = 0.0
    per_partition: dict[str, int] = field(default_factory=dict)
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        uptime = 0.0
        if self.started_at is not None:
            uptime = max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())
        return {
            "state": self.state,
            "consumed_total": self.consumed_total,
            "valid_total": self.valid_total,
            "invalid_total": self.invalid_total,
            "persisted_total": self.persisted_total,
            "skipped_total": self.skipped_total,
            "dlq_total": self.dlq_total,
            "commit_total": self.commit_total,
            "poll_errors": self.poll_errors,
            "db_flush_errors": self.db_flush_errors,
            "dropped_total": self.dropped_total,
            "per_partition": dict(self.per_partition),
            "events_per_sec": round(self.window_eps, 2),
            "avg_events_per_sec": round(self.consumed_total / uptime, 2) if uptime > 0 else 0.0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "uptime_seconds": round(uptime, 1),
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# PostgreSQL writer
# ---------------------------------------------------------------------------


class PostgresEventWriter:
    """Buffered writer for the ``network_events`` table with retry logic.

    Rows are buffered in memory and flushed when ``batch_size`` is reached or
    ``flush_interval_seconds`` elapse. Failed flushes are retried with backoff
    and the buffer is capped at ``max_buffer`` rows (oldest rows are dropped,
    with the drop count tracked in ``dropped_total``).
    """

    INSERT_SQL = """
        INSERT INTO network_events (
            id, event_time, source_ip, destination_ip, source_port, destination_port,
            protocol, bytes_sent, bytes_received, packets_sent, packets_received,
            duration_ms, tcp_flags, hostname, sensor_id, raw_payload
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    def __init__(
        self,
        dsn: str,
        *,
        table: str = "network_events",
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        max_buffer: int = 10_000,
        connect_retries: int = 5,
        connect_timeout: int = 5,
        flush_retries: int = 3,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        if not _PSYCOPG2_AVAILABLE:
            raise ImportError(
                "psycopg2 is required for PostgreSQL persistence. "
                "Install it with: pip install psycopg2-binary"
            )
        self._dsn = dsn
        self._table = table
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self.max_buffer = max(100, int(max_buffer))
        self._connect_retries = max(1, int(connect_retries))
        self._connect_timeout = max(1, int(connect_timeout))
        self._flush_retries = max(1, int(flush_retries))
        self._backoff_base_seconds = max(0.05, float(backoff_base_seconds))

        self._connection: Any = None
        self._buffer: list[tuple[Any, ...]] = []
        self._last_flush = time.monotonic()

        #: Rows successfully persisted (cumulative).
        self.persisted_total = 0
        #: Rows dropped because the buffer cap was exceeded.
        self.dropped_total = 0

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    # ------------------------------------------------------------- lifecycle

    def connect(self) -> None:
        """Open the DB connection with retries; raises ``psycopg2.Error``."""

        last_error: Exception | None = None
        for attempt in range(1, self._connect_retries + 1):
            try:
                self._connection = psycopg2.connect(  # type: ignore[union-attr]
                    self._dsn, connect_timeout=self._connect_timeout
                )
                self._connection.autocommit = False
                register_uuid()  # type: ignore[misc]
                logger.info("db_connected", attempt=attempt)
                return
            except psycopg2.Error as exc:  # type: ignore[union-attr]
                last_error = exc
                logger.warning(
                    "db_connect_retry",
                    attempt=attempt,
                    max_attempts=self._connect_retries,
                    error=str(exc).strip(),
                )
                time.sleep(self._backoff_base_seconds * attempt)
        raise last_error if last_error is not None else RuntimeError("DB connection failed")

    def add(self, row: tuple[Any, ...]) -> None:
        """Buffer a row for the next flush."""

        self._buffer.append(row)

    def maybe_flush(self) -> bool:
        """Flush when the batch size or flush interval threshold is reached."""

        due_by_size = len(self._buffer) >= self.batch_size
        due_by_time = (
            self._buffer and (time.monotonic() - self._last_flush) >= self.flush_interval_seconds
        )
        if due_by_size or due_by_time:
            return self.flush()
        return False

    def flush(self) -> bool:
        """Persist buffered rows; returns ``True`` when a flush happened."""

        if not self._buffer:
            return False

        rows = self._buffer
        self._buffer = []
        last_error: Exception | None = None

        for attempt in range(1, self._flush_retries + 1):
            try:
                if self._connection is None or self._connection.closed:
                    self._connect_once()
                with self._connection.cursor() as cursor:
                    execute_values(  # type: ignore[misc]
                        cursor, self.INSERT_SQL, rows, page_size=max(1, len(rows))
                    )
                self._connection.commit()
                self.persisted_total += len(rows)
                self._last_flush = time.monotonic()
                logger.info(
                    "db_flush_ok",
                    rows=len(rows),
                    persisted_total=self.persisted_total,
                    attempt=attempt,
                )
                return True
            except psycopg2.Error as exc:  # type: ignore[union-attr]
                last_error = exc
                self._close_connection_quietly()
                logger.warning(
                    "db_flush_retry",
                    attempt=attempt,
                    max_attempts=self._flush_retries,
                    error=str(exc).strip(),
                )
                time.sleep(self._backoff_base_seconds * attempt)

        # All attempts failed: requeue in original order and cap the buffer.
        self._buffer = rows + self._buffer
        dropped = self._enforce_buffer_cap()
        if dropped:
            logger.warning(
                "db_buffer_overflow",
                dropped_rows=dropped,
                dropped_total=self.dropped_total,
                buffered=self.buffered,
            )
        logger.error(
            "db_flush_failed",
            rows=len(rows),
            buffered=self.buffered,
            error=str(last_error).strip() if last_error else "unknown",
        )
        return False

    def close(self) -> None:
        """Best-effort final flush and connection teardown."""

        try:
            if self._buffer:
                self.flush()
        finally:
            self._close_connection_quietly()

    # -------------------------------------------------------------- internal

    def _connect_once(self) -> None:
        self._connection = psycopg2.connect(  # type: ignore[union-attr]
            self._dsn, connect_timeout=self._connect_timeout
        )
        self._connection.autocommit = False
        register_uuid()  # type: ignore[misc]

    def _close_connection_quietly(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._connection = None

    def _enforce_buffer_cap(self) -> int:
        excess = len(self._buffer) - self.max_buffer
        if excess <= 0:
            return 0
        del self._buffer[:excess]
        self.dropped_total += excess
        return excess


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _estimate_packets(num_bytes: int) -> int:
    """Derive a rough packet count from a byte count (payload/1460)."""

    if num_bytes <= 0:
        return 0
    return max(1, math.ceil(num_bytes / _BYTES_PER_PACKET))


def event_to_db_row(event: NetworkEvent) -> tuple[Any, ...] | None:
    """Map a :class:`NetworkEvent` onto a ``network_events`` row.

    Returns ``None`` when the event has no usable IP addresses (the table
    requires ``source_ip``/``destination_ip``).
    """

    if event.source_ip is None or event.destination_ip is None:
        return None

    raw_payload = event.model_dump(mode="json")
    bytes_sent = int(event.src_bytes)
    bytes_received = int(event.dst_bytes)

    return (
        str(event.event_id),
        event.timestamp,
        str(event.source_ip),
        str(event.destination_ip),
        event.source_port,
        event.destination_port,
        event.protocol_type.upper()[:16],
        bytes_sent,
        bytes_received,
        _estimate_packets(bytes_sent),
        _estimate_packets(bytes_received),
        int(event.duration * 1000),
        event.flag,
        event.source_host,
        SENSOR_ID,
        Json(raw_payload),  # type: ignore[misc]
    )


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class EventConsumer:
    """Validating Kafka consumer with optional PostgreSQL persistence."""

    def __init__(
        self,
        *,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
        group_id: str | None = None,
        auto_offset_reset: str | None = None,
        write_to_db: bool = True,
        require_db: bool = False,
        database_dsn: str | None = None,
        dlq_topic: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        poll_timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS,
        max_poll_records: int = DEFAULT_MAX_POLL_RECORDS,
        max_consecutive_poll_errors: int = 20,
    ) -> None:
        self.bootstrap_servers = bootstrap_servers or kafka_bootstrap_servers()
        self.topic = topic or TOPIC_NETWORK_EVENTS
        self.group_id = group_id or consumer_group()
        self.auto_offset_reset = auto_offset_reset or env(
            "KAFKA_AUTO_OFFSET_RESET", "earliest"
        )
        self.write_to_db = bool(write_to_db)
        self.require_db = bool(require_db)
        self.poll_timeout_ms = max(100, int(poll_timeout_ms))
        self.max_poll_records = max(1, int(max_poll_records))
        self.max_consecutive_poll_errors = max(1, int(max_consecutive_poll_errors))

        #: DLQ topic; ``None`` disables dead-letter routing.
        self.dlq_topic = dlq_topic if dlq_topic is not None else dlq_topic_name(self.topic)

        self._database_dsn = database_dsn or database_url()
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_seconds

        self._consumer: KafkaConsumer | None = None
        self._dlq_producer: KafkaProducer | None = None
        self._dlq_disabled = False
        self._writer: PostgresEventWriter | None = None
        self._writer_drop_marker = 0

        self._stop_event = threading.Event()
        self._pending_offsets: dict[TopicPartition, int] = {}
        self._stats = ConsumerStats()

    # ------------------------------------------------------------ properties

    @property
    def is_running(self) -> bool:
        return self._stats.state == STATE_RUNNING

    # -------------------------------------------------------------- lifecycle

    def run(
        self,
        *,
        max_messages: int | None = None,
        duration: float | None = None,
    ) -> int:
        """Blocking consume loop.

        Args:
            max_messages: Stop after consuming this many messages.
            duration: Stop after this many seconds.

        Returns:
            The number of messages consumed in this run.

        Raises:
            ConsumerStartupError: ``require_db`` is set but the DB is unreachable.
            ConsumerError: The broker repeatedly failed to serve polls.
        """

        self._stop_event.clear()
        self._stats = ConsumerStats(state=STATE_RUNNING, started_at=datetime.now(timezone.utc))
        self._consumer = self._create_consumer()
        self._setup_writer()

        self._consumer.subscribe([self.topic])
        self._wait_for_topic(timeout=30.0)

        started = time.monotonic()
        window_start = started
        window_count = 0
        processed = 0
        consecutive_poll_errors = 0

        try:
            while not self._stop_event.is_set():
                if duration is not None and (time.monotonic() - started) >= duration:
                    logger.info("consumer_duration_reached", duration_seconds=duration)
                    break

                try:
                    batches = self._consumer.poll(
                        timeout_ms=self.poll_timeout_ms,
                        max_records=self.max_poll_records,
                    )
                    consecutive_poll_errors = 0
                except KafkaError as exc:
                    consecutive_poll_errors += 1
                    self._stats.poll_errors += 1
                    self._stats.last_error = str(exc)
                    logger.warning(
                        "consumer_poll_failed",
                        consecutive_errors=consecutive_poll_errors,
                        error=str(exc),
                    )
                    if consecutive_poll_errors >= self.max_consecutive_poll_errors:
                        raise ConsumerError(
                            f"Kafka poll failed {consecutive_poll_errors} consecutive "
                            f"times: {exc}"
                        ) from exc
                    time.sleep(min(2.0 * consecutive_poll_errors, 10.0))
                    continue

                done_early = False
                for topic_partition, records in batches.items():
                    for record in records:
                        self._process_record(record, topic_partition)
                        processed += 1
                        window_count += 1
                        if max_messages is not None and processed >= max_messages:
                            done_early = True
                            break
                    if done_early:
                        break

                # -- flush + commit (at-least-once) ---------------------------
                flushed = self._writer.maybe_flush() if self._writer is not None else False
                if self._writer is None or flushed:
                    self._commit_pending()
                self._sync_writer_stats()

                # -- rolling events/sec ---------------------------------------
                now = time.monotonic()
                if now - window_start >= 1.0:
                    self._stats.window_eps = window_count / (now - window_start)
                    window_count = 0
                    window_start = now

                if done_early:
                    logger.info("consumer_message_limit_reached", max_messages=max_messages)
                    break

        except KeyboardInterrupt:  # pragma: no cover - interactive safety net
            logger.info("consumer_interrupted")
        finally:
            self._shutdown()

        logger.info("consumer_summary", **self.get_stats())
        return processed

    def stop(self) -> None:
        """Request a graceful shutdown (returns once the loop notices)."""

        self._stop_event.set()

    def get_stats(self) -> dict[str, Any]:
        """Return a JSON-friendly statistics snapshot."""

        snapshot = self._stats.to_dict()
        snapshot.update(
            {
                "topic": self.topic,
                "group_id": self.group_id,
                "bootstrap_servers": self.bootstrap_servers,
                "auto_offset_reset": self.auto_offset_reset,
                "db_enabled": self._writer is not None,
                "db_buffered": self._writer.buffered if self._writer else 0,
                "dlq_topic": self.dlq_topic if not self._dlq_disabled else None,
            }
        )
        return snapshot

    # --------------------------------------------------------------- internal

    def _create_consumer(self) -> KafkaConsumer:
        consumer = KafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            client_id="cybershield-event-consumer",
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=False,
            max_poll_records=self.max_poll_records,
        )
        logger.info(
            "consumer_created",
            bootstrap_servers=self.bootstrap_servers,
            topic=self.topic,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
        )
        return consumer

    def _setup_writer(self) -> None:
        """Connect the PostgreSQL writer; degrade gracefully unless required."""

        if not self.write_to_db:
            logger.info("consumer_db_disabled")
            return
        if not _PSYCOPG2_AVAILABLE:
            message = "psycopg2 not installed - run `pip install psycopg2-binary`"
            if self.require_db:
                raise ConsumerStartupError(message)
            logger.warning("consumer_db_unavailable", reason=message)
            return

        writer = PostgresEventWriter(
            self._database_dsn,
            batch_size=self._batch_size,
            flush_interval_seconds=self._flush_interval_seconds,
        )
        try:
            writer.connect()
        except Exception as exc:  # noqa: BLE001 - degrade unless required
            if self.require_db:
                raise ConsumerStartupError(f"PostgreSQL unreachable: {exc}") from exc
            logger.error(
                "consumer_db_connect_failed",
                error=str(exc).strip(),
                note="continuing without PostgreSQL persistence",
            )
            return
        self._writer = writer

    def _wait_for_topic(self, timeout: float) -> bool:
        """Wait until the topic metadata is visible (fresh stacks)."""

        assert self._consumer is not None
        deadline = time.monotonic() + timeout
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                if self.topic in self._consumer.topics():
                    logger.info("consumer_topic_ready", topic=self.topic)
                    return True
            except KafkaError as exc:
                logger.warning("consumer_topic_probe_failed", error=str(exc))
            time.sleep(2.0)
        logger.warning("consumer_topic_not_ready", topic=self.topic, timeout=timeout)
        return False

    def _process_record(self, record: Any, topic_partition: TopicPartition) -> None:
        """Validate + optionally persist a single Kafka record."""

        self._stats.consumed_total += 1
        self._stats.last_event_at = datetime.now(timezone.utc)
        partition_key = f"{topic_partition.topic}-{topic_partition.partition}"
        self._stats.per_partition[partition_key] = (
            self._stats.per_partition.get(partition_key, 0) + 1
        )

        event, error = self._decode_event(record.value)
        if event is None:
            self._stats.invalid_total += 1
            self._handle_poison_pill(record, error)
        else:
            self._stats.valid_total += 1
            if self._writer is not None:
                row = event_to_db_row(event)
                if row is None:
                    self._stats.skipped_total += 1
                    if self._stats.skipped_total <= 3 or self._stats.skipped_total % 1000 == 0:
                        logger.warning(
                            "consumer_event_skipped",
                            reason="missing source/destination IP",
                            event_id=str(event.event_id),
                        )
                else:
                    self._writer.add(row)

        # Track the highest processed offset per partition for manual commit.
        committed_offset = record.offset + 1
        current = self._pending_offsets.get(topic_partition, -1)
        if committed_offset > current:
            self._pending_offsets[topic_partition] = committed_offset

    @staticmethod
    def _decode_event(raw: Any) -> tuple[NetworkEvent | None, Exception | None]:
        """Decode + validate a raw Kafka payload; returns (event, error)."""

        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
            return NetworkEvent.model_validate(payload), None
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            return None, exc

    def _handle_poison_pill(self, record: Any, error: Exception | None) -> None:
        """Count, log and (optionally) dead-letter an invalid message."""

        if self._stats.invalid_total <= 5 or self._stats.invalid_total % 100 == 0:
            logger.warning(
                "consumer_invalid_message",
                partition=record.partition,
                offset=record.offset,
                error=f"{type(error).__name__}: {error}" if error else "unknown",
            )

        if self.dlq_topic is None or self._dlq_disabled:
            return

        producer = self._ensure_dlq_producer()
        if producer is None:
            return

        try:
            payload_text = (
                record.value.decode("utf-8", errors="replace")
                if isinstance(record.value, (bytes, bytearray))
                else str(record.value)
            )
            producer.send(
                self.dlq_topic,
                value={
                    "source_topic": self.topic,
                    "partition": record.partition,
                    "offset": record.offset,
                    "error": f"{type(error).__name__}: {error}" if error else "unknown",
                    "payload": payload_text[:8192],
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self._stats.dlq_total += 1
        except KafkaError as exc:
            logger.warning("consumer_dlq_send_failed", error=str(exc))

    def _ensure_dlq_producer(self) -> KafkaProducer | None:
        if self._dlq_producer is not None:
            return self._dlq_producer
        try:
            self._dlq_producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id="cybershield-event-consumer-dlq",
                acks=1,
                retries=3,
                request_timeout_ms=10_000,
                max_block_ms=10_000,
                value_serializer=lambda value: json.dumps(
                    value, separators=(",", ":"), default=str
                ).encode("utf-8"),
            )
            logger.info("consumer_dlq_ready", dlq_topic=self.dlq_topic)
        except KafkaError as exc:
            self._dlq_disabled = True
            logger.warning("consumer_dlq_disabled", error=str(exc))
            return None
        return self._dlq_producer

    def _commit_pending(self) -> bool:
        """Commit tracked offsets synchronously (with retries)."""

        if self._consumer is None or not self._pending_offsets:
            return False

        offsets = {
            topic_partition: OffsetAndMetadata(offset, None)
            for topic_partition, offset in self._pending_offsets.items()
        }
        for attempt in range(1, 4):
            try:
                self._consumer.commit(offsets=offsets)
                self._stats.commit_total += len(self._pending_offsets)
                self._pending_offsets.clear()
                logger.debug("consumer_offsets_committed", partitions=len(offsets))
                return True
            except KafkaError as exc:
                self._stats.last_error = str(exc)
                logger.warning(
                    "consumer_commit_retry",
                    attempt=attempt,
                    error=str(exc),
                )
                time.sleep(0.5 * attempt)
        logger.error("consumer_commit_failed", partitions=len(offsets))
        return False

    def _sync_writer_stats(self) -> None:
        """Mirror writer counters (persisted/dropped) into consumer stats."""

        if self._writer is None:
            return
        self._stats.persisted_total = self._writer.persisted_total
        if self._writer.dropped_total > self._writer_drop_marker:
            self._stats.dropped_total = self._writer.dropped_total
            self._writer_drop_marker = self._writer.dropped_total

    def _shutdown(self) -> None:
        """Flush pending rows, commit offsets and close every client."""

        try:
            if self._writer is not None:
                if self._writer.flush():
                    self._commit_pending()
                self._sync_writer_stats()
                self._writer.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            logger.warning("consumer_writer_shutdown_failed", error=str(exc))

        try:
            if self._consumer is not None:
                self._consumer.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("consumer_close_failed", error=str(exc))

        try:
            if self._dlq_producer is not None:
                self._dlq_producer.flush(timeout=5.0)
                self._dlq_producer.close(timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("consumer_dlq_close_failed", error=str(exc))

        self._stats.state = STATE_STOPPED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="event_consumer",
        description="Consume + validate `network-events`, persist to PostgreSQL (optional).",
    )
    parser.add_argument("--topic", default=TOPIC_NETWORK_EVENTS, help="Source Kafka topic.")
    parser.add_argument("--group-id", default=None, help="Consumer group id.")
    parser.add_argument("--bootstrap", default=None, help="Kafka bootstrap servers.")
    parser.add_argument("--auto-offset-reset", choices=["earliest", "latest"], default=None)
    parser.add_argument("--db-url", default=None, help="PostgreSQL DSN (DATABASE_URL).")
    parser.add_argument("--no-db", action="store_true", help="Disable PostgreSQL persistence.")
    parser.add_argument("--require-db", action="store_true", help="Fail fast if DB is down.")
    parser.add_argument("--no-dlq", action="store_true", help="Disable the dead-letter topic.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--flush-interval", type=float, default=DEFAULT_FLUSH_INTERVAL_SECONDS)
    parser.add_argument("--poll-timeout-ms", type=int, default=DEFAULT_POLL_TIMEOUT_MS)
    parser.add_argument("--max-messages", type=int, default=None, help="Stop after N messages.")
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds.")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR.")
    parser.add_argument("--json-logs", action="store_true", help="Force JSON log output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    consumer = EventConsumer(
        bootstrap_servers=args.bootstrap,
        topic=args.topic,
        group_id=args.group_id,
        auto_offset_reset=args.auto_offset_reset,
        write_to_db=not args.no_db,
        require_db=args.require_db,
        database_dsn=args.db_url,
        dlq_topic=None if args.no_dlq else dlq_topic_name(args.topic),
        batch_size=args.batch_size,
        flush_interval_seconds=args.flush_interval,
        poll_timeout_ms=args.poll_timeout_ms,
    )

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("consumer_shutdown_signal", signal=signum)
        consumer.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError, AttributeError):  # pragma: no cover - platform specific
            pass

    try:
        consumer.run(max_messages=args.max_messages, duration=args.duration)
    except ConsumerStartupError as exc:
        logger.error("consumer_startup_failed", error=str(exc))
        return 2
    except ConsumerError as exc:
        logger.error("consumer_failed", error=str(exc))
        return 3

    logger.info("consumer_summary", **consumer.get_stats())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
