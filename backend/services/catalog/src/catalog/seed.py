from __future__ import annotations

import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.config import load_settings
from catalog.infrastructure.db.models import CategoryModel, MerchantModel, ProductModel
from catalog.infrastructure.db.session import build_engine, build_session_factory
from catalog.seed_data import (
    CATEGORIES,
    CREATED_AT,
    MERCHANTS,
    PRODUCTS,
    merchant_id,
    product_id,
)


async def seed_catalog(session: AsyncSession) -> int:
    for slug, label in CATEGORIES:
        stmt = insert(CategoryModel).values(slug=slug, label=label)
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["slug"], set_={"label": stmt.excluded.label})
        )
    for merchant in MERCHANTS:
        stmt = insert(MerchantModel).values(
            id=merchant_id(merchant.slug), slug=merchant.slug, name=merchant.name
        )
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["id"], set_={"name": stmt.excluded.name})
        )
    for product in PRODUCTS:
        values = {
            "id": product_id(product.slug),
            "slug": product.slug,
            "name": product.name,
            "description": product.description,
            "price_cents": product.price_cents,
            "currency": "BRL",
            "category_slug": product.category,
            "merchant_id": merchant_id(product.merchant),
            "image_url": product.image_url,
            "rating": product.rating,
            "reviews_count": product.reviews_count,
            "tags": list(product.tags),
            "created_at": CREATED_AT[product.slug],
        }
        await session.execute(
            insert(ProductModel).values(**values).on_conflict_do_nothing(index_elements=["id"])
        )
    await session.commit()
    return len(PRODUCTS)


async def run_seed(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return await seed_catalog(session)


async def main() -> None:
    engine = build_engine(load_settings().database_url)
    try:
        count = await run_seed(build_session_factory(engine))
    finally:
        await engine.dispose()
    print(f"catalog seeded: {count} products")


if __name__ == "__main__":
    asyncio.run(main())
