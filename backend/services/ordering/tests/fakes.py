import copy
from uuid import NAMESPACE_URL, UUID, uuid5

from ordering.application.errors import CatalogUnavailable
from ordering.application.ports import CatalogProduct, IdempotencyRecord, OwnerScope
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

    async def list_by_customer(
        self, customer_id: UUID, page: int, page_size: int, scope: OwnerScope = OwnerScope.GUEST
    ) -> tuple[list[Order], int]:
        mine = [o for o in self._uow.db.orders.values() if o.customer_id == customer_id]
        if scope is OwnerScope.OWNED:
            mine = [o for o in mine if o.owner_id == customer_id]
        elif scope is OwnerScope.GUEST:
            mine = [o for o in mine if o.owner_id is None]
        mine.reverse()
        start = (page - 1) * page_size
        return [copy.deepcopy(o) for o in mine[start : start + page_size]], len(mine)

    async def list_by_merchant(
        self, merchant_id: UUID, page: int, page_size: int
    ) -> tuple[list[Order], int]:
        mine = [o for o in self._uow.db.orders.values() if o.items_of(merchant_id)]
        mine.reverse()
        start = (page - 1) * page_size
        return [copy.deepcopy(o) for o in mine[start : start + page_size]], len(mine)

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


def merchant_of(product_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"test-merchant-of:{product_id}")


class FakeCatalog:
    def __init__(self, prices: dict[UUID, int] | None = None, default_price: int = 1990) -> None:
        self.prices = dict(prices or {})
        self.default_price = default_price
        self.unknown: set[UUID] = set()
        self.fail = False
        self.calls = 0

    async def get_products(self, ids: list[UUID]) -> list[CatalogProduct]:
        self.calls += 1
        if self.fail:
            raise CatalogUnavailable("catalog is down")
        return [
            CatalogProduct(
                id=i,
                name=f"Produto {str(i)[:4]}",
                price_cents=self.prices.get(i, self.default_price),
                currency="BRL",
                merchant_id=merchant_of(i),
            )
            for i in ids
            if i not in self.unknown
        ]
