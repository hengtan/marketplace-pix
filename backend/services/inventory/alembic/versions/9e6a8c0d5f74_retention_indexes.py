"""retention indexes

Revision ID: 9e6a8c0d5f74
Revises: 8c3e5a7b2d41
Create Date: 2026-11-11 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e6a8c0d5f74"
down_revision: str | Sequence[str] | None = "8c3e5a7b2d41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_outbox_published_at",
        "outbox_events",
        ["published_at"],
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )
    op.create_index("ix_inbox_processed_at", "inbox_messages", ["processed_at"])


def downgrade() -> None:
    op.drop_index("ix_inbox_processed_at", table_name="inbox_messages")
    op.drop_index("ix_outbox_published_at", table_name="outbox_events")
