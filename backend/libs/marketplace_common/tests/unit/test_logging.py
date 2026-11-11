import json
import logging

import pytest
from opentelemetry import trace

from marketplace_common.observability import JsonFormatter, set_request_id, setup_logging


def render(record_message: str = "hello", **extra: object) -> dict:
    record = logging.LogRecord(
        "marketplace.test", logging.INFO, "f.py", 1, record_message, (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter("orders").format(record))


def test_basic_fields():
    entry = render("order created", order_id="abc")

    assert entry["message"] == "order created"
    assert entry["level"] == "INFO"
    assert entry["service"] == "orders"
    assert entry["logger"] == "marketplace.test"
    assert entry["order_id"] == "abc"
    assert entry["timestamp"].endswith("+00:00")
    assert "trace_id" not in entry
    assert "request_id" not in entry


def test_includes_trace_and_span_ids_inside_a_span():
    with trace.get_tracer("t").start_as_current_span("work") as span:
        entry = render()
        context = span.get_span_context()

    assert entry["trace_id"] == trace.format_trace_id(context.trace_id)
    assert entry["span_id"] == trace.format_span_id(context.span_id)
    assert len(entry["trace_id"]) == 32


def test_includes_request_id_when_set():
    set_request_id("req-123")
    try:
        assert render()["request_id"] == "req-123"
    finally:
        set_request_id(None)


def test_exception_is_serialized():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, "f.py", 1, "failed", (), sys.exc_info())
    entry = json.loads(JsonFormatter("orders").format(record))

    assert "ValueError: boom" in entry["exception"]


def test_setup_logging_writes_one_json_line_per_record(capsys: pytest.CaptureFixture[str]):
    setup_logging("billing", level="INFO")
    logging.getLogger("marketplace.demo").info("hi %s", "there")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(line)["message"] == "hi there"
    assert json.loads(line)["service"] == "billing"
