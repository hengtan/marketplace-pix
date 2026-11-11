from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from payments.domain.errors import InvalidPayment, InvalidStateTransition
from payments.domain.events import PaymentConfirmed, PaymentCreated, PaymentExpired
from payments.domain.money import Money
from payments.domain.payment import Payment, PaymentStatus, payment_id_for

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def make(order_id=None, amount=4480) -> Payment:
    return Payment.create(
        order_id or uuid4(), Money(amount), "ch_1", "PIX-1", NOW + timedelta(minutes=30)
    )


def test_create_is_pending_and_emits_payment_created():
    payment = make()
    assert payment.status is PaymentStatus.PENDING
    (event,) = payment.pull_events()
    assert isinstance(event, PaymentCreated)
    assert event.amount_cents == 4480
    assert event.order_id == payment.order_id
    assert payment.pull_events() == []


def test_payment_id_is_deterministic_per_order():
    order_id = uuid4()
    assert make(order_id).id == make(order_id).id == payment_id_for(order_id)
    assert make().id != make().id


def test_zero_amount_is_rejected():
    with pytest.raises(InvalidPayment):
        make(amount=0)


def test_confirm_sets_status_and_emits_event():
    payment = make()
    payment.pull_events()
    payment.confirm(NOW)
    (event,) = payment.pull_events()
    assert payment.status is PaymentStatus.CONFIRMED
    assert payment.confirmed_at == NOW
    assert isinstance(event, PaymentConfirmed)


def test_confirm_twice_is_idempotent():
    payment = make()
    payment.pull_events()
    payment.confirm(NOW)
    payment.confirm(NOW + timedelta(minutes=1))
    assert len(payment.pull_events()) == 1
    assert payment.confirmed_at == NOW


def test_cannot_expire_before_deadline():
    payment = make()
    with pytest.raises(InvalidStateTransition):
        payment.expire(NOW + timedelta(minutes=29))


def test_expire_after_deadline_emits_event():
    payment = make()
    payment.pull_events()
    payment.expire(NOW + timedelta(minutes=30))
    (event,) = payment.pull_events()
    assert payment.status is PaymentStatus.EXPIRED
    assert isinstance(event, PaymentExpired)


def test_cannot_confirm_an_expired_payment():
    payment = make()
    payment.expire(NOW + timedelta(hours=1))
    with pytest.raises(InvalidStateTransition):
        payment.confirm(NOW + timedelta(hours=2))


def test_cannot_expire_a_confirmed_payment():
    payment = make()
    payment.confirm(NOW)
    with pytest.raises(InvalidStateTransition):
        payment.expire(NOW + timedelta(hours=1))


def test_cancel_pending_payment_emits_event():
    payment = make()
    payment.pull_events()
    payment.cancel()
    (event,) = payment.pull_events()
    assert payment.status is PaymentStatus.CANCELLED
    assert type(event).__name__ == "PaymentCancelled"


def test_cancel_is_idempotent_and_noop_for_expired():
    payment = make()
    payment.cancel()
    payment.pull_events()
    payment.cancel()
    assert payment.pull_events() == []

    expired = make()
    expired.expire(NOW + timedelta(hours=1))
    expired.pull_events()
    expired.cancel()
    assert expired.status is PaymentStatus.EXPIRED and expired.pull_events() == []


def test_cannot_cancel_a_confirmed_payment():
    payment = make()
    payment.confirm(NOW)
    with pytest.raises(InvalidStateTransition):
        payment.cancel()


def test_cannot_confirm_a_cancelled_payment_and_expire_is_a_noop():
    payment = make()
    payment.cancel()
    with pytest.raises(InvalidStateTransition):
        payment.confirm(NOW)
    payment.pull_events()
    payment.expire(NOW + timedelta(hours=1))
    assert payment.status is PaymentStatus.CANCELLED and payment.pull_events() == []
