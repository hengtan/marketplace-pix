"""order owner and merchant item index

Revision ID: 8b2d4f6a1c30
Revises: 7a1c3d5e9b20
Create Date: 2026-11-11 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b2d4f6a1c30"
down_revision: str | Sequence[str] | None = "7a1c3d5e9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_orders_owner_id", "orders", ["owner_id"])
    op.create_index("ix_order_items_merchant_id", "order_items", ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_merchant_id", table_name="order_items")
    op.drop_index("ix_orders_owner_id", table_name="orders")
    op.drop_column("orders", "owner_id")
