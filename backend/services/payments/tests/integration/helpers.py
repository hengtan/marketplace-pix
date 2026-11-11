from uuid import uuid4

from sqlalchemy import func, select

from payments.application.ports import IncomingEvent


def order_created(order_id=None, event_id=None, total=4480) -> IncomingEvent:
    order_id = order_id or uuid4()
    return IncomingEvent(
        id=event_id or uuid4(),
        type="OrderCreated",
        key=str(order_id),
        payload={"order_id": str(order_id), "total_cents": total, "currency": "BRL"},
    )


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))
