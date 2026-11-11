import asyncio
from uuid import uuid4

import httpx
import pytest
from marketplace_common.messaging import IncomingEvent
from sqlalchemy import select

from payments.application.handle_order_event import HandleOrderEvent, HandleResult
from payments.infrastructure.db.models import OutboxEventModel, PaymentModel, SimulatedChargeModel
from payments.interface.api import create_app
from tests.integration.conftest import SECRET
from tests.integration.helpers import order_created


@pytest.fixture
async def client(uow_factory, psp):
    app = create_app(uow_factory=uow_factory, psp=psp, webhook_secret=SECRET, dev_psp=psp)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def refund_request(order_key: str, payment_id: str) -> IncomingEvent:
    return IncomingEvent(
        id=uuid4(),
        type="PaymentRefundRequested",
        key=order_key,
        payload={
            "order_id": order_key,
            "payment_id": payment_id,
            "amount_cents": 4480,
            "currency": "BRL",
            "reason": "order cancelled before payment",
        },
    )


async def pay(client, order_key: str) -> dict:
    payment = (await client.get(f"/payments/by-order/{order_key}")).json()
    charge_id = payment["psp_charge_id"]
    assert (await client.post(f"/dev/psp/charges/{charge_id}/pay")).json()["webhook_status"] == 200
    return payment


async def test_late_payment_is_refunded_at_the_psp_and_audited_in_the_outbox(
    client, uow_factory, session_factory, psp
):
    handler = HandleOrderEvent(uow_factory, psp)
    created = order_created()
    await handler.handle(created)
    payment = await pay(client, created.key)

    results = await asyncio.gather(
        *(handler.handle(refund_request(created.key, payment["id"])) for _ in range(4))
    )

    assert sorted(r.value for r in results).count("REFUNDED") == 1
    assert HandleResult.REFUNDED in results
    async with session_factory() as session:
        stored = (await session.execute(select(PaymentModel))).scalar_one()
        charge = (await session.execute(select(SimulatedChargeModel))).scalar_one()
        events = (
            (
                await session.execute(
                    select(OutboxEventModel).where(OutboxEventModel.type == "PaymentRefunded")
                )
            )
            .scalars()
            .all()
        )
    assert stored.status == "REFUNDED"
    assert charge.status == "REFUNDED"
    assert len(events) == 1
    assert events[0].payload["amount_cents"] == 4480
    assert events[0].payload["reason"] == "order cancelled before payment"
    assert events[0].payload["schema_version"] == 1
    assert (await client.get(f"/payments/by-order/{created.key}")).json()["status"] == "REFUNDED"


async def test_a_pending_charge_is_not_refunded(client, uow_factory, psp, session_factory):
    handler = HandleOrderEvent(uow_factory, psp)
    created = order_created()
    await handler.handle(created)
    payment = (await client.get(f"/payments/by-order/{created.key}")).json()

    result = await handler.handle(refund_request(created.key, payment["id"]))

    assert result is HandleResult.IGNORED
    assert (await client.get(f"/payments/by-order/{created.key}")).json()["status"] == "PENDING"
