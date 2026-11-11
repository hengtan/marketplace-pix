from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payments.domain.money import Money
from payments.domain.payment import Payment, PaymentStatus
from payments.infrastructure.db.models import PaymentModel


def _to_domain(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        order_id=model.order_id,
        amount=Money(model.amount_cents, model.currency),
        psp_charge_id=model.psp_charge_id,
        pix_code=model.pix_code,
        expires_at=model.expires_at,
        status=PaymentStatus(model.status),
        confirmed_at=model.confirmed_at,
    )


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        self._session.add(
            PaymentModel(
                id=payment.id,
                order_id=payment.order_id,
                status=payment.status.value,
                amount_cents=payment.amount.cents,
                currency=payment.amount.currency,
                psp_charge_id=payment.psp_charge_id,
                pix_code=payment.pix_code,
                expires_at=payment.expires_at,
                confirmed_at=payment.confirmed_at,
            )
        )

    async def get_by_order(self, order_id: UUID, lock: bool = False) -> Payment | None:
        stmt = select(PaymentModel).where(PaymentModel.order_id == order_id)
        if lock:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def get_by_psp_charge_id(self, charge_id: str, lock: bool = False) -> Payment | None:
        stmt = select(PaymentModel).where(PaymentModel.psp_charge_id == charge_id)
        if lock:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def save(self, payment: Payment) -> None:
        model = await self._session.get(PaymentModel, payment.id)
        if model is None:
            raise LookupError(f"payment {payment.id} not found")
        model.status = payment.status.value
        model.confirmed_at = payment.confirmed_at

    async def fetch_expired(self, now: datetime, limit: int) -> list[Payment]:
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.status == PaymentStatus.PENDING.value)
            .where(PaymentModel.expires_at <= now)
            .order_by(PaymentModel.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_to_domain(m) for m in (await self._session.execute(stmt)).scalars().all()]
