import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from payments.application.handle_order_event import HandleOrderEvent
from payments.application.ports import ChargeStatus, IncomingEvent
from payments.interface.api import create_app
from payments.interface.webhook_security import sign
from tests.fakes import FakeDatabase, FakePsp, FakeUow

SECRET = "test-secret"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
async def env():
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
    app = create_app(uow_factory=lambda: FakeUow(db), psp=psp, webhook_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, db, psp, order_id, psp.by_reference[str(order_id)].id


def webhook(charge_id, event="charge.paid"):
    body = json.dumps({"event": event, "charge_id": charge_id}).encode()
    return body, {"X-Signature": sign(SECRET, body)}


async def test_webhook_without_signature_is_401(env):
    client, _, _, _, charge_id = env
    body, _ = webhook(charge_id)
    assert (await client.post("/webhooks/psp", content=body)).status_code == 401


async def test_webhook_with_wrong_signature_is_401_and_changes_nothing(env):
    client, db, psp, _, charge_id = env
    psp.statuses[charge_id] = ChargeStatus.PAID
    body, _ = webhook(charge_id)

    response = await client.post("/webhooks/psp", content=body, headers={"X-Signature": "bad"})

    assert response.status_code == 401
    assert next(iter(db.payments.values())).status.value == "PENDING"


async def test_signature_made_with_another_secret_is_401(env):
    client, _, _, _, charge_id = env
    body, _ = webhook(charge_id)
    headers = {"X-Signature": sign("other-secret", body)}
    assert (await client.post("/webhooks/psp", content=body, headers=headers)).status_code == 401


async def test_valid_webhook_confirms_when_psp_agrees(env):
    client, db, psp, _, charge_id = env
    psp.statuses[charge_id] = ChargeStatus.PAID
    body, headers = webhook(charge_id)

    response = await client.post("/webhooks/psp", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "confirmed"}
    assert next(iter(db.payments.values())).status.value == "CONFIRMED"


async def test_validly_signed_webhook_is_still_rejected_if_psp_says_not_paid(env):
    client, db, _, _, charge_id = env
    body, headers = webhook(charge_id)

    response = await client.post("/webhooks/psp", content=body, headers=headers)

    assert response.status_code == 409
    assert next(iter(db.payments.values())).status.value == "PENDING"


async def test_other_webhook_events_are_ignored(env):
    client, _, _, _, charge_id = env
    body, headers = webhook(charge_id, event="charge.created")
    response = await client.post("/webhooks/psp", content=body, headers=headers)
    assert response.json() == {"status": "ignored"}


async def test_unknown_charge_is_404(env):
    client, _, psp, _, _ = env
    body, headers = webhook("ch_unknown")
    assert (await client.post("/webhooks/psp", content=body, headers=headers)).status_code == 404


async def test_get_payment_by_order(env):
    client, _, _, order_id, _ = env
    response = await client.get(f"/payments/by-order/{order_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assert response.json()["amount_cents"] == 4480
    assert (await client.get(f"/payments/by-order/{uuid4()}")).status_code == 404


async def test_dev_endpoint_is_disabled_by_default(env):
    client, _, _, _, charge_id = env
    assert (await client.post(f"/dev/psp/charges/{charge_id}/pay")).status_code == 404


async def test_health(env):
    client, *_ = env
    assert (await client.get("/health")).json() == {"status": "ok"}
