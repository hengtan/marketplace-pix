import copy
from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from inventory.domain.events import DomainEvent
from inventory.domain.reservation import Reservation, ReservationStatus
from inventory.domain.stock import Stock


class FakeDatabase:
    def __init__(self) -> None:
        self.stocks: dict[UUID, Stock] = {}
        self.reservations: dict[UUID, Reservation] = {}
        self.events: list[DomainEvent] = []
        self.inbox: set[tuple[UUID, str]] = set()

    def seed(self, **levels: int) -> dict[str, UUID]:
        ids = {name: UUID(int=index + 1) for index, name in enumerate(levels)}
        for name, available in levels.items():
            self.stocks[ids[name]] = Stock(ids[name], available)
        return ids

    def event_types(self) -> list[str]:
        return [type(e).__name__ for e in self.events]


def persisted(reservation: Reservation) -> Reservation:
    clone = copy.deepcopy(reservation)
    clone._events = []
    return clone


class FakeStocks:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def get_many(
        self, product_ids: Collection[UUID], lock: bool = False
    ) -> dict[UUID, Stock]:
        merged = {**self._uow.db.stocks, **self._uow.staged_stocks}
        return {pid: copy.deepcopy(merged[pid]) for pid in product_ids if pid in merged}

    async def save(self, stock: Stock) -> None:
        self._uow.staged_stocks[stock.product_id] = copy.deepcopy(stock)

    async def list_all(self, limit: int) -> list[Stock]:
        merged = {**self._uow.db.stocks, **self._uow.staged_stocks}
        return [copy.deepcopy(s) for s in merged.values()][:limit]

    async def list_by_merchant(self, merchant_id: UUID, limit: int) -> list[Stock]:
        merged = {**self._uow.db.stocks, **self._uow.staged_stocks}
        mine = [s for s in merged.values() if s.merchant_id == merchant_id]
        return [copy.deepcopy(s) for s in mine][:limit]


class FakeReservations:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    def _all(self) -> list[Reservation]:
        merged = {**self._uow.db.reservations, **self._uow.staged_reservations}
        return [copy.deepcopy(r) for r in merged.values()]

    async def add(self, reservation: Reservation) -> None:
        self._uow.staged_reservations[reservation.order_id] = persisted(reservation)

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Reservation | None:
        return next((r for r in self._all() if r.order_id == order_id), None)

    async def save(self, reservation: Reservation) -> None:
        self._uow.staged_reservations[reservation.order_id] = persisted(reservation)

    async def fetch_expired(self, now: datetime, limit: int) -> list[Reservation]:
        due = [
            r for r in self._all() if r.status is ReservationStatus.RESERVED and r.expires_at <= now
        ]
        return due[:limit]


class FakeOutbox:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add(self, events: list[DomainEvent]) -> None:
        self._uow.staged_events.extend(events)


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
        self.staged_stocks: dict[UUID, Stock] = {}
        self.staged_reservations: dict[UUID, Reservation] = {}
        self.staged_events: list[DomainEvent] = []
        self.staged_inbox: set[tuple[UUID, str]] = set()
        self.stocks = FakeStocks(self)
        self.reservations = FakeReservations(self)
        self.outbox = FakeOutbox(self)
        self.inbox = FakeInbox(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._discard()

    def _discard(self) -> None:
        self.staged_stocks, self.staged_reservations = {}, {}
        self.staged_events, self.staged_inbox = [], set()

    async def commit(self) -> None:
        self.db.stocks.update(self.staged_stocks)
        self.db.reservations.update(self.staged_reservations)
        self.db.events.extend(self.staged_events)
        self.db.inbox.update(self.staged_inbox)
        self._discard()
