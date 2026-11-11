from datetime import UTC, datetime, timedelta
from uuid import uuid4

from marketplace_common.messaging import IncomingEvent

from payments.application.expire_payments import ExpirePayments
from payments.application.handle_order_event import HandleOrderEvent
from payments.application.ports import ChargeStatus
from payments.domain.events import PaymentExpired
from payments.domain.payment import PaymentStatus
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


async def create_payment(db, psp):
    order_id = uuid4()
    await HandleOrderEvent(
        lambda: FakeUow(db), psp, ttl=timedelta(minutes=30), clock=lambda: NOW
    ).handle(
        IncomingEvent(
            uuid4(),
            "OrderCreated",
            str(order_id),
            {"order_id": str(order_id), "total_cents": 1000, "currency": "BRL"},
        )
    )


async def test_expires_only_payments_past_deadline():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)

    early = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(minutes=29))
    assert await early.run_once() == 0

    late = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(minutes=31))
    assert await late.run_once() == 1

    (payment,) = db.payments.values()
    assert payment.status is PaymentStatus.EXPIRED
    assert sum(isinstance(e, PaymentExpired) for e in db.events) == 1


async def test_running_twice_does_not_emit_a_second_event():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    job = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=1))

    assert await job.run_once() == 1
    assert await job.run_once() == 0
    assert sum(isinstance(e, PaymentExpired) for e in db.events) == 1


async def test_expiring_cancels_the_charge_at_the_psp():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    (payment,) = db.payments.values()

    job = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=1))
    assert await job.run_once() == 1

    assert psp.cancelled == [payment.psp_charge_id]
    assert psp.statuses[payment.psp_charge_id] is ChargeStatus.CANCELLED
    assert await job.run_once() == 0
    assert psp.cancelled == [payment.psp_charge_id]


async def test_a_charge_that_was_paid_is_not_expired_and_not_cancelled():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    (payment,) = db.payments.values()
    psp.refuse_cancel = True

    job = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=1))
    assert await job.run_once() == 0

    assert payment.status is PaymentStatus.PENDING
    assert not any(isinstance(e, PaymentExpired) for e in db.events)


async def test_a_psp_outage_postpones_the_expiry_and_the_next_run_finishes_it():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    job = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=1))

    psp.fail_cancel = True
    assert await job.run_once() == 0
    (payment,) = db.payments.values()
    assert payment.status is PaymentStatus.PENDING

    psp.fail_cancel = False
    assert await job.run_once() == 1
    assert db.payments[payment.id].status is PaymentStatus.EXPIRED


async def test_one_failing_charge_does_not_block_the_others():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    await create_payment(db, psp)
    first_charge = next(iter(psp.by_reference.values())).id
    psp.fail_cancel_for = {first_charge}

    job = ExpirePayments(lambda: FakeUow(db), psp, clock=lambda: NOW + timedelta(hours=1))
    assert await job.run_once() == 1

    statuses = sorted(p.status.value for p in db.payments.values())
    assert statuses == ["EXPIRED", "PENDING"]
