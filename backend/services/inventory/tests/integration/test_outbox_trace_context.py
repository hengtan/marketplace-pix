from datetime import timedelta
from uuid import uuid4

from marketplace_common.observability import current_traceparent, get_tracer

from inventory.application.reserve_stock import ReserveStock
from tests.integration.helpers import items, set_stock


async def test_outbox_event_stores_the_active_trace_context(uow_factory, session_factory):
    product = uuid4()
    await set_stock(session_factory, product, 10)

    with get_tracer().start_as_current_span("orders.events process"):
        expected = current_traceparent()
        await ReserveStock(uow_factory, timedelta(minutes=35)).execute(uuid4(), items((product, 1)))

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
        assert expected is not None
        assert message.traceparent == expected
        assert await uow.outbox_store.count_pending() == 1


async def test_outbox_event_without_active_span_has_no_trace_context(uow_factory, session_factory):
    product = uuid4()
    await set_stock(session_factory, product, 10)

    await ReserveStock(uow_factory, timedelta(minutes=35)).execute(uuid4(), items((product, 1)))

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
    assert message.traceparent is None
