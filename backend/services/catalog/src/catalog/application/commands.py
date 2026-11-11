from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from marketplace_common.security import Principal, Scope

from catalog.application.ports import UowFactory
from catalog.domain.changes import apply_changes
from catalog.domain.errors import (
    DuplicateSlug,
    InvalidProduct,
    NotProductOwner,
    ProductNotFound,
)
from catalog.domain.events import ProductCreated, ProductDeactivated
from catalog.domain.product import Merchant, Product

DEFAULT_CURRENCY = "BRL"


@dataclass(frozen=True, slots=True)
class NewProduct:
    name: str
    description: str
    price_cents: int
    category: str
    slug: str | None = None
    image_url: str | None = None
    tags: tuple[str, ...] = ()
    merchant_id: UUID | None = None


def slugify(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:120]


def _may_manage(principal: Principal, merchant_id: UUID) -> bool:
    if principal.can(Scope.CATALOG_WRITE_ANY):
        return True
    return principal.can(Scope.CATALOG_WRITE_OWN) and principal.owns_merchant(merchant_id)


class ManageProducts:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def create(self, principal: Principal, data: NewProduct) -> Product:
        target = data.merchant_id or principal.merchant_id
        if target is None:
            raise InvalidProduct("merchant_id is required")
        if not _may_manage(principal, target):
            raise NotProductOwner(str(target))
        slug = data.slug or slugify(data.name)
        if not slug:
            raise InvalidProduct("slug could not be derived from the name")
        async with self._uow_factory() as uow:
            merchant: Merchant | None = await uow.products.merchant(target)
            if merchant is None:
                raise InvalidProduct("merchant not found")
            if not await uow.products.category_exists(data.category):
                raise InvalidProduct(f"unknown category {data.category}")
            if await uow.products.slug_taken(slug):
                raise DuplicateSlug(slug)
            try:
                product = Product(
                    id=uuid4(),
                    slug=slug,
                    name=data.name,
                    description=data.description,
                    price_cents=data.price_cents,
                    currency=DEFAULT_CURRENCY,
                    category=data.category,
                    image_url=data.image_url,
                    rating=Decimal(0),
                    reviews_count=0,
                    tags=data.tags,
                    merchant=merchant,
                    created_at=datetime.now(UTC),
                )
            except ValueError as error:
                raise InvalidProduct(str(error)) from error
            await uow.products.add(product)
            await uow.outbox.add(
                [
                    ProductCreated(
                        product_id=product.id,
                        merchant_id=merchant.id,
                        slug=product.slug,
                        name=product.name,
                        category=product.category,
                        price_cents=product.price_cents,
                        currency=product.currency,
                    )
                ]
            )
            await uow.commit()
        return product

    async def update(
        self, principal: Principal, product_id: UUID, changes: Mapping[str, Any]
    ) -> Product:
        async with self._uow_factory() as uow:
            product = await uow.products.get(product_id)
            if product is None or not product.active:
                raise ProductNotFound(str(product_id))
            if not _may_manage(principal, product.merchant.id):
                raise NotProductOwner(str(product_id))
            if "category" in changes and not await uow.products.category_exists(
                str(changes["category"])
            ):
                raise InvalidProduct(f"unknown category {changes['category']}")
            try:
                updated, events = apply_changes(product, changes)
            except ValueError as error:
                raise InvalidProduct(str(error)) from error
            if events:
                await uow.products.save(updated)
                await uow.outbox.add(events)
                await uow.commit()
        return updated

    async def deactivate(self, principal: Principal, product_id: UUID) -> None:
        async with self._uow_factory() as uow:
            product = await uow.products.get(product_id)
            if product is None:
                raise ProductNotFound(str(product_id))
            if not _may_manage(principal, product.merchant.id):
                raise NotProductOwner(str(product_id))
            if not product.active:
                return
            await uow.products.save(replace(product, active=False))
            await uow.outbox.add(
                [ProductDeactivated(product_id=product.id, merchant_id=product.merchant.id)]
            )
            await uow.commit()

    async def reactivate(self, principal: Principal, product_id: UUID) -> Product:
        async with self._uow_factory() as uow:
            product = await uow.products.get(product_id)
            if product is None:
                raise ProductNotFound(str(product_id))
            if not _may_manage(principal, product.merchant.id):
                raise NotProductOwner(str(product_id))
            if product.active:
                return product
            reactivated = replace(product, active=True)
            await uow.products.save(reactivated)
            await uow.outbox.add(
                [
                    ProductCreated(
                        product_id=product.id,
                        merchant_id=product.merchant.id,
                        slug=product.slug,
                        name=product.name,
                        category=product.category,
                        price_cents=product.price_cents,
                        currency=product.currency,
                    )
                ]
            )
            await uow.commit()
        return reactivated
