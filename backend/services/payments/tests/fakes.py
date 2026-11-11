import copy
from datetime import datetime
from uuid import UUID

from payments.application.ports import ChargeStatus, PspCharge
from payments.domain.events import DomainEvent
from payments.domain.money import Money
from payments.domain.payment import Payment, PaymentStatus


class FakeDatabase:
    def __init__(self) -> None:
        self.payments: dict[UUID, Payment] = {}
        self.events: list[DomainEvent] = []
        self.inbox: set[tuple[UUID, str]] = set()


def persisted(payment: Payment) -> Payment:
    clone = copy.deepcopy(payment)
    clone._events = []
    return clone


class FakePayments:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    def _all(self) -> list[Payment]:
        merged = {**self._uow.db.payments, **self._uow.staged_payments}
        return [copy.deepcopy(p) for p in merged.values()]

    async def add(self, payment: Payment) -> None:
        self._uow.staged_payments[payment.id] = persisted(payment)

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Payment | None:
        return next((p for p in self._all() if p.order_id == order_id), None)

    async def get_by_psp_charge_id(self, charge_id: str, lock: bool = False) -> Payment | None:
        return next((p for p in self._all() if p.psp_charge_id == charge_id), None)

    async def save(self, payment: Payment) -> None:
        self._uow.staged_payments[payment.id] = persisted(payment)

    async def fetch_expired(self, now: datetime, limit: int) -> list[Payment]:
        due = [p for p in self._all() if p.status is PaymentStatus.PENDING and p.expires_at <= now]
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
        self.staged_payments: dict[UUID, Payment] = {}
        self.staged_events: list[DomainEvent] = []
        self.staged_inbox: set[tuple[UUID, str]] = set()
        self.payments = FakePayments(self)
        self.outbox = FakeOutbox(self)
        self.inbox = FakeInbox(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._discard()

    def _discard(self) -> None:
        self.staged_payments, self.staged_events, self.staged_inbox = {}, [], set()

    async def commit(self) -> None:
        self.db.payments.update(self.staged_payments)
        self.db.events.extend(self.staged_events)
        self.db.inbox.update(self.staged_inbox)
        self._discard()


class FakePsp:
    def __init__(self) -> None:
        self.by_reference: dict[str, PspCharge] = {}
        self.statuses: dict[str, ChargeStatus] = {}
        self.create_calls = 0
        self.fail_create = False
        self.refuse_cancel = False
        self.cancelled: list[str] = []
        self.refuse_refund = False
        self.refunded: list[str] = []

    async def create_charge(self, reference: str, amount: Money, expires_at: datetime) -> PspCharge:
        self.create_calls += 1
        if self.fail_create:
            raise ConnectionError("psp is down")
        if reference not in self.by_reference:
            charge_id = f"ch_{len(self.by_reference) + 1}"
            self.by_reference[reference] = PspCharge(charge_id, f"PIX-{charge_id}", expires_at)
            self.statuses[charge_id] = ChargeStatus.PENDING
        return self.by_reference[reference]

    async def get_charge_status(self, charge_id: str) -> ChargeStatus:
        return self.statuses[charge_id]

    async def refund_charge(self, charge_id: str) -> bool:
        if self.refuse_refund or self.statuses.get(charge_id) not in (
            ChargeStatus.PAID,
            ChargeStatus.REFUNDED,
        ):
            return False
        self.statuses[charge_id] = ChargeStatus.REFUNDED
        self.refunded.append(charge_id)
        return True

    async def cancel_charge(self, charge_id: str) -> bool:
        if self.refuse_cancel:
            return False
        self.statuses[charge_id] = ChargeStatus.CANCELLED
        self.cancelled.append(charge_id)
        return True

    @property
    def charges(self) -> int:
        return len(self.by_reference)
