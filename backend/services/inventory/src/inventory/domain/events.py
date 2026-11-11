from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Shortage:
    product_id: UUID
    requested: int
    available: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    order_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReserved(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class StockRejected(DomainEvent):
    reason: str
    missing: list[Shortage]


@dataclass(frozen=True, slots=True, kw_only=True)
class StockCommitted(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class StockReleased(DomainEvent):
    reason: str
