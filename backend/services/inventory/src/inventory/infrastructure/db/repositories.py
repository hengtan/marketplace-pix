from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from inventory.domain.reservation import Reservation, ReservationItem, ReservationStatus
from inventory.domain.stock import Stock
from inventory.infrastructure.db.models import ReservationModel, StockModel


class SqlAlchemyStockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_many(
        self, product_ids: Collection[UUID], lock: bool = False
    ) -> dict[UUID, Stock]:
        if not product_ids:
            return {}
        stmt = (
            select(StockModel)
            .where(StockModel.product_id.in_(set(product_ids)))
            .order_by(StockModel.product_id)
        )
        if lock:
            stmt = stmt.with_for_update()
        rows = (await self._session.execute(stmt)).scalars().all()
        return {r.product_id: Stock(r.product_id, r.available, r.reserved) for r in rows}

    async def save(self, stock: Stock) -> None:
        stmt = insert(StockModel).values(
            product_id=stock.product_id, available=stock.available, reserved=stock.reserved
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["product_id"],
                set_={
                    "available": stmt.excluded.available,
                    "reserved": stmt.excluded.reserved,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )

    async def list_all(self, limit: int) -> list[Stock]:
        stmt = select(StockModel).order_by(StockModel.product_id).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [Stock(r.product_id, r.available, r.reserved) for r in rows]


def _to_domain(row: ReservationModel) -> Reservation:
    return Reservation(
        order_id=row.order_id,
        items=[ReservationItem(UUID(i["product_id"]), int(i["quantity"])) for i in row.items],
        status=ReservationStatus(row.status),
        expires_at=row.expires_at,
    )


def _items_json(reservation: Reservation) -> list[dict[str, str | int]]:
    return [
        {"product_id": str(i.product_id), "quantity": i.quantity} for i in reservation.items
    ]


class SqlAlchemyReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, reservation: Reservation) -> None:
        self._session.add(
            ReservationModel(
                order_id=reservation.order_id,
                status=reservation.status.value,
                items=_items_json(reservation),
                expires_at=reservation.expires_at,
            )
        )
        await self._session.flush()

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Reservation | None:
        stmt = select(ReservationModel).where(ReservationModel.order_id == order_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def save(self, reservation: Reservation) -> None:
        await self._session.execute(
            update(ReservationModel)
            .where(ReservationModel.order_id == reservation.order_id)
            .values(status=reservation.status.value, expires_at=reservation.expires_at)
        )

    async def fetch_expired(self, now: datetime, limit: int) -> list[Reservation]:
        stmt = (
            select(ReservationModel)
            .where(ReservationModel.status == ReservationStatus.RESERVED.value)
            .where(ReservationModel.expires_at <= now)
            .order_by(ReservationModel.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]
