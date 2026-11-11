from marketplace_common.events import assert_producer_contract
from marketplace_common.events.contract import (
    SAMPLE_EVENT_ID,
    SAMPLE_EXPIRES_AT,
    SAMPLE_OCCURRED_AT,
    SAMPLE_ORDER_ID,
    SAMPLE_PAYMENT_ID,
)

from payments.domain.events import (
    PaymentCancelled,
    PaymentConfirmed,
    PaymentCreated,
    PaymentExpired,
)
from payments.infrastructure.db.outbox import serialize_event

COMMON = {
    "order_id": SAMPLE_ORDER_ID,
    "payment_id": SAMPLE_PAYMENT_ID,
    "event_id": SAMPLE_EVENT_ID,
    "occurred_at": SAMPLE_OCCURRED_AT,
}


def test_payment_created_matches_its_golden_file() -> None:
    event = PaymentCreated(
        **COMMON,
        amount_cents=3980,
        currency="BRL",
        pix_code="SIMULATED-PIX|ch_0123456789abcdef|3980",
        expires_at=SAMPLE_EXPIRES_AT,
    )
    assert_producer_contract("PaymentCreated", serialize_event(event))


def test_payment_confirmed_matches_its_golden_file() -> None:
    event = PaymentConfirmed(**COMMON, amount_cents=3980, currency="BRL")
    assert_producer_contract("PaymentConfirmed", serialize_event(event))


def test_payment_expired_matches_its_golden_file() -> None:
    assert_producer_contract("PaymentExpired", serialize_event(PaymentExpired(**COMMON)))


def test_payment_cancelled_matches_its_golden_file() -> None:
    assert_producer_contract("PaymentCancelled", serialize_event(PaymentCancelled(**COMMON)))
