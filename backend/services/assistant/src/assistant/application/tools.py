from typing import Any
from uuid import UUID

from assistant.application.ports import (
    CatalogGateway,
    InventoryGateway,
    OrderGateway,
    ToolResult,
)
from assistant.application.retrieval import HybridRetriever
from assistant.domain.errors import ToolError, UpstreamUnavailable
from assistant.domain.models import Filters
from assistant.domain.text import format_brl


def _uuid(arguments: dict[str, Any], key: str) -> UUID:
    try:
        return UUID(str(arguments[key]))
    except (KeyError, ValueError):
        raise ToolError(f"argument {key} must be a uuid") from None


class SearchProductsTool:
    name = "search_products"

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolError("argument query is required")
        restrict = None
        if arguments.get("product_ids"):
            restrict = Filters(product_ids=tuple(UUID(str(p)) for p in arguments["product_ids"]))
        result = await self._retriever.retrieve(query, restrict)
        passages = tuple(result.passages)
        data: dict[str, Any] = {
            "filters": result.filters.to_dict(),
            "mode": result.mode,
            "count": len(passages),
            "products": [
                {
                    "product_id": str(p.product_id),
                    "slug": p.slug,
                    "name": p.name,
                    "price_cents": p.price_cents,
                    "rating": p.rating,
                    "score": p.score,
                }
                for p in passages
            ],
        }
        if not passages:
            return ToolResult("Nenhum produto encontrado.", data, passages)
        listing = "; ".join(f"{p.name} ({format_brl(p.price_cents)})" for p in passages)
        return ToolResult(f"{len(passages)} produtos encontrados: {listing}.", data, passages)


class GetStockTool:
    name = "get_stock"

    def __init__(self, inventory: InventoryGateway, catalog: CatalogGateway) -> None:
        self._inventory = inventory
        self._catalog = catalog

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        product_id = _uuid(arguments, "product_id")
        name = str(arguments.get("name") or "")
        try:
            stock = await self._inventory.get_stock(product_id)
            if not name:
                product = await self._catalog.get_product(product_id)
                name = product.name if product else "o produto"
        except UpstreamUnavailable:
            return ToolResult(
                "Não consegui consultar o estoque agora. Tente novamente em instantes.",
                {"product_id": str(product_id)},
                ok=False,
            )
        if stock is None:
            return ToolResult(
                f"Não há registro de estoque para {name or 'o produto'}.",
                {"product_id": str(product_id)},
                ok=False,
            )
        data = {
            "product_id": str(product_id),
            "name": name,
            "available": stock.available,
            "reserved": stock.reserved,
        }
        return ToolResult(f"{name}: {stock.available} unidades disponíveis.", data)


class GetOrderStatusTool:
    name = "get_order_status"

    def __init__(self, orders: OrderGateway) -> None:
        self._orders = orders

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        order_id = _uuid(arguments, "order_id")
        try:
            order = await self._orders.get_order(order_id)
        except UpstreamUnavailable:
            return ToolResult(
                "Não consegui consultar o pedido agora. Tente novamente em instantes.",
                {"order_id": str(order_id)},
                ok=False,
            )
        if order is None:
            return ToolResult(
                "Não encontrei nenhum pedido com esse código.",
                {"order_id": str(order_id)},
                ok=False,
            )
        data = {
            "order_id": str(order.order_id),
            "status": order.status,
            "total_cents": order.total_cents,
            "items_count": order.items_count,
            "created_at": order.created_at,
            "cancel_reason": order.cancel_reason,
        }
        short_id = str(order.order_id)[:8]
        summary = f"Pedido {short_id}: {order.status}, {format_brl(order.total_cents)}."
        return ToolResult(summary, data)
