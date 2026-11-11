import asyncio
from uuid import UUID, uuid4

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from marketplace_common.messaging import (
    IncomingEvent,
    KafkaEventConsumer,
    KafkaPublisher,
    OutboxMessage,
    OutboxRelay,
)
from marketplace_common.observability import current_traceparent, get_tracer
from tests.integration.conftest import BOOTSTRAP
from tests.integration.helpers import wait_until
from tests.unit.test_outbox_relay import FakeStore, FakeUow


class Recorder:
    def __init__(self) -> None:
        self.events: list[IncomingEvent] = []
        self.trace_ids: list[int] = []

    async def handle(self, event: IncomingEvent) -> None:
        self.trace_ids.append(trace.get_current_span().get_span_context().trace_id)
        self.events.append(event)


def message(topic: str, traceparent: str | None) -> OutboxMessage:
    return OutboxMessage(
        id=uuid4(),
        topic=topic,
        key="order-1",
        type="OrderCreated",
        payload={"order_id": "1"},
        traceparent=traceparent,
    )


async def relay_and_consume(topic: str, msg: OutboxMessage) -> Recorder:
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    recorder = Recorder()
    consumer = KafkaEventConsumer(BOOTSTRAP, topic, f"g-{uuid4().hex[:6]}", recorder)
    stop = asyncio.Event()
    try:
        await OutboxRelay(lambda: FakeUow(FakeStore([msg])), publisher).run_once()
        await consumer.start()
        task = asyncio.create_task(consumer.run(stop))
        try:
            await wait_until(lambda: len(recorder.events) == 1)
        finally:
            stop.set()
            await task
            await consumer.stop()
    finally:
        await publisher.stop()
    return recorder


async def test_trace_survives_outbox_relay_kafka_and_consumer(
    topics: tuple[str, str], spans: InMemorySpanExporter
):
    topic, _ = topics
    with get_tracer().start_as_current_span("POST /orders") as request_span:
        stored_traceparent = current_traceparent()
        trace_id = request_span.get_span_context().trace_id
    spans.clear()

    recorder = await relay_and_consume(topic, message(topic, stored_traceparent))

    assert recorder.trace_ids == [trace_id]
    finished = {s.name: s for s in spans.get_finished_spans()}
    publish = finished[f"{topic} publish"]
    process = finished[f"{topic} process"]
    assert publish.kind == SpanKind.PRODUCER
    assert process.kind == SpanKind.CONSUMER
    assert publish.context.trace_id == process.context.trace_id == trace_id
    assert publish.parent is not None
    assert format(publish.parent.span_id, "016x") == stored_traceparent.split("-")[2]
    assert process.parent is not None
    assert process.parent.span_id == publish.context.span_id
    assert process.attributes["marketplace.event_type"] == "OrderCreated"
    assert UUID(str(process.attributes["messaging.message.id"]))


async def test_context_published_inside_an_active_span_is_propagated_without_stored_value(
    topics: tuple[str, str], spans: InMemorySpanExporter
):
    topic, _ = topics
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    recorder = Recorder()
    consumer = KafkaEventConsumer(BOOTSTRAP, topic, f"g-{uuid4().hex[:6]}", recorder)
    stop = asyncio.Event()
    try:
        with get_tracer().start_as_current_span("direct") as span:
            expected = span.get_span_context().trace_id
            await publisher.publish(message(topic, None))
        await consumer.start()
        task = asyncio.create_task(consumer.run(stop))
        try:
            await wait_until(lambda: len(recorder.events) == 1)
        finally:
            stop.set()
            await task
            await consumer.stop()
    finally:
        await publisher.stop()

    assert recorder.trace_ids == [expected]


async def test_message_without_trace_starts_a_new_trace(
    topics: tuple[str, str], spans: InMemorySpanExporter
):
    topic, _ = topics

    recorder = await relay_and_consume(topic, message(topic, None))

    (trace_id,) = recorder.trace_ids
    process = next(s for s in spans.get_finished_spans() if s.name.endswith("process"))
    assert process.context.trace_id == trace_id
    assert trace_id != 0
