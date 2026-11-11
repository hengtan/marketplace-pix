from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from ordering.infrastructure.db.models import OrderItemModel, OrderModel


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        self._session.add(
            OrderModel(
                id=order.id,
                customer_id=order.customer_id,
                status=order.status.value,
                currency=order.total.currency,
                total_cents=order.total.cents,
                items=[
                    OrderItemModel(
                        position=position,
                        product_id=item.product_id,
                        quantity=item.quantity,
                        unit_price_cents=item.unit_price.cents,
                    )
                    for position, item in enumerate(order.items)
                ],
            )
        )

    async def get(self, order_id: UUID, lock: bool = False) -> Order | None:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id)
            .options(selectinload(OrderModel.items))
        )
        if lock:
            stmt = stmt.with_for_update(of=OrderModel)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        return Order(
            id=model.id,
            customer_id=model.customer_id,
            items=tuple(
                OrderItem(i.product_id, i.quantity, Money(i.unit_price_cents, model.currency))
                for i in model.items
            ),
            status=OrderStatus(model.status),
        )

    async def save(self, order: Order) -> None:
        model = await self._session.get(OrderModel, order.id)
        if model is None:
            raise LookupError(f"order {order.id} not found")
        model.status = order.status.value
