from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from payments.application.confirm_payment import ConfirmPayment, ConfirmResult
from payments.application.errors import PaymentNotFound
from payments.application.handle_order_event import HandleOrderEvent
from payments.application.ports import ChargeStatus, IncomingEvent
from payments.domain.errors import InvalidStateTransition
from payments.domain.events import PaymentConfirmed
from payments.domain.payment import PaymentStatus
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
async def setup():
    db, psp = FakeDatabase(), FakePsp()
    order_id = uuid4()
    await HandleOrderEvent(lambda: FakeUow(db), psp, clock=lambda: NOW).handle(
        IncomingEvent(
            uuid4(),
            "OrderCreated",
            str(order_id),
            {"order_id": str(order_id), "total_cents": 4480, "currency": "BRL"},
        )
    )
    charge_id = psp.by_reference[str(order_id)].id
    use_case = ConfirmPayment(lambda: FakeUow(db), psp, clock=lambda: NOW)
    return db, psp, use_case, charge_id


async def test_confirms_when_psp_says_paid(setup):
    db, psp, use_case, charge_id = setup
    psp.statuses[charge_id] = ChargeStatus.PAID

    assert await use_case.execute(charge_id) is ConfirmResult.CONFIRMED

    (payment,) = db.payments.values()
    assert payment.status is PaymentStatus.CONFIRMED
    assert isinstance(db.events[-1], PaymentConfirmed)


async def test_fail_closed_when_psp_does_not_confirm(setup):
    db, psp, use_case, charge_id = setup

    assert await use_case.execute(charge_id) is ConfirmResult.NOT_PAID

    (payment,) = db.payments.values()
    assert payment.status is PaymentStatus.PENDING
    assert not any(isinstance(e, PaymentConfirmed) for e in db.events)


async def test_repeated_webhook_is_idempotent(setup):
    db, psp, use_case, charge_id = setup
    psp.statuses[charge_id] = ChargeStatus.PAID

    await use_case.execute(charge_id)
    second = await use_case.execute(charge_id)

    assert second is ConfirmResult.ALREADY_CONFIRMED
    assert sum(isinstance(e, PaymentConfirmed) for e in db.events) == 1


async def test_unknown_charge_is_not_found(setup):
    _, _, use_case, _ = setup
    with pytest.raises(PaymentNotFound):
        await use_case.execute("ch_unknown")


async def test_late_payment_on_expired_payment_is_rejected(setup):
    db, psp, _, charge_id = setup
    (payment,) = db.payments.values()
    payment.expire(NOW + timedelta(hours=1))
    psp.statuses[charge_id] = ChargeStatus.PAID
    late = ConfirmPayment(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=2))

    with pytest.raises(InvalidStateTransition):
        await late.execute(charge_id)
