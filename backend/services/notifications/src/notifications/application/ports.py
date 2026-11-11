from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from notifications.domain.notification import Notification, NotificationKind
from notifications.domain.order_projection import OrderProjection


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: UUID
    type: str
    key: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DailyStats:
    created: int
    paid: int
    cancelled: int
    paid_cents: int


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    stats: DailyStats
    currency: str = "BRL"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    html: str
    text: str


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to_email: str
    to_name: str
    subject: str
    html: str
    text: str


class NotificationRepository(Protocol):
    async def add(self, notification: Notification) -> bool: ...

    async def get(self, notification_id: UUID) -> Notification | None: ...

    async def get_for_sending(self, notification_id: UUID) -> Notification | None: ...

    async def save(self, notification: Notification) -> None: ...

    async def list_page(
        self, customer_id: UUID | None, page: int, page_size: int
    ) -> tuple[list[Notification], int]: ...

    async def fetch_stale_queued(self, before: datetime, limit: int) -> list[Notification]: ...

    async def touch(self, ids: list[UUID], now: datetime) -> None: ...


class OrderProjectionRepository(Protocol):
    async def add(self, order: OrderProjection) -> None: ...

    async def get(self, order_id: UUID) -> OrderProjection | None: ...

    async def save(self, order: OrderProjection) -> None: ...

    async def stats_between(self, start: datetime, end: datetime) -> DailyStats: ...


class InboxStore(Protocol):
    async def claim(self, message_id: UUID, consumer: str) -> bool: ...


class UnitOfWork(Protocol):
    @property
    def notifications(self) -> NotificationRepository: ...

    @property
    def orders(self) -> OrderProjectionRepository: ...

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


class EmailSender(Protocol):
    async def send(self, email: OutgoingEmail) -> None: ...


class EmailRenderer(Protocol):
    def render(self, kind: NotificationKind, context: dict[str, Any]) -> RenderedEmail: ...

    def render_daily_summary(self, summary: DailySummary) -> RenderedEmail: ...


class NotificationQueue(Protocol):
    async def enqueue(self, notification_id: UUID) -> None: ...
