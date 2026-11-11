from datetime import UTC, datetime, timedelta
from uuid import uuid4

from marketplace_common.messaging import IncomingEvent

from payments.application.expire_payments import ExpirePayments
from payments.application.handle_order_event import HandleOrderEvent
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

    early = ExpirePayments(lambda: FakeUow(db), clock=lambda: NOW + timedelta(minutes=29))
    assert await early.run_once() == 0

    late = ExpirePayments(lambda: FakeUow(db), clock=lambda: NOW + timedelta(minutes=31))
    assert await late.run_once() == 1

    (payment,) = db.payments.values()
    assert payment.status is PaymentStatus.EXPIRED
    assert sum(isinstance(e, PaymentExpired) for e in db.events) == 1


async def test_running_twice_does_not_emit_a_second_event():
    db, psp = FakeDatabase(), FakePsp()
    await create_payment(db, psp)
    job = ExpirePayments(lambda: FakeUow(db), clock=lambda: NOW + timedelta(hours=1))

    assert await job.run_once() == 1
    assert await job.run_once() == 0
    assert sum(isinstance(e, PaymentExpired) for e in db.events) == 1
