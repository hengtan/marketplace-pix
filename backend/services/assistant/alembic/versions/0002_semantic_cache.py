"""semantic cache of answers

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11
"""

from alembic import op
from assistant.config import load_settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dimension = load_settings().embedding_dim
    op.execute(
        f"""
        CREATE TABLE semantic_cache (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            embedder text NOT NULL,
            filter_key text NOT NULL,
            intent text NOT NULL,
            query_text text NOT NULL,
            embedding vector({dimension}) NOT NULL,
            payload jsonb NOT NULL,
            product_ids uuid[] NOT NULL,
            volatile boolean NOT NULL,
            tokens_saved integer NOT NULL,
            hits integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_semantic_cache_embedding_hnsw ON semantic_cache "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_semantic_cache_products ON semantic_cache USING gin (product_ids)")
    op.execute("CREATE INDEX ix_semantic_cache_expires ON semantic_cache (expires_at)")
    op.execute("CREATE INDEX ix_semantic_cache_key ON semantic_cache (embedder, filter_key)")


def downgrade() -> None:
    op.execute("DROP TABLE semantic_cache")
