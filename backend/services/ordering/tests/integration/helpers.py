from uuid import UUID, uuid4

from sqlalchemy import func, select

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.ports import IncomingEvent
from ordering.infrastructure.db.models import OrderModel, OutboxEventModel


async def make_order(uow_factory) -> UUID:
    command = CreateOrderCommand(uuid4(), [CreateOrderItem(uuid4(), 1, 4480)])
    return (await CreateOrder(uow_factory).execute(command)).order_id


def payment_event(order_id: UUID, type_: str = "PaymentConfirmed", event_id=None) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type=type_,
        key=str(order_id),
        payload={"order_id": str(order_id), "payment_id": str(uuid4())},
    )


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def order_status(session_factory, order_id: UUID) -> str:
    async with session_factory() as session:
        return (await session.get(OrderModel, order_id)).status


async def outbox_types(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = (await session.execute(select(OutboxEventModel))).scalars().all()
    return sorted(r.type for r in rows)
