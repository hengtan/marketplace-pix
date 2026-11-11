"""stock merchant owner

Revision ID: 8c3e5a7b2d41
Revises: 7a1c3d5e9b22
Create Date: 2026-11-11 13:10:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "8c3e5a7b2d41"
down_revision: str | Sequence[str] | None = "7a1c3d5e9b22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDED = {
    "aurora-tech": [
        "fone-bluetooth-nova",
        "caixa-som-pulse",
        "smartwatch-orbit",
        "teclado-mecanico-forge",
        "mouse-glide-pro",
        "webcam-clear-4k",
        "carregador-turbo-65w",
        "hub-usbc-dock",
    ],
    "casa-lume": [
        "luminaria-arco-dourado",
        "cafeteira-prensa-francesa",
        "vaso-ceramica-terra",
        "manta-algodao-nuvem",
        "jogo-facas-chef",
        "difusor-aromas-calma",
        "relogio-parede-minimal",
        "organizador-bambu-set",
    ],
    "trilha-sports": [
        "tenis-corrida-vento",
        "mochila-trilha-30l",
        "garrafa-termica-aco-750",
        "tapete-yoga-grip",
        "relogio-gps-trail",
        "capacete-bike-aero",
        "corda-pular-speed",
        "kit-elasticos-forca",
    ],
}


def upgrade() -> None:
    op.add_column("stock", sa.Column("merchant_id", sa.Uuid(), nullable=True))
    op.create_index("ix_stock_merchant_id", "stock", ["merchant_id"])
    stock = sa.table(
        "stock", sa.column("product_id", sa.Uuid()), sa.column("merchant_id", sa.Uuid())
    )
    for merchant_slug, products in SEEDED.items():
        merchant_id = uuid5(NAMESPACE_URL, f"marketplace-pix:merchant:{merchant_slug}")
        ids = [uuid5(NAMESPACE_URL, f"marketplace-pix:product:{slug}") for slug in products]
        op.execute(
            stock.update().where(stock.c.product_id.in_(ids)).values(merchant_id=merchant_id)
        )


def downgrade() -> None:
    op.drop_index("ix_stock_merchant_id", table_name="stock")
    op.drop_column("stock", "merchant_id")
