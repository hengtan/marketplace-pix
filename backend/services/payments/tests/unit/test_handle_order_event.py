from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from marketplace_common.messaging import IncomingEvent

from payments.application.handle_order_event import HandleOrderEvent, HandleResult
from payments.domain.events import PaymentCreated
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def order_created(order_id=None, event_id=None, total=4480) -> IncomingEvent:
    order_id = order_id or uuid4()
    return IncomingEvent(
        id=event_id or uuid4(),
        type="OrderCreated",
        key=str(order_id),
        payload={"order_id": str(order_id), "total_cents": total, "currency": "BRL"},
    )


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
def psp():
    return FakePsp()


@pytest.fixture
def handler(db, psp):
    return HandleOrderEvent(lambda: FakeUow(db), psp, ttl=timedelta(minutes=30), clock=lambda: NOW)


async def test_order_created_creates_charge_payment_and_event(handler, db, psp):
    event = order_created()

    assert await handler.handle(event) is HandleResult.PROCESSED

    (payment,) = db.payments.values()
    assert payment.amount.cents == 4480
    assert payment.expires_at == NOW + timedelta(minutes=30)
    assert psp.charges == 1
    assert [type(e) for e in db.events] == [PaymentCreated]


async def test_same_event_delivered_twice_creates_one_payment(handler, db, psp):
    event = order_created()

    first = await handler.handle(event)
    second = await handler.handle(event)

    assert (first, second) == (HandleResult.PROCESSED, HandleResult.DUPLICATE)
    assert len(db.payments) == 1
    assert psp.charges == 1
    assert len(db.events) == 1


async def test_two_different_events_for_the_same_order_create_one_payment(handler, db, psp):
    order_id = uuid4()

    await handler.handle(order_created(order_id))
    result = await handler.handle(order_created(order_id))

    assert result is HandleResult.DUPLICATE
    assert len(db.payments) == 1
    assert psp.charges == 1


async def test_other_event_types_are_ignored(handler, db, psp):
    event = IncomingEvent(id=uuid4(), type="OrderPaid", key="k", payload={})

    assert await handler.handle(event) is HandleResult.IGNORED
    assert db.payments == {} and psp.charges == 0 and db.inbox == set()


async def test_psp_failure_saves_nothing_and_allows_redelivery(handler, db, psp):
    event = order_created()
    psp.fail_create = True

    with pytest.raises(ConnectionError):
        await handler.handle(event)
    assert db.payments == {} and db.inbox == set()

    psp.fail_create = False
    assert await handler.handle(event) is HandleResult.PROCESSED
    assert len(db.payments) == 1


def order_cancelled(order_id, event_id=None) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type="OrderCancelled",
        key=str(order_id),
        payload={"order_id": str(order_id), "reason": "out of stock"},
    )


async def test_order_cancelled_cancels_the_pending_payment_and_the_psp_charge(handler, db, psp):
    created = order_created()
    await handler.handle(created)
    order_id = UUID(created.key)

    result = await handler.handle(order_cancelled(order_id))

    assert result is HandleResult.PROCESSED
    (payment,) = db.payments.values()
    assert payment.status.value == "CANCELLED"
    assert psp.cancelled == [payment.psp_charge_id]
    assert [type(e).__name__ for e in db.events] == ["PaymentCreated", "PaymentCancelled"]


async def test_order_cancelled_delivered_twice_applies_once(handler, db, psp):
    created = order_created()
    await handler.handle(created)
    event = order_cancelled(UUID(created.key))

    assert await handler.handle(event) is HandleResult.PROCESSED
    assert await handler.handle(event) is HandleResult.DUPLICATE
    assert len(psp.cancelled) == 1 and len(db.events) == 2


async def test_order_cancelled_for_an_unknown_order_is_ignored(handler, db):
    assert await handler.handle(order_cancelled(uuid4())) is HandleResult.IGNORED
    assert db.inbox == set()


async def test_order_cancelled_after_the_payment_was_confirmed_is_a_conflict(handler, db, psp):
    created = order_created()
    await handler.handle(created)
    (payment,) = db.payments.values()
    payment.confirm(NOW)

    result = await handler.handle(order_cancelled(UUID(created.key)))

    assert result is HandleResult.CONFLICT
    assert payment.status.value == "CONFIRMED" and psp.cancelled == []


async def test_if_the_psp_refuses_to_cancel_the_payment_stays_pending(handler, db, psp):
    created = order_created()
    await handler.handle(created)
    psp.refuse_cancel = True

    result = await handler.handle(order_cancelled(UUID(created.key)))

    assert result is HandleResult.CONFLICT
    (payment,) = db.payments.values()
    assert payment.status.value == "PENDING"
    assert [type(e).__name__ for e in db.events] == ["PaymentCreated"]
