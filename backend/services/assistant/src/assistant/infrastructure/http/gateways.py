from typing import Any
from uuid import UUID

import httpx
from marketplace_common.security import sign_principal

from assistant.application.identity import current_identity
from assistant.application.ports import OrderInfo, StockInfo
from assistant.domain.errors import UpstreamUnavailable
from assistant.domain.models import CatalogProduct

PAGE_SIZE = 48


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    try:
        response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError:
        raise UpstreamUnavailable(f"request failed: {url.split('?')[0]}") from None
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise UpstreamUnavailable(f"upstream answered {response.status_code}")
    return response.json()


def parse_product(raw: dict[str, Any]) -> CatalogProduct:
    return CatalogProduct(
        id=UUID(raw["id"]),
        slug=raw["slug"],
        name=raw["name"],
        description=raw["description"],
        price_cents=int(raw["price_cents"]),
        category=raw["category"],
        rating=float(raw["rating"]),
        reviews_count=int(raw["reviews_count"]),
        tags=tuple(raw.get("tags") or ()),
        merchant_name=(raw.get("merchant") or {}).get("name", ""),
    )


class HttpCatalogGateway:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    async def list_products(self) -> list[CatalogProduct]:
        products: list[CatalogProduct] = []
        page = 1
        while True:
            body = await _get(
                self._client,
                f"{self._base}/products",
                {"page": page, "page_size": PAGE_SIZE, "sort": "newest"},
            )
            if body is None:
                raise UpstreamUnavailable("catalog products not available")
            products.extend(parse_product(item) for item in body["items"])
            if not body["items"] or len(products) >= body["total"]:
                return products
            page += 1

    async def get_product(self, product_id: UUID) -> CatalogProduct | None:
        body = await _get(self._client, f"{self._base}/products/{product_id}")
        return parse_product(body) if body else None

    async def categories(self) -> dict[str, str]:
        body = await _get(self._client, f"{self._base}/categories")
        return {item["slug"]: item["label"] for item in body or []}


class HttpInventoryGateway:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    async def get_stock(self, product_id: UUID) -> StockInfo | None:
        body = await _get(self._client, f"{self._base}/stock/{product_id}")
        if body is None:
            return None
        return StockInfo(product_id, int(body["available"]), int(body["reserved"]))


class HttpOrderGateway:
    """Consulta o pedido em nome de quem está no chat: repassa a identidade assinada do usuário
    autenticado, e o ordering decide pelo dono. Sem identidade, a chamada é anônima (convidado)."""

    def __init__(self, client: httpx.AsyncClient, base_url: str, internal_secret: str = "") -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._secret = internal_secret

    def _identity_headers(self) -> dict[str, str]:
        caller = current_identity()
        if caller is None:
            return {}
        headers = {"x-request-id": caller.request_id}
        if caller.principal is not None and self._secret:
            headers.update(sign_principal(self._secret, caller.principal, caller.request_id))
        return headers

    async def get_order(self, order_id: UUID) -> OrderInfo | None:
        body = await _get(
            self._client, f"{self._base}/orders/{order_id}", headers=self._identity_headers()
        )
        if body is None:
            return None
        return OrderInfo(
            order_id=order_id,
            status=str(body["status"]),
            total_cents=int(body["total_cents"]),
            currency=str(body["currency"]),
            items_count=sum(int(i["quantity"]) for i in body.get("items", [])),
            created_at=str(body.get("created_at") or ""),
            cancel_reason=body.get("cancel_reason"),
        )
