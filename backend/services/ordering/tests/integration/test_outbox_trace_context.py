from uuid import uuid4

from marketplace_common.observability import current_traceparent, get_tracer
from sqlalchemy import select

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.infrastructure.db.models import OutboxEventModel
from tests.fakes import FakeCatalog

PRODUCT = uuid4()


def command() -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=uuid4(),
        customer_name="Maria Souza",
        customer_email="maria@example.com",
        items=[CreateOrderItem(PRODUCT, 1)],
    )


async def test_outbox_event_stores_the_active_trace_context(uow_factory, session_factory):
    with get_tracer().start_as_current_span("POST /orders"):
        expected = current_traceparent()
        await CreateOrder(uow_factory, FakeCatalog({PRODUCT: 1000})).execute(command())

    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert expected is not None
    assert row.traceparent == expected
    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
        assert message.traceparent == expected
        assert await uow.outbox_store.count_pending() == 1


async def test_outbox_event_without_active_span_has_no_trace_context(uow_factory):
    await CreateOrder(uow_factory, FakeCatalog({PRODUCT: 1000})).execute(command())

    async with uow_factory() as uow:
        (message,) = await uow.outbox_store.fetch_pending(10)
    assert message.traceparent is None
