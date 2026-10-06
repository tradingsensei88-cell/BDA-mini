-- =============================================================================
-- CyberShield AI - PostgreSQL bootstrap schema
-- Executed automatically on first container start via
-- /docker-entrypoint-initdb.d/01-init.sql (mounted from this file).
--
-- Tables: network_events, security_events, model_versions, predictions,
--         anomalies, alerts, investigations, system_metrics
-- =============================================================================

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET timezone = 'UTC';

-- =============================================================================
-- Shared helpers
-- =============================================================================

-- Keeps `updated_at` accurate on mutable tables.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. network_events - raw flow-level telemetry ingested from the packet sensors
-- =============================================================================
CREATE TABLE IF NOT EXISTS network_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    source_ip         INET             NOT NULL,
    destination_ip    INET             NOT NULL,
    source_port       INTEGER          CHECK (source_port BETWEEN 0 AND 65535),
    destination_port  INTEGER          CHECK (destination_port BETWEEN 0 AND 65535),
    protocol          VARCHAR(16)      NOT NULL DEFAULT 'TCP',
    bytes_sent        BIGINT           NOT NULL DEFAULT 0 CHECK (bytes_sent >= 0),
    bytes_received    BIGINT           NOT NULL DEFAULT 0 CHECK (bytes_received >= 0),
    packets_sent      INTEGER          NOT NULL DEFAULT 0 CHECK (packets_sent >= 0),
    packets_received  INTEGER          NOT NULL DEFAULT 0 CHECK (packets_received >= 0),
    duration_ms       INTEGER          CHECK (duration_ms >= 0),
    tcp_flags         TEXT,
    flow_state        VARCHAR(32),
    hostname          VARCHAR(255),
    sensor_id         VARCHAR(64),
    geo_country       CHAR(2),
    raw_payload       JSONB,
    ingested_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE network_events IS 'Raw network flow telemetry mirrored from Kafka (network-events topic).';

CREATE INDEX IF NOT EXISTS idx_network_events_event_time   ON network_events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_network_events_source_ip    ON network_events (source_ip);
CREATE INDEX IF NOT EXISTS idx_network_events_dest_ip      ON network_events (destination_ip);
CREATE INDEX IF NOT EXISTS idx_network_events_protocol     ON network_events (protocol);
CREATE INDEX IF NOT EXISTS idx_network_events_raw_payload  ON network_events USING GIN (raw_payload);

-- =============================================================================
-- 2. security_events - normalized detections from IDS/IPS, auth logs, firewalls
-- =============================================================================
CREATE TABLE IF NOT EXISTS security_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    event_type        VARCHAR(64)      NOT NULL,  -- port_scan, brute_force, ddos, exfiltration, ...
    category          VARCHAR(64),                -- reconnaissance, intrusion, malware, ...
    severity          VARCHAR(16)      NOT NULL DEFAULT 'medium'
                      CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    source_ip         INET,
    destination_ip    INET,
    destination_port  INTEGER          CHECK (destination_port BETWEEN 0 AND 65535),
    username          VARCHAR(128),
    hostname          VARCHAR(255),
    source_system     VARCHAR(64),                -- snort, suricata, windows_events, auth_log, ...
    mitre_technique   VARCHAR(32),                -- e.g. T1046 (Network Service Scanning)
    description       TEXT,
    raw_log           JSONB,
    is_processed      BOOLEAN          NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE security_events IS 'Normalized security detections from heterogeneous log sources.';

