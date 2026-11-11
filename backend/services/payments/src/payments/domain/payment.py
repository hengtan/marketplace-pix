from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from payments.domain.errors import InvalidPayment, InvalidStateTransition
from payments.domain.events import (
    DomainEvent,
    PaymentCancelled,
    PaymentConfirmed,
    PaymentCreated,
    PaymentExpired,
    PaymentRefunded,
)
from payments.domain.money import Money


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


def payment_id_for(order_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:payment:{order_id}")


@dataclass(slots=True)
class Payment:
    id: UUID
    order_id: UUID
    amount: Money
    psp_charge_id: str
    pix_code: str
    expires_at: datetime
    status: PaymentStatus = PaymentStatus.PENDING
    confirmed_at: datetime | None = None
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        order_id: UUID,
        amount: Money,
        psp_charge_id: str,
        pix_code: str,
        expires_at: datetime,
    ) -> Payment:
        if amount.cents <= 0:
            raise InvalidPayment("amount must be positive")
        payment = cls(
            id=payment_id_for(order_id),
            order_id=order_id,
            amount=amount,
            psp_charge_id=psp_charge_id,
            pix_code=pix_code,
            expires_at=expires_at,
        )
        payment._events.append(
            PaymentCreated(
                order_id=order_id,
                payment_id=payment.id,
                amount_cents=amount.cents,
                currency=amount.currency,
                pix_code=pix_code,
                expires_at=expires_at,
            )
        )
        return payment

    def confirm(self, at: datetime) -> None:
        if self.status is PaymentStatus.CONFIRMED:
            return
        if self.status is PaymentStatus.EXPIRED:
            raise InvalidStateTransition("payment already expired")
        if self.status is PaymentStatus.CANCELLED:
            raise InvalidStateTransition("payment was cancelled")
        self.status = PaymentStatus.CONFIRMED
        self.confirmed_at = at
        self._events.append(
            PaymentConfirmed(
                order_id=self.order_id,
                payment_id=self.id,
                amount_cents=self.amount.cents,
                currency=self.amount.currency,
            )
        )

    def expire(self, now: datetime) -> None:
        if self.status in (PaymentStatus.EXPIRED, PaymentStatus.CANCELLED):
            return
        if self.status is PaymentStatus.CONFIRMED:
            raise InvalidStateTransition("payment already confirmed")
        if now < self.expires_at:
            raise InvalidStateTransition("payment has not expired yet")
        self.status = PaymentStatus.EXPIRED
        self._events.append(PaymentExpired(order_id=self.order_id, payment_id=self.id))

    def refund(self, reason: str) -> None:
        if self.status is PaymentStatus.REFUNDED:
            return
        if self.status is not PaymentStatus.CONFIRMED:
            raise InvalidStateTransition(f"cannot refund a payment in {self.status}")
        self.status = PaymentStatus.REFUNDED
        self._events.append(
            PaymentRefunded(
                order_id=self.order_id,
                payment_id=self.id,
                amount_cents=self.amount.cents,
                currency=self.amount.currency,
                reason=reason,
            )
        )

    def cancel(self) -> None:
        if self.status in (PaymentStatus.CANCELLED, PaymentStatus.EXPIRED):
            return
        if self.status is PaymentStatus.CONFIRMED:
            raise InvalidStateTransition("payment already confirmed")
        self.status = PaymentStatus.CANCELLED
        self._events.append(PaymentCancelled(order_id=self.order_id, payment_id=self.id))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
