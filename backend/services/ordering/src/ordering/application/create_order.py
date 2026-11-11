from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from uuid import UUID

from ordering.application.errors import IdempotencyKeyReused, UnknownProduct
from ordering.application.ports import CatalogGateway, UnitOfWork
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem


@dataclass(frozen=True, slots=True)
class CreateOrderItem:
    product_id: UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class CreateOrderCommand:
    customer_id: UUID
    customer_name: str
    customer_email: str
    items: list[CreateOrderItem]
    owner_id: UUID | None = None

    def fingerprint(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CreateOrderResult:
    order_id: UUID
    replayed: bool


class CreateOrder:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], catalog: CatalogGateway) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog

    async def execute(
        self, command: CreateOrderCommand, idempotency_key: str | None = None
    ) -> CreateOrderResult:
        order = await self._build_order(command)
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

    async def _build_order(self, command: CreateOrderCommand) -> Order:
        quantities: dict[UUID, int] = {}
        for item in command.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        products = {p.id: p for p in await self._catalog.get_products(list(quantities))}
        missing = [str(pid) for pid in quantities if pid not in products]
        if missing:
            raise UnknownProduct(", ".join(missing))
        items = [
            OrderItem(
                product_id=pid,
                merchant_id=products[pid].merchant_id,
                quantity=quantity,
                unit_price=Money(products[pid].price_cents, products[pid].currency),
            )
            for pid, quantity in quantities.items()
        ]
        return Order.create(
            command.customer_id,
            items,
            command.customer_name,
            command.customer_email,
            owner_id=command.owner_id,
        )
