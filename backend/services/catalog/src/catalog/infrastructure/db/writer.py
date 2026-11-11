from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog.domain.product import Merchant, Product
from catalog.infrastructure.db.models import CategoryModel, MerchantModel, ProductModel
from catalog.infrastructure.db.repository import to_domain


class SqlAlchemyProductWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, product_id: UUID) -> Product | None:
        model = await self._session.scalar(
            select(ProductModel)
            .where(ProductModel.id == product_id)
            .with_for_update(of=ProductModel)
        )
        return to_domain(model) if model else None

    async def slug_taken(self, slug: str) -> bool:
        return (
            await self._session.scalar(select(ProductModel.id).where(ProductModel.slug == slug))
            is not None
        )

    async def category_exists(self, slug: str) -> bool:
        return (
            await self._session.scalar(select(CategoryModel.slug).where(CategoryModel.slug == slug))
            is not None
        )

    async def merchant(self, merchant_id: UUID) -> Merchant | None:
        model = await self._session.get(MerchantModel, merchant_id)
        return Merchant(model.id, model.slug, model.name) if model else None

    async def add(self, product: Product) -> None:
        self._session.add(
            ProductModel(
                id=product.id,
                slug=product.slug,
                name=product.name,
                description=product.description,
                price_cents=product.price_cents,
                currency=product.currency,
                category_slug=product.category,
                merchant_id=product.merchant.id,
                image_url=product.image_url,
                rating=product.rating,
                reviews_count=product.reviews_count,
                tags=list(product.tags),
                created_at=product.created_at,
                active=product.active,
            )
        )
        await self._session.flush()

    async def save(self, product: Product) -> None:
        model = await self._session.get(ProductModel, product.id)
        assert model is not None
        model.name = product.name
        model.description = product.description
        model.price_cents = product.price_cents
        model.category_slug = product.category
        model.image_url = product.image_url
        model.tags = list(product.tags)
        model.active = product.active
        await self._session.flush()
