from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class OwnProductOut(ProductOut):
    active: bool

    @classmethod
    def from_owned(cls, product: Product) -> OwnProductOut:
        return cls(**ProductOut.from_domain(product).model_dump(), active=product.active)


class OwnProductListOut(BaseModel):
    items: list[OwnProductOut]


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


class ProductCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=4000)
    price_cents: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=80)
    slug: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    image_url: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)
    merchant_id: UUID | None = None


class ProductPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    price_cents: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=20)
