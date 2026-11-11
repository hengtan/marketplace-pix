from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from marketplace_common.messaging import IncomingEvent

from payments.application.handle_order_event import HandleOrderEvent, HandleResult
from payments.application.ports import ChargeStatus
from payments.domain.errors import InvalidStateTransition
from payments.domain.events import PaymentRefunded
from payments.domain.money import Money
from payments.domain.payment import Payment, PaymentStatus
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def make_payment() -> Payment:
    payment = Payment.create(
        uuid4(), Money(3980, "BRL"), "ch_1", "PIX", NOW + timedelta(minutes=30)
    )
    payment.pull_events()
    return payment


def refund_requested(
    order_id: UUID, payment_id: UUID, event_id: UUID | None = None
) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type="PaymentRefundRequested",
        key=str(order_id),
        payload={
            "order_id": str(order_id),
            "payment_id": str(payment_id),
            "amount_cents": 3980,
            "currency": "BRL",
            "reason": "order cancelled before payment",
        },
    )


def test_confirmed_payment_can_be_refunded_once() -> None:
    payment = make_payment()
    payment.confirm(NOW)
    payment.pull_events()

    payment.refund("late payment")
    payment.refund("late payment")

    assert payment.status is PaymentStatus.REFUNDED
    (event,) = payment.pull_events()
    assert isinstance(event, PaymentRefunded) and event.reason == "late payment"
    assert event.amount_cents == 3980


@pytest.mark.parametrize("prepare", ["pending", "cancelled", "expired"])
def test_only_a_confirmed_payment_can_be_refunded(prepare: str) -> None:
    payment = make_payment()
    if prepare == "cancelled":
        payment.cancel()
    if prepare == "expired":
        payment.expire(NOW + timedelta(hours=1))
    with pytest.raises(InvalidStateTransition):
        payment.refund("x")


@pytest.fixture
def world():
    db, psp = FakeDatabase(), FakePsp()
    payment = make_payment()
    payment.confirm(NOW)
    payment.pull_events()
    db.payments[payment.id] = payment
    psp.statuses["ch_1"] = ChargeStatus.PAID
    handler = HandleOrderEvent(lambda: FakeUow(db), psp, clock=lambda: NOW)
    return db, psp, payment, handler


async def test_refund_request_refunds_at_the_psp_and_emits_the_event(world):
    db, psp, payment, handler = world

    result = await handler.handle(refund_requested(payment.order_id, payment.id))

    assert result is HandleResult.REFUNDED
    assert db.payments[payment.id].status is PaymentStatus.REFUNDED
    assert psp.refunded == ["ch_1"]
    assert [type(e) for e in db.events] == [PaymentRefunded]


async def test_refund_is_idempotent_across_redelivery_and_distinct_events(world):
    db, psp, payment, handler = world
    request = refund_requested(payment.order_id, payment.id)

    first = await handler.handle(request)
    same_event = await handler.handle(request)
    other_event = await handler.handle(refund_requested(payment.order_id, payment.id))

    assert (first, same_event, other_event) == (
        HandleResult.REFUNDED,
        HandleResult.DUPLICATE,
        HandleResult.DUPLICATE,
    )
    assert psp.refunded == ["ch_1"]
    assert len(db.events) == 1


async def test_refund_for_a_payment_that_was_never_confirmed_is_ignored(world):
    db, psp, payment, handler = world
    pending = make_payment()
    db.payments[pending.id] = pending
    psp.statuses["ch_1"] = ChargeStatus.PENDING

    result = await handler.handle(refund_requested(pending.order_id, pending.id))

    assert result is HandleResult.IGNORED
    assert psp.refunded == [] and db.events == []


async def test_refund_for_an_unknown_order_is_ignored(world):
    _, psp, _, handler = world
    assert await handler.handle(refund_requested(uuid4(), uuid4())) is HandleResult.IGNORED
    assert psp.refunded == []


async def test_psp_failure_leaves_the_payment_confirmed_so_the_retry_can_finish(world):
    db, psp, payment, handler = world
    psp.refuse_refund = True

    with pytest.raises(RuntimeError):
        await handler.handle(refund_requested(payment.order_id, payment.id))

    assert db.payments[payment.id].status is PaymentStatus.CONFIRMED
    assert db.events == [] and db.inbox == set()
    psp.refuse_refund = False
    assert (
        await handler.handle(refund_requested(payment.order_id, payment.id))
        is HandleResult.REFUNDED
    )
