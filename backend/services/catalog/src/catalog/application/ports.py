from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from catalog.domain.pagination import Page
from catalog.domain.product import Category, Product, ProductQuery


class CatalogReader(Protocol):
    async def search(self, query: ProductQuery) -> Page[Product]: ...

    async def get(self, product_id: UUID) -> Product | None: ...

    async def get_by_slug(self, slug: str) -> Product | None: ...

    async def get_many(self, product_ids: Sequence[UUID]) -> list[Product]: ...

    async def categories(self) -> list[Category]: ...


ReaderFactory = Callable[[], AbstractAsyncContextManager[CatalogReader]]
