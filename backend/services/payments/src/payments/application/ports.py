from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from payments.domain.events import DomainEvent
from payments.domain.money import Money
from payments.domain.payment import Payment


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: UUID
    type: str
    key: str
    payload: dict[str, Any]


class ChargeStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class PspCharge:
    id: str
    pix_code: str
    expires_at: datetime


class PspGateway(Protocol):
    async def create_charge(
        self, reference: str, amount: Money, expires_at: datetime
    ) -> PspCharge: ...

    async def get_charge_status(self, charge_id: str) -> ChargeStatus: ...

    async def cancel_charge(self, charge_id: str) -> bool: ...


class PaymentRepository(Protocol):
    async def add(self, payment: Payment) -> None: ...

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Payment | None: ...

    async def get_by_psp_charge_id(self, charge_id: str, lock: bool = False) -> Payment | None: ...

    async def save(self, payment: Payment) -> None: ...

    async def fetch_expired(self, now: datetime, limit: int) -> list[Payment]: ...


class InboxStore(Protocol):
    async def claim(self, message_id: UUID, consumer: str) -> bool: ...


class OutboxWriter(Protocol):
    async def add(self, events: list[DomainEvent]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def payments(self) -> PaymentRepository: ...

    @property
    def outbox(self) -> OutboxWriter: ...

    @property
    def inbox(self) -> InboxStore: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    topic: str
    key: str
    type: str
    payload: dict[str, Any]


class OutboxStore(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxMessage]: ...

    async def mark_published(self, ids: list[UUID]) -> None: ...


class MessagePublisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None: ...


class RelayUnitOfWork(Protocol):
    @property
    def outbox_store(self) -> OutboxStore: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
