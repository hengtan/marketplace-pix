from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from ledger.application.clock import Clock, utcnow
from ledger.application.errors import InvalidQuery
from ledger.application.ports import EntryRecord, UnitOfWork
from ledger.domain.account import merchant_account_id

MAX_DAYS = 365


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    gross_cents: int
    net_cents: int
    orders: int


@dataclass(frozen=True, slots=True)
class MerchantSummary:
    merchant_id: UUID
    currency: str
    balance_cents: int
    gross_sales_cents: int
    platform_fees_cents: int
    net_sales_cents: int
    orders_count: int
    daily: list[DailySummary]


@dataclass(frozen=True, slots=True)
class EntriesPage:
    items: list[EntryRecord]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    balanced: bool
    total_debits_cents: int
    total_credits_cents: int
    transactions_count: int
    accounts_checked: int
    accounts_consistent: bool
    inconsistent_accounts: list[str]
    checked_at: datetime


class GetMerchantSummary:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        clock: Clock = utcnow,
        default_currency: str = "BRL",
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._default_currency = default_currency

    async def execute(self, merchant_id: UUID, days: int = 30) -> MerchantSummary:
        if not 1 <= days <= MAX_DAYS:
            raise InvalidQuery(f"days must be between 1 and {MAX_DAYS}")
        today = self._clock().astimezone(UTC).date()
        first_day = today - timedelta(days=days - 1)
        start = datetime.combine(first_day, time.min, tzinfo=UTC)
        end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)

        async with self._uow_factory() as uow:
            balance = await uow.queries.get_balance(merchant_account_id(merchant_id))
            rows = await uow.queries.merchant_daily_totals(merchant_id, start, end)

        by_day = {row.day: row for row in rows}
        daily: list[DailySummary] = []
        for offset in range(days):
            day = first_day + timedelta(days=offset)
            row = by_day.get(day)
            if row is None:
                daily.append(DailySummary(day, 0, 0, 0))
            else:
                daily.append(
                    DailySummary(day, row.net_cents + row.fees_cents, row.net_cents, row.orders)
                )
        net = sum(d.net_cents for d in daily)
        gross = sum(d.gross_cents for d in daily)
        return MerchantSummary(
            merchant_id=merchant_id,
            currency=balance.currency if balance else self._default_currency,
            balance_cents=balance.balance_cents if balance else 0,
            gross_sales_cents=gross,
            platform_fees_cents=gross - net,
            net_sales_cents=net,
            orders_count=sum(d.orders for d in daily),
            daily=daily,
        )


class ListAccountEntries:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, account_id: str, page: int = 1, page_size: int = 20) -> EntriesPage:
        if page < 1 or not 1 <= page_size <= 100:
            raise InvalidQuery("page must be >= 1 and page_size between 1 and 100")
        async with self._uow_factory() as uow:
            items, total = await uow.queries.list_entries(
                account_id, limit=page_size, offset=(page - 1) * page_size
            )
        return EntriesPage(items=items, total=total, page=page, page_size=page_size)


class Reconcile:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock = utcnow) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self) -> ReconciliationReport:
        async with self._uow_factory() as uow:
            totals = await uow.queries.ledger_totals()
        return ReconciliationReport(
            balanced=totals.total_debits_cents == totals.total_credits_cents,
            total_debits_cents=totals.total_debits_cents,
            total_credits_cents=totals.total_credits_cents,
            transactions_count=totals.transactions_count,
            accounts_checked=totals.accounts_checked,
            accounts_consistent=not totals.inconsistent_accounts,
            inconsistent_accounts=list(totals.inconsistent_accounts),
            checked_at=self._clock(),
        )
