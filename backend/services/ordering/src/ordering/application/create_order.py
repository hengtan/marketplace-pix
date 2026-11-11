from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from uuid import UUID

from ordering.application.errors import IdempotencyKeyReused
from ordering.application.ports import UnitOfWork
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem


@dataclass(frozen=True, slots=True)
class CreateOrderItem:
    product_id: UUID
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True, slots=True)
class CreateOrderCommand:
    customer_id: UUID
    items: list[CreateOrderItem]
    currency: str = "BRL"

    def fingerprint(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CreateOrderResult:
    order_id: UUID
    replayed: bool


class CreateOrder:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, command: CreateOrderCommand, idempotency_key: str | None = None
    ) -> CreateOrderResult:
        items = [
            OrderItem(i.product_id, i.quantity, Money(i.unit_price_cents, command.currency))
            for i in command.items
        ]
        order = Order.create(command.customer_id, items)
        async with self._uow_factory() as uow:
            if idempotency_key is not None:
                existing = await uow.idempotency.claim(
                    idempotency_key, command.fingerprint(), order.id
                )
                if existing is not None:
                    if existing.request_hash != command.fingerprint():
                        raise IdempotencyKeyReused(idempotency_key)
                    return CreateOrderResult(existing.order_id, replayed=True)
            await uow.orders.add(order)
            await uow.outbox.add(order.pull_events())
            await uow.commit()
        return CreateOrderResult(order.id, replayed=False)
