from uuid import UUID

from ordering.application.ports import IdempotencyRecord
from ordering.domain.events import DomainEvent
from ordering.domain.order import Order


class FakeDatabase:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}
        self.events: list[DomainEvent] = []
        self.keys: dict[str, IdempotencyRecord] = {}


class FakeOrders:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add(self, order: Order) -> None:
        self._uow.staged_orders.append(order)

    async def get(self, order_id: UUID) -> Order | None:
        return self._uow.db.orders.get(order_id)


class FakeOutbox:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add(self, events: list[DomainEvent]) -> None:
        self._uow.staged_events.extend(events)


class FakeIdempotency:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def claim(self, key: str, request_hash: str, order_id: UUID) -> IdempotencyRecord | None:
        existing = self._uow.db.keys.get(key) or self._uow.staged_keys.get(key)
        if existing is not None:
            return existing
        self._uow.staged_keys[key] = IdempotencyRecord(key, request_hash, order_id)
        return None


class FakeUow:
    def __init__(self, db: FakeDatabase | None = None) -> None:
        self.db = db or FakeDatabase()
        self.staged_orders: list[Order] = []
        self.staged_events: list[DomainEvent] = []
        self.staged_keys: dict[str, IdempotencyRecord] = {}
        self.committed = False
        self.orders = FakeOrders(self)
        self.outbox = FakeOutbox(self)
        self.idempotency = FakeIdempotency(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.staged_orders, self.staged_events, self.staged_keys = [], [], {}

    async def commit(self) -> None:
        for order in self.staged_orders:
            self.db.orders[order.id] = order
        self.db.events.extend(self.staged_events)
        self.db.keys.update(self.staged_keys)
        self.staged_orders, self.staged_events, self.staged_keys = [], [], {}
        self.committed = True
