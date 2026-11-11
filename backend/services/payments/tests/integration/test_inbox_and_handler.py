import asyncio
from uuid import uuid4

from sqlalchemy import select

from payments.application.handle_order_event import HandleOrderEvent, HandleResult
from payments.infrastructure.db.models import (
    InboxMessageModel,
    OutboxEventModel,
    PaymentModel,
    SimulatedChargeModel,
)
from tests.integration.helpers import count, order_created


async def test_inbox_claim_is_true_once_then_false(uow_factory):
    message_id = uuid4()
    async with uow_factory() as uow:
        assert await uow.inbox.claim(message_id, "payments") is True
        assert await uow.inbox.claim(message_id, "payments") is False
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.inbox.claim(message_id, "payments") is False
        assert await uow.inbox.claim(message_id, "other-consumer") is True


async def test_failure_before_commit_releases_the_inbox_claim(uow_factory, session_factory):
    message_id = uuid4()
    try:
        async with uow_factory() as uow:
            assert await uow.inbox.claim(message_id, "payments")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert await count(session_factory, InboxMessageModel) == 0
    async with uow_factory() as uow:
        assert await uow.inbox.claim(message_id, "payments") is True


async def test_handler_creates_payment_charge_and_event_in_real_database(
    uow_factory, session_factory, psp
):
    handler = HandleOrderEvent(uow_factory, psp)
    event = order_created()

    assert await handler.handle(event) is HandleResult.PROCESSED

    async with session_factory() as session:
        payment = (await session.execute(select(PaymentModel))).scalars().one()
        outbox = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert payment.status == "PENDING" and payment.amount_cents == 4480
    assert outbox.type == "PaymentCreated" and outbox.topic == "payments.events"
    assert outbox.key == event.key and outbox.published_at is None
    assert await count(session_factory, SimulatedChargeModel) == 1


async def test_five_concurrent_deliveries_of_the_same_event_create_one_payment(
    uow_factory, session_factory, psp
):
    handler = HandleOrderEvent(uow_factory, psp)
    event = order_created()

    results = await asyncio.gather(*(handler.handle(event) for _ in range(5)))

    assert sorted(r.value for r in results) == ["DUPLICATE"] * 4 + ["PROCESSED"]
    assert await count(session_factory, PaymentModel) == 1
    assert await count(session_factory, SimulatedChargeModel) == 1
    assert await count(session_factory, OutboxEventModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1
