from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from marketplace_common.observability import (
    current_traceparent,
    get_tracer,
    inject_headers,
    setup_tracing,
)
from marketplace_common.observability.tracing import (
    context_from_headers,
    context_from_traceparent,
)


def test_without_endpoint_tracing_is_a_safe_noop(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    provider_before = trace.get_tracer_provider()

    assert setup_tracing("orders") is False
    assert trace.get_tracer_provider() is provider_before


def test_sdk_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    assert setup_tracing("orders") is False


def test_with_endpoint_tracing_is_enabled(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    assert setup_tracing("orders") is True
    assert isinstance(trace.get_tracer_provider(), TracerProvider)


def test_inject_and_extract_round_trip_keeps_the_trace_id():
    with get_tracer().start_as_current_span("producer") as span:
        headers = inject_headers()
        traceparent = current_traceparent()
        expected = span.get_span_context().trace_id

    assert traceparent is not None
    assert traceparent == headers["traceparent"]
    for context in (context_from_headers(headers), context_from_traceparent(traceparent)):
        assert context is not None
        with get_tracer().start_as_current_span("consumer", context=context) as child:
            assert child.get_span_context().trace_id == expected


def test_no_active_span_means_no_traceparent():
    assert current_traceparent() is None
    assert context_from_traceparent(None) is None
