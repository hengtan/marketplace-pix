from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from ledger.domain.events import DomainEvent
from ledger.domain.order_projection import OrderProjection
from ledger.domain.transaction import Transaction


@dataclass(frozen=True, slots=True)
class EntryRecord:
    id: UUID
    transaction_id: UUID
    account_id: str
    direction: str
    amount_cents: int
    description: str
    order_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account_id: str
    currency: str
    balance_cents: int


@dataclass(frozen=True, slots=True)
class DailyMerchantTotals:
    day: date
    net_cents: int
    fees_cents: int
    orders: int


@dataclass(frozen=True, slots=True)
class LedgerTotals:
    total_debits_cents: int
    total_credits_cents: int
    transactions_count: int
    accounts_checked: int
    inconsistent_accounts: tuple[str, ...]


class OrderProjectionRepository(Protocol):
    async def add(self, projection: OrderProjection) -> bool: ...

    async def get(self, order_id: UUID) -> OrderProjection | None: ...


class LedgerRepository(Protocol):
    async def add_transaction(self, transaction: Transaction) -> bool: ...


class LedgerQueries(Protocol):
    async def get_balance(self, account_id: str) -> AccountBalance | None: ...

    async def merchant_daily_totals(
        self, merchant_id: UUID, start: datetime, end: datetime
    ) -> list[DailyMerchantTotals]: ...

    async def list_entries(
        self, account_id: str, limit: int, offset: int
    ) -> tuple[list[EntryRecord], int]: ...

    async def ledger_totals(self) -> LedgerTotals: ...


class InboxStore(Protocol):
    async def claim(self, message_id: UUID, consumer: str) -> bool: ...


class OutboxWriter(Protocol):
    async def add(self, events: list[DomainEvent]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def orders(self) -> OrderProjectionRepository: ...

    @property
    def ledger(self) -> LedgerRepository: ...

    @property
    def queries(self) -> LedgerQueries: ...

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
