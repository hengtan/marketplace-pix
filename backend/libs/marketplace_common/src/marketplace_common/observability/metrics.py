from __future__ import annotations

import logging
import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests served", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HANDLER_DURATION = Histogram(
    "marketplace_handler_duration_seconds",
    "Event handler duration by event type and result",
    ["consumer_group", "event_type", "result"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
DLQ_MESSAGES = Counter(
    "marketplace_dlq_messages_total",
    "Messages sent to the dead letter queue",
    ["source_topic", "consumer_group"],
)
OUTBOX_PUBLISHED = Counter(
    "marketplace_outbox_published_total",
    "Events published by the outbox relay",
    ["topic", "event_type"],
)
OUTBOX_PENDING = Gauge("marketplace_outbox_pending", "Outbox events waiting to be published")
OUTBOX_RELAY_ERRORS = Counter(
    "marketplace_outbox_relay_errors_total", "Outbox relay iterations that failed"
)

CLEANUP_DELETED = Counter(
    "marketplace_cleanup_deleted_total", "Rows removed by the retention job", ["table"]
)
CLEANUP_BATCHES = Counter(
    "marketplace_cleanup_batches_total", "Delete batches executed by the retention job", ["table"]
)
CLEANUP_RUNS = Counter(
    "marketplace_cleanup_runs_total", "Retention job iterations by result", ["result"]
)
CLEANUP_DURATION = Histogram(
    "marketplace_cleanup_run_duration_seconds",
    "Duration of one retention job iteration",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0),
)
CLEANUP_LAST_SUCCESS = Gauge(
    "marketplace_cleanup_last_success_timestamp_seconds",
    "Unix time of the last successful retention run",
)

DEFAULT_METRICS_PORT = 9100


def start_metrics_server(port: int | None = None) -> bool:
    """Expõe /metrics em uma porta própria para workers e relays (padrão 9100, METRICS_PORT)."""
    chosen = port if port is not None else int(os.environ.get("METRICS_PORT", DEFAULT_METRICS_PORT))
    if chosen <= 0:
        return False
    try:
        start_http_server(chosen)
    except OSError:
        logger.warning("metrics port %d unavailable, metrics endpoint disabled", chosen)
        return False
    logger.info("metrics exposed on port %d", chosen)
    return True
