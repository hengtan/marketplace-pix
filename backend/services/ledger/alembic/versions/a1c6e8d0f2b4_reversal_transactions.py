"""transaction kind for refund reversals

Revision ID: a1c6e8d0f2b4
Revises: 9f7b9d1e6a85
Create Date: 2026-11-11 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c6e8d0f2b4"
down_revision: str | Sequence[str] | None = "9f7b9d1e6a85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledger_transactions",
        sa.Column("kind", sa.String(length=10), server_default="PAYMENT", nullable=False),
    )
    op.drop_constraint("ledger_transactions_order_id_key", "ledger_transactions", type_="unique")
    op.drop_constraint("ledger_transactions_payment_id_key", "ledger_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_ledger_transactions_order_kind", "ledger_transactions", ["order_id", "kind"]
    )
    op.create_unique_constraint(
        "uq_ledger_transactions_payment_kind", "ledger_transactions", ["payment_id", "kind"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_ledger_transactions_payment_kind", "ledger_transactions", type_="unique")
    op.drop_constraint("uq_ledger_transactions_order_kind", "ledger_transactions", type_="unique")
    op.create_unique_constraint(
        "ledger_transactions_payment_id_key", "ledger_transactions", ["payment_id"]
    )
    op.create_unique_constraint(
        "ledger_transactions_order_id_key", "ledger_transactions", ["order_id"]
    )
    op.drop_column("ledger_transactions", "kind")
