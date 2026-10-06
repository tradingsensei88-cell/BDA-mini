#!/usr/bin/env bash
# =============================================================================
# CyberShield AI - Kafka topic bootstrap.
#
# Auto-creation is enabled on the broker, but this script creates the platform
# topics up-front with deliberate partition counts so the streaming topology
# can scale consumers deterministically.
#
# Usage (from the repository root):
#   docker compose exec kafka bash /dev/stdin < infrastructure/kafka/create-topics.sh
# or copy it into the broker and run:
#   docker compose cp infrastructure/kafka/create-topics.sh kafka:/tmp/create-topics.sh
#   docker compose exec kafka bash /tmp/create-topics.sh
# =============================================================================
set -euo pipefail

BROKER="${KAFKA_BROKER:-kafka:9092}"
REPLICATION="${KAFKA_REPLICATION:-1}"

# topic:partitions
TOPICS=(
  "network-events:6"
  "security-events:6"
  "predictions:3"
  "alerts:3"
  "anomalies:3"
  "system-metrics:2"
)

for entry in "${TOPICS[@]}"; do
  topic="${entry%%:*}"
  partitions="${entry##*:}"
  echo "==> creating topic '${topic}' (partitions=${partitions}, replication=${REPLICATION})"
  kafka-topics --bootstrap-server "${BROKER}" \
    --create --if-not-exists \
    --topic "${topic}" \
    --partitions "${partitions}" \
    --replication-factor "${REPLICATION}"
done

echo "==> topics on ${BROKER}:"
kafka-topics --bootstrap-server "${BROKER}" --list
