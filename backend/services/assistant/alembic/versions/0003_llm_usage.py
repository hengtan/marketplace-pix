"""token and cost usage per session and per user

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE llm_usage (
            scope text NOT NULL,
            key text NOT NULL,
            period text NOT NULL,
            tokens bigint NOT NULL DEFAULT 0,
            cost_micro_usd bigint NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (scope, key, period)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE llm_usage")
