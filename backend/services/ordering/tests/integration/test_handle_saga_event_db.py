import asyncio
from uuid import uuid4

from ordering.application.handle_saga_event import HandleSagaEvent
from ordering.infrastructure.db.models import InboxMessageModel
from tests.integration.helpers import count, make_order, order_status, outbox_types, payment_event


async def test_confirmation_marks_order_paid_and_writes_event_to_outbox(
    uow_factory, session_factory
):
    order_id = await make_order(uow_factory)

    result = await HandleSagaEvent(uow_factory).handle(payment_event(order_id))

    assert result.value == "PROCESSED"
    assert await order_status(session_factory, order_id) == "PAID"
    assert await outbox_types(session_factory) == ["OrderCreated", "OrderPaid"]


async def test_five_concurrent_deliveries_of_the_same_event_apply_once(
    uow_factory, session_factory
):
    order_id = await make_order(uow_factory)
    handler = HandleSagaEvent(uow_factory)
    event = payment_event(order_id)

    results = await asyncio.gather(*(handler.handle(event) for _ in range(5)))

    assert sorted(r.value for r in results) == ["DUPLICATE"] * 4 + ["PROCESSED"]
    assert await outbox_types(session_factory) == ["OrderCreated", "OrderPaid"]
    assert await count(session_factory, InboxMessageModel) == 1


async def test_confirmed_and_expired_racing_for_the_same_order_have_one_winner(
    uow_factory, session_factory
):
    order_id = await make_order(uow_factory)
    handler = HandleSagaEvent(uow_factory)

    results = await asyncio.gather(
        handler.handle(payment_event(order_id, "PaymentConfirmed")),
        handler.handle(payment_event(order_id, "PaymentExpired")),
    )

    assert sorted(r.value for r in results) == ["CONFLICT", "PROCESSED"]
    status = await order_status(session_factory, order_id)
    expected_event = "OrderPaid" if status == "PAID" else "OrderCancelled"
    assert status in {"PAID", "CANCELLED"}
    assert await outbox_types(session_factory) == sorted(["OrderCreated", expected_event])


async def test_event_for_unknown_order_is_ignored_without_side_effects(
    uow_factory, session_factory
):
    result = await HandleSagaEvent(uow_factory).handle(payment_event(uuid4()))

    assert result.value == "IGNORED"
    assert await count(session_factory, InboxMessageModel) == 0


async def test_stock_rejected_cancels_the_order_in_the_database(uow_factory, session_factory):
    order_id = await make_order(uow_factory)

    await HandleSagaEvent(uow_factory).handle(payment_event(order_id, "StockRejected"))

    assert await order_status(session_factory, order_id) == "CANCELLED"
    assert await outbox_types(session_factory) == ["OrderCancelled", "OrderCreated"]
