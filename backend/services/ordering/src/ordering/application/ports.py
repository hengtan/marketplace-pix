from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from ordering.domain.events import DomainEvent
from ordering.domain.order import Order


class OrderRepository(Protocol):
    async def add(self, order: Order) -> None: ...

    async def get(self, order_id: UUID, lock: bool = False) -> Order | None: ...

    async def save(self, order: Order) -> None: ...


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: UUID
    type: str
    key: str
    payload: dict[str, Any]


class InboxStore(Protocol):
    async def claim(self, message_id: UUID, consumer: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    request_hash: str
    order_id: UUID


class IdempotencyStore(Protocol):
    async def claim(
        self, key: str, request_hash: str, order_id: UUID
    ) -> IdempotencyRecord | None: ...


class OutboxWriter(Protocol):
    async def add(self, events: list[DomainEvent]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def orders(self) -> OrderRepository: ...

    @property
    def outbox(self) -> OutboxWriter: ...

    @property
    def idempotency(self) -> IdempotencyStore: ...

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
