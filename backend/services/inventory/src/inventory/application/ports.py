from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from inventory.domain.events import DomainEvent
from inventory.domain.reservation import Reservation
from inventory.domain.stock import Stock


class StockRepository(Protocol):
    async def get_many(
        self, product_ids: Collection[UUID], lock: bool = False
    ) -> dict[UUID, Stock]: ...

    async def save(self, stock: Stock) -> None: ...

    async def list_all(self, limit: int) -> list[Stock]: ...

    async def list_by_merchant(self, merchant_id: UUID, limit: int) -> list[Stock]: ...


class ReservationRepository(Protocol):
    async def add(self, reservation: Reservation) -> None: ...

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Reservation | None: ...

    async def save(self, reservation: Reservation) -> None: ...

    async def fetch_expired(self, now: datetime, limit: int) -> list[Reservation]: ...


class InboxStore(Protocol):
    async def claim(self, message_id: UUID, consumer: str) -> bool: ...


class OutboxWriter(Protocol):
    async def add(self, events: list[DomainEvent]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def stocks(self) -> StockRepository: ...

    @property
    def reservations(self) -> ReservationRepository: ...

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
