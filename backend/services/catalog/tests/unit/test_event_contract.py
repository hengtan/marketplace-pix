from marketplace_common.events import assert_producer_contract
from marketplace_common.events.contract import (
    SAMPLE_EVENT_ID,
    SAMPLE_MERCHANT_ID,
    SAMPLE_OCCURRED_AT,
    SAMPLE_PRODUCT_ID,
)

from catalog.domain.events import (
    ProductCreated,
    ProductDeactivated,
    ProductPriceChanged,
    ProductUpdated,
)
from catalog.infrastructure.db.outbox import serialize_event

COMMON = {
    "product_id": SAMPLE_PRODUCT_ID,
    "merchant_id": SAMPLE_MERCHANT_ID,
    "event_id": SAMPLE_EVENT_ID,
    "occurred_at": SAMPLE_OCCURRED_AT,
}
SNAPSHOT = {
    "slug": "fone-bluetooth-nova",
    "name": "Fone Bluetooth Nova ANC",
    "category": "tecnologia",
    "price_cents": 34990,
    "currency": "BRL",
}


def test_product_created_matches_its_golden_file() -> None:
    assert_producer_contract(
        "ProductCreated", serialize_event(ProductCreated(**COMMON, **SNAPSHOT))
    )


def test_product_updated_matches_its_golden_file() -> None:
    assert_producer_contract(
        "ProductUpdated", serialize_event(ProductUpdated(**COMMON, **SNAPSHOT))
    )


def test_price_changed_matches_its_golden_file() -> None:
    event = ProductPriceChanged(
        **COMMON, old_price_cents=34990, new_price_cents=29990, currency="BRL"
    )
    assert_producer_contract("ProductPriceChanged", serialize_event(event))


def test_deactivated_matches_its_golden_file() -> None:
    assert_producer_contract("ProductDeactivated", serialize_event(ProductDeactivated(**COMMON)))
