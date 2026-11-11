"""outbox traceparent

Revision ID: 7a1c3d5e9b21
Revises: b3675c3003ff
Create Date: 2026-11-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7a1c3d5e9b21"
down_revision: str | Sequence[str] | None = "b3675c3003ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("traceparent", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox_events", "traceparent")
