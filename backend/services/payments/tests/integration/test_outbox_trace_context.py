from marketplace_common.observability import current_traceparent, get_tracer

from payments.application.handle_order_event import HandleOrderEvent
from tests.integration.helpers import order_created


async def test_outbox_event_stores_the_active_trace_context(uow_factory, psp):
    with get_tracer().start_as_current_span("orders.events process"):
        expected = current_traceparent()
        await HandleOrderEvent(uow_factory, psp).handle(order_created())

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
        assert expected is not None
        assert message.traceparent == expected
        assert await uow.outbox_store.count_pending() == 1


async def test_outbox_event_without_active_span_has_no_trace_context(uow_factory, psp):
    await HandleOrderEvent(uow_factory, psp).handle(order_created())

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
    assert message.traceparent is None
