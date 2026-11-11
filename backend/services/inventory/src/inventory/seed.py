from __future__ import annotations

import asyncio
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inventory.config import load_settings
from inventory.infrastructure.db.models import StockModel
from inventory.infrastructure.db.session import build_engine, build_session_factory

PRODUCT_SLUGS = [
    "fone-bluetooth-nova",
    "caixa-som-pulse",
    "smartwatch-orbit",
    "teclado-mecanico-forge",
    "mouse-glide-pro",
    "webcam-clear-4k",
    "carregador-turbo-65w",
    "hub-usbc-dock",
    "luminaria-arco-dourado",
    "cafeteira-prensa-francesa",
    "vaso-ceramica-terra",
    "manta-algodao-nuvem",
    "jogo-facas-chef",
    "difusor-aromas-calma",
    "relogio-parede-minimal",
    "organizador-bambu-set",
    "tenis-corrida-vento",
    "mochila-trilha-30l",
    "garrafa-termica-aco-750",
    "tapete-yoga-grip",
    "relogio-gps-trail",
    "capacete-bike-aero",
    "corda-pular-speed",
    "kit-elasticos-forca",
]

DEFAULT_QUANTITY = 25
QUANTITY_OVERRIDES = {"relogio-gps-trail": 3, "smartwatch-orbit": 5}


def product_id_for(slug: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:product:{slug}")


def initial_stock() -> dict[UUID, int]:
    return {
        product_id_for(slug): QUANTITY_OVERRIDES.get(slug, DEFAULT_QUANTITY)
        for slug in PRODUCT_SLUGS
    }


async def seed(session_factory: async_sessionmaker[AsyncSession]) -> int:
    rows = [
        {"product_id": product_id, "available": quantity, "reserved": 0}
        for product_id, quantity in initial_stock().items()
    ]
    async with session_factory() as session:
        result = await session.execute(
            insert(StockModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["product_id"])
            .returning(StockModel.product_id)
        )
        created = len(result.all())
        await session.commit()
    return created


async def main() -> None:
    engine = build_engine(load_settings().database_url)
    try:
        created = await seed(build_session_factory(engine))
    finally:
        await engine.dispose()
    print(f"inventory seed: {created} new, {len(PRODUCT_SLUGS) - created} already present")


if __name__ == "__main__":
    asyncio.run(main())
