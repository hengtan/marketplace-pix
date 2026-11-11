from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Date, case, cast, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.application.ports import (
    AccountBalance,
    DailyMerchantTotals,
    EntryRecord,
    LedgerTotals,
)
from ledger.domain.account import (
    PLATFORM_REVENUE_ID,
    Direction,
    merchant_account_id,
)
from ledger.domain.money import Money
from ledger.domain.order_projection import OrderProjection, ProjectedItem
from ledger.domain.transaction import Transaction
from ledger.infrastructure.db.models import (
    AccountModel,
    EntryModel,
    OrderProjectionModel,
    TransactionModel,
)


def _projection_to_domain(model: OrderProjectionModel) -> OrderProjection:
    return OrderProjection(
        order_id=model.order_id,
        currency=model.currency,
        items=tuple(
            ProjectedItem(
                product_id=UUID(item["product_id"]),
                merchant_id=UUID(item["merchant_id"]),
                quantity=item["quantity"],
                unit_price=Money(item["unit_price_cents"], model.currency),
            )
            for item in model.items
        ),
        created_at=model.created_at,
    )


class SqlAlchemyOrderProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, projection: OrderProjection) -> bool:
        stmt = (
            insert(OrderProjectionModel)
            .values(
                order_id=projection.order_id,
                currency=projection.currency,
                total_cents=projection.total.cents,
                items=[
                    {
                        "product_id": str(i.product_id),
                        "merchant_id": str(i.merchant_id),
                        "quantity": i.quantity,
                        "unit_price_cents": i.unit_price.cents,
                    }
                    for i in projection.items
                ],
                created_at=projection.created_at,
            )
            .on_conflict_do_nothing(index_elements=["order_id"])
            .returning(OrderProjectionModel.order_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def get(self, order_id: UUID) -> OrderProjection | None:
        model = await self._session.get(OrderProjectionModel, order_id)
        return None if model is None else _projection_to_domain(model)


class SqlAlchemyLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_transaction(self, order_id: UUID, kind: str) -> bool:
        found = await self._session.scalar(
            select(TransactionModel.id).where(
                TransactionModel.order_id == order_id, TransactionModel.kind == kind
            )
        )
        return found is not None

    async def add_transaction(self, transaction: Transaction) -> bool:
        claimed = await self._session.execute(
            insert(TransactionModel)
            .values(
                id=transaction.id,
                order_id=transaction.order_id,
                payment_id=transaction.payment_id,
                kind=transaction.kind.value,
                currency=transaction.currency,
                total_cents=transaction.total_debits.cents,
                platform_fee_cents=transaction.platform_fee.cents,
                created_at=transaction.created_at,
            )
            .on_conflict_do_nothing()
            .returning(TransactionModel.id)
        )
        if claimed.scalar_one_or_none() is None:
            return False

        deltas = transaction.balance_deltas()
        for account, delta in deltas.items():
            upsert = insert(AccountModel).values(
                id=account.id,
                type=account.type.value,
                normal_side=account.normal_side.value,
                currency=transaction.currency,
                balance_cents=delta,
            )
            await self._session.execute(
                upsert.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "balance_cents": AccountModel.balance_cents + upsert.excluded.balance_cents,
                        "updated_at": func.now(),
                    },
                )
            )

        await self._session.execute(
            insert(EntryModel),
            [
                {
                    "id": e.id,
                    "transaction_id": transaction.id,
                    "account_id": e.account.id,
                    "direction": e.direction.value,
                    "amount_cents": e.amount.cents,
                    "description": e.description,
                    "order_id": transaction.order_id,
                    "merchant_id": e.merchant_id,
                    "created_at": transaction.created_at,
                }
                for e in transaction.entries
            ],
        )
        return True


class SqlAlchemyLedgerQueries:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_balance(self, account_id: str) -> AccountBalance | None:
        model = await self._session.get(AccountModel, account_id)
        if model is None:
            return None
        return AccountBalance(model.id, model.currency, model.balance_cents)

    async def merchant_daily_totals(
        self, merchant_id: UUID, start: datetime, end: datetime
    ) -> list[DailyMerchantTotals]:
        merchant_account = merchant_account_id(merchant_id)
        day = cast(func.timezone("UTC", EntryModel.created_at), Date).label("day")
        credit = EntryModel.direction == Direction.CREDIT.value
        is_net = (EntryModel.account_id == merchant_account) & credit
        is_net_reversal = (EntryModel.account_id == merchant_account) & ~credit
        is_fee = (EntryModel.account_id == PLATFORM_REVENUE_ID) & credit
        is_fee_reversal = (EntryModel.account_id == PLATFORM_REVENUE_ID) & ~credit
        amount = EntryModel.amount_cents
        stmt = (
            select(
                day,
                func.coalesce(
                    func.sum(case((is_net, amount), (is_net_reversal, -amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((is_fee, amount), (is_fee_reversal, -amount), else_=0)), 0
                ),
                func.count(distinct(case((is_net, EntryModel.order_id), else_=None)))
                - func.count(distinct(case((is_net_reversal, EntryModel.order_id), else_=None))),
            )
            .where(EntryModel.merchant_id == merchant_id)
            .where(EntryModel.created_at >= start)
            .where(EntryModel.created_at < end)
            .group_by(day)
            .order_by(day)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            DailyMerchantTotals(day=r[0], net_cents=int(r[1]), fees_cents=int(r[2]), orders=r[3])
            for r in rows
        ]

    async def list_entries(
        self, account_id: str, limit: int, offset: int
    ) -> tuple[list[EntryRecord], int]:
        total = await self._session.scalar(
            select(func.count()).select_from(EntryModel).where(EntryModel.account_id == account_id)
        )
        rows = (
            (
                await self._session.execute(
                    select(EntryModel)
                    .where(EntryModel.account_id == account_id)
                    .order_by(EntryModel.created_at.desc(), EntryModel.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        records = [
            EntryRecord(
                id=r.id,
                transaction_id=r.transaction_id,
                account_id=r.account_id,
                direction=r.direction,
                amount_cents=r.amount_cents,
                description=r.description,
                order_id=r.order_id,
                created_at=r.created_at,
            )
            for r in rows
        ]
        return records, int(total or 0)

    async def ledger_totals(self) -> LedgerTotals:
        await self._session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        sums = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    EntryModel.direction == Direction.DEBIT.value,
                                    EntryModel.amount_cents,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    EntryModel.direction == Direction.CREDIT.value,
                                    EntryModel.amount_cents,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
            )
        ).one()
        transactions = await self._session.scalar(
            select(func.count()).select_from(TransactionModel)
        )
        accounts = await self._session.scalar(select(func.count()).select_from(AccountModel))
        entries_balance = func.coalesce(
            func.sum(
                case(
                    (EntryModel.direction == AccountModel.normal_side, EntryModel.amount_cents),
                    else_=-EntryModel.amount_cents,
                )
            ),
            0,
        )
        inconsistent = (
            (
                await self._session.execute(
                    select(AccountModel.id)
                    .outerjoin(EntryModel, EntryModel.account_id == AccountModel.id)
                    .group_by(AccountModel.id, AccountModel.balance_cents)
                    .having(entries_balance != AccountModel.balance_cents)
                    .order_by(AccountModel.id)
                )
            )
            .scalars()
            .all()
        )
        return LedgerTotals(
            total_debits_cents=int(sums[0]),
            total_credits_cents=int(sums[1]),
            transactions_count=int(transactions or 0),
            accounts_checked=int(accounts or 0),
            inconsistent_accounts=tuple(inconsistent),
        )
