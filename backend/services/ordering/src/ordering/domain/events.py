from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    order_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCreated(DomainEvent):
    customer_id: UUID
    total_cents: int
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPaid(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled(DomainEvent):
    reason: str
