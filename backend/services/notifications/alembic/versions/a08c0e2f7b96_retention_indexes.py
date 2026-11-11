"""retention indexes

Revision ID: a08c0e2f7b96
Revises: 53673f566f4f
Create Date: 2026-11-11 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a08c0e2f7b96"
down_revision: str | Sequence[str] | None = "53673f566f4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_inbox_processed_at", "inbox_messages", ["processed_at"])


def downgrade() -> None:
    op.drop_index("ix_inbox_processed_at", table_name="inbox_messages")
