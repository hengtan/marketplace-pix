import copy
from datetime import datetime
from uuid import UUID

from notifications.application.errors import SendError
from notifications.application.ports import DailyStats, OutgoingEmail
from notifications.domain.notification import Notification, NotificationStatus
from notifications.domain.order_projection import OrderProjection


class FakeDatabase:
    def __init__(self) -> None:
        self.notifications: dict[UUID, Notification] = {}
        self.orders: dict[UUID, OrderProjection] = {}
        self.inbox: set[tuple[UUID, str]] = set()
        self.locked: set[UUID] = set()

    def by_kind(self) -> list[str]:
        return sorted(n.kind.value for n in self.notifications.values())


class FakeNotifications:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    def _all(self) -> dict[UUID, Notification]:
        return {**self._uow.db.notifications, **self._uow.staged_notifications}

    async def add(self, notification: Notification) -> bool:
        for existing in self._all().values():
            if (existing.event_id, existing.kind) == (notification.event_id, notification.kind):
                return False
        self._uow.staged_notifications[notification.id] = copy.deepcopy(notification)
        return True

    async def get(self, notification_id: UUID) -> Notification | None:
        found = self._all().get(notification_id)
        return copy.deepcopy(found) if found else None

    async def get_for_sending(self, notification_id: UUID) -> Notification | None:
        if notification_id in self._uow.db.locked:
            return None
        return await self.get(notification_id)

    async def save(self, notification: Notification) -> None:
        self._uow.staged_notifications[notification.id] = copy.deepcopy(notification)

    async def list_page(
        self, customer_id: UUID | None, page: int, page_size: int
    ) -> tuple[list[Notification], int]:
        rows = [
            copy.deepcopy(n)
            for n in self._all().values()
            if customer_id is None or n.recipient.customer_id == customer_id
        ]
        rows.sort(key=lambda n: n.created_at, reverse=True)
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    async def fetch_stale_queued(self, before: datetime, limit: int) -> list[Notification]:
        due = [
            copy.deepcopy(n)
            for n in self._all().values()
            if n.status is NotificationStatus.QUEUED and n.next_attempt_at <= before
        ]
        due.sort(key=lambda n: n.next_attempt_at)
        return due[:limit]

    async def touch(self, ids: list[UUID], now: datetime) -> None:
        for notification_id in ids:
            notification = copy.deepcopy(self._all()[notification_id])
            notification.next_attempt_at = now
            self._uow.staged_notifications[notification_id] = notification


class FakeOrders:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    def _all(self) -> dict[UUID, OrderProjection]:
        return {**self._uow.db.orders, **self._uow.staged_orders}

    async def add(self, order: OrderProjection) -> None:
        self._uow.staged_orders[order.order_id] = copy.deepcopy(order)

    async def get(self, order_id: UUID) -> OrderProjection | None:
        found = self._all().get(order_id)
        return copy.deepcopy(found) if found else None

    async def save(self, order: OrderProjection) -> None:
        self._uow.staged_orders[order.order_id] = copy.deepcopy(order)

    async def stats_between(self, start: datetime, end: datetime) -> DailyStats:
        orders = list(self._all().values())
        paid = [o for o in orders if o.paid_at and start <= o.paid_at < end]
        return DailyStats(
            created=sum(1 for o in orders if start <= o.created_at < end),
            paid=len(paid),
            cancelled=sum(1 for o in orders if o.cancelled_at and start <= o.cancelled_at < end),
            paid_cents=sum(o.total_cents for o in paid),
        )


class FakeInbox:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def claim(self, message_id: UUID, consumer: str) -> bool:
        key = (message_id, consumer)
        if key in self._uow.db.inbox or key in self._uow.staged_inbox:
            return False
        self._uow.staged_inbox.add(key)
        return True


class FakeUow:
    def __init__(self, db: FakeDatabase | None = None) -> None:
        self.db = db or FakeDatabase()
        self.staged_notifications: dict[UUID, Notification] = {}
        self.staged_orders: dict[UUID, OrderProjection] = {}
        self.staged_inbox: set[tuple[UUID, str]] = set()
        self.notifications = FakeNotifications(self)
        self.orders = FakeOrders(self)
        self.inbox = FakeInbox(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._discard()

    def _discard(self) -> None:
        self.staged_notifications, self.staged_orders, self.staged_inbox = {}, {}, set()

    async def commit(self) -> None:
        self.db.notifications.update(self.staged_notifications)
        self.db.orders.update(self.staged_orders)
        self.db.inbox.update(self.staged_inbox)
        self._discard()


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []
        self.fail = False

    async def enqueue(self, notification_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("broker is down")
        self.enqueued.append(notification_id)


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.failures: list[Exception] = []

    async def send(self, email: OutgoingEmail) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(email)

    def fail_times(self, count: int, permanent: bool = False) -> None:
        self.failures = [
            SendError("smtp refused", permanent=permanent)
            if permanent
            else ConnectionError("smtp down")
            for _ in range(count)
        ]
