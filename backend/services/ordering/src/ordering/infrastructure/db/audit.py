from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ordering.infrastructure.db.models import OrderAuditModel


class SqlAlchemyAuditLog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self, order_id: UUID, kind: str, reference_id: UUID | None, details: dict[str, Any]
    ) -> bool:
        stmt = (
            insert(OrderAuditModel)
            .values(
                id=uuid4(),
                order_id=order_id,
                kind=kind,
                reference_id=reference_id,
                details=details,
            )
            .on_conflict_do_nothing(index_elements=["order_id", "kind", "reference_id"])
            .returning(OrderAuditModel.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
