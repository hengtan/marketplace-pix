from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    product_id: UUID
    merchant_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductCreated(DomainEvent):
    slug: str
    name: str
    category: str
    price_cents: int
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductUpdated(DomainEvent):
    slug: str
    name: str
    category: str
    price_cents: int
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductPriceChanged(DomainEvent):
    old_price_cents: int
    new_price_cents: int
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductDeactivated(DomainEvent):
    pass
