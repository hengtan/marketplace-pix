import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from ledger.application.ports import (
    AccountBalance,
    DailyMerchantTotals,
    EntryRecord,
    LedgerTotals,
)
from ledger.domain.account import PLATFORM_REVENUE_ID, Account, Direction, merchant_account_id
from ledger.domain.events import DomainEvent
from ledger.domain.order_projection import OrderProjection
from ledger.domain.transaction import Transaction


@dataclass
class StoredEntry:
    record: EntryRecord
    merchant_id: UUID | None


@dataclass
class FakeDatabase:
    projections: dict[UUID, OrderProjection] = field(default_factory=dict)
    transactions: dict[UUID, Transaction] = field(default_factory=dict)
    entries: list[StoredEntry] = field(default_factory=list)
    accounts: dict[str, tuple[Account, str, int]] = field(default_factory=dict)
    events: list[DomainEvent] = field(default_factory=list)
    inbox: set[tuple[UUID, str]] = field(default_factory=set)

    def transaction_for_order(self, order_id: UUID) -> Transaction | None:
        return next((t for t in self.transactions.values() if t.order_id == order_id), None)

    def balance(self, account_id: str) -> int:
        entry = self.accounts.get(account_id)
        return 0 if entry is None else entry[2]


class FakeOrders:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add(self, projection: OrderProjection) -> bool:
        if projection.order_id in self._uow.db.projections:
            return False
        if projection.order_id in self._uow.staged_projections:
            return False
        self._uow.staged_projections[projection.order_id] = projection
        return True

    async def get(self, order_id: UUID) -> OrderProjection | None:
        return self._uow.db.projections.get(order_id) or self._uow.staged_projections.get(order_id)


class FakeLedger:
    def __init__(self, uow: "FakeUow") -> None:
        self._uow = uow

    async def add_transaction(self, transaction: Transaction) -> bool:
        db = self._uow.db
        known = [*db.transactions.values(), *self._uow.staged_transactions]
        if any(
            t.kind is transaction.kind
            and (t.order_id == transaction.order_id or t.payment_id == transaction.payment_id)
            for t in known
        ):
            return False
        self._uow.staged_transactions.append(copy.deepcopy(transaction))
        return True

    async def has_transaction(self, order_id: UUID, kind: str) -> bool:
        known = [*self._uow.db.transactions.values(), *self._uow.staged_transactions]
        return any(t.order_id == order_id and t.kind.value == kind for t in known)


class FakeQueries:
    def __init__(self, uow: "FakeUow") -> None:
        self._db = uow.db

    async def get_balance(self, account_id: str) -> AccountBalance | None:
        stored = self._db.accounts.get(account_id)
        if stored is None:
            return None
        return AccountBalance(account_id, stored[1], stored[2])

    async def merchant_daily_totals(
        self, merchant_id: UUID, start: datetime, end: datetime
    ) -> list[DailyMerchantTotals]:
        account = merchant_account_id(merchant_id)
        net: dict[date, int] = {}
        fees: dict[date, int] = {}
        orders: dict[date, list[set[UUID]]] = {}
        for stored in self._db.entries:
            rec = stored.record
            if stored.merchant_id != merchant_id or not start <= rec.created_at < end:
                continue
            day = rec.created_at.date()
            sign = 1 if rec.direction == Direction.CREDIT.value else -1
            if rec.account_id == account:
                net[day] = net.get(day, 0) + sign * rec.amount_cents
                bucket = orders.setdefault(day, [set(), set()])
                bucket[0 if sign > 0 else 1].add(rec.order_id)
            elif rec.account_id == PLATFORM_REVENUE_ID:
                fees[day] = fees.get(day, 0) + sign * rec.amount_cents
        days = sorted(set(net) | set(fees))
        return [
            DailyMerchantTotals(
                d,
                net.get(d, 0),
                fees.get(d, 0),
                len(orders.get(d, [set(), set()])[0]) - len(orders.get(d, [set(), set()])[1]),
            )
            for d in days
        ]

    async def list_entries(
        self, account_id: str, limit: int, offset: int
    ) -> tuple[list[EntryRecord], int]:
        records = [s.record for s in self._db.entries if s.record.account_id == account_id]
        records.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return records[offset : offset + limit], len(records)

    async def ledger_totals(self) -> LedgerTotals:
        debits = sum(
            s.record.amount_cents for s in self._db.entries if s.record.direction == "DEBIT"
        )
        credits = sum(
            s.record.amount_cents for s in self._db.entries if s.record.direction == "CREDIT"
        )
        inconsistent = []
        for account_id, (account, _, balance) in sorted(self._db.accounts.items()):
            computed = sum(
                account.signed_amount(Direction(s.record.direction), s.record.amount_cents)
                for s in self._db.entries
                if s.record.account_id == account_id
            )
            if computed != balance:
                inconsistent.append(account_id)
        return LedgerTotals(
            total_debits_cents=debits,
            total_credits_cents=credits,
            transactions_count=len(self._db.transactions),
            accounts_checked=len(self._db.accounts),
            inconsistent_accounts=tuple(inconsistent),
        )


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
        self.staged_projections: dict[UUID, OrderProjection] = {}
        self.staged_transactions: list[Transaction] = []
        self.staged_events: list[DomainEvent] = []
        self.staged_inbox: set[tuple[UUID, str]] = set()
        self.orders = FakeOrders(self)
        self.ledger = FakeLedger(self)
        self.queries = FakeQueries(self)
        self.outbox = FakeOutbox(self)
        self.inbox = FakeInbox(self)

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._discard()

    def _discard(self) -> None:
        self.staged_projections, self.staged_transactions = {}, []
        self.staged_events, self.staged_inbox = [], set()

    async def commit(self) -> None:
        db = self.db
        db.projections.update(self.staged_projections)
        for transaction in self.staged_transactions:
            stored = copy.deepcopy(transaction)
            stored._events = []
            db.transactions[stored.id] = stored
            for entry in stored.entries:
                db.entries.append(
                    StoredEntry(
                        EntryRecord(
                            id=entry.id,
                            transaction_id=stored.id,
                            account_id=entry.account.id,
                            direction=entry.direction.value,
                            amount_cents=entry.amount.cents,
                            description=entry.description,
                            order_id=stored.order_id,
                            created_at=stored.created_at,
                        ),
                        entry.merchant_id,
                    )
                )
            for account, delta in stored.balance_deltas().items():
                _, currency, balance = db.accounts.get(account.id, (account, stored.currency, 0))
                db.accounts[account.id] = (account, currency, balance + delta)
        db.events.extend(self.staged_events)
        db.inbox.update(self.staged_inbox)
        self._discard()
