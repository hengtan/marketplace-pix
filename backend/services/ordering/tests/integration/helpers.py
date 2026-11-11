from uuid import UUID, uuid4

from marketplace_common.messaging import IncomingEvent
from sqlalchemy import func, select

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.infrastructure.db.models import OrderModel, OutboxEventModel
from tests.fakes import FakeCatalog


async def make_order(uow_factory, customer_id: UUID | None = None) -> UUID:
    product_id = uuid4()
    command = CreateOrderCommand(
        customer_id or uuid4(),
        "Maria Souza",
        "maria@example.com",
        [CreateOrderItem(product_id, 1)],
    )
    catalog = FakeCatalog({product_id: 4480})
    return (await CreateOrder(uow_factory, catalog).execute(command)).order_id


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
