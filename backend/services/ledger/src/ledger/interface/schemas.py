from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from ledger.application.ports import EntryRecord
from ledger.application.queries import EntriesPage, MerchantSummary, ReconciliationReport


class DailyOut(BaseModel):
    date: date
    gross_cents: int
    net_cents: int
    orders: int


class MerchantSummaryOut(BaseModel):
    merchant_id: UUID
    currency: str
    balance_cents: int
    gross_sales_cents: int
    platform_fees_cents: int
    net_sales_cents: int
    orders_count: int
    daily: list[DailyOut]

    @classmethod
    def from_domain(cls, summary: MerchantSummary) -> MerchantSummaryOut:
        return cls(
            merchant_id=summary.merchant_id,
            currency=summary.currency,
            balance_cents=summary.balance_cents,
            gross_sales_cents=summary.gross_sales_cents,
            platform_fees_cents=summary.platform_fees_cents,
            net_sales_cents=summary.net_sales_cents,
            orders_count=summary.orders_count,
            daily=[
                DailyOut(
                    date=d.day, gross_cents=d.gross_cents, net_cents=d.net_cents, orders=d.orders
                )
                for d in summary.daily
            ],
        )


class EntryOut(BaseModel):
    id: UUID
    transaction_id: UUID
    direction: str
    amount_cents: int
    description: str
    order_id: UUID
    created_at: datetime

    @classmethod
    def from_record(cls, record: EntryRecord) -> EntryOut:
        return cls(
            id=record.id,
            transaction_id=record.transaction_id,
            direction=record.direction,
            amount_cents=record.amount_cents,
            description=record.description,
            order_id=record.order_id,
            created_at=record.created_at,
        )


class EntriesPageOut(BaseModel):
    items: list[EntryOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_domain(cls, page: EntriesPage) -> EntriesPageOut:
        return cls(
            items=[EntryOut.from_record(r) for r in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )


class ReconciliationOut(BaseModel):
    balanced: bool
    total_debits_cents: int
    total_credits_cents: int
    transactions_count: int
    checked_at: datetime
    accounts_checked: int
    accounts_consistent: bool
    inconsistent_accounts: list[str]

    @classmethod
    def from_domain(cls, report: ReconciliationReport) -> ReconciliationOut:
        return cls(
            balanced=report.balanced,
            total_debits_cents=report.total_debits_cents,
            total_credits_cents=report.total_credits_cents,
            transactions_count=report.transactions_count,
            checked_at=report.checked_at,
            accounts_checked=report.accounts_checked,
            accounts_consistent=report.accounts_consistent,
            inconsistent_accounts=report.inconsistent_accounts,
        )
