from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from payments.domain.payment import Payment


class PaymentOut(BaseModel):
    id: UUID
    order_id: UUID
    status: str
    amount_cents: int
    currency: str
    pix_code: str
    psp_charge_id: str
    expires_at: datetime
    confirmed_at: datetime | None

    @classmethod
    def from_domain(cls, payment: Payment) -> PaymentOut:
        return cls(
            id=payment.id,
            order_id=payment.order_id,
            status=payment.status.value,
            amount_cents=payment.amount.cents,
            currency=payment.amount.currency,
            pix_code=payment.pix_code,
            psp_charge_id=payment.psp_charge_id,
            expires_at=payment.expires_at,
            confirmed_at=payment.confirmed_at,
        )
