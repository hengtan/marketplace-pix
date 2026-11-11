from __future__ import annotations

import pytest
from pydantic import ValidationError

from marketplace_common.events import REGISTRY, golden_payload

CATALOG_TYPES = ["ProductCreated", "ProductDeactivated", "ProductPriceChanged", "ProductUpdated"]


def test_the_catalog_event_types_are_registered() -> None:
    assert set(CATALOG_TYPES) <= set(REGISTRY.types())


@pytest.mark.parametrize("event_type", CATALOG_TYPES)
def test_catalog_events_are_keyed_by_product_and_have_no_order(event_type: str) -> None:
    payload = golden_payload(event_type, 1)
    parsed = REGISTRY.parse(event_type, payload)
    assert str(parsed.product_id) == payload["product_id"]  # type: ignore[attr-defined]
    assert "order_id" not in payload
    assert payload["schema_version"] == 1


def test_a_price_change_carries_both_prices() -> None:
    payload = golden_payload("ProductPriceChanged", 1)
    assert payload["old_price_cents"] != payload["new_price_cents"]
    broken = {k: v for k, v in payload.items() if k != "new_price_cents"}
    with pytest.raises(ValidationError):
        REGISTRY.parse("ProductPriceChanged", broken)
