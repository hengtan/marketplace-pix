"""stock active flag

Revision ID: a4d7f1c92b68
Revises: 9e6a8c0d5f74
Create Date: 2026-11-11 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4d7f1c92b68"
down_revision: str | Sequence[str] | None = "9e6a8c0d5f74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("stock", "active")
