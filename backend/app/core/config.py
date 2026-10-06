"""CyberShield AI - application configuration.

Loads settings from environment variables (and an optional .env file),
exposing a single cached ``Settings`` instance for the whole backend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ---------------------------------------------------------
    app_name: str = "CyberShield AI"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # -- PostgreSQL ----------------------------------------------------------
    postgres_user: str = "cybershield"
    postgres_password: str = "cybershield_secret"
    postgres_db: str = "cybershield"
    database_url: str = (
        "postgresql://cybershield:cybershield_secret@postgres:5432/cybershield"
    )

    # -- Redis ---------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"

    # -- Kafka ---------------------------------------------------------------
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_external_servers: str = "localhost:29092"
    kafka_network_events_topic: str = "network-events"
    kafka_security_events_topic: str = "security-events"
    kafka_predictions_topic: str = "predictions"
    kafka_alerts_topic: str = "alerts"
    kafka_anomalies_topic: str = "anomalies"

    # -- HDFS ----------------------------------------------------------------
    hdfs_namenode_url: str = "hdfs://namenode:8020"
    hdfs_web_url: str = "http://namenode:9870"
    hdfs_base_path: str = "/cybershield"

    # -- Spark ---------------------------------------------------------------
    spark_master_url: str = "spark://spark-master:7077"

    # -- CORS ----------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    # -- API -------------------------------------------------------------
    api_prefix: str = "/api"
    request_id_header: str = "X-Request-ID"
    rate_limit_per_minute: int = 600

    # -- Demo / standalone mode ------------------------------------------
    # When true (default) the backend generates realistic NSL-KDD style
    # events in-process so every endpoint works without Kafka/Spark/HDFS.
    demo_mode: bool = True
    demo_event_rate: int = 12
    demo_seed: int = 42
    demo_backfill_events: int = 3600
    demo_backfill_hours: int = 168

    # -- Database tuning ---------------------------------------------------
    db_connect_timeout: float = 3.0
    db_connect_retries: int = 2
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # -- Redis tuning ------------------------------------------------------
    redis_connect_timeout: float = 2.0
    redis_event_channel: str = "cybershield:events"
    redis_alert_channel: str = "cybershield:alerts"
    redis_anomaly_channel: str = "cybershield:anomalies"
    redis_metrics_channel: str = "cybershield:metrics"

    # -- WebSocket -----------------------------------------------------------
    ws_heartbeat_seconds: float = 30.0
    ws_channel: str = "/ws/security-events"
    ws_replay_limit: int = 25

    # -- ML --------------------------------------------------------------------
    # Optional override for the folder holding model_metadata.json, etc.
    ml_models_dir: str = ""

    # -- Derived helpers -----------------------------------------------------
    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a normalized list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        """Async SQLAlchemy DSN derived from ``database_url`` (asyncpg driver)."""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def project_root(self) -> Path:
        """Absolute path of the repository root (``cybershield-ai/``)."""

        return Path(__file__).resolve().parents[3]

    @property
    def ml_models_path(self) -> Path:
        """Directory containing model metadata JSON artifacts."""

        if self.ml_models_dir:
            return Path(self.ml_models_dir)
        return self.project_root / "ml" / "models"

    @property
    def local_database_url(self) -> str:
        """Localhost variant of ``database_url`` (dev fallback when Docker
        service hostnames such as ``postgres`` cannot be resolved)."""

        url = self.database_url
        for remote in ("@postgres:", "@db:"):
            if remote in url:
                return url.replace(remote, "@localhost:")
        return url

    @property
    def local_redis_url(self) -> str:
        """Localhost variant of ``redis_url`` (dev fallback)."""

        url = self.redis_url
        for remote in ("redis://redis:", "redis://cache:"):
            if url.startswith(remote):
                return url.replace(remote, "redis://localhost:", 1)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()


settings = get_settings()
