from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from catalog.domain.events import DomainEvent, ProductPriceChanged, ProductUpdated
from catalog.domain.product import Product

EDITABLE_FIELDS = frozenset({"name", "description", "price_cents", "category", "image_url", "tags"})


def apply_changes(
    product: Product, changes: Mapping[str, Any]
) -> tuple[Product, list[DomainEvent]]:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"fields not editable: {sorted(unknown)}")
    effective: dict[str, Any] = {
        key: tuple(value) if key == "tags" else value
        for key, value in changes.items()
        if getattr(product, key) != (tuple(value) if key == "tags" else value)
    }
    if not effective:
        return product, []
    updated = replace(product, **effective)
    events: list[DomainEvent] = []
    if "price_cents" in effective:
        events.append(
            ProductPriceChanged(
                product_id=product.id,
                merchant_id=product.merchant.id,
                old_price_cents=product.price_cents,
                new_price_cents=updated.price_cents,
                currency=updated.currency,
            )
        )
    if set(effective) - {"price_cents"}:
        events.append(
            ProductUpdated(
                product_id=product.id,
                merchant_id=product.merchant.id,
                slug=updated.slug,
                name=updated.name,
                category=updated.category,
                price_cents=updated.price_cents,
                currency=updated.currency,
            )
        )
    return updated, events
