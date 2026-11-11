"""retention indexes

Revision ID: 9c4e6a8b3d52
Revises: 8b2d4f6a1c30
Create Date: 2026-11-11 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c4e6a8b3d52"
down_revision: str | Sequence[str] | None = "8b2d4f6a1c30"
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
    op.create_index("ix_idempotency_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_created_at", table_name="idempotency_keys")
    op.drop_index("ix_inbox_processed_at", table_name="inbox_messages")
    op.drop_index("ix_outbox_published_at", table_name="outbox_events")
