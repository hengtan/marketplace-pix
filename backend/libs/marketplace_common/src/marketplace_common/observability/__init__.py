from marketplace_common.observability.context import get_request_id, set_request_id
from marketplace_common.observability.http import (
    MetricsMiddleware,
    RequestIdMiddleware,
    install_api_observability,
)
from marketplace_common.observability.logs import JsonFormatter, setup_logging
from marketplace_common.observability.metrics import start_metrics_server
from marketplace_common.observability.tracing import (
    current_traceparent,
    get_tracer,
    inject_headers,
    instrument_fastapi,
    instrument_sqlalchemy,
    setup_tracing,
)


def setup_worker_observability(service_name: str) -> None:
    """Para workers e relays: logs JSON, tracing opcional e /metrics na porta METRICS_PORT."""
    setup_logging(service_name)
    setup_tracing(service_name)
    start_metrics_server()


__all__ = [
    "JsonFormatter",
    "MetricsMiddleware",
    "RequestIdMiddleware",
    "current_traceparent",
    "get_request_id",
    "get_tracer",
    "inject_headers",
    "install_api_observability",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "set_request_id",
    "setup_logging",
    "setup_tracing",
    "setup_worker_observability",
    "start_metrics_server",
]
