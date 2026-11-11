from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.application.ports import CatalogReader, ReaderFactory
from catalog.domain.pagination import Page
from catalog.domain.product import Category, Merchant, Product, ProductQuery
from catalog.domain.sorting import SortOrder
from catalog.infrastructure.db.models import CategoryModel, ProductModel

NAME_WEIGHT = 4.0
DESCRIPTION_WEIGHT = 2.0
TAGS_WEIGHT = 1.0
TYPO_TOLERANCE = 0.55


def _escape_like(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _token_matches(token: str) -> ColumnElement[bool]:
    pattern = f"%{_escape_like(token)}%"
    return or_(
        ProductModel.name_search.like(pattern, escape="\\"),
        ProductModel.description_search.like(pattern, escape="\\"),
        ProductModel.tags_search.like(pattern, escape="\\"),
        func.word_similarity(token, ProductModel.name_search) >= TYPO_TOLERANCE,
    )


def relevance_score(search: str) -> ColumnElement[float]:
    return (
        func.word_similarity(search, ProductModel.name_search) * NAME_WEIGHT
        + func.word_similarity(search, ProductModel.description_search) * DESCRIPTION_WEIGHT
        + func.word_similarity(search, ProductModel.tags_search) * TAGS_WEIGHT
    )


def order_clauses(sort: SortOrder, search: str | None) -> list[ColumnElement[Any]]:
    tiebreak: list[ColumnElement[Any]] = [ProductModel.name.asc(), ProductModel.id.asc()]
    match sort:
        case SortOrder.PRICE_ASC:
            primary: list[ColumnElement[Any]] = [ProductModel.price_cents.asc()]
        case SortOrder.PRICE_DESC:
            primary = [ProductModel.price_cents.desc()]
        case SortOrder.NEWEST:
            primary = [ProductModel.created_at.desc()]
        case SortOrder.RATING:
            primary = [ProductModel.rating.desc(), ProductModel.reviews_count.desc()]
        case SortOrder.RELEVANCE if search is not None:
            primary = [relevance_score(search).desc(), ProductModel.reviews_count.desc()]
        case SortOrder.RELEVANCE:
            primary = [ProductModel.reviews_count.desc(), ProductModel.rating.desc()]
    return [*primary, *tiebreak]


def filter_conditions(query: ProductQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    search = query.normalized_search
    if search is not None:
        conditions.extend(_token_matches(token) for token in search.split())
    if query.category is not None:
        conditions.append(ProductModel.category_slug == query.category)
    if query.min_price_cents is not None:
        conditions.append(ProductModel.price_cents >= query.min_price_cents)
    if query.max_price_cents is not None:
        conditions.append(ProductModel.price_cents <= query.max_price_cents)
    return conditions


def to_domain(model: ProductModel) -> Product:
    return Product(
        id=model.id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        price_cents=model.price_cents,
        currency=model.currency,
        category=model.category_slug,
        image_url=model.image_url,
        rating=model.rating,
        reviews_count=model.reviews_count,
        tags=tuple(model.tags),
        merchant=Merchant(id=model.merchant.id, slug=model.merchant.slug, name=model.merchant.name),
        created_at=model.created_at,
    )


class SqlAlchemyCatalogReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, query: ProductQuery) -> Page[Product]:
        conditions = filter_conditions(query)
        total = await self._session.scalar(
            select(func.count()).select_from(ProductModel).where(*conditions)
        )
        stmt = (
            select(ProductModel)
            .where(*conditions)
            .order_by(*order_clauses(query.sort, query.normalized_search))
            .limit(query.page.page_size)
            .offset(query.page.offset)
        )
        rows = (await self._session.scalars(stmt)).unique().all()
        return Page(
            items=[to_domain(row) for row in rows],
            total=total or 0,
            page=query.page.page,
            page_size=query.page.page_size,
        )

    async def get(self, product_id: UUID) -> Product | None:
        model = await self._session.get(ProductModel, product_id)
        return to_domain(model) if model else None

    async def get_by_slug(self, slug: str) -> Product | None:
        model = await self._session.scalar(select(ProductModel).where(ProductModel.slug == slug))
        return to_domain(model) if model else None

    async def get_many(self, product_ids: Sequence[UUID]) -> list[Product]:
        rows = (
            (
                await self._session.scalars(
                    select(ProductModel).where(ProductModel.id.in_(product_ids))
                )
            )
            .unique()
            .all()
        )
        by_id = {row.id: to_domain(row) for row in rows}
        return [by_id[pid] for pid in product_ids if pid in by_id]

    async def categories(self) -> list[Category]:
        stmt = (
            select(CategoryModel.slug, CategoryModel.label, func.count(ProductModel.id))
            .outerjoin(ProductModel, ProductModel.category_slug == CategoryModel.slug)
            .group_by(CategoryModel.slug, CategoryModel.label)
            .order_by(CategoryModel.label)
        )
        rows = (await self._session.execute(stmt)).all()
        return [Category(slug=slug, label=label, count=count) for slug, label, count in rows]


def build_reader_factory(factory: async_sessionmaker[AsyncSession]) -> ReaderFactory:
    @asynccontextmanager
    async def open_reader() -> AsyncIterator[CatalogReader]:
        async with factory() as session:
            yield SqlAlchemyCatalogReader(session)

    return open_reader
