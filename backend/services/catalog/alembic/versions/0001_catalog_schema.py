"""catalog schema with trigram search

Revision ID: 0001
Revises:
Create Date: 2026-11-11 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        "CREATE FUNCTION catalog_unaccent(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE "
        "AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$"
    )
    op.execute(
        "CREATE FUNCTION catalog_join_tags(text[]) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE "
        "AS $$ SELECT array_to_string($1, ' ') $$"
    )

    op.create_table(
        "merchants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
    )
    op.create_table(
        "categories",
        sa.Column("slug", sa.String(80), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("category_slug", sa.String(80), sa.ForeignKey("categories.slug"), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("rating", sa.Numeric(2, 1), nullable=False, server_default="0"),
        sa.Column("reviews_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(60)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "name_search",
            sa.Text(),
            sa.Computed("lower(catalog_unaccent(name))", persisted=True),
        ),
        sa.Column(
            "description_search",
            sa.Text(),
            sa.Computed("lower(catalog_unaccent(description))", persisted=True),
        ),
        sa.Column(
            "tags_search",
            sa.Text(),
            sa.Computed("lower(catalog_unaccent(catalog_join_tags(tags)))", persisted=True),
        ),
        sa.CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
        sa.CheckConstraint("rating >= 0 and rating <= 5", name="ck_products_rating_range"),
        sa.CheckConstraint("reviews_count >= 0", name="ck_products_reviews_non_negative"),
    )
    op.create_index("ix_products_category_price", "products", ["category_slug", "price_cents"])
    op.create_index("ix_products_price", "products", ["price_cents"])
    op.create_index("ix_products_created_at", "products", ["created_at"])
    op.create_index("ix_products_rating", "products", ["rating", "reviews_count"])
    op.create_index("ix_products_merchant", "products", ["merchant_id"])
    for column in ("name", "description", "tags"):
        op.create_index(
            f"ix_products_{column}_trgm",
            "products",
            [f"{column}_search"],
            postgresql_using="gin",
            postgresql_ops={f"{column}_search": "gin_trgm_ops"},
        )


def downgrade() -> None:
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("merchants")
    op.execute("DROP FUNCTION catalog_join_tags(text[])")
    op.execute("DROP FUNCTION catalog_unaccent(text)")
