from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx

from ordering.application.errors import CatalogUnavailable
from ordering.application.ports import CatalogProduct


class HttpCatalogGateway:
    def __init__(
        self,
        base_url: str,
        timeout: float = 3.0,
        attempts: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        self._attempts = attempts

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_products(self, ids: list[UUID]) -> list[CatalogProduct]:
        params = {"ids": ",".join(str(i) for i in ids)}
        last_error: Exception | None = None
        for attempt in range(self._attempts):
            try:
                response = await self._client.get("/products/by-ids", params=params)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "catalog error", request=response.request, response=response
                    )
                response.raise_for_status()
                payload = response.json()
                raw_items = payload["items"] if isinstance(payload, dict) else payload
                return [_to_product(raw) for raw in raw_items]
            except (httpx.HTTPError, ValueError, KeyError) as error:
                last_error = error
                if attempt + 1 < self._attempts:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise CatalogUnavailable(str(last_error)) from last_error


def _to_product(raw: dict[str, Any]) -> CatalogProduct:
    return CatalogProduct(
        id=UUID(raw["id"]),
        name=raw["name"],
        price_cents=int(raw["price_cents"]),
        currency=raw["currency"],
        merchant_id=UUID(raw["merchant"]["id"]),
    )
