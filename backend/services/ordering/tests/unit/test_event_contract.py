from uuid import uuid4

import pytest
from marketplace_common.events import assert_producer_contract, golden_payload
from marketplace_common.events.contract import (
    SAMPLE_CUSTOMER_ID,
    SAMPLE_EVENT_ID,
    SAMPLE_MERCHANT_ID,
    SAMPLE_OCCURRED_AT,
    SAMPLE_ORDER_ID,
    SAMPLE_PRODUCT_ID,
)

from ordering.domain.events import OrderCancelled, OrderCreated, OrderCreatedItem, OrderPaid
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem
from ordering.infrastructure.db.outbox import serialize_event

COMMON = {
    "order_id": SAMPLE_ORDER_ID,
    "event_id": SAMPLE_EVENT_ID,
    "occurred_at": SAMPLE_OCCURRED_AT,
}


def order_created(customer_type: str | None) -> OrderCreated:
    return OrderCreated(
        **COMMON,
        customer_id=SAMPLE_CUSTOMER_ID,
        customer_name="Maria Souza",
        customer_email="maria@example.com",
        total_cents=3980,
        currency="BRL",
        customer_type=customer_type,
        items=(
            OrderCreatedItem(
                product_id=SAMPLE_PRODUCT_ID,
                merchant_id=SAMPLE_MERCHANT_ID,
                quantity=2,
                unit_price_cents=1990,
            ),
        ),
    )


def test_order_created_matches_the_v2_golden_file() -> None:
    assert_producer_contract("OrderCreated", serialize_event(order_created("registered")))


def test_order_paid_matches_the_v1_golden_file() -> None:
    assert_producer_contract("OrderPaid", serialize_event(OrderPaid(**COMMON)))


def test_order_cancelled_matches_the_v1_golden_file() -> None:
    event = OrderCancelled(**COMMON, reason="payment expired")
    assert_producer_contract("OrderCancelled", serialize_event(event))


def test_a_producer_that_drops_a_field_breaks_the_contract() -> None:
    payload = serialize_event(order_created("registered"))
    del payload["customer_email"]
    with pytest.raises(AssertionError, match="customer_email"):
        assert_producer_contract("OrderCreated", payload)


def test_a_producer_that_adds_a_field_without_a_new_version_breaks_the_contract() -> None:
    payload = serialize_event(order_created("registered"))
    payload["coupon_code"] = "BLACKFRIDAY"
    with pytest.raises(AssertionError, match="coupon_code"):
        assert_producer_contract("OrderCreated", payload)


def test_aggregate_emits_v2_with_the_right_customer_type() -> None:
    item = OrderItem(uuid4(), uuid4(), 1, Money(1000, "BRL"))
    guest = Order.create(uuid4(), [item], "Ana", "ana@example.com")
    member = Order.create(uuid4(), [item], "Ana", "ana@example.com", owner_id=uuid4())
    guest_payload = serialize_event(guest.pull_events()[0])
    member_payload = serialize_event(member.pull_events()[0])
    assert guest_payload["schema_version"] == member_payload["schema_version"] == 2
    assert (guest_payload["customer_type"], member_payload["customer_type"]) == (
        "guest",
        "registered",
    )
    assert set(guest_payload) == set(golden_payload("OrderCreated", 2))
