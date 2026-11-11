from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from catalog.domain.pagination import Page
from catalog.domain.product import Category, Product


class MerchantOut(BaseModel):
    id: UUID
    slug: str
    name: str


class ProductOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    price_cents: int
    currency: str
    category: str
    image_url: str | None
    rating: float
    reviews_count: int
    tags: list[str]
    merchant: MerchantOut
    created_at: datetime

    @classmethod
    def from_domain(cls, product: Product) -> ProductOut:
        return cls(
            id=product.id,
            slug=product.slug,
            name=product.name,
            description=product.description,
            price_cents=product.price_cents,
            currency=product.currency,
            category=product.category,
            image_url=product.image_url,
            rating=float(product.rating),
            reviews_count=product.reviews_count,
            tags=list(product.tags),
            merchant=MerchantOut(
                id=product.merchant.id, slug=product.merchant.slug, name=product.merchant.name
            ),
            created_at=product.created_at,
        )


class ProductPageOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_domain(cls, page: Page[Product]) -> ProductPageOut:
        return cls(
            items=[ProductOut.from_domain(p) for p in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )

    @classmethod
    def from_products(cls, products: list[Product]) -> ProductPageOut:
        return cls(
            items=[ProductOut.from_domain(p) for p in products],
            total=len(products),
            page=1,
            page_size=max(len(products), 1),
        )


class CategoryOut(BaseModel):
    slug: str
    label: str
    count: int

    @classmethod
    def from_domain(cls, category: Category) -> CategoryOut:
        return cls(slug=category.slug, label=category.label, count=category.count)