CREATE INDEX IF NOT EXISTS idx_security_events_event_time ON security_events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_type       ON security_events (event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity   ON security_events (severity);
CREATE INDEX IF NOT EXISTS idx_security_events_source_ip  ON security_events (source_ip);
CREATE INDEX IF NOT EXISTS idx_security_events_unprocessed
    ON security_events (event_time DESC) WHERE is_processed = FALSE;

-- =============================================================================
-- 3. model_versions - ML model registry (training runs, artifacts, metrics)
-- =============================================================================
CREATE TABLE IF NOT EXISTS model_versions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name        VARCHAR(128)     NOT NULL,
    version           VARCHAR(32)      NOT NULL,
    algorithm         VARCHAR(64)      NOT NULL,  -- isolation_forest, random_forest, xgboost, ...
    stage             VARCHAR(32)      NOT NULL DEFAULT 'development'
                      CHECK (stage IN ('development', 'staging', 'production', 'archived')),
    is_active         BOOLEAN          NOT NULL DEFAULT FALSE,
    artifact_path     TEXT,                       -- HDFS or local path to the serialized model
    metrics           JSONB            NOT NULL DEFAULT '{}'::jsonb,
    hyperparameters   JSONB            NOT NULL DEFAULT '{}'::jsonb,
    training_dataset  VARCHAR(255),               -- e.g. NSL-KDD, CICIDS2017
    trained_at        TIMESTAMPTZ,
    deployed_at       TIMESTAMPTZ,
    notes             TEXT,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_model_versions_name_version UNIQUE (model_name, version)
);

COMMENT ON TABLE model_versions IS 'Registry of every trained ML model version and its evaluation metrics.';

-- Only one active deployment per model name.
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_one_active
    ON model_versions (model_name) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_model_versions_stage ON model_versions (stage);

CREATE TRIGGER trg_model_versions_updated_at
    BEFORE UPDATE ON model_versions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 4. predictions - per-event model inference results
-- =============================================================================
CREATE TABLE IF NOT EXISTS predictions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id           UUID REFERENCES network_events (id) ON DELETE CASCADE,
    security_event_id  UUID REFERENCES security_events (id) ON DELETE SET NULL,
    model_version_id   UUID REFERENCES model_versions (id) ON DELETE SET NULL,
    predicted_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    is_attack          BOOLEAN          NOT NULL,
    attack_type        VARCHAR(64),                -- DoS, Probe, R2L, U2R, normal-class name
    confidence         NUMERIC(5, 4)    NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    probabilities      JSONB            NOT NULL DEFAULT '{}'::jsonb,
    feature_vector     JSONB,
    latency_ms         NUMERIC(10, 2)   CHECK (latency_ms >= 0),
    created_at         TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE predictions IS 'Model inference output for individual network/security events.';

CREATE INDEX IF NOT EXISTS idx_predictions_predicted_at   ON predictions (predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_is_attack      ON predictions (is_attack) WHERE is_attack = TRUE;
CREATE INDEX IF NOT EXISTS idx_predictions_event_id       ON predictions (event_id);
CREATE INDEX IF NOT EXISTS idx_predictions_model_version  ON predictions (model_version_id);

-- =============================================================================
-- 5. anomalies - unsupervised outlier detections over sliding windows
-- =============================================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    detected_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    window_start    TIMESTAMPTZ      NOT NULL,
    window_end      TIMESTAMPTZ      NOT NULL,
    source_ip       INET,
    method          VARCHAR(64)      NOT NULL DEFAULT 'isolation_forest',
    anomaly_score   NUMERIC(6, 5)    NOT NULL,     -- higher = more anomalous
    threshold       NUMERIC(6, 5),
    is_confirmed    BOOLEAN,                       -- analyst-confirmed true/false positive
    features        JSONB            NOT NULL DEFAULT '{}'::jsonb,
    description     TEXT,
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_anomalies_window CHECK (window_end >= window_start)
);

COMMENT ON TABLE anomalies IS 'Unsupervised anomaly detections (Isolation Forest / statistical baselines).';

CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at ON anomalies (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_source_ip   ON anomalies (source_ip);
CREATE INDEX IF NOT EXISTS idx_anomalies_score       ON anomalies (anomaly_score DESC);

-- =============================================================================
-- 6. alerts - actionable SOC alerts derived from predictions/anomalies
-- =============================================================================
CREATE TABLE IF NOT EXISTS alerts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type       VARCHAR(64)      NOT NULL,     -- ddos, port_scan, data_exfiltration, ...
    title            VARCHAR(255)     NOT NULL,
    description      TEXT,
    severity         VARCHAR(16)      NOT NULL DEFAULT 'medium'
                     CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    status           VARCHAR(32)      NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open', 'acknowledged', 'investigating', 'resolved', 'false_positive')),
    source_ip        INET,
    destination_ip   INET,
    prediction_id    UUID REFERENCES predictions (id) ON DELETE SET NULL,
    anomaly_id       UUID REFERENCES anomalies (id) ON DELETE SET NULL,
    risk_score       NUMERIC(5, 2)    CHECK (risk_score >= 0 AND risk_score <= 100),
    assigned_to      VARCHAR(128),
    acknowledged_at  TIMESTAMPTZ,
    resolved_at      TIMESTAMPTZ,
    metadata         JSONB            NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE alerts IS 'SOC-facing alerts generated from ML predictions and anomaly detections.';

CREATE INDEX IF NOT EXISTS idx_alerts_created_at    ON alerts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status        ON alerts (status);
CREATE INDEX IF NOT EXISTS idx_alerts_severity      ON alerts (severity);
CREATE INDEX IF NOT EXISTS idx_alerts_source_ip     ON alerts (source_ip);
CREATE INDEX IF NOT EXISTS idx_alerts_open
    ON alerts (created_at DESC) WHERE status IN ('open', 'acknowledged', 'investigating');

CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 7. investigations - analyst case management for alert triage
-- =============================================================================
CREATE TABLE IF NOT EXISTS investigations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title             VARCHAR(255)     NOT NULL,
    status            VARCHAR(32)      NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'in_progress', 'on_hold', 'closed')),
    priority          VARCHAR(16)      NOT NULL DEFAULT 'medium'
                      CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    severity          VARCHAR(16)      NOT NULL DEFAULT 'medium'
                      CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    analyst           VARCHAR(128),
    summary           TEXT,
    findings          TEXT,
    attack_vector     VARCHAR(64),
    mitre_techniques  TEXT[]           NOT NULL DEFAULT '{}',
    tags              TEXT[]           NOT NULL DEFAULT '{}',
    related_alert_ids UUID[]           NOT NULL DEFAULT '{}',
    opened_at         TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    closed_at         TIMESTAMPTZ,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE investigations IS 'Analyst case files grouping related alerts into a single incident.';

CREATE INDEX IF NOT EXISTS idx_investigations_status     ON investigations (status);
CREATE INDEX IF NOT EXISTS idx_investigations_analyst    ON investigations (analyst);
CREATE INDEX IF NOT EXISTS idx_investigations_opened_at  ON investigations (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_investigations_tags       ON investigations USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_investigations_alerts     ON investigations USING GIN (related_alert_ids);

CREATE TRIGGER trg_investigations_updated_at
    BEFORE UPDATE ON investigations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 8. system_metrics - platform health time-series (pipeline observability)
-- =============================================================================
CREATE TABLE IF NOT EXISTS system_metrics (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recorded_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    component     VARCHAR(64)      NOT NULL,   -- kafka, spark, hdfs, postgres, redis, backend, ml
    metric_name   VARCHAR(128)     NOT NULL,   -- events_per_sec, consumer_lag, inference_latency_ms, ...
    metric_value  DOUBLE PRECISION NOT NULL,
    unit          VARCHAR(32),                 -- count, ms, bytes, percent
    host          VARCHAR(255),
    labels        JSONB            NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE system_metrics IS 'Time-series metrics emitted by every platform component for observability dashboards.';

CREATE INDEX IF NOT EXISTS idx_system_metrics_recorded_at ON system_metrics (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_metrics_lookup
    ON system_metrics (component, metric_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_metrics_labels ON system_metrics USING GIN (labels);

-- =============================================================================
-- Bootstrap seed - register the first (untrained) model version slot
-- =============================================================================
INSERT INTO model_versions (
    model_name, version, algorithm, stage, is_active, artifact_path,
    metrics, hyperparameters, training_dataset, trained_at, notes
)
VALUES (
    'cybershield-attack-classifier',
    '0.1.0-bootstrap',
    'isolation_forest',
    'development',
    FALSE,
    'hdfs:///cybershield/models/cybershield-attack-classifier/0.1.0-bootstrap',
    '{}'::jsonb,
    '{}'::jsonb,
    'NSL-KDD',
    NULL,
    'Bootstrap registry entry created by infrastructure/postgres/init.sql. Replace with a real trained model.'
)
ON CONFLICT (model_name, version) DO NOTHING;
