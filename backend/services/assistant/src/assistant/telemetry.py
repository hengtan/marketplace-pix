import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from marketplace_common.observability import get_tracer
from opentelemetry.trace import Span, Status, StatusCode, Tracer, set_span_in_context, use_span

from assistant.domain.pii import redact
from assistant.metrics import STEP_DURATION

PREVIEW_CHARS = 80


def safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, bool | int | float):
        return value
    return redact(str(value))


class SpanHandle:
    """Thin wrapper that redacts personal data from every attribute before it is recorded."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self.span.set_attribute(key, safe_value(value))


@contextmanager
def step_span(
    step: str, *, tracer: Tracer | None = None, attributes: Mapping[str, Any] | None = None
) -> Iterator[SpanHandle]:
    """Span plus latency histogram for one pipeline step. Use it around code that does not
    yield; for steps that stream use `ManualSpan`."""
    started = time.perf_counter()
    with (tracer or get_tracer()).start_as_current_span(f"assistant.{step}") as span:
        handle = SpanHandle(span)
        for key, value in (attributes or {}).items():
            handle.set_attribute(key, value)
        try:
            yield handle
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
        finally:
            STEP_DURATION.labels(step).observe(time.perf_counter() - started)


class ManualSpan:
    """Span that can stay open across `yield`s of an async generator: it is never attached
    to the context, so closing the generator from another task cannot corrupt the context."""

    def __init__(self, step: str, parent: Span | None = None, tracer: Tracer | None = None) -> None:
        context = set_span_in_context(parent) if parent is not None else None
        self._step = step
        self._started = time.perf_counter()
        self.handle = SpanHandle(
            (tracer or get_tracer()).start_span(f"assistant.{step}", context=context)
        )

    def end(self, error: BaseException | None = None) -> None:
        if error is not None:
            self.handle.span.record_exception(error)
            self.handle.span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        self.handle.span.end()
        STEP_DURATION.labels(self._step).observe(time.perf_counter() - self._started)


def preview(text: str) -> str:
    return redact(text)[:PREVIEW_CHARS]


_DONE: Any = object()


class ChatTrace:
    """Root span of a chat request. It is attached to the context only while code runs inside
    `scope()`, never across a `yield`, so spans of the steps nest under it and the async
    generator can be cancelled safely."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer
        self._root = ManualSpan("chat", tracer=tracer)
        self.span = self._root.handle.span

    def set_attribute(self, key: str, value: Any) -> None:
        self._root.handle.set_attribute(key, value)

    def scope(self) -> Any:
        return use_span(
            self.span, end_on_exit=False, record_exception=False, set_status_on_exception=False
        )

    def child(self, step: str) -> ManualSpan:
        return ManualSpan(step, parent=self.span, tracer=self._tracer)

    def end(self, error: BaseException | None = None) -> None:
        self._root.end(error)


async def next_in_span(iterator: Any, span: Span) -> Any:
    """Advances an async iterator with `span` as the current span; returns _DONE when finished."""
    with use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
        try:
            return await iterator.__anext__()
        except StopAsyncIteration:
            return _DONE


def is_done(value: Any) -> bool:
    return value is _DONE
