import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from marketplace_common.messaging import IncomingEvent
from sqlalchemy import func, select, text

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.handle_saga_event import HandleResult, HandleSagaEvent
from ordering.application.saga_timeout import SagaTimeoutManager
from ordering.infrastructure.db.models import OrderAuditModel, OrderModel, OutboxEventModel
from tests.fakes import FakeCatalog

PRODUCT = uuid4()
TIMEOUT = timedelta(minutes=45)


async def place_order(uow_factory) -> UUID:
    result = await CreateOrder(uow_factory, FakeCatalog({PRODUCT: 1990})).execute(
        CreateOrderCommand(
            customer_id=uuid4(),
            customer_name="Maria",
            customer_email="maria@example.com",
            items=[CreateOrderItem(PRODUCT, 2)],
        ),
        idempotency_key=uuid4().hex,
    )
    return result.order_id


async def age(session_factory, order_id: UUID, minutes: int) -> None:
    async with session_factory() as session:
        await session.execute(
            text("update orders set created_at = :t where id = :id"),
            {"t": datetime.now(UTC) - timedelta(minutes=minutes), "id": order_id},
        )
        await session.commit()


async def events_of(session_factory, order_id: UUID) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            select(OutboxEventModel.type).where(OutboxEventModel.aggregate_id == order_id)
        )
    return sorted(rows.scalars().all())


async def status_of(session_factory, order_id: UUID) -> str:
    async with session_factory() as session:
        return (await session.get(OrderModel, order_id)).status


def payment_confirmed(order_id: UUID, payment_id: UUID | None = None) -> IncomingEvent:
    return IncomingEvent(
        id=uuid4(),
        type="PaymentConfirmed",
        key=str(order_id),
        payload={
            "order_id": str(order_id),
            "payment_id": str(payment_id or uuid4()),
            "amount_cents": 3980,
            "currency": "BRL",
        },
    )


async def test_payment_that_never_arrives_cancels_the_order_once(uow_factory, session_factory):
    order_id = await place_order(uow_factory)
    manager = SagaTimeoutManager(uow_factory, TIMEOUT)

    assert await manager.run_once() == 0
    await age(session_factory, order_id, 50)
    assert await manager.run_once() == 1
    assert await manager.run_once() == 0

    assert await status_of(session_factory, order_id) == "CANCELLED"
    assert await events_of(session_factory, order_id) == ["OrderCancelled", "OrderCreated"]
    async with session_factory() as session:
        audit = (await session.execute(select(OrderAuditModel))).scalar_one()
        assert (audit.order_id, audit.kind) == (order_id, "SAGA_TIMEOUT")
        reason = await session.scalar(
            select(OrderModel.cancel_reason).where(OrderModel.id == order_id)
        )
    assert reason == "saga timeout"


async def test_concurrent_sweeps_cancel_each_order_exactly_once(uow_factory, session_factory):
    ids = [await place_order(uow_factory) for _ in range(8)]
    for order_id in ids:
        await age(session_factory, order_id, 90)
    managers = [SagaTimeoutManager(uow_factory, TIMEOUT, batch_size=3) for _ in range(4)]

    totals = 0
    for _ in range(4):
        totals += sum(await asyncio.gather(*(m.run_once() for m in managers)))

    assert totals == 8
    async with session_factory() as session:
        cancelled = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(OutboxEventModel.type == "OrderCancelled")
        )
        audits = await session.scalar(select(func.count()).select_from(OrderAuditModel))
    assert (cancelled, audits) == (8, 8)


async def test_payment_after_the_timeout_is_refunded_not_applied(uow_factory, session_factory):
    order_id = await place_order(uow_factory)
    await age(session_factory, order_id, 60)
    await SagaTimeoutManager(uow_factory, TIMEOUT).run_once()
    handler = HandleSagaEvent(uow_factory)
    payment_id = uuid4()

    first = await handler.handle(payment_confirmed(order_id, payment_id))
    again = await handler.handle(payment_confirmed(order_id, payment_id))

    assert first is again is HandleResult.REFUND_REQUESTED
    assert await status_of(session_factory, order_id) == "CANCELLED"
    assert await events_of(session_factory, order_id) == [
        "OrderCancelled",
        "OrderCreated",
        "PaymentRefundRequested",
    ]
    async with session_factory() as session:
        audits = (
            (
                await session.execute(
                    select(OrderAuditModel).where(OrderAuditModel.kind == "LATE_PAYMENT")
                )
            )
            .scalars()
            .all()
        )
        refund = (
            await session.execute(
                select(OutboxEventModel).where(OutboxEventModel.type == "PaymentRefundRequested")
            )
        ).scalar_one()
    assert len(audits) == 1 and audits[0].reference_id == payment_id
    assert refund.payload["payment_id"] == str(payment_id)
    assert refund.payload["amount_cents"] == 3980
    assert refund.payload["schema_version"] == 1


async def test_payment_racing_the_timeout_never_leaves_a_paid_and_cancelled_order(
    uow_factory, session_factory
):
    outcomes = set()
    for _ in range(12):
        order_id = await place_order(uow_factory)
        await age(session_factory, order_id, 60)
        handler = HandleSagaEvent(uow_factory)
        manager = SagaTimeoutManager(uow_factory, TIMEOUT)

        await asyncio.gather(manager.run_once(), handler.handle(payment_confirmed(order_id)))

        status = await status_of(session_factory, order_id)
        events = await events_of(session_factory, order_id)
        outcomes.add(status)
        if status == "PAID":
            assert "OrderCancelled" not in events and "PaymentRefundRequested" not in events
        else:
            assert status == "CANCELLED"
            assert "OrderPaid" not in events
            assert events.count("PaymentRefundRequested") == 1
    assert outcomes <= {"PAID", "CANCELLED"}
