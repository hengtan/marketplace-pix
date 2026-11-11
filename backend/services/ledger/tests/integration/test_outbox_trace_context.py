from uuid import uuid4

from marketplace_common.observability import current_traceparent, get_tracer

from tests.builders import order_created, payment_confirmed
from tests.integration.helpers import order_id_of


async def test_outbox_event_stores_the_active_trace_context(
    order_handler, payment_handler, uow_factory
):
    event = order_created(lines=[(uuid4(), 1, 10000)])
    await order_handler.handle(event)

    with get_tracer().start_as_current_span("payments.events process"):
        expected = current_traceparent()
        await payment_handler.handle(
            payment_confirmed(order_id_of(event), event.payload["total_cents"])
        )

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
        assert expected is not None
        assert message.traceparent == expected
        assert await uow.outbox_store.count_pending() == 1
