"""
Prometheus-compatible metrics for FindLEI.
Uses the official `prometheus_client` library (pure Python, no C extensions).

Exposed at GET /metrics  (text/plain; version=0.0.4)

Metrics
-------
findlei_jobs_total{status}           Counter  – completed / error jobs
findlei_leis_checked_total{source}   Counter  – per data source (gleif / lei-lookup / not_found)
findlei_job_duration_seconds         Histogram – end-to-end job wall time
findlei_lei_duration_seconds         Histogram – per-LEI lookup wall time
findlei_active_jobs                  Gauge    – jobs currently processing
findlei_http_requests_total{method, path, status_code}  Counter – HTTP layer
"""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Use a private registry so we don't inherit default process/python collectors
# (they pull in platform-specific C extensions that may not be available everywhere)
registry = CollectorRegistry(auto_describe=True)

# ── Counters ──────────────────────────────────────────────────────────────────
jobs_total = Counter(
    "findlei_jobs_total",
    "Total LEI batch jobs by final status",
    ["status"],          # completed | error
    registry=registry,
)

leis_checked_total = Counter(
    "findlei_leis_checked_total",
    "Total individual LEIs processed, by data source used",
    ["source"],          # gleif | lei_lookup | gleif_and_lei_lookup | not_found | invalid
    registry=registry,
)

http_requests_total = Counter(
    "findlei_http_requests_total",
    "Inbound HTTP requests",
    ["method", "path", "status_code"],
    registry=registry,
)

# ── Gauges ────────────────────────────────────────────────────────────────────
active_jobs = Gauge(
    "findlei_active_jobs",
    "Number of jobs currently in processing state",
    registry=registry,
)

# ── Histograms ────────────────────────────────────────────────────────────────
job_duration_seconds = Histogram(
    "findlei_job_duration_seconds",
    "Wall-clock time to complete a full batch job",
    buckets=[5, 15, 30, 60, 120, 300, 600],
    registry=registry,
)

lei_duration_seconds = Histogram(
    "findlei_lei_duration_seconds",
    "Wall-clock time to resolve a single LEI",
    buckets=[0.2, 0.5, 1, 2, 5, 10, 20],
    registry=registry,
)


def metrics_response() -> tuple[bytes, str]:
    """Return (body_bytes, content_type) for the /metrics endpoint."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
