from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MerchantModel(Base):
    __tablename__ = "merchants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class CategoryModel(Base):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))


class ProductModel(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default="BRL")
    category_slug: Mapped[str] = mapped_column(ForeignKey("categories.slug"))
    merchant_id: Mapped[UUID] = mapped_column(ForeignKey("merchants.id"))
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), server_default="0")
    reviews_count: Mapped[int] = mapped_column(Integer, server_default="0")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    name_search: Mapped[str] = mapped_column(
        Text, Computed("lower(catalog_unaccent(name))", persisted=True)
    )
    description_search: Mapped[str] = mapped_column(
        Text, Computed("lower(catalog_unaccent(description))", persisted=True)
    )
    tags_search: Mapped[str] = mapped_column(
        Text, Computed("lower(catalog_unaccent(catalog_join_tags(tags)))", persisted=True)
    )

    merchant: Mapped[MerchantModel] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
        CheckConstraint("rating >= 0 and rating <= 5", name="ck_products_rating_range"),
        CheckConstraint("reviews_count >= 0", name="ck_products_reviews_non_negative"),
        Index("ix_products_category_price", "category_slug", "price_cents"),
        Index("ix_products_price", "price_cents"),
        Index("ix_products_merchant", "merchant_id"),
        Index("ix_products_created_at", "created_at"),
        Index("ix_products_rating", "rating", "reviews_count"),
        Index(
            "ix_products_name_trgm",
            "name_search",
            postgresql_using="gin",
            postgresql_ops={"name_search": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_description_trgm",
            "description_search",
            postgresql_using="gin",
            postgresql_ops={"description_search": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_tags_trgm",
            "tags_search",
            postgresql_using="gin",
            postgresql_ops={"tags_search": "gin_trgm_ops"},
        ),
    )
