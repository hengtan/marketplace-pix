import json
import uuid
from pathlib import Path
from uuid import UUID

from assistant.application.ports import OrderInfo, StockInfo
from assistant.domain.models import CatalogProduct
from assistant.infrastructure.http.gateways import parse_product

LOW_STOCK = {"relogio-gps-trail": 3, "smartwatch-orbit": 5}
DEFAULT_STOCK = 25


def product_uuid(slug: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"marketplace-pix:product:{slug}")


class SnapshotCatalogGateway:
    """Catalog served from a JSON snapshot, for reproducible runs without the real service."""

    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._products = [parse_product(item) for item in raw["items"]]
        self.labels = {
            "tecnologia": "Tecnologia",
            "casa": "Casa e decoração",
            "esporte": "Esporte e aventura",
        }

    async def list_products(self) -> list[CatalogProduct]:
        return list(self._products)

    async def get_product(self, product_id: UUID) -> CatalogProduct | None:
        return next((p for p in self._products if p.id == product_id), None)

    async def categories(self) -> dict[str, str]:
        return dict(self.labels)


class FixtureInventoryGateway:
    def __init__(self, products: list[CatalogProduct]) -> None:
        self._stock = {p.id: LOW_STOCK.get(p.slug, DEFAULT_STOCK) for p in products}

    async def get_stock(self, product_id: UUID) -> StockInfo | None:
        available = self._stock.get(product_id)
        return None if available is None else StockInfo(product_id, available, 0)


class EmptyOrderGateway:
    async def get_order(self, order_id: UUID) -> OrderInfo | None:
        return None
