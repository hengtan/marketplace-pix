from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payments.application.clock import Clock, utcnow
from payments.application.ports import ChargeStatus, PspCharge
from payments.domain.money import Money
from payments.infrastructure.db.models import SimulatedChargeModel


class PspChargeNotFound(Exception):
    pass


class SimulatedPsp:
    """PSP de mentira. Usa sessões próprias (commit independente), como um sistema externo."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utcnow
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def create_charge(self, reference: str, amount: Money, expires_at: datetime) -> PspCharge:
        charge_id = f"ch_{uuid4().hex[:16]}"
        async with self._session_factory() as session:
            await session.execute(
                insert(SimulatedChargeModel)
                .values(
                    id=charge_id,
                    reference=reference,
                    amount_cents=amount.cents,
                    currency=amount.currency,
                    status=ChargeStatus.PENDING.value,
                    pix_code=f"SIMULATED-PIX|{charge_id}|{amount.cents}",
                    expires_at=expires_at,
                )
                .on_conflict_do_nothing(index_elements=["reference"])
            )
            await session.commit()
            row = (
                await session.execute(
                    select(SimulatedChargeModel).where(SimulatedChargeModel.reference == reference)
                )
            ).scalar_one()
        return PspCharge(id=row.id, pix_code=row.pix_code, expires_at=row.expires_at)

    async def get_charge_status(self, charge_id: str) -> ChargeStatus:
        async with self._session_factory() as session:
            row = await session.get(SimulatedChargeModel, charge_id)
        if row is None:
            raise PspChargeNotFound(charge_id)
        status = ChargeStatus(row.status)
        if status is ChargeStatus.PENDING and row.expires_at <= self._clock():
            return ChargeStatus.EXPIRED
        return status

    async def mark_paid(self, charge_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(SimulatedChargeModel)
                .where(SimulatedChargeModel.id == charge_id)
                .where(SimulatedChargeModel.status == ChargeStatus.PENDING.value)
                .where(SimulatedChargeModel.expires_at > self._clock())
                .values(status=ChargeStatus.PAID.value)
            )
            await session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def cancel_charge(self, charge_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(SimulatedChargeModel)
                .where(SimulatedChargeModel.id == charge_id)
                .where(
                    SimulatedChargeModel.status.in_(
                        [ChargeStatus.PENDING.value, ChargeStatus.CANCELLED.value]
                    )
                )
                .values(status=ChargeStatus.CANCELLED.value)
            )
            await session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]
