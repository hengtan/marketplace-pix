from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    order_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class OrderCreatedItem:
    product_id: UUID
    merchant_id: UUID
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCreated(DomainEvent):
    customer_id: UUID
    customer_name: str
    customer_email: str
    total_cents: int
    currency: str
    items: tuple[OrderCreatedItem, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPaid(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled(DomainEvent):
    reason: str
