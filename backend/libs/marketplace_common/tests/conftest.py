import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from marketplace_common.observability.tracing import setup_tracing

_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session", autouse=True)
def _tracing() -> None:
    assert setup_tracing("marketplace-tests", span_exporter=_EXPORTER)


@pytest.fixture
def spans() -> InMemorySpanExporter:
    _EXPORTER.clear()
    return _EXPORTER
