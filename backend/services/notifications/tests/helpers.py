from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from notifications.application.ports import IncomingEvent

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
CUSTOMER_ID = uuid4()


def order_created(
    order_id: UUID | None = None,
    event_id: UUID | None = None,
    customer_id: UUID | None = None,
    email: str = "maria@example.com",
    name: str = "Maria da Silva",
    occurred_at: datetime = NOW,
) -> IncomingEvent:
    order_id = order_id or uuid4()
    return IncomingEvent(
        id=event_id or uuid4(),
        type="OrderCreated",
        key=str(order_id),
        payload={
            "order_id": str(order_id),
            "customer_id": str(customer_id or CUSTOMER_ID),
            "customer_name": name,
            "customer_email": email,
            "total_cents": 394_880,
            "currency": "BRL",
            "items": [
                {
                    "product_id": str(uuid4()),
                    "merchant_id": str(uuid4()),
                    "quantity": 2,
                    "unit_price_cents": 34990,
                },
                {
                    "product_id": str(uuid4()),
                    "merchant_id": str(uuid4()),
                    "quantity": 1,
                    "unit_price_cents": 324_900,
                },
            ],
            "event_id": str(event_id or uuid4()),
            "occurred_at": occurred_at.isoformat(),
        },
    )


def event(
    event_type: str, order_id: UUID, event_id: UUID | None = None, **payload: Any
) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type=event_type,
        key=str(order_id),
        payload={"order_id": str(order_id), **payload},
    )


def payment_created(order_id: UUID, event_id: UUID | None = None) -> IncomingEvent:
    return event(
        "PaymentCreated",
        order_id,
        event_id,
        payment_id=str(uuid4()),
        amount_cents=394_880,
        currency="BRL",
        pix_code="00020126PIXCODE5303986",
        expires_at="2026-11-11T15:30:00+00:00",
    )


def order_paid(order_id: UUID, event_id: UUID | None = None) -> IncomingEvent:
    return event("OrderPaid", order_id, event_id, occurred_at=NOW.isoformat())


def order_cancelled(
    order_id: UUID, reason: str = "out of stock", event_id: UUID | None = None
) -> IncomingEvent:
    return event("OrderCancelled", order_id, event_id, reason=reason, occurred_at=NOW.isoformat())
