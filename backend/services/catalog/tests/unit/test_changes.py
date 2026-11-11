from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from catalog.domain.changes import apply_changes
from catalog.domain.events import ProductPriceChanged, ProductUpdated
from catalog.domain.product import Merchant, Product


def product() -> Product:
    return Product(
        id=uuid4(),
        slug="fone",
        name="Fone",
        description="Fone sem fio",
        price_cents=10000,
        currency="BRL",
        category="tecnologia",
        image_url=None,
        rating=Decimal("4.5"),
        reviews_count=10,
        tags=("audio",),
        merchant=Merchant(uuid4(), "aurora-tech", "Aurora Tech"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_changing_only_the_price_emits_only_a_price_event() -> None:
    before = product()
    after, events = apply_changes(before, {"price_cents": 8000})
    assert after.price_cents == 8000
    (event,) = events
    assert isinstance(event, ProductPriceChanged)
    assert (event.old_price_cents, event.new_price_cents) == (10000, 8000)
    assert event.product_id == before.id and event.merchant_id == before.merchant.id


def test_changing_text_emits_an_updated_event_with_the_snapshot() -> None:
    after, events = apply_changes(product(), {"name": "Fone Pro", "tags": ["audio", "anc"]})
    (event,) = events
    assert isinstance(event, ProductUpdated)
    assert event.name == "Fone Pro" == after.name
    assert after.tags == ("audio", "anc")


def test_price_and_text_together_emit_both_events() -> None:
    _, events = apply_changes(product(), {"price_cents": 9000, "description": "novo"})
    assert {type(e) for e in events} == {ProductPriceChanged, ProductUpdated}


def test_values_equal_to_the_current_ones_change_nothing() -> None:
    before = product()
    after, events = apply_changes(before, {"price_cents": 10000, "name": "Fone"})
    assert after == before
    assert events == []


def test_a_non_positive_price_is_rejected() -> None:
    with pytest.raises(ValueError):
        apply_changes(product(), {"price_cents": 0})


def test_fields_outside_the_editable_set_are_rejected() -> None:
    with pytest.raises(ValueError):
        apply_changes(product(), {"rating": 5})
