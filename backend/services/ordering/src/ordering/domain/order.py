from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from ordering.domain.errors import InvalidOrder, InvalidStateTransition
from ordering.domain.events import DomainEvent, OrderCancelled, OrderCreated, OrderPaid
from ordering.domain.money import Money


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class OrderItem:
    product_id: UUID
    quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise InvalidOrder("quantity must be positive")

    @property
    def subtotal(self) -> Money:
        return self.unit_price.times(self.quantity)


@dataclass(slots=True)
class Order:
    id: UUID
    customer_id: UUID
    items: tuple[OrderItem, ...]
    status: OrderStatus = OrderStatus.PENDING
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(cls, customer_id: UUID, items: list[OrderItem]) -> Order:
        if not items:
            raise InvalidOrder("order needs at least one item")
        currencies = {i.unit_price.currency for i in items}
        if len(currencies) > 1:
            raise InvalidOrder("all items must share one currency")
        order = cls(id=uuid4(), customer_id=customer_id, items=tuple(items))
        total = order.total
        order._events.append(
            OrderCreated(
                order_id=order.id,
                customer_id=customer_id,
                total_cents=total.cents,
                currency=total.currency,
            )
        )
        return order

    @property
    def total(self) -> Money:
        currency = self.items[0].unit_price.currency
        total = Money.zero(currency)
        for item in self.items:
            total = total + item.subtotal
        return total

    def mark_paid(self) -> None:
        if self.status is OrderStatus.PAID:
            return
        if self.status is not OrderStatus.PENDING:
            raise InvalidStateTransition(f"cannot pay an order in {self.status}")
        self.status = OrderStatus.PAID
        self._events.append(OrderPaid(order_id=self.id))

    def cancel(self, reason: str) -> None:
        if self.status is OrderStatus.CANCELLED:
            return
        if self.status is not OrderStatus.PENDING:
            raise InvalidStateTransition(f"cannot cancel an order in {self.status}")
        self.status = OrderStatus.CANCELLED
        self._events.append(OrderCancelled(order_id=self.id, reason=reason))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
