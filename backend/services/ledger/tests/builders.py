from datetime import datetime
from uuid import UUID, uuid4

from marketplace_common.messaging import IncomingEvent


def order_created(
    order_id: UUID | None = None,
    lines: list[tuple[UUID, int, int]] | None = None,
    event_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> IncomingEvent:
    order_id = order_id or uuid4()
    lines = lines or [(uuid4(), 1, 10000)]
    items = [
        {
            "product_id": str(uuid4()),
            "merchant_id": str(merchant),
            "quantity": qty,
            "unit_price_cents": price,
        }
        for merchant, qty, price in lines
    ]
    payload = {
        "order_id": str(order_id),
        "customer_id": str(uuid4()),
        "customer_name": "Ana",
        "customer_email": "ana@example.com",
        "total_cents": sum(qty * price for _, qty, price in lines),
        "currency": "BRL",
        "items": items,
    }
    if occurred_at:
        payload["occurred_at"] = occurred_at.isoformat()
    return IncomingEvent(event_id or uuid4(), "OrderCreated", str(order_id), payload)


def payment_confirmed(
    order_id: UUID,
    amount_cents: int,
    payment_id: UUID | None = None,
    event_id: UUID | None = None,
    currency: str = "BRL",
) -> IncomingEvent:
    return IncomingEvent(
        event_id or uuid4(),
        "PaymentConfirmed",
        str(order_id),
        {
            "order_id": str(order_id),
            "payment_id": str(payment_id or uuid4()),
            "amount_cents": amount_cents,
            "currency": currency,
        },
    )


def payment_refunded(
    order_id: UUID,
    amount_cents: int,
    payment_id: UUID,
    event_id: UUID | None = None,
    currency: str = "BRL",
) -> IncomingEvent:
    return IncomingEvent(
        event_id or uuid4(),
        "PaymentRefunded",
        str(order_id),
        {
            "order_id": str(order_id),
            "payment_id": str(payment_id),
            "amount_cents": amount_cents,
            "currency": currency,
            "reason": "order cancelled before payment",
        },
    )
