from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ordering.domain.errors import InvalidOrder, InvalidStateTransition
from ordering.domain.events import (
    DomainEvent,
    OrderCancelled,
    OrderCreated,
    OrderCreatedItem,
    OrderPaid,
)
from ordering.domain.money import Money


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class OrderItem:
    product_id: UUID
    merchant_id: UUID
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
    customer_name: str
    customer_email: str
    items: tuple[OrderItem, ...]
    status: OrderStatus = OrderStatus.PENDING
    cancel_reason: str | None = None
    created_at: datetime | None = None
    owner_id: UUID | None = None
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        customer_id: UUID,
        items: list[OrderItem],
        customer_name: str,
        customer_email: str,
        owner_id: UUID | None = None,
    ) -> Order:
        if not items:
            raise InvalidOrder("order needs at least one item")
        if not customer_name.strip():
            raise InvalidOrder("customer name is required")
        if "@" not in customer_email:
            raise InvalidOrder("customer email is invalid")
        currencies = {i.unit_price.currency for i in items}
        if len(currencies) > 1:
            raise InvalidOrder("all items must share one currency")
        order = cls(
            id=uuid4(),
            customer_id=customer_id,
            customer_name=customer_name.strip(),
            customer_email=customer_email.strip(),
            items=tuple(items),
            owner_id=owner_id,
        )
        total = order.total
        order._events.append(
            OrderCreated(
                order_id=order.id,
                customer_id=customer_id,
                customer_name=order.customer_name,
                customer_email=order.customer_email,
                total_cents=total.cents,
                currency=total.currency,
                items=tuple(
                    OrderCreatedItem(
                        product_id=i.product_id,
                        merchant_id=i.merchant_id,
                        quantity=i.quantity,
                        unit_price_cents=i.unit_price.cents,
                    )
                    for i in order.items
                ),
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
        self.cancel_reason = reason
        self._events.append(OrderCancelled(order_id=self.id, reason=reason))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events

    def is_owned_by(self, user_id: UUID) -> bool:
        return self.owner_id is not None and self.owner_id == user_id

    @property
    def is_guest(self) -> bool:
        return self.owner_id is None

    def items_of(self, merchant_id: UUID) -> tuple[OrderItem, ...]:
        return tuple(i for i in self.items if i.merchant_id == merchant_id)
