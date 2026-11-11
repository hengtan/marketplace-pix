from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from payments.application.expire_payments import ExpirePayments
from payments.application.handle_order_event import HandleOrderEvent
from payments.infrastructure.db.models import OutboxEventModel
from payments.infrastructure.psp.simulated import SimulatedPsp
from payments.interface.api import create_app
from tests.integration.conftest import SECRET
from tests.integration.helpers import count, order_created


@pytest.fixture
async def client(uow_factory, psp):
    app = create_app(uow_factory=uow_factory, psp=psp, webhook_secret=SECRET, dev_psp=psp)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def outbox_types(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = (
            await session.execute(select(OutboxEventModel).order_by(OutboxEventModel.created_at))
        ).scalars()
        return sorted(r.type for r in rows)


async def test_full_flow_order_created_then_pix_paid_then_confirmed(
    client, uow_factory, session_factory, psp
):
    event = order_created()
    await HandleOrderEvent(uow_factory, psp).handle(event)

    payment = (await client.get(f"/payments/by-order/{event.key}")).json()
    assert payment["status"] == "PENDING"
    charge_id = payment["pix_code"].split("|")[1]

    paid = await client.post(f"/dev/psp/charges/{charge_id}/pay")
    assert paid.json()["webhook_status"] == 200
    assert paid.json()["webhook_body"] == {"status": "confirmed"}

    confirmed = (await client.get(f"/payments/by-order/{event.key}")).json()
    assert confirmed["status"] == "CONFIRMED" and confirmed["confirmed_at"]
    assert await outbox_types(session_factory) == ["PaymentConfirmed", "PaymentCreated"]


async def test_replayed_webhook_does_not_emit_a_second_confirmation(
    client, uow_factory, session_factory, psp
):
    event = order_created()
    await HandleOrderEvent(uow_factory, psp).handle(event)
    charge_id = (
        (await client.get(f"/payments/by-order/{event.key}")).json()["pix_code"].split("|")[1]
    )
    await client.post(f"/dev/psp/charges/{charge_id}/pay")

    from payments.interface.webhook_security import sign

    body = f'{{"event":"charge.paid","charge_id":"{charge_id}"}}'.encode()
    again = await client.post(
        "/webhooks/psp", content=body, headers={"X-Signature": sign(SECRET, body)}
    )

    assert again.json() == {"status": "already_confirmed"}
    assert await count(session_factory, OutboxEventModel) == 2


async def test_forged_webhook_with_valid_signature_but_unpaid_charge_changes_nothing(
    client, uow_factory, session_factory, psp
):
    from payments.interface.webhook_security import sign

    event = order_created()
    await HandleOrderEvent(uow_factory, psp).handle(event)
    charge_id = (
        (await client.get(f"/payments/by-order/{event.key}")).json()["pix_code"].split("|")[1]
    )
    body = f'{{"event":"charge.paid","charge_id":"{charge_id}"}}'.encode()

    response = await client.post(
        "/webhooks/psp", content=body, headers={"X-Signature": sign(SECRET, body)}
    )

    assert response.status_code == 409
    assert (await client.get(f"/payments/by-order/{event.key}")).json()["status"] == "PENDING"


async def test_expiry_marks_payment_expired_and_blocks_late_payment(
    client, uow_factory, session_factory, psp
):
    event = order_created()
    await HandleOrderEvent(uow_factory, psp, ttl=timedelta(minutes=30)).handle(event)
    charge_id = (
        (await client.get(f"/payments/by-order/{event.key}")).json()["pix_code"].split("|")[1]
    )

    later = lambda: datetime.now(UTC) + timedelta(hours=1)  # noqa: E731
    assert await ExpirePayments(uow_factory, clock=later).run_once() == 1
    assert await ExpirePayments(uow_factory, clock=later).run_once() == 0

    assert (await client.get(f"/payments/by-order/{event.key}")).json()["status"] == "EXPIRED"
    assert await outbox_types(session_factory) == ["PaymentCreated", "PaymentExpired"]
    late_psp = SimulatedPsp(session_factory, clock=later)
    assert await late_psp.mark_paid(charge_id) is False


async def test_order_cancelled_cancels_the_charge_and_blocks_a_late_payment(
    client, uow_factory, session_factory, psp
):
    from payments.application.handle_order_event import HandleOrderEvent as Handler
    from payments.application.ports import IncomingEvent

    created = order_created()
    await Handler(uow_factory, psp).handle(created)
    charge_id = (await client.get(f"/payments/by-order/{created.key}")).json()["psp_charge_id"]

    cancelled = IncomingEvent(
        uuid4(), "OrderCancelled", created.key, {"order_id": created.key, "reason": "out of stock"}
    )
    assert (await Handler(uow_factory, psp).handle(cancelled)).value == "PROCESSED"

    assert (await client.get(f"/payments/by-order/{created.key}")).json()["status"] == "CANCELLED"
    assert await outbox_types(session_factory) == ["PaymentCancelled", "PaymentCreated"]
    late = await client.post(f"/dev/psp/charges/{charge_id}/pay")
    assert late.status_code == 409
