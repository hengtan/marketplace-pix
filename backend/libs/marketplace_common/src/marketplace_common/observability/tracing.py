from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)

TRACER_NAME = "marketplace_common"
TRACEPARENT = "traceparent"
_configured = False


def get_tracer() -> Tracer:
    return trace.get_tracer(TRACER_NAME)


def _endpoint_configured() -> bool:
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def _sdk_disabled() -> bool:
    return os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true"


def setup_tracing(
    service_name: str,
    span_exporter: SpanExporter | None = None,
) -> bool:
    """Configura o OpenTelemetry a partir das variáveis OTEL_* e devolve se ficou ativo.

    Sem `OTEL_EXPORTER_OTLP_ENDPOINT` (e sem exportador explícito) nada é configurado: o tracer
    global continua sendo o no-op da API e o custo é praticamente zero.
    """
    global _configured
    if _sdk_disabled() or (span_exporter is None and not _endpoint_configured()):
        return False
    if _configured:
        return True
    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", service_name)})
    provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True
    _instrument_httpx()
    logger.info("tracing enabled for %s", resource.attributes.get("service.name"))
    return True


def _instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def instrument_fastapi(app: Any) -> None:
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready,/metrics")


def instrument_sqlalchemy(engine: Any) -> None:
    """Recebe um AsyncEngine ou Engine e instrumenta as queries como spans filhos."""
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))


def inject_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def current_traceparent() -> str | None:
    return inject_headers().get(TRACEPARENT)


def context_from_headers(headers: Mapping[str, str]) -> otel_context.Context:
    return propagate.extract(dict(headers))


def context_from_traceparent(traceparent: str | None) -> otel_context.Context | None:
    if not traceparent:
        return None
    return propagate.extract({TRACEPARENT: traceparent})
