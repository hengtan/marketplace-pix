import copy
from uuid import UUID

from ordering.application.ports import IdempotencyRecord
from ordering.domain.events import DomainEvent
from ordering.domain.order import Order


class FakeDatabase:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}
        self.events: list[DomainEvent] = []
        self.keys: dict[str, IdempotencyRecord] = {}
        self.inbox: set[tuple[UUID, str]] = set()


def persisted(order: Order) -> Order:
    clone = copy.deepcopy(order)
    clone._events = []
    return clone


class FakeOrders:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add(self, order: Order) -> None:
        self._uow.staged_orders[order.id] = persisted(order)

    async def save(self, order: Order) -> None:
        self._uow.staged_orders[order.id] = persisted(order)

    async def get(self, order_id: UUID, lock: bool = False) -> Order | None:
        order = self._uow.staged_orders.get(order_id) or self._uow.db.orders.get(order_id)
        return copy.deepcopy(order) if order is not None else None


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
        self.staged_orders: dict[UUID, Order] = {}
        self.staged_events: list[DomainEvent] = []
        self.staged_keys: dict[str, IdempotencyRecord] = {}
        self.staged_inbox: set[tuple[UUID, str]] = set()
        self.committed = False
        self.orders = FakeOrders(self)
        self.outbox = FakeOutbox(self)
        self.idempotency = FakeIdempotency(self)
        self.inbox = FakeInbox(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._discard()

    def _discard(self) -> None:
        self.staged_orders, self.staged_events = {}, []
        self.staged_keys, self.staged_inbox = {}, set()

    async def commit(self) -> None:
        self.db.orders.update(self.staged_orders)
        self.db.events.extend(self.staged_events)
        self.db.keys.update(self.staged_keys)
        self.db.inbox.update(self.staged_inbox)
        self._discard()
        self.committed = True
