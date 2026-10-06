"""CyberShield AI - Kafka event producer / network traffic simulator.

Replays the NSL-KDD dataset as a live network traffic stream, publishing one
JSON event per record to the ``network-events`` Kafka topic at a configurable
rate (10 / 100 / 500 / 1000 events per second by default).

Features
--------
* Loads + preprocesses the dataset through :class:`~streaming.producers.dataset_adapter.NSLKDDAdapter`.
* Thread-safe lifecycle: :meth:`~EventProducer.start`,
  :meth:`~EventProducer.pause`, :meth:`~EventProducer.resume`,
  :meth:`~EventProducer.reset`, :meth:`~EventProducer.set_rate`,
  :meth:`~EventProducer.stop`.
* Tick-based pacing (50 ms ticks with a fractional accumulator) so low rates
  such as 10 ev/s and high rates such as 1000 ev/s are equally accurate.
* Schema validation of every event against
  :class:`~streaming.schemas.event_schema.NetworkEvent` before publishing.
* Connection handling with retries + exponential backoff; the topic is
  created automatically when missing.
* Run statistics: totals, per-second rate, per-category attack breakdown.

CLI examples::

    # rehearse without Kafka (prints through the loopback path at 100 ev/s)
    python -m streaming.producers.event_producer --rate 100 --dry-run --count 200

    # publish 60 seconds of traffic at 500 ev/s against a local stack
    python -m streaming.producers.event_producer --rate 500 --duration 60
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kafka import KafkaProducer
from kafka.errors import KafkaError

from streaming.logging_config import configure_logging, get_logger
from streaming.producers.dataset_adapter import NSLKDDAdapter
from streaming.schemas.event_schema import (
    TOPIC_NETWORK_EVENTS,
    AttackCategory,
    NetworkEvent,
)
from streaming.settings import (
    kafka_bootstrap_servers,
    kafka_network_events_topic,
    load_env,
    resolve_dataset_path,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Event rates advertised by the simulator and exposed through the CLI.
PUBLISH_RATE_PRESETS: tuple[int, ...] = (10, 100, 500, 1000)

DEFAULT_RATE: int = 100
MAX_RATE: int = 10_000
MIN_RATE: int = 1

#: Pacing tick. Each tick emits ``rate * _TICK_SECONDS`` events (fractional
#: values accumulate across ticks so slow rates stay accurate).
_TICK_SECONDS: float = 0.05

#: Consecutive send failures tolerated before the producer aborts.
_MAX_CONSECUTIVE_SEND_ERRORS: int = 100

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_STOPPED = "stopped"


class ProducerConnectionError(RuntimeError):
    """Raised when the Kafka broker cannot be reached after all retries."""


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@dataclass
class ProducerStats:
    """Thread-safe snapshot of producer activity (mutated under the lock)."""

    state: str = STATE_IDLE
    rate: int = DEFAULT_RATE
    total_events: int = 0
    delivered_events: int = 0
    delivery_errors: int = 0
    send_errors: int = 0
    normal_count: int = 0
    attack_counts: dict[str, int] = field(default_factory=dict)
    dataset_size: int = 0
    loops_completed: int = 0
    window_eps: float = 0.0
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    last_error: str | None = None

    @property
    def attack_count(self) -> int:
        return int(sum(self.attack_counts.values()))

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot with all five categories always present."""

        categories = {category.value: 0 for category in AttackCategory}
        categories.update(self.attack_counts)

        uptime = 0.0
        if self.started_at is not None:
            uptime = max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())

        return {
            "state": self.state,
            "rate": self.rate,
            "total_events": self.total_events,
            "delivered_events": self.delivered_events,
            "delivery_errors": self.delivery_errors,
            "send_errors": self.send_errors,
            "normal_count": self.normal_count,
            "attack_count": self.attack_count,
            "attack_counts": categories,
            "dataset_size": self.dataset_size,
            "loops_completed": self.loops_completed,
            "events_per_sec": round(self.window_eps, 2),
            "avg_events_per_sec": round(self.total_events / uptime, 2) if uptime > 0 else 0.0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "uptime_seconds": round(uptime, 1),
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


class EventProducer:
    """Dataset-backed Kafka producer with pause/resume/rate controls."""

    def __init__(
        self,
        *,
        dataset_path: str | Path | None = None,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
        rate: int = DEFAULT_RATE,
        loop: bool = True,
        seed: int | None = None,
        host_count: int = 100,
        validate_events: bool = True,
        dry_run: bool = False,
        shuffle_events: bool = True,
        chunk_size: int = 2048,
        connect_retries: int = 5,
        connect_backoff_seconds: float = 3.0,
    ) -> None:
        """Configure the simulator (no I/O happens until :meth:`start`).

        Args:
            dataset_path: NSL-KDD file; auto-resolved from ``data/raw`` when
                omitted.
            bootstrap_servers: Kafka bootstrap servers; defaults to
                ``KAFKA_BOOTSTRAP_SERVERS`` / ``localhost:29092``.
            topic: Target topic; defaults to ``network-events``.
            rate: Initial event rate in events/second.
            loop: Restart from the beginning when the dataset is exhausted.
            seed: Seed for deterministic synthetic fields.
            host_count: Size of the synthetic host pool.
            validate_events: Validate every payload against ``NetworkEvent``.
            dry_run: Skip Kafka entirely (loopback mode for testing).
            shuffle_events: Shuffle the dataset once after loading.
            chunk_size: Conversion chunk size used by the adapter iterator.
            connect_retries: Broker connection attempts before failing.
            connect_backoff_seconds: Base delay between connection attempts.
        """

        self._dataset_path = dataset_path
        self.bootstrap_servers = bootstrap_servers or kafka_bootstrap_servers()
        self.topic = topic or kafka_network_events_topic()
        self.dry_run = bool(dry_run)
        self._loop = bool(loop)
        self._seed = int(seed) if seed is not None else 42
        self._validate_events = bool(validate_events)
        self._shuffle_events = bool(shuffle_events)
        self._chunk_size = max(256, int(chunk_size))
        self._connect_retries = max(1, int(connect_retries))
        self._connect_backoff_seconds = max(0.1, float(connect_backoff_seconds))

        self._adapter = NSLKDDAdapter(seed=self._seed, host_count=host_count)

        self._lock = threading.RLock()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._frame = None
        self._iterator: Iterator[dict[str, Any]] | None = None
        self._buffer: deque[dict[str, Any]] = deque()
        self._kafka: KafkaProducer | None = None
        self._kafka_closed = False
        self._consecutive_send_errors = 0

        validated_rate = self._validate_rate(rate)
        self._stats = ProducerStats(rate=validated_rate)

    # ------------------------------------------------------------ properties

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    # -------------------------------------------------------------- lifecycle

    def start(
        self,
        *,
        duration: float | None = None,
        max_events: int | None = None,
        block: bool = True,
    ) -> bool:
        """Start publishing.

        Args:
            duration: Stop automatically after this many seconds.
            max_events: Stop automatically after this many events.
            block: When ``True`` (default) wait for the run to finish.

        Returns:
            ``True`` if a new run was started, ``False`` if already running.

        Raises:
            ProducerConnectionError: Broker unreachable (not raised in dry-run).
            FileNotFoundError: No dataset file could be resolved.
        """

        with self._lock:
            if self.is_running:
                logger.warning("producer_already_running")
                return False
            self._stop_event.clear()
            self._resume_event.set()

        self._ensure_ready()

        thread = threading.Thread(
            target=self._run,
            kwargs={"duration": duration, "max_events": max_events},
            name="cybershield-event-producer",
            daemon=True,
        )
        with self._lock:
            self._thread = thread
        thread.start()

        if block:
            thread.join()
        return True

    def pause(self) -> bool:
        """Temporarily stop emitting (in-flight sends are unaffected)."""

        with self._lock:
            if not self.is_running or self.is_paused:
                return False
            self._resume_event.clear()
            self._stats.state = STATE_PAUSED
        logger.info("producer_paused", total_events=self._stats.total_events)
        return True

    def resume(self) -> bool:
        """Resume emitting after :meth:`pause`."""

        with self._lock:
            if not self.is_running or not self.is_paused:
                return False
            self._resume_event.set()
            self._stats.state = STATE_RUNNING
        logger.info("producer_resumed", rate=self._stats.rate)
        return True

    def stop(self, timeout: float = 10.0) -> None:
        """Stop publishing, flush pending messages and close the client."""

        self._stop_event.set()
        self._resume_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._close_kafka(timeout=timeout)
        with self._lock:
            self._stats.state = STATE_STOPPED
        logger.info("producer_stopped", **self.get_stats())

    def reset(self) -> bool:
        """Rewind the dataset and zero the statistics.

        Keeps the previous run state: if the producer was running it is
        restarted against a fresh iterator after the reset.
        """

        was_running = self.is_running
        if was_running:
            self._stop_event.set()
            thread = self._thread
            if thread is not None:
                thread.join(timeout=5.0)

        with self._lock:
            self._buffer.clear()
            self._iterator = None
            self._consecutive_send_errors = 0
            rate = self._stats.rate
            dataset_size = self._stats.dataset_size
            self._stats = ProducerStats(
                state=STATE_IDLE, rate=rate, dataset_size=dataset_size
            )
            self._stop_event.clear()
            self._resume_event.set()
        logger.info("producer_reset", dataset_size=dataset_size)

        if was_running:
            self.start(block=False)
        return True

    def set_rate(self, rate: int) -> int:
        """Change the publishing rate (events/second); returns the new rate."""

        validated = self._validate_rate(rate)
        with self._lock:
            self._stats.rate = validated
        logger.info("producer_rate_updated", rate=validated)
        return validated

    def get_stats(self) -> dict[str, Any]:
        """Return a JSON-friendly statistics snapshot."""

        with self._lock:
            snapshot = self._stats.to_dict()
        snapshot["topic"] = self.topic
        snapshot["bootstrap_servers"] = self.bootstrap_servers
        snapshot["dry_run"] = self.dry_run
        return snapshot

    # --------------------------------------------------------------- internal

    @staticmethod
    def _validate_rate(rate: int) -> int:
        value = int(rate)
        if value < MIN_RATE or value > MAX_RATE:
            raise ValueError(
                f"rate must be between {MIN_RATE} and {MAX_RATE} events/sec, got {value}"
            )
        return value

    def _current_rate(self) -> int:
        with self._lock:
            return self._stats.rate

    def _ensure_ready(self) -> None:
        """Load the dataset and connect to Kafka (idempotent)."""

        if self._frame is None:
            path = resolve_dataset_path(self._dataset_path)
            raw = self._adapter.load_dataset(path)
            frame = self._adapter.preprocess(raw)
            if self._shuffle_events and len(frame) > 1:
                frame = frame.sample(frac=1.0, random_state=self._seed).reset_index(drop=True)
            self._frame = frame
            self._iterator = None
            self._buffer.clear()
            with self._lock:
                self._stats.dataset_size = int(len(frame))
            logger.info(
                "producer_dataset_ready",
                path=str(path),
                rows=int(len(frame)),
                summary=self._adapter.summary(frame),
            )

        if not self.dry_run and self._kafka is None:
            self._kafka = self._create_kafka_producer()
            self._kafka_closed = False

    def _create_kafka_producer(self) -> KafkaProducer:
        """Create a KafkaProducer with retries + backoff."""

        config: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "client_id": "cybershield-event-producer",
            "acks": 1,
            "retries": 5,
            "retry_backoff_ms": 200,
            "request_timeout_ms": 15_000,
            "max_block_ms": 15_000,
            "linger_ms": 10,
            "key_serializer": lambda key: str(key).encode("utf-8"),
            "value_serializer": _json_serializer,
        }

        last_error: Exception | None = None
        for attempt in range(1, self._connect_retries + 1):
            try:
                producer = KafkaProducer(**config)
                partitions = producer.partitions_for(self.topic)
                if not partitions:
                    raise ProducerConnectionError(
                        f"topic {self.topic!r} metadata not available yet"
                    )
                logger.info(
                    "producer_kafka_connected",
                    bootstrap_servers=self.bootstrap_servers,
                    topic=self.topic,
                    partitions=len(partitions),
                    attempt=attempt,
                )
                self._ensure_topic_exists()
                return producer
            except ProducerConnectionError:
                raise
            except KafkaError as exc:
                last_error = exc
                logger.warning(
                    "producer_kafka_connect_retry",
                    attempt=attempt,
                    max_attempts=self._connect_retries,
                    bootstrap_servers=self.bootstrap_servers,
                    error=str(exc),
                )
                time.sleep(self._connect_backoff_seconds * attempt)

        raise ProducerConnectionError(
            f"Could not connect to Kafka at {self.bootstrap_servers!r} after "
            f"{self._connect_retries} attempts: {last_error}"
        )

    def _ensure_topic_exists(self) -> None:
        """Best-effort topic creation (non-fatal when the broker refuses)."""

        try:
            from kafka.admin import KafkaAdminClient, NewTopic
            from kafka.errors import TopicAlreadyExistsError

            admin = KafkaAdminClient(
                bootstrap_servers=self.bootstrap_servers,
                client_id="cybershield-event-producer-admin",
                request_timeout_ms=10_000,
            )
            try:
                admin.create_topics(
                    [NewTopic(name=self.topic, num_partitions=3, replication_factor=1)],
                    validate_only=False,
                )
                logger.info("producer_topic_created", topic=self.topic)
            except TopicAlreadyExistsError:
                pass
            finally:
                admin.close()
        except Exception as exc:  # noqa: BLE001 - non-fatal convenience only
            logger.warning("producer_topic_check_skipped", error=str(exc))

    # ------------------------------------------------------------- run loop

    def _run(self, duration: float | None, max_events: int | None) -> None:
        """Publishing loop executed on the worker thread."""

        with self._lock:
            self._stats.state = STATE_RUNNING
            self._stats.started_at = datetime.now(timezone.utc)

        started = time.monotonic()
        next_tick = started
        window_start = started
        accumulator = 0.0
        window_count = 0
        emitted_in_run = 0

        try:
            while not self._stop_event.is_set():
                # -- honour pause -----------------------------------------
                if not self._resume_event.is_set():
                    with self._lock:
                        self._stats.state = STATE_PAUSED
                    self._resume_event.wait(timeout=0.25)
                    accumulator = 0.0
                    next_tick = time.monotonic()
                    window_start = time.monotonic()
                    with self._lock:
                        self._stats.state = STATE_RUNNING
                    continue

                # -- duration / count guards --------------------------------
                if duration is not None and (time.monotonic() - started) >= duration:
                    logger.info("producer_duration_reached", duration_seconds=duration)
                    break
                if max_events is not None and emitted_in_run >= max_events:
                    logger.info("producer_event_count_reached", max_events=max_events)
                    break

                # -- emit one tick worth of events ---------------------------
                accumulator += self._current_rate() * _TICK_SECONDS
                to_send = int(accumulator)
                accumulator -= to_send

                normal_local = 0
                attack_local: dict[str, int] = {}
                attempted = 0
                exhausted = False

                for _ in range(to_send):
                    if self._stop_event.is_set():
                        break
                    # Honour pause at per-event granularity so at most one
                    # event lands after pause() returns (rather than a full
                    # tick worth of events at high rates).
                    if not self._resume_event.is_set():
                        break
                    if max_events is not None and emitted_in_run >= max_events:
                        break
                    event = self._next_event()
                    if event is None:
                        exhausted = True
                        break
                    self._publish(event)
                    attempted += 1
                    emitted_in_run += 1
                    category = str(event.get("attack_category", "Unknown"))
                    if category == AttackCategory.NORMAL.value:
                        normal_local += 1
                    else:
                        attack_local[category] = attack_local.get(category, 0) + 1

                # -- merge statistics -----------------------------------------
                if attempted:
                    now = time.monotonic()
                    window_count += attempted
                    with self._lock:
                        self._stats.total_events += attempted
                        self._stats.normal_count += normal_local
                        for category, count in attack_local.items():
                            self._stats.attack_counts[category] = (
                                self._stats.attack_counts.get(category, 0) + count
                            )
                        self._stats.last_event_at = datetime.now(timezone.utc)
                        if now - window_start >= 1.0:
                            self._stats.window_eps = window_count / (now - window_start)
                            window_count = 0
                            window_start = now

                if exhausted:
                    logger.info(
                        "producer_dataset_exhausted",
                        loops_completed=self._stats.loops_completed,
                        loop_enabled=self._loop,
                    )
                    break

                # -- pacing: sleep to the next tick, correcting drift --------
                next_tick += _TICK_SECONDS
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:  # fell behind (e.g. after a stall) - resync the clock
                    next_tick = time.monotonic()

        except Exception as exc:  # noqa: BLE001 - keep the thread from dying silently
            with self._lock:
                self._stats.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("producer_fatal_error", error=str(exc))
        finally:
            self._flush_and_close()
            with self._lock:
                if self._stats.state != STATE_STOPPED:
                    self._stats.state = STATE_STOPPED
            logger.info("producer_run_finished", **self.get_stats())

    def _next_event(self) -> dict[str, Any] | None:
        """Pop the next event from the buffer, refilling from the iterator."""

        with self._lock:
            if not self._buffer:
                self._refill_buffer()
                if not self._buffer:
                    return None
            return self._buffer.popleft()

    def _refill_buffer(self) -> None:
        """Pull the next events; rewinds when looping is enabled."""

        if self._frame is None:
            return
        if self._iterator is None:
            self._iterator = self._adapter.iter_events(self._frame, chunk_size=self._chunk_size)

        if self._drain_iterator():
            return

        if not self._loop:
            return

        self._stats.loops_completed += 1
        self._iterator = self._adapter.iter_events(self._frame, chunk_size=self._chunk_size)
        self._drain_iterator()

    def _drain_iterator(self) -> int:
        """Move up to ``_chunk_size`` events from the iterator into the buffer.

        ``NSLKDDAdapter.iter_events`` is a flat generator that yields
        individual event dictionaries (not lists of events), so the buffer is
        filled event by event until it holds at most one chunk. Returns the
        number of events drained (0 when the dataset is exhausted).
        """

        iterator = self._iterator
        if iterator is None:
            return 0
        drained = 0
        for event in iterator:
            self._buffer.append(event)
            drained += 1
            if drained >= self._chunk_size:
                break
        return drained

    def _publish(self, event: dict[str, Any]) -> None:
        """Validate and ship a single event (or log it in dry-run mode)."""

        payload: dict[str, Any] = event
        if self._validate_events:
            payload = NetworkEvent.model_validate(event).model_dump(mode="json")

        if self.dry_run:
            self._dry_run_event(payload)
            return

        producer = self._kafka
        if producer is None:
            raise ProducerConnectionError("Kafka producer not initialised")

        try:
            future = producer.send(self.topic, key=payload.get("source_host"), value=payload)
            future.add_callback(self._on_delivery_success)
            future.add_errback(self._on_delivery_error)
            self._consecutive_send_errors = 0
        except KafkaError as exc:
            with self._lock:
                self._stats.send_errors += 1
                self._stats.last_error = str(exc)
            self._consecutive_send_errors += 1
            if self._consecutive_send_errors in (1, 10, 50) or (
                self._consecutive_send_errors % 100 == 0
            ):
                logger.warning(
                    "producer_send_failed",
                    consecutive_errors=self._consecutive_send_errors,
                    error=str(exc),
                )
            if self._consecutive_send_errors >= _MAX_CONSECUTIVE_SEND_ERRORS:
                with self._lock:
                    self._stats.last_error = (
                        f"aborting after {self._consecutive_send_errors} consecutive "
                        f"send failures: {exc}"
                    )
                self._stop_event.set()

    def _dry_run_event(self, payload: dict[str, Any]) -> None:
        """Dry-run sink: exposes the sample on the wire and logs sparsely."""

        with self._lock:
            self._stats.delivered_events += 1
            total = self._stats.total_events + 1  # pre-merge approximation for logging
        if total <= 3 or total % 500 == 0:
            logger.info(
                "producer_dry_run_event",
                event_id=str(payload.get("event_id")),
                attack_category=payload.get("attack_category"),
                source_host=payload.get("source_host"),
                note="dry-run: event not sent to Kafka",
            )

    def _on_delivery_success(self, metadata: Any) -> None:
        with self._lock:
            self._stats.delivered_events += 1

    def _on_delivery_error(self, exc: BaseException) -> None:
        with self._lock:
            self._stats.delivery_errors += 1
            self._stats.last_error = str(exc)
        if self._stats.delivery_errors in (1, 10, 100) or self._stats.delivery_errors % 1000 == 0:
            logger.warning(
                "producer_delivery_failed",
                delivery_errors=self._stats.delivery_errors,
                error=str(exc),
            )

    def _flush_and_close(self) -> None:
        self._close_kafka(timeout=10.0)

    def _close_kafka(self, timeout: float = 10.0) -> None:
        producer = self._kafka
        if producer is None or self._kafka_closed:
            return
        try:
            pending = producer.flush(timeout=timeout)
            if pending:
                logger.warning("producer_flush_incomplete", pending_messages=pending)
        except Exception as exc:  # noqa: BLE001 - shutdown should never raise
            logger.warning("producer_flush_failed", error=str(exc))
        try:
            producer.close(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("producer_close_failed", error=str(exc))
        self._kafka_closed = True


def _json_serializer(value: Any) -> bytes:
    """Compact UTF-8 JSON encoder used as the Kafka value serializer."""

    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="event_producer",
        description="Replay NSL-KDD traffic into the `network-events` Kafka topic.",
    )
    parser.add_argument("--rate", type=int, choices=PUBLISH_RATE_PRESETS, default=DEFAULT_RATE)
    parser.add_argument("--dataset", default=None, help="Dataset path (default: data/raw/*).")
    parser.add_argument("--topic", default=TOPIC_NETWORK_EVENTS, help="Target Kafka topic.")
    parser.add_argument("--bootstrap", default=None, help="Kafka bootstrap servers.")
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds.")
    parser.add_argument("--count", type=int, default=None, help="Stop after N events.")
    parser.add_argument("--hosts", type=int, default=100, help="Synthetic host pool size.")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic seed.")
    parser.add_argument("--no-loop", action="store_true", help="Stop when dataset is exhausted.")
    parser.add_argument("--no-shuffle", action="store_true", help="Keep original row order.")
    parser.add_argument("--no-validate", action="store_true", help="Skip schema validation.")
    parser.add_argument("--dry-run", action="store_true", help="Do not contact Kafka.")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR.")
    parser.add_argument("--json-logs", action="store_true", help="Force JSON log output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    try:
        dataset = resolve_dataset_path(args.dataset)
    except FileNotFoundError as exc:
        logger.error("producer_dataset_missing", error=str(exc))
        return 1

    producer = EventProducer(
        dataset_path=dataset,
        bootstrap_servers=args.bootstrap,
        topic=args.topic,
        rate=args.rate,
        loop=not args.no_loop,
        seed=args.seed,
        host_count=max(2, args.hosts),
        validate_events=not args.no_validate,
        dry_run=args.dry_run,
        shuffle_events=not args.no_shuffle,
    )

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("producer_shutdown_signal", signal=signum)
        producer.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError, AttributeError):  # pragma: no cover - platform specific
            pass

    try:
        producer.start(duration=args.duration, max_events=args.count, block=True)
    except ProducerConnectionError as exc:
        logger.error("producer_connection_failed", error=str(exc))
        return 2
    finally:
        producer.stop()

    stats = producer.get_stats()
    logger.info("producer_summary", **stats)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
