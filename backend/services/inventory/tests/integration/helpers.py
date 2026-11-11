from uuid import UUID, uuid4

from marketplace_common.messaging import IncomingEvent
from sqlalchemy import func, select

from inventory.domain.reservation import ReservationItem, ReservationStatus
from inventory.infrastructure.db.models import OutboxEventModel, ReservationModel, StockModel


async def set_stock(session_factory, product_id: UUID, available: int, reserved: int = 0) -> None:
    async with session_factory() as session:
        session.add(StockModel(product_id=product_id, available=available, reserved=reserved))
        await session.commit()


async def stock_levels(session_factory, product_id: UUID) -> tuple[int, int]:
    async with session_factory() as session:
        row = await session.get(StockModel, product_id)
        assert row is not None
        return row.available, row.reserved


async def reservation_status(session_factory, order_id: UUID) -> ReservationStatus | None:
    async with session_factory() as session:
        row = await session.get(ReservationModel, order_id)
        return ReservationStatus(row.status) if row else None


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def outbox_types(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            select(OutboxEventModel.type).order_by(OutboxEventModel.created_at)
        )
        return [r[0] for r in rows]


def items(*pairs: tuple[UUID, int]) -> list[ReservationItem]:
    return [ReservationItem(product_id, quantity) for product_id, quantity in pairs]


def order_created_event(order_id, product_id, quantity=1, event_id=None) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type="OrderCreated",
        key=str(order_id),
        payload={
            "order_id": str(order_id),
            "items": [
                {
                    "product_id": str(product_id),
                    "merchant_id": str(uuid4()),
                    "quantity": quantity,
                    "unit_price_cents": 1000,
                }
            ],
        },
    )
