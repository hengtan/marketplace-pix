import json
import re
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

import assistant.metrics  # noqa: F401
from assistant.telemetry import ChatTrace, ManualSpan, next_in_span, safe_value, step_span

DASHBOARD = (
    Path(__file__).resolve().parents[5] / "infra/observability/grafana/dashboards/assistant.json"
)


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: InMemorySpanExporter):  # type: ignore[no-untyped-def]
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test")


def test_span_attributes_are_redacted(exporter, tracer) -> None:  # type: ignore[no-untyped-def]
    with step_span(
        "rewrite", tracer=tracer, attributes={"question": "ligue 11 91234-5678"}
    ) as span:
        span.set_attribute("note", "ana@loja.com")
        span.set_attribute("count", 3)
    attrs = dict(exporter.get_finished_spans()[0].attributes or {})
    assert attrs["question"] == "ligue [TELEFONE]" and attrs["note"] == "[EMAIL]"
    assert attrs["count"] == 3
    assert safe_value(object().__class__.__name__) == "object"


def test_step_span_records_errors_and_still_closes(exporter, tracer) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RuntimeError), step_span("retrieve", tracer=tracer):
        raise RuntimeError("boom")
    span = exporter.get_finished_spans()[0]
    assert span.name == "assistant.retrieve"
    assert span.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in span.events)


async def test_steps_nest_under_the_chat_root_even_across_awaits(exporter, tracer) -> None:  # type: ignore[no-untyped-def]
    trace = ChatTrace(tracer)
    with trace.scope(), step_span("tool", tracer=tracer):
        pass
    child = trace.child("generate")
    child.end()
    trace.end()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    root = spans["assistant.chat"]
    assert spans["assistant.tool"].parent.span_id == root.context.span_id
    assert spans["assistant.generate"].parent.span_id == root.context.span_id


async def test_next_in_span_walks_an_async_iterator(tracer) -> None:  # type: ignore[no-untyped-def]
    async def numbers():  # type: ignore[no-untyped-def]
        yield 1
        yield 2

    span = ManualSpan("generate", tracer=tracer)
    iterator = numbers().__aiter__()
    from assistant.telemetry import is_done

    assert await next_in_span(iterator, span.handle.span) == 1
    assert await next_in_span(iterator, span.handle.span) == 2
    assert is_done(await next_in_span(iterator, span.handle.span))
    span.end()


def _registry_names() -> set[str]:
    names: set[str] = set()
    for family in REGISTRY.collect():
        base = family.name
        names |= {base, f"{base}_total", f"{base}_bucket", f"{base}_sum", f"{base}_count"}
    return names


def test_dashboard_only_queries_metrics_that_exist() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    known = _registry_names()
    used: set[str] = set()
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            used |= set(re.findall(r"\bassistant_[a-z_]+", target["expr"]))
    assert used, "dashboard has no assistant queries"
    assert used <= known, sorted(used - known)
    assert dashboard["uid"] == "assistant"
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids))


def test_dashboard_covers_every_pipeline_step() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")
    for step in ("rewrite", "retrieve", "rerank", "generate"):
        assert step in text
    for metric in ("tokens_total", "cost_usd_total", "step_duration_seconds_bucket"):
        assert metric in text
