"""CyberShield AI - stream processing package.

Contains Kafka producers/consumers and PySpark jobs that move telemetry
through the pipeline: sensors -> Kafka -> Spark -> predictions -> Postgres/HDFS.
"""
