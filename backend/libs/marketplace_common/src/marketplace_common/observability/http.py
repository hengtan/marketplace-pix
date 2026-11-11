from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marketplace_common.observability.context import set_request_id
from marketplace_common.observability.logs import setup_logging
from marketplace_common.observability.metrics import HTTP_DURATION, HTTP_REQUESTS
from marketplace_common.observability.tracing import instrument_fastapi, setup_tracing
from marketplace_common.resilience.deadline import install_deadline

REQUEST_ID_HEADER = b"x-request-id"
METRICS_PATH = "/metrics"
UNMATCHED_ROUTE = "unmatched"


def _valid_request_id(value: str) -> bool:
    return 0 < len(value) <= 64 and value.isprintable()


class RequestIdMiddleware:
    """Guarda o X-Request-Id da requisição (ou cria um) para os logs e devolve no response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER, b"").decode("latin-1")
        request_id = incoming if _valid_request_id(incoming) else uuid.uuid4().hex
        set_request_id(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(name.lower() == REQUEST_ID_HEADER for name, _ in headers):
                    headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            set_request_id(None)


def _route_template(scope: Scope) -> str:
    app = scope.get("app")
    for route in getattr(app, "routes", []):
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return str(getattr(route, "path", UNMATCHED_ROUTE))
    return UNMATCHED_ROUTE


class MetricsMiddleware:
    """Métricas RED por rota: taxa, erros (status) e duração."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == METRICS_PATH:
            await self.app(scope, receive, send)
            return
        status = 500
        started = time.perf_counter()

        async def send_and_capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_capture)
        finally:
            route = _route_template(scope)
            method = scope["method"]
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)


def install_api_observability(
    app: FastAPI,
    service_name: str,
    *,
    deadline_default_seconds: float | None = None,
    deadline_max_seconds: float | None = None,
) -> None:
    """Liga logs JSON, tracing, deadline, request id e /metrics em uma API FastAPI."""
    setup_logging(service_name)
    setup_tracing(service_name)
    instrument_fastapi(app)
    install_deadline(app, deadline_default_seconds, deadline_max_seconds)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)

    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.add_api_route(METRICS_PATH, metrics, methods=["GET"], include_in_schema=False)
