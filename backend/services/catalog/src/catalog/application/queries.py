from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from catalog.application.ports import ReaderFactory
from catalog.domain.errors import InvalidQuery, ProductNotFound
from catalog.domain.pagination import Page
from catalog.domain.product import Category, Product, ProductQuery

MAX_BY_IDS = 100


class SearchProducts:
    def __init__(self, reader_factory: ReaderFactory) -> None:
        self._reader_factory = reader_factory

    async def execute(self, query: ProductQuery) -> Page[Product]:
        async with self._reader_factory() as reader:
            return await reader.search(query)


class GetProduct:
    def __init__(self, reader_factory: ReaderFactory) -> None:
        self._reader_factory = reader_factory

    async def by_id(self, product_id: UUID) -> Product:
        async with self._reader_factory() as reader:
            product = await reader.get(product_id)
        if product is None:
            raise ProductNotFound(f"product {product_id} not found")
        return product

    async def by_slug(self, slug: str) -> Product:
        async with self._reader_factory() as reader:
            product = await reader.get_by_slug(slug)
        if product is None:
            raise ProductNotFound(f"product {slug} not found")
        return product


class GetProductsByIds:
    def __init__(self, reader_factory: ReaderFactory) -> None:
        self._reader_factory = reader_factory

    async def execute(self, product_ids: Sequence[UUID]) -> list[Product]:
        unique = list(dict.fromkeys(product_ids))
        if not unique:
            raise InvalidQuery("ids is required")
        if len(unique) > MAX_BY_IDS:
            raise InvalidQuery(f"ids cannot exceed {MAX_BY_IDS} items")
        async with self._reader_factory() as reader:
            return await reader.get_many(unique)


class ListCategories:
    def __init__(self, reader_factory: ReaderFactory) -> None:
        self._reader_factory = reader_factory

    async def execute(self) -> list[Category]:
        async with self._reader_factory() as reader:
            return await reader.categories()
