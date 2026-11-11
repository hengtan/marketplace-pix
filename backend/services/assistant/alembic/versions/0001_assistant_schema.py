"""assistant schema: chunks (pgvector), sessions, messages, eval_runs

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from assistant.config import load_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    dimension = load_settings().embedding_dim
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE FUNCTION f_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$
        """
    )
    op.execute(
        f"""
        CREATE TABLE chunks (
            id text PRIMARY KEY,
            product_id uuid NOT NULL,
            chunk_index integer NOT NULL,
            content text NOT NULL,
            content_hash text NOT NULL,
            embedding vector({dimension}) NOT NULL,
            metadata jsonb NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', f_unaccent(content))) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")
    op.execute("CREATE INDEX ix_chunks_product_id ON chunks (product_id)")
    op.execute("CREATE INDEX ix_chunks_metadata ON chunks USING gin (metadata jsonb_path_ops)")

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_messages_session_id_id", "messages", ["session_id", "id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("embedder", sa.String(100), nullable=False),
        sa.Column("llm", sa.String(100), nullable=False),
        sa.Column("cases_count", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("cases", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_eval_runs_created_at", "eval_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.execute("DROP TABLE chunks")
    op.execute("DROP FUNCTION f_unaccent(text)")
