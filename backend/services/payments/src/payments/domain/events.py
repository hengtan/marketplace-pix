from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    order_id: UUID
    payment_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentCreated(DomainEvent):
    amount_cents: int
    currency: str
    pix_code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentConfirmed(DomainEvent):
    amount_cents: int
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentExpired(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentCancelled(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentRefunded(DomainEvent):
    amount_cents: int
    currency: str
    reason: str
