from sqlalchemy import func, select

from catalog.infrastructure.db.models import CategoryModel, MerchantModel, ProductModel
from catalog.seed import run_seed
from catalog.seed_data import merchant_id, product_id


async def _counts(factory):
    async with factory() as session:
        products = await session.scalar(select(func.count()).select_from(ProductModel))
        merchants = await session.scalar(select(func.count()).select_from(MerchantModel))
        categories = await session.scalar(select(func.count()).select_from(CategoryModel))
    return products, merchants, categories


async def test_seed_creates_contract_data(seeded) -> None:
    assert await _counts(seeded) == (24, 3, 3)


async def test_seed_twice_keeps_same_counts(seeded) -> None:
    await run_seed(seeded)
    await run_seed(seeded)
    assert await _counts(seeded) == (24, 3, 3)


async def test_seed_ids_follow_contract(seeded) -> None:
    async with seeded() as session:
        product = await session.get(ProductModel, product_id("fone-bluetooth-nova"))
        merchant = await session.get(MerchantModel, merchant_id("aurora-tech"))
    assert product is not None
    assert product.price_cents == 34990
    assert product.merchant_id == merchant_id("aurora-tech")
    assert merchant is not None
    assert merchant.name == "Aurora Tech"


async def test_seed_values_are_plausible(seeded) -> None:
    async with seeded() as session:
        rows = (await session.scalars(select(ProductModel))).unique().all()
    assert all(4.1 <= float(row.rating) <= 4.9 for row in rows)
    assert all(row.reviews_count > 0 and row.tags and len(row.description) > 80 for row in rows)
    assert all("—" not in row.description and "–" not in row.description for row in rows)
    assert all(row.image_url is None or row.image_url.startswith("https://") for row in rows)
