from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ledger.domain.errors import InvalidOrderProjection
from ledger.domain.money import Money


@dataclass(frozen=True, slots=True)
class ProjectedItem:
    product_id: UUID
    merchant_id: UUID
    quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise InvalidOrderProjection("quantity must be positive")
        if self.unit_price.cents <= 0:
            raise InvalidOrderProjection("unit price must be positive")

    @property
    def subtotal(self) -> Money:
        return self.unit_price.times(self.quantity)


@dataclass(frozen=True, slots=True)
class OrderProjection:
    order_id: UUID
    currency: str
    items: tuple[ProjectedItem, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.items:
            raise InvalidOrderProjection("an order needs at least one item")
        if any(i.unit_price.currency != self.currency for i in self.items):
            raise InvalidOrderProjection("all items must share the order currency")

    @property
    def total(self) -> Money:
        total = Money.zero(self.currency)
        for item in self.items:
            total = total + item.subtotal
        return total

    def merchant_subtotals(self) -> dict[UUID, Money]:
        subtotals: dict[UUID, Money] = {}
        for item in self.items:
            current = subtotals.get(item.merchant_id, Money.zero(self.currency))
            subtotals[item.merchant_id] = current + item.subtotal
        return subtotals
