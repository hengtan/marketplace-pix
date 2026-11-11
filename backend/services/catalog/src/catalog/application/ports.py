from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from catalog.domain.events import DomainEvent
from catalog.domain.pagination import Page
from catalog.domain.product import Category, Merchant, Product, ProductQuery


class CatalogReader(Protocol):
    async def search(self, query: ProductQuery) -> Page[Product]: ...

    async def get(self, product_id: UUID) -> Product | None: ...

    async def get_by_slug(self, slug: str) -> Product | None: ...

    async def get_many(self, product_ids: Sequence[UUID]) -> list[Product]: ...

    async def categories(self) -> list[Category]: ...


ReaderFactory = Callable[[], AbstractAsyncContextManager[CatalogReader]]


class ProductWriter(Protocol):
    async def get(self, product_id: UUID) -> Product | None: ...

    async def list_by_merchant(self, merchant_id: UUID) -> list[Product]: ...

    async def slug_taken(self, slug: str) -> bool: ...

    async def category_exists(self, slug: str) -> bool: ...

    async def merchant(self, merchant_id: UUID) -> Merchant | None: ...

    async def add(self, product: Product) -> None: ...

    async def save(self, product: Product) -> None: ...


class Outbox(Protocol):
    async def add(self, events: list[DomainEvent]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def products(self) -> ProductWriter: ...

    @property
    def outbox(self) -> Outbox: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


UowFactory = Callable[[], UnitOfWork]
