from uuid import UUID

from sqlalchemy import func, select

from ledger.application.queries import Reconcile
from ledger.infrastructure.db.models import AccountModel


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def balances(session_factory) -> dict[str, int]:
    async with session_factory() as session:
        rows = (await session.execute(select(AccountModel))).scalars().all()
    return {r.id: r.balance_cents for r in rows}


async def reconcile(uow_factory):
    return await Reconcile(uow_factory).execute()


def order_id_of(event) -> UUID:
    return UUID(event.payload["order_id"])
