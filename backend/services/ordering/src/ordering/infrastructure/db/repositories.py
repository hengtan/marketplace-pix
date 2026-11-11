from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ordering.application.ports import OwnerScope
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from ordering.infrastructure.db.models import OrderItemModel, OrderModel


def _to_domain(model: OrderModel) -> Order:
    return Order(
        id=model.id,
        customer_id=model.customer_id,
        customer_name=model.customer_name,
        customer_email=model.customer_email,
        items=tuple(
            OrderItem(
                product_id=i.product_id,
                merchant_id=i.merchant_id,
                quantity=i.quantity,
                unit_price=Money(i.unit_price_cents, model.currency),
            )
            for i in model.items
        ),
        status=OrderStatus(model.status),
        cancel_reason=model.cancel_reason,
        created_at=model.created_at,
        owner_id=model.owner_id,
    )


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        self._session.add(
            OrderModel(
                id=order.id,
                customer_id=order.customer_id,
                owner_id=order.owner_id,
                customer_name=order.customer_name,
                customer_email=order.customer_email,
                status=order.status.value,
                cancel_reason=order.cancel_reason,
                currency=order.total.currency,
                total_cents=order.total.cents,
                items=[
                    OrderItemModel(
                        position=position,
                        product_id=item.product_id,
                        merchant_id=item.merchant_id,
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
        return None if model is None else _to_domain(model)

    async def save(self, order: Order) -> None:
        model = await self._session.get(OrderModel, order.id)
        if model is None:
            raise LookupError(f"order {order.id} not found")
        model.status = order.status.value
        model.cancel_reason = order.cancel_reason

    async def list_by_customer(
        self, customer_id: UUID, page: int, page_size: int, scope: OwnerScope
    ) -> tuple[list[Order], int]:
        condition = [OrderModel.customer_id == customer_id]
        if scope is OwnerScope.OWNED:
            condition.append(OrderModel.owner_id == customer_id)
        elif scope is OwnerScope.GUEST:
            condition.append(OrderModel.owner_id.is_(None))
        return await self._page(condition, page, page_size)

    async def fetch_stuck_pending(self, created_before: datetime, limit: int) -> list[Order]:
        stmt = (
            select(OrderModel)
            .where(OrderModel.status == OrderStatus.PENDING.value)
            .where(OrderModel.created_at < created_before)
            .options(selectinload(OrderModel.items))
            .order_by(OrderModel.created_at)
            .limit(limit)
            .with_for_update(of=OrderModel, skip_locked=True)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(m) for m in models]

    async def list_by_merchant(
        self, merchant_id: UUID, page: int, page_size: int
    ) -> tuple[list[Order], int]:
        mine = OrderModel.id.in_(
            select(OrderItemModel.order_id).where(OrderItemModel.merchant_id == merchant_id)
        )
        return await self._page([mine], page, page_size)

    async def _page(
        self, condition: list[ColumnElement[bool]], page: int, page_size: int
    ) -> tuple[list[Order], int]:
        total = await self._session.scalar(
            select(func.count()).select_from(OrderModel).where(*condition)
        )
        stmt = (
            select(OrderModel)
            .where(*condition)
            .options(selectinload(OrderModel.items))
            .order_by(OrderModel.created_at.desc(), OrderModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(m) for m in models], int(total or 0)
